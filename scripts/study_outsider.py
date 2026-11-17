# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check the deployed study and evidence anonymously before IndexNow submission."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen

from build import BASE, ROOT
from sitemap import staged_articles
from study_checks import Document, EVIDENCE_DIR, SLUG, check, resource_surfaces

MAX_RESPONSE = 2 * 1024 * 1024
MAX_CITATION_RESPONSE = 8 * 1024 * 1024
DOI_TARGETS = {'10.1109/JSAC.2002.801752': 'ieeexplore.ieee.org/document/1031903'}


def fetch(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None:
        raise ValueError("outsider links must use anonymous HTTPS")
    same_origin = (parsed.hostname, parsed.port or 443) == (urlsplit(BASE).hostname, 443)
    # Vendor documentation includes hydration data larger than our own assets.
    limit = MAX_RESPONSE if same_origin else MAX_CITATION_RESPONSE
    request = Request(url, headers={"User-Agent": "LLM-Measurement-Study-Check/1",
                                   "Cache-Control": "no-cache"}, method="GET")
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("study link did not return HTTP 200")
        data = response.read(limit + 1)
    if len(data) > limit:
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


def matches_doi_target(value, expected):
    if not isinstance(value, str):
        return False
    target = urlsplit(value)
    ports = {'http': 80, 'https': 443}
    return (target.scheme in ports and target.username is None and target.password is None
            and target.port in (None, ports[target.scheme]) and not target.query and not target.fragment
            and (target.hostname or '') + target.path.removesuffix('/') == expected)


def doi_reference(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'doi.org'
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.query or parsed.fragment):
        raise ValueError('DOI citations must use canonical anonymous HTTPS')
    doi = parsed.path.removeprefix('/')
    expected = DOI_TARGETS.get(doi)
    if expected is None:
        raise ValueError('DOI citation has no reviewed target pin')
    return doi, 'https://doi.org/api/handles/' + quote(doi, safe='/'), expected


def doi_registry_target(record, doi):
    if (not isinstance(record, dict) or type(record.get('responseCode')) is not int
            or record['responseCode'] != 1 or not isinstance(record.get('handle'), str)
            or record['handle'].casefold() != doi.casefold()):
        raise ValueError('DOI is not registered as requested')
    values = record.get('values')
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise ValueError('DOI registry values are malformed')
    urls = [value.get('data') for value in values if value.get('type') == 'URL']
    if len(urls) != 1 or not isinstance(urls[0], dict) or urls[0].get('format') != 'string':
        raise ValueError('DOI registry target is malformed')
    return urls[0].get('value')


def check_doi(url, fetcher):
    doi, registry_url, expected = doi_reference(url)
    record = json.loads(fetcher(registry_url))
    if not matches_doi_target(doi_registry_target(record, doi), expected):
        raise ValueError('DOI registry target differs from its reviewed pin')
    return {'registry_url': registry_url, 'expected_target': expected,
            'publisher_reachability': 'not_asserted'}


def fetch_reference(url, fetcher, visited, doi_checks):
    if urlsplit(url).hostname == 'doi.org':
        if url not in doi_checks:
            doi_checks[url] = check_doi(url, fetcher)
        return None
    if url not in visited:
        visited[url] = fetcher(url)
    return visited[url]


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
    doi_checks = {}
    # Local bytes were already validated offline, including the MathML, fold,
    # head renderer and sole third-party resource. The live byte check binds it.
    links = [node.attrs["href"] for node in article.walk("a") if "href" in node.attrs]
    links += sorted(resources)
    links += [EVIDENCE_DIR + "/" + path.name for path in (root / "docs" / EVIDENCE_DIR).iterdir()]
    for link in links:
        url, fragment = urldefrag(urljoin(article_url, link))
        content = fetch_reference(url, fetcher, visited, doi_checks)
        if url in doi_checks:
            continue
        if url.startswith(BASE) and url != article_url:
            if content != local_bytes(root, url):
                raise ValueError("live local study link differs from the checked bytes")
        if fragment and url.startswith(BASE):
            ids = {node.attrs.get("id") for node in Document(content.decode("utf-8")).root.walk()}
            if fragment not in ids:
                raise ValueError("live study link has no matching fragment")
    return {"pass": True, "url": article_url, "anonymous_get_only": True,
            "fresh_cache": True, "article_sha256": hashlib.sha256(actual).hexdigest(),
            "checked_links_and_resources": len(visited) + len(doi_checks),
            "doi_registry_checks": doi_checks, "evidence_files": local["evidence_files"],
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
