# PDF Scan-Page Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce BR-07 by rejecting any PDF page where one visible raster-image placement covers at least 80% of the page crop box and fewer than 30 useful text characters are present.

**Architecture:** Extend the existing bounded PDF validator with a dependency-free content-stream geometry walker. The walker tracks transformation, graphics, and supported convex clipping state; recursively enters Form XObjects with decoded-byte, repeated-work, cycle, depth, and operation limits; and returns the maximum visible image coverage for each page. Unsupported compound, curved, non-convex, or even-odd clipping is accepted while drawing but fails closed as `PDF_MALFORMED` when applied, preventing unknown geometry from becoming zero coverage.

**Tech Stack:** Python 3.13, pypdf 6.x, pytest, Ruff, Black.

---

### Task 1: Add generated-PDF scan regression tests

**Files:**
- Create: `backend/tests/test_t009_pdf_scan_detection.py`
- Reference: `backend/tests/test_t009_pdf_decoded_limit.py`

- [x] **Step 1: Create deterministic PDF builders**

Build pages with `PdfWriter`, a Type1 Helvetica resource, a 1x1 grayscale image XObject, and explicit content operators. The core builder must produce content equivalent to:

```python
content = (
    f"q {width} 0 0 {height} {x} {y} cm /Im0 Do Q\n"
    "BT /F1 10 Tf 5 95 Td "
    f"({text}) Tj ET"
).encode("ascii")
```

Use a `DecodedStreamObject` for `/Contents`, and register `/Im0` under `/Resources /XObject` with `/Subtype /Image`, `/Width 1`, `/Height 1`, `/ColorSpace /DeviceGray`, and `/BitsPerComponent 8`.

- [x] **Step 2: Add observable threshold tests**

Add tests asserting:

```python
with pytest.raises(PDFValidationError) as exc_info:
    validate_pdf(scan_pdf)
assert exc_info.value.code == "PDF_SCAN_ONLY"

assert validate_pdf(large_image_with_30_chars).has_text is True
assert validate_pdf(image_below_80_percent).has_text is True
assert validate_pdf(text_page_plus_blank_page).page_count == 2
```

Also construct a Form XObject containing `/Im0 Do`, apply the Form `/Matrix`, and assert a transformed image covering at least 80% is rejected.

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
cd backend
uv run pytest tests/test_t009_pdf_scan_detection.py -q
```

Expected: the large-image/short-text and Form-image rejection tests fail because `validate_pdf()` currently accepts any page containing non-whitespace text.

### Task 2: Implement recursive image-placement geometry

**Files:**
- Modify: `backend/app/services/pdf_validation.py`
- Test: `backend/tests/test_t009_pdf_scan_detection.py`

- [x] **Step 1: Add matrix and polygon primitives**

Use six-element PDF matrices and implement the same multiplication order as pypdf:

```python
def _multiply_matrix(m: Matrix, n: Matrix) -> Matrix:
    return (
        m[0] * n[0] + m[1] * n[2],
        m[0] * n[1] + m[1] * n[3],
        m[2] * n[0] + m[3] * n[2],
        m[2] * n[1] + m[3] * n[3],
        m[4] * n[0] + m[5] * n[2] + n[4],
        m[4] * n[1] + m[5] * n[3] + n[5],
    )
```

Transform the unit square, clip convex polygons with Sutherland-Hodgman edge clipping, and calculate area using the shoelace formula. Page coverage is clipped-image area divided by crop-box area.

- [x] **Step 2: Walk content operations**

Create a bounded recursive walker that:

```python
if operator == b"q":
    stack.append(current_ctm)
elif operator == b"Q":
    current_ctm = stack.pop() if stack else IDENTITY_MATRIX
elif operator == b"cm" and len(operands) >= 6:
    current_ctm = _multiply_matrix(tuple(map(float, operands[:6])), current_ctm)
elif operator == b"INLINE IMAGE":
    maximum_coverage = max(maximum_coverage, image_coverage(current_ctm))
elif operator == b"Do":
    # Resolve the named XObject from current resources.
    # For /Image, measure the transformed unit square.
    # For /Form, compose /Matrix, intersect /BBox, inherit resources,
    # and recurse with path-based cycle detection.
```

Limit Form recursion depth and total content operations. Raise a malformed-PDF exception when limits are exceeded; never silently accept an unbounded traversal.

- [x] **Step 3: Enforce BR-07 in `validate_pdf()`**

For every page, reuse the already decoded/cached content streams, extract text once, and calculate:

```python
useful_character_count = sum(not character.isspace() for character in text)
image_coverage = _maximum_raster_coverage(page)
if image_coverage >= 0.80 and useful_character_count < 30:
    raise PDFValidationError("PDF_SCAN_ONLY")
```

A page with zero useful characters and zero visible raster area remains a true blank page and does not independently trigger the page-level rule. Preserve the existing final `if not text_found: PDF_SCAN_ONLY` behavior for wholly textless files.

- [x] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
cd backend
uv run pytest tests/test_t009_pdf_scan_detection.py tests/test_t009_pdf_decoded_limit.py tests/test_t009_pdf_behavior.py -q
```

Expected: all focused PDF tests pass.

### Task 3: Verify, document, and publish

**Files:**
- Modify: `docs/superpowers/plans/2026-08-28-pdf-upload-storage-job-lifecycle.md`
- Commit all scan-page files.

- [x] **Step 1: Reconcile canonical implementation notes**

Record that BR-07 now uses recursive PDF placement geometry; crop, Form, and supported content clipping; fail-closed rejection of unsupported applied clipping; the inclusive 80% image threshold; the exclusive 30-character text threshold; and cumulative Form decoded/work bounds. Update the final pytest count after verification.

- [x] **Step 2: Run complete verification**

Run from `backend/`:

```bash
uv run ruff check .
uv run black --check .
RUN_DATABASE_TESTS=1 uv run pytest -v
```

Result: Ruff and Black checks passed; the database-enabled full suite passed with 196 tests.

- [ ] **Step 3: Commit and push**

Create an atomic conventional commit for implementation/tests/docs, push the existing PR #8 branch without force, and verify remote HEAD equals local HEAD.

- [ ] **Step 4: Request CodeRabbit**

Comment on PR #8:

```text
@coderabbitai full review

Please review exact final PR HEAD `<final-sha>`.
```

Wait for the completed review, report its full result verbatim, and stop for the user's decision whether any new finding should be fixed.
