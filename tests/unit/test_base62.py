"""Unit tests for Base62 encoding and generator."""

import pytest

from app.services.base62 import decode_base62, encode_base62, generate_random_code


def test_generate_random_code_length() -> None:
    """Verify generated code has requested length and valid characters."""
    code = generate_random_code(7)
    assert len(code) == 7
    assert code.isalnum()


def test_generate_random_code_uniqueness() -> None:
    """Verify high randomness across consecutive generations."""
    generated = {generate_random_code(7) for _ in range(1000)}
    assert len(generated) == 1000


def test_encode_and_decode_symmetry() -> None:
    """Verify integer encode and decode roundtrip."""
    test_values = [0, 1, 61, 62, 100, 99999, 1234567890, 3521614606207]
    for val in test_values:
        encoded = encode_base62(val)
        decoded = decode_base62(encoded)
        assert decoded == val


def test_invalid_base62_character_raises() -> None:
    """Verify decoding invalid characters raises ValueError."""
    with pytest.raises(ValueError, match="Invalid Base62 character"):
        decode_base62("abc#123")
