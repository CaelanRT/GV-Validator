# GV Validator (VRA MVP)

CLI scaffold for the Validation Reconciliation Agent described in `spec.md`.

## What works now

- `run-reconciliation` Typer command.
- Discovers 4.1-6 protocol radio groups from the protocol PDF.
- Parses report Difference IDs and repeat grouping.
- Builds a strict reconciliation grid for repeats 1-4 and IDs 1-19 (76 rows).
- Generates per-row evidence crops (protocol/report master + sample) under `output/evidence/`.
- Calls Gemini (`gemini-1.5-flash`) for visual comparison when `GEMINI_API_KEY` is set.
- Produces:
  - `output/protocol_reconciled.pdf`
  - `output/reconciliation_log.csv`
  - `output/exceptions.csv`

## Current MVP limits

- If `GEMINI_API_KEY` is not set, visual-comparison rows remain `UNSET` for manual review.
- Protocol PDF currently exposes only a subset of 4.1-6 radio rows; rows without a mapped widget are logged and left unset in the PDF.
- Radio automation only applies where a protocol widget mapping exists.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install .
```

## Team setup (.env)

```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY
```

Recommended baseline values:

```env
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.0-flash
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

By default, CLI loads `.env`. You can override the path with:

```bash
.venv/bin/vra run-reconciliation ... --env-file "/absolute/path/to/.env"
```

## API call reduction notes

- The client now uses a single configured model (`GEMINI_MODEL`) per request (no per-row model fallback loop).
- VLM responses are cached in `.cache/vlm_cache.json` by image hash, so reruns with the same evidence crops avoid repeat API calls.
- If needed, increase spacing between requests using `GEMINI_MIN_SECONDS_BETWEEN_CALLS` in `.env`.

