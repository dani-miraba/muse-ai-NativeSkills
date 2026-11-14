# Installing `spreadsheet_analyst`

This skill installs into `~/workspace/custom-skills/spreadsheet_analyst/` and provides low-RAM streaming inspection, SQLite ingestion, profiling, read-only querying, and export via `tabular_cli.py`.

## Automated installation (via Muse)

Share this repository URL with Muse and authorize the installation of `spreadsheet_analyst` following `AGENTS.md`.

## Manual verified installation

Replace `<BASE_URL>` with `https://raw.githubusercontent.com/<owner>/<repo>/main/skills/spreadsheet_analyst`:

```bash
curl -fsSL "<BASE_URL>/manifest.json" -o /tmp/manifest.json
curl -fsSL "<BASE_URL>/scripts/sync_skill.py" -o /tmp/sync_skill.py
python3 /tmp/sync_skill.py --base-url "<BASE_URL>"
python3 ~/workspace/custom-skills/spreadsheet_analyst/scripts/tabular_cli.py --help
```
