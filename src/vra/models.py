from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class Decision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "N#2FA"
    UNSET = "UNSET"


class ComparisonResult(BaseModel):
    match: bool
    reason: str
    confidence: Optional[float] = None


class ProtocolRow(BaseModel):
    repeat_id: int
    difference_id: int
    page_index: int
    radio_group_name: str
    widget_indices: Dict[str, int] = Field(
        default_factory=dict,
        description="Radio widget index keyed by export value: PASS/FAIL/N#2FA",
    )
    master_bbox: Optional[Tuple[float, float, float, float]] = None
    sample_bbox: Optional[Tuple[float, float, float, float]] = None


class ReportBlock(BaseModel):
    repeat_id: int
    difference_id: int
    page_index: int
    block_bbox: Tuple[float, float, float, float]
    master_bbox: Optional[Tuple[float, float, float, float]] = None
    sample_bbox: Optional[Tuple[float, float, float, float]] = None


class ReconciliationRow(BaseModel):
    repeat_id: int
    difference_id: int
    decision: Decision
    match: bool
    confidence: Optional[float] = None
    reason: str = ""
    evidence: List[str] = Field(default_factory=list)
    protocol_page_index: Optional[int] = None
    protocol_widget_name: Optional[str] = None
    report_page_index: Optional[int] = None

