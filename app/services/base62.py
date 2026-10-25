"""Base62 encoding and random short-code generation utilities."""

import secrets
import string

BASE62_CHARACTERS = string.digits + string.ascii_letters
BASE62_RADIX = len(BASE62_CHARACTERS)  # 62


def generate_random_code(length: int = 7) -> str:
    """Generate a cryptographically secure random Base62 string.

    A 7-character Base62 string provides 62^7 = 3,521,614,606,208 possible permutations.
    """
    return "".join(secrets.choice(BASE62_CHARACTERS) for _ in range(length))


def encode_base62(num: int) -> str:
    """Encode a positive integer into a Base62 string."""
    if num == 0:
        return BASE62_CHARACTERS[0]
    digits: list[str] = []
    while num > 0:
        rem = num % BASE62_RADIX
        digits.append(BASE62_CHARACTERS[rem])
        num //= BASE62_RADIX
    return "".join(reversed(digits))


def decode_base62(code: str) -> int:
    """Decode a Base62 string back into an integer."""
    num = 0
    for char in code:
        idx = BASE62_CHARACTERS.find(char)
        if idx == -1:
            raise ValueError(f"Invalid Base62 character: '{char}'")
        num = num * BASE62_RADIX + idx
    return num
