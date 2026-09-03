# Document IR & PDF Parser Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse each validated text-native PDF once into one durable, idempotently replaceable Document IR containing pages, nested sections, paragraphs, tables, and page coordinates.

**Architecture:** Add one `DocumentIR` owner row per `DocumentVersion`, storing a versioned JSONB payload. A pure parser calls existing `validate_pdf` first, then uses bounded pypdf/pdfplumber extraction under one node budget. An async persistence service locks the owning `Submission` first, then the target `DocumentVersion` with `FOR UPDATE`, reuses existing IR by default, or atomically replaces it for an explicit rebuild. Only non-null `declared_sha256` is checksum-authoritative; worker success overwrites server-observed `sha256` metadata.

**Tech Stack:** Python 3.13, pypdf 6.x, pdfplumber 0.11.x, SQLAlchemy 2 async, PostgreSQL 17 JSONB, Alembic, pytest, Ruff, Black.

---

## File map

**Create**

- `backend/app/services/document_ir.py` — pure bounded parser, structural heuristics, cross-page table join, persistence lock/rebuild operation.
- `backend/alembic/versions/20260902_0008_document_ir.py` — schema-qualified reversible `document_irs` migration.
- `backend/tests/test_t010_document_ir_parser.py` — pure and real-PDF parser/security edge tests.
- `backend/tests/test_t010_document_ir_persistence.py` — ORM contract, idempotent rebuild, `FOR UPDATE`, worker integration, PostgreSQL concurrency.
- `backend/tests/test_t010_migration_roundtrip.py` — PostgreSQL upgrade/downgrade and audit TRUNCATE guard.

**Modify**

- `backend/pyproject.toml`, `backend/uv.lock` — add pdfplumber using existing dependency policy.
- `backend/app/core/config.py` — add positive `pdf_ir_max_nodes` setting.
- `backend/app/models/analysis.py` — add `DocumentIR` model.
- `backend/app/models/submission.py` — add one-to-one `DocumentVersion.document_ir` relationship.
- `backend/app/models/__init__.py` — export `DocumentIR`.
- `backend/app/workers/tasks.py` — build/reuse IR before fenced job completion.
- `backend/tests/test_models.py` — register and verify model/table/FK/JSONB constraints.
- `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md` — reconcile only proven parser/persistence details after verification.

## Task 1: Lock schema and migration security contract

**Files:**
- Modify: `backend/tests/test_models.py`
- Create: `backend/alembic/versions/20260902_0008_document_ir.py`
- Modify: `backend/app/models/analysis.py`
- Modify: `backend/app/models/submission.py`
- Modify: `backend/app/models/__init__.py`

- [x] **Step 1: Write failing model metadata tests**

Add `DocumentIR` to imports and `MODEL_TABLE_MAP`, then add assertions:

```python
assert isinstance(DocumentIR.__table__.c.content.type, JSONB)
assert foreign_key_targets(DocumentIR) == {"document_versions.id"}
assert DocumentIR.__table__.c.document_version_id.unique

checks = {
    constraint.name
    for constraint in DocumentIR.__table__.constraints
    if isinstance(constraint, CheckConstraint)
}
assert {
    "ck_document_irs_schema_version_positive",
    "ck_document_irs_parser_version_not_blank",
    "ck_document_irs_content_object",
} <= checks
```

Expected model map entry:

```python
DocumentIR: "document_irs",
```

- [x] **Step 2: Run metadata test RED**

Run from `backend/`:

```text
uv run pytest tests/test_models.py -q
```

Expected: collection fails because `DocumentIR` is not exported.

- [x] **Step 3: Add minimal ORM model and relationships**

Add to `backend/app/models/analysis.py`:

```python
class DocumentIR(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_irs"
    __table_args__ = (
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_document_irs_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(parser_version)) > 0 "
            "AND parser_version !~ '^[[:space:]]*$'",
            name="ck_document_irs_parser_version_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'",
            name="ck_document_irs_content_object",
        ),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "document_versions.id",
            ondelete="CASCADE",
            name="fk_document_irs_document_version_id_document_versions",
        ),
        unique=True,
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        sa.Integer,
        default=1,
        server_default=sa.text("1"),
        nullable=False,
    )
    parser_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(
        "DocumentVersion",
        back_populates="document_ir",
        foreign_keys=[document_version_id],
    )
```

Add `DocumentIR` to `TYPE_CHECKING` and add to `DocumentVersion`:

```python
document_ir: Mapped[DocumentIR | None] = relationship(
    "DocumentIR",
    back_populates="document_version",
    foreign_keys="DocumentIR.document_version_id",
    uselist=False,
    passive_deletes=True,
)
```

Export `DocumentIR` through `app.models`.

- [x] **Step 4: Create migration only after SC-1/2/3 checklist exists**

Create exact revision skeleton:

```python
"""Add durable Document IR storage.

SC-1: both directions pin ``search_path`` before any operation.
SC-2: this revision never touches append-only audit tables or triggers.
SC-3: all application objects and foreign-key targets are schema-qualified.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260902_0008"
down_revision: str | None = "20260829_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.create_table(
        "document_irs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "schema_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_document_irs_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(parser_version)) > 0 "
            "AND parser_version !~ '^[[:space:]]*$'",
            name="ck_document_irs_parser_version_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'",
            name="ck_document_irs_content_object",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["public.document_versions.id"],
            name="fk_document_irs_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_irs"),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_document_irs_document_version_id",
        ),
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_table("document_irs", schema="public")
```

Do not add functions, triggers, raw unqualified names, audit-table operations, or data rewrites.

- [x] **Step 5: Run metadata test GREEN and offline migration smoke**

```text
uv run pytest tests/test_models.py -q
uv run alembic upgrade head --sql
```

Expected: model tests pass; generated SQL creates only `public.document_irs` for revision 0008 and includes `public.document_versions.id`.

- [x] **Step 6: Commit schema slice**

```text
git add backend/app/models backend/alembic/versions/20260902_0008_document_ir.py backend/tests/test_models.py
git commit -m "feat(t010): add durable document IR schema"
```

## Task 2: Add parser dependency, limits, and validation-first boundary

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/document_ir.py`
- Create: `backend/tests/test_t010_document_ir_parser.py`

- [x] **Step 1: Add pdfplumber through uv**

Run from `backend/`:

```text
uv add "pdfplumber>=0.11,<1"
```

Expected: `pyproject.toml` and `uv.lock` change; no unrelated dependency removal.

- [x] **Step 2: Write validation-order and budget RED tests**

Use monkeypatched collaborators, not source-text assertions:

```python
def test_parser_validates_before_opening_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def reject(_data: bytes, **_limits: int) -> None:
        calls.append("validate")
        raise PDFValidationError("PDF_ACTIVE_CONTENT")

    def must_not_open(_stream: BytesIO):
        calls.append("open")
        raise AssertionError("pdfplumber must not open rejected bytes")

    monkeypatch.setattr(document_ir, "validate_pdf", reject)
    monkeypatch.setattr(document_ir.pdfplumber, "open", must_not_open)

    with pytest.raises(PDFValidationError, match="PDF_ACTIVE_CONTENT"):
        document_ir.parse_document_ir(b"%PDF-rejected")
    assert calls == ["validate"]


def test_node_budget_fails_closed() -> None:
    budget = document_ir._NodeBudget(limit=2)
    budget.consume()
    budget.consume()
    with pytest.raises(PDFValidationError) as error:
        budget.consume()
    assert error.value.code == "PDF_STRUCTURE_LIMIT"
```

Add a real active-content test using `PdfWriter.add_js(...)` and a second case
using `PdfWriter.add_attachment(...)`. Monkeypatch `pdfplumber.open` to raise
if called; both `parse_document_ir` calls must raise
`PDFValidationError("PDF_ACTIVE_CONTENT")` before that callback runs.

Add a parser-level node test with a valid PDF containing many positioned text
runs and `max_nodes=3`. Assert `PDF_STRUCTURE_LIMIT`; use a counting fake page
to prove no later layout object is visited after exhaustion.

Also test config rejects `PDF_IR_MAX_NODES=0`.

- [x] **Step 3: Run parser boundary tests RED**

```text
uv run pytest tests/test_t010_document_ir_parser.py -q
```

Expected: import fails because `app.services.document_ir` does not exist.

- [x] **Step 4: Add minimal parser boundary**

Create constants and types:

```python
SCHEMA_VERSION = 1
PARSER_VERSION = "pypdf-pdfplumber-v1"


class DocumentIRExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedDocumentIR:
    validation: PDFValidationResult
    content: dict[str, Any]


@dataclass
class _NodeBudget:
    limit: int
    used: int = 0

    def consume(self, count: int = 1) -> None:
        if count < 0 or self.used + count > self.limit:
            raise PDFValidationError("PDF_STRUCTURE_LIMIT")
        self.used += count
```

Add synchronous entrypoint:

```python
def parse_document_ir(
    data: bytes,
    *,
    max_size_bytes: int = 50_000_000,
    max_page_count: int = 100,
    max_nodes: int = 100_000,
) -> ParsedDocumentIR:
    validation = validate_pdf(
        data,
        max_size_bytes=max_size_bytes,
        max_page_count=max_page_count,
    )
    budget = _NodeBudget(max_nodes)
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            pages = _parse_pages(pdf.pages, budget)
    except PDFValidationError:
        raise
    except Exception as exc:
        raise DocumentIRExtractionError("Document IR extraction failed") from exc
    content = _assemble_ir(validation, pages, budget)
    return ParsedDocumentIR(validation=validation, content=content)
```

Add to `Settings`:

```python
pdf_ir_max_nodes: int = Field(default=100_000, gt=0)
```

Initially `_parse_pages` may return page metadata with empty structural arrays; later tasks fill it.

- [x] **Step 5: Run boundary tests GREEN**

```text
uv run pytest tests/test_t010_document_ir_parser.py -q
```

Expected: validation order, positive setting, and exact budget boundary pass.

- [x] **Step 6: Commit parser boundary**

```text
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/app/services/document_ir.py backend/tests/test_t010_document_ir_parser.py
git commit -m "feat(t010): add bounded document IR parser boundary"
```

## Task 3: Extract pages, headings, nested sections, and paragraphs

**Files:**
- Modify: `backend/app/services/document_ir.py`
- Modify: `backend/tests/test_t010_document_ir_parser.py`

- [x] **Step 1: Add a real text-PDF builder and edge tests**

Build PDFs with pypdf `DecodedStreamObject`, Helvetica resources, and explicit content operators. The helper accepts page operation lists:

```python
def make_text_pdf(*page_operations: list[str]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    for operations in page_operations:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = resources
        content = DecodedStreamObject()
        content.set_data("\n".join(operations).encode("ascii"))
        page[NameObject("/Contents")] = content
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
```

Required tests:

```python
def test_document_without_headings_has_root_paragraphs() -> None:
    parsed = parse_document_ir(
        make_text_pdf([
            "BT /F1 12 Tf 72 700 Td (Ordinary paragraph line one.) Tj ET",
            "BT /F1 12 Tf 72 684 Td (Ordinary paragraph line two.) Tj ET",
        ])
    )
    assert parsed.content["sections"] == []
    assert [p["section_id"] for p in parsed.content["paragraphs"]] == [None]
    assert "line one. Ordinary paragraph line two." in parsed.content["pages"][0]["text"]


def test_nested_numbered_headings_build_parent_chain() -> None:
    parsed = parse_document_ir(
        make_text_pdf([
            "BT /F1 18 Tf 72 730 Td (1 Introduction) Tj ET",
            "BT /F1 12 Tf 72 710 Td (Root body text long enough.) Tj ET",
            "BT /F1 16 Tf 72 680 Td (1.1 Scope) Tj ET",
            "BT /F1 14 Tf 72 650 Td (1.1.1 Inputs) Tj ET",
            "BT /F1 13 Tf 72 620 Td (1.1.1.1 Validation) Tj ET",
            "BT /F1 12 Tf 72 590 Td (Nested body text long enough.) Tj ET",
        ])
    )
    sections = parsed.content["sections"]
    assert [section["level"] for section in sections] == [1, 2, 3, 4]
    assert [section["parent_id"] for section in sections] == [
        None,
        sections[0]["id"],
        sections[1]["id"],
        sections[2]["id"],
    ]
```

Add a skipped-level case: `1` followed by `1.1.1`; child attaches to level 1 with no synthetic level 2.

Add a two-page case with text on page 1 and a blank page 2. Assert page 2
remains in `content["pages"]` with empty text and block IDs. Add a typography
case proving a short 18-point line above 12-point body text becomes a heading,
while an ordinary 12-point capitalized sentence ending in a period does not.

- [x] **Step 2: Run structural tests RED**

```text
uv run pytest tests/test_t010_document_ir_parser.py -q
```

Expected: empty placeholder structure does not satisfy heading/paragraph assertions.

- [x] **Step 3: Implement bounded word/line extraction**

Use `page.extract_words(extra_attrs=["fontname", "size"])`. Before emitting structures, consume budget for every page object list and extracted word. Group words whose `top` values differ by at most 3 points, then sort each line by `x0`.

Define internal immutable records:

```python
@dataclass(frozen=True)
class _BBox:
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class _Line:
    text: str
    bbox: _BBox
    font_size: float
    font_name: str
```

`_safe_bbox` rejects non-finite, reversed, negative, or out-of-page coordinates with `PDFValidationError("PDF_IR_MALFORMED")`; output values use `round(value, 3)`.

- [x] **Step 4: Implement heading and section stack**

Use:

```python
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+\S")
```

Numbered headings derive level from dot depth. Typography headings require short text, no sentence-ending period, and either bold font or size at least 1.25 times median body size. Rank distinct typography sizes descending for level. Numbering wins when both signals match.

Create deterministic IDs in reading order: `section-1`, `section-2`; use a stack keyed by level and attach to closest preceding lower level.

- [x] **Step 5: Implement paragraph grouping**

Exclude heading lines and table-overlapping lines. Join adjacent lines when horizontal start differs by at most 12 points and vertical gap is no more than `max(6, previous_height * 1.5)`. Paragraph IDs are `paragraph-1`, `paragraph-2`; paragraph section is current section at the line position. Never join across pages.

- [x] **Step 6: Run structural tests GREEN**

```text
uv run pytest tests/test_t010_document_ir_parser.py -q
```

Expected: no-heading, deep nesting, skipped-level, paragraph, text order, and coordinate invariants pass.

- [x] **Step 7: Commit structure extraction**

```text
git add backend/app/services/document_ir.py backend/tests/test_t010_document_ir_parser.py
git commit -m "feat(t010): extract pages sections and paragraphs"
```

## Task 4: Extract tables and join cross-page fragments

**Files:**
- Modify: `backend/app/services/document_ir.py`
- Modify: `backend/tests/test_t010_document_ir_parser.py`

- [x] **Step 1: Add ruled-table PDF test across two pages**

Generate page 1 grid in the lower continuation zone and page 2 grid in the upper continuation zone. Each has identical two-column x boundaries and a repeated `Name | Value` header. Assert:

```python
assert len(parsed.content["tables"]) == 1
table = parsed.content["tables"][0]
assert [region["page_number"] for region in table["regions"]] == [1, 2]
assert table["page_start"] == 1
assert table["page_end"] == 2
assert [row["cells"][0]["text"] for row in table["rows"]] == [
    "Name",
    "First",
    "Second",
]
assert all(
    cell is None or {"x0", "top", "x1", "bottom"} <= cell["bbox"].keys()
    for row in table["rows"]
    for cell in row["cells"]
)
```

Add a negative case: same page zones but incompatible column boundaries produce two tables.

- [x] **Step 2: Run table tests RED**

```text
uv run pytest tests/test_t010_document_ir_parser.py -q
```

Expected: tables remain empty.

- [x] **Step 3: Implement bounded page table regions**

For every `page.find_tables()` result:

- consume one node for table, region, each row, and each cell slot;
- validate table bbox and every non-null cell bbox with `_safe_bbox`;
- pair `table.rows[*].cells` with `table.extract()` values using `zip(..., strict=True)`;
- normalize cell text with collapsed whitespace;
- retain explicit `None` for missing cells;
- exclude words whose center lies inside table bbox from heading/paragraph classification.

Store normalized column boundaries from non-null first-row cell bboxes divided by page width.

- [x] **Step 4: Implement conservative cross-page join**

Join only consecutive-page regions when:

```python
previous["bbox"]["bottom"] >= previous_page_height * 0.8
current["bbox"]["top"] <= current_page_height * 0.2
same_column_count
max_boundary_delta <= 0.02
```

When normalized first-row text is identical, keep the first header and skip the repeated row. Otherwise preserve all rows. Keep page-specific regions; never create one cross-page bbox.

- [x] **Step 5: Run table tests GREEN**

```text
uv run pytest tests/test_t010_document_ir_parser.py -q
```

Expected: compatible fragments merge once; incompatible fragments stay separate; table text is absent from paragraphs.

- [x] **Step 6: Commit table extraction**

```text
git add backend/app/services/document_ir.py backend/tests/test_t010_document_ir_parser.py
git commit -m "feat(t010): extract cross-page PDF tables"
```

## Task 5: Add locked idempotent persistence

**Files:**
- Modify: `backend/app/services/document_ir.py`
- Create: `backend/tests/test_t010_document_ir_persistence.py`

- [x] **Step 1: Write mock-session lock/reuse/rebuild RED tests**

Prove observable behavior:

- first SQL statement locks owning `Submission`, then target `DocumentVersion` renders `FOR UPDATE` under PostgreSQL dialect;
- existing IR plus `rebuild=False` returns without calling `parse_document_ir`;
- `rebuild=True` calls parser once, retains the same IR ID, and replaces content rather than merging old keys;
- first build adds exactly one `DocumentIR` and flushes;
- only non-null declared SHA mismatch and sibling duplicate server SHA raise stable `PDF_SHA256_MISMATCH` and `PDF_DUPLICATE` before adding IR;
- a legacy row with null `declared_sha256` accepts a stale stored SHA hint and lets worker metadata overwrite it.

Compile lock statements using:

```python
sql = str(statement.compile(dialect=postgresql.dialect()))
assert "FOR UPDATE" in sql
```

- [x] **Step 2: Run persistence tests RED**

```text
uv run pytest tests/test_t010_document_ir_persistence.py -q
```

Expected: `get_or_build_document_ir` does not exist.

- [x] **Step 3: Implement one locked operation**

Add:

```python
async def get_or_build_document_ir(
    db: AsyncSession,
    document_version_id: uuid.UUID,
    data: bytes,
    *,
    rebuild: bool = False,
) -> DocumentIR:
    await db.execute(
        sa.select(Submission)
        .join(DocumentVersion, DocumentVersion.submission_id == Submission.id)
        .where(DocumentVersion.id == document_version_id)
        .with_for_update(of=Submission)
    )
    document = (
        await db.execute(
            sa.select(DocumentVersion)
            .where(DocumentVersion.id == document_version_id)
            .with_for_update()
        )
    ).scalar_one()
    existing = (
        await db.execute(
            sa.select(DocumentIR).where(
                DocumentIR.document_version_id == document_version_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None and not rebuild:
        return existing

    settings = get_settings()
    parsed = await asyncio.to_thread(
        parse_document_ir,
        data,
        max_size_bytes=settings.pdf_max_size_bytes,
        max_page_count=settings.pdf_max_page_count,
        max_nodes=settings.pdf_ir_max_nodes,
    )
    if document.declared_sha256 is not None and (
        document.declared_sha256 != parsed.validation.sha256
    ):
        raise PDFValidationError(
            "PDF_SHA256_MISMATCH",
            "PDF checksum does not match",
        )
    duplicate = (
        await db.execute(
            sa.select(DocumentVersion.id).where(
                DocumentVersion.submission_id == document.submission_id,
                DocumentVersion.sha256 == parsed.validation.sha256,
                DocumentVersion.id != document.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise PDFValidationError("PDF_DUPLICATE", "Duplicate document version")

    if existing is None:
        existing = DocumentIR(
            document_version_id=document.id,
            schema_version=SCHEMA_VERSION,
            parser_version=PARSER_VERSION,
            content=parsed.content,
        )
        db.add(existing)
    else:
        existing.schema_version = SCHEMA_VERSION
        existing.parser_version = PARSER_VERSION
        existing.content = parsed.content
    await db.flush()
    return existing
```

Do not use an upsert as a substitute for the submission/document locks.

- [x] **Step 4: Run persistence unit tests GREEN**

```text
uv run pytest tests/test_t010_document_ir_persistence.py -q
```

Expected: lock, no-reparse replay, clean replacement, checksum, and duplicate tests pass.

- [x] **Step 5: Add real-PostgreSQL two-session tests**

Guard with `RUN_DATABASE_TESTS=1`. Seed the minimum Course/Assignment/Submission/DocumentVersion graph using unique UUIDs. For one target version, observe the first parser entering while it holds the submission/document locks; the second same-version session must block, then reuse the stored IR without entering the parser. For two versions under one Submission, start with distinct stale SHA hints, observe the second session waiting on the Submission lock, update the first version with the parsed server SHA before commit, and require the second session to raise safe `PDF_DUPLICATE`.

Assert:
```python
assert parser_call_count == 1
assert await scalar_count("public.document_irs", document_version_id) == 1
```

Always delete seeded rows in reverse FK order.

- [x] **Step 6: Run PostgreSQL concurrency tests GREEN**

```text
RUN_DATABASE_TESTS=1 uv run pytest tests/test_t010_document_ir_persistence.py -q
```

Expected: same-version replay parses once; sibling duplicate race yields one IR and safe `PDF_DUPLICATE`.

- [x] **Step 7: Commit persistence slice**

```text
git add backend/app/services/document_ir.py backend/tests/test_t010_document_ir_persistence.py
git commit -m "feat(t010): persist document IR idempotently"
```

## Task 6: Integrate worker without weakening attempt fencing

**Files:**
- Modify: `backend/app/workers/tasks.py`
- Modify: `backend/tests/test_t010_document_ir_persistence.py`
- Modify: relevant existing T-009 worker tests only where mocks need the new collaborator

- [x] **Step 1: Write worker RED tests**

Test four outcomes by mocking storage, `get_or_build_document_ir`, and existing job service calls:

1. success updates `sha256`, `size_bytes`, and `page_count` from `ir.content["source"]`, then calls fenced `mark_done`;
2. `PDFValidationError("PDF_STRUCTURE_LIMIT")` marks document `INVALID` and job error with the same code;
3. `DocumentIRExtractionError` marks document `PROCESSING_FAILED` with `PDF_IR_EXTRACTION_FAILED` and sanitized detail;
4. stale `mark_done=False` rolls back, leaving no committed IR mutation.

- [x] **Step 2: Run worker tests RED**

```text
uv run pytest tests/test_t010_document_ir_persistence.py tests/test_t009_pdf_behavior.py tests/test_t009_job_recovery.py -q
```

Expected: worker never calls IR builder.

- [x] **Step 3: Replace validation-only worker branch**

Import:

```python
from app.services.document_ir import (
    DocumentIRExtractionError,
    get_or_build_document_ir,
)
```

After bounded storage read, call:

```python
ir = await get_or_build_document_ir(
    db,
    job.document_version.id,
    data,
)
job_outcome = ("success", ir)
```

Retain `except PDFValidationError`. Add a distinct `except DocumentIRExtractionError` before generic storage failure. Remove duplicate standalone `validate_pdf`, SHA mismatch, and duplicate queries because the locked service now owns them once.

On success:

```python
source = ir.content["source"]
job.document_version.sha256 = source["sha256"]
job.document_version.size_bytes = source["size_bytes"]
job.document_version.page_count = source["page_count"]
success = await mark_done(db, job, attempt_count=claimed_attempt)
```

On extraction error use only:

```python
job.document_version.status = DocumentStatus.PROCESSING_FAILED
job.document_version.failure_code = "PDF_IR_EXTRACTION_FAILED"
job.document_version.failure_detail = "Document structure extraction failed"
```

Do not log exception text or extracted content.

- [x] **Step 4: Run focused worker tests GREEN**

```text
uv run pytest tests/test_t010_document_ir_persistence.py tests/test_t009_pdf_behavior.py tests/test_t009_job_recovery.py -q
```

Expected: T-010 outcomes pass; existing upload/job lifecycle remains green.

- [x] **Step 5: Commit worker integration**

```text
git add backend/app/workers/tasks.py backend/tests/test_t010_document_ir_persistence.py backend/tests/test_t009_pdf_behavior.py backend/tests/test_t009_job_recovery.py
git commit -m "feat(t010): build document IR in analysis worker"
```

## Task 7: Prove migration roundtrip and append-only safety on PostgreSQL

**Files:**
- Create: `backend/tests/test_t010_migration_roundtrip.py`

- [x] **Step 1: Write real-PostgreSQL migration test**

Guard with `RUN_DATABASE_TESTS=1`. Use Alembic config from existing T-009 migration tests. Test sequence:

1. downgrade to `20260829_0007`;
2. upgrade to `20260902_0008`;
3. query `information_schema.tables`, `pg_constraint`, and `information_schema.columns` to prove table, FK, unique, checks, JSONB, and timestamps;
4. inside a nested transaction/savepoint, assert `TRUNCATE public.audit_events` raises an append-only error without invalidating later assertions;
5. downgrade to `20260829_0007` and prove only `public.document_irs` disappeared;
6. in a fresh nested transaction/savepoint, assert audit TRUNCATE remains rejected;
7. upgrade back to `head` in `finally`.

Static contract assertions also inspect migration module attributes and exact down revision, but do not replace PostgreSQL behavior.

- [x] **Step 2: Run migration roundtrip**

```text
RUN_DATABASE_TESTS=1 uv run pytest tests/test_t010_migration_roundtrip.py -q
```

Expected: upgrade/downgrade/re-upgrade succeeds; audit TRUNCATE rejected in both schemas. Any failure must be fixed in migration or test setup, not suppressed.


- [x] **Step 3: Commit migration verification**

```text
git add backend/tests/test_t010_migration_roundtrip.py
git commit -m "test(t010): verify document IR migration roundtrip"
```

## Task 8: Full verification, three-group review, and documentation reconciliation

**Files:**
- Modify: `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md` only when implementation changed canonical detail
- Modify: `docs/superpowers/specs/2026-09-02-document-ir-pdf-parser-design.md` only for verified contract corrections
- Modify: `docs/superpowers/plans/2026-09-02-document-ir-pdf-parser.md` checkboxes during execution

- [x] **Step 1: Run focused T-010 tests**

```text
uv run pytest tests/test_t010_document_ir_parser.py tests/test_t010_document_ir_persistence.py tests/test_t010_migration_roundtrip.py -v
```

Expected: all pass; database tests require `RUN_DATABASE_TESTS=1` for execution rather than skip evidence.

- [x] **Step 2: Run required format and test suite**

```text
uv run ruff check .
uv run black --check .
RUN_DATABASE_TESTS=1 uv run pytest -v
```

Expected: all commands exit 0. Record exact passed/skipped counts.

- [x] **Step 3: Run explicit Alembic roundtrip on PostgreSQL 17**

```text
uv run alembic upgrade head
uv run alembic downgrade 20260829_0007
uv run alembic upgrade head
```

Expected: all exit 0. Immediately rerun audit TRUNCATE guard test and T-010 concurrency test.

- [x] **Step 4: Functional Correctness review**

Confirm with named passing tests:

- zero headings produces root paragraphs;
- deep and skipped heading levels produce correct parents;
- compatible cross-page tables merge, incompatible tables do not;
- coordinates remain finite, ordered, and page-bounded;
- table text is not duplicated as paragraph text.

- [x] **Step 5: Data Integrity & Integration review**

Confirm with named passing tests:

- normal replay does not invoke parser;
- forced rebuild updates same row and removes old payload keys;
- one target version produces one parse and one row through `FOR UPDATE`;
- sibling versions lock the owning `Submission` before duplicate-SHA validation;
- null `declared_sha256` does not treat stale stored hints as authoritative;
- worker persists IR and terminal job state in one fenced transaction;
- migration and ORM metadata align.

- [x] **Step 6: Security & Privacy review**

Confirm with named passing tests:

- `validate_pdf` runs before pdfplumber;
- page-tree preflight rejects forged count/cycle/depth/node/dereference abuse before page flattening;
- active/embedded content never reaches extractor, while benign structural `/S` values pass;
- node and table complexity budgets halt traversal before further work;
- pypdf/pdfminer/pdfplumber records are suppressed without suppressing application logs, including concurrent contexts and exception cleanup;
- no content or storage secrets enter persisted error detail/logs;
- SC-1/2/3 hold and audit TRUNCATE remains blocked.

- [x] **Step 7: Reconcile canonical docs**

Update only verified facts: one JSONB IR per `DocumentVersion`, top-left point coordinates, parser versioning, pdfplumber table extraction, and worker parse-once lifecycle. Do not add frontend/evaluator behavior.

- [x] **Step 8: Run final verification after documentation edits**

```text
uv run ruff check .
uv run black --check .
RUN_DATABASE_TESTS=1 uv run pytest -v
```

Expected: all pass after final integrated state.

- [x] **Step 9: Commit final reconciliation**

```text
git add docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md docs/superpowers/specs/2026-09-02-document-ir-pdf-parser-design.md docs/superpowers/plans/2026-09-02-document-ir-pdf-parser.md
git commit -m "docs(t010): reconcile document IR contract"
```

Final report must list files changed, exact verification commands/results, Alembic upgrade/downgrade evidence, separate three-group review, DOC_IMPACT, and remaining risks.
