# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Validate exact guide fragments with cached released collectors, not a YAML stub."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import uuid

CONFIG_IMAGES = {
    "cardinality": "ghcr.io/llm-measurement/otelcol-genai-sketches@sha256:b17b3489b65c27a622402982e8e61ee44c7ada247ff3168efacc63a3867c7818",
    "traces-usage": "otel/opentelemetry-collector-contrib@sha256:fd328de2552466ad78385e1b1289c3f2402b1c45f265b252aab1955b42845ac1",
}
RECEIVER = """receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 127.0.0.1:4317
"""
CARDINALITY_TAIL = """
exporters:
  prometheus:
    endpoint: 127.0.0.1:8889
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [genaisketch]
    metrics:
      receivers: [genaisketch]
      exporters: [prometheus]
"""
TRACE_TAIL = """
  debug/existing:
    verbosity: basic
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug/existing, file/inspect]
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compose(block):
    name, snippet = block["id"], block["text"]
    assert name in CONFIG_IMAGES and snippet
    assert snippet.startswith("connectors:\n" if name == "cardinality" else "exporters:\n")
    # The fragment is a contiguous, byte-exact section, not parsed/re-serialized.
    tail = CARDINALITY_TAIL if name == "cardinality" else TRACE_TAIL
    return (RECEIVER + snippet + tail).encode()


def platform_image(name, architecture):
    image = CONFIG_IMAGES[name]
    if name != "cardinality":
        return image
    raw = Path(__file__).with_name("collector-v061-index.json").read_bytes().removesuffix(b"\n")
    assert digest(raw) == image.split("@sha256:", 1)[1], "release index bytes changed"
    index = json.loads(raw)
    entries = [item for item in index["manifests"]
               if item["platform"] == {"os": "linux", "architecture": architecture}]
    assert len(entries) == 1, "unsupported collector architecture"
    return image.split("@", 1)[0] + "@" + entries[0]["digest"]


def validate(block, fresh, env, output):
    name, image = block["id"], CONFIG_IMAGES[block["id"]]
    env = dict(env)
    if "DOCKER_HOST" not in env:
        env["DOCKER_HOST"] = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            check=True, capture_output=True, text=True).stdout.strip()
    inspected = subprocess.run(["docker", "image", "inspect", image], env=env,
                               capture_output=True, text=True)
    runtime_image = image
    if inspected.returncode:
        # Release checks cached platform children. Accept only the child bound
        # by the exact published index; never discover or pull a replacement.
        architecture = {"aarch64": "arm64", "arm64": "arm64",
                        "x86_64": "amd64", "AMD64": "amd64"}[platform.machine()]
        runtime_image = platform_image(name, architecture)
        inspected = subprocess.run(["docker", "image", "inspect", runtime_image], env=env,
                                   check=True, capture_output=True, text=True)
    image_info = json.loads(inspected.stdout)[0]
    assert runtime_image in image_info["RepoDigests"], "cached collector digest mismatch"
    output.mkdir(parents=True, exist_ok=True)
    complete = compose(block)
    (output / (name + ".composed.yaml")).write_bytes(complete)
    (fresh / "capture").mkdir(mode=0o700, exist_ok=True)
    name_prefix = "site-config-" + uuid.uuid4().hex[:12]
    results = []
    for negative in (False, True):
        current = complete
        if negative:
            old, new = ((b"weight: tokens", b"weight: unsupported_site_test_weight") if name == "cardinality"
                        else (b"format: json", b"unsupported_site_test_setting: true"))
            assert complete.count(old) == 1
            current = complete.replace(old, new, 1)
        suffix = "negative" if negative else "published"
        # Separate immutable files avoid host/VM bind-mount cache reuse.
        config = fresh / (name + "." + suffix + ".yaml")
        config.write_bytes(current)
        (output / (name + "." + suffix + ".yaml")).write_bytes(current)
        container = name_prefix + "-" + suffix
        command = ["docker", "run", "--pull=never", "--name", container, "--network", "none", "--rm",
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--user", str(os.getuid()) + ":" + str(os.getgid()),
            "--mount", f"type=bind,src={config},dst=/fixture/config.yaml,readonly",
            "--mount", f"type=bind,src={fresh / 'capture'},dst=/private-capture",
            "-e", "GENAI_SKETCH_SECRET=site-synthetic-only-not-a-production-secret",
            runtime_image, "validate", "--config=file:/fixture/config.yaml"]
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", container], env=env, capture_output=True, timeout=30)
            raise
        (output / f"{name}.{suffix}.stdout.txt").write_text(result.stdout)
        (output / f"{name}.{suffix}.stderr.txt").write_text(result.stderr)
        remaining = subprocess.run(["docker", "ps", "-a", "--filter", "name=^/" + container + "$",
            "--format", "{{.Names}}"], env=env, capture_output=True, text=True, check=True, timeout=30)
        assert not remaining.stdout.strip(), "validation container was not removed"
        if negative:
            diagnostic = ("topk_keys weight must be tokens or requests" if name == "cardinality"
                          else "unsupported_site_test_setting")
            assert result.returncode != 0 and diagnostic in result.stdout + result.stderr, result.stderr
        else:
            assert result.returncode == 0, result.stderr
        results.append({"case": suffix, "exit": result.returncode, "pass": True,
            "configuration_sha256": digest(current), "stdout_sha256": digest(result.stdout.encode()),
            "stderr_sha256": digest(result.stderr.encode())})
    return {"page": name, "block": name, "kind": "collector-validate", "pass": True, "config_sha256": digest(block["text"].encode()),
        "composed_sha256": digest(complete), "image": image, "runtime_image": runtime_image,
        "image_id": image_info["Id"], "containers_removed": True,
        "image_architecture": image_info["Architecture"], "network": "none", "pull": "never",
        "validation": "released collector validate command; no receiver traffic or capture performed",
        "runtime_args": ["validate", "--config=file:/fixture/config.yaml"], "results": results}


def main():
    from own_data import environment, page_blocks
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page", choices=list(CONFIG_IMAGES))
    args = parser.parse_args()
    records = []
    for slug in CONFIG_IMAGES:
        if args.page and args.page != slug:
            continue
        blocks = page_blocks(slug).configs
        assert len(blocks) == 1 and blocks[0]["id"] == slug
        with tempfile.TemporaryDirectory(prefix="site-config-") as directory:
            fresh = Path(directory).resolve()
            records.append(validate(blocks[0], fresh, environment(fresh), args.output))
    (args.output / "manifest.json").write_text(json.dumps({"config_records": records}, indent=2) + "\n")
    print("PASS: exact published YAML fragments accepted; both negative controls rejected")


if __name__ == "__main__":
    main()
