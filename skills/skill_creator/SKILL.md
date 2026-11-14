# Skill Creator

## Identify the right change

- Read the conversation before asking questions, and extract the workflow, tools, corrections, inputs, outputs, and success criteria already established by the user.

- Search existing skills with `muse.skill_search` using outcome words, related services, formats, and actions before creating a new skill. Search even when no related skill appears in the prompt because search-only skills are not listed by default.

- Update the closest custom skill when it already covers the reusable workflow. Create a connector doc under `~/workspace/custom-connectors/custom.<provider>/` when the knowledge applies to one external service.

- Write an amendment when correcting a read-only system skill under `/opt/muse/skills/`, following `references/muse-constraints.md`.

- Save a custom skill only when the workflow is reusable across future conversations, never for one-off task logs or personal user details.

## Design before drafting

- Clarify only the missing details that affect the result, including the trigger, expected output, inputs, permissions, side effects, dependencies, and success criteria.

- Read [design-and-evaluation.md](references/design-and-evaluation.md) when creating a substantial skill, updating an existing skill, deciding whether it should be search-only, or planning tests.

- Describe what the skill delivers and when to find it in `skill.yaml`. Use terms a user would naturally use, and state a meaningful boundary when a similar request belongs elsewhere.

- Set `include_in_prompt: true` only for capabilities that should be available in most conversations. Set it to `false` for specialized capabilities that Muse should find through `muse.skill_search`.

- Keep the main workflow in `SKILL.md`, move conditional or domain-specific detail into linked files under `references/`, and add scripts only for deterministic or repeatedly implemented work.

## Scaffold and write the skill

- Initialize new custom skills under `~/workspace/custom-skills/<skill_name>/` with `init_skill.py` so the folder name, `skill.yaml`, and `SKILL.md` match Muse conventions.

```text
python3 ~/workspace/custom-skills/skill_creator/scripts/init_skill.py <skill_name> --title "<Skill Title>" --category "<Category>" --description "<One sentence outcome and when to use it>"
```

- Explain why a non-obvious instruction matters so Muse can apply it to new cases. Avoid rules that only fit one example or duplicate behavior already provided by Muse.

- Define an output structure or a short example only when consistency matters to the user. Keep examples representative rather than treating them as the only valid case.

- Disclose external writes, messages, purchases, data access, or other material effects before the step that performs them. Do not hide behavior that would surprise the user.

- Write Python helpers for a 6 GB RAM VM by streaming large inputs instead of loading full files into memory.

## Validate and improve

- Run `quick_validate.py` on the skill folder and resolve every error before reporting completion.

```text
python3 ~/workspace/custom-skills/skill_creator/scripts/quick_validate.py ~/workspace/custom-skills/<skill_name>
```

- Test every helper script locally with a harmless read or sample input, and never trigger external side effects just to verify a skill.

- Test meaningful or risky skills with realistic requests. Include a normal case, a boundary case, and a close request that should use another skill or connector.

- Test search-only skills with `muse.skill_search` using natural user language. Check both queries that should find the skill and near misses that should not.

- Compare an update with the prior version when practical. Preserve the previous version until the result is reviewed, then make the smallest change supported by the observed failure.

- Separate objective checks from human judgment. Automate verifiable facts, and ask the user to review subjective quality such as writing, usefulness, or visual style.

- State clearly any path that was not executed, and never store tokens, passwords, or API keys in any skill file.

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.
