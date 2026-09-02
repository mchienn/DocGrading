# PDF Clipping Fail-Closed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent BR-07 bypasses by rejecting PDFs whose applied clipping geometry cannot be measured exactly by the bounded raster-coverage walker.

**Architecture:** Preserve exact page, Form, CTM, and single simple-convex-path clipping. Replace the current unknown-clip-as-zero behavior with fail-closed `_PDFGeometryLimit`, which `validate_pdf()` exposes as `PDF_MALFORMED`. Explicitly closed paths are normalized before validation; self-intersections and clip paths above the bounded vertex cap are rejected.

**Tech Stack:** Python 3.13, pypdf 6.x, pytest, Ruff, Black.

---

### Task 1: Add fail-closed clipping regressions

**Files:**
- Modify: `backend/tests/test_t009_pdf_scan_detection.py`

- [x] **Step 1: Add the compound-rectangle regression**

Create a page whose two non-zero-winding rectangles jointly cover the whole page, followed by a full-page image and one useful text character:

```python
def test_compound_clip_cannot_disable_scan_detection() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 100, 100),
            "pre_image_operations": (
                "0 0 50 100 re 50 0 50 100 re W n"
            ),
            "text": "A",
        }
    )

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(data)

    assert exc_info.value.code == "PDF_MALFORMED"
```

- [x] **Step 2: Change the even-odd regression to the fail-closed contract**

Replace the current assertion that accepts a self-overlapping `W*` path with:

```python
with pytest.raises(PDFValidationError) as exc_info:
    validate_pdf(data)
assert exc_info.value.code == "PDF_MALFORMED"
```

- [x] **Step 3: Add curved and non-convex clip regressions**

Use a parameterized test so unsupported paths only fail when applied by `W n`:

```python
@pytest.mark.parametrize(
    "clip_operations",
    [
        "0 0 m 30 0 70 100 100 100 c 100 0 l W n",
        "0 0 m 100 0 l 50 40 l 100 100 l 0 100 l W n",
    ],
)
def test_unsupported_applied_clip_fails_closed(
    clip_operations: str,
) -> None:
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 100, 100),
            "pre_image_operations": clip_operations,
            "text": "A",
        }
    )
    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(data)
    assert exc_info.value.code == "PDF_MALFORMED"
```

- [x] **Step 4: Verify RED**

Run from `backend/`:

```bash
uv run pytest tests/test_t009_pdf_scan_detection.py -q
```

Expected: the compound, even-odd, curved, and non-convex cases fail because unsupported applied clipping currently becomes zero coverage or is accepted.

### Task 2: Reject unsupported applied clipping

**Files:**
- Modify: `backend/app/services/pdf_validation.py`
- Test: `backend/tests/test_t009_pdf_scan_detection.py`

- [x] **Step 1: Make clip polygons concrete**

Change `_image_coverage()`, `_walk_raster_coverage()`, and the graphics stack to use `Polygon`, not `Polygon | None`. Remove the zero-coverage branch:

```python
def _image_coverage(
    matrix: Matrix,
    clip_polygon: Polygon,
    page_area: float,
) -> float:
    image_polygon = _transform_polygon(UNIT_SQUARE, matrix)
    visible_polygon = _clip_polygon(image_polygon, clip_polygon)
    return _polygon_area(visible_polygon) / page_area
```

Keep `current_path: Polygon | None`; `None` means the current path became unsupported, not that the active clipping region is empty.

- [x] **Step 2: Fail when an unsupported path is applied**

At path termination, replace assignment of `current_clip = None` with:

```python
if clip_pending:
    if current_path is None or not _is_convex_polygon(current_path):
        raise _PDFGeometryLimit
    current_clip = _clip_polygon(current_clip, current_path)
```

A second `re`/`m`, curve operator, or `W*` continues to set `current_path = None`. Drawing an unsupported path without `W`/`W*` clears it normally and remains accepted.

- [x] **Step 3: Keep Form clipping concrete**

Always intersect a supported inherited clip with a transformed Form `/BBox`:

```python
form_clip = current_clip
if form_bbox:
    form_clip = _clip_polygon(current_clip, transformed_bbox)
```

An empty polygon is a valid exact clip with zero visible area; it is distinct from unsupported geometry.

- [x] **Step 4: Verify GREEN and regression coverage**

Run from `backend/`:

```bash
uv run pytest \
  tests/test_t009_pdf_scan_detection.py \
  tests/test_t009_pdf_decoded_limit.py \
  tests/test_t009_pdf_behavior.py -q
```

Expected: every focused PDF test passes, including exact rectangular clipping, graphics-state restore, Form geometry, decoded limits, and all fail-closed regressions.

- [x] **Step 5: Run focused style checks**

```bash
uv run ruff check app/services/pdf_validation.py tests/test_t009_pdf_scan_detection.py
uv run black --check app/services/pdf_validation.py tests/test_t009_pdf_scan_detection.py
```

Expected: both commands succeed. If Black reports changes, format only these two files and rerun the focused tests and checks.

### Task 3: Reconcile clipping documentation

**Files:**
- Modify: `docs/superpowers/plans/2026-08-29-pdf-scan-page-detection.md`
- Modify: `docs/superpowers/plans/2026-08-28-pdf-upload-storage-job-lifecycle.md`
- Reference: `docs/superpowers/specs/2026-08-29-t009-clipping-outbox-hardening-design.md`

- [x] **Step 1: Record fail-closed semantics**

Replace wording that says unsupported clipping becomes unknown/zero coverage with the final contract:

```text
Single convex W clipping is measured exactly. Compound, curved, even-odd,
non-convex, or degenerate applied clipping is rejected as PDF_MALFORMED;
it is never converted to zero raster coverage.
```

- [x] **Step 2: Preserve the review handoff**

Do not commit or push this subsystem separately. The final integrated commit includes clipping, outbox, tests, migration, and reconciled documentation so CodeRabbit reviews one exact final HEAD.
