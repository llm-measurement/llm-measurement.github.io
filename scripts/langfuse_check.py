# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Verify the current Langfuse guide independently of the older release-cache lane."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

from outsider import Blocks, ROOT, normalize


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def blocks(root=ROOT):
    parsed = Blocks()
    parsed.feed((root / 'pages/langfuse-spend.html').read_text())
    assert len(parsed.commands) == 1 and parsed.expected
    assert [b['id'] for b in parsed.own] == ['langfuse-install', 'langfuse-own', 'langfuse-short']
    return parsed


def environment(fresh):
    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SYSTEMROOT'}}
    env.update(HOME=str(fresh), GH_CONFIG_DIR=str(fresh / 'gh'), XDG_CONFIG_HOME=str(fresh / 'config'),
               XDG_CACHE_HOME=str(fresh / 'cache'), TMPDIR=str(fresh), GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0', GOMAXPROCS='1',
               GOENV='off', GOTOOLCHAIN='local', GOPROXY='off', GOSUMDB='off', GOTELEMETRY='off')
    return env


def execute(block, fresh, output, name):
    result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', block['text']], cwd=fresh,
                            env=environment(fresh), text=True, capture_output=True, timeout=1800)
    (output / (name + '.stdout')).write_text(result.stdout)
    (output / (name + '.stderr')).write_text(result.stderr)
    assert result.returncode == block['exit'], (name, result.stderr[-3000:])
    return {'page': 'langfuse-spend', 'exit': result.returncode, 'pass': True,
            'command_sha256': digest(block['text'].encode()), 'stdout_sha256': digest(result.stdout.encode()),
            'stdout': result.stdout, 'transport': 'fresh anonymous public downloads; no cache shim or credentials'}


def prepare_own(fresh, source):
    destination = fresh / 'langfuse-export/my-project'
    (destination / 'manifests').mkdir(parents=True)
    (destination / 'observations_v2').mkdir()
    original = source / 'examples/langfuse-spend/export/synthetic-langfuse'
    templates = [json.loads(line) for line in (original / 'observations_v2/2026-10-07T00-00-00.jsonl').read_text().splitlines()]
    manifest = json.loads((original / 'manifests/2026-10-07T01-00-00.json').read_text())
    for day in range(32):
        start = datetime(2026, 9, 20, tzinfo=timezone.utc) + timedelta(days=day)
        end = start + timedelta(days=1)
        date = start.date().isoformat()
        name = date + 'T00-00-00.jsonl'
        rows = []
        for index, template in enumerate(templates):
            row = dict(template, id=date + '-' + str(index))
            for field in ('start_time', 'end_time'):
                row[field] = date + template[field][10:]
            rows.append(row)
        raw = ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode()
        (destination / 'observations_v2' / name).write_bytes(raw)
        copied = json.loads(json.dumps(manifest))
        copied['window'] = {'minTimestamp': start.isoformat().replace('+00:00', 'Z'),
                            'maxTimestamp': end.isoformat().replace('+00:00', 'Z')}
        copied['maxTimestamp'] = copied['window']['maxTimestamp']
        copied['files'][0].update(key='synthetic-langfuse/observations_v2/' + name,
                                  sizeBytes=len(raw), rowCount=len(rows))
        (destination / 'manifests' / (date + '.json')).write_text(json.dumps(copied))


def check(output, root=ROOT):
    output.mkdir(parents=True, exist_ok=True)
    parsed = blocks(root)
    release = json.loads((root / 'evidence/langfuse-release.json').read_text())
    with tempfile.TemporaryDirectory(prefix='langfuse-sample-') as directory:
        fresh = Path(directory)
        sample = execute(parsed.commands[0], fresh, output, 'sample')
        assert 'Observation levels: DEFAULT 4 -> 6.' in sample['stdout']
        assert 'Records needing usage review' not in sample['stdout']
        for expected in parsed.expected:
            assert normalize(expected['text']) in normalize(sample['stdout']), expected['text']
        archive = fresh / 'langfuse-sample.tar.gz'
        assert digest(archive.read_bytes()) == release['sample_sha256']
        source = fresh / ('fleetdiff-' + release['commit'])
        version = subprocess.check_output([str(fresh / 'fleetdiff-install/fleetdiff'), '--version'],
                                          cwd=fresh, env=environment(fresh), text=True).strip()
        assert version.split()[:3] == ['fleetdiff', release['version'], '(' + release['commit'] + ')']
        own = []
        with tempfile.TemporaryDirectory(prefix='langfuse-own-') as owned:
            own_fresh = Path(owned)
            prepare_own(own_fresh, source)
            for block in parsed.own:
                record = execute(block, own_fresh, output, block['id'])
                record['block'] = block['id']
                if block['id'] != 'langfuse-install':
                    assert 'Logged model requests:' in record['stdout']
                    assert 'Observation levels: DEFAULT' in record['stdout']
                    assert 'Records needing usage review' not in record['stdout']
                own.append(record)
    result = {'checked_utc': datetime.now(timezone.utc).isoformat(), 'system': platform.system(),
              'machine': platform.machine(), 'release': release, 'installed_version': version,
              'method': 'Exact published sample and all own-data blocks; independent fresh HOME/directories; real public release checksum/attestation verification. Own fixture: 32 manifest-covered synthetic days derived from released rows. No provider or Langfuse API calls.',
              'sample': sample, 'own': own}
    (output / 'langfuse-verified.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def saved_verification(root=ROOT):
    record = json.loads((root / 'evidence/langfuse-verified.json').read_text())
    assert record['release'] == json.loads((root / 'evidence/langfuse-release.json').read_text())
    parsed = blocks(root)
    assert record['installed_version'].split()[:3] == ['fleetdiff', record['release']['version'], '(' + record['release']['commit'] + ')']
    assert [actual['block'] for actual in record['own']] == [expected['id'] for expected in parsed.own]
    for actual, expected in [(record['sample'], parsed.commands[0]), *zip(record['own'], parsed.own)]:
        assert actual['pass'] and actual['exit'] == expected['exit']
        assert actual['command_sha256'] == digest(expected['text'].encode())
        assert actual['stdout_sha256'] == digest(actual['stdout'].encode())
    assert len(record['own']) == len(parsed.own)
    assert 'Observation levels: DEFAULT 4 -> 6.' in record['sample']['stdout']
    for actual in [record['sample'], *record['own'][1:]]:
        assert 'Records needing usage review' not in actual['stdout']
    for expected in parsed.expected:
        assert normalize(expected['text']) in normalize(record['sample']['stdout'])
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check(args.output)
    print(json.dumps({'status': 'PASS', 'version': result['installed_version'], 'own_blocks': len(result['own'])}))
