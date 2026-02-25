# Feasibility Assessment: Test 4.1-6 Validation Reconciliation

## Summary: **Yes, this is feasible.**

The PDF structure supports the spec. Below are findings from inspecting both documents and recommended spec updates.

---

## Protocol PDF (GRA-BAR-BRL-PQ_Merged.pdf)

| Finding | Details |
|--------|---------|
| **Table location** | "4.1-6 GRA-BAR-BRL-PQ Difference TABLE III" on page 42 |
| **Table span** | Pages 42–45 (4 pages) |
| **Widget naming** | `PassFail18diff{N}4.1-6 GRA-BAR-BRL-PQ` where N encodes row (e.g. diff64, diff94, diff124) |
| **Radio groups** | 3 radios per row: PASS, FAIL, N/A (export values: `"PASS"`, `"FAIL"`, `"N#2FA"`) |
| **Widget count** | ~12 radios per page × 4 pages = 48 radios for 16 rows; full table is 19 IDs × 4 repeats = 76 rows, so table may extend to page 46 |

**Widget mapping:** Each group of 3 radios shares a field name. To set PASS, use `widget.field_value = "PASS"` (not `"On"`). PyMuPDF supports this via `widget.update()`.

---

## Report PDF (PQ6_GRA_report.pdf)

| Finding | Details |
|--------|---------|
| **Structure** | 21 pages; Repeat 1 has 19 differences, Repeat 2 has 19, Repeats 3–4 have 0 |
| **Layout** | Each page has 3 difference blocks (e.g. page 3: IDs 1, 2, 3) with "Difference ID: X", "Master", "Sample", "Difference" |
| **Images** | ~10 images per difference page; Master/Sample crops are present |
| **Text anchors** | "Difference ID: 1" at y≈169, "Difference ID: 2" at y≈364, etc. — usable for layout-based extraction |

**Extraction approach:** Use text search for "Difference ID: X" to get y-coordinates, then derive Master/Sample image rects from the layout (or image placement data).

---

## Technical Gaps Addressed

1. **Widget naming** — Pattern identified; mapping from (repeat, difference_id) to field name can be built from widget order and rects.
2. **PASS value** — Use `"PASS"` as the export value, not `"On"`.
3. **Bounding boxes** — Protocol table cells can be inferred from text block positions; report crops from text anchors + image placement.
4. **Repeat/ID mapping** — Report groups by Repeat ID; protocol uses a linear row index (repeat × 19 + id).

---

## Recommended Spec Changes

See `spec.md` updates below.
