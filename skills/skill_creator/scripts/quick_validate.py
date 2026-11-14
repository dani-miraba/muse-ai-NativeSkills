#!/usr/bin/env python3
"""Validate a Muse custom skill directory against Muse formatting and safety rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import py_compile
import re
import sys
from typing import Any

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse top-level and 1-level nested YAML keys without external dependencies."""
    try:
        import yaml

        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict):
            return loaded
    except ImportError:
        pass

    data: dict[str, Any] = {}
    current_parent: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, val = stripped.split(":", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if indent == 0:
            if val == "":
                data[key] = {}
                current_parent = key
            else:
                lower = val.lower()
                if lower == "true":
                    data[key] = True
                elif lower == "false":
                    data[key] = False
                else:
                    data[key] = val
                current_parent = None
        elif current_parent and isinstance(data.get(current_parent), dict):
            data[current_parent][key] = val
    return data


def _validate_metadata(yaml_path: Path, folder_name: str, errors: list[str]) -> None:
    meta = parse_simple_yaml(yaml_path.read_text(encoding="utf-8"))
    for req in ("name", "title", "description", "category", "include_in_prompt"):
        if req not in meta:
            errors.append(f"skill.yaml missing required field: {req}")

    name = str(meta.get("name", ""))
    if name and not NAME_RE.match(name):
        errors.append(f"skill.yaml name '{name}' must be snake_case")
    if name and name != folder_name:
        errors.append(
            f"skill.yaml name '{name}' must match folder name '{folder_name}'"
        )

    amends = meta.get("amends")
    if amends is not None:
        if not isinstance(amends, dict) or set(amends.keys()) != {
            "skill",
            "reviewed_revision",
        }:
            errors.append("amends block must contain exactly 'skill' and 'reviewed_revision'")


def _validate_markdown(
    md_path: Path, errors: list[str], warnings: list[str]
) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].strip() == "---":
        errors.append("SKILL.md must not contain YAML frontmatter")
    if not any(ln.startswith("# ") for ln in lines[:5]):
        errors.append("SKILL.md must start with a level-1 '# Title' heading")

    in_fence = False
    for idx, ln in enumerate(lines, start=1):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ";" in ln:
            errors.append(f"SKILL.md line {idx}: semicolon ';' is disallowed in prose")
        if "\u2014" in ln or "\u2013" in ln:
            errors.append(f"SKILL.md line {idx}: em/en dash is disallowed")
        if any(q in ln for q in ("\u201c", "\u201d", "\u2018", "\u2019")):
            errors.append(f"SKILL.md line {idx}: curly quotes are disallowed")
        if re.match(r"^\s*[-*]\s+Note:", ln):
            warnings.append(f"SKILL.md line {idx}: avoid 'Note:' prefix")


def _scan_skill_files(skill_dir: Path, errors: list[str]) -> None:
    text_suffixes = {".md", ".yaml", ".yml", ".py", ".json", ".txt"}
    for file_path in skill_dir.rglob("*"):
        if not file_path.is_file() or "__pycache__" in file_path.parts:
            continue
        if file_path.suffix in text_suffixes:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            for pat in SECRET_PATTERNS:
                if pat.search(content):
                    errors.append(f"Potential secret detected in {file_path.name}")
        if file_path.suffix == ".py":
            try:
                py_compile.compile(str(file_path), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(f"Python syntax error in {file_path.name}: {exc.msg}")


def validate_skill(skill_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not skill_dir.is_dir():
        return {"ok": False, "errors": [f"Not a directory: {skill_dir}"], "warnings": []}

    yaml_path = skill_dir / "skill.yaml"
    md_path = skill_dir / "SKILL.md"

    if not yaml_path.is_file():
        errors.append("Missing skill.yaml")
    if not md_path.is_file():
        errors.append("Missing SKILL.md")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}

    _validate_metadata(yaml_path, skill_dir.name, errors)
    _validate_markdown(md_path, errors, warnings)
    _scan_skill_files(skill_dir, errors)

    return {
        "ok": len(errors) == 0,
        "skill_dir": str(skill_dir),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args()
    result = validate_skill(args.skill_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
