# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Bind fleetdiff source pins and collector release/advisory pins, optionally live."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from outsider import Blocks, ROOT
from own_data import FIXTURE_COMMIT, FIXTURE_VERSION

REPOSITORY = "https://github.com/llm-measurement/fleetdiff.git"
PIN = re.compile(
    r"https://(?:raw\.githubusercontent\.com|github\.com|codeload\.github\.com)"
    r"/llm-measurement/fleetdiff/(?:blob/|tree/|tar\.gz/)?([0-9a-fA-F]{7,40})(?=[/#\s\"'<>`)]|$)"
)


def resolve_tag(tag):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("expected a fleetdiff release tag")
    ref = "refs/tags/" + tag
    # This read is anonymous and must not depend on local Git URL rewrites.
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "SYSTEMROOT", "LANG", "LC_ALL"}}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0")
    with tempfile.TemporaryDirectory(prefix="site-tag-check-") as fresh:
        # Git ignores the current directory as a ceiling; stop at its parent.
        env["GIT_CEILING_DIRECTORIES"] = str(Path(fresh).parent)
        result = subprocess.run(["git", "ls-remote", "--exit-code", REPOSITORY, ref, ref + "^{}"],
                                cwd=fresh, env=env, text=True, capture_output=True, timeout=60, check=True)
    refs = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if (len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{40}", fields[0])
                or fields[1] not in {ref, ref + "^{}"} or fields[1] in refs):
            raise ValueError("unexpected fleetdiff tag resolution")
        refs[fields[1]] = fields[0]
    if ref not in refs:
        raise ValueError("fleetdiff release tag was not found")
    return refs.get(ref + "^{}", refs[ref])


def check_source(name, source, commit, version=FIXTURE_VERSION):
    if name == "evidence/README.md":
        start, end = "<!-- historical-verification:start -->", "<!-- historical-verification:end -->"
        assert source.count(start) == source.count(end) == 1
        before, history = source.split(start)
        _, after = history.split(end)
        source = before + after
    pins = PIN.findall(source)
    for pin in pins:
        if pin != commit:
            raise ValueError(f"{name}: fleetdiff pin {pin} != {version} commit {commit}")
    blocks = Blocks()
    blocks.feed(source)
    for block in blocks.commands + blocks.own + blocks.review:
        if not PIN.search(block["text"]):
            continue
        words = shlex.split(block["text"])
        installer_urls = [word for word in words if word.startswith("https://raw.githubusercontent.com/llm-measurement/fleetdiff/")
                          and word.endswith("/scripts/install.sh")]
        if installer_urls:
            versions = [words[index + 1] for index, word in enumerate(words[:-1])
                        if index > 0 and words[index - 1] in {"sh", "bash"}
                        and word in {"install-fleetdiff.sh", "./install-fleetdiff.sh", "scripts/install.sh"}]
            if versions != [version]:
                raise ValueError(f"{name}: pinned installer must explicitly install {version}")
    return len(pins)


def check(root=ROOT, live=False):
    commit = resolve_tag(FIXTURE_VERSION) if live else FIXTURE_COMMIT
    if commit != FIXTURE_COMMIT:
        raise ValueError(f"{FIXTURE_VERSION} resolves to {commit}, not recorded {FIXTURE_COMMIT}")
    paths = [root / "README.md", root / "evidence/README.md", root / ".github/workflows/docs.yml"]
    paths += sorted((root / "pages").glob("*.html"))
    paths += sorted((root / "docs").glob("*.html"))
    paths += [root / "docs/llms.txt"]
    langfuse = json.loads((root / "evidence/langfuse-release.json").read_text())
    if live and resolve_tag(langfuse["version"]) != langfuse["commit"]:
        raise ValueError("Langfuse guide release tag changed")
    count = sum(check_source(str(path.relative_to(root)), path.read_text(),
                            langfuse["commit"] if path.name == "langfuse-spend.html" else commit,
                            langfuse["version"] if path.name == "langfuse-spend.html" else FIXTURE_VERSION)
                for path in paths)
    if not count:
        raise ValueError("no fleetdiff commit pins found")
    note = (root / "evidence/README.md").read_text()
    if f"Installer URLs pin `{commit}`" not in note:
        raise ValueError("evidence README installer revision does not match the release")
    record = json.loads((root / "evidence/own-data-verified.json").read_text())
    archive = record["fixture_archive"]
    if (record["fixture_source"] != commit or archive["expected_commit"] != commit
            or archive["version"] != FIXTURE_VERSION):
        raise ValueError("own-data verification source does not match the release")
    for result in record["results"]:
        if "installed_version" in result:
            if result["installed_version"].split()[:3] != ["fleetdiff", FIXTURE_VERSION, f"({commit})"]:
                raise ValueError("verified installed binary does not match the release")
    mode = "live tag resolution" if live else "recorded release (offline)"
    print(f"PASS: {count} release-bound fleetdiff pins; existing guides {FIXTURE_VERSION}, Langfuse {langfuse['version']}; {mode}")
    from collector_pins import check as check_collector
    check_collector(root, live=live)
