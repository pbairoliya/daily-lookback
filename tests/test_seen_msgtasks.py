"""Grow-only message-task signature store + fuzzy de-dup behavior."""
import taskcat
import runstate


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(runstate, "SEEN_MSGTASKS_FILE", tmp_path / "seen.json")
    sigs = [{"check", "tracking", "sara", "order"}, {"call", "doctor"}]
    runstate.write_seen_msgtasks(sigs)
    back = runstate.read_seen_msgtasks()
    assert back == sigs


def test_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(runstate, "SEEN_MSGTASKS_FILE", tmp_path / "nope.json")
    assert runstate.read_seen_msgtasks() == []


def test_reworded_commitment_matches_prior_signature():
    # The two phrasings the iMessage model produced on different days.
    a = taskcat.significant_words("Check tracking for Alex's order.")
    b = taskcat.significant_words("Check tracking for an order Alex placed.")
    assert taskcat.jaccard(a, b) >= 0.5  # would be skipped as already-surfaced


def test_distinct_commitments_dont_match():
    a = taskcat.significant_words("Call Dad's doctor about the prescription")
    b = taskcat.significant_words("Send Sam the vacation photos")
    assert taskcat.jaccard(a, b) < 0.5
