# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Run the security page's manual download-and-verify commands verbatim."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

from outsider import Blocks, ROOT
from own_data import environment


def review_environment(fresh, block):
    env = environment(fresh)
    env.update(HOME=str(fresh), DOCKER_CONFIG=str(fresh / "docker"),
               XDG_CACHE_HOME=str(fresh / "cache"))
    for name in ("COSIGN_PASSWORD", "DOCKER_AUTH_CONFIG"):
        env.pop(name, None)
    if block == "collector":
        # gh's OCI provenance API needs authentication even for public artifacts.
        config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gh"
        env["GH_CONFIG_DIR"] = os.environ.get("GH_CONFIG_DIR", str(config))
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            if name in os.environ:
                env[name] = os.environ[name]
    return env


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    blocks = Blocks()
    blocks.feed((ROOT / "pages/security.html").read_text())
    assert {b["id"] for b in blocks.review} == {"fleetdiff", "collector"}
    records = []
    for block in blocks.review:
        with tempfile.TemporaryDirectory(prefix="site-release-review-") as directory:
            fresh = Path(directory)
            env = review_environment(fresh, block["id"])
            result = subprocess.run(["bash", "-e", "-c", block["text"]], cwd=fresh,
                env=env, text=True, capture_output=True, timeout=1200)
            (output / (block["id"] + ".stdout.txt")).write_text(result.stdout)
            (output / (block["id"] + ".stderr.txt")).write_text(result.stderr)
            assert result.returncode == 0, (block["id"], result.stderr)
            if block["id"] == "fleetdiff":
                assert "fleetdiff v0.10.0" in result.stdout
            records.append({"block": block["id"], "pass": True, "exit": 0,
                "authentication": "credentialed GitHub API" if block["id"] == "collector" else "anonymous",
                "command_sha256": hashlib.sha256(block["text"].encode()).hexdigest(),
                "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest()})
            print(f"PASS release review: {block['id']}", flush=True)
    (output / "manifest.json").write_text(json.dumps({"system": platform.system(),
        "machine": platform.machine(), "method": "Exact published commands; fresh working directories, caches and Docker credential configuration; anonymous downloads and Cosign checks; collector GitHub API verification uses existing gh credentials; trusted verification tools supplied on PATH.",
        "results": records}, indent=2) + "\n")
