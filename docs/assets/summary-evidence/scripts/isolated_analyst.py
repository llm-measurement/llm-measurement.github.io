# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Require raw-read/network denial, then run the summary-only analyst."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY = '(version 1)(allow default)(deny network*)(deny file-read* (subpath %s))'
PROBE = '''import json, socket
checks = {}
try:
    open("data/oracle.json", "rb")
except PermissionError:
    checks["raw_read_denied"] = True
try:
    socket.create_connection(("127.0.0.1", 9), timeout=1)
except PermissionError:
    checks["network_denied"] = True
assert checks == {"raw_read_denied": True, "network_denied": True}, checks
print(json.dumps(checks, sort_keys=True))
'''


def main():
    policy = POLICY % json.dumps(str(ROOT / "data"))
    prefix = ["sandbox-exec", "-p", policy, sys.executable]
    proof = subprocess.run(prefix + ["-c", PROBE], cwd=ROOT, check=True,
                           text=True, capture_output=True)
    (ROOT / "evidence/analyst-denial.log").write_text(proof.stdout)
    run = subprocess.run(prefix + ["scripts/analyst_run.py"], cwd=ROOT,
                         check=True, text=True, capture_output=True)
    (ROOT / "evidence/analyst-sandbox.log").write_text(run.stdout)
    print(proof.stdout + run.stdout, end="")


if __name__ == "__main__":
    main()
