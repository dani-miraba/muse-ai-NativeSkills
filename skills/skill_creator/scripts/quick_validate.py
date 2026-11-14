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
PLACEHOLDER_PATTERNS = [
    re.compile(r"replace this line", re.IGNORECASE),
    re.compile(r"\b(?:todo|tbd)\b", re.IGNORECASE),
]
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
LOCAL_REFERENCE_RE = re.compile(r"\[[^\]]+\]\((references/[^)#]+)(?:#[^)]+)?\)")
COMMAND_RE = re.compile(
    r"^\s*(?:\$\s+)?(?:python3?|curl|wget|git|bash|sh|node|npm|pip|sqlite3)\b"
)
ACTIONLESS_BULLET_RE = re.compile(r"^\s*-\s+(?:this|that|the|a|an|it|there)\b", re.IGNORECASE)


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


def _validate_metadata(
    yaml_path: Path, folder_name: str, errors: list[str], warnings: list[str]
) -> dict[str, Any]:
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

    for field in ("title", "description", "category"):
        value = meta.get(field)
        if field in meta and (not isinstance(value, str) or not value.strip()):
            errors.append(f"skill.yaml field '{field}' must be a non-empty string")

    if "include_in_prompt" in meta and not isinstance(meta["include_in_prompt"], bool):
        errors.append("skill.yaml include_in_prompt must be true or false")

    amends = meta.get("amends")
    if amends is not None:
        if not isinstance(amends, dict) or set(amends.keys()) != {
            "skill",
            "reviewed_revision",
        }:
            errors.append("amends block must contain exactly 'skill' and 'reviewed_revision'")
        else:
            revision = str(amends["reviewed_revision"])
            if revision == "PENDING_LOCAL_SHA256":
                warnings.append(
                    "amends reviewed_revision will be replaced by the installer on Muse"
                )
            elif not SHA256_RE.match(revision):
                errors.append("amends reviewed_revision must be a 64-character SHA-256")

    return meta


def _validate_markdown(
    md_path: Path, skill_dir: Path, title: str, errors: list[str], warnings: list[str]
) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        errors.append("SKILL.md must not be empty")
        return
    if lines[0].strip() == "---":
        errors.append("SKILL.md must not contain YAML frontmatter")
    if not lines[0].startswith("# "):
        errors.append("SKILL.md must start with a level-1 '# Title' heading")
    elif lines[0][2:].strip() != title:
        errors.append("SKILL.md title must match skill.yaml title")

    in_fence = False
    previous_bullet = False
    for idx, ln in enumerate(lines, start=1):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            previous_bullet = False
            continue
        if in_fence:
            continue
        if "|" in ln and re.match(r"^\s*\|?.+\|.+\|?\s*$", ln):
            errors.append(f"SKILL.md line {idx}: Markdown tables are disallowed")
        if ";" in ln:
            errors.append(f"SKILL.md line {idx}: semicolon ';' is disallowed in prose")
        if "\u2014" in ln or "\u2013" in ln:
            errors.append(f"SKILL.md line {idx}: em/en dash is disallowed")
        if any(q in ln for q in ("\u201c", "\u201d", "\u2018", "\u2019")):
            errors.append(f"SKILL.md line {idx}: curly quotes are disallowed")
        if re.match(r"^\s*[-*]\s+Note:", ln):
            errors.append(f"SKILL.md line {idx}: 'Note:' prefix is disallowed")
        if re.match(r"^\s*\*\s+", ln):
            errors.append(f"SKILL.md line {idx}: use '- ' bullets, not '* '")
        if re.match(r"^\s*-\s+[^`]+:\s+", ln):
            errors.append(f"SKILL.md line {idx}: 'Label: text' bullets are disallowed")
        if previous_bullet and re.match(r"^\s*-\s+", ln):
            errors.append(f"SKILL.md line {idx}: leave one blank line between bullets")
        if ACTIONLESS_BULLET_RE.match(ln):
            warnings.append(f"SKILL.md line {idx}: begin the bullet with an action verb")
        if COMMAND_RE.match(ln):
            errors.append(f"SKILL.md line {idx}: put commands inside a fenced block")
        previous_bullet = bool(re.match(r"^\s*-\s+", ln))

    if in_fence:
        errors.append("SKILL.md contains an unclosed fenced code block")

    markdown = "\n".join(lines)
    for match in LOCAL_REFERENCE_RE.finditer(markdown):
        reference_path = skill_dir / match.group(1)
        if not reference_path.is_file():
            errors.append(f"SKILL.md links to missing reference: {match.group(1)}")
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(markdown):
            errors.append("SKILL.md contains an unfinished scaffold placeholder")


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

    skill_dir = skill_dir.resolve()

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

    meta = _validate_metadata(yaml_path, skill_dir.name, errors, warnings)
    _validate_markdown(md_path, skill_dir, str(meta.get("title", "")), errors, warnings)
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
