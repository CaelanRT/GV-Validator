from __future__ import annotations

import typer

from .cli import run_reconciliation_command


def main() -> None:
    typer.run(run_reconciliation_command)

