# Skill Creator

## Decide what to build first

- Search existing skills with `muse.skill_search` before creating a new one, and update the closest custom skill instead of duplicating functionality.

- Save a custom skill only when the workflow is reusable across future conversations, never for one-off task logs or personal user details.

- Create a connector doc under `~/workspace/custom-connectors/custom.<provider>/` when the knowledge applies to operating a single external service.

- Write an amendment when fixing a read-only system skill under `/opt/muse/skills/`, following `references/muse-constraints.md`.

## Scaffold the skill directory

- Initialize new custom skills under `~/workspace/custom-skills/<skill_name>/` with `init_skill.py` so the folder name, `skill.yaml`, and `SKILL.md` match Muse conventions.

```text
python3 ~/workspace/custom-skills/skill_creator/scripts/init_skill.py <skill_name> --title "<Skill Title>" --category "<Category>" --description "<One sentence outcome>"
```

- Keep `SKILL.md` short and focused on steps, moving edge cases into `references/` and deterministic parsing or validation into `scripts/`.

- Write Python helpers for a 6 GB RAM VM by streaming large inputs instead of loading full files into memory.

## Validate and test before saving

- Run `quick_validate.py` on the skill folder and confirm it passes with zero errors before reporting completion.

```text
python3 ~/workspace/custom-skills/skill_creator/scripts/quick_validate.py ~/workspace/custom-skills/<skill_name>
```

- Test every helper script locally with a harmless read or sample input, and never trigger external side effects just to verify a skill.

- State clearly any path that was not executed, and never store tokens, passwords, or API keys in any skill file.

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.
