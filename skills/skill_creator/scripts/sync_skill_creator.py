#!/usr/bin/env python3
"""Download, SHA-256 verify, and install/update skill_creator from a server."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TARGET_DIR = Path.home() / "workspace" / "custom-skills" / "skill_creator"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str, timeout: float = 20.0) -> bytes:
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
        raise RuntimeError(f"Refusing non-HTTPS URL: {url}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "muse-skill-creator-sync/1.0", "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sync_from_manifest(base_url: str, target_dir: Path) -> dict[str, Any]:
    base = base_url.rstrip("/")
    manifest = json.loads(fetch_bytes(f"{base}/manifest.json").decode("utf-8"))

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

    written = []
    for rel_path, content, digest in staged:
        dest = target_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        written.append({"path": rel_path, "sha256": digest, "bytes": len(content)})

    return {
        "ok": True,
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "target_dir": str(target_dir),
        "installed": written,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR)
    args = parser.parse_args()
    res = sync_from_manifest(args.base_url, args.target_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
