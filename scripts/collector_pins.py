# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check current collector pins against stable releases and published advisories."""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import parse_qsl, urlsplit

REPO = "llm-measurement/otelcol-genai-sketches"
API = "https://api.github.com/repos/" + REPO
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
PACKAGES = {
    "ghcr.io/" + REPO: "runtime",
    "github.com/" + REPO: "runtime",
    "github.com/" + REPO + "/connector/genaisketchconnector": "runtime",
    "ghcr.io/llm-measurement/charts/otelcol-genai-sketches": "chart",
}
SOURCE_PIN = re.compile(
    r"https://(?:github\.com|raw\.githubusercontent\.com|codeload\.github\.com)/"
    + re.escape(REPO)
    + r"/(?:blob/|tree/|releases/tag/|releases/download/|archive/refs/tags/|tar\.gz/(?:refs/tags/)?)?"
    r"(v[0-9][^/\s\"'<>`)]*)"
)
VERSION_TOKEN = r"v?[0-9]+\.[0-9]+\.[0-9]+(?:[+-][0-9A-Za-z.-]+)?"
TEXT_PIN = re.compile(
    r"\b(collector(?: configuration(?: pins| guidance:))?|chart)\s+(" + VERSION_TOKEN + r")(?![\w.+-])",
    re.IGNORECASE,
)
LEADING_PIN = re.compile(r"\b(" + VERSION_TOKEN + r")(?![\w.+-])\s+(collector|image)\b", re.IGNORECASE)
OCI_PIN = re.compile(r"ghcr\.io/llm-measurement/(charts/)?otelcol-genai-sketches:([^\s\"'<>`),]+)")


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "li", "pre", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")


def version(value):
    if not isinstance(value, str) or not re.fullmatch("v?" + VERSION, value):
        raise ValueError("expected an exact stable collector version: " + repr(value))
    return tuple(map(int, value.removeprefix("v").split(".")))


def timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid collector API timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid collector API timestamp") from error
    if result.tzinfo is None:
        raise ValueError("collector API timestamp needs a timezone")
    return result


def affected(value, expression):
    """GitHub comparator conjunctions; unknown syntax fails rather than passing."""
    current = version(value)
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("missing advisory affected range")
    alternatives = []
    for alternative in expression.split("||"):
        comparisons = []
        for term in alternative.split(","):
            match = re.fullmatch(r"\s*(>=|<=|>|<|=)?\s*(v?" + VERSION + r")\s*", term)
            if not match:
                raise ValueError("unsupported advisory affected range: " + expression)
            op, bound = match.groups()
            other = version(bound)
            comparisons.append({None: current == other, "=": current == other,
                                ">=": current >= other, "<=": current <= other,
                                ">": current > other, "<": current < other}[op])
        alternatives.append(all(comparisons))
    return any(alternatives)


def fetch_list(endpoint):
    if endpoint not in {"/releases", "/security-advisories"}:
        raise ValueError("unexpected collector API endpoint")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result = []
    url = API + endpoint + "?per_page=100"
    seen = set()
    for _ in range(20):
        if url in seen:
            raise ValueError("collector API pagination repeated a URL")
        seen.add(url)
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "llm-measurement-site-pin-check"})
        with opener.open(request, timeout=60) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            links = response.headers.get("Link", "")
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("collector API response exceeds size limit")
        records = json.loads(raw)
        if not isinstance(records, list) or len(records) > 100:
            raise ValueError("unexpected collector API list")
        result.extend(records)
        following = []
        for link in links.split(",") if links else []:
            match = re.fullmatch(r'\s*<([^>]+)>\s*;\s*rel="([a-z ]+)"\s*', link)
            if not match:
                raise ValueError("malformed collector API pagination link")
            if "next" in match.group(2).split():
                following.append(match.group(1))
        if not following:
            return result
        if len(following) != 1:
            raise ValueError("multiple collector API next links")
        url = following[0]
        parsed, expected = urlsplit(url), urlsplit(API + endpoint)
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        allowed = {"per_page", "page"} if endpoint == "/releases" else {"per_page", "before", "after", "sort", "direction", "state"}
        if (parsed.scheme != expected.scheme or parsed.netloc != expected.netloc
                or parsed.path != expected.path or parsed.fragment
                or len(query) != len(dict(query)) or not set(dict(query)) <= allowed
                or dict(query).get("per_page") != "100"):
            raise ValueError("unexpected collector API pagination target")
    raise ValueError("collector API pagination exceeds limit")


def policy(releases, advisories):
    if not isinstance(releases, list) or not isinstance(advisories, list):
        raise ValueError("release and advisory inputs must be lists")
    for item in releases:
        if (not isinstance(item, dict) or not isinstance(item.get("tag_name"), str)
                or type(item.get("draft")) is not bool or type(item.get("prerelease")) is not bool):
            raise ValueError("incomplete collector release")
        timestamp(item.get("published_at"))
    stable = [r for r in releases if r.get("draft") is False and r.get("prerelease") is False
              and r.get("published_at") and re.fullmatch("v" + VERSION, r.get("tag_name", ""))]
    if not stable:
        raise ValueError("no published stable collector release")
    latest = max(stable, key=lambda r: version(r["tag_name"]))
    published = []
    for advisory in advisories:
        if (not isinstance(advisory, dict) or advisory.get("state") not in {"triage", "draft", "published", "closed"}
                or "withdrawn_at" not in advisory):
            raise ValueError("incomplete collector advisory state")
        withdrawn = timestamp(advisory["withdrawn_at"])
        if advisory.get("state") != "published" or withdrawn is not None:
            continue
        if timestamp(advisory.get("published_at")) is None or not isinstance(advisory.get("vulnerabilities"), list):
            raise ValueError("incomplete published collector advisory")
        published.append({"ghsa_id": advisory["ghsa_id"], "url": advisory["html_url"],
            "vulnerabilities": [{"package": item["package"]["name"],
                                 "affected": item["vulnerable_version_range"]}
                                for item in advisory["vulnerabilities"]]})
    record = {"schema": 1, "repository": REPO, "checked_at": datetime.now(timezone.utc).isoformat(),
            "latest_stable": latest["tag_name"], "release_url": latest["html_url"],
            "sources": [API + "/releases", API + "/security-advisories"],
            "advisories": published}
    validate_policy(record)
    return record


def validate_policy(record):
    if (not isinstance(record, dict) or record.get("schema") != 1 or record.get("repository") != REPO
            or not isinstance(record.get("advisories"), list)):
        raise ValueError("unexpected collector policy snapshot")
    version(record.get("latest_stable"))
    for advisory in record["advisories"]:
        if (not isinstance(advisory, dict) or not isinstance(advisory.get("ghsa_id"), str)
                or not re.fullmatch(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", advisory["ghsa_id"])
                or not isinstance(advisory.get("vulnerabilities"), list) or not advisory["vulnerabilities"]):
            raise ValueError("incomplete collector advisory record")
        for item in advisory["vulnerabilities"]:
            if (not isinstance(item, dict) or not isinstance(item.get("package"), str) or not item["package"]
                    or not isinstance(item.get("affected"), str) or not item["affected"]):
                raise ValueError("incomplete collector vulnerability record")
            if item["package"] in PACKAGES:
                affected(record["latest_stable"], item["affected"])


def live_policy():
    return policy(fetch_list("/releases"), fetch_list("/security-advisories"))


def source_pins(source):
    pins = []
    for match in SOURCE_PIN.finditer(source):
        ref = match.group(1).removesuffix(".tar.gz")
        version(ref)
        pins.append(("runtime", ref))
    visible = VisibleText()
    visible.feed(source)
    text = "".join(visible.parts)
    pins.extend(("chart" if kind.lower() == "chart" else "runtime", ref)
                for kind, ref in TEXT_PIN.findall(text))
    pins.extend(("runtime", ref) for ref, _ in LEADING_PIN.findall(text))
    pins.extend(("chart" if chart else "runtime", ref) for chart, ref in OCI_PIN.findall(source))
    # The security page binds both OCI subjects to this explicit runtime tag.
    from outsider import Blocks
    blocks = Blocks()
    blocks.feed(source)
    for block in blocks.review:
        if block["id"] == "collector":
            assignments = re.findall(r"(?m)^release=(\S+)$", block["text"])
            if len(assignments) != 1:
                raise ValueError("collector verification needs one exact release assignment")
            version(assignments[0])
            pins.append(("runtime", assignments[0]))
    return pins


def check_source(name, source, record):
    validate_policy(record)
    pins = source_pins(source)
    latest = record["latest_stable"]
    for kind, pin in pins:
        for advisory in record["advisories"]:
            for item in advisory["vulnerabilities"]:
                if PACKAGES.get(item["package"]) == kind and affected(pin, item["affected"]):
                    raise ValueError(f"{name}: collector {kind} {pin} is affected by {advisory['ghsa_id']}")
        if version(pin) != version(latest):
            raise ValueError(f"{name}: collector {kind} {pin} != latest stable release {latest}")
    return len(pins)


def current_evidence(source):
    start = "<!-- historical-verification:start -->"
    end = "<!-- historical-verification:end -->"
    if (source.lower().count("historical-verification") != 2
            or source.count(start) != 1 or source.count(end) != 1
            or source.index(end) < source.index(start)):
        raise ValueError("evidence needs exactly one ordered historical-verification marker pair")
    before, _, remainder = source.partition(start)
    _, _, after = remainder.partition(end)
    return before + after


def check(root, live=False):
    record = live_policy() if live else json.loads((root / "evidence/collector-release-policy.json").read_text())
    validate_policy(record)
    paths = [root / "README.md", root / "docs/llms.txt"]
    paths += sorted((root / "pages").glob("*.html")) + sorted((root / "docs").glob("*.html"))
    count = sum(check_source(str(p.relative_to(root)), p.read_text(), record) for p in paths)
    evidence = root / "evidence/README.md"
    count += check_source("evidence/README.md", current_evidence(evidence.read_text()), record)
    if not count:
        raise ValueError("no collector version pins found")
    mode = "live anonymous release/advisory lookup" if live else "recorded release/advisory snapshot (offline)"
    print(f"PASS: {count} collector pins match {record['latest_stable']}; no published affected range matches; {mode}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True, help="write the public release/advisory snapshot")
    args = parser.parse_args()
    args.record.write_text(json.dumps(live_policy(), indent=2, sort_keys=True) + "\n")
