#!/usr/bin/env python3
"""Resilient REST client helper built on top of Muse's dynamic_credentials.

Provides:
- Safe surrogate injection via /opt/muse/skills/custom-connector-setup/bin/dynamic_credentials.py
- Redirect blocking on authenticated requests
- Exponential backoff + Retry-After handling for 429/5xx on safe/idempotent calls
- Generic pagination helpers (offset, cursor, Link header)
- Large-payload spill-to-file to protect agent context
- Structured error payloads and dry-run previews
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable

DYNAMIC_CREDS_DIR = "/opt/muse/skills/custom-connector-setup/bin"
if DYNAMIC_CREDS_DIR not in sys.path:
    sys.path.insert(0, DYNAMIC_CREDS_DIR)

from dynamic_credentials import (
    DynamicCredentialError,
    add_surrogate_to_request,
    read_response_body,
    url_with_surrogate_path_segment,
    url_with_surrogate_query_param,
)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_INLINE_BYTES = 16384
DEFAULT_MAX_RETRIES = 2
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel=["\']?next["\']?')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Block HTTP redirects so credentials are never forwarded across hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RestClientError(
            f"HTTP redirect {code} blocked for security; verify endpoint",
            category="redirect_blocked",
            status=code,
            retryable=False,
        )


class RestClientError(RuntimeError):
    """Structured REST client failure."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        status: int | None = None,
        retryable: bool = False,
        body_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.status = status
        self.retryable = retryable
        self.body_excerpt = body_excerpt

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": self.message,
            "category": self.category,
            "retryable": self.retryable,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.body_excerpt:
            payload["body_excerpt"] = self.body_excerpt
        return payload


def _classify_http_status(status: int) -> tuple[str, bool]:
    if status in (401, 403):
        return "auth_or_scope", False
    if status == 429:
        return "rate_limited", True
    if 400 <= status < 500:
        return "client_or_validation", False
    if 500 <= status < 600:
        return "server_error", True
    return "http_error", False


def _parse_retry_after(headers: Any) -> float | None:
    if not headers:
        return None
    raw = headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw.strip())
        return max(0.0, min(seconds, 30.0))
    except ValueError:
        return None


def _truncate_text(raw: bytes | str, limit: int = 800) -> str:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def shape_response(
    data: Any,
    *,
    max_inline_bytes: int = DEFAULT_MAX_INLINE_BYTES,
    spill_dir: str | Path | None = None,
    prefix: str = "rest_response",
) -> dict[str, Any]:
    """Return data inline if small, or spill to a file with a compact summary."""

    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) <= max_inline_bytes:
        return {"ok": True, "spilled": False, "size_bytes": len(encoded), "data": data}

    target_dir = Path(spill_dir) if spill_dir else Path.cwd() / "tmp"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{int(time.time() * 1000)}.json"
    out_path = target_dir / filename
    out_path.write_bytes(encoded)

    summary: dict[str, Any] = {
        "ok": True,
        "spilled": True,
        "file_path": str(out_path),
        "size_bytes": len(encoded),
    }
    if isinstance(data, dict):
        summary["top_level_keys"] = list(data.keys())[:30]
        for key in ("results", "items", "data", "elements", "orders"):
            if isinstance(data.get(key), list):
                summary["list_key"] = key
                summary["item_count"] = len(data[key])
                summary["sample_first"] = data[key][0] if data[key] else None
                break
    elif isinstance(data, list):
        summary["item_count"] = len(data)
        summary["sample_first"] = data[0] if data else None
    return summary


def _append_query_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    parsed = urllib.parse.urlsplit(url)
    existing = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    for k, v in params.items():
        if v is not None:
            existing.append((str(k), str(v)))
    return urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(existing))
    )


class RobustRestClient:
    """Reusable REST client wrapping dynamic_credentials and safe retry/pagination."""

    def __init__(
        self,
        provider: str,
        allowed_hosts: Iterable[str],
        *,
        placement: str = "bearer_header",
        entry_name: str = "access_token",
        auth_required: bool = True,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        user_agent: str = "muse-custom-connector-pro/1.0",
    ) -> None:
        self.provider = provider
        self.allowed_hosts = [h.strip().lower() for h in allowed_hosts if h.strip()]
        self.placement = placement
        self.entry_name = entry_name
        self.auth_required = auth_required
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.opener = urllib.request.build_opener(NoRedirect())

    def _build_url_and_attach_auth(
        self, url: str, params: dict[str, Any] | None
    ) -> tuple[str, bool]:
        url = _append_query_params(url, params)

        if not self.auth_required:
            return url, False

        if self.placement == "query_param":
            url = url_with_surrogate_query_param(
                url,
                self.provider,
                entry_name=self.entry_name,
                allowed_hosts=self.allowed_hosts,
            )
            return url, False
        if self.placement == "url_path_segment":
            url = url_with_surrogate_path_segment(
                url,
                self.provider,
                entry_name=self.entry_name,
                allowed_hosts=self.allowed_hosts,
            )
            return url, False
        return url, True

    def preview_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return a safe dry-run preview without sending any network request."""

        final_url = _append_query_params(url, params)
        return {
            "ok": True,
            "dry_run": True,
            "method": method.upper(),
            "url": final_url,
            "provider": self.provider if self.auth_required else None,
            "headers": sorted(list((headers or {}).keys())),
            "json_body": json_body,
        }

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        allow_retry: bool | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[Any, dict[str, str]]:
        """Execute an HTTP request and return (parsed_json, response_headers)."""

        upper_method = method.upper()
        if not url.startswith("https://"):
            raise RestClientError(
                "Only HTTPS endpoints are permitted",
                category="client_or_validation",
                retryable=False,
            )

        can_retry = (
            allow_retry
            if allow_retry is not None
            else (upper_method in SAFE_METHODS or bool(idempotency_key))
        )
        attempts = (self.max_retries + 1) if can_retry else 1

        body_bytes: bytes | None = None
        req_headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if headers:
            req_headers.update(headers)
        if idempotency_key and "Idempotency-Key" not in req_headers:
            req_headers["Idempotency-Key"] = idempotency_key
        if json_body is not None:
            body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

        last_error: RestClientError | None = None

        for attempt in range(attempts):
            try:
                target_url, attach_header = self._build_url_and_attach_auth(url, params)
                req = urllib.request.Request(
                    target_url,
                    data=body_bytes,
                    headers=req_headers,
                    method=upper_method,
                )
                if attach_header:
                    add_surrogate_to_request(
                        req,
                        self.provider,
                        entry_name=self.entry_name,
                        allowed_hosts=self.allowed_hosts,
                    )
                with self.opener.open(req, timeout=self.timeout) as resp:
                    raw = read_response_body(resp)
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    if not raw.strip():
                        return {}, resp_headers
                    try:
                        return json.loads(raw.decode("utf-8")), resp_headers
                    except json.JSONDecodeError:
                        return {"raw_text": raw.decode("utf-8", errors="replace")}, resp_headers

            except DynamicCredentialError as exc:
                raise RestClientError(
                    str(exc), category="auth_or_scope", retryable=False
                ) from None
            except RestClientError as exc:
                raise exc
            except urllib.error.HTTPError as exc:
                raw_err = exc.read() if exc.fp else b""
                category, retryable = _classify_http_status(exc.code)
                last_error = RestClientError(
                    f"HTTP {exc.code} from {urllib.parse.urlsplit(url).hostname}",
                    category=category,
                    status=exc.code,
                    retryable=retryable,
                    body_excerpt=_truncate_text(raw_err),
                )
                if not can_retry or exc.code not in RETRYABLE_STATUS_CODES or attempt + 1 >= attempts:
                    raise last_error from None
                delay = _parse_retry_after(exc.headers)
                if delay is None:
                    delay = min(1.5 * (2**attempt), 10.0)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = RestClientError(
                    f"Network or timeout error: {exc}",
                    category="timeout_or_network",
                    retryable=True,
                )
                if not can_retry or attempt + 1 >= attempts:
                    raise last_error from None
                time.sleep(min(1.5 * (2**attempt), 10.0))

        assert last_error is not None
        raise last_error

    def paginate_offset(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        items_key: str = "results",
        offset_param: str = "offset",
        limit_param: str = "limit",
        limit: int = 50,
        max_pages: int = 10,
    ) -> list[Any]:
        """Collect items across offset/limit pages."""

        collected: list[Any] = []
        base_params = dict(params or {})
        offset = int(base_params.get(offset_param, 0))
        for _ in range(max_pages):
            page_params = dict(base_params)
            page_params[offset_param] = offset
            page_params[limit_param] = limit
            payload, _ = self.request_json("GET", url, params=page_params)
            batch = payload.get(items_key, []) if isinstance(payload, dict) else []
            if not isinstance(batch, list) or not batch:
                break
            collected.extend(batch)
            if len(batch) < limit:
                break
            offset += len(batch)
        return collected

    def paginate_cursor(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        cursor_param: str = "cursor",
        extract_items: Callable[[Any], list[Any]],
        extract_next_cursor: Callable[[Any, dict[str, str]], str | None],
        max_pages: int = 10,
    ) -> list[Any]:
        """Collect items across cursor-paginated responses."""

        collected: list[Any] = []
        base_params = dict(params or {})
        cursor: str | None = None
        for _ in range(max_pages):
            page_params = dict(base_params)
            if cursor:
                page_params[cursor_param] = cursor
            payload, resp_headers = self.request_json("GET", url, params=page_params)
            batch = extract_items(payload)
            if batch:
                collected.extend(batch)
            cursor = extract_next_cursor(payload, resp_headers)
            if not cursor:
                break
        return collected

    def paginate_link_header(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        extract_items: Callable[[Any], list[Any]],
        max_pages: int = 10,
    ) -> list[Any]:
        """Collect items following RFC 8288 Link rel='next' headers."""

        collected: list[Any] = []
        next_url: str | None = url
        next_params: dict[str, Any] | None = params
        for _ in range(max_pages):
            if not next_url:
                break
            payload, resp_headers = self.request_json("GET", next_url, params=next_params)
            next_params = None
            batch = extract_items(payload)
            if batch:
                collected.extend(batch)
            link_header = resp_headers.get("Link") or resp_headers.get("link") or ""
            match = _LINK_NEXT_RE.search(link_header)
            next_url = match.group(1) if match else None
        return collected


def emit_json(payload: Any, *, exit_code: int = 0) -> int:
    """Print JSON deterministically to stdout and return exit_code."""

    print(json.dumps(payload, ensure_ascii=False))
    return exit_code
