# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Independent citation preflight or future anonymous, exact-byte live check."""
import argparse
import json
from pathlib import Path
from urllib.parse import urldefrag, urljoin

from cheaper_study_checks import (BASE, DEPENDENCIES, EVIDENCE_DIR, EVIDENCE_NAMES,
                                  ROOT, SLUG, URL, article_document, check)
from sitemap import staged_articles
from study_checks import Document, resource_surfaces, sha256
from study_outsider import fetch, fetch_reference, local_bytes


def article_links(article):
    return [node.attrs["href"] for node in article.walk("a") if "href" in node.attrs]


def check_citations(root=ROOT, fetcher=None):
    # Source-only: publication, built resources and reproduction may still be pending.
    _, _, article = article_document(root)
    fetcher = fetch if fetcher is None else fetcher
    visited, doi_checks = {}, {}
    citations = sorted({urldefrag(urljoin(URL, link))[0] for link in article_links(article)
                        if not urljoin(URL, link).startswith(BASE)})
    for url in citations:
        fetch_reference(url, fetcher, visited, doi_checks)
    return {"pass": True, "mode": "citations", "slug": SLUG,
            "checked_citations": citations, "doi_registry_checks": doi_checks,
            "anonymous_get_only": True, "fresh_cache": True,
            "scope": "external article citations; reachability, not claim verification"}


def check_live(root=ROOT, fetcher=None):
    root = Path(root)
    local = check(root)
    fetcher = fetch if fetcher is None else fetcher
    publication = staged_articles(root)
    actual = fetcher(URL)
    if actual != publication[f"docs/{SLUG}.html"]:
        raise ValueError("live article differs from its staged publication artifact")
    document = Document(actual.decode("utf-8"))
    article, = document.root.walk("article")
    resources, _ = resource_surfaces(document)
    links = article_links(article) + sorted(resources | set(local["resources"]))
    links += [f"{EVIDENCE_DIR}/{name}" for name in sorted(EVIDENCE_NAMES)]
    links += sorted(DEPENDENCIES)
    visited, doi_checks = {URL: actual}, {}
    for link in links:
        url, fragment = urldefrag(urljoin(URL, link))
        content = fetch_reference(url, fetcher, visited, doi_checks)
        if url in doi_checks:
            continue
        if url.startswith(BASE):
            # Validate the local path with the existing boundary check even when
            # deployment rewrites that page's dates from first-parent Git history.
            expected = local_bytes(root, url)
            path = "docs/" + url.removeprefix(BASE)
            if path in publication:
                expected = publication[path]
            if content != expected:
                raise ValueError("live local study link differs from checked publication bytes")
            if fragment:
                ids = {node.attrs.get("id") for node in Document(content.decode("utf-8")).root.walk()}
                if fragment not in ids:
                    raise ValueError("live study link has no matching fragment")
    return {"pass": True, "mode": "live", "url": URL, "anonymous_get_only": True,
            "fresh_cache": True, "article_sha256": sha256(actual),
            "checked_links_and_resources": len(visited) + len(doi_checks),
            "doi_registry_checks": doi_checks, "evidence_files": local["evidence_files"],
            "inline_charts": local["inline_charts"],
            "plausible_and_article_head_match": True, "staged_publication_bytes_match": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--citations", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = check_live(args.root) if args.live else check_citations(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
