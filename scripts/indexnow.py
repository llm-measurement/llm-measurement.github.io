# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Notify IndexNow of changed canonical pages after their deployment is live."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from build import BASE, ROOT

KEY_FILE = "1fcb3191597647daa6285898dc9171b1.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"


def pages(sitemap):
    result = {}
    for element in ET.fromstring(sitemap).findall("{*}url/{*}loc"):
        url = element.text
        parsed = urlsplit(url)
        if (not url.startswith(BASE) or parsed.query or parsed.fragment
                or parsed.username or parsed.password):
            raise ValueError("sitemap contains a noncanonical URL")
        path = parsed.path.removeprefix("/") or "index.html"
        if "/" in path or not path.endswith(".html") or url in result:
            raise ValueError("sitemap contains an unexpected page")
        result[url] = "docs/" + path
    if not 1 <= len(result) <= 10000:
        raise ValueError("unexpected sitemap size")
    return result


def previous_bytes(revision, path):
    result = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=ROOT,
                            capture_output=True)
    return result.stdout if result.returncode == 0 else None


def changes(previous):
    current = pages((ROOT / "docs/sitemap.xml").read_bytes())
    # The first deployment verifies the key and registers this small site.
    if previous_bytes(previous, "docs/" + KEY_FILE) is None:
        return {url: (ROOT / path).read_bytes() for url, path in current.items()}
    old_sitemap = previous_bytes(previous, "docs/sitemap.xml")
    if old_sitemap is None:
        raise ValueError("previous sitemap is unavailable")
    old = pages(old_sitemap)
    result = {url: None for url in old.keys() - current.keys()}
    for url, path in current.items():
        content = (ROOT / path).read_bytes()
        if previous_bytes(previous, path) != content:
            result[url] = content
    return dict(sorted(result.items()))


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "LLM-Measurement-IndexNow/1"}),
                 timeout=20) as response:
        if response.geturl() != url:
            raise ValueError("unexpected live URL redirect")
        return response.read()


def wait_live(changed, seconds):
    expected = {BASE + KEY_FILE: (ROOT / "docs" / KEY_FILE).read_bytes(), **changed}
    deadline = time.monotonic() + seconds
    while True:
        try:
            for url, content in expected.items():
                try:
                    actual = fetch(url)
                except HTTPError as error:
                    if content is None and error.code in (404, 410):
                        continue
                    raise
                if content is None or actual != content:
                    raise ValueError("deployment is not live yet")
            return
        except (HTTPError, URLError, TimeoutError, ValueError):
            if time.monotonic() >= deadline:
                raise RuntimeError("live deployment verification failed") from None
            time.sleep(10)


def submit(changed):
    key = (ROOT / "docs" / KEY_FILE).read_text().strip()
    if key != KEY_FILE.removesuffix(".txt"):
        raise ValueError("IndexNow key file does not match its name")
    payload = {"host": urlsplit(BASE).netloc, "key": key,
               "keyLocation": BASE + KEY_FILE, "urlList": sorted(changed)}
    request = Request(ENDPOINT, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json; charset=utf-8"},
                      method="POST")
    with urlopen(request, timeout=30) as response:
        if response.status not in (200, 202):
            raise RuntimeError(f"IndexNow refused submission: HTTP {response.status}")
        print(f"IndexNow received {len(changed)} URLs: HTTP {response.status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", default="HEAD^")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()
    subprocess.run(["git", "rev-parse", "--verify", args.previous + "^{commit}"],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    changed = changes(args.previous)
    print(json.dumps({"changed_urls": sorted(changed)}, indent=2))
    if args.submit and changed:
        wait_live(changed, args.wait_seconds)
        submit(changed)


if __name__ == "__main__":
    main()
