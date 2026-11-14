# Installing `skill_creator`

This skill installs into `~/workspace/custom-skills/skill_creator/` and provides scaffolding (`init_skill.py`) and validation (`quick_validate.py`) for Muse custom skills.

## Automated installation (via Muse)

Share this repository URL with Muse and authorize the installation of `skill_creator` following `AGENTS.md`.

## Manual verified installation

Replace `<BASE_URL>` with `https://raw.githubusercontent.com/<owner>/<repo>/main/skills/skill_creator`:

```bash
curl -fsSL "<BASE_URL>/manifest.json" -o /tmp/manifest.json
curl -fsSL "<BASE_URL>/scripts/sync_skill_creator.py" -o /tmp/sync_skill_creator.py
python3 /tmp/sync_skill_creator.py --base-url "<BASE_URL>"
python3 ~/workspace/custom-skills/skill_creator/scripts/quick_validate.py ~/workspace/custom-skills/skill_creator
```
