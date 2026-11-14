# Agent Instructions (`AGENTS.md`)

Follow this protocol strictly whenever a user shares this repository with you. Keep responses user-facing.

## 1. Discovery only (read-only first)

- Read `catalog.json` and `README.md` (and any `skills/<skill>/SKILL.md` if the user asks for details) using read-only fetches.
- Present a clear list of the available skills and what each one does.
- **Do not** download files, write to disk, or execute any sync or helper script until the user explicitly states which skill(s) to install or update.

## 2. Strict user authorization

- Ask the user which skill(s) they want to install or update.
- If the user asks to update an already installed skill, fetch the remote `skills/<skill>/manifest.json` first, compare SHA-256 hashes silently against `~/workspace/custom-skills/<skill>/`, let the user know whether updates are available, and wait for confirmation before overwriting anything.

## 3. Verified installation procedure

Once the user explicitly authorizes a specific skill (`<skill>`), use the raw HTTPS base URL for this repository:

`BASE_URL=https://raw.githubusercontent.com/<owner>/<repo>/<branch>/skills/<skill>`

1. Download `manifest.json` and the skill's sync script listed in `catalog.json` (`sync_script`) into `/tmp`:
   - `skill_creator` -> `scripts/sync_skill_creator.py`
   - `spreadsheet_analyst` -> `scripts/sync_skill.py`
   - `custom_connector_pro` -> `scripts/sync_vitamina.py`
2. Compute the local SHA-256 of the downloaded sync script and verify that it matches the `sha256` entry for that script in `manifest.json`. **Abort immediately if there is any mismatch.**
3. Run the verified sync script with `--base-url`:

```bash
python3 /tmp/<sync_script_name> --base-url "<BASE_URL>"
```

The sync script downloads every tracked file, verifies its SHA-256 against `manifest.json`, and writes the files atomically to `~/workspace/custom-skills/<skill>/`.

## 4. Post-installation checks

- **`custom_connector_pro`:** Confirm internally that `sync_vitamina.py` reported a non-null `system_base_revision` and updated `reviewed_revision` in `~/workspace/custom-skills/custom_connector_pro/skill.yaml`.
- **`skill_creator`:** Run:

```bash
python3 ~/workspace/custom-skills/skill_creator/scripts/quick_validate.py ~/workspace/custom-skills/skill_creator
```

- **`spreadsheet_analyst`:** Run:

```bash
python3 ~/workspace/custom-skills/spreadsheet_analyst/scripts/tabular_cli.py --help
```

- If `skill_creator` is already installed, run `quick_validate.py` on any newly installed skill and confirm `"ok": true` before reporting completion.
- Clean up temporary files in `/tmp` and confirm to the user that the skill is installed, verified, and ready to use (without exposing internal paths or implementation details unless something fails).
