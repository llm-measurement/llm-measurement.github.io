# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Deliberately seed pinned public release bytes, only from protected site main."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

import release_cache as cache

REPOSITORY = "llm-measurement/llm-measurement.github.io"
WORKFLOW = REPOSITORY + "/.github/workflows/seed-release-cache.yml@refs/heads/main"


def seed_origin(env):
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main", "GITHUB_REF_PROTECTED": "true",
                "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_WORKFLOW_REF": WORKFLOW}
    if any(env.get(key) != value for key, value in expected.items()):
        raise ValueError("seed requires manual dispatch of the protected main workflow")
    commit = env.get("GITHUB_SHA", "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("invalid site source commit")
    if env.get("GITHUB_WORKFLOW_SHA") != commit:
        raise ValueError("seed workflow and checked-out site source must match")
    return {"repository": REPOSITORY, "workflow": WORKFLOW, "ref": "refs/heads/main",
            "site_commit": commit, "run_id": int(env["GITHUB_RUN_ID"]),
            "run_attempt": int(env["GITHUB_RUN_ATTEMPT"]), "protected_ref": True}


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        target = urllib.parse.urlsplit(new_url)
        if target.scheme != "https" or target.hostname != "release-assets.githubusercontent.com" or target.username or target.password:
            raise ValueError("release redirect outside the approved content host")
        return super().redirect_request(request, file, code, message, headers, new_url)


def record(log, value):
    with log.open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")


def download_asset(name, checksum, destination, log, origin, opener):
    url = "https://github.com/llm-measurement/fleetdiff/releases/download/" + cache.spec()["version"] + "/" + name
    event = {"asset": name, "url": url, "purpose": "deliberate protected-main cache seed",
             "run_id": origin["run_id"], "run_attempt": origin["run_attempt"],
             "started_at": datetime.now(timezone.utc).isoformat(), "status": "started"}
    record(log, event)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "site-deliberate-release-cache-seed"})
        with opener.open(request, timeout=120) as response:
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024 or cache.digest(data) != checksum:
            raise ValueError("release asset size or digest mismatch")
        with (destination / name).open("xb") as stream:
            stream.write(data)
    except Exception as error:
        record(log, dict(event, status="failed", error_type=type(error).__name__,
                         finished_at=datetime.now(timezone.utc).isoformat()))
        raise RuntimeError("seed asset request failed: " + name + " (" + type(error).__name__ + ")") from None
    record(log, dict(event, status="verified", bytes=len(data), sha256=cache.digest(data),
                     finished_at=datetime.now(timezone.utc).isoformat()))


def seed(source, work, output):
    origin = seed_origin(os.environ)
    work.mkdir(mode=0o700)
    assets = work / "assets"
    assets.mkdir(mode=0o700)
    log = work / "deliberate-downloads.jsonl"
    log.touch(exist_ok=False)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ReleaseRedirect())
    for name, checksum in cache.spec()["assets"].items():
        download_asset(name, checksum, assets, log, origin, opener)
    cache.prepare(assets, source, output)
    (output / "seed-origin.json").write_text(json.dumps(origin, indent=2) + "\n")
    (output / "deliberate-downloads.jsonl").write_bytes(log.read_bytes())
    inventory = json.dumps(cache.member_hashes(output), sort_keys=True, indent=2).encode() + b"\n"
    (output / "cache-members.json").write_bytes(inventory)
    checksum = cache.digest(inventory)
    cache.verify_cache(output, checksum)
    print("Verified deliberate cache seed; manifest SHA256 " + checksum)
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("manifest_sha256=" + checksum + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seed(args.source, args.work, args.output)


if __name__ == "__main__":
    main()
