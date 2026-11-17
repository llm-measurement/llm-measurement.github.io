# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Offline, bounded checks for the approved prompt-cache study, not guide rules."""
import argparse
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SLUG = "prompt-cache-bills"
TITLE = "Same Prompt, Same Cache, Opposite Bills"
EVIDENCE_DIR = "assets/cache-evidence"
MANIFEST = "evidence/cache-study-verified.json"
EVIDENCE_NAMES = frozenset({
    "RUN.md", "cache_puzzle-output.txt", "cache_puzzle.py", "fleetdiff-output.txt",
    "live_check-output.txt", "live_check-summary.json", "live_check.py",
    "make_fixture.py", "results.json", "scheduled-job.csv",
    "trace_replay-output.txt", "trace_replay-results.json", "trace_replay.py",
})
RERUN_NAME = "fleetdiff-v0141-output.txt"
SUPPORT_NAMES = frozenset({"index.html", "RERUN_v0.14.1.md", "ATTRIBUTION.md"})
CONVERTER_PASS = "PASS: approved text, equations and all three code blocks unchanged"
PLAUSIBLE_SRC = "https://plausible.io/js/pa-XxJJVAxJMHffrJ0MqBrpF.js"
PLAUSIBLE_INIT = (
    "window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},"
    "plausible.init=plausible.init||function(i){plausible.o=i||{}};\n  plausible.init()"
)
PRIVACY_TEXT = "Privacy-friendly analytics by Plausible: no cookies, no personal data"
QUOTED_LINES = (
    "Cache reuse rose: cache-read share 0% -> 93.5% (uncached input -460,000).",
    "      Cache reads: 0 of 492,000 input tokens -> 460,000 of 492,000 (all requests report cache detail).",
    "      Cache writes: 480,000 of 492,000 input tokens -> 20,000 of 492,000 (all requests report cache detail).",
    "  Recorded spend (USD, analyzed calls): 1.944 -> 0.402.",
)
VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def digest(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            f"{label}: expected lowercase SHA-256")
    return value


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: object = None
    start: int = 0
    end: int = 0

    def walk(self, tag=None):
        for child in self.children:
            if isinstance(child, Element):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.walk(tag)

    def text(self):
        return "".join(child.text() if isinstance(child, Element) else child
                       for child in self.children)


class Document(HTMLParser):
    """Retain source offsets as well as structure; code whitespace stays literal."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0] + [i + 1 for i, character in enumerate(source) if character == "\n"]
        self.root = Element("#document")
        self.stack = [self.root]
        self.comments = []
        self.feed(source)
        self.close()
        require(len(self.stack) == 1, "unclosed HTML element")

    def source_offset(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        require(len(attrs) == len(dict(attrs)), f"duplicate HTML attribute on {tag}")
        node = Element(tag, dict(attrs), parent=self.stack[-1], start=self.source_offset())
        self.stack[-1].children.append(node)
        if tag in VOID_TAGS:
            node.end = self.source_offset() + len(self.get_starttag_text())
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        require(tag not in {"script", "style"}, f"self-closing active HTML element: {tag}")
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.pop().end = self.source_offset() + len(self.get_starttag_text())

    def handle_endtag(self, tag):
        require(len(self.stack) > 1 and self.stack[-1].tag == tag,
                f"mismatched HTML closing tag: {tag}")
        self.stack.pop().end = self.source.index(">", self.source_offset()) + 1

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def handle_comment(self, data):
        self.comments.append(data.strip())


def local_asset(url, label):
    require(isinstance(url, str) and url and not any(c.isspace() for c in url),
            f"{label}: invalid resource URL")
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    require(not parsed.scheme and not parsed.netloc and not parsed.query
            and not parsed.fragment and not path.startswith("/")
            and "\\" not in path and not any(ord(c) < 32 for c in path),
            f"{label}: resource must be a relative local asset: {url}")
    parts = path.split("/")
    require(parts[0] == "assets" and all(p not in {"", ".", ".."} for p in parts),
            f"{label}: resource outside assets: {url}")
    return path


def css_resources(source, label):
    # This site's CSS has no escapes or imports. Reject those rather than try to
    # implement the CSS grammar and accidentally miss an obfuscated remote URL.
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    require("\\" not in source and "@import" not in source.lower()
            and "expression(" not in source.lower() and "-moz-binding" not in source.lower(),
            f"{label}: CSS imports, escapes or execution are not allowed")
    require(not re.search(r"\b(?:image|image-set|-webkit-image-set)\s*\(", source, re.I),
            f"{label}: unsupported CSS image resource function")
    resources = set()
    matches = list(re.finditer(r"url\s*\(([^)]*)\)", source, re.I))
    for match in matches:
        url = match.group(1).strip().strip("\"'")
        resources.add(local_asset(urljoin(label if label.startswith("assets/") else "", url), label))
    require(len(re.findall(r"\burl\b", source, re.I)) == len(matches),
            f"{label}: unsupported CSS URL syntax")
    return resources


def check_resource_attributes(node, resources):
    attrs = node.attrs
    forbidden = {"base", "iframe", "frame", "frameset", "fencedframe", "object", "embed",
                 "applet", "portal", "form", "input", "button", "audio", "video", "source",
                 "track", "template", "foreignobject", "annotation-xml", "animate", "set"}
    require(node.tag not in forbidden, f"unexpected resource or active element: {node.tag}")
    for name, value in attrs.items():
        require(not name.startswith("on"), f"inline event handler: {name}")
        require(name not in {"srcdoc", "srcset", "imagesrcset", "ping", "poster", "background",
                             "action", "formaction", "manifest", "codebase", "archive", "data"},
                f"unexpected resource attribute: {name}")
        if name == "style":
            resources.update(css_resources(value or "", "inline style"))
        if name in {"href", "xlink:href"} and node.tag != "link":
            parsed = urlsplit(value or "")
            if node.tag == "a":
                require(parsed.scheme.lower() in {"", "https", "http", "mailto"},
                        f"unsafe hyperlink: {value}")
            else:
                require(value and value.startswith("#"), f"unexpected SVG/MathML resource: {value}")
        if name == "src":
            require(node.tag in {"script", "img"}, f"unexpected src on {node.tag}")
    if node.tag == "meta":
        require(attrs.get("http-equiv", "").lower() not in {"refresh", "link"},
                "meta refresh/resource header is not allowed")


def check_script_resource(node, resources):
    attrs = node.attrs
    src = attrs.get("src")
    if src == PLAUSIBLE_SRC:
        require("async" in attrs and not node.text().strip(), "invalid Plausible script")
        require(attrs.get("type", "").lower() in {"", "text/javascript"}, "Plausible must execute")
        return "plausible"
    if src is not None:
        require(src == "assets/site.js" and "defer" in attrs and not node.text().strip()
                and attrs.get("type", "").lower() in {"", "text/javascript"},
                f"unexpected executing script: {src}")
        resources.add(src)
        return "site_script"
    if attrs.get("type", "").lower() == "application/ld+json":
        json.loads(node.text())
        return None
    require(node.text().strip() == PLAUSIBLE_INIT, "unexpected inline executing script")
    return "initializer"


def check_link_resource(node, resources, stylesheets):
    attrs = node.attrs
    rel = set(attrs.get("rel", "").lower().split())
    if rel == {"canonical"}:
        return
    require(rel in ({"stylesheet"}, {"icon"}, {"apple-touch-icon"}),
            f"unexpected resource link: {rel}")
    asset = local_asset(attrs.get("href"), "link")
    resources.add(asset)
    if rel == {"stylesheet"}:
        stylesheets.add(asset)


def resource_surfaces(document):
    resources = set()
    stylesheets = set()
    scripts = {"plausible": 0, "initializer": 0, "site_script": 0}
    for node in document.root.walk():
        check_resource_attributes(node, resources)
        if node.tag == "script":
            kind = check_script_resource(node, resources)
            if kind is not None:
                scripts[kind] += 1
        elif node.tag == "link":
            check_link_resource(node, resources, stylesheets)
        elif node.tag == "img":
            resources.add(local_asset(node.attrs.get("src"), "image"))
        elif node.tag == "style":
            resources.update(css_resources(node.text(), "style element"))
    require(scripts["plausible"] == 1, "expected exactly one correct Plausible src")
    require(scripts["initializer"] == 1 and scripts["site_script"] == 1,
            "expected one Plausible initializer and one site script")
    return resources, stylesheets


def inventory(root, label):
    require(root.is_dir() and not root.is_symlink(), f"{label}: missing evidence directory")
    entries = list(root.iterdir())
    require(all(p.is_file() and not p.is_symlink() for p in entries),
            f"{label}: evidence entries must be regular files")
    names = {p.name for p in entries}
    required = EVIDENCE_NAMES | {RERUN_NAME}
    require(required <= names and names <= required | SUPPORT_NAMES,
            f"{label}: protected evidence inventory differs")
    return names


def check_manifest(root):
    record = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    require(type(record.get("schema")) is int and record["schema"] == 1, "study manifest schema must be 1")
    digest(record.get("source_sha256"), "approved source")
    require(record.get("converter_pass") == CONVERTER_PASS, "approved conversion did not pass")
    require(record.get("deterministic_evidence_reproduced") is True, "deterministic evidence was not reproduced")
    return record


def check_body(root, record):
    body_bytes = (root / f"pages/{SLUG}.html").read_bytes()
    require(sha256(body_bytes) == digest(record.get("article_body_sha256"), "article body"),
            "article body hash differs from approved conversion")
    body = body_bytes.decode("utf-8")
    source_document = Document(body)
    articles = list(source_document.root.walk("article"))
    require(len(articles) == 1 and body.strip() == body[articles[0].start:articles[0].end],
            "study body must contain exactly one article")
    require("study" in articles[0].attrs.get("class", "").split(), "missing study article profile")
    return body_bytes, body, source_document


def check_evidence(root, record):
    evidence = record.get("evidence")
    require(isinstance(evidence, dict), "missing evidence hash map")
    # Accept basenames or repository-relative paths, never a mixed/expanded inventory.
    if set(evidence) == {f"{EVIDENCE_DIR}/{name}" for name in EVIDENCE_NAMES}:
        evidence = {name: evidence[f"{EVIDENCE_DIR}/{name}"] for name in EVIDENCE_NAMES}
    require(set(evidence) == EVIDENCE_NAMES, "manifest must protect exactly the 13 approved evidence files")
    source_names = inventory(root / EVIDENCE_DIR, "source")
    for prefix in (root, root / "docs"):
        folder = prefix / EVIDENCE_DIR
        require(inventory(folder, str(prefix)) == source_names, "built evidence inventory differs")
        for name, value in evidence.items():
            require(sha256((folder / name).read_bytes()) == digest(value, name),
                    f"{prefix}: evidence hash mismatch: {name}")
    return evidence, source_names


def check_rerun_record(record, evidence):
    rerun = record.get("rerun")
    require(isinstance(rerun, dict) and isinstance(rerun.get("version"), str)
            and re.fullmatch(r"(?:fleetdiff )?v0\.14\.1(?: \([0-9a-f]{40}\) go[0-9.]+ [a-z0-9]+/[a-z0-9]+)?",
                             rerun["version"]), "rerun must use v0.14.1")
    for key in ("archive_sha256", "binary_sha256", "stdout_sha256", "sample_csv_sha256"):
        digest(rerun.get(key), f"rerun {key}")
    require(rerun.get("full_stdout_byte_equal") is True, "rerun stdout equality not confirmed")
    require(rerun.get("quoted_lines") == list(QUOTED_LINES), "rerun quoted lines differ, including spacing")
    require(rerun.get("spend_before") == "1.944" and rerun.get("spend_after") == "0.402",
            "rerun spend must be 1.944 -> 0.402")
    require(rerun["sample_csv_sha256"] == evidence["scheduled-job.csv"], "rerun sample CSV hash mismatch")
    return rerun


def check_support_files(root, source_names):
    for name in source_names & SUPPORT_NAMES:
        require((root / EVIDENCE_DIR / name).read_bytes() == (root / "docs" / EVIDENCE_DIR / name).read_bytes(),
                f"built support file differs: {name}")


def check_quoted_stdout(stdout):
    lines = stdout.decode("utf-8").splitlines()
    positions = []
    for line in QUOTED_LINES:
        require(lines.count(line) == 1, f"literal quoted line missing or duplicated: {line}")
        positions.append(lines.index(line))
    require(positions == sorted(positions), "quoted output lines are out of order")


def check_rerun(root, record, evidence, source_names):
    rerun = check_rerun_record(record, evidence)
    stdout = (root / EVIDENCE_DIR / RERUN_NAME).read_bytes()
    require(sha256(stdout) == rerun["stdout_sha256"], "rerun stdout hash mismatch")
    require(stdout == (root / EVIDENCE_DIR / "fleetdiff-output.txt").read_bytes(),
            "rerun full stdout is not byte equal to approved output")
    require(stdout == (root / "docs" / EVIDENCE_DIR / RERUN_NAME).read_bytes(),
            "built rerun stdout differs")
    check_support_files(root, source_names)
    check_quoted_stdout(stdout)


def check_built_article(root, body, source_document):
    built = (root / f"docs/{SLUG}.html").read_bytes().decode("utf-8")
    document = Document(built)
    built_articles = list(document.root.walk("article"))
    require(len(built_articles) == 1 and built.startswith(body, built_articles[0].start)
            and built.count(body) == 1, "built article differs from approved body")
    entries = [p for p in json.loads((root / "pages.json").read_text(encoding="utf-8")) if p["slug"] == SLUG]
    require(len(entries) == 1 and entries[0].get("title") == TITLE, "study must have its approved title")
    headings = list(document.root.walk("h1"))
    require(len(headings) == 1 and headings[0].text() == entries[0]["title"], "study H1/title mismatch")
    require(not source_document.comments and all(c == "Privacy-friendly analytics by Plausible"
                                                for c in document.comments), "internal HTML comment leaked")
    require(not any(marker in built or marker in body for marker in ("FIXES", "POST_v2")),
            "internal revision marker leaked")
    return document, built_articles[0]


def check_article_math(document):
    maths = list(document.root.walk("math"))
    require(maths, "missing static MathML")
    for math in maths:
        require(math.attrs.get("xmlns") == "http://www.w3.org/1998/Math/MathML", "MathML missing namespace")
        annotations = list(math.walk("annotation"))
        require(len(annotations) == 1 and annotations[0].attrs.get("encoding") == "application/x-tex"
                and annotations[0].text().strip() and list(math.walk("semantics")),
                "MathML requires static semantics and a TeX annotation")
    return len(maths)


def check_article_fold(article):
    blocks = list(article.walk("pre"))
    require(len(blocks) == 3, "expected exactly three approved code blocks")
    codes = []
    for block in blocks:
        children = list(block.walk("code"))
        require(len(children) == 1, "each study code block needs one code element")
        codes.append(children[0])
    require([code.attrs.get("class") for code in codes] == ["language-sql", "language-sh", "language-text"],
            "study code block languages/order differ")
    details = codes[0].parent.parent
    require(details.tag == "details" and details.attrs.get("open") is None
            and "open" not in details.attrs, "SQL must use a native collapsed details element")
    summaries = [child for child in details.children if isinstance(child, Element) and child.tag == "summary"]
    require(len(summaries) == 1 and summaries[0].text().startswith("SQL:"), "SQL disclosure needs its summary")
    require(codes[2].text() == "\n...\n".join(QUOTED_LINES), "article output quote differs, including spacing")
    return len(blocks)


def check_privacy_footer(document):
    footers = list(document.root.walk("footer"))
    require(len(footers) == 1 and footers[0].text().count(PRIVACY_TEXT) == 1,
            "expected footer privacy text exactly once")
    privacy_links = [a for a in footers[0].walk("a") if a.attrs.get("href") == "https://plausible.io/data-policy"]
    require(len(privacy_links) == 1 and privacy_links[0].text() == "Plausible", "missing Plausible privacy link")


def check_local_resources(root, resources, stylesheets):
    pending = list(resources)
    while pending:
        name = pending.pop()
        original, published = root / name, root / "docs" / name
        require(original.is_file() and published.is_file() and not original.is_symlink()
                and not published.is_symlink(), f"missing local resource: {name}")
        require(original.read_bytes() == published.read_bytes(), f"built resource differs: {name}")
        if name in stylesheets:
            dependencies = css_resources(published.read_text(encoding="utf-8"), name) - resources
            resources.update(dependencies)
            pending.extend(dependencies)
    return resources


def check(root=ROOT):
    """Return a JSON-compatible summary; fail closed without invoking any tools or network."""
    root = Path(root)
    record = check_manifest(root)
    body_bytes, body, source_document = check_body(root, record)
    evidence, source_names = check_evidence(root, record)
    check_rerun(root, record, evidence, source_names)
    document, article = check_built_article(root, body, source_document)
    math_count = check_article_math(document)
    block_count = check_article_fold(article)
    check_privacy_footer(document)
    resources = check_local_resources(root, *resource_surfaces(document))
    return {"slug": SLUG, "article_body_sha256": sha256(body_bytes),
            "evidence_files": len(evidence), "quoted_lines": len(QUOTED_LINES),
            "mathml": math_count, "code_blocks": block_count, "resources": sorted(resources),
            "spend_before": "1.944", "spend_after": "0.402", "offline": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(check(args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
