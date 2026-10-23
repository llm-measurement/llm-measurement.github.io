# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Pinned release-cache preparation and fail-closed curl transport for routine checks."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
SPEC = HERE / "release_cache_manifest.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def spec():
    return json.loads(SPEC.read_text())


def checked_file(root, item):
    relative = Path(item["file"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid cache member")
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("missing regular pinned cache member: " + str(relative))
    data = path.read_bytes()
    if digest(data) != item["sha256"]:
        raise ValueError("cache digest mismatch: " + str(relative))
    return data


def cache_root():
    value = os.environ.get("SITE_RELEASE_CACHE")
    if not value:
        raise ValueError("SITE_RELEASE_CACHE is required; no public download fallback")
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("release cache is not a directory")
    manifest = json.loads((root / "cache-identity.json").read_text())
    if manifest["spec_sha256"] != digest(SPEC.read_bytes()):
        raise ValueError("cache was prepared for a different pinned specification")
    definition = spec()
    for key, expected in (("version", definition["version"]), ("source_commit", definition["commit"]),
                          ("source_tree", definition["tree"]), ("artifact", definition["artifact"])):
        if manifest.get(key) != expected:
            raise ValueError("wrong pinned cache identity: " + key)
    expected_subjects = sorted(name for name in definition["assets"] if name != "provenance.jsonl")
    if sorted(manifest.get("attested_subjects_verified", [])) != expected_subjects:
        raise ValueError("cache preparation did not verify every original signed subject")
    return root


def read_url(url, root=None):
    definition = spec()
    if url not in definition["urls"]:
        raise ValueError("URL is not in the pinned routine-check cache: " + url)
    return checked_file(root if root is not None else cache_root(), definition["urls"][url])


def source_archive(source, prefix):
    definition = spec()
    raw = subprocess.check_output(["git", "-C", str(source), "archive", "--format=tar",
                                   "--prefix=" + prefix + "/", definition["commit"]])
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as stream:
        stream.write(raw)
    return buffer.getvalue()


def check_artifact(metadata):
    expected = spec()["artifact"]
    if metadata.get("expired"):
        raise ValueError("original release workflow artifact expired; no release-download fallback")
    for key in ("id", "name", "digest"):
        if metadata.get(key) != expected[key]:
            raise ValueError("wrong original workflow artifact " + key)
    run = metadata.get("workflow_run", {})
    if run.get("id") != expected["run_id"] or run.get("head_sha") != spec()["commit"]:
        raise ValueError("artifact is not from the pinned release source/run")


def prepare(assets, source, destination):
    definition = spec()
    for suffix, expected in (("", definition["commit"]), ("^{tree}", definition["tree"])):
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD" + suffix], text=True).strip()
        if actual != expected:
            raise ValueError("source checkout does not match the original release")
    destination.mkdir(mode=0o700)
    for name, checksum in definition["assets"].items():
        data = checked_file(assets, {"file": name, "sha256": checksum})
        (destination / name).write_bytes(data)
    for item in definition["source_files"].values():
        data = subprocess.check_output(["git", "-C", str(source), "show",
                                        definition["commit"] + ":" + item["source"]])
        if digest(data) != item["sha256"]:
            raise ValueError("pinned source helper mismatch")
        target = destination / item["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for prefix, item in definition["source_archives"].items():
        data = source_archive(source, prefix)
        if digest(data) != item["sha256"]:
            raise ValueError("pinned source archive reconstruction mismatch")
        (destination / item["file"]).write_bytes(data)
    for item in definition["urls"].values():
        checked_file(destination, item)
    verified = verify_subjects(destination)
    identity = {"mode": "verified-cache, not fresh anonymous downloads",
                "version": definition["version"], "source_commit": definition["commit"],
                "source_tree": definition["tree"], "artifact": definition["artifact"],
                "spec_sha256": digest(SPEC.read_bytes()),
                "attested_subjects_verified": verified,
                "source_archives": "deterministic git archive of the pinned commit; not original codeload bytes",
                "provenance": "original published bundle; consumers still run real gh verification"}
    (destination / "cache-identity.json").write_text(json.dumps(identity, indent=2) + "\n")


def verify_subjects(root):
    definition = spec()
    verified = []
    for name in definition["assets"]:
        if name == "provenance.jsonl":
            continue
        subprocess.run(["gh", "attestation", "verify", str(root / name),
                        "--bundle", str(root / "provenance.jsonl"),
                        "--repo", "llm-measurement/fleetdiff",
                        "--signer-workflow", "llm-measurement/fleetdiff/.github/workflows/release.yml",
                        "--source-ref", definition["tag_ref"], "--source-digest", definition["commit"],
                        "--deny-self-hosted-runners"], check=True, capture_output=True, text=True)
        verified.append(name)
    return verified


def member_hashes(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("cache contains a link or special member")
        if path.is_file() and path.relative_to(root).as_posix() != "cache-members.json":
            files[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return files


def verify_cache(root, manifest_sha256):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("cache root must be a regular directory")
    inventory = checked_file(root, {"file": "cache-members.json", "sha256": manifest_sha256})
    definition = spec()
    members = json.loads(inventory)
    expected = set(definition["assets"]) | {"cache-identity.json", "seed-origin.json", "deliberate-downloads.jsonl"}
    expected.update(item["file"] for item in definition["source_files"].values())
    expected.update(item["file"] for item in definition["source_archives"].values())
    if set(members) != expected or member_hashes(root) != members:
        raise ValueError("cache member inventory differs from the pinned manifest")
    for name, checksum in definition["assets"].items():
        checked_file(root, {"file": name, "sha256": checksum})
    for item in definition["urls"].values():
        checked_file(root, item)
    identity = json.loads((root / "cache-identity.json").read_text())
    if identity.get("spec_sha256") != digest(SPEC.read_bytes()):
        raise ValueError("cache specification differs from the protected source")
    for key, value in (("version", definition["version"]), ("source_commit", definition["commit"]),
                       ("source_tree", definition["tree"]), ("artifact", definition["artifact"])):
        if identity.get(key) != value:
            raise ValueError("cache identity differs from the pinned release")
    verified = verify_subjects(root)
    if sorted(identity.get("attested_subjects_verified", [])) != sorted(verified):
        raise ValueError("cache identity has an incomplete subject inventory")
    return verified


def environment(fresh, env):
    root = cache_root()
    shim = fresh / "cache-transport"
    shim.mkdir(mode=0o700, exist_ok=True)
    launcher = "#!" + sys.executable + "\nimport runpy, sys\nsys.argv.insert(1, '--curl')\nrunpy.run_path(" + repr(str(Path(__file__).resolve())) + ", run_name='__main__')\n"
    (shim / "curl").write_text(launcher)
    (shim / "curl").chmod(0o700)
    return dict(env, PATH=str(shim) + os.pathsep + env["PATH"], SITE_RELEASE_CACHE=str(root))


def curl_arguments(arguments):
    urls, output, remote_name = [], None, False
    args = iter(arguments)
    for arg in args:
        if arg in ("--output", "-o"):
            output = next(args)
        elif arg in ("--proto", "--proto-redir"):
            if next(args) != "=https":
                raise ValueError("only the published HTTPS protocol constraint is supported")
        elif arg == "--url":
            urls.append(next(args))
        elif arg in ("--fail", "--silent", "--show-error", "--location", "--tlsv1.2", "--disable"):
            pass
        elif arg == "--remote-name":
            remote_name = True
        elif arg.startswith("-") and not arg.startswith("--"):
            flags = arg[1:]
            while flags:
                flag, flags = flags[0], flags[1:]
                if flag == "o":
                    output = flags or next(args)
                    flags = ""
                elif flag == "O":
                    remote_name = True
                elif flag not in "fsSLq":
                    raise ValueError("unsupported curl option")
        elif arg.startswith("-"):
            raise ValueError("unsupported curl option")
        else:
            urls.append(arg)
    if len(urls) != 1:
        raise ValueError("cache transport requires exactly one expected URL")
    if remote_name:
        if output is not None:
            raise ValueError("conflicting output options")
        output = urlsplit(urls[0]).path.rsplit("/", 1)[-1]
    return urls[0], output


def curl(arguments):
    url, output = curl_arguments(arguments)
    data = read_url(url)
    if output is None or output == "-":
        sys.stdout.buffer.write(data)
    else:
        path = Path(output)
        if path.is_symlink():
            raise ValueError("refusing linked curl output")
        with path.open("wb") as stream:
            stream.write(data)


def main():
    if sys.argv[1:2] == ["--curl"]:
        curl(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.verify:
        if not args.manifest_sha256:
            parser.error("restored cache verification requires the exact manifest SHA256")
        verified = verify_cache(args.verify, args.manifest_sha256)
        print("Verified restored cache bytes and " + str(len(verified)) + " original signed subjects")
    elif args.metadata:
        check_artifact(json.loads(args.metadata.read_text()))
    else:
        if not all((args.assets, args.source, args.output)):
            parser.error("supply --metadata or --assets/--source/--output")
        prepare(args.assets, args.source, args.output)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, StopIteration, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print("Pinned release cache failed: " + str(error), file=sys.stderr)
        sys.exit(22)
