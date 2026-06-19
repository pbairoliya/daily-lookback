"""Housing inquiries are dropped unless from an allowlisted manager."""
from reminders import classify_email


def _mail(frm: str, subject: str, snippet: str = "") -> dict:
    return {"from": frm, "subject": subject, "snippet": snippet, "labels": []}


def test_generic_housing_inquiry_dropped() -> None:
    m = classify_email(
        _mail("leasing@parcapts.com", "Inquiry about your apartment application",
              "Following up regarding your lease application and tour.")
    )
    assert m["category"] == "noise"
    assert m["actionable"] is False


def test_alcott_inquiry_kept() -> None:
    m = classify_email(
        _mail("leasing@alcott.com", "Inquiry about your apartment application",
              "Alcott leasing — following up regarding your lease application.")
    )
    assert m["category"] == "housing_inquiry"
    assert m["actionable"] is True


def test_akelius_inquiry_kept() -> None:
    m = classify_email(
        _mail("noreply@akelius.com", "Regarding your apartment inquiry",
              "Akelius Real Estate Management — your lease application tour.")
    )
    assert m["category"] == "housing_inquiry"
