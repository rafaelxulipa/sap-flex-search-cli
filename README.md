# flexsearch-cli

Python CLI to run FlexibleSearch queries against SAP Commerce Cloud 2211 via the HAC console execute endpoint. Handles HAC's form login + CSRF token, persists the session cookie, and renders results as table / JSON / CSV.

Verified end-to-end against:
- CCv2 `backgroundprocessing` aspect (HAC served at host root, `base_path: /`)
- Local / legacy Hybris (HAC at `/hac`, `base_path: /hac`)

## Install

The repo ships with a `mise.toml` that auto-creates a `.venv` via `uv`. If you have [mise](https://mise.jdx.dev) + [uv](https://github.com/astral-sh/uv):

```bash
cd /path/to/flexsearch-cli
mise install         # installs latest python
uv pip install -e ".[dev]"
# Now `flexsearch` is on PATH whenever this dir is mise-active.
```

Otherwise, with any Python ≥ 3.9:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
# Run as: .venv/bin/flexsearch ...

# Or install globally with pipx:
pipx install /path/to/flexsearch-cli
```

## First run

```bash
flexsearch config init                      # writes ~/.flexsearch/config.yaml
$EDITOR ~/.flexsearch/config.yaml           # set urls / password_env per profile

# either export the env var...
export HAC_LOCAL_PASS=nimda
# ...or drop it in a .env file (see "Credentials" below)
echo "HAC_LOCAL_PASS=nimda" > ~/.flexsearch/.env

flexsearch login                            # one-shot login, caches cookie
```

Sample config:

```yaml
default_profile: local
profiles:
  local:
    url: https://localhost:9002
    user: admin
    password_env: HAC_LOCAL_PASS
    verify_ssl: false
    base_path: /hac          # legacy / local install
  s1:
    # CCv2 backgroundprocessing aspect mounts HAC at the host root
    url: https://backgroundprocessing.<env>-s1-public.model-t.cc.commerce.ondemand.com
    user: admin
    password_env: HAC_S1_PASS
    base_path: /              # default (root)
```

`base_path` is the webapp context root for HAC. Common values:

| `base_path` | When to use |
|-------------|-------------|
| `/` (default) | CCv2 backgroundprocessing aspect (`backgroundprocessing.*`), HAC served at root |
| `/hac` | Legacy / local Hybris install, traditional `/hac/...` mount |
| anything else | Custom deployments |

All HAC endpoints (login, console pages, execute) are built as `<url><base_path>/<rest>`.

Profile selection: `--profile NAME` > `FLEXSEARCH_PROFILE` env > `default_profile`.

## Credentials

Each profile names an env var via `password_env`. The CLI auto-loads `.env` files before resolving it, in this order (first match wins per key, real exported env vars always win):

1. `--env-file PATH` (CLI flag)
2. `./.env` in the current working directory
3. `~/.flexsearch/.env`

So a `.env` like:

```env
HAC_LOCAL_PASS=nimda
HAC_DEV_PASS=...
HAC_PRD_PASS=...
```

…is picked up automatically. Don't commit it.

## Usage

```bash
# inline query
flexsearch query -q "select {pk}, {code} from {Product}" -m 10

# from file
flexsearch query -f my_query.fxs -F json | jq

# from stdin
echo "select {pk} from {User}" | flexsearch query -F csv -o users.csv

# pick profile
flexsearch -p s1 query -q "select count(*) from {Product}"

# explicit env file (overrides the search above)
flexsearch --env-file ./secrets/.env.prd -p prd query -q "..."

# inspect resolved profile
flexsearch -p s1 config show

# list all profiles
flexsearch config list

# REPL — multi-line, terminate with ;
flexsearch repl

# verbose mode — prints every HTTP request URL + status (handy for debugging URL drift / WAF blocks)
flexsearch -v query -q "..."
```

Sample successful run against a CCv2 S1 env:

```text
$ flexsearch -p s1 query -q "select count(*) from {Product}"
┏━━━━━━━━┓
┃        ┃
┡━━━━━━━━┩
│ 210414 │
└────────┘
1 row(s) in 50 ms
```

## Safety

Non-SELECT queries (UPDATE/DELETE/DROP/...) are refused unless you pass both `--commit --i-know-what-im-doing`. On `prd`-named profiles you also get a confirmation prompt. The REPL is read-only with no override.

## Output formats

- `table` (default) — Rich-rendered ASCII table.
- `json` — `{ query, executionTime, headers, rows: [{col: val, ...}] }`. Add `--raw` to dump the raw HAC payload (`{ headers, resultList, executionTime, exception, query }`).
- `csv` — RFC4180 CSV with header row.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## How it works

All paths below are relative to `<url><base_path>` (e.g. `/` on CCv2 backgroundprocessing, `/hac` on legacy installs).

1. `GET <base_path>/` — follow redirects to whatever login page HAC serves on this build (`/login`, `/login.jsp`, ...).
2. Parse the login `<form>` to discover its real `action` URL plus the actual `name` of the username/password/CSRF/hidden fields.
3. `POST` to that action with credentials → captures `JSESSIONID`.
4. Probe `<base_path>/`, `console/flexsearch`, `platform/flexsearch`, `flexsearch` for a CSRF token (any HAC page works).
5. `POST <base_path>/console/flexsearch/execute` (with fallbacks `platform/flexsearch/execute`, `flexsearch/execute`), form-urlencoded with `flexibleSearchQuery`, `user`, `locale`, `maxCount`, `commit` — JSON response parsed into rows.

Cookies persist at `~/.cache/flexsearch/<profile>.cookies`. On 401/redirect-to-login the client re-authenticates once and retries.

## Troubleshooting

Run with `-v` to see every HTTP URL + status code. Common cases:

- **HTTP 404 on every `/hac/...` URL on a CCv2 env** — the `backgroundprocessing` aspect mounts HAC at the host root, not under `/hac`. Set `base_path: /` (or remove the field) on that profile.
- **HTTP 405 on POST `j_spring_security_check`** — the HAC build uses a non-legacy form action (`/login`, custom path, etc.). The CLI now scrapes the form's real `action` automatically; if it still fails, your env probably routes login through SSO/SAML which this CLI doesn't handle.
- **HTTP 404 / 405 from a CCv2 `*-public.model-t.cc.commerce.ondemand.com` URL where everything looks blocked** — the public Akamai WAF blocks HAC. Either get your IP allowlisted on the env's HAC endpoint, or use the SAP Cloud Portal "Open HAC" link to get a temporary authorized URL.
- **`No CSRF token found on any HAC page`** — non-fatal warning; the request is sent without one. If HAC actually requires it on this env, you'll get a 403 with a clear message; share the `-v` output and we'll pin the right selector.
- **Stale cookie issues** — `flexsearch -p <name> login` force-refreshes the session jar.
