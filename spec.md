# Technical Specification: Validation Reconciliation Agent (VRA)

## 1. Project Objective
To develop a CLI tool that automates the verification of desktop application validation reports against formal PQ protocols. The tool uses a Vision-Language Model (VLM) to compare image crops and programmatically toggles interactive PDF radio buttons to mark tests as **"PASS"** or **"FAIL"** based on AI findings.

## 2. Target Test Case: 4.1-6 (Nested Repeats)
* **Primary Implementation Target:** Test 4.1-6.
* **Reference Document:** `GRA-BAR-BRL-PQ_Merged.pdf` (Difference TABLE III starting on page 42).
* **Actuals Document:** `PQ6_GRA_report.pdf` (Graphics Inspection Report).

## 3. Technical Stack
* **Language:** Python 3.11+
* **CLI Framework:** Typer
* **PDF Engine:** PyMuPDF (fitz) for extraction; PyMuPDF or pdfrw for widget manipulation.
* **Vision Brain:** Gemini 1.5 Flash (via API).
* **Structured Data:** Pydantic for model outputs.

## 4. Functional Requirements

### 4.1. PDF Data Extraction
**The Reference (PQ Document):**
* Locate string: `"4.1-6 GRA-BAR-BRL-PQ Difference TABLE III"` (page 42).
* Table spans pages 42–45 (or 46); iterate IDs 1 to 19 across 4 repeats.
* Extract bounding boxes for **"Master"** and **"Sample"** cells.
* Map (repeat, difference_id) to PDF Widget Names. Widget pattern: `PassFail18diff{N}4.1-6 GRA-BAR-BRL-PQ` where N encodes row. Each row has 3 radios: PASS, FAIL, N/A (export values: `"PASS"`, `"FAIL"`, `"N#2FA"`).

**The Actual (GVD Report):**
* Group findings by **Repeat ID** (1 through 4). Repeats 3–4 may have 0 differences.
* Use text anchors `"Difference ID: X"` to locate blocks; Master/Sample images lie within each block.
* Extract "Master" and "Sample" crops for each Difference ID (e.g., ID 12).

### 4.2. Agentic Reconciliation Logic
1.  **Retrieve Requirements:** Fetch expected visual state from the PQ Table.
2.  **Visual Comparison:** Send 4 images (PQ Master/Sample + Report Master/Sample) to VLM.
3.  **Prompt Instruction:** Match visual differences. Respond in JSON: `{ "match": true/false, "reason": "string", "confidence": 0.0–1.0 }` (confidence optional, for threshold decisions).
4.  **Multi-Repeat Handling:** Verify IDs across all four repeats for Test 4.1-6.

### 4.3. Programmatic Form Interaction
* **Action:** If `match: true` (and above threshold), set the **PASS** radio button widget value to `"PASS"` (the AcroForm export value, not `"On"`).
* **Implementation:** Modify the widget's `/V` value via PyMuPDF (do not just draw an "X").
* **Manual Trigger:** If confidence is low, leave unselected for human review.

## 5. CLI Commands & Workflow
**Command:** `run-reconciliation`

**Inputs:**
* `--protocol`: Path to PQ protocol.
* `--report`: Path to GVD report.
* `--test-id`: Identifier (e.g., "4.1-6").
* `--threshold`: Confidence (default 0.90).

## 6. Output & Reporting
* **Modified PDF:** Copy of Protocol with validated radio buttons selected.
* **Reconciliation Log:** CSV/Table summary (ID, Status, Confidence, Evidence).
* **Exception Report:** List of False Positives or failed matches.

## 7. Edge Case Handling
* **Missing IDs:** Mark as **FAIL**.
* **Extra IDs:** Mark as **Informational** (False Positive).
* **Repeats with 0 differences:** If the report shows 0 differences for a repeat (e.g., Repeats 3–4), all 19 IDs for that repeat should be marked **PASS** (no false positives detected).
* **Layout Shifts:** Use text-anchor searching instead of hard-coded coordinates.

---

## Appendix A: Test 4.1-6 Discovered Structure (Reference)

| Item | Value |
|------|-------|
| Table header | `4.1-6 GRA-BAR-BRL-PQ Difference TABLE III` |
| Table pages | 42–45 |
| Widget field pattern | `PassFail18diff{N}4.1-6 GRA-BAR-BRL-PQ` |
| PASS export value | `"PASS"` |
| FAIL export value | `"FAIL"` |
| N/A export value | `"N#2FA"` |