# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Exercise published own-data commands with synthetic inputs and real tools/DB."""
from contextlib import contextmanager
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import urllib.request

from outsider import Blocks, ROOT
from postgres_transport import postgres_transport

PAGES = ("index", "token-spike", "litellm-spend", "session-budget", "cache-check", "cardinality",
         "traces-usage", "anomalies", "distinct-users", "tokenmaxxing", "row-coverage", "routing", "what-if", "security")
FIXTURE_VERSION = "v0.12.1"
# Must match the release source commit; installed binaries are checked against it.
FIXTURE_COMMIT = "0d7db95c5bb3013f8c564c91fbb07b6235a2664e"
FIXTURE_URL = "https://codeload.github.com/llm-measurement/fleetdiff/tar.gz/" + FIXTURE_COMMIT
EXPORT_START = "2026-09-23T00:00:00Z"
EXPORT_END = "2026-10-09T00:00:00Z"
EXPECTED = {
    "home-spend": ("Logged model requests:", "Who drove", "user-1:"),
    "home-traces": ("Your traces can fully answer 2 of 7 questions.",),
    "home-python": ("Successfully installed",),
    "home-go": (),
    "token-spike": ("Logged model requests:", "user-1:"),
    "token-spike-install": ("Verified",),
    "token-spike-summaries": ("Reported tokens: 400 -> 3300", "user-1"),
    "litellm-spend": ("Logged model requests:", "key-1:"),
    "litellm-export-file": ("Logged model requests: 70 -> 70.", "key-1:"),
    "litellm-native": ("Logged model requests: 70 -> 70.", "key-1:"),
    "litellm-native-env": ("Logged model requests: 70 -> 70.", "key-1:"),
    "session-budget": ("3 of 4 sessions with complete recorded spend exceed the supplied USD 1.00 cap.",
                       "Recorded USD: p50 1.10; p95 1.60; max 1.60 (n=4, exact nearest-rank).",
                       "Above-cap sessions with no recorded session-budget rejection: 2."),
    "session-budget-install": ("Verified",),
    "session-budget-native": ("3 of 4 sessions with complete recorded spend exceed the supplied USD 1.00 cap.",
                       "Recorded USD: p50 1.10; p95 1.60; max 1.60 (n=4, exact nearest-rank).",
                       "Above-cap sessions with no recorded session-budget rejection: 2.",
                       "session_budget recorded rejections: 1."),
    "spend-export": ("Exported request-level rows to ./litellm-export/spend.csv",),
    "litellm-install": ("Verified", "installation in ././bin"),
    "cache-check": ("Cache-read share of recorded input:", "session-1:"),
    "cache-check-install": ("Verified",),
    "cache-check-native": ("Cache-read share of recorded input:", "session-1:"),
    "cardinality": ("2 problems to fix:", "enduser.id is a metric label"),
    "traces-usage": ("4 model attempts across 6 captured spans; 170 reported tokens.",),
    "anomalies-install": ("Verified",),
    "anomalies": ("2 unusual windows among 2 checked.", "coverage change, not lower usage"),
    "distinct-users": ("Estimated distinct users: 3",),
    "tokenmaxxing": ("Estimated distinct users: 3", "Recorded tokens: 4,800",
                     "user-1: [3,600, 3,600] tokens", "100.0% to 100.0%"),
    "row-coverage-export": ("Exported spend.csv and daily.csv in the new private output directory.",),
    "row-coverage-install": ("Verified", "fleetdiff v0.12.1 (" + FIXTURE_COMMIT + ")"),
    "row-coverage-native": ("Spend-log row coverage (relative to LiteLLM daily request counts):",
                            "8 exported rows; 9 daily requests (8 successful, 1 failed); 1 missing row."),
    "row-coverage": ("Spend-log row coverage (relative to LiteLLM daily request counts):",
                     "2026-10-07 UTC: 8 exported rows; 9 daily requests (8 successful, 1 failed); 1 missing row."),
    "row-coverage-export-files": ("Spend-log row coverage (relative to LiteLLM daily request counts):",
                     "2026-10-07 UTC: 8 exported rows; 9 daily requests (8 successful, 1 failed); 1 missing row."),
    "what-if-install": ("Verified",),
    "what-if-native": ("$0.154400 -> $0.109398 to $0.147974", "Level 1, same work and output verbosity: $0.148703",
                        "Coverage: 3 observations priced; missing splits are excluded, never zero.", "missing split: 1"),
    "what-if-reprice": ("$0.154400 -> $0.109398 to $0.147974", "Level 1, same work and output verbosity: $0.148703",
                        "Coverage: 3 observations priced; missing splits are excluded, never zero.", "missing split: 1"),
    "what-if-workload-map": (),
    "routing-export": ("Exported routing details to ./routing-export/spend.csv",),
    "routing-install": ("Verified",),
    "routing-native": ("Model-request rows: 3 -> 3 requests; 360 -> 360 recorded tokens;",
                       "Classifier routing overhead: 1 -> 1 rows;", "agent known: 0 -> 0; unknown: 1 -> 1"),
    "routing-audit": ("Model-request rows: 3 -> 3 requests; 360 -> 360 recorded tokens;",
                      "Classifier routing overhead: 1 -> 1 rows;", "agent known: 0 -> 0; unknown: 1 -> 1"),
    "routing-export-file": ("Model-request rows: 3 -> 3 requests; 360 -> 360 recorded tokens;",
                      "Classifier routing overhead: 1 -> 1 rows;", "agent known: 0 -> 0; unknown: 1 -> 1"),
    "routing-agents": (),
    "routing-scope": ("Model-request rows: 2 -> 2 requests; 240 -> 240 recorded tokens;",),
}
NATIVE_BLOCKS = {"litellm-native", "litellm-native-env", "routing-native", "routing-agents", "routing-scope",
                 "row-coverage-native", "session-budget-native", "cache-check-native", "what-if-native"}


def page_blocks(slug):
    blocks = Blocks()
    blocks.feed((ROOT / "pages" / (slug + ".html")).read_text())
    return blocks


def installed_version(fresh, env):
    version = run([str(fresh / "bin/fleetdiff"), "--version"], cwd=fresh, env=env).strip()
    assert version.split()[:3] == ["fleetdiff", FIXTURE_VERSION, "(" + FIXTURE_COMMIT + ")"], version
    return version


def run(command, *, cwd, env, data=None, timeout=1800):
    result = subprocess.run(command, cwd=cwd, env=env, input=data, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Test setup failed: {command[0]}\n{result.stderr}")
    return result.stdout


def environment(fresh):
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SYSTEMROOT", "DOCKER_HOST"}}
    env.update({"HOME": str(fresh), "XDG_CONFIG_HOME": str(fresh / "config"),
        "XDG_CACHE_HOME": str(fresh / "cache"), "GH_CONFIG_DIR": str(fresh / "gh"),
        "DOCKER_CONFIG": str(fresh / "docker"), "TMPDIR": str(fresh),
        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GOWORK": "off", "GOTOOLCHAIN": "go1.26.9", "PYTHONNOUSERSITE": "1", "GOCACHE": str(fresh / "go-build"),
        "GOMODCACHE": str(fresh / "go-mod"), "GOPROXY": "https://proxy.golang.org", "GOSUMDB": "sum.golang.org",
        "GOENV": "off", "GOTELEMETRY": "off", "PIP_CONFIG_FILE": os.devnull,
        "PIP_INDEX_URL": "https://pypi.org/simple", "PIP_CACHE_DIR": str(fresh / "pip")})
    return env


def extract_fixture(archive, root):
    if not callable(getattr(tarfile, "data_filter", None)):
        raise RuntimeError("Python tarfile data filter support is required (use an updated Python 3.11+).")
    expected_root = "fleetdiff-" + FIXTURE_COMMIT
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        assert len(members) <= 10000 and sum(m.size for m in members) <= 128 * 1024 * 1024
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            assert path.parts and not path.is_absolute() and ".." not in path.parts and path.parts[0] == expected_root
            assert ".git" not in path.parts and (member.isdir() or member.isfile())
            assert path.as_posix() not in names and not member.mode & 0o6000
            names.add(path.as_posix())
        source = root / expected_root
        assert not source.exists()
        bundle.extractall(root, members=members, filter="data")
    assert (source / "go.mod").is_file() and (source / "examples/litellm-spend/export.sql").is_file()
    return source


def fixture_source(root):
    if not callable(getattr(tarfile, "data_filter", None)):
        raise RuntimeError("Python tarfile data filter support is required before downloading fixtures.")
    request = urllib.request.Request(FIXTURE_URL, headers={"User-Agent": "site-own-data-verifier"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=120) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    assert len(data) <= 32 * 1024 * 1024, "fixture archive exceeds size bound"
    archive = root / "fleetdiff-source.tar.gz"
    archive.write_bytes(data)
    source = extract_fixture(archive, root)
    files = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(source.rglob("*")) if path.is_file()}
    inventory = "".join(f"{checksum}  {name}\n" for name, checksum in files.items())
    provenance = {"version": FIXTURE_VERSION, "expected_commit": FIXTURE_COMMIT, "url": FIXTURE_URL,
        "archive_sha256": hashlib.sha256(data).hexdigest(), "archive_bytes": len(data),
        "archive_root": source.name, "source_sha256": hashlib.sha256(inventory.encode()).hexdigest(),
        "files": files, "git_operations": False}
    return source, provenance


def prepare(fresh, source, env, slug):
    run(["python3", str(source / "examples/litellm-spend/generate.py"), "--rows", "160",
         "--days", "16", "--format", "csv", "--output", str(fresh / "spend.csv")], cwd=fresh, env=env)
    shutil.copyfile(source / "examples/inspect/synthetic-traces.json", fresh / "traces.jsonl")
    shutil.copyfile(source / "examples/diagnose/unsafe.yaml", fresh / "collector.yaml")
    for name in ("before", "after"):
        shutil.copytree(source / "examples/sessions/data" / name, fresh / name)
    (fresh / "usage.csv").write_text("user_id,tokens\nprivate-ana,1200\nprivate-ben,300\nprivate-ana,2400\nprivate-cy,900\n")
    if slug == "session-budget":
        shutil.copyfile(source / "examples/litellm-spend/session-budget.csv", fresh / "spend.csv")
    if slug == "what-if":
        for name in ("spend.csv", "workload-map.json"):
            shutil.copyfile(source / "examples/what-if" / name, fresh / name)
        env["PERIOD"] = "2026-10-07"
        prepare_workload_map(fresh, source)
    if slug == "routing":
        with (source / "examples/routing/synthetic.csv").open() as handle:
            reader = csv.DictReader(handle)
            columns, rows = reader.fieldnames, list(reader)
        columns += ["team_id", "organization_id", "end_user", "custom_llm_provider",
                    "rejection_kind", "reasoning_output_tokens"]
        with (fresh / "spend.csv").open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                for name in ("api_key", "user", "session_id", "agent_id", "model_id",
                             "model_group", "original_model_group"):
                    if row[name]:
                        row[name] = "SENTINEL_" + row[name]
                writer.writerow(row)
        env.update(BEFORE="2026-10-01", AFTER="2026-10-02",
                   ROUTE="SENTINEL_coding-default")
    if slug == "row-coverage":
        with (fresh / "spend.csv").open() as handle:
            earlier = [row for row in csv.DictReader(handle) if row["startTime"] < "2026-10-07"]
        with (source / "examples/litellm-spend/coverage_runtime_spend.csv").open() as handle:
            reader = csv.DictReader(handle)
            columns, coverage = reader.fieldnames, list(reader)
        with (fresh / "spend.csv").open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(earlier + coverage)
        with (source / "examples/litellm-spend/coverage_runtime_daily.csv").open() as handle:
            daily = list(csv.DictReader(handle))
        for day in sorted({row["startTime"][:10] for row in earlier}):
            selected = [row for row in earlier if row["startTime"].startswith(day)]
            failed = sum(row["status"] == "failure" for row in selected)
            daily.append(dict(date=day, api_requests=len(selected), successful_requests=len(selected) - failed,
                              failed_requests=failed))
        with (fresh / "daily.csv").open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "api_requests", "successful_requests", "failed_requests"])
            writer.writeheader()
            writer.writerows(daily)
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


def prepare_workload_map(fresh, source):
    blocks = page_blocks("what-if").configs
    assert [b["id"] for b in blocks] == ["what-if-workload-map"]
    raw = blocks[0]["text"].encode()
    published = json.loads(raw)
    original = json.loads((source / "examples/what-if/workload-map.json").read_text())
    assert published["version"] == original["version"] == 1
    assert len(published["mappings"]) == len(original["mappings"]) == 2
    replacements = {}
    for old, new in zip(original["mappings"], published["mappings"]):
        assert old["workload"] == new["workload"]
        assert old["selector"]["kind"] == new["selector"]["kind"]
        column = {"key": "api_key", "team": "team_id"}[new["selector"]["kind"]]
        replacements[column] = (old["selector"]["value"], new["selector"]["value"])
    with (fresh / "spend.csv").open() as handle:
        reader = csv.DictReader(handle)
        columns, rows = reader.fieldnames, list(reader)
    for column, (old, new) in replacements.items():
        assert any(row[column] == old for row in rows), "published selector has no fixture match"
        for row in rows:
            if row[column] == old:
                row[column] = new
    with (fresh / "spend.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (fresh / "workload-map.json").write_bytes(raw)
    (fresh / "workload-map.json").chmod(0o600)


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


def refresh_database_dates(fresh, env, slug, now):
    """Move synthetic rows, not the CLI clock, into complete UTC windows."""
    end = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with (fresh / "spend.csv").open() as handle:
        reader = csv.DictReader(handle)
        columns, rows = reader.fieldnames, list(reader)
    for row in rows:
        old = datetime.fromisoformat(row["startTime"].replace("Z", "+00:00"))
        if slug == "routing":
            target = end - timedelta(days=14 if old.day == 1 else 7)
        else:
            target = end - timedelta(days=16) + timedelta(days=(old.date() - datetime(2026, 9, 23).date()).days)
        shift = target.date() - old.date()
        for name in ("startTime", "endTime"):
            original_date = datetime.fromisoformat(row[name].replace("Z", "+00:00")).date()
            row[name] = (original_date + shift).isoformat() + row[name][10:]
    with (fresh / "spend.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    if slug == "row-coverage":
        with (fresh / "daily.csv").open() as handle:
            reader = csv.DictReader(handle)
            columns, rows = reader.fieldnames, list(reader)
        shift = end.date() - datetime.fromisoformat(EXPORT_END.replace("Z", "+00:00")).date()
        for row in rows:
            row["date"] = (datetime.fromisoformat(row["date"]).date() + shift).isoformat()
        with (fresh / "daily.csv").open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    env.update(EXPORT_BEFORE=(end - timedelta(days=14 if slug == "routing" else 16)).isoformat(),
               EXPORT_AFTER=end.isoformat(),
               BEFORE=(end - timedelta(days=14)).date().isoformat(),
               AFTER=(end - timedelta(days=7)).date().isoformat())
    return end


def native_grants(source, daily=False):
    document = (source / "docs/NATIVE_EXPORT.md").read_text()
    blocks = re.findall(r"```sql\n(.*?)```", document, re.DOTALL)
    assert len(blocks) == 2 and "CREATE ROLE fleetdiff_reader" in blocks[0]
    assert 'ON TABLE public."LiteLLM_SpendLogs"' in blocks[0]
    assert 'ON TABLE public."LiteLLM_DailyUserSpend"' in blocks[1]
    grants = blocks[0] + (blocks[1] if daily else "")
    return grants


def database_fixture_variants(fresh, env, slug, now):
    """Keep historical file examples separate from clock-relative native inputs."""
    names = ("spend.csv", "daily.csv") if slug == "row-coverage" else ("spend.csv",)
    file_env = dict(env, EXPORT_BEFORE=EXPORT_START, EXPORT_AFTER=EXPORT_END)
    if slug == "routing":
        file_env.update(EXPORT_BEFORE="2026-10-01T00:00:00Z", EXPORT_AFTER="2026-10-03T00:00:00Z",
                        BEFORE="2026-10-01", AFTER="2026-10-02")
    historical = ({name: (fresh / name).read_bytes() for name in names}, file_env)
    native_env = dict(env)
    if slug == "what-if":
        # This page selects an explicit historical period, not a clock-relative default.
        day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        day = refresh_database_dates(fresh, native_env, slug, now)
    native = ({name: (fresh / name).read_bytes() for name in names}, native_env)
    return day, {"file": historical, "native": native}


def page_native_grants(slug):
    if slug == "litellm-spend":
        return page_blocks(slug).sql
    if slug == "row-coverage":
        # The row page links the shared role definition and publishes its own daily grant.
        shared = page_blocks("litellm-spend").sql
        assert [b["id"] for b in shared] == ["litellm-reader-grants", "litellm-daily-grants"]
        daily = page_blocks(slug).sql
        assert [b["id"] for b in daily] == ["row-coverage-daily-grants"]
        return [shared[0], daily[0]]
    return None


def published_grants(source, blocks):
    """Match released SQL; execute the decoded page text, never a rewritten copy."""
    released = re.findall(r"```sql\n(.*?)```", (source / "docs/NATIVE_EXPORT.md").read_text(), re.DOTALL)
    assert len(released) == 2
    assert [b["id"] for b in blocks] in (
        ["litellm-reader-grants", "litellm-daily-grants"],
        ["litellm-reader-grants", "row-coverage-daily-grants"])
    for block, expected in zip(blocks, released):
        # Markdown fences end with a newline; HTML may end directly at </code>.
        assert block["text"].removesuffix("\n") == expected.removesuffix("\n"), block["id"]
    return blocks


def database_sql(fresh, source, coverage=False, routing=False, details=False):
    sql = (source / "examples/litellm-spend/test-schema.sql").read_text()
    # Only the disposable fixture role changes database name, never page SQL.
    sql = sql.replace("CONNECT ON DATABASE fixture", "CONNECT ON DATABASE litellm")
    columns = ["request_id", "call_type", "api_key", "user", "team_id", "organization_id", "end_user",
               "model", "model_id", "model_group", "custom_llm_provider", "prompt_tokens", "completion_tokens",
               "total_tokens", "spend", "status", "session_id", "startTime", "endTime"]
    with (fresh / "spend.csv").open() as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        if not (coverage or routing or details):
            assert reader.fieldnames == columns
    if coverage or routing or details:
        columns += ["agent_id", "metadata"]
    payload = io.StringIO()
    writer = csv.DictWriter(payload, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for original in rows:
        row = dict(original)
        if coverage or routing or details:
            usage = {}
            for field, target in (("cache_read_input_tokens", "cache_read_input_tokens"),
                                  ("cache_write_input_tokens", "cache_creation_input_tokens")):
                if row.get(field, "") != "":
                    usage[target] = int(row[field])
            if row.get("reasoning_output_tokens", "") != "":
                usage["completion_tokens_details"] = {"reasoning_tokens": int(row["reasoning_output_tokens"])}
            metadata = {"additional_usage_values": usage}
            if row.get("rejection_kind"):
                assert details and row["rejection_kind"] == "session_budget" and row["status"] == "failure"
                # Content-free synthetic fixture matching every released SQL discriminator.
                metadata["error_information"] = {
                    "error_code": "429", "error_class": "ProxyRateLimitError",
                    "error_rate_limit_category": "litellm_rate_limit", "error_rate_limit_type": "budget",
                    "error_message": "litellm.RateLimitError: Session budget exceeded for session SENTINEL_TEST.",
                }
            if routing:
                metadata.update({field: row[field] for field in
                    ("original_model_group", "attempted_fallbacks", "internal_call_origin") if row.get(field)})
            row["metadata"] = json.dumps(metadata)
            if details and "spend" not in row:
                # What-if's token-only fixture has no recorded cost. A deliberate
                # synthetic $1 value proves repricing does not use recorded spend.
                row["spend"] = "1"
        writer.writerow(row)
    sql += '\nCOPY public."LiteLLM_SpendLogs" (' + ','.join('"' + name + '"' for name in columns)
    sql += ") FROM STDIN WITH CSV HEADER;\n" + payload.getvalue() + "\\.\n"
    if routing:
        sql += "ALTER ROLE fixture_reader SET default_transaction_read_only = on;\n"
    if coverage:
        sql += '''CREATE TABLE public."LiteLLM_DailyUserSpend" (
            date text NOT NULL, api_requests bigint NOT NULL,
            successful_requests bigint NOT NULL, failed_requests bigint NOT NULL);
            GRANT SELECT ON public."LiteLLM_DailyUserSpend" TO fixture_reader;
            ALTER ROLE fixture_reader SET default_transaction_read_only = on;
            COPY public."LiteLLM_DailyUserSpend" (date,api_requests,successful_requests,failed_requests)
            FROM STDIN WITH CSV HEADER;
'''
        sql += (fresh / "daily.csv").read_text() + "\\.\n"
    return sql


def comparable_rows(rows):
    normalized = []
    for original in rows:
        row = dict(original)
        for name in ("startTime", "endTime"):
            row[name] = datetime.fromisoformat(row[name])
        row["spend"] = Decimal(row["spend"])
        normalized.append(row)
    return sorted(normalized, key=lambda row: row["request_id"])


@contextmanager
def database(fresh, source, env, coverage=False, routing=False, native=False, sql_blocks=None, details=False):
    """Actual read-only Postgres; Docker transports psql, it does not stub it."""
    name = "site-export-" + uuid.uuid4().hex[:12]
    image = json.loads((source / "examples/litellm-spend/images.json").read_text())["postgres"]
    env = dict(env)
    if "DOCKER_HOST" not in env:
        env["DOCKER_HOST"] = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True, text=True, check=True).stdout.strip()
    started = False
    try:
        assert re.fullmatch(r"postgres@sha256:[0-9a-f]{64}", image), "Postgres must be digest pinned"
        inspected = json.loads(run(["docker", "image", "inspect", image], cwd=fresh, env=env))
        assert image in inspected[0]["RepoDigests"], "cached Postgres digest mismatch"
        run(["docker", "run", "--pull=never", "-d", "--name", name, "--network", "none", "--rm",
             "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=litellm",
             "-v", f"{fresh}:{fresh}", image], cwd=fresh, env=env)
        started = True
        for _ in range(60):
            process = subprocess.run(["docker", "exec", name, "cat", "/proc/1/comm"], env=env, capture_output=True, text=True)
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "litellm"], env=env, capture_output=True)
            if process.stdout.strip() == "postgres" and ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Test database did not become ready")
        sql = database_sql(fresh, source, coverage, routing, details)
        if native and not coverage:
            sql += '''\nCREATE TABLE public."LiteLLM_DailyUserSpend" (
                date text NOT NULL, api_requests bigint NOT NULL,
                successful_requests bigint NOT NULL, failed_requests bigint NOT NULL);\n'''
        admin = ["docker", "exec", "-i", name, "psql", "-U", "postgres", "-d", "litellm", "-v", "ON_ERROR_STOP=1"]
        run(admin, cwd=fresh, env=env, data=sql)
        network = run(["docker", "inspect", "--format", "{{.HostConfig.NetworkMode}}", name], cwd=fresh, env=env).strip()
        assert network == "none"
        if native:
            grants = published_grants(source, sql_blocks) if sql_blocks is not None else [
                {"id": "released-native-grants", "text": native_grants(source, daily=coverage)}]
            sql_evidence = []
            for block in grants:
                output = run(admin, cwd=fresh, env=env, data=block["text"])
                sql_evidence.append({"block": block["id"], "exit": 0, "pass": True,
                    "command_sha256": hashlib.sha256(block["text"].encode()).hexdigest(),
                    "stdout_sha256": hashlib.sha256(output.encode()).hexdigest()})
            reader = ["docker", "exec", name, "psql", "-U", "fleetdiff_reader", "-d", "litellm", "-At", "-v", "ON_ERROR_STOP=1", "-c"]
            identity = run(reader + [
                '''SELECT current_user, current_setting('default_transaction_read_only'),
                has_column_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'metadata', 'SELECT'),
                has_column_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'messages', 'SELECT'),
                has_table_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'INSERT'),
                has_table_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'SELECT');'''], cwd=fresh, env=env).strip()
            assert identity == "fleetdiff_reader|on|t|f|f|f", identity
            privileges = run(reader + ['''SELECT a.attname,
                has_column_privilege(current_user, a.attrelid, a.attnum, 'SELECT')
                FROM pg_attribute a WHERE a.attrelid = 'public."LiteLLM_SpendLogs"'::regclass
                AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attname;'''], cwd=fresh, env=env).strip()
            allowed = set("request_id call_type api_key user team_id organization_id end_user model model_id model_group custom_llm_provider prompt_tokens completion_tokens total_tokens spend status session_id agent_id startTime endTime metadata".split())
            columns = dict(line.split("|") for line in privileges.splitlines())
            assert {k for k, v in columns.items() if v == "t"} == allowed, columns
            assert {k for k, v in columns.items() if v == "f"} == {"messages", "response", "proxy_server_request"}, columns
            restrictions = run(reader + ['''SELECT current_database(), rolsuper, rolcreatedb,
                rolcreaterole, rolinherit, rolreplication, rolbypassrls,
                EXISTS(SELECT 1 FROM pg_auth_members WHERE member = r.oid),
                has_database_privilege(current_user, current_database(), 'CREATE'),
                has_schema_privilege(current_user, 'public', 'CREATE'),
                has_table_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'UPDATE'),
                has_table_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'DELETE'),
                has_table_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'TRUNCATE')
                FROM pg_roles r WHERE rolname = current_user;'''], cwd=fresh, env=env).strip()
            assert restrictions == "litellm|" + "|".join(["f"] * 12), restrictions
            daily_evidence = {}
            if coverage or sql_blocks is not None:
                daily_identity = run(reader + [
                    '''SELECT has_column_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'date', 'SELECT'),
                    has_column_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'api_requests', 'SELECT'),
                    has_column_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'successful_requests', 'SELECT'),
                    has_column_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'failed_requests', 'SELECT'),
                    has_table_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'SELECT'),
                    has_table_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'INSERT');'''], cwd=fresh, env=env).strip()
                assert daily_identity == "t|t|t|t|f|f", daily_identity
                daily_evidence = {"daily_readonly_identity": daily_identity}
                if coverage:
                    daily_evidence["daily_fixture_sha256"] = hashlib.sha256((fresh / "daily.csv").read_bytes()).hexdigest()
            with postgres_transport(name, env) as (port, transport):
                url = f"postgresql://fleetdiff_reader@127.0.0.1:{port}/litellm?sslmode=disable"
                (fresh / ".config").mkdir(mode=0o700, exist_ok=True)
                credential = fresh / ".config/litellm-db-url"
                with open(credential, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
                    handle.write(url + "\n")
                assert credential.stat().st_uid == os.geteuid() and credential.stat().st_mode & 0o777 == 0o600
                try:
                    yield dict(env, DATABASE_URL_FILE=str(credential), FLEETDIFF_LITELLM_DATABASE_URL=url)
                finally:
                    credential.unlink()
            assert transport["connections"] > 0 and transport["client_bytes"] > 0 and transport["server_bytes"] > 0
            assert not transport["errors"], transport
            (fresh / "database-evidence.json").write_text(json.dumps({"postgres": image, "network": network,
                "database": "litellm", "sql_blocks": sql_evidence,
                "column_select_privileges": columns, "role_restrictions": restrictions,
                "credential_relative_path": ".config/litellm-db-url", "credential_mode": "0600",
                "readonly_identity": identity, "transport": transport, **daily_evidence,
                "fixture_sha256": hashlib.sha256((fresh / "spend.csv").read_bytes()).hexdigest()}, indent=2) + "\n")
            return
        service = fresh / "pg_service.conf"
        service.write_text("[litellm_readonly]\nhost=/var/run/postgresql\nuser=fixture_reader\ndbname=litellm\n")
        wrappers = fresh / "test-tools"
        wrappers.mkdir()
        wrapper = wrappers / "psql"
        wrapper.write_text("#!/bin/sh\nexec docker exec --user " + str(os.getuid()) + ":" + str(os.getgid()) +
            " -e PGSERVICEFILE=" + shlex.quote(str(service)) + " -w " + shlex.quote(str(fresh)) + " " +
            shlex.quote(name) + ' psql "$@"\n')
        wrapper.chmod(0o700)
        if coverage:
            # Run the real helper inside Docker so both inherited descriptors stay intact.
            shell = wrappers / "sh"
            shell.write_text("#!/bin/sh\ncase ${1-} in\n./coverage-helper/export-coverage.sh)\nexec docker exec --user " +
                str(os.getuid()) + ":" + str(os.getgid()) + " -e PGSERVICEFILE=" + shlex.quote(str(service)) +
                " -w " + shlex.quote(str(fresh)) + " " + shlex.quote(name) + ' sh "$@";;\n' +
                '*) exec /bin/sh "$@";;\nesac\n')
            shell.chmod(0o700)
            identity = run(["docker", "exec", name, "psql", "-U", "fixture_reader", "-d", "litellm", "-At", "-c",
                '''SELECT current_user, current_setting('default_transaction_read_only'),
                has_table_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'SELECT'),
                has_table_privilege(current_user, 'public."LiteLLM_SpendLogs"', 'INSERT'),
                has_table_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'SELECT'),
                has_table_privilege(current_user, 'public."LiteLLM_DailyUserSpend"', 'INSERT');'''], cwd=fresh, env=env).strip()
            assert identity == "fixture_reader|on|t|f|t|f", identity
            network = run(["docker", "inspect", "--format", "{{.HostConfig.NetworkMode}}", name], cwd=fresh, env=env).strip()
            assert network == "none"
            (fresh / "database-evidence.json").write_text(json.dumps({"postgres": image, "network": network,
                "readonly_identity": identity, "start_utc": EXPORT_START, "end_exclusive": EXPORT_END,
                "fixture_sha256": {name: hashlib.sha256((fresh / name).read_bytes()).hexdigest()
                                   for name in ("spend.csv", "daily.csv")}}, indent=2) + "\n")
        # Only manual export commands use bounds in BEFORE/AFTER. Keep the
        # caller's comparison dates intact for the next investigate block.
        db_env = dict(env, PATH=str(wrappers) + os.pathsep + env["PATH"],
                      BEFORE=env.get("EXPORT_BEFORE", EXPORT_START), AFTER=env.get("EXPORT_AFTER", EXPORT_END))
        if routing and "EXPORT_BEFORE" not in env:
            db_env.update(BEFORE="2026-10-01T00:00:00Z", AFTER="2026-10-03T00:00:00Z")
        yield db_env
    finally:
        if started:
            cleanup = subprocess.run(["docker", "rm", "-f", name], env=env, capture_output=True)
            if cleanup.returncode:
                print(f"Cleanup needed: docker rm -f {name}")


def check(output, page=None):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    manifest = {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
                "fixture_source": FIXTURE_COMMIT,
                "method": "Exact published commands; fresh HOME/directories/caches; anonymous fixed-commit source archive; real released installer, CLI and library. Synthetic data is seeded into real read-only Postgres using cached digest-pinned network-none Docker. Native commands use the unchanged installed host binary through a loopback byte transport, not a database mock. The paired psql helper executes unmodified inside the container to retain its inherited descriptors.",
                "dependencies": [], "config_records": [], "results": records}
    with tempfile.TemporaryDirectory(prefix="site-own-source-") as directory:
        fixture_root = Path(directory)
        source, provenance = fixture_source(fixture_root)
        (output / "fixture-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        manifest["fixture_archive"] = {key: value for key, value in provenance.items() if key != "files"}
        manifest["fixture_archive"]["file_count"] = len(provenance["files"])
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for slug in PAGES:
            if page and slug != page:
                continue
            blocks = page_blocks(slug)
            assert blocks.own, slug
            with tempfile.TemporaryDirectory(prefix="site-own-" + slug + "-") as directory:
                fresh = Path(directory).resolve()
                env = environment(fresh)
                prepare(fresh, source, env, slug)
                expected_configs = {"cardinality": ["cardinality"], "traces-usage": ["traces-usage"],
                                    "what-if": ["what-if-workload-map"]}.get(slug, [])
                assert [b["id"] for b in blocks.configs] == expected_configs, slug
                if slug in {"cardinality", "traces-usage"}:
                    from config_checks import validate
                    manifest["config_records"].append(validate(blocks.configs[0], fresh, env, output / "configs"))
                    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                if slug == "security":
                    dependency = next(b for b in page_blocks("litellm-spend").own if b["id"] == "litellm-install")
                    result = subprocess.run(["bash", "-e", "-c", dependency["text"]], cwd=fresh,
                        env=env, text=True, capture_output=True, timeout=1800)
                    (output / "security-install.stdout.txt").write_text(result.stdout)
                    (output / "security-install.stderr.txt").write_text(result.stderr)
                    assert result.returncode == dependency["exit"], result.stderr
                    for excerpt in EXPECTED[dependency["id"]]:
                        assert excerpt in result.stdout
                    manifest["dependencies"].append({"page": slug, "source_page": "litellm-spend",
                        "block": dependency["id"], "exit": result.returncode, "pass": True,
                        "command_sha256": hashlib.sha256(dependency["text"].encode()).hexdigest(),
                        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                        "installed_version": installed_version(fresh, env)})
                database_day = None
                variants = None
                file_reports = {}
                if slug in {"litellm-spend", "routing", "row-coverage", "security",
                            "session-budget", "cache-check", "what-if"}:
                    database_day, variants = database_fixture_variants(fresh, env, slug, datetime.now(timezone.utc))
                for block in blocks.own:
                    begin = time.monotonic()
                    if variants is not None:
                        fixture_mode = "native" if block["id"] in NATIVE_BLOCKS else "file"
                        files, env = variants[fixture_mode]
                        for name, data in files.items():
                            (fresh / name).write_bytes(data)
                    if block["id"] == "anomalies":
                        refresh_history(fresh / "summary-history", time.time())
                    def execute(selected_env):
                        return subprocess.run(["bash", "-e", "-c", block["text"]], cwd=fresh,
                            env=selected_env, text=True, capture_output=True, timeout=1800)
                    if block["id"] in NATIVE_BLOCKS:
                        assert datetime.now(timezone.utc).date() == database_day.date(), "UTC day changed; rerun with fresh fixtures"
                        with database(fresh, source, env, coverage=slug == "row-coverage", routing=slug == "routing",
                                      native=True, sql_blocks=page_native_grants(slug),
                                      details=slug in {"session-budget", "cache-check", "what-if"}) as db_env:
                            if block["id"] == "litellm-native-env":
                                # Compare both published credential paths against this same fixture,
                                # including when checking security independently of the spend page.
                                file_block = next(b for b in page_blocks("litellm-spend").own if b["id"] == "litellm-native")
                                file_env = dict(db_env)
                                file_env.pop("FLEETDIFF_LITELLM_DATABASE_URL")
                                before_files = set(fresh.iterdir())
                                file_result = subprocess.run(["bash", "-e", "-c", file_block["text"]], cwd=fresh,
                                    env=file_env, text=True, capture_output=True, timeout=1800)
                                assert file_result.returncode == file_block["exit"], file_result.stderr
                                assert set(fresh.iterdir()) == before_files, "native temporary export was not cleaned up"
                                for excerpt in EXPECTED[file_block["id"]]:
                                    assert excerpt in file_result.stdout
                                db_env.pop("DATABASE_URL_FILE")
                            else:
                                db_env.pop("FLEETDIFF_LITELLM_DATABASE_URL")
                            before_files = set(fresh.iterdir())
                            result = execute(db_env)
                            assert set(fresh.iterdir()) == before_files, "native temporary export was not cleaned up"
                            if block["id"] == "litellm-native-env":
                                assert result.stdout == file_result.stdout, "credential sources changed the report"
                                assert result.stderr == file_result.stderr
                        shutil.copyfile(fresh / "database-evidence.json", output / (block["id"] + "-database.json"))
                    elif block["id"] in {"spend-export", "row-coverage-export", "routing-export"}:
                        coverage = block["id"] == "row-coverage-export"
                        routing = block["id"] == "routing-export"
                        with database(fresh, source, env, coverage=coverage, routing=routing) as db_env:
                            try:
                                result = execute(db_env)
                            finally:
                                export_dir = "litellm-coverage-export" if coverage else "litellm-export"
                                if routing:
                                    export_dir = "routing-export"
                                for diagnostics in fresh.glob(export_dir + "/private-psql.*"):
                                    shutil.copyfile(diagnostics, output / (block["id"] + "-" + diagnostics.name))
                                if coverage and (fresh / "database-evidence.json").exists():
                                    shutil.copyfile(fresh / "database-evidence.json", output / "row-coverage-database.json")
                    else:
                        result = execute(env)
                    (output / (block["id"] + ".stdout.txt")).write_text(result.stdout)
                    (output / (block["id"] + ".stderr.txt")).write_text(result.stderr)
                    record = {"page": slug, "block": block["id"], "pass": False,
                        "exit": result.returncode, "seconds": round(time.monotonic() - begin, 2),
                        "command_sha256": hashlib.sha256(block["text"].encode()).hexdigest(),
                        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest()}
                    if block["id"] in NATIVE_BLOCKS:
                        record["database"] = json.loads((fresh / "database-evidence.json").read_text())
                        record["fixture_utc_midnight"] = database_day.isoformat()
                        if slug == "what-if":
                            record["synthetic_recorded_spend_per_row_usd"] = "1"
                        if block["id"] == "litellm-native-env":
                            record["file_source_comparison"] = {"pass": True,
                                "command_sha256": hashlib.sha256(file_block["text"].encode()).hexdigest(),
                                "stdout_sha256": hashlib.sha256(file_result.stdout.encode()).hexdigest()}
                    records.append(record)
                    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                    assert result.returncode == block["exit"], (slug, block["id"], result.returncode, result.stderr)
                    for excerpt in EXPECTED[block["id"]]:
                        assert excerpt in result.stdout, (block["id"], excerpt, result.stdout)
                    if "sh install-fleetdiff.sh v0.12.1" in block["text"]:
                        record["installed_version"] = installed_version(fresh, env)
                    if block["id"] == "home-go":
                        assert "github.com/llm-measurement/llm-sketchkit v0.4.0" in (fresh / "measurement-go/go.mod").read_text()
                    if block["id"] == "spend-export":
                        exported = fresh / "litellm-export/spend.csv"
                        with exported.open() as handle:
                            rows = list(csv.DictReader(handle))
                        assert len(rows) == 160 and "messages" not in rows[0] and "response" not in rows[0]
                        assert "cache_read_input_tokens" in rows[0] and rows[0]["cache_read_input_tokens"] == ""
                        assert (fresh / "export.sql").read_bytes() == (source / "examples/litellm-spend/export.sql").read_bytes()
                    if block["id"] == "litellm-export-file":
                        record["input_sha256"] = hashlib.sha256((fresh / "litellm-export/spend.csv").read_bytes()).hexdigest()
                    file_inputs = {
                        "routing-audit": ("spend.csv",),
                        "routing-export-file": ("routing-export/spend.csv",),
                        "row-coverage": ("spend.csv", "daily.csv"),
                        "row-coverage-export-files": ("litellm-coverage-export/spend.csv", "litellm-coverage-export/daily.csv"),
                    }
                    if block["id"] in file_inputs:
                        record["input_sha256"] = {name: hashlib.sha256((fresh / name).read_bytes()).hexdigest()
                                                  for name in file_inputs[block["id"]]}
                        file_reports[block["id"]] = result.stdout
                        counterpart = {"routing-export-file": "routing-audit",
                                       "row-coverage-export-files": "row-coverage"}.get(block["id"])
                        if counterpart:
                            assert result.stdout == file_reports[counterpart], "actual SQL export changed the report"
                            record["standin_report_comparison"] = {"block": counterpart, "pass": True,
                                "stdout_sha256": hashlib.sha256(file_reports[counterpart].encode()).hexdigest()}
                    if block["id"] == "row-coverage-export":
                        for name in ("export-coverage.sh", "export.sql", "daily-projection.sql"):
                            assert (fresh / "coverage-helper" / name).read_bytes() == (source / "examples/litellm-spend" / name).read_bytes()
                        with (fresh / "litellm-coverage-export/spend.csv").open() as handle:
                            exported = list(csv.DictReader(handle))
                        with (fresh / "spend.csv").open() as handle:
                            expected = list(csv.DictReader(handle))
                        assert comparable_rows(exported) == comparable_rows(expected)
                        with (fresh / "litellm-coverage-export/daily.csv").open() as handle:
                            daily = list(csv.DictReader(handle))
                        with (fresh / "daily.csv").open() as handle:
                            expected_daily = list(csv.DictReader(handle))
                        assert sorted(daily, key=lambda row: row["date"]) == sorted(expected_daily, key=lambda row: row["date"])
                        assert sum(row["startTime"].startswith("2026-10-07") for row in exported) == 8
                        assert sum(row["startTime"].startswith("2026-10-08") for row in exported) == 1
                        assert next(row for row in daily if row["date"] == "2026-10-07")["api_requests"] == "9"
                        record["paired_export"] = {"start_utc": EXPORT_START, "end_exclusive": EXPORT_END,
                            "fixture_oct07_spend_rows": 8, "fixture_oct07_daily_requests": 9,
                            "fixture_oct08_spend_rows": 1, "readonly": True, "network": "none"}
                    if block["id"] in {"what-if-reprice", "what-if-native"}:
                        assert result.stdout == (source / "examples/what-if/expected.text").read_text()
                    if block["id"] == "what-if-workload-map":
                        mapped = json.loads(result.stdout)
                        assert mapped["covered_source_cost_usd"] == "0.154400000"
                        assert mapped["covered_level1_cost_usd"] == "0.148703445"
                        assert mapped["covered_observations"] == 3 and mapped["excluded_observations"] == {"missing_split": 1}
                        assert mapped["unmapped_moved_observations"] == 0
                        assert len(mapped["level2"]) == 1 and mapped["level2"][0]["workload"] == "mapped"
                        raw = blocks.configs[0]["text"].encode()
                        assert (fresh / "workload-map.json").read_bytes() == raw
                        manifest["config_records"].append({
                            "page": slug, "block": "what-if-workload-map", "kind": "fleetdiff-workload-map",
                            "pass": True, "exit": result.returncode, "config_sha256": hashlib.sha256(raw).hexdigest(),
                            "execution_block": block["id"], "command_sha256": record["command_sha256"],
                            "stdout_sha256": record["stdout_sha256"], "input_relative_path": "workload-map.json",
                            "fixture_sha256": hashlib.sha256((fresh / "spend.csv").read_bytes()).hexdigest(),
                            "validation": "exact published JSON consumed by the released CLI; only synthetic CSV identities adapted",
                        })
                    if block["id"] == "routing-export":
                        assert (fresh / "export.sql").read_bytes() == (source / "examples/litellm-spend/export.sql").read_bytes()
                        with (fresh / "routing-export/spend.csv").open() as handle:
                            exported = list(csv.DictReader(handle))
                        with (fresh / "spend.csv").open() as handle:
                            expected = list(csv.DictReader(handle))
                        assert len(exported) == 8
                        assert comparable_rows(exported) == comparable_rows(expected)
                        assert all(not {"messages", "response", "metadata"} & row.keys() for row in exported)
                    if block["id"] == "routing-agents":
                        audit = json.loads(result.stdout)["routing_audit"]
                        assert audit["group_by"] == "route-agent"
                        assert audit["provider_snapshot_confirmed"] is False
                        assert not audit.get("configuration_labels_included", False)
                        for side in ("before", "after"):
                            assert audit["model_rows"][side]["requests"] == 3
                            assert audit["model_rows"][side]["recorded_tokens"] == 360
                            assert audit["classifier_overhead"][side]["recorded_spend_usd"] == "0.00005"
                            responses = next(c for c in audit["coverage"]["by_call_type"] if c["call_type"] == "aresponses")
                            assert responses[side]["agent"]["known_rows"] == 0
                            assert responses[side]["agent"]["missing_rows"] == 1
                        assert len(audit["cohorts"]) == 2
                    assert all(raw not in result.stdout for raw in ("private-ana", "private-ben", "private-cy"))
                    if slug in {"session-budget", "what-if", "routing", "cache-check"}:
                        assert "SENTINEL_" not in result.stdout + result.stderr
                    if slug == "what-if":
                        assert all(value not in result.stdout + result.stderr for value in
                                   ("your-coding-key-id", "your-extraction-team-id"))
                    record["pass"] = True
                    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                    print(f"PASS own data: {slug}/{block['id']}; exit {result.returncode}", flush=True)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
