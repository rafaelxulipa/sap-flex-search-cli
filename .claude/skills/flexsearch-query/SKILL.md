---
name: flexsearch-query
description: Run FlexibleSearch (FXS) queries against a SAP Commerce Cloud 2211 / Hybris instance via the local `flexsearch` CLI. Use this skill whenever the user asks to query a Hybris/Commerce database, count items in a Type, inspect a Product/Order/User/CMSComponent, run a `select {pk} from {Type}` query, dump rows from HAC, or generally "ask Hybris" something. Trigger phrases: "flexible search", "flex search", "fxs", "query Hybris", "query HAC", "count products", "select from {Type}", "run this against s1/d1/local", "how many orders/users/customers in <env>", "what's in the {Type} table", "Hybris flexsearch CLI". Works against local Hybris and CCv2 environments (backgroundprocessing aspect).
---

# FlexibleSearch Query Skill

Use the local `flexsearch` CLI to run FlexibleSearch queries against a Hybris / SAP Commerce Cloud 2211 instance. The CLI handles HAC login + CSRF, persists the session cookie, and emits table / JSON / CSV.

## When to use

- User asks to count, list, inspect, or query any Hybris Type (`Product`, `Order`, `User`, `Customer`, `CMSComponent`, `Catalog`, `Category`, `Media`, `Promotion`, anything in items.xml).
- User wants to verify data on a CCv2 environment (`local`, `d1`, `s1`, `p1`, etc.).
- User pastes a FlexibleSearch query and asks to run it.
- User asks a question that requires reading from the platform DB and is not asking for a code change.

Do **not** use this skill to:
- Modify data (the CLI refuses non-SELECT queries by default; do not bypass).
- Run impex / cronjobs / groovy — different consoles, not supported here.
- Run plain SQL — the CLI talks to FlexibleSearch only (use `{Type}` / `{attribute}` braces, not raw table names).

## Binary location

The CLI lives in a project venv. Prefer the absolute path so the skill works from any cwd:

```
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch
```

If `flexsearch` is on `$PATH` (e.g. mise auto-source in the project dir, or pipx install), use the bare name. When unsure, just use the absolute path.

## Profiles & secrets

Profiles are defined in `~/.flexsearch/config.yaml`. Each profile names a `password_env` env var. Passwords are auto-loaded from `.env` files in this order:

1. `--env-file PATH`
2. `./.env` in cwd
3. `~/.flexsearch/.env`

Existing exported env vars always win. **Never print or log password values.**

Inspect available profiles before running anything that depends on a specific env:

```bash
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch config list
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch -p s1 config show
```

## Running queries

Pick a profile with `-p <name>` (or rely on `default_profile`). The query goes via `-q` (inline), `-f` (file), or stdin. Default output is a Rich-rendered ASCII table; `-F json` and `-F csv` are also available.

### Examples

Count rows of a Type:
```bash
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch -p s1 query \
  -q "select count(*) from {Product}"
```

List a few products (limit results with `-m`):
```bash
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch -p s1 query \
  -q "select {pk}, {code}, {name} from {Product}" -m 20
```

JSON for piping to jq:
```bash
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch -p s1 query \
  -q "select {pk}, {code} from {Product}" -F json | jq '.rows | length'
```

CSV to file:
```bash
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch -p s1 query \
  -q "select {pk}, {code} from {Product}" -F csv -o /tmp/products.csv
```

Multi-line query from a file:
```bash
/Users/vinicius/Projects/flexsearch-cli/.venv/bin/flexsearch -p s1 query \
  -f /tmp/my_query.fxs
```

## Common flags

| Flag | Purpose |
|------|---------|
| `-p <profile>` | Profile name (`local`, `d1`, `s1`, ...). Comes before the subcommand. |
| `-q "<query>"` | Inline query. |
| `-f <path>` | Query from file (multi-line OK). |
| `-m <int>` | Max rows (default 200). Always cap when the user wants a peek. |
| `-l <locale>` | Localized attribute language (default `en`). |
| `-r <user>` | Run-as principal (default `admin`). |
| `-F table\|json\|csv` | Output format (default `table`). |
| `-o <file>` | Write output to file instead of stdout. |
| `--raw` | With `-F json`, emit the raw HAC payload (`headers`, `resultList`, `executionTime`, `exception`). |
| `-v` | Verbose: prints every HTTP request URL + status. Use only when debugging. |

Subcommands: `query`, `repl`, `login`, `config show|list|init`.

## FlexibleSearch syntax reminders

- Use `{Type}` for tables and `{attribute}` for columns: `select {pk}, {code} from {Product}`.
- Joins: `select {p.pk} from {Product as p join Catalog as c on {p.catalog} = {c.pk}}`.
- Localized attributes resolve to the requested `-l` locale: `select {p.name[en]} from {Product as p}`.
- WHERE with parameters is fine: `where {code} = 'ABC'`. The CLI does not support bind-parameter substitution; embed literals or escape carefully.
- `count(*)` is supported.
- For OR-mapped Item Types, query the parent type unless you need a subtype's discriminator.

## Safety

- The CLI **refuses** non-SELECT queries (`UPDATE`, `DELETE`, `INSERT`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `MERGE`, `REPLACE`) with exit code 2.
- Do not bypass with `--commit --i-know-what-im-doing` unless the user has explicitly asked for a write and confirmed the target environment. **Never** do this on `prd`-named profiles without a typed confirmation from the user.
- The REPL is hard read-only with no override.

## Failure modes & fixes

Read the message carefully. The CLI surfaces the actual HAC error.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Error: Profile '...': env var '...' is empty or unset.` | Password env var missing | Tell the user to add it to `.env` or export it. Do not invent the value. |
| `HAC login failed (status 405)` | Login URL wrong for this build | The CLI scrapes the form action — if it still fails, the env likely uses SSO/SAML which this CLI doesn't handle. |
| `All known FlexibleSearch endpoints returned 404` | Wrong `base_path` | CCv2 `backgroundprocessing.*` mounts HAC at root — set `base_path: /` (or remove). Local/legacy installs need `base_path: /hac`. |
| `404` on every URL on `*-public.model-t.cc.commerce.ondemand.com` | Akamai WAF blocks HAC on the public edge | IP allowlist in CCv2 endpoints, or use SAP Cloud Portal "Open HAC" for a temporary URL. Not a code issue. |
| `FlexibleSearch error: ...` | Query syntax / type / attribute error from HAC | Surface the message verbatim to the user; do not guess. |

For deep debugging add `-v` to print every HTTP request URL + status code.

## Operating defaults for agents

- Always pass `-m` with a sane cap (e.g. 50–200) when the user asks to "look at" or "list" something. Don't dump 500k rows.
- Quote queries with double quotes; FXS uses braces `{...}` and single-quoted literals which conflict with single-quoted shell strings.
- Prefer `-F json` when the result will be parsed/piped programmatically; prefer the default table when showing to the user.
- If the user doesn't specify a profile, ask once; do not assume `local` vs `s1`.
- Exit code 0 = success, 1 = HAC error, 2 = guardrail / usage error. Treat non-zero as failure and show stderr to the user.
- If a query is destined to be reused, save it under `~/.flexsearch/queries/<name>.fxs` and run via `-f`.
