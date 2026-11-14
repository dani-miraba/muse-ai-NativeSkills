# Custom Connector Pro

## Check for a blueprint first

- Check `~/workspace/custom-skills/custom_connector_pro/blueprints/` for `<provider>.md` before searching the web for API documentation.

- Read any matching blueprint first to confirm `api_hosts`, `auth_scheme`, scopes, pagination rules, and known limits.

- When a verified blueprint server URL is provided, download only files whose SHA-256 matches `manifest.json` before reading or executing them.

## Build resilient REST helpers

- Import `RobustRestClient`, `RestClientError`, `shape_response`, and `emit_json` from `~/workspace/custom-skills/custom_connector_pro/scripts/robust_rest.py` instead of writing raw `urllib.request` code per connector.

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "workspace/custom-skills/custom_connector_pro/scripts"))
```

- Keep every authenticated request inside `RobustRestClient`, which wraps `/opt/muse/skills/custom-connector-setup/bin/dynamic_credentials.py` and blocks HTTP redirects.

- Separate read commands, write commands, and `--dry-run` previews into distinct subcommands in each connector CLI.

- Enable `allow_retry=True` or pass an `idempotency_key` only on safe reads and explicitly idempotent writes, and never retry unguarded writes after a timeout.

- Route large responses through `shape_response` so payloads over 16 KB spill to a workspace file and return a compact summary.

## Build resilient MCP helpers

- Copy `~/workspace/custom-skills/custom_connector_pro/scripts/robust_mcp.py` when configuring a Streamable HTTP MCP connector, then set `PROVIDER`, `ENDPOINT`, and `ALLOWED_TOOLS`.

- Run `list-tools --all` to inspect every paginated tool schema before adding exact tool names to `ALLOWED_TOOLS`.

- Pass `--idempotent` on `call-tool` only for read-only or idempotent MCP operations.

## Verify and maintain

- Compile every Python helper with `python3 -m py_compile` and run one harmless read command before reporting that the connector works.

- Document every verified command, `--dry-run` flag, pagination mode, spill behavior, and post-timeout check in `~/workspace/custom-connectors/custom.<provider>/CONNECTOR.md`.

- Verify integrity or update this skill from a trusted server with `sync_vitamina.py`:

```text
python3 ~/workspace/custom-skills/custom_connector_pro/scripts/sync_vitamina.py --base-url https://<your-host>
```
