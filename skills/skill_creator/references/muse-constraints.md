# Muse Skill Constraints

## Persistence and paths

- System files under `/opt/muse/` and `/opt/hatch/` are read-only and get replaced on every deployment.

- Persistent user skills live in `~/workspace/custom-skills/<skill_name>/`, and persistent connectors live in `~/workspace/custom-connectors/custom.<provider>/`.

- Never write secrets, API keys, passwords, or cookies into `SKILL.md`, `skill.yaml`, `references/`, or `scripts/`.

## Descriptor rules (`skill.yaml`)

- Use `snake_case` (lowercase letters, digits, and underscores) for `name` matching the folder name, and never reuse a system skill name.

- Include `name`, `title`, `description`, `category`, and `include_in_prompt` (`true` for always-listed skills, `false` for search-only skills).

- When amending a system skill, add `amends` with `skill` (the base skill `name` from its `skill.yaml`) and `reviewed_revision` (the 64-char SHA-256 of the base `SKILL.md`).

## Markdown formatting rules (`SKILL.md`)

- Omit YAML frontmatter from `SKILL.md` and start directly with `# <Skill Title>`.

- Address the agent in plain second person, starting each bullet with an action verb and keeping one blank line between bullets.

- Avoid semicolons, em dashes, en dashes, curly quotes, Markdown tables, `Label: text` bullets, and `Note:` prefixes.

- Put every shell or Python command inside a fenced code block, and keep `SKILL.md` focused on the workflow rather than duplicating connector commands.

## VM resource limits

- Target a 6 GB RAM and 150 GB disk environment by preferring streaming, disk-backed SQLite, and standard-library Python over loading full datasets into memory.
