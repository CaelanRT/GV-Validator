from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from .models import Decision, ReconciliationRow
from .pdf_protocol import apply_pass_fail_value, extract_protocol_rows, render_protocol_crop
from .pdf_report import build_report_lookup, extract_report_blocks, render_report_crop
from .vlm import VLMClient

EXPECTED_REPEATS = range(1, 5)
EXPECTED_DIFFERENCE_IDS = range(1, 20)


def run_reconciliation(
    protocol_pdf: Path,
    report_pdf: Path,
    test_id: str,
    threshold: float,
    output_dir: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[Path, Path, Path, List[ReconciliationRow]]:
    protocol_rows = extract_protocol_rows(protocol_pdf, test_id=test_id)
    report_blocks = extract_report_blocks(report_pdf)
    report_lookup = build_report_lookup(report_blocks)
    repeat_counts: Dict[int, int] = {}
    for block in report_blocks:
        repeat_counts[block.repeat_id] = repeat_counts.get(block.repeat_id, 0) + 1

    vlm = VLMClient()
    rows: List[ReconciliationRow] = []
    protocol_lookup = {(r.repeat_id, r.difference_id): r for r in protocol_rows}
    expected_keys: Set[Tuple[int, int]] = {
        (repeat_id, difference_id)
        for repeat_id in EXPECTED_REPEATS
        for difference_id in EXPECTED_DIFFERENCE_IDS
    }

    for repeat_id in EXPECTED_REPEATS:
        for difference_id in EXPECTED_DIFFERENCE_IDS:
            key = (repeat_id, difference_id)
            protocol_row = protocol_lookup.get(key)
            report_block = report_lookup.get(key)

            if report_block is None:
                if repeat_counts.get(repeat_id, 0) == 0:
                    rows.append(
                        ReconciliationRow(
                            repeat_id=repeat_id,
                            difference_id=difference_id,
                            decision=Decision.PASS,
                            match=True,
                            confidence=1.0,
                            reason=(
                                "Auto-pass: report shows zero differences for this repeat."
                            ),
                            evidence=["repeat_zero_differences"],
                            protocol_page_index=(
                                protocol_row.page_index if protocol_row else None
                            ),
                            protocol_widget_name=(
                                protocol_row.radio_group_name if protocol_row else None
                            ),
                            report_page_index=None,
                        )
                    )
                    if progress_callback:
                        progress_callback(
                            len(rows),
                            len(expected_keys),
                            (
                                f"repeat {repeat_id} diff {difference_id}: "
                                "auto-pass (repeat has zero differences)"
                            ),
                        )
                else:
                    evidence = ["missing_difference_id"]
                    if protocol_row is None:
                        evidence.append("missing_protocol_widget")
                    rows.append(
                        ReconciliationRow(
                            repeat_id=repeat_id,
                            difference_id=difference_id,
                            decision=Decision.FAIL,
                            match=False,
                            confidence=1.0,
                            reason="Missing difference in report for active repeat.",
                            evidence=evidence,
                            protocol_page_index=(
                                protocol_row.page_index if protocol_row else None
                            ),
                            protocol_widget_name=(
                                protocol_row.radio_group_name if protocol_row else None
                            ),
                            report_page_index=None,
                        )
                    )
                    if progress_callback:
                        progress_callback(
                            len(rows),
                            len(expected_keys),
                            (
                                f"repeat {repeat_id} diff {difference_id}: "
                                "missing report difference"
                            ),
                        )
                continue

            evidence_dir = output_dir / "evidence" / f"r{repeat_id}_d{difference_id}"
            pq_master = (
                render_protocol_crop(
                    protocol_pdf=protocol_pdf,
                    page_index=protocol_row.page_index,
                    bbox=protocol_row.master_bbox,
                    out_path=evidence_dir / "pq_master.png",
                )
                if protocol_row and protocol_row.master_bbox
                else None
            )
            pq_sample = (
                render_protocol_crop(
                    protocol_pdf=protocol_pdf,
                    page_index=protocol_row.page_index,
                    bbox=protocol_row.sample_bbox,
                    out_path=evidence_dir / "pq_sample.png",
                )
                if protocol_row and protocol_row.sample_bbox
                else None
            )
            report_master = (
                render_report_crop(
                    report_pdf=report_pdf,
                    page_index=report_block.page_index,
                    bbox=report_block.master_bbox,
                    out_path=evidence_dir / "report_master.png",
                )
                if report_block.master_bbox
                else None
            )
            report_sample = (
                render_report_crop(
                    report_pdf=report_pdf,
                    page_index=report_block.page_index,
                    bbox=report_block.sample_bbox,
                    out_path=evidence_dir / "report_sample.png",
                )
                if report_block.sample_bbox
                else None
            )

            comparison = vlm.compare(
                pq_master=pq_master,
                pq_sample=pq_sample,
                report_master=report_master,
                report_sample=report_sample,
            )
            effective_confidence = (
                comparison.confidence if comparison.confidence is not None else 1.0
            )
            if protocol_row is None:
                decision = Decision.UNSET
                reason = (
                    "Protocol row mapping missing for this repeat/difference; "
                    "manual review required."
                )
            elif comparison.match and effective_confidence >= threshold:
                decision = Decision.PASS
                reason = comparison.reason
            elif effective_confidence >= threshold:
                decision = Decision.FAIL
                reason = comparison.reason
            else:
                decision = Decision.UNSET
                reason = comparison.reason

            evidence = ["vlm_compare"]
            evidence.extend(
                str(path)
                for path in (pq_master, pq_sample, report_master, report_sample)
                if path
            )
            if protocol_row is None:
                evidence.append("missing_protocol_widget")
            rows.append(
                ReconciliationRow(
                    repeat_id=repeat_id,
                    difference_id=difference_id,
                    decision=decision,
                    match=comparison.match,
                    confidence=comparison.confidence,
                    reason=reason,
                    evidence=evidence,
                    protocol_page_index=(
                        protocol_row.page_index if protocol_row else None
                    ),
                    protocol_widget_name=(
                        protocol_row.radio_group_name if protocol_row else None
                    ),
                    report_page_index=report_block.page_index,
                )
            )
            if progress_callback:
                progress_callback(
                    len(rows),
                    len(expected_keys),
                    (
                        f"repeat {repeat_id} diff {difference_id}: "
                        f"{rows[-1].decision.value}"
                    ),
                )

    for repeat_id, difference_id in sorted(report_lookup.keys()):
        if (repeat_id, difference_id) in expected_keys:
            continue
        report_block = report_lookup[(repeat_id, difference_id)]
        rows.append(
            ReconciliationRow(
                repeat_id=repeat_id,
                difference_id=difference_id,
                decision=Decision.UNSET,
                match=False,
                confidence=1.0,
                reason="Informational: extra difference ID found in report.",
                evidence=["extra_difference_id"],
                protocol_page_index=None,
                protocol_widget_name=None,
                report_page_index=report_block.page_index,
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = output_dir / "protocol_reconciled.pdf"
    out_csv = output_dir / "reconciliation_log.csv"
    out_exceptions = output_dir / "exceptions.csv"

    decisions: Dict[Tuple[int, int], str] = {}
    for row in rows:
        if row.decision in (Decision.PASS, Decision.FAIL):
            decisions[(row.repeat_id, row.difference_id)] = row.decision.value
    apply_pass_fail_value(
        protocol_pdf_in=protocol_pdf,
        protocol_pdf_out=out_pdf,
        decisions=decisions,
        test_id=test_id,
    )

    with out_csv.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "repeat_id",
                "difference_id",
                "status",
                "match",
                "confidence",
                "reason",
                "evidence",
                "protocol_page",
                "protocol_widget",
                "report_page",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.repeat_id,
                    row.difference_id,
                    row.decision.value,
                    row.match,
                    row.confidence,
                    row.reason,
                    ";".join(row.evidence),
                    row.protocol_page_index,
                    row.protocol_widget_name,
                    row.report_page_index,
                ]
            )

    with out_exceptions.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["repeat_id", "difference_id", "status", "reason"])
        for row in rows:
            if row.decision != Decision.PASS:
                writer.writerow(
                    [row.repeat_id, row.difference_id, row.decision.value, row.reason]
                )

    return out_pdf, out_csv, out_exceptions, rows

