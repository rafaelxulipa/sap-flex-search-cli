from __future__ import annotations

import csv
import json
import sys
from typing import TextIO

from rich.console import Console
from rich.table import Table

from .client import FlexResult


def _stringify(v) -> str:
    if v is None:
        return ""
    return str(v)


def render_table(result: FlexResult, stream: TextIO | None = None) -> None:
    console = Console(file=stream or sys.stdout, soft_wrap=False)
    if not result.headers and not result.rows:
        console.print("[dim](no results)[/dim]")
        return
    table = Table(show_lines=False, header_style="bold cyan")
    for h in result.headers or [f"col{i}" for i in range(len(result.rows[0]) if result.rows else 0)]:
        table.add_column(str(h), overflow="fold")
    for row in result.rows:
        table.add_row(*[_stringify(c) for c in row])
    console.print(table)
    if result.execution_time is not None:
        console.print(f"[dim]{len(result.rows)} row(s) in {result.execution_time} ms[/dim]")


def render_json(result: FlexResult, stream: TextIO | None = None, raw: bool = False) -> None:
    out = stream or sys.stdout
    if raw:
        json.dump(result.raw, out, indent=2, default=str)
    else:
        payload = {
            "query": result.query,
            "executionTime": result.execution_time,
            "headers": result.headers,
            "rows": [
                {h: row[i] if i < len(row) else None for i, h in enumerate(result.headers)}
                for row in result.rows
            ]
            if result.headers
            else result.rows,
        }
        json.dump(payload, out, indent=2, default=str)
    out.write("\n")


def render_csv(result: FlexResult, stream: TextIO | None = None) -> None:
    out = stream or sys.stdout
    writer = csv.writer(out)
    if result.headers:
        writer.writerow(result.headers)
    for row in result.rows:
        writer.writerow([_stringify(c) for c in row])
