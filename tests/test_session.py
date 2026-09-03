from app.core.session import create_session_token, read_session_token


def test_a_token_round_trips_to_the_same_workspace_id():
    workspace_id = "8efeb645-86e3-4fe6-a87b-e56705a8e12e"
    token = create_session_token(workspace_id)
    assert read_session_token(token) == workspace_id


def test_two_tokens_for_the_same_workspace_are_not_identical():
    # Fernet includes its own timestamp/nonce in the ciphertext, so
    # encrypting the same plaintext twice should not produce the same
    # token -- if it did, that would leak whether two sessions belong
    # to the same workspace just by comparing raw cookie values.
    workspace_id = "8efeb645-86e3-4fe6-a87b-e56705a8e12e"
    assert create_session_token(workspace_id) != create_session_token(workspace_id)


def test_garbage_input_returns_none_instead_of_raising():
    assert read_session_token("not-a-real-token") is None


def test_empty_string_returns_none():
    assert read_session_token("") is None


def test_a_token_for_one_workspace_never_reads_as_another():
    token = create_session_token("11111111-1111-1111-1111-111111111111")
    assert read_session_token(token) != "22222222-2222-2222-2222-222222222222"