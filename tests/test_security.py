from app.core.security import generate_api_key, hash_api_key, verify_api_key


def test_generated_key_has_the_expected_prefix_and_length():
    key = generate_api_key()
    assert key.startswith("ghost_live_")
    assert len(key) == len("ghost_live_") + 32  # 16 bytes of hex


def test_two_generated_keys_are_different():
    assert generate_api_key() != generate_api_key()


def test_hashing_is_deterministic():
    key = "ghost_live_abc123"
    assert hash_api_key(key) == hash_api_key(key)


def test_different_keys_hash_differently():
    assert hash_api_key("ghost_live_aaa") != hash_api_key("ghost_live_bbb")


def test_hash_never_equals_the_raw_key():
    key = "ghost_live_abc123"
    assert hash_api_key(key) != key


def test_verify_api_key_accepts_the_correct_key():
    key = generate_api_key()
    assert verify_api_key(key, hash_api_key(key)) is True


def test_verify_api_key_rejects_a_wrong_key():
    key = generate_api_key()
    other = generate_api_key()
    assert verify_api_key(other, hash_api_key(key)) is False