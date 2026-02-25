from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import fitz

from .models import ProtocolRow


TABLE_HEADER = "4.1-6 GRA-BAR-BRL-PQ Difference TABLE III"
WIDGET_PATTERN = "PassFail18diff"
FIELD_NUMBER_RE = re.compile(r"PassFail18diff(\d+)")


def _extract_export_value(widget: fitz.Widget) -> str:
    states = widget.button_states().get("normal", [])
    for state in states:
        if state != "Off":
            return state
    return "Off"


def _safe_first_rect(page: fitz.Page, label: str) -> Optional[fitz.Rect]:
    rects = page.search_for(label)
    if not rects:
        return None
    return rects[0]


def _column_bounds(page: fitz.Page) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    master_rect = _safe_first_rect(page, "MASTER")
    sample_rect = _safe_first_rect(page, "SAMPLE")
    pass_fail_rect = _safe_first_rect(page, "PASS/FAIL")

    page_width = page.rect.width
    if not (master_rect and sample_rect and pass_fail_rect):
        # Fallback tuned to current 4.1-6 table geometry.
        return (90.0, 290.0), (290.0, 490.0)

    master_left = max(0.0, master_rect.x0 - 65.0)
    master_right = (master_rect.x1 + sample_rect.x0) / 2.0
    sample_left = master_right
    sample_right = min(page_width, (sample_rect.x1 + pass_fail_rect.x0) / 2.0)
    return (master_left, master_right), (sample_left, sample_right)


def _field_sort_number(field_name: str) -> int:
    match = FIELD_NUMBER_RE.search(field_name)
    if not match:
        return 10**9
    return int(match.group(1))


def extract_protocol_rows(protocol_pdf: Path, test_id: str) -> List[ProtocolRow]:
    if test_id != "4.1-6":
        raise ValueError(f"Unsupported test-id '{test_id}'. MVP supports only 4.1-6.")

    doc = fitz.open(protocol_pdf)
    try:
        header_pages: List[int] = []
        for page_idx in range(len(doc)):
            if TABLE_HEADER in doc[page_idx].get_text():
                header_pages.append(page_idx)
        if not header_pages:
            raise RuntimeError(f"Could not find table header '{TABLE_HEADER}' in protocol PDF.")

        candidate_pages = list(range(header_pages[0], len(doc)))
        rows: List[ProtocolRow] = []
        row_counter = 0

        for page_idx in candidate_pages:
            page = doc[page_idx]
            page_widgets = list(page.widgets())
            if not page_widgets:
                continue

            grouped: Dict[str, List[Tuple[int, fitz.Widget]]] = OrderedDict()
            for i, widget in enumerate(page_widgets):
                field_name = getattr(widget, "field_name", "") or ""
                if WIDGET_PATTERN not in field_name or test_id not in field_name:
                    continue
                grouped.setdefault(field_name, []).append((i, widget))

            parsed_rows: List[
                Tuple[float, int, str, Dict[str, int], Tuple[float, float], Tuple[float, float]]
            ] = []
            for field_name, widget_entries in grouped.items():
                master_col, sample_col = _column_bounds(page)
                widget_indices: Dict[str, int] = {}
                ys: List[float] = []
                for index, widget in widget_entries:
                    export_value = _extract_export_value(widget)
                    if export_value != "Off":
                        widget_indices[export_value] = index
                    ys.append(widget.rect.y0)
                    ys.append(widget.rect.y1)
                row_top = max(0.0, min(ys) - 2.0) if ys else 0.0
                parsed_rows.append(
                    (
                        row_top,
                        _field_sort_number(field_name),
                        field_name,
                        widget_indices,
                        (master_col[0], master_col[1]),
                        (sample_col[0], sample_col[1]),
                    )
                )

            parsed_rows.sort(key=lambda item: (item[0], item[1]))
            for (
                row_top,
                _field_num,
                field_name,
                widget_indices,
                master_col,
                sample_col,
            ) in parsed_rows:
                row_counter += 1
                repeat_id = ((row_counter - 1) // 19) + 1
                difference_id = ((row_counter - 1) % 19) + 1
                row_widgets = grouped[field_name]
                ys = [
                    value
                    for _, widget in row_widgets
                    for value in (widget.rect.y0, widget.rect.y1)
                ]
                row_bottom = min(page.rect.height, max(ys) + 2.0) if ys else row_top
                rows.append(
                    ProtocolRow(
                        repeat_id=repeat_id,
                        difference_id=difference_id,
                        page_index=page_idx,
                        radio_group_name=field_name,
                        widget_indices=widget_indices,
                        master_bbox=(
                            master_col[0],
                            row_top,
                            master_col[1],
                            row_bottom,
                        ),
                        sample_bbox=(
                            sample_col[0],
                            row_top,
                            sample_col[1],
                            row_bottom,
                        ),
                    )
                )

        if not rows:
            raise RuntimeError("No matching 4.1-6 radio groups were discovered in protocol PDF.")
        return rows
    finally:
        doc.close()


def render_protocol_crop(
    protocol_pdf: Path,
    page_index: int,
    bbox: Tuple[float, float, float, float],
    out_path: Path,
    zoom: float = 2.0,
) -> Path:
    doc = fitz.open(protocol_pdf)
    try:
        page = doc[page_index]
        rect = fitz.Rect(*bbox)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(out_path)
        return out_path
    finally:
        doc.close()


def apply_pass_fail_value(
    protocol_pdf_in: Path,
    protocol_pdf_out: Path,
    decisions: Dict[Tuple[int, int], str],
    test_id: str,
) -> None:
    if test_id != "4.1-6":
        raise ValueError(f"Unsupported test-id '{test_id}'. MVP supports only 4.1-6.")

    doc = fitz.open(protocol_pdf_in)
    try:
        rows = extract_protocol_rows(protocol_pdf_in, test_id=test_id)
        row_lookup = {(r.repeat_id, r.difference_id): r for r in rows}

        for (repeat_id, difference_id), export_value in decisions.items():
            row = row_lookup.get((repeat_id, difference_id))
            if row is None:
                continue

            page = doc[row.page_index]
            for widget in page.widgets():
                if (getattr(widget, "field_name", "") or "") != row.radio_group_name:
                    continue
                normal_states = widget.button_states().get("normal", [])
                if export_value in normal_states:
                    widget.field_value = export_value
                    widget.update()

        protocol_pdf_out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(protocol_pdf_out)
    finally:
        doc.close()

