# Design and Evaluation

## Choose the right artifact

- Create a custom skill when Muse needs reusable instructions, local domain knowledge, or a repeatable workflow across future conversations.

- Update an existing custom skill when it already owns the same outcome and the change improves that outcome without changing its purpose.

- Create a custom connector when the reusable knowledge is mainly how to operate one external provider.

- Create an amendment when the needed correction belongs to a read-only system skill. Read `muse-constraints.md` before creating the amendment.

## Capture intent

- Reuse evidence from the current conversation before interviewing the user. Extract the task sequence, corrections, files, tools, expected result, and authorization boundaries already demonstrated.

- Ask about an edge case, input format, output format, dependency, or success criterion only when it would change the design or prevent a reliable result.

- Define the boundary in plain language. Identify a close request that the skill should not handle and where Muse should route it instead.

## Design discovery

- Write `skill.yaml` descriptions as one clear sentence that names the outcome and the situations in which Muse should find the skill.

- Use vocabulary that appears in realistic user requests, including related services, file formats, and actions where they help distinguish the skill.

- Set `include_in_prompt: true` for broadly useful capabilities that should remain visible in every conversation. Set it to `false` for specialized capabilities that should be found with `muse.skill_search`.

- Avoid making descriptions so broad that they capture adjacent work. A search-only skill still needs a precise description because search results must help Muse choose among related skills.

## Organize instructions

- Keep the common workflow, non-obvious constraints, and routing decisions in `SKILL.md`.

- Put optional variants, provider details, large schemas, and conditional procedures in focused reference files. Link each reference from the point where Muse should read it.

- Add a short contents list or search terms to a long reference when they make the needed section easier to locate.

- Add a script only when deterministic execution, repeated parsing, or consistent validation provides a concrete benefit. Keep scripts independent of undeclared tools and test them with safe local inputs.

- State the reason behind important constraints. Prefer a useful principle over a long list of brittle commands.

## Plan proportionate evaluation

- Skip extensive evaluation for a narrow and low-risk documentation skill after structural validation and a focused review.

- Create two or three realistic task prompts for a substantial or risky skill. Include ordinary wording, incomplete but recoverable context, and a close request outside the skill boundary.

- Define observable checks for deterministic results such as created files, parsed fields, validation errors, or unchanged source data. Use user review for subjective results such as clarity, tone, design, or usefulness.

- Test a search-only skill by running `muse.skill_search` with natural phrases that should find it and nearby phrases that should select something else.

- Preserve a copy of the prior skill before a meaningful update. Compare the same prompts against the prior and updated versions when doing so is practical.

- Correct the smallest general cause supported by the result. Do not add universal rules that only repair one test prompt.
