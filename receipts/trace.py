"""Live terminal trace so judges can watch every decision and call."""

import os

from rich.console import Console

# Under MCP (stdio), stdout carries the protocol, so the human-readable trace goes to stderr.
console = Console(highlight=False, stderr=bool(os.environ.get("RECEIPTS_MCP")))


def step(title: str) -> None:
    console.print(f"\n[bold cyan]▶ {title}[/]")


def info(msg: str) -> None:
    console.print(f"  {msg}")


def call(seq: int, endpoint: str, detail: str) -> None:
    console.print(f"  [dim]receipt #{seq:>3}[/] [magenta]{endpoint}[/] {detail}")


def warn(msg: str) -> None:
    console.print(f"  [yellow]⚠ {msg}[/]")


def ok(msg: str) -> None:
    console.print(f"  [green]✔ {msg}[/]")


def bad(msg: str) -> None:
    console.print(f"  [red]✘ {msg}[/]")
