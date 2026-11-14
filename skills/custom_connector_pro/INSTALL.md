# Installing `custom_connector_pro`

This skill installs into `~/workspace/custom-skills/custom_connector_pro/` as an amendment to Muse's `custom_connector_setup` system skill, adding shared REST/MCP resilience helpers (`robust_rest.py`, `robust_mcp.py`) and optional provider blueprints.

## Automated installation (via Muse)

Share this repository URL with Muse and authorize the installation of `custom_connector_pro` following `AGENTS.md`.

## Manual verified installation

Replace `<BASE_URL>` with `https://raw.githubusercontent.com/<owner>/<repo>/main/skills/custom_connector_pro`:

```bash
curl -fsSL "<BASE_URL>/manifest.json" -o /tmp/manifest.json
curl -fsSL "<BASE_URL>/scripts/sync_vitamina.py" -o /tmp/sync_vitamina.py
python3 /tmp/sync_vitamina.py --base-url "<BASE_URL>"
```

During installation, `sync_vitamina.py` automatically computes the SHA-256 of `/opt/muse/skills/custom-connector-setup/SKILL.md` on the host VM and writes it to `reviewed_revision` in `skill.yaml`.
