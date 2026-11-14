#!/usr/bin/env python3
"""Verify that published skill manifests are complete and installable."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from build_all import ROOT, SKILLS_DIR, SKILL_SPECS, distributable_files

VALIDATOR = SKILLS_DIR / "skill_creator" / "scripts" / "quick_validate.py"
PENDING_REVISION = "PENDING_LOCAL_SHA256"
TEST_REVISION = "0" * 64


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage_runtime_revision(target_dir: Path, spec: dict[str, object]) -> None:
    """Model the installer patch that makes an amendment valid on a Muse VM."""
    if not spec.get("amends"):
        return
    yaml_path = target_dir / "skill.yaml"
    content = yaml_path.read_text(encoding="utf-8")
    if PENDING_REVISION not in content:
        raise ValueError("amendment source must contain PENDING_LOCAL_SHA256")
    yaml_path.write_text(content.replace(PENDING_REVISION, TEST_REVISION), encoding="utf-8")


def verify_skill(spec: dict[str, object]) -> list[str]:
    skill_dir = SKILLS_DIR / str(spec["dir"])
    manifest_path = skill_dir / "manifest.json"
    errors: list[str] = []

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{manifest_path}: cannot read manifest: {exc}"]

    entries = manifest.get("files")
    if not isinstance(entries, list):
        return [f"{manifest_path}: files must be a list"]

    expected_paths = set(distributable_files(skill_dir))
    actual_paths: set[str] = set()
    staged: list[tuple[str, bytes]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append(f"{manifest_path}: invalid file entry")
            continue
        rel_path = entry["path"]
        if rel_path in actual_paths:
            errors.append(f"{manifest_path}: duplicate entry: {rel_path}")
            continue
        actual_paths.add(rel_path)
        source_path = skill_dir / rel_path
        if not source_path.is_file():
            errors.append(f"{manifest_path}: missing source file: {rel_path}")
            continue
        content = source_path.read_bytes()
        if entry.get("sha256") != sha256_bytes(content):
            errors.append(f"{manifest_path}: SHA-256 mismatch: {rel_path}")
        if entry.get("bytes") != len(content):
            errors.append(f"{manifest_path}: byte count mismatch: {rel_path}")
        staged.append((rel_path, content))

    for rel_path in sorted(expected_paths - actual_paths):
        errors.append(f"{manifest_path}: untracked distributable file: {rel_path}")
    for rel_path in sorted(actual_paths - expected_paths):
        errors.append(f"{manifest_path}: unexpected file entry: {rel_path}")
    if errors:
        return errors

    with tempfile.TemporaryDirectory(prefix=".muse-manifest-", dir=ROOT) as temp_dir:
        target_dir = Path(temp_dir) / str(spec["name"])
        for rel_path, content in staged:
            destination = target_dir / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        try:
            stage_runtime_revision(target_dir, spec)
        except (OSError, ValueError) as exc:
            return [f"{manifest_path}: cannot stage amendment revision: {exc}"]
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(target_dir)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            output = result.stdout.strip() or result.stderr.strip()
            errors.append(f"{manifest_path}: clean install validation failed: {output}")

    return errors


def verify_catalog() -> list[str]:
    catalog_path = ROOT / "catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{catalog_path}: cannot read catalog: {exc}"]

    catalog_names = {
        entry.get("name") for entry in catalog.get("skills", []) if isinstance(entry, dict)
    }
    expected_names = {str(spec["name"]) for spec in SKILL_SPECS}
    if catalog_names != expected_names:
        return [f"{catalog_path}: skill names do not match configured skills"]
    return []


def main() -> int:
    errors = verify_catalog()
    for spec in SKILL_SPECS:
        errors.extend(verify_skill(spec))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Verified {len(SKILL_SPECS)} manifests and clean installations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
