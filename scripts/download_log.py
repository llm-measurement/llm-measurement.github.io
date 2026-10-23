# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Record public cumulative download counts without downloading release assets."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request

REPOSITORIES = {'llm-measurement/fleetdiff', 'llm-measurement/otelcol-genai-sketches',
                'llm-measurement/llm-sketchkit'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        raise ValueError('metadata redirects are refused; no asset content fallback')


def fetch_json(url):
    if not url.startswith('https://api.github.com/repos/'):
        raise ValueError('only the fixed public metadata API is allowed')
    request = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json',
        'User-Agent': 'llm-measurement-download-counts', 'X-GitHub-Api-Version': '2026-03-10'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=60) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('release metadata exceeds the size limit')
    return json.loads(data)


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('expected a nonnegative integer')
    return value


def seed_requests(path):
    from release_cache import spec
    definition = spec()
    data = path.read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('seed request log exceeds its size bound')
    allowed = {'asset', 'url', 'purpose', 'run_id', 'run_attempt', 'started_at', 'status',
               'finished_at', 'error_type', 'bytes', 'sha256'}
    records = []
    for line in data.splitlines():
        item = json.loads(line)
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError('unexpected seed request fields')
        name = item['asset']
        expected = 'https://github.com/llm-measurement/fleetdiff/releases/download/' + definition['version'] + '/' + name
        if name not in definition['assets'] or item['url'] != expected or item['purpose'] != 'deliberate protected-main cache seed':
            raise ValueError('seed request outside the approved release')
        integer(item['run_id'])
        integer(item['run_attempt'])
        datetime.fromisoformat(item['started_at'])
        if item['status'] not in {'started', 'verified', 'failed'}:
            raise ValueError('invalid seed request status')
        if item['status'] == 'verified':
            integer(item['bytes'])
            if item['sha256'] != definition['assets'][name]:
                raise ValueError('verified seed request has the wrong asset digest')
        if item['status'] != 'started':
            datetime.fromisoformat(item['finished_at'])
        if 'error_type' in item and not item['error_type'].isidentifier():
            raise ValueError('invalid sanitized error type')
        records.append(item)
    return records


def snapshot(repository, fetch=fetch_json):
    if repository not in REPOSITORIES:
        raise ValueError('repository is outside the approved public scope')
    records, seen = [], set()
    for page in range(1, 101):
        url = f'https://api.github.com/repos/{repository}/releases?per_page=100&page={page}'
        releases = fetch(url)
        if not isinstance(releases, list) or len(releases) > 100:
            raise ValueError('invalid release metadata page')
        for release in releases:
            if release.get('draft'):
                raise ValueError('anonymous collection must not contain draft releases')
            release_id = integer(release['id'])
            for asset in release['assets']:
                asset_id = integer(asset['id'])
                if asset_id in seen:
                    raise ValueError('duplicate release asset across metadata pages')
                seen.add(asset_id)
                records.append({'release_id': release_id, 'tag': release['tag_name'],
                    'published_at': release['published_at'], 'asset_id': asset_id,
                    'name': asset['name'], 'size_bytes': integer(asset['size']),
                    'download_count': integer(asset['download_count']), 'digest': asset.get('digest')})
        if len(releases) < 100:
            break
    else:
        raise ValueError('release pagination exceeds the bound; no partial snapshot written')
    return {'repository': repository, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'method': 'Anonymous public REST release metadata only; no asset content requested.',
        'count_semantics': 'Provider cumulative counts, including any CI and repeated requests. Not unique users; request purpose cannot be inferred.',
        'deliberate_download_requests_by_this_run': [],
        'deliberate_download_note': 'This metadata collector performs no deliberate download checks. The empty list does not claim that other clients made no requests.',
        'assets': sorted(records, key=lambda row: row['asset_id'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', choices=sorted(REPOSITORIES), default='llm-measurement/fleetdiff')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed-log', type=Path)
    args = parser.parse_args()
    record = snapshot(args.repository)
    if args.seed_log:
        record['related_protected_main_seed_requests'] = seed_requests(args.seed_log)
        record['seed_log_note'] = 'Historical request events, including started/verified/failed states. Not new requests by this metadata collector; never subtract these from cumulative provider counters.'
    with args.output.open('x') as stream:
        stream.write(json.dumps(record, indent=2) + '\n')
    print(f"Recorded {len(record['assets'])} cumulative asset counters; zero deliberate asset downloads")


if __name__ == '__main__':
    main()
