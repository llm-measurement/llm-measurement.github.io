# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Prepare the publication sitemap with UTC dates from committed page content."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from build import BASE, ROOT

NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'


def git(root, *args):
    return subprocess.check_output(['git', '--no-optional-locks', '-C', str(root), *args])


def content_dates(root):
    if git(root, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        raise ValueError('sitemap dates require full Git history; use fetch-depth: 0')
    result = {}
    for entry in ET.parse(root / 'docs/sitemap.xml').getroot():
        url = entry.findtext(f'{{{NS}}}loc')
        if not url or not url.startswith(BASE):
            raise ValueError('unexpected canonical sitemap URL')
        name = url.removeprefix(BASE) or 'index.html'
        if '/' in name or not name.endswith('.html') or '?' in name or '#' in name:
            raise ValueError('unexpected sitemap page path')
        path = 'docs/' + name
        committed = git(root, 'show', 'HEAD:' + path)
        if committed != (root / path).read_bytes():
            raise ValueError('page content differs from Git; commit it before publication')
        stamp = git(root, 'log', '-1', '--format=%cI', '--', path).decode().strip()
        date = datetime.fromisoformat(stamp)
        if date.tzinfo is None:
            raise ValueError('Git content date has no timezone')
        if url in result:
            raise ValueError('duplicate canonical sitemap URL')
        result[url] = date.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    if not result:
        raise ValueError('empty sitemap')
    return result


def render(root):
    dates = content_dates(root)
    tree = ET.parse(root / 'docs/sitemap.xml')
    for entry in tree.getroot():
        for old in list(entry.findall(f'{{{NS}}}lastmod')):
            entry.remove(old)
        ET.SubElement(entry, f'{{{NS}}}lastmod').text = dates[entry.findtext(f'{{{NS}}}loc')]
    ET.register_namespace('', NS)
    ET.indent(tree, space='  ')
    return ET.tostring(tree.getroot(), encoding='utf-8', xml_declaration=True) + b'\n'


def check(root, sitemap):
    dates = content_dates(root)
    actual = {}
    for entry in ET.fromstring(sitemap):
        url = entry.findtext(f'{{{NS}}}loc')
        values = entry.findall(f'{{{NS}}}lastmod')
        if url in actual or len(values) != 1:
            raise ValueError('each canonical URL needs exactly one lastmod')
        actual[url] = values[0].text
    if actual != dates:
        raise ValueError('sitemap lastmod dates do not match page content history')


def prepare(root, destination):
    sitemap = render(root)
    check(root, sitemap)
    # This staging directory is a deployment artifact, not another source tree.
    shutil.copytree(root / 'docs', destination)
    (destination / 'sitemap.xml').write_bytes(sitemap)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', type=Path)
    args = parser.parse_args()
    if bool(args.output) == bool(args.check):
        parser.error('choose exactly one of --output NEW_DIRECTORY or --check FILE')
    if args.output:
        prepare(ROOT, args.output)
    else:
        check(ROOT, args.check.read_bytes())
    print('PASS sitemap: every UTC lastmod matches the last committed page-content change')


if __name__ == '__main__':
    main()
