# Legacy Codex CLI reference

The primary interface is the [macOS app](README.md). The Python CLI remains available;
this page keeps its commands without duplicating generated `--help` output.

## Reports

Run from the checkout root with Python 3.10+:

| Command | Report |
| --- | --- |
| `python3 codex_usage.py menu` | Interactive terminal menu |
| `python3 codex_usage.py all` | Local, online and reset-credit reports |
| `python3 codex_usage.py local-usage --days 60 --top 20` | Local metadata; no network |
| `python3 codex_usage.py online-usage` | Signed-in account limits and profile |
| `python3 codex_usage.py resets --warn-days 14` | Reset credits and expiry warnings |
| `python3 codex_usage.py api-usage --group-by model` | Organization API usage; requires `OPENAI_ADMIN_KEY` |

Without a command, an interactive terminal opens the menu; redirected input/output
selects `all`. Use `<command> --help` for options, `--json` on reports for JSON, or
`--no-colour` for plain terminal output.

## Export

```sh
python3 codex_usage.py export --report local-usage --format json --output-dir ./exports
```

Formats: `json`, `csv`, `txt`. Reports: `all`, `resets`, `local-usage`, `online-usage`,
`api-usage`. Without `--output-dir`, exports go to `~/Downloads/codex-usage`, subject
to `CODEX_USAGE_EXPORT_DIR`.

The bundled helper also runs CLI reports and exports without a separate Python installation:

```sh
./dist/Usage.app/Contents/Resources/helper/usage-helper --codex local-usage
```

[Configuration and known limitations](docs/development.md) ·
[Privacy](docs/privacy.md) · [Historical screenshots](docs/screenshots.md) · [License](LICENCE)
