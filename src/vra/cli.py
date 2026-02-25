from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv

from .models import Decision
from .reconciliation import run_reconciliation

app = typer.Typer(help="Validation Reconciliation Agent (VRA) CLI.")


@app.callback()
def main() -> None:
    """Root command group for VRA."""
    return


@app.command("run-reconciliation")
def run_reconciliation_command(
    protocol: Path = typer.Option(..., "--protocol", help="Path to PQ protocol PDF."),
    report: Path = typer.Option(..., "--report", help="Path to GVD report PDF."),
    test_id: str = typer.Option("4.1-6", "--test-id", help="Test identifier."),
    threshold: float = typer.Option(
        0.90, "--threshold", min=0.0, max=1.0, help="Confidence threshold."
    ),
    output_dir: Path = typer.Option(
        Path("output"),
        "--output-dir",
        help="Directory for reconciled files and logs.",
    ),
    env_file: Path = typer.Option(
        Path(".env"),
        "--env-file",
        help="Path to dotenv file containing GEMINI_API_KEY.",
    ),
) -> None:
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)

    if not protocol.exists():
        raise typer.BadParameter(f"Protocol PDF not found: {protocol}")
    if not report.exists():
        raise typer.BadParameter(f"Report PDF not found: {report}")

    out_pdf, out_csv, out_exceptions, rows = run_reconciliation(
        protocol_pdf=protocol,
        report_pdf=report,
        test_id=test_id,
        threshold=threshold,
        output_dir=output_dir,
    )

    total = len(rows)
    pass_count = sum(1 for r in rows if r.decision == Decision.PASS)
    fail_count = sum(1 for r in rows if r.decision == Decision.FAIL)
    unset_count = sum(1 for r in rows if r.decision == Decision.UNSET)

    typer.echo("Reconciliation complete.")
    typer.echo(f"Rows processed: {total}")
    typer.echo(f"PASS: {pass_count} | FAIL: {fail_count} | UNSET: {unset_count}")
    typer.echo(f"Modified protocol: {out_pdf}")
    typer.echo(f"Log CSV: {out_csv}")
    typer.echo(f"Exceptions CSV: {out_exceptions}")


if __name__ == "__main__":
    app()

