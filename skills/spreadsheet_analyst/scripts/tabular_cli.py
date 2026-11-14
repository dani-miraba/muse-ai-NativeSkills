#!/usr/bin/env python3
"""Low-RAM streaming tabular analyst CLI for Muse (Excel, CSV, JSON/NDJSON -> SQLite).

Designed for 6 GB RAM VMs:
- Shared schema inference & header sanitization between `inspect` and `ingest`
- Streaming CSV (BOM-aware + --delimiter), XLSX (openpyxl read_only/write_only),
  NDJSON, and incremental JSON array chunked parsing (with --array-key)
- Atomic post-commit dataset manifest with source_sha256, column_map, and status
- Read-only `query` with set_authorizer, monotonic timeout via set_progress_handler,
  stdout byte cap, and non-deterministic LIMIT warning sent to stderr
- Streaming `profile` (with per-column SQLite typeof distribution) and `export`
"""

from __future__ import annotations

import argparse
import codecs
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Iterable, Iterator

MAX_SQLITE_COLUMNS = 1990
DEFAULT_SAMPLE_ROWS = 200
DEFAULT_BATCH_SIZE = 1000
DEFAULT_QUERY_LIMIT = 50
DEFAULT_QUERY_TIMEOUT = 15.0
DEFAULT_MAX_STDOUT_BYTES = 32768
MAX_JSON_FLATTEN_DEPTH = 3

SQLITE_RESERVED = {
    "abort", "action", "add", "after", "all", "alter", "always", "analyze", "and",
    "as", "asc", "attach", "autoincrement", "before", "begin", "between", "by",
    "cascade", "case", "cast", "check", "collate", "column", "commit", "conflict",
    "constraint", "create", "cross", "current", "current_date", "current_time",
    "current_timestamp", "database", "default", "deferrable", "deferred", "delete",
    "desc", "detach", "distinct", "do", "drop", "each", "else", "end", "escape",
    "except", "exclude", "exclusive", "exists", "explain", "fail", "filter",
    "first", "following", "for", "foreign", "from", "full", "generated", "glob",
    "group", "groups", "having", "if", "ignore", "immediate", "in", "index",
    "indexed", "initially", "inner", "insert", "instead", "intersect", "into",
    "is", "isnull", "join", "key", "last", "left", "like", "limit", "match",
    "materialized", "natural", "no", "not", "nothing", "notnull", "null", "nulls",
    "of", "offset", "on", "or", "order", "others", "outer", "over", "partition",
    "plan", "pragma", "preceding", "primary", "query", "raise", "range",
    "recursive", "references", "regexp", "reindex", "release", "rename",
    "replace", "restrict", "returning", "right", "rollback", "row", "rows",
    "savepoint", "select", "set", "table", "temp", "temporary", "then", "ties",
    "to", "transaction", "trigger", "unbounded", "union", "unique", "update",
    "using", "vacuum", "values", "view", "virtual", "when", "where", "window",
    "with", "without",
}

SAFE_SQL_FUNCTIONS = {
    "abs", "avg", "char", "coalesce", "count", "date", "datetime", "glob",
    "hex", "ifnull", "iif", "instr", "json", "json_array", "json_array_length",
    "json_extract", "json_object", "json_type", "json_valid", "julianday",
    "length", "like", "lower", "ltrim", "max", "min", "nullif", "printf",
    "quote", "replace", "round", "rtrim", "strftime", "substr", "substring",
    "sum", "time", "total", "trim", "typeof", "unicode", "upper",
}

COMMON_ARRAY_KEYS = ("results", "items", "data", "orders", "records", "elements")

_HEADER_CLEAN_RE = re.compile(r"[^0-9A-Za-z_]+")
_TABLE_CLEAN_RE = re.compile(r"[^0-9A-Za-z_]")
_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?")
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_ORDER_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def detect_bom_and_encoding(path: Path) -> tuple[str, bool]:
    """Detect BOM explicitly; fallback to latin-1 only if UTF-8 decoding fails."""
    with path.open("rb") as f:
        head = f.read(65536)

    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig", False
    if head.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le", False
    if head.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be", False

    try:
        head.decode("utf-8")
        return "utf-8", False
    except UnicodeDecodeError:
        return "latin-1", True


def sanitize_headers(
    raw_headers: list[str], *, collision_sources: dict[str, str] | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Sanitize headers deterministically and return (sanitized, column_map)."""
    seen: set[str] = {"_source_row", "_source_sheet"}
    sanitized: list[str] = []
    col_map: list[dict[str, str]] = []

    for idx, raw in enumerate(raw_headers):
        orig = str(raw).strip() if raw is not None else ""
        reasons: list[str] = []
        if not orig:
            base = f"col_{idx + 1}"
            reasons.append("empty")
        else:
            base = _HEADER_CLEAN_RE.sub("_", orig).strip("_").lower()
            if not base or base[0].isdigit():
                base = f"c_{base}" if base else f"col_{idx + 1}"
            if base in SQLITE_RESERVED:
                base = f"{base}_col"
                reasons.append("reserved")
            if collision_sources and orig in collision_sources:
                reasons.append(collision_sources[orig])

        candidate = base
        suffix = 2
        while candidate in seen:
            candidate = f"{base}_{suffix}"
            suffix += 1
            if "duplicate" not in reasons:
                reasons.append("duplicate")

        seen.add(candidate)
        sanitized.append(candidate)
        if candidate != orig or reasons:
            col_map.append(
                {
                    "original": orig,
                    "sanitized": candidate,
                    "reason": ",".join(reasons) if reasons else "normalized",
                }
            )
    return sanitized, col_map


def infer_value_kind(val: Any) -> str:
    if val is None or val == "":
        return "null"
    if isinstance(val, bool):
        return "integer"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "real"
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return "null"
        if _INT_RE.fullmatch(s):
            return "integer"
        if _FLOAT_RE.fullmatch(s):
            return "real"
    return "text"


def merge_kinds(current: str, incoming: str) -> str:
    if incoming == "null":
        return current
    if current == "null":
        return incoming
    if current == incoming:
        return current
    if {current, incoming} == {"integer", "real"}:
        return "real"
    return "text"


def coerce_cell(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, (dt.datetime, dt.date, dt.time)):
        return val.isoformat()
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    s = str(val)
    if s == "":
        return None
    return s


def flatten_dict(
    obj: dict[str, Any],
    *,
    prefix: str = "",
    depth: int = 1,
    max_depth: int = MAX_JSON_FLATTEN_DEPTH,
) -> dict[str, Any]:
    """Flatten nested dicts up to max_depth; keep lists or deeper dicts as JSON text."""
    flat: dict[str, Any] = {}
    for k, v in obj.items():
        key = f"{prefix}_{k}" if prefix else str(k)
        if isinstance(v, dict) and depth < max_depth:
            flat.update(
                flatten_dict(v, prefix=key, depth=depth + 1, max_depth=max_depth)
            )
        elif isinstance(v, (dict, list)):
            flat[key] = json.dumps(v, ensure_ascii=False)
        else:
            flat[key] = v
    return flat


def _extract_by_dotted_path(obj: Any, dotted_path: str) -> Any:
    cur = obj
    for part in dotted_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _iter_json_array_stream(
    path: Path, encoding: str, array_key: str | None
) -> tuple[Iterator[dict[str, Any]], str | None]:
    """Stream JSON objects from NDJSON or a JSON array / wrapped object array."""
    with path.open("r", encoding=encoding, errors="replace") as f:
        first_non_ws = ""
        while True:
            ch = f.read(1)
            if not ch:
                break
            if not ch.isspace():
                first_non_ws = ch
                break

    if not first_non_ws:
        return iter([]), None

    if first_non_ws == "{" and array_key is None:
        with path.open("r", encoding=encoding, errors="replace") as f:
            lines = [f.readline() for _ in range(3)]
        non_empty = [ln.strip() for ln in lines if ln.strip()]
        if len(non_empty) >= 2 and all(ln.startswith("{") and ln.endswith("}") for ln in non_empty[:2]):
            def ndjson_gen() -> Iterator[dict[str, Any]]:
                with path.open("r", encoding=encoding, errors="replace") as fp:
                    for raw_line in fp:
                        line = raw_line.strip()
                        if not line:
                            continue
                        item = json.loads(line)
                        if isinstance(item, dict):
                            yield item
                        else:
                            yield {"value": item}
            return ndjson_gen(), "ndjson"

    decoder = json.JSONDecoder()

    def chunked_array_gen(start_pos: int) -> Iterator[dict[str, Any]]:
        with path.open("r", encoding=encoding, errors="replace") as fp:
            fp.seek(start_pos)
            buf = ""
            eof = False
            while True:
                while not eof and len(buf) < 65536:
                    chunk = fp.read(65536)
                    if not chunk:
                        eof = True
                    else:
                        buf += chunk
                buf = buf.lstrip()
                if not buf:
                    break
                if buf.startswith(","):
                    buf = buf[1:].lstrip()
                    continue
                if buf.startswith("]"):
                    break
                try:
                    obj, idx = decoder.raw_decode(buf)
                    buf = buf[idx:]
                    if isinstance(obj, dict):
                        yield obj
                    else:
                        yield {"value": obj}
                except json.JSONDecodeError:
                    if eof:
                        raise
                    more = fp.read(65536)
                    if not more:
                        eof = True
                    else:
                        buf += more

    if first_non_ws == "[":
        with path.open("r", encoding=encoding, errors="replace") as fp:
            pos = 0
            while True:
                ch = fp.read(1)
                pos = fp.tell()
                if ch == "[":
                    return chunked_array_gen(pos), "root_array"

    target_key = array_key
    with path.open("r", encoding=encoding, errors="replace") as fp:
        parsed = json.load(fp)
    if isinstance(parsed, dict):
        used_key = target_key
        arr = _extract_by_dotted_path(parsed, target_key) if target_key else None
        if arr is None and not target_key:
            for candidate in COMMON_ARRAY_KEYS:
                if isinstance(parsed.get(candidate), list):
                    arr = parsed[candidate]
                    used_key = candidate
                    break
        if isinstance(arr, list):
            def list_gen() -> Iterator[dict[str, Any]]:
                for item in arr:
                    yield item if isinstance(item, dict) else {"value": item}
            return list_gen(), used_key or "object"
        return iter([parsed]), "single_object"

    raise ValueError("Unsupported JSON root structure")


def detect_file_format(path: Path, explicit_fmt: str | None) -> str:
    if explicit_fmt:
        return explicit_fmt.lower()
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return "xlsx"
    if ext in (".csv", ".tsv"):
        return "csv"
    if ext in (".json", ".jsonl", ".ndjson"):
        return "json"
    raise ValueError(f"Cannot infer format from extension: {ext}; pass --format")


def iter_source_rows(
    path: Path,
    fmt: str,
    *,
    sheet: str | None = None,
    header_row: int | None = None,
    delimiter: str | None = None,
    array_key: str | None = None,
) -> tuple[list[str], Iterator[tuple[str | None, int, list[Any]]], dict[str, Any]]:
    """Return (raw_headers, row_iterator(sheet_name, source_row, values), meta)."""
    meta: dict[str, Any] = {"format": fmt}

    if fmt == "xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet_names = wb.sheetnames
        target_sheet = sheet or sheet_names[0]
        if target_sheet not in sheet_names:
            wb.close()
            raise ValueError(f"Sheet '{target_sheet}' not found; available: {sheet_names}")
        ws = wb[target_sheet]
        meta["sheets"] = sheet_names
        meta["selected_sheet"] = target_sheet
        meta["row_index_meaning"] = "1-based Excel worksheet row number"

        row_iter = ws.iter_rows(values_only=True)
        current_row_num = 0
        raw_headers: list[str] = []
        target_hdr_row = header_row or 1

        for row in row_iter:
            current_row_num += 1
            vals = list(row)
            if header_row is None:
                if any(v is not None and str(v).strip() != "" for v in vals):
                    raw_headers = ["" if v is None else str(v) for v in vals]
                    break
            elif current_row_num == target_hdr_row:
                raw_headers = ["" if v is None else str(v) for v in vals]
                break

        def xlsx_gen() -> Iterator[tuple[str | None, int, list[Any]]]:
            nonlocal current_row_num
            try:
                for row in row_iter:
                    current_row_num += 1
                    vals = list(row)
                    if not any(v is not None and str(v).strip() != "" for v in vals):
                        continue
                    yield target_sheet, current_row_num, vals
            finally:
                wb.close()

        return raw_headers, xlsx_gen(), meta

    if fmt == "csv":
        encoding, fell_back = detect_bom_and_encoding(path)
        meta["encoding_used"] = encoding
        meta["encoding_fallback"] = fell_back
        meta["row_index_meaning"] = "1-based logical CSV record number (excluding header)"

        if delimiter is None:
            with path.open("r", encoding=encoding, errors="replace", newline="") as f:
                sample = f.read(65536)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                delim = dialect.delimiter
            except csv.Error:
                delim = "\t" if path.suffix.lower() == ".tsv" else ","
        else:
            delim = "\t" if delimiter == "\\t" else delimiter
        meta["delimiter"] = delim

        fp = path.open("r", encoding=encoding, errors="replace", newline="")
        reader = csv.reader(fp, delimiter=delim)
        target_hdr = header_row or 1
        raw_headers = []
        rec_idx = 0
        for row in reader:
            rec_idx += 1
            if header_row is None:
                if any(cell.strip() != "" for cell in row):
                    raw_headers = row
                    break
            elif rec_idx == target_hdr:
                raw_headers = row
                break

        def csv_gen() -> Iterator[tuple[str | None, int, list[Any]]]:
            data_row_num = 0
            try:
                for row in reader:
                    if not any(cell.strip() != "" for cell in row):
                        continue
                    data_row_num += 1
                    yield None, data_row_num, list(row)
            finally:
                fp.close()

        return raw_headers, csv_gen(), meta

    if fmt == "json":
        encoding, fell_back = detect_bom_and_encoding(path)
        meta["encoding_used"] = encoding
        meta["encoding_fallback"] = fell_back
        meta["row_index_meaning"] = "0-based logical JSON record index"

        obj_iter, detected_source = _iter_json_array_stream(path, encoding, array_key)
        meta["json_source_mode"] = detected_source

        buffered: list[dict[str, Any]] = []
        raw_headers: list[str] = []
        seen_keys: set[str] = set()
        for _ in range(DEFAULT_SAMPLE_ROWS):
            try:
                item = next(obj_iter)
            except StopIteration:
                break
            flat = flatten_dict(item)
            buffered.append(flat)
            for k in flat.keys():
                if k not in seen_keys:
                    seen_keys.add(k)
                    raw_headers.append(k)

        def json_gen() -> Iterator[tuple[str | None, int, list[Any]]]:
            idx = 0
            for flat in buffered:
                yield None, idx, [flat.get(k) for k in raw_headers]
                idx += 1
            for item in obj_iter:
                flat = flatten_dict(item)
                yield None, idx, [flat.get(k) for k in raw_headers]
                idx += 1

        return raw_headers, json_gen(), meta

    raise ValueError(f"Unsupported format: {fmt}")


def analyze_sample_and_schema(
    raw_headers: list[str],
    row_iter: Iterator[tuple[str | None, int, list[Any]]],
    *,
    selected_columns: list[str] | None = None,
    sample_size: int = DEFAULT_SAMPLE_ROWS,
) -> tuple[list[str], list[dict[str, str]], list[str], list[tuple[str | None, int, list[Any]]], dict[str, Any]]:
    """Shared schema inference + column selection + heuristic warnings."""
    sanitized, col_map = sanitize_headers(raw_headers)

    if selected_columns:
        wanted = [c.strip() for c in selected_columns if c.strip()]
        idx_map: list[int] = []
        for w in wanted:
            if w in sanitized:
                idx_map.append(sanitized.index(w))
            elif w in raw_headers:
                idx_map.append(raw_headers.index(w))
            else:
                raise ValueError(f"Requested column '{w}' not found in headers")
        sanitized = [sanitized[i] for i in idx_map]
    else:
        idx_map = list(range(len(sanitized)))

    if len(sanitized) > MAX_SQLITE_COLUMNS:
        raise ValueError(
            f"Column count ({len(sanitized)}) exceeds safe SQLite limit ({MAX_SQLITE_COLUMNS}); "
            "pass --columns col1,col2,... to select required columns"
        )

    kinds = ["null"] * len(sanitized)
    none_counts = [0] * len(sanitized)
    sampled_rows: list[tuple[str | None, int, list[Any]]] = []

    for _ in range(sample_size):
        try:
            sheet_name, src_row, vals = next(row_iter)
        except StopIteration:
            break
        projected = [vals[i] if i < len(vals) else None for i in idx_map]
        sampled_rows.append((sheet_name, src_row, projected))
        for j, v in enumerate(projected):
            k = infer_value_kind(v)
            if k == "null":
                none_counts[j] += 1
            kinds[j] = merge_kinds(kinds[j], k)

    warnings: list[str] = []
    if sampled_rows:
        n_samp = len(sampled_rows)
        sparse_cols = [
            sanitized[j]
            for j in range(len(sanitized))
            if raw_headers[idx_map[j]].strip() and (none_counts[j] / n_samp) > 0.90
        ]
        if sparse_cols:
            warnings.append(
                f"possible_uncached_formulas_or_sparse_columns (>90% null in sample): {sparse_cols[:15]}"
            )

    final_types = ["TEXT" if k in ("null", "text") else k.upper() for k in kinds]
    info = {
        "warnings": warnings,
        "sample_rows_checked": len(sampled_rows),
        "idx_map": idx_map,
    }
    return sanitized, col_map, final_types, sampled_rows, info


def cmd_inspect(args: argparse.Namespace) -> int:
    path = Path(args.file)
    fmt = detect_file_format(path, args.format)
    raw_headers, row_iter, meta = iter_source_rows(
        path,
        fmt,
        sheet=args.sheet,
        header_row=args.header_row,
        delimiter=args.delimiter,
        array_key=args.array_key,
    )
    selected = args.columns.split(",") if args.columns else None
    try:
        sanitized, col_map, final_types, sampled_rows, info = analyze_sample_and_schema(
            raw_headers, row_iter, selected_columns=selected, sample_size=args.sample_rows
        )
    finally:
        if hasattr(row_iter, "close"):
            row_iter.close()

    preview = [
        {"_source_sheet": s, "_source_row": r, **dict(zip(sanitized, vals))}
        for s, r, vals in sampled_rows[:3]
    ]
    out = {
        "ok": True,
        "file": str(path),
        "source_sha256": sha256_file(path),
        "meta": meta,
        "column_count": len(sanitized),
        "schema": [{"name": n, "inferred_type": t} for n, t in zip(sanitized, final_types)],
        "column_map": col_map,
        "warnings": info["warnings"],
        "sample_rows": preview,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.file)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    table = _TABLE_CLEAN_RE.sub("_", args.table).lower()
    if not table or table[0].isdigit():
        raise ValueError("Invalid table name")

    fmt = detect_file_format(path, args.format)
    source_hash = sha256_file(path)
    raw_headers, row_iter, meta = iter_source_rows(
        path,
        fmt,
        sheet=args.sheet,
        header_row=args.header_row,
        delimiter=args.delimiter,
        array_key=args.array_key,
    )
    selected = args.columns.split(",") if args.columns else None
    try:
        sanitized, col_map, final_types, sampled_rows, info = analyze_sample_and_schema(
            raw_headers, row_iter, selected_columns=selected, sample_size=args.sample_rows
        )
        idx_map: list[int] = info["idx_map"]

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA cache_size = -16000")
            conn.execute("PRAGMA temp_store = FILE")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")

            if args.replace:
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')

            col_defs = ['"_source_sheet" TEXT', '"_source_row" INTEGER'] + [
                f'"{name}" {col_type}' for name, col_type in zip(sanitized, final_types)
            ]
            conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)})')

            placeholders = ", ".join(["?"] * (len(sanitized) + 2))
            col_list = ", ".join(['"_source_sheet"', '"_source_row"'] + [f'"{n}"' for n in sanitized])
            insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'

            observed_kinds = [t.lower() for t in final_types]
            row_count = 0
            batch: list[tuple[Any, ...]] = []

            def process_row(sheet_name: str | None, src_row: int, projected_vals: list[Any]) -> None:
                nonlocal row_count
                coerced = []
                for j, v in enumerate(projected_vals):
                    cv = coerce_cell(v)
                    k = infer_value_kind(cv)
                    observed_kinds[j] = merge_kinds(observed_kinds[j], k)
                    coerced.append(cv)
                batch.append((sheet_name, src_row, *coerced))
                row_count += 1
                if len(batch) >= DEFAULT_BATCH_SIZE:
                    conn.executemany(insert_sql, batch)
                    batch.clear()

            for s, r, vals in sampled_rows:
                process_row(s, r, vals)
            for s, r, vals in row_iter:
                projected = [vals[i] if i < len(vals) else None for i in idx_map]
                process_row(s, r, projected)

            if batch:
                conn.executemany(insert_sql, batch)
                batch.clear()

            conn.commit()
        finally:
            conn.close()
    finally:
        if hasattr(row_iter, "close"):
            row_iter.close()

    manifest_path = db_path.with_suffix(f"{db_path.suffix}.{table}.manifest.json")
    tmp_manifest = manifest_path.with_suffix(".tmp")
    manifest = {
        "status": "complete",
        "table": table,
        "db": str(db_path),
        "source_file": str(path),
        "source_sha256": source_hash,
        "row_count": row_count,
        "meta": meta,
        "warnings": info["warnings"],
        "column_map": col_map,
        "schema": [
            {
                "name": name,
                "initial_type": init_t,
                "observed_type": obs_k.upper() if obs_k != "null" else "NULL",
            }
            for name, init_t, obs_k in zip(sanitized, final_types, observed_kinds)
        ],
        "ingested_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_manifest.replace(manifest_path)

    print(
        json.dumps(
            {
                "ok": True,
                "status": "complete",
                "table": table,
                "row_count": row_count,
                "manifest_path": str(manifest_path),
                "warnings": info["warnings"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _open_readonly_sqlite(db_path: Path, timeout_seconds: float) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA temp_store = FILE")

    deadline = time.monotonic() + timeout_seconds

    def progress_handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(progress_handler, 10000)

    def authorizer(action: int, arg1: str | None, arg2: str | None, db_name: str | None, trigger: str | None) -> int:
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and arg2 and arg2.lower() in SAFE_SQL_FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    conn.set_authorizer(authorizer)
    return conn


def cmd_profile(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    table = _TABLE_CLEAN_RE.sub("_", args.table).lower()
    conn = _open_readonly_sqlite(db_path, args.timeout)
    try:
        cur = conn.execute(f'SELECT * FROM "{table}" LIMIT 0')
        col_names = [d[0] for d in cur.description or []]
        total_rows = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        profiles = []
        for col in col_names:
            if col in ("_source_sheet", "_source_row"):
                continue
            row = conn.execute(
                f'SELECT '
                f'SUM(CASE WHEN "{col}" IS NULL THEN 1 ELSE 0 END), '
                f'COUNT(DISTINCT "{col}"), '
                f'MIN("{col}"), '
                f'MAX("{col}") '
                f'FROM "{table}"'
            ).fetchone()
            type_rows = conn.execute(
                f'SELECT typeof("{col}"), COUNT(*) FROM "{table}" GROUP BY typeof("{col}")'
            ).fetchall()
            profiles.append(
                {
                    "column": col,
                    "null_count": row[0],
                    "distinct_count": row[1],
                    "min": row[2],
                    "max": row[3],
                    "type_distribution": {t: c for t, c in type_rows},
                }
            )
    finally:
        conn.close()

    print(
        json.dumps(
            {"ok": True, "table": table, "total_rows": total_rows, "columns": profiles},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _ensure_limit_clause(sql: str, default_limit: int) -> tuple[str, bool]:
    stripped = sql.strip().rstrip(";")
    has_limit = bool(_LIMIT_RE.search(stripped))
    has_order = bool(_ORDER_RE.search(stripped))
    if not has_limit:
        stripped = f"{stripped} LIMIT {default_limit}"
        return stripped, not has_order
    return stripped, False


def cmd_query(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    sql_text, warn_non_det = _ensure_limit_clause(args.sql, args.limit)
    if warn_non_det:
        print(
            "warning: applied default LIMIT without ORDER BY; row order is non-deterministic",
            file=sys.stderr,
        )

    conn = _open_readonly_sqlite(db_path, args.timeout)
    try:
        cur = conn.execute(sql_text)
        col_names = [d[0] for d in cur.description or []]
        rows = []
        total_bytes = 2
        truncated = False
        for raw_row in cur:
            rec = dict(zip(col_names, raw_row))
            rec_bytes = len(json.dumps(rec, ensure_ascii=False).encode("utf-8")) + 2
            if total_bytes + rec_bytes > args.max_bytes:
                truncated = True
                break
            rows.append(rec)
            total_bytes += rec_bytes
    finally:
        conn.close()

    out = {"ok": True, "row_count": len(rows), "truncated_by_bytes": truncated, "rows": rows}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = args.format.lower() if args.format else out_path.suffix.lstrip(".").lower()

    conn = _open_readonly_sqlite(db_path, args.timeout)
    count = 0
    try:
        cur = conn.execute(args.sql.strip().rstrip(";"))
        col_names = [d[0] for d in cur.description or []]

        if fmt == "csv":
            with out_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(col_names)
                for row in cur:
                    writer.writerow(row)
                    count += 1
        elif fmt in ("ndjson", "jsonl"):
            with out_path.open("w", encoding="utf-8") as f:
                for row in cur:
                    f.write(json.dumps(dict(zip(col_names, row)), ensure_ascii=False) + "\n")
                    count += 1
        elif fmt == "json":
            with out_path.open("w", encoding="utf-8") as f:
                f.write("[\n")
                first = True
                for row in cur:
                    if not first:
                        f.write(",\n")
                    f.write(json.dumps(dict(zip(col_names, row)), ensure_ascii=False))
                    first = False
                    count += 1
                f.write("\n]\n")
        elif fmt == "xlsx":
            import openpyxl

            wb = openpyxl.Workbook(write_only=True)
            ws = wb.create_sheet(title="export")
            ws.append(col_names)
            for row in cur:
                ws.append(list(row))
                count += 1
            wb.save(out_path)
        else:
            raise ValueError(f"Unsupported export format: {fmt}")
    finally:
        conn.close()

    print(json.dumps({"ok": True, "exported_rows": count, "out": str(out_path)}, ensure_ascii=False))
    return 0


def _add_source_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("file")
    subparser.add_argument("--format", choices=["xlsx", "csv", "json"])
    subparser.add_argument("--sheet")
    subparser.add_argument("--header-row", type=int)
    subparser.add_argument("--delimiter")
    subparser.add_argument("--array-key")
    subparser.add_argument("--columns")
    subparser.add_argument("--sample-rows", type=int, default=DEFAULT_SAMPLE_ROWS)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    ins = sub.add_parser("inspect")
    _add_source_args(ins)

    ing = sub.add_parser("ingest")
    _add_source_args(ing)
    ing.add_argument("--db", required=True)
    ing.add_argument("--table", required=True)
    ing.add_argument("--replace", action="store_true")

    prof = sub.add_parser("profile")
    prof.add_argument("--db", required=True)
    prof.add_argument("--table", required=True)
    prof.add_argument("--timeout", type=float, default=DEFAULT_QUERY_TIMEOUT)

    qry = sub.add_parser("query")
    qry.add_argument("--db", required=True)
    qry.add_argument("--sql", required=True)
    qry.add_argument("--limit", type=int, default=DEFAULT_QUERY_LIMIT)
    qry.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_STDOUT_BYTES)
    qry.add_argument("--timeout", type=float, default=DEFAULT_QUERY_TIMEOUT)

    exp = sub.add_parser("export")
    exp.add_argument("--db", required=True)
    exp.add_argument("--sql", required=True)
    exp.add_argument("--out", required=True)
    exp.add_argument("--format", choices=["csv", "json", "ndjson", "jsonl", "xlsx"])
    exp.add_argument("--timeout", type=float, default=DEFAULT_QUERY_TIMEOUT)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handlers = {
        "inspect": cmd_inspect,
        "ingest": cmd_ingest,
        "profile": cmd_profile,
        "query": cmd_query,
        "export": cmd_export,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
