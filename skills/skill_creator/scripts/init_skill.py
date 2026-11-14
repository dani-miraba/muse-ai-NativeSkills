#!/usr/bin/env python3
"""Scaffold a new Muse custom skill under ~/workspace/custom-skills/<skill_name>/."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

DEFAULT_CUSTOM_SKILLS_DIR = Path.home() / "workspace" / "custom-skills"
SYSTEM_SKILLS_DIR = Path("/opt/muse/skills")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def scaffold_skill(
    skill_name: str,
    *,
    title: str,
    description: str,
    category: str,
    include_in_prompt: bool,
    base_dir: Path,
    with_scripts: bool,
    with_references: bool,
) -> Path:
    if not NAME_RE.match(skill_name):
        raise ValueError(
            "skill_name must be snake_case (lowercase letters, digits, underscores)"
        )

    if SYSTEM_SKILLS_DIR.is_dir():
        system_names = {
            p.name.replace("-", "_") for p in SYSTEM_SKILLS_DIR.iterdir() if p.is_dir()
        }
        if skill_name in system_names:
            raise ValueError(
                f"'{skill_name}' collides with a system skill; choose a distinct name"
            )

    target_dir = base_dir / skill_name
    if target_dir.exists():
        raise FileExistsError(f"Skill directory already exists: {target_dir}")

    target_dir.mkdir(parents=True, exist_ok=False)
    if with_scripts:
        (target_dir / "scripts").mkdir(exist_ok=True)
    if with_references:
        (target_dir / "references").mkdir(exist_ok=True)

    skill_yaml = (
        f'name: "{skill_name}"\n'
        f'title: "{title}"\n'
        f'description: "{description}"\n'
        f'category: "{category}"\n'
        f"include_in_prompt: {'true' if include_in_prompt else 'false'}\n"
    )
    (target_dir / "skill.yaml").write_text(skill_yaml, encoding="utf-8")

    skill_md = (
        f"# {title}\n\n"
        "## Method\n\n"
        "- Replace this line with the first actionable step.\n\n"
        "- Verify outputs with a harmless read or local test before finishing.\n\n"
        "## Available connectors\n\n"
        "- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.\n\n"
        "- If nothing here fits, look on the web for a maintained API or MCP server and set it up with "
        "[Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.\n"
    )
    (target_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return target_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_name", help="snake_case skill folder and name")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--category", default="Work and knowledge")
    parser.add_argument("--include-in-prompt", action="store_true")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_CUSTOM_SKILLS_DIR)
    parser.add_argument("--no-scripts", action="store_true")
    parser.add_argument("--no-references", action="store_true")
    args = parser.parse_args()

    created = scaffold_skill(
        args.skill_name,
        title=args.title,
        description=args.description,
        category=args.category,
        include_in_prompt=args.include_in_prompt,
        base_dir=args.base_dir,
        with_scripts=not args.no_scripts,
        with_references=not args.no_references,
    )
    print(json.dumps({"ok": True, "created_dir": str(created)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileExistsError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
