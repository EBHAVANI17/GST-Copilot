"""GSTIN format and check character.

A GSTIN has 15 characters: 2-digit state code, 10-character PAN, entity number,
the letter Z (by default), and a check character computed from the first 14
(weighted base-36 sum, weights 1, 2, 1, 2, ...).
"""

import re

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SHAPE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


def check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = ALPHABET.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return ALPHABET[(36 - total % 36) % 36]


def is_valid(gstin: str) -> bool:
    """Right shape and right check character. Says nothing about registration."""
    g = gstin.strip().upper()
    return bool(_SHAPE.match(g)) and check_char(g[:14]) == g[14]


def state_code(gstin: str) -> str:
    return gstin[:2]
