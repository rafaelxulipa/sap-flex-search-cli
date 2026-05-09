# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Python CLI (`flexsearch`) that runs FlexibleSearch (FXS) queries against SAP Commerce Cloud 2211 / Hybris via the HAC console execute endpoint. It's a thin scraper around HAC's form login + CSRF flow — no Hybris SDK, just `requests` + `beautifulsoup4`.

Verified end-to-end against:
- CCv2 `backgroundprocessing` aspect (HAC at host root, `base_path: /`)
- Local / legacy Hybris (HAC at `/hac`)

## Common commands

```bash
# Install (mise + uv path; repo has mise.toml that auto-creates .venv)
mise install
uv pip install -e ".[dev]"

# Plain venv path
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Tests
pytest -q
pytest tests/test_safety.py -q              # single file
pytest tests/test_safety.py::test_name -q   # single test

# Run CLI locally
flexsearch -p s1 query -q "select count(*) from {Product}"
flexsearch -v query -q "..."                # verbose: prints every HTTP URL + status
flexsearch -p s1 config show                # inspect resolved profile
flexsearch login                            # force-refresh cookie jar
flexsearch repl                             # multi-line, terminate with ';'
```

There is no lint/format config in this repo.

## Architecture

Single Python package under `src/flexsearch/`. Module responsibilities:

- `cli.py` — Click entry point (`flexsearch = "flexsearch.cli:main"`). Defines top-level group + `query`, `repl`, `login`, `config {show,list,init}` subcommands. Loads `.env` files in this order before reading `password_env`: `--env-file` → `./.env` → `~/.flexsearch/.env` (existing env vars always win). Profile selection precedence: `--profile` flag > `FLEXSEARCH_PROFILE` env > `default_profile` in config.
- `config.py` — YAML config loader (`~/.flexsearch/config.yaml`), `Profile` model, `write_sample()`. `Profile.normalized_base_path` and `Profile.base_url` are how everything else builds URLs. Cookie path: `~/.cache/flexsearch/<profile>.cookies`.
- `client.py` — `HacClient` / `HacError`. The whole HAC dance lives here. **All HAC URLs are built as `<url><base_path>/<rest>`**, so `base_path` (`/`, `/hac`, custom) is the load-bearing field that distinguishes CCv2 from legacy.
- `safety.py` — `is_read_only(sql)` / `find_write_verbs(sql)`. Pure functions; the CLI uses these to gate non-SELECT queries behind `--commit --i-know-what-im-doing`. REPL is hard-coded read-only with no override.
- `output.py` — `render_table` (Rich), `render_json` (with `--raw` for the unwrapped HAC payload), `render_csv` (RFC4180).
- `repl.py` — prompt_toolkit REPL; lazy-imported from `cli.py` so prompt_toolkit only loads when used.

### How `HacClient` talks to HAC

This is the part that's non-obvious from reading code in isolation:

1. `GET <base_path>/` and follow redirects to whatever login page the HAC build serves (`/login`, `/login.jsp`, custom).
2. **Parse the login `<form>` to discover the real `action` URL plus the actual `name` of username / password / CSRF / hidden fields** — do not assume `j_spring_security_check` or `j_username`. Different HAC builds use different field names.
3. POST credentials to that scraped action → `JSESSIONID`.
4. Probe `<base_path>/`, `console/flexsearch`, `platform/flexsearch`, `flexsearch` for a CSRF token (any HAC page works). Missing token is a non-fatal warning.
5. POST to `<base_path>/console/flexsearch/execute` (fallbacks: `platform/flexsearch/execute`, `flexsearch/execute`), form-urlencoded with `flexibleSearchQuery`, `user`, `locale`, `maxCount`, `commit`. Response is JSON; parsed into rows.

Cookies persist per-profile. On 401 / redirect-to-login, the client re-authenticates **once** and retries.

### Safety model

- `query` subcommand: non-SELECT verbs are refused unless **both** `--commit` and `--i-know-what-im-doing` are passed. Profiles named `prd` / `prod` / `production` get an extra confirmation prompt.
- `repl`: read-only, no override path exists.
- When changing safety logic, update `safety.py` and the corresponding tests in `tests/test_safety.py` together — the gating in `cli.py:query` calls these directly.

## Configuration

Config lives at `~/.flexsearch/config.yaml` (or `--config PATH`). Each profile has `url`, `user`, `password_env`, `verify_ssl`, `base_path`. The password is **always** read from the env var named by `password_env` — never stored in the YAML. Drop secrets into `~/.flexsearch/.env` or `./.env` rather than exporting.

`base_path` cheat sheet:
- `/` (default) → CCv2 backgroundprocessing aspect
- `/hac` → legacy / local Hybris
- anything else → custom deployments

## Output formats

- `table` (default) — Rich ASCII table
- `json` — `{ query, executionTime, headers, rows: [{col: val, ...}] }`; `--raw` dumps the unwrapped HAC payload (`{ headers, resultList, executionTime, exception, query }`)
- `csv` — RFC4180 with header row

## Troubleshooting cues for code changes

- `404` on every `/hac/...` against a CCv2 env → that profile's `base_path` should be `/`, not `/hac`.
- `405` on POST to `j_spring_security_check` → the form-scraping in `client.py` step 2 is not finding the right action; do not hardcode the legacy path.
- `404 / 405` from a `*-public.model-t.cc.commerce.ondemand.com` URL → Akamai WAF, not a code bug.
- Stale cookies → `flexsearch -p <name> login` clears the jar.
