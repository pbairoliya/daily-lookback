"""Contact allowlist labeling for the family-only iMessage feed."""
import imessage
from imessage import contact_label


def test_label_matches_on_handle_digits(monkeypatch):
    monkeypatch.setattr(imessage, "IMESSAGE_CONTACTS", {
        "5551230001": "Alex (helps with Dad)",
        "5551230002": "Dad",
        "5551230003": "Sam (sister)",
    })
    assert contact_label({"sender": "+15551230001", "chat": ""}) == "Alex (helps with Dad)"
    assert contact_label({"sender": "+15551230002", "chat": "Dad"}) == "Dad"
    assert contact_label({"is_from_me": True, "sender": "me"}) == "me"
    # Unknown sender never leaks a raw number — falls back to chat name.
    assert contact_label({"sender": "+15550001111", "chat": "Spam"}) == "Spam"
