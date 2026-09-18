# T-009 PDF Scan-Page Detection Design

## Goal

Implement BR-07 without adding dependencies: reject a PDF with `PDF_SCAN_ONLY` when any nonblank page contains one raster-image placement covering at least 80% of the visible page area and the page has fewer than 30 useful text characters.

## Semantics

- A useful text character is any Unicode character for which `str.isspace()` is false.
- The text threshold is exact: fewer than 30 rejects; 30 or more passes this rule.
- Image coverage is the visible area of one image placement divided by the page crop-box area. The threshold is inclusive: coverage greater than or equal to `0.80` qualifies.
- A true blank page has no useful text and no raster placement with positive visible area. It does not independently trigger the scan-page rule.
- A file containing no useful text anywhere continues to fail with the existing `PDF_SCAN_ONLY` error.

## Geometry

Walk the already bounded and cached PDF content streams. Maintain the current transformation matrix and the `q`/`Q` graphics-state stack. Handle:

- image XObjects invoked by `Do`;
- inline images;
- nested Form XObjects, including inherited resources and each Form `/Matrix`;
- page crop-box clipping and nested Form `/BBox` clipping;
- cycle and traversal limits for hostile Form graphs.

An image paints the unit square. Transform its four corners into page space, clip the resulting convex polygon against the active page/Form clip polygon, compute the clipped polygon area with the shoelace formula, and compare it with the crop-box area. The walker stops once one placement reaches 80%.

The implementation intentionally does not rasterize pages or decode image pixels. Coverage depends on PDF placement geometry, not image resolution. No native renderer or new package is introduced.

Applied clipping is exact for one simple convex path using either non-zero-winding `W` or even-odd `W*`; both rules produce the same region for that bounded case. Explicitly closed paths are normalized. Curved `W` paths use their control-point bounding box only as a conservative upper bound: when that bound could reach the scan threshold, validation returns `PDF_SCAN_ANALYSIS_UNSUPPORTED` rather than treating the bound as exact evidence for `PDF_SCAN_ONLY`. Compound, curved `W*`, self-intersecting, non-convex, degenerate, or over-limit clipping raises the same geometry-limit boundary; unsupported paths used only for drawing remain accepted.

## Validation Flow

For every page, inside the existing bounded pypdf context:

1. Decode page content and preflight unique Form XObject streams against the cumulative byte budget.
2. Extract text and count useful characters only after Form preflight succeeds.
3. Skip raster geometry when useful text count is at least 30.
4. Otherwise walk image placements recursively and calculate maximum visible coverage.
5. Raise `PDF_SCAN_ANALYSIS_UNSUPPORTED` if applied clipping or Form traversal cannot be represented safely by the bounded geometry walker.
6. Raise `PDF_SCAN_ONLY` when coverage is at least 80% and useful text count is below 30.
7. Ignore a true blank page for page-level scan detection.

Existing active-content, encryption, raw-size, decoded-size, page-count, and malformed-PDF behavior remains unchanged.

## Safety Limits

- Reuse resolved pypdf objects; never decode raster pixels.
- Track visited Form objects on the current recursion path to stop cycles.
- Cap recursive Form depth and total visited content operations. Exceeding either bound returns `PDF_SCAN_ANALYSIS_UNSUPPORTED` rather than allowing unbounded work.
- Keep all content access inside the existing pypdf decode lock and output limits.

## Tests

Add generated-PDF regression coverage for:

- an image covering more than 80% with fewer than 30 useful characters: rejected as `PDF_SCAN_ONLY`;
- the same large-image geometry with at least 30 useful characters: accepted;
- an image below 80% with short text: accepted;
- a text-native page plus a true blank page: accepted;
- a large image inside a transformed Form XObject: detected;
- exact 80% and 30-character boundary behavior.

Run focused PDF tests, Ruff, Black, and the full pytest suite with PostgreSQL integration enabled before pushing.
