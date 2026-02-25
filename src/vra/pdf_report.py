from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz

from .models import ReportBlock

RE_REPEAT = re.compile(r"Repeat ID\s+(\d+)")
RE_DIFF = re.compile(r"Difference ID:\s*(\d+)")


def _first_rect_for_text(page: fitz.Page, needle: str) -> Tuple[float, float, float, float]:
    rects = page.search_for(needle)
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    r = rects[0]
    return (r.x0, r.y0, r.x1, r.y1)


def extract_report_blocks(report_pdf: Path) -> List[ReportBlock]:
    doc = fitz.open(report_pdf)
    try:
        blocks: List[ReportBlock] = []
        current_repeat: Optional[int] = None

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text()

            repeat_match = RE_REPEAT.search(text)
            if repeat_match:
                current_repeat = int(repeat_match.group(1))

            page_diffs: List[Tuple[int, Tuple[float, float, float, float]]] = []
            for diff_match in RE_DIFF.finditer(text):
                difference_id = int(diff_match.group(1))
                label = f"Difference ID: {difference_id}"
                bbox = _first_rect_for_text(page, label)
                page_diffs.append((difference_id, bbox))

            page_diffs.sort(key=lambda item: item[1][1])
            for i, (difference_id, bbox) in enumerate(page_diffs):
                top = max(0.0, bbox[1] + 22.0)
                next_top = (
                    page_diffs[i + 1][1][1]
                    if (i + 1) < len(page_diffs)
                    else page.rect.height - 5.0
                )
                bottom = max(top + 10.0, next_top - 8.0)
                mid_x = page.rect.width / 2.0
                left_margin = 8.0
                right_margin = page.rect.width - 8.0
                master_bbox = (left_margin, top, mid_x - 6.0, bottom)
                sample_bbox = (mid_x + 6.0, top, right_margin, bottom)

                blocks.append(
                    ReportBlock(
                        repeat_id=current_repeat or 1,
                        difference_id=difference_id,
                        page_index=page_idx,
                        block_bbox=bbox,
                        master_bbox=master_bbox,
                        sample_bbox=sample_bbox,
                    )
                )

        return blocks
    finally:
        doc.close()


def build_report_lookup(blocks: List[ReportBlock]) -> Dict[Tuple[int, int], ReportBlock]:
    return {(b.repeat_id, b.difference_id): b for b in blocks}


def render_report_crop(
    report_pdf: Path,
    page_index: int,
    bbox: Tuple[float, float, float, float],
    out_path: Path,
    zoom: float = 2.0,
) -> Path:
    doc = fitz.open(report_pdf)
    try:
        page = doc[page_index]
        rect = fitz.Rect(*bbox)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(out_path)
        return out_path
    finally:
        doc.close()

