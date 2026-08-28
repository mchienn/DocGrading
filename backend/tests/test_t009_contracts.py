import pytest

from app.models.enums import AnalysisJobStatus


def test_analysis_job_has_only_terminal_done_and_error_states() -> None:
    assert [member.value for member in AnalysisJobStatus] == [
        "QUEUED",
        "RUNNING",
        "DONE",
        "ERROR",
    ]


def test_analysis_job_has_nullable_timezone_heartbeat_at_column() -> None:
    import sqlalchemy as sa

    from app.models.analysis import AnalysisJob

    col = AnalysisJob.__table__.c.heartbeat_at
    assert col.nullable is True
    assert isinstance(col.type, sa.DateTime)
    assert col.type.timezone is True


def test_pdf_validation_rejects_non_pdf_with_stable_code() -> None:
    from app.services.pdf_validation import PDFValidationError, validate_pdf

    with pytest.raises(PDFValidationError) as error:
        validate_pdf(b"not a pdf")
    assert error.value.code == "NOT_A_PDF"


def test_presign_policy_is_exact_and_short_lived() -> None:
    from app.services.storage import S3Storage

    policy = S3Storage.build_presign_conditions(
        key="uploads/random.pdf", max_size=50_000_000
    )
    assert {"key": "uploads/random.pdf"} in policy
    assert {"Content-Type": "application/pdf"} in policy
    assert ["content-length-range", 1, 50_000_000] in policy
