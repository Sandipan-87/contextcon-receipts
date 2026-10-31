"""Live terminal trace so judges can watch every decision and call."""

from rich.console import Console

console = Console(highlight=False)


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
