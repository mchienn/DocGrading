"""Ten-point grades, with compatibility for unmarked historical percentages."""

from decimal import Decimal


def ten_point_score(value: object) -> Decimal | None:
    if value is None:
        return None
    score = Decimal(str(value))
    if not score.is_finite() or not 0 <= score <= 100:
        raise ValueError("Invalid grade")
    # Historical rows have no scale marker. Do not divide already valid /10
    # grades again; preserve ambiguous values <= 10 for teacher review.
    if score > 10:
        score /= 10
    return score.quantize(Decimal("0.01"))


def ten_point_levels(levels: list[dict]) -> list[dict]:
    """Convert a legacy rubric as a whole, without mutating its frozen version."""
    scores = [Decimal(str(level["score"])) for level in levels if "score" in level]
    if not any(score > 10 for score in scores):
        return levels
    return [
        (
            {**level, "score": float(Decimal(str(level["score"])) / 10)}
            if "score" in level
            else dict(level)
        )
        for level in levels
    ]
