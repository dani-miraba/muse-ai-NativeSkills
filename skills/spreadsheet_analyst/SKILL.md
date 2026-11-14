# Spreadsheet and Tabular Analyst

## Route structured files here

- Use this skill for `.xlsx`, `.xlsm`, `.csv`, `.tsv`, `.json`, and `.jsonl` files, including spilled JSON outputs from custom connectors.

- Keep using the system `documents` skill for PDFs, Word files, and narrative documents with layout or figures.

- Never compute totals, counts, or joins manually over large tables, and never load full files into memory with `pandas.read_csv` or `pandas.read_excel`.

## Inspect before ingesting

- Run `inspect` first to check sheet names, encoding, delimiter, inferred types, column mapping, and warnings such as uncached Excel formulas.

```text
python3 ~/workspace/custom-skills/spreadsheet_analyst/scripts/tabular_cli.py inspect <file>
```

- Pass `--sheet`, `--header-row`, `--delimiter`, or `--array-key` (for wrapped API JSON such as `results` or `data`) when auto-detection needs overrides.

- When a file exceeds 1,990 columns, pass `--columns col1,col2,...` to keep only the required columns.

## Ingest and profile on disk

- Stream rows into a disk SQLite database in `/tmp` or a workspace folder to keep RAM usage low.

```text
python3 ~/workspace/custom-skills/spreadsheet_analyst/scripts/tabular_cli.py ingest <file> --db /tmp/work.sqlite --table <name> --replace
```

- Verify `<db>.<table>.manifest.json` for `status: "complete"`, `source_sha256`, and `column_map` before citing original column names, `_source_sheet`, and `_source_row`.

- Run `profile` to check null counts, distinct counts, min/max values, and SQLite `type_distribution` per column.

```text
python3 ~/workspace/custom-skills/spreadsheet_analyst/scripts/tabular_cli.py profile --db /tmp/work.sqlite --table <name>
```

## Query and export safely

- Run read-only SQL queries with `query`, which enforces `mode=ro`, a safe-function authorizer, a monotonic timeout, and a stdout byte cap.

```text
python3 ~/workspace/custom-skills/spreadsheet_analyst/scripts/tabular_cli.py query --db /tmp/work.sqlite --sql "SELECT * FROM <name> ORDER BY _source_row LIMIT 50"
```

- Stream large result sets directly to CSV, JSON, NDJSON, or XLSX with `export` instead of printing them to stdout.

```text
python3 ~/workspace/custom-skills/spreadsheet_analyst/scripts/tabular_cli.py export --db /tmp/work.sqlite --sql "SELECT * FROM <name> ORDER BY _source_row" --out /tmp/result.csv
```

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.
