# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check the deployed study and evidence anonymously before IndexNow submission."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen

from build import BASE, ROOT
from sitemap import staged_articles
from study_checks import Document, EVIDENCE_DIR, SLUG, check, resource_surfaces

MAX_RESPONSE = 2 * 1024 * 1024


def fetch(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("outsider links must use anonymous HTTPS")
    request = Request(url, headers={"User-Agent": "LLM-Measurement-Study-Check/1",
                                   "Cache-Control": "no-cache"}, method="GET")
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("study link did not return HTTP 200")
        data = response.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ValueError("study response exceeds the bounded check size")
    return data


def local_bytes(root, url):
    relative = url.removeprefix(BASE)
    path = root / "docs" / (relative or "index.html")
    if path.is_dir():
        path = path / "index.html"
    if not path.resolve().is_relative_to((root / "docs").resolve()) or not path.is_file():
        raise ValueError("study link is not a published local file")
    return path.read_bytes()


def check_live(root=ROOT, fetcher=None):
    root = Path(root)
    local = check(root)
    fetcher = fetch if fetcher is None else fetcher
    article_url = urljoin(BASE, SLUG + ".html")
    expected = staged_articles(root)["docs/" + SLUG + ".html"]
    actual = fetcher(article_url)
    if actual != expected:
        raise ValueError("live article differs from its committed publication artifact")
    document = Document(actual.decode("utf-8"))
    article, = document.root.walk("article")
    resources, _ = resource_surfaces(document)
    visited = {article_url: actual}
    # Local bytes were already validated offline, including the MathML, fold,
    # head renderer and sole third-party resource. The live byte check binds it.
    links = [node.attrs["href"] for node in article.walk("a") if "href" in node.attrs]
    links += sorted(resources)
    links += [EVIDENCE_DIR + "/" + path.name for path in (root / "docs" / EVIDENCE_DIR).iterdir()]
    for link in links:
        url, fragment = urldefrag(urljoin(article_url, link))
        if url not in visited:
            visited[url] = fetcher(url)
        if url.startswith(BASE) and url != article_url:
            if visited[url] != local_bytes(root, url):
                raise ValueError("live local study link differs from the checked bytes")
        if fragment and url.startswith(BASE):
            ids = {node.attrs.get("id") for node in Document(visited[url].decode("utf-8")).root.walk()}
            if fragment not in ids:
                raise ValueError("live study link has no matching fragment")
    return {"pass": True, "url": article_url, "anonymous_get_only": True,
            "fresh_cache": True, "article_sha256": hashlib.sha256(actual).hexdigest(),
            "checked_links_and_resources": len(visited), "evidence_files": local["evidence_files"],
            "mathml": local["mathml"], "native_sql_fold": True,
            "plausible_and_article_head_match": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    if args.live:
        print(json.dumps(check_live(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
