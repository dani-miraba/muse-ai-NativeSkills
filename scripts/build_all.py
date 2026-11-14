#!/usr/bin/env python3
"""Regenerate manifest.json for every skill under skills/ and build root catalog.json."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

SKILL_SPECS: list[dict[str, Any]] = [
    {
        "dir": "skill_creator",
        "name": "skill_creator",
        "version": "1.0.0",
        "sync_script": "scripts/sync_skill_creator.py",
        "amends": None,
        "files": [
            "SKILL.md",
            "skill.yaml",
            "references/muse-constraints.md",
            "scripts/init_skill.py",
            "scripts/quick_validate.py",
            "scripts/sync_skill_creator.py",
        ],
    },
    {
        "dir": "spreadsheet_analyst",
        "name": "spreadsheet_analyst",
        "version": "1.0.0",
        "sync_script": "scripts/sync_skill.py",
        "amends": None,
        "files": [
            "SKILL.md",
            "skill.yaml",
            "scripts/tabular_cli.py",
            "scripts/sync_skill.py",
        ],
    },
    {
        "dir": "custom_connector_pro",
        "name": "custom_connector_pro",
        "version": "1.0.0",
        "sync_script": "scripts/sync_vitamina.py",
        "amends": "custom_connector_setup",
        "files": [
            "SKILL.md",
            "skill.yaml",
            "scripts/robust_rest.py",
            "scripts/robust_mcp.py",
            "scripts/sync_vitamina.py",
            "blueprints/README.md",
        ],
    },
]


def parse_skill_yaml(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        if raw_line.startswith(" "):
            continue
        key, val = line.split(":", 1)
        val = val.strip().strip('"').strip("'")
        if val:
            meta[key.strip()] = val
    return meta


def build_skill_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    skill_dir = SKILLS_DIR / spec["dir"]
    entries: list[dict[str, Any]] = []
    for rel in spec["files"]:
        file_path = skill_dir / rel
        if not file_path.is_file():
            raise FileNotFoundError(f"Missing tracked file: {file_path}")
        data = file_path.read_bytes()
        entries.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )

    manifest = {
        "name": spec["name"],
        "version": spec["version"],
        "target_skill_dir": f"~/workspace/custom-skills/{spec['name']}",
        "files": entries,
    }
    out_path = skill_dir / "manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    meta = parse_skill_yaml(skill_dir / "skill.yaml")
    return {
        "name": spec["name"],
        "title": meta.get("title", spec["name"]),
        "version": spec["version"],
        "path": f"skills/{spec['dir']}",
        "category": meta.get("category", ""),
        "description": meta.get("description", ""),
        "amends": spec["amends"],
        "sync_script": spec["sync_script"],
        "target_dir": f"~/workspace/custom-skills/{spec['name']}",
        "file_count": len(entries),
    }


def main() -> None:
    catalog_entries = [build_skill_manifest(spec) for spec in SKILL_SPECS]
    catalog = {
        "schema_version": 1,
        "skills": catalog_entries,
    }
    catalog_path = ROOT / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {len(catalog_entries)} skill manifests and {catalog_path}.")


if __name__ == "__main__":
    main()
