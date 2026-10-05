import uuid

from app.synthetic.prober import (
    classify_outcome,
    compute_state_transition,
    resolve_blocks_link_local,
    validate_check_url,
)


def test_classify_outcome_success_in_range():
    outcome = classify_outcome(200, 42.0, None, 200, 299)
    assert outcome.success is True
    assert outcome.error is None


def test_classify_outcome_status_outside_range_is_failure():
    outcome = classify_outcome(500, 10.0, None, 200, 299)
    assert outcome.success is False


def test_classify_outcome_transport_error_is_failure_even_without_status():
    outcome = classify_outcome(None, None, "Connection refused", 200, 299)
    assert outcome.success is False
    assert outcome.error == "Connection refused"


def test_classify_outcome_error_overrides_status_code():
    # Shouldn't happen in practice (error implies no status), but the
    # precedence should still be error-first if both are somehow set.
    outcome = classify_outcome(200, 5.0, "timed out", 200, 299)
    assert outcome.success is False


def test_resolve_blocks_link_local_for_literal_metadata_ip():
    blocked, reason = resolve_blocks_link_local("169.254.169.254")
    assert blocked is True
    assert "169.254.169.254" in reason


def test_resolve_blocks_link_local_allows_ordinary_literal_ip():
    blocked, reason = resolve_blocks_link_local("8.8.8.8")
    assert blocked is False
    assert reason is None


def test_resolve_blocks_link_local_does_not_block_private_ranges():
    # Deliberate: this is a self-hosted deployment, probing a
    # company's own internal services is the legitimate use case.
    blocked, _ = resolve_blocks_link_local("10.0.0.5")
    assert blocked is False
    blocked, _ = resolve_blocks_link_local("192.168.1.1")
    assert blocked is False
    blocked, _ = resolve_blocks_link_local("127.0.0.1")
    assert blocked is False


def test_validate_check_url_rejects_non_http_scheme():
    assert validate_check_url("ftp://example.com") is not None


def test_validate_check_url_rejects_link_local_target():
    error = validate_check_url("http://169.254.169.254/latest/meta-data/")
    assert error is not None
    assert "not allowed" in error


def test_validate_check_url_accepts_ordinary_url():
    assert validate_check_url("https://example.com/health") is None


def test_state_transition_success_resets_failures_and_no_op_when_no_incident_open():
    t = compute_state_transition(True, consecutive_failures=1, failure_threshold=2, open_incident_id=None)
    assert t.new_consecutive_failures == 0
    assert t.should_open_incident is False
    assert t.should_resolve_incident is False


def test_state_transition_success_resolves_open_incident():
    t = compute_state_transition(True, consecutive_failures=3, failure_threshold=2, open_incident_id=uuid.uuid4())
    assert t.new_consecutive_failures == 0
    assert t.should_resolve_incident is True


def test_state_transition_failure_below_threshold_does_not_open():
    t = compute_state_transition(False, consecutive_failures=0, failure_threshold=2, open_incident_id=None)
    assert t.new_consecutive_failures == 1
    assert t.should_open_incident is False


def test_state_transition_failure_crossing_threshold_opens_incident():
    t = compute_state_transition(False, consecutive_failures=1, failure_threshold=2, open_incident_id=None)
    assert t.new_consecutive_failures == 2
    assert t.should_open_incident is True


def test_state_transition_failure_does_not_duplicate_already_open_incident():
    t = compute_state_transition(False, consecutive_failures=5, failure_threshold=2, open_incident_id=uuid.uuid4())
    assert t.new_consecutive_failures == 6
    assert t.should_open_incident is False