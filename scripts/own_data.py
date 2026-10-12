# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Exercise published own-data commands with local stand-ins and real tools."""
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid

from outsider import Blocks, ROOT

PAGES = ("index", "token-spike", "litellm-spend", "cache-check", "cardinality",
         "traces-usage", "anomalies", "distinct-users", "tokenmaxxing")
EXPECTED = {
    "home-spend": ("Logged model requests:", "Who drove", "user-1:"),
    "home-traces": ("Your traces can fully answer 2 of 7 questions.",),
    "home-python": ("Successfully installed",),
    "home-go": (),
    "token-spike": ("Logged model requests:", "user-1:"),
    "token-spike-summaries": ("Reported tokens: 400 -> 3300", "user-1"),
    "litellm-spend": ("Logged model requests:", "key-1:"),
    "spend-export": ("Exported request-level rows to ./litellm-export/spend.csv",),
    "litellm-install": ("Verified", "installation in ././bin"),
    "cache-check": ("Cache-read share of recorded input:", "session-1:"),
    "cardinality": ("2 problems to fix:", "enduser.id is a metric label"),
    "traces-usage": ("4 model attempts across 6 captured spans; 170 reported tokens.",),
    "anomalies-install": ("Verified",),
    "anomalies": ("2 unusual windows among 2 checked.", "coverage change, not lower usage"),
    "distinct-users": ("Estimated distinct users: 3",),
    "tokenmaxxing": ("Estimated distinct users: 3", "Recorded tokens: 4,800",
                     "user-1: [3,600, 3,600] tokens", "100.0% to 100.0%"),
}


def run(command, *, cwd, env, data=None, timeout=1800):
    result = subprocess.run(command, cwd=cwd, env=env, input=data, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Test setup failed: {command[0]}\n{result.stderr}")
    return result.stdout


def environment(fresh):
    env = dict(os.environ)
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "PYTHONPATH", "PYTHONHOME", "PGPASSWORD", "PGSERVICEFILE"):
        env.pop(key, None)
    env.update({"GH_CONFIG_DIR": str(fresh / "gh"), "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
        "GOWORK": "off", "GOTOOLCHAIN": "go1.26.9", "PYTHONNOUSERSITE": "1", "GOCACHE": str(fresh / "go-build"),
        "GOMODCACHE": str(fresh / "go-mod"), "PIP_CACHE_DIR": str(fresh / "pip")})
    return env


def prepare(fresh, source, env, slug):
    run(["python3", str(source / "examples/litellm-spend/generate.py"), "--rows", "160",
         "--days", "16", "--format", "csv", "--output", str(fresh / "spend.csv")], cwd=fresh, env=env)
    shutil.copyfile(source / "examples/inspect/synthetic-traces.json", fresh / "traces.jsonl")
    shutil.copyfile(source / "examples/diagnose/unsafe.yaml", fresh / "collector.yaml")
    for name in ("before", "after"):
        shutil.copytree(source / "examples/sessions/data" / name, fresh / name)
    (fresh / "usage.csv").write_text("user_id,tokens\nprivate-ana,1200\nprivate-ben,300\nprivate-ana,2400\nprivate-cy,900\n")
    if slug == "cache-check":
        with (source / "examples/litellm-spend/cache-drop.csv").open() as handle:
            originals = list(csv.DictReader(handle))
        with (fresh / "spend.csv").open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=originals[0].keys())
            writer.writeheader()
            for day in range(16):
                for index, original in enumerate(originals[:2] if day < 8 else originals[2:]):
                    row = dict(original)
                    date = datetime(2026, 9, 23, tzinfo=timezone.utc).timestamp() + day * 86400
                    date = datetime.fromtimestamp(date, timezone.utc).strftime("%Y-%m-%d")
                    row.update(request_id=f"cache-{day}-{index}", session_id=row["api_key"],
                               startTime=date + "T12:00:00Z", endTime=date + "T12:00:01Z")
                    writer.writerow(row)
    if slug == "anomalies":
        run(["go", "run", "./examples/scan", "--out", str(fresh / "summary-history")], cwd=source, env=env)


def refresh_history(directory, now):
    # Refresh only the stand-in, after downloads and before the exact scan block.
    windows = [(path, json.loads(path.read_text())) for path in directory.glob("*.json")]
    assert len(windows) == 30
    end = int(now) // 60 * 60 * 1_000_000_000
    delta = end - max(window["observed_end_unix_nano"] for _, window in windows)
    for path, window in windows:
        for key in ("window_start_unix_nano", "observed_start_unix_nano", "observed_end_unix_nano", "emitted_at_unix_nano"):
            window[key] += delta
        path.write_text(json.dumps(window, sort_keys=True, separators=(",", ":")))


@contextmanager
def database(fresh, source, env):
    """Actual read-only Postgres; Docker transports psql, it does not stub it."""
    name = "site-export-" + uuid.uuid4().hex[:12]
    image = json.loads((source / "examples/litellm-spend/images.json").read_text())["postgres"]
    started = False
    try:
        run(["docker", "run", "-d", "--name", name, "--network", "none", "--rm",
             "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=fixture",
             "-v", f"{fresh}:{fresh}", image], cwd=fresh, env=env)
        started = True
        for _ in range(60):
            process = subprocess.run(["docker", "exec", name, "cat", "/proc/1/comm"], capture_output=True, text=True)
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "fixture"], capture_output=True)
            if process.stdout.strip() == "postgres" and ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Test database did not become ready")
        sql = (source / "examples/litellm-spend/test-schema.sql").read_text()
        with (fresh / "spend.csv").open() as handle:
            assert next(csv.reader(handle)) == ["request_id", "call_type", "api_key", "user", "team_id", "organization_id", "end_user", "model", "model_id", "model_group", "custom_llm_provider", "prompt_tokens", "completion_tokens", "total_tokens", "spend", "status", "session_id", "startTime", "endTime"]
        sql += '\nCOPY public."LiteLLM_SpendLogs" (request_id,call_type,api_key,"user",team_id,organization_id,end_user,model,model_id,model_group,custom_llm_provider,prompt_tokens,completion_tokens,total_tokens,spend,status,session_id,"startTime","endTime") FROM STDIN WITH CSV HEADER;\n'
        sql += (fresh / "spend.csv").read_text() + "\\.\n"
        run(["docker", "exec", "-i", name, "psql", "-U", "postgres", "-d", "fixture", "-v", "ON_ERROR_STOP=1"], cwd=fresh, env=env, data=sql)
        service = fresh / "pg_service.conf"
        service.write_text("[litellm_readonly]\nhost=/var/run/postgresql\nuser=fixture_reader\ndbname=fixture\n")
        wrappers = fresh / "test-tools"
        wrappers.mkdir()
        wrapper = wrappers / "psql"
        wrapper.write_text("#!/bin/sh\nexec docker exec --user " + str(os.getuid()) + ":" + str(os.getgid()) +
            " -e PGSERVICEFILE=" + shlex.quote(str(service)) + " -w " + shlex.quote(str(fresh)) + " " +
            shlex.quote(name) + ' psql "$@"\n')
        wrapper.chmod(0o700)
        db_env = dict(env, PATH=str(wrappers) + os.pathsep + env["PATH"],
                      START_UTC="2026-09-23T00:00:00Z", END_UTC="2026-10-09T00:00:00Z")
        yield db_env
    finally:
        if started:
            cleanup = subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            if cleanup.returncode:
                print(f"Cleanup needed: docker rm -f {name}")


def check(output, page=None):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="site-own-source-") as directory:
        fixture_root = Path(directory)
        env = environment(fixture_root)
        source = fixture_root / "fleetdiff"
        run(["git", "clone", "--depth", "1", "--branch", "v0.8.0",
             "https://github.com/llm-measurement/fleetdiff.git", str(source)], cwd=fixture_root, env=env)
        source_sha = run(["git", "rev-parse", "HEAD"], cwd=source, env=env).strip()
        for slug in PAGES:
            if page and slug != page:
                continue
            blocks = Blocks()
            blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
            assert blocks.own, slug
            with tempfile.TemporaryDirectory(prefix="site-own-" + slug + "-") as directory:
                fresh = Path(directory)
                env = environment(fresh)
                prepare(fresh, source, env, slug)
                for block in blocks.own:
                    begin = time.monotonic()
                    if block["id"] == "anomalies":
                        refresh_history(fresh / "summary-history", time.time())
                    def execute(selected_env):
                        return subprocess.run(["bash", "-e", "-c", block["text"]], cwd=fresh,
                            env=selected_env, text=True, capture_output=True, timeout=1800)
                    if block["id"] == "spend-export":
                        with database(fresh, source, env) as db_env:
                            try:
                                result = execute(db_env)
                            finally:
                                for diagnostics in fresh.glob("litellm-export/private-psql.*"):
                                    shutil.copyfile(diagnostics, output / diagnostics.name)
                    else:
                        result = execute(env)
                    (output / (block["id"] + ".stdout.txt")).write_text(result.stdout)
                    (output / (block["id"] + ".stderr.txt")).write_text(result.stderr)
                    assert result.returncode == block["exit"], (slug, block["id"], result.returncode, result.stderr)
                    for excerpt in EXPECTED[block["id"]]:
                        assert excerpt in result.stdout, (block["id"], excerpt, result.stdout)
                    if block["id"] == "home-go":
                        assert "github.com/llm-measurement/llm-sketchkit v0.3.0" in (fresh / "measurement-go/go.mod").read_text()
                    if block["id"] == "spend-export":
                        exported = fresh / "litellm-export/spend.csv"
                        with exported.open() as handle:
                            rows = list(csv.DictReader(handle))
                        assert len(rows) == 160 and "messages" not in rows[0] and "response" not in rows[0]
                        assert "cache_read_input_tokens" in rows[0] and rows[0]["cache_read_input_tokens"] == ""
                    assert all(raw not in result.stdout for raw in ("private-ana", "private-ben", "private-cy"))
                    records.append({"page": slug, "block": block["id"], "pass": True,
                        "exit": result.returncode, "seconds": round(time.monotonic() - begin, 2),
                        "command_sha256": hashlib.sha256(block["text"].encode()).hexdigest(),
                        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest()})
                    print(f"PASS own data: {slug}/{block['id']}; exit {result.returncode}", flush=True)
    manifest = {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
                "fixture_source": source_sha, "method": "Exact published commands; fresh directories/caches; anonymous fixture clone; real released installer, CLI and library; SQL uses real read-only Postgres via Docker psql.", "results": records}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
