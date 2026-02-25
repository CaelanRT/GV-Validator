# GV Validator (VRA MVP)

CLI scaffold for the Validation Reconciliation Agent described in `spec.md`.

## What works now

- `run-reconciliation` Typer command.
- Discovers 4.1-6 protocol radio groups from the protocol PDF.
- Parses report Difference IDs and repeat grouping.
- Generates per-row evidence crops (protocol/report master + sample) under `output/evidence/`.
- Produces:
  - `output/protocol_reconciled.pdf`
  - `output/reconciliation_log.csv`
  - `output/exceptions.csv`

## Current MVP limits

- VLM (Gemini) integration is not wired yet.
- Rows requiring AI visual comparison are marked `UNSET` for manual review.
- Radio automation currently only applies rows with deterministic decisions from rule logic.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install .
```

## Run

```bash
.venv/bin/vra run-reconciliation \
  --protocol "/absolute/path/to/GRA-BAR-BRL-PQ_Merged.pdf" \
  --report "/absolute/path/to/PQ6_GRA_report.pdf" \
  --test-id "4.1-6" \
  --threshold 0.90 \
  --output-dir "/absolute/path/to/output"
```

