from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from .client import FlexResult, HacClient, HacError
from .output import render_csv, render_json, render_table
from .safety import find_write_verbs, is_read_only

HISTORY_PATH = Path.home() / ".flexsearch_history"


def _is_terminator(line: str) -> bool:
    s = line.rstrip()
    return s.endswith(";") or s in ("\\q", "exit", "quit")


def run_repl(
    client: HacClient,
    *,
    max_count: int,
    locale: str,
    run_as: str,
    fmt: str = "table",
) -> None:
    console = Console()
    profile = client.profile
    console.print(
        f"[bold green]flexsearch[/bold green] connected to "
        f"[cyan]{profile.base_url}[/cyan] as [yellow]{profile.user}[/yellow] "
        f"(profile: [magenta]{profile.name}[/magenta])"
    )
    console.print("[dim]End queries with ';'. Type \\q, exit, or Ctrl-D to quit.[/dim]")
    session: PromptSession[str] = PromptSession(history=FileHistory(str(HISTORY_PATH)))

    buffer: list[str] = []
    while True:
        try:
            prompt = "fxs> " if not buffer else "...> "
            line = session.prompt(prompt)
        except KeyboardInterrupt:
            buffer.clear()
            continue
        except EOFError:
            console.print("[dim]bye[/dim]")
            return

        stripped = line.strip()
        if not buffer and stripped in ("\\q", "exit", "quit"):
            return
        if not buffer and stripped.startswith("\\"):
            _handle_meta(stripped, console)
            continue

        buffer.append(line)
        if not _is_terminator(line):
            continue

        query = "\n".join(buffer).rstrip().rstrip(";").strip()
        buffer.clear()
        if not query:
            continue

        if not is_read_only(query):
            verbs = find_write_verbs(query)
            console.print(
                f"[red]Refused: query contains write verb(s) {verbs}. "
                f"REPL is read-only.[/red]"
            )
            continue

        try:
            result: FlexResult = client.execute(
                query, max_count=max_count, locale=locale, run_as=run_as, commit=False
            )
        except HacError as e:
            console.print(f"[red]Error:[/red] {e}")
            continue

        if fmt == "json":
            render_json(result)
        elif fmt == "csv":
            render_csv(result)
        else:
            render_table(result)


def _handle_meta(cmd: str, console: Console) -> None:
    console.print(f"[yellow]Unknown meta command: {cmd}[/yellow]")
