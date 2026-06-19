"""Reading the user's own bullets out of a section (e.g. 🔜 Tomorrow)."""
from vault import section_items

NOTE = """# note

## 🔜 Tomorrow
> Anything to carry over or prep for.
- Call the leasing office
- [ ] Submit expense report
- [x] Already booked flight

## 🧠 Learnings
- something
"""


def test_extracts_real_bullets_only() -> None:
    items = section_items(NOTE, "🔜 Tomorrow")
    assert items == [
        "Call the leasing office",
        "Submit expense report",
        "Already booked flight",
    ]


def test_skips_hint_and_blank() -> None:
    # The "> Anything…" hint and blank lines must not appear.
    items = section_items(NOTE, "🔜 Tomorrow")
    assert all(not i.startswith(">") for i in items)
    assert "" not in items


def test_missing_section_empty() -> None:
    assert section_items(NOTE, "🔔 Reminders") == []
