from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from . import __version__, config as config_mod
from .client import HacClient, HacError
from .output import render_csv, render_json, render_table
from .safety import find_write_verbs, is_read_only

console = Console(stderr=True)

log = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _load_dotenv_files(explicit: Path | None) -> None:
    """Load .env files into os.environ. Existing env vars always win.

    Search order (first match wins per key):
      1. --env-file path (if given)
      2. ./.env in cwd
      3. ~/.flexsearch/.env
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path.home() / ".flexsearch" / ".env")
    for p in candidates:
        if p.exists():
            load_dotenv(p, override=False)
            log.debug("Loaded env file: %s", p)


def _read_query(query: str | None, file: Path | None) -> str:
    if query and file:
        raise click.UsageError("Use only one of -q/--query or -f/--file.")
    if query:
        return query
    if file:
        return Path(file).read_text()
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data
    raise click.UsageError("No query provided. Use -q, -f, or pipe via stdin.")


@click.group(invoke_without_command=False, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="flexsearch")
@click.option("--profile", "-p", help="Profile name from config (overrides FLEXSEARCH_PROFILE).")
@click.option("--config", "config_path", type=click.Path(path_type=Path), help="Path to config YAML.")
@click.option("--env-file", "env_file", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Path to a .env file (loaded before reading password_env).")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging.")
@click.pass_context
def main(ctx: click.Context, profile: str | None, config_path: Path | None, env_file: Path | None, verbose: bool) -> None:
    """Run FlexibleSearch queries against SAP Commerce 2211 via HAC."""
    _setup_logging(verbose)
    _load_dotenv_files(env_file)
    ctx.ensure_object(dict)
    ctx.obj["profile_name"] = profile
    ctx.obj["config_path"] = config_path


def _load_profile(ctx: click.Context):
    cfg = config_mod.load(ctx.obj.get("config_path"))
    return cfg, cfg.resolve(ctx.obj.get("profile_name"))


@main.command()
@click.option("-q", "--query", help="FlexibleSearch query string.")
@click.option("-f", "--file", "file", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Read query from file.")
@click.option("-m", "--max-count", type=int, default=200, show_default=True)
@click.option("-l", "--locale", default="en", show_default=True)
@click.option("-r", "--run-as", default="admin", show_default=True, help="Run query as this principal.")
@click.option("--commit", is_flag=True, help="Commit DML/DDL (gated).")
@click.option(
    "--i-know-what-im-doing",
    "override",
    is_flag=True,
    help="Required with --commit to allow non-SELECT queries.",
)
@click.option("-F", "--format", "fmt", type=click.Choice(["table", "json", "csv"]), default="table", show_default=True)
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), help="Write to file instead of stdout.")
@click.option("--raw", is_flag=True, help="With --format json, emit raw HAC payload.")
@click.pass_context
def query(
    ctx: click.Context,
    query: str | None,
    file: Path | None,
    max_count: int,
    locale: str,
    run_as: str,
    commit: bool,
    override: bool,
    fmt: str,
    output: Path | None,
    raw: bool,
) -> None:
    """Execute a single FlexibleSearch query."""
    sql = _read_query(query, file)

    if not is_read_only(sql):
        verbs = find_write_verbs(sql)
        if not (commit and override):
            console.print(
                f"[red]Refused:[/red] query contains write verb(s) {verbs}. "
                f"To proceed, pass [bold]--commit --i-know-what-im-doing[/bold]."
            )
            sys.exit(2)
        cfg, profile = _load_profile(ctx)
        if profile.name in {"prd", "prod", "production"}:
            console.print(f"[bold red]About to run write query on '{profile.name}' ({profile.base_url}).[/bold red]")
            if not click.confirm("Proceed?", default=False):
                sys.exit(2)
    else:
        cfg, profile = _load_profile(ctx)

    client = HacClient(profile)
    try:
        result = client.execute(
            sql, max_count=max_count, locale=locale, run_as=run_as, commit=commit
        )
    except HacError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    out_stream = open(output, "w", encoding="utf-8") if output else sys.stdout
    try:
        if fmt == "table":
            render_table(result, stream=out_stream)
        elif fmt == "json":
            render_json(result, stream=out_stream, raw=raw)
        else:
            render_csv(result, stream=out_stream)
    finally:
        if output:
            out_stream.close()


@main.command()
@click.option("-m", "--max-count", type=int, default=200, show_default=True)
@click.option("-l", "--locale", default="en", show_default=True)
@click.option("-r", "--run-as", default="admin", show_default=True)
@click.option("-F", "--format", "fmt", type=click.Choice(["table", "json", "csv"]), default="table", show_default=True)
@click.pass_context
def repl(ctx: click.Context, max_count: int, locale: str, run_as: str, fmt: str) -> None:
    """Interactive prompt; queries terminated with ';'."""
    from .repl import run_repl  # local import: prompt_toolkit only loads when needed
    cfg, profile = _load_profile(ctx)
    client = HacClient(profile)
    run_repl(client, max_count=max_count, locale=locale, run_as=run_as, fmt=fmt)


@main.group()
def config() -> None:
    """Inspect or initialize CLI config."""


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Print resolved profile."""
    cfg, profile = _load_profile(ctx)
    console.print(f"[bold]Config:[/bold] {cfg.source_path}")
    console.print(f"[bold]Profile:[/bold] {profile.name}")
    console.print(f"  url:         {profile.url}")
    console.print(f"  base_path:   {profile.normalized_base_path}")
    console.print(f"  user:        {profile.user}")
    console.print(f"  password_env:{profile.password_env}")
    console.print(f"  verify_ssl:  {profile.verify_ssl}")
    console.print(f"  cookie:      {profile.cookie_path()}")


@config.command("list")
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """List all profiles."""
    cfg = config_mod.load(ctx.obj.get("config_path"))
    for name, p in cfg.profiles.items():
        marker = "*" if name == cfg.default_profile else " "
        console.print(f"{marker} {name:<10} {p.url}  (user={p.user}, env={p.password_env})")


@config.command("init")
def config_init() -> None:
    """Write a sample config file at ~/.flexsearch/config.yaml."""
    try:
        path = config_mod.write_sample()
    except config_mod.ConfigError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    console.print(f"Wrote sample config at [green]{path}[/green]")


@main.command()
@click.pass_context
def login(ctx: click.Context) -> None:
    """Force login (refresh cookie jar) for the active profile."""
    cfg, profile = _load_profile(ctx)
    client = HacClient(profile)
    client.logout_clear()
    try:
        client.login()
    except HacError as e:
        console.print(f"[red]Login failed:[/red] {e}")
        sys.exit(1)
    console.print(f"[green]Logged in to {profile.base_url} as {profile.user}.[/green]")


if __name__ == "__main__":
    main()
