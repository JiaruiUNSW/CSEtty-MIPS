from __future__ import annotations

from .errors import AssemblyError, SourceRef

MASK_8 = 0xFF
MASK_16 = 0xFFFF
MASK_32 = 0xFFFF_FFFF
SIGN_32 = 0x8000_0000
INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1


def u32(value: int) -> int:
    return value & MASK_32


def s32(value: int) -> int:
    value &= MASK_32
    return value - (1 << 32) if value & SIGN_32 else value


def sign_extend(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    value &= mask
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def fits_signed(value: int, bits: int) -> bool:
    return -(1 << (bits - 1)) <= value <= (1 << (bits - 1)) - 1


def fits_unsigned(value: int, bits: int) -> bool:
    return 0 <= value <= (1 << bits) - 1


def checked_add_i32(left: int, right: int) -> int | None:
    result = s32(left) + s32(right)
    return u32(result) if INT32_MIN <= result <= INT32_MAX else None


def checked_sub_i32(left: int, right: int) -> int | None:
    result = s32(left) - s32(right)
    return u32(result) if INT32_MIN <= result <= INT32_MAX else None


def require_signed(value: int, bits: int, source: SourceRef, what: str) -> int:
    if not fits_signed(value, bits):
        raise AssemblyError(
            "A120",
            f"{what} {value} does not fit in a signed {bits}-bit field",
            source,
        )
    return value & ((1 << bits) - 1)


def require_signed_or_bit_pattern(value: int, bits: int, source: SourceRef, what: str) -> int:
    """Accept either a signed value or an explicit unsigned field bit pattern."""
    if not (fits_signed(value, bits) or fits_unsigned(value, bits)):
        raise AssemblyError(
            "A120",
            f"{what} {value} does not fit in a signed {bits}-bit field or {bits}-bit pattern",
            source,
        )
    return value & ((1 << bits) - 1)


def require_unsigned(value: int, bits: int, source: SourceRef, what: str) -> int:
    if not fits_unsigned(value, bits):
        raise AssemblyError(
            "A121",
            f"{what} {value} does not fit in an unsigned {bits}-bit field",
            source,
        )
    return value
