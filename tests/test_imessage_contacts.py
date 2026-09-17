"""Contact allowlist labeling for the family-only iMessage feed."""
import imessage
from imessage import contact_label


def test_label_matches_on_handle_digits(monkeypatch):
    monkeypatch.setattr(imessage, "IMESSAGE_CONTACTS", {
        "5551230001": "Alex (helps with Mom)",
        "5551230002": "Mom",
        "5551230003": "Sam (brother)",
    })
    assert contact_label({"sender": "+15551230001", "chat": ""}) == "Alex (helps with Mom)"
    assert contact_label({"sender": "+15551230002", "chat": "Mom"}) == "Mom"
    assert contact_label({"is_from_me": True, "sender": "me"}) == "me"
    # Unknown sender never leaks a raw number — falls back to chat name.
    assert contact_label({"sender": "+15550001111", "chat": "Spam"}) == "Spam"


def test_prompt_roster_is_built_from_config_labels():
    """No real names live in the source — the roster comes from config."""
    from imessage import build_extract_prompt

    prompt = build_extract_prompt(
        {"5551230001": "Mom", "5551230002": "Sam (brother)"},
        focus="anything about Mom's appointments",
    )
    assert "- Mom" in prompt and "- Sam (brother)" in prompt
    assert "Above all: anything about Mom's appointments." in prompt  # auto-punctuated
    assert "JSON ONLY" in prompt


def test_prompt_degrades_cleanly_with_no_config():
    from imessage import build_extract_prompt

    prompt = build_extract_prompt({}, focus="")
    assert "These messages are ONLY with" not in prompt
    assert "Above all" not in prompt
    assert "JSON ONLY" in prompt


def test_duplicate_labels_appear_once_in_the_roster():
    from imessage import build_extract_prompt

    prompt = build_extract_prompt({"555000": "Mom", "555111": "Mom"}, focus="")
    assert prompt.count("- Mom") == 1
