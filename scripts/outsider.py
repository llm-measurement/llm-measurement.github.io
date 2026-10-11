# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Run the exact published command blocks in independent fresh directories."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


class Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.commands = []
        self.expected = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "pre":
            if "data-run" in attrs:
                self.current = (self.commands, {"text": "", "exit": int(attrs["data-exit"])})
            elif "data-output" in attrs:
                self.current = (self.expected, {"text": ""})

    def handle_endtag(self, tag):
        if tag == "pre" and self.current:
            self.current[0].append(self.current[1])
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.current[1]["text"] += data


def normalize(text):
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page", choices=["cardinality", "token-spike", "tokenmaxxing", "litellm-spend", "anomalies", "traces-usage", "distinct-users"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    pages = json.loads((ROOT / "pages.json").read_text())
    for page in pages:
        slug = page["slug"]
        if slug == "index" or page.get("kind") == "evidence" or (args.page and slug != args.page):
            continue
        blocks = Blocks()
        source = (ROOT / "pages" / (slug + ".html")).read_text()
        blocks.feed(source)
        assert len(blocks.commands) == 1 and blocks.expected
        with tempfile.TemporaryDirectory(prefix="llm-guide-") as fresh:
            env = dict(os.environ)
            for key in ("GH_TOKEN", "GITHUB_TOKEN", "PYTHONPATH", "PYTHONHOME"):
                env.pop(key, None)
            env.update({
                "GH_CONFIG_DIR": fresh + "/gh", "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper",
                "GIT_CONFIG_VALUE_0": "", "GOWORK": "off", "PYTHONNOUSERSITE": "1",
                "GOCACHE": fresh + "/go-build", "GOMODCACHE": fresh + "/go-mod",
                "PIP_CACHE_DIR": fresh + "/pip",
            })
            begin = time.monotonic()
            result = subprocess.run(
                ["bash", "-e", "-c", blocks.commands[0]["text"]],
                cwd=fresh, env=env, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=1800,
            )
            (args.output / (slug + ".stdout.txt")).write_text(result.stdout)
            (args.output / (slug + ".stderr.txt")).write_text(result.stderr)
            assert result.returncode == blocks.commands[0]["exit"], (slug, result.returncode)
            for excerpt in blocks.expected:
                assert normalize(excerpt["text"]) in normalize(result.stdout), (slug, excerpt["text"])
            records.append({
                "page": slug, "exit": result.returncode, "pass": True,
                "seconds": round(time.monotonic() - begin, 2),
                "command_sha256": hashlib.sha256(blocks.commands[0]["text"].encode()).hexdigest(),
                "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            })
            print(f"PASS: {slug}; exit {result.returncode}; every displayed excerpt matches", flush=True)
    manifest = {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version(), "results": records}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
