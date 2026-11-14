# Muse Custom Skills

Meta does not provide public documentation on skills for `muse.ai`, yet the agent supports self-improvement and its VM accepts custom skills. Even though Muse can create and maintain custom skills, it does not ship with a built-in skill or guide defining how to structure, validate, and keep them within VM limits.

In the inspected VM (6 GB RAM, 150 GB disk), Muse included 57 system skills: 21 general skills, 7 internal skills, and 29 tied to specific APIs or MCP servers. Each region gets its own tailored VM, though the underlying file layout is expected to be the same. I adapted these three skills as an experiment; they installed cleanly on my assigned environment, and I am publishing them here with no guarantee that they will work on other VMs.

> **Agents:** Read [AGENTS.md](./AGENTS.md) before downloading, modifying, or installing any files from this repository.

## Available skills

| Skill | Version | Type | Purpose |
| --- | --- | --- | --- |
| [`skill_creator`](skills/skill_creator/) | `1.0.0` | Custom skill | Lightweight adaptation of Claude's `skill_creator` tailored to Muse's formatting, security, and low-RAM rules. |
| [`spreadsheet_analyst`](skills/spreadsheet_analyst/) | `1.0.0` | Custom skill | Built from scratch because Muse's built-in `documents` skill targets prose and page layout rather than exact calculations (`SUM`, `GROUP BY`, joins) over large CSV/Excel files or massive API JSON payloads (such as files spilled by `robust_rest.py`). |
| [`custom_connector_pro`](skills/custom_connector_pro/) | `1.0.0` | Amendment (`custom_connector_setup`) | Extension for Muse's `custom_connector_setup` skill that adds safe retries, pagination helpers, dry-run previews, and spill-to-file handling for large API responses so they do not flood context. |

## Repository layout

```text
.
├── AGENTS.md                 # Agent discovery and verified installation protocol
├── README.md
├── catalog.json              # Machine-readable skill index
├── scripts/
│   └── build_all.py          # Regenerates per-skill manifests and catalog.json
└── skills/
    ├── skill_creator/
    ├── spreadsheet_analyst/
    └── custom_connector_pro/
```

## Quick start with Muse

1. Share this repository URL with Muse and ask it to list the available skills and their usage.
2. Review the summary and confirm which skill(s) you want to install.
3. Muse will fetch the selected skill's `manifest.json`, verify every SHA-256 hash, install it under `~/workspace/custom-skills/<skill>/`, and run post-install checks.

## Maintaining manifests

Whenever you edit files under `skills/`, run:

```bash
python3 scripts/build_all.py
```

A GitHub Actions workflow (`.github/workflows/sync-manifests.yml`) also validates all skills with `quick_validate.py` and keeps `manifest.json` and `catalog.json` up to date on pushes to `main`.

## Disclaimer

This repository is strictly an experiment. While the base directory structure is expected to match across Muse VMs, it has not been verified across all regions or deployments.
