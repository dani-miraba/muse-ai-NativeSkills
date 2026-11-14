#!/usr/bin/env python3
"""Enhanced MCP Streamable HTTP CLI client for Muse custom connectors.

Drop-in upgrade over /opt/muse/skills/custom-connector-setup/templates/mcp_client.py.
Adds:
- `list-tools --all` automatic cursor pagination
- Safe 1-time retry on `list-tools` or `--idempotent` calls
- Large-payload spill-to-file (`--max-inline-bytes`, `--spill-dir`)
- Structured JSON error output on failure
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DYNAMIC_CREDS_DIR = "/opt/muse/skills/custom-connector-setup/bin"
if DYNAMIC_CREDS_DIR not in sys.path:
    sys.path.insert(0, DYNAMIC_CREDS_DIR)

from dynamic_credentials import DynamicCredentialError, add_surrogate_to_request

PROVIDER = ""
ENDPOINT = ""
ALLOWED_TOOLS: set[str] = set()
PROTOCOLS = {"2025-11-25", "2025-06-18", "2025-03-26"}
DEFAULT_MAX_INLINE_BYTES = 16384


class McpError(RuntimeError):
    """Transport or protocol failure with structured category."""

    def __init__(self, message: str, *, category: str = "mcp_error") -> None:
        super().__init__(message)
        self.category = category


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise McpError(
            "MCP endpoint redirected; verify the endpoint before continuing",
            category="redirect_blocked",
        )


def shape_output(
    result: dict[str, Any],
    *,
    max_inline_bytes: int,
    spill_dir: Path,
    tool_name: str,
) -> dict[str, Any]:
    encoded = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) <= max_inline_bytes:
        return result
    spill_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in tool_name)
    out_path = spill_dir / f"mcp_{safe_name}_{int(time.time() * 1000)}.json"
    out_path.write_bytes(encoded)
    return {
        "spilled": True,
        "file_path": str(out_path),
        "size_bytes": len(encoded),
        "isError": bool(result.get("isError")),
        "top_level_keys": list(result.keys()),
    }


class Client:
    def __init__(self, *, timeout: float = 45.0):
        endpoint = urllib.parse.urlsplit(ENDPOINT)
        if (
            not PROVIDER.startswith("custom.")
            or endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.port not in (None, 443)
        ):
            raise McpError(
                "Configure a registered provider and its fixed HTTPS endpoint",
                category="configuration",
            )
        self.host = endpoint.hostname
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())
        self.session: str | None = None
        self.protocol = "2025-11-25"
        self.sequence = 0

    def send(self, method: str, params: dict[str, Any], *, notification: bool = False):
        self.sequence += 1
        request_id = None if notification else self.sequence
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            body["id"] = request_id
        encoded = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol,
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(
            ENDPOINT, data=encoded, headers=headers, method="POST"
        )
        add_surrogate_to_request(request, PROVIDER, allowed_hosts=[self.host])
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if session := response.headers.get("Mcp-Session-Id"):
                    if not all(33 <= ord(c) <= 126 for c in session):
                        raise McpError(
                            "MCP server returned an invalid session header",
                            category="protocol",
                        )
                    self.session = session
                if notification and response.status == 202:
                    return None
                if notification:
                    raise McpError(
                        "MCP server did not accept the initialization notification",
                        category="protocol",
                    )
                return self.read_result(response, request_id)
        except urllib.error.HTTPError as error:
            cat = "auth_or_scope" if error.code in (401, 403) else "http_error"
            raise McpError(
                f"MCP returned HTTP {error.code}; the operation was not replayed",
                category=cat,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise McpError(
                "MCP request did not complete; check any write before retrying",
                category="timeout_or_network",
            ) from None

    @staticmethod
    def decode(payload: bytes, request_id: int | None):
        message = json.loads(payload)
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise McpError(
                "MCP returned an invalid JSON-RPC message", category="protocol"
            )
        if type(message.get("id")) is not int or message["id"] != request_id:
            return None
        if "error" in message:
            err = message["error"]
            raise McpError(
                f"MCP returned a JSON-RPC error: {err}", category="jsonrpc_error"
            )
        if not isinstance(message.get("result"), dict):
            raise McpError("MCP returned no result object", category="protocol")
        return message["result"]

    @classmethod
    def read_result(cls, response, request_id: int | None):
        content_type = response.headers.get_content_type()
        if content_type == "application/json":
            result = cls.decode(response.read(), request_id)
            if result is None:
                raise McpError("MCP returned the wrong request ID", category="protocol")
            return result
        if content_type != "text/event-stream":
            raise McpError(
                "MCP returned an unsupported content type", category="protocol"
            )
        data: list[bytes] = []
        while True:
            line = response.readline()
            if not line:
                raise McpError(
                    "MCP event stream ended before the matching result",
                    category="protocol",
                )
            line = line.rstrip(b"\r\n")
            if line.startswith(b"data:"):
                data.append(line[5:].lstrip(b" "))
            elif not line and data:
                result = cls.decode(b"\n".join(data), request_id)
                data.clear()
                if result is not None:
                    return result

    def initialize(self):
        result = self.send(
            "initialize",
            {
                "protocolVersion": self.protocol,
                "capabilities": {},
                "clientInfo": {"name": "muse-custom-connector", "version": "1"},
            },
        )
        protocol = result.get("protocolVersion")
        capabilities = result.get("capabilities")
        if (
            not isinstance(protocol, str)
            or protocol not in PROTOCOLS
            or not isinstance(capabilities, dict)
            or not isinstance(capabilities.get("tools"), dict)
        ):
            raise McpError(
                "MCP server did not negotiate a supported tool protocol",
                category="protocol",
            )
        self.protocol = protocol
        self.send("notifications/initialized", {}, notification=True)


def run_with_optional_retry(fn, *, retry: bool):
    attempts = 2 if retry else 1
    for attempt in range(attempts):
        try:
            return fn()
        except McpError as exc:
            if not retry or exc.category != "timeout_or_network" or attempt + 1 >= attempts:
                raise
            time.sleep(1.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list-tools")
    listing.add_argument("--cursor")
    listing.add_argument("--all", action="store_true", help="Fetch all cursor pages")

    calling = subparsers.add_parser("call-tool")
    calling.add_argument("--name", required=True)
    calling.add_argument("--arguments-file", type=Path, required=True)
    calling.add_argument("--idempotent", action="store_true")
    calling.add_argument("--max-inline-bytes", type=int, default=DEFAULT_MAX_INLINE_BYTES)
    calling.add_argument("--spill-dir", type=Path, default=Path.cwd() / "tmp")

    args = parser.parse_args()

    if args.command == "call-tool":
        if args.name not in ALLOWED_TOOLS:
            parser.error(
                "Inspect this operation's schema and add its exact name to ALLOWED_TOOLS"
            )
        arguments = json.loads(args.arguments_file.read_bytes())
        if not isinstance(arguments, dict):
            parser.error("arguments must be a JSON object")

    def execute():
        client = Client()
        client.initialize()
        if args.command == "list-tools":
            if not args.all:
                return client.send(
                    "tools/list", {"cursor": args.cursor} if args.cursor else {}
                )
            all_tools: list[Any] = []
            cursor = args.cursor
            for _ in range(25):
                page = client.send("tools/list", {"cursor": cursor} if cursor else {})
                all_tools.extend(page.get("tools", []))
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            return {"tools": all_tools, "nextCursor": cursor}
        raw_result = client.send(
            "tools/call", {"name": args.name, "arguments": arguments}
        )
        return shape_output(
            raw_result,
            max_inline_bytes=args.max_inline_bytes,
            spill_dir=args.spill_dir,
            tool_name=args.name,
        )

    retry_allowed = args.command == "list-tools" or getattr(args, "idempotent", False)
    result = run_with_optional_retry(execute, retry=retry_allowed)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("isError") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (McpError, DynamicCredentialError, ValueError, OSError) as error:
        category = getattr(error, "category", "error")
        print(
            json.dumps({"ok": False, "category": category, "error": str(error)}),
            file=sys.stderr,
        )
        raise SystemExit(1)
