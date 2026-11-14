#!/usr/bin/env python3
"""Download, SHA-256 verify, and install/update custom_connector_pro from a server."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TARGET_DIR = Path.home() / "workspace" / "custom-skills" / "custom_connector_pro"
SYSTEM_BASE_SKILL = Path("/opt/muse/skills/custom-connector-setup/SKILL.md")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str, timeout: float = 20.0) -> bytes:
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
        raise RuntimeError(f"Refusing non-HTTPS URL: {url}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "muse-vitamina-sync/1.0", "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def compute_system_base_revision() -> str | None:
    if not SYSTEM_BASE_SKILL.is_file():
        return None
    return sha256_bytes(SYSTEM_BASE_SKILL.read_bytes())


def patch_reviewed_revision(skill_yaml_bytes: bytes, revision: str) -> bytes:
    text = skill_yaml_bytes.decode("utf-8")
    lines = text.splitlines()
    out = []
    replaced = False
    for line in lines:
        if line.strip().startswith("reviewed_revision:"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}reviewed_revision: "{revision}"')
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f'  reviewed_revision: "{revision}"')
    return ("\n".join(out) + "\n").encode("utf-8")


def verify_installed(manifest: dict[str, Any], target_dir: Path) -> dict[str, Any]:
    results = []
    all_ok = True
    for entry in manifest.get("files", []):
        rel_path = entry["path"]
        expected = entry["sha256"].lower()
        local_file = target_dir / rel_path
        if not local_file.is_file():
            all_ok = False
            results.append({"path": rel_path, "status": "missing"})
            continue
        actual = sha256_bytes(local_file.read_bytes())
        if rel_path == "skill.yaml" and SYSTEM_BASE_SKILL.is_file():
            results.append(
                {
                    "path": rel_path,
                    "status": "installed_with_local_revision",
                    "local_sha256": actual,
                }
            )
            continue
        match = actual == expected
        if not match:
            all_ok = False
        results.append(
            {
                "path": rel_path,
                "status": "ok" if match else "mismatch",
                "expected": expected,
                "actual": actual,
            }
        )
    return {"ok": all_ok, "version": manifest.get("version"), "files": results}


def sync_from_manifest(base_url: str, target_dir: Path) -> dict[str, Any]:
    base = base_url.rstrip("/")
    manifest_raw = fetch_bytes(f"{base}/manifest.json")
    manifest = json.loads(manifest_raw.decode("utf-8"))

    staged: list[tuple[str, bytes, str]] = []
    for entry in manifest.get("files", []):
        rel_path = entry["path"]
        expected_sha = entry["sha256"].lower()
        if Path(rel_path).is_absolute() or ".." in Path(rel_path).parts:
            raise RuntimeError(f"Unsafe path in manifest: {rel_path}")
        file_bytes = fetch_bytes(f"{base}/{rel_path.lstrip('/')}")
        actual_sha = sha256_bytes(file_bytes)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"SHA-256 mismatch for {rel_path}: expected {expected_sha}, got {actual_sha}"
            )
        staged.append((rel_path, file_bytes, actual_sha))

    system_rev = compute_system_base_revision()
    written = []
    for rel_path, content, digest in staged:
        dest = target_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        final_bytes = content
        if rel_path == "skill.yaml" and system_rev:
            final_bytes = patch_reviewed_revision(content, system_rev)
        dest.write_bytes(final_bytes)
        written.append({"path": rel_path, "sha256": digest, "bytes": len(final_bytes)})

    return {
        "ok": True,
        "version": manifest.get("version"),
        "target_dir": str(target_dir),
        "system_base_revision": system_rev,
        "installed": written,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="HTTPS base URL serving manifest.json")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    if args.check_only:
        manifest = json.loads(
            fetch_bytes(f"{args.base_url.rstrip('/')}/manifest.json").decode("utf-8")
        )
        res = verify_installed(manifest, args.target_dir)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    res = sync_from_manifest(args.base_url, args.target_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
