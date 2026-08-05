from __future__ import annotations

import random

import pytest

from csetty_mips import SourceUnit, assemble
from csetty_mips.disassembler import disassemble
from csetty_mips.errors import RuntimeFault
from csetty_mips.isa import (
    ALL_REAL_INSTRUCTIONS,
    BRANCH1_OPCODES,
    BRANCH2_OPCODES,
    FPU_MEMORY_OPCODES,
    I_SIGNED_OPCODES,
    I_UNSIGNED_OPCODES,
    MEMORY_OPCODES,
    R3_FUNCTS,
    REGIMM_RT,
    SHIFT_IMMEDIATE_FUNCTS,
    SHIFT_VARIABLE_FUNCTS,
    SPECIAL2_ACCUM_FUNCTS,
    TRAP_I_RT,
    TRAP_R_FUNCTS,
)
from csetty_mips.machine import Machine


def _r(rs: int, rt: int, rd: int, shamt: int, funct: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | (shamt << 6) | funct


def _i(opcode: int, rs: int, rt: int, immediate: int) -> int:
    return (opcode << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def _u32(value: int) -> int:
    return value & 0xFFFF_FFFF


def _s32(value: int) -> int:
    value &= 0xFFFF_FFFF
    return value if value < 0x8000_0000 else value - 0x1_0000_0000


def _encoding_cases() -> list[tuple[str, str, int]]:
    cases: list[tuple[str, str, int]] = []
    for name, funct in R3_FUNCTS.items():
        cases.append((name, f"{name} $s0, $t0, $t1", _r(8, 9, 16, 0, funct)))
    for name, funct in SHIFT_IMMEDIATE_FUNCTS.items():
        cases.append((name, f"{name} $s0, $t1, 4", _r(0, 9, 16, 4, funct)))
    for name, funct in SHIFT_VARIABLE_FUNCTS.items():
        cases.append((name, f"{name} $s0, $t1, $t0", _r(8, 9, 16, 0, funct)))
    for name, funct in SPECIAL2_ACCUM_FUNCTS.items():
        cases.append((name, f"{name} $t0, $t1", (0x1C << 26) | _r(8, 9, 0, 0, funct)))
    for name, funct in TRAP_R_FUNCTS.items():
        cases.append((name, f"{name} $t0, $t1", _r(8, 9, 0, 0, funct)))
    for name, opcode in I_SIGNED_OPCODES.items():
        cases.append((name, f"{name} $t1, $t0, -7", _i(opcode, 8, 9, -7)))
    for name, opcode in I_UNSIGNED_OPCODES.items():
        cases.append((name, f"{name} $t1, $t0, 0xabcd", _i(opcode, 8, 9, 0xABCD)))
    for name, opcode in BRANCH2_OPCODES.items():
        cases.append((name, f"{name} $t0, $t1, target", _i(opcode, 8, 9, 0)))
    for name, opcode in BRANCH1_OPCODES.items():
        cases.append((name, f"{name} $t0, target", _i(opcode, 8, 0, 0)))
    for name, selector in REGIMM_RT.items():
        cases.append((name, f"{name} $t0, target", _i(0x01, 8, selector, 0)))
    for name, selector in TRAP_I_RT.items():
        cases.append((name, f"{name} $t0, -7", _i(0x01, 8, selector, -7)))
    for name, opcode in MEMORY_OPCODES.items():
        cases.append((name, f"{name} $t0, -8($sp)", _i(opcode, 29, 8, -8)))
    for name, opcode in FPU_MEMORY_OPCODES.items():
        cases.append((name, f"{name} $f12, -8($sp)", _i(opcode, 29, 12, -8)))

    target = 0x0040_0004
    cases.extend(
        [
            ("j", "j target", (0x02 << 26) | (target >> 2)),
            ("jal", "jal target", (0x03 << 26) | (target >> 2)),
            ("jr", "jr $t0", _r(8, 0, 0, 0, 0x08)),
            ("jalr", "jalr $s0, $t0", _r(8, 0, 16, 0, 0x09)),
            ("movz", "movz $s0, $t0, $t1", _r(8, 9, 16, 0, 0x0A)),
            ("movn", "movn $s0, $t0, $t1", _r(8, 9, 16, 0, 0x0B)),
            ("syscall", "syscall", 0x0000_000C),
            ("break", "break", 0x0000_000D),
            ("mfhi", "mfhi $s0", _r(0, 0, 16, 0, 0x10)),
            ("mthi", "mthi $t0", _r(8, 0, 0, 0, 0x11)),
            ("mflo", "mflo $s0", _r(0, 0, 16, 0, 0x12)),
            ("mtlo", "mtlo $t0", _r(8, 0, 0, 0, 0x13)),
            ("mult", "mult $t0, $t1", _r(8, 9, 0, 0, 0x18)),
            ("multu", "multu $t0, $t1", _r(8, 9, 0, 0, 0x19)),
            ("div", "div $t0, $t1", _r(8, 9, 0, 0, 0x1A)),
            ("divu", "divu $t0, $t1", _r(8, 9, 0, 0, 0x1B)),
            ("mul", "mul $s0, $t0, $t1", (0x1C << 26) | _r(8, 9, 16, 0, 0x02)),
            ("clz", "clz $s0, $t0", (0x1C << 26) | _r(8, 0, 16, 0, 0x20)),
            ("clo", "clo $s0, $t0", (0x1C << 26) | _r(8, 0, 16, 0, 0x21)),
            ("seb", "seb $s0, $t0", (0x1F << 26) | _r(0, 8, 16, 0x10, 0x20)),
            ("seh", "seh $s0, $t0", (0x1F << 26) | _r(0, 8, 16, 0x18, 0x20)),
            ("rotr", "rotr $s0, $t1, 4", _r(1, 9, 16, 4, 0x02)),
            ("rotrv", "rotrv $s0, $t1, $t0", _r(8, 9, 16, 1, 0x06)),
            ("lui", "lui $t0, 0xabcd", _i(0x0F, 0, 8, 0xABCD)),
            ("mfc1", "mfc1 $t0, $f12", (0x11 << 26) | (8 << 16) | (12 << 11)),
            (
                "mtc1",
                "mtc1 $t0, $f12",
                (0x11 << 26) | (4 << 21) | (8 << 16) | (12 << 11),
            ),
        ]
    )
    return cases


ENCODING_CASES = _encoding_cases()


def test_encoding_table_covers_every_declared_real_instruction() -> None:
    names = [name for name, _, _ in ENCODING_CASES]
    assert len(names) == len(set(names))
    assert set(names) == set(ALL_REAL_INSTRUCTIONS)


@pytest.mark.parametrize(("name", "instruction", "expected"), ENCODING_CASES)
def test_every_real_instruction_has_the_architectural_encoding(
    name: str, instruction: str, expected: int
) -> None:
    del name
    program = assemble(
        [SourceUnit("encoding-matrix.s", f".text\nmain: {instruction}\ntarget: nop\n")]
    )
    assert program.text_words[0] == expected
    assert not disassemble(expected, program.entry).startswith(".word")


@pytest.mark.parametrize(
    "operation", ("addu", "subu", "and", "or", "xor", "nor", "slt", "sltu", "mul")
)
def test_random_binary_alu_semantics_against_an_independent_integer_oracle(
    operation: str,
) -> None:
    program = assemble([SourceUnit("alu.s", f".text\nmain: {operation} $s0, $t0, $t1\n")])
    rng = random.Random(f"csetty-mips-{operation}")
    for _ in range(128):
        left = rng.getrandbits(32)
        right = rng.getrandbits(32)
        machine = Machine(program)
        machine.write_register(8, left)
        machine.write_register(9, right)
        machine.step()
        expected = {
            "addu": _u32(left + right),
            "subu": _u32(left - right),
            "and": left & right,
            "or": left | right,
            "xor": left ^ right,
            "nor": _u32(~(left | right)),
            "slt": int(_s32(left) < _s32(right)),
            "sltu": int(left < right),
            "mul": _u32(_s32(left) * _s32(right)),
        }[operation]
        assert machine.read_register(16) == expected


@pytest.mark.parametrize("operation", ("sll", "srl", "sra", "rotr"))
@pytest.mark.parametrize("amount", (0, 1, 7, 16, 31))
def test_immediate_shift_and_rotate_semantics(operation: str, amount: int) -> None:
    program = assemble([SourceUnit("shift.s", f".text\nmain: {operation} $s0, $t0, {amount}\n")])
    value = 0x8123_4567
    machine = Machine(program)
    machine.write_register(8, value)
    machine.step()
    expected = {
        "sll": _u32(value << amount),
        "srl": value >> amount,
        "sra": _u32(_s32(value) >> amount),
        "rotr": value if amount == 0 else _u32((value >> amount) | (value << (32 - amount))),
    }[operation]
    assert machine.read_register(16) == expected


@pytest.mark.parametrize("operation", ("mult", "multu", "div", "divu"))
def test_hi_lo_arithmetic_semantics(operation: str) -> None:
    program = assemble([SourceUnit("hilo.s", f".text\nmain: {operation} $t0, $t1\n")])
    cases = ((0xFFFF_FFFE, 3), (0x8000_0000, 0xFFFF_FFFF), (17, 5))
    for left, right in cases:
        machine = Machine(program)
        machine.write_register(8, left)
        machine.write_register(9, right)
        machine.step()
        if operation == "mult":
            combined = (_s32(left) * _s32(right)) & 0xFFFF_FFFF_FFFF_FFFF
            quotient = remainder = 0
        elif operation == "multu":
            combined = left * right
            quotient = remainder = 0
        elif operation == "div":
            quotient = abs(_s32(left)) // abs(_s32(right))
            if (_s32(left) < 0) != (_s32(right) < 0):
                quotient = -quotient
            remainder = _s32(left) - quotient * _s32(right)
            combined = 0
        else:
            quotient, remainder = divmod(left, right)
            combined = 0
        if operation.startswith("mult"):
            assert machine.lo == combined & 0xFFFF_FFFF
            assert machine.hi == (combined >> 32) & 0xFFFF_FFFF
        else:
            assert machine.lo == _u32(quotient)
            assert machine.hi == _u32(remainder)


@pytest.mark.parametrize(
    ("operation", "expected"),
    (
        ("lwl", (0x11BB_CCDD, 0x2211_CCDD, 0x3322_11DD, 0x4433_2211)),
        ("lwr", (0x4433_2211, 0xAA44_3322, 0xAABB_4433, 0xAABB_CC44)),
    ),
)
def test_lwl_lwr_all_little_endian_offsets(
    operation: str, expected: tuple[int, int, int, int]
) -> None:
    for offset in range(4):
        program = assemble(
            [
                SourceUnit(
                    "unaligned-load.s",
                    ".data\nbytes: .byte 0x11, 0x22, 0x33, 0x44\n"
                    f".text\nmain: li $s0, 0xaabbccdd\n"
                    f" {operation} $s0, bytes + {offset}\n jr $ra\n",
                )
            ]
        )
        machine = Machine(program)
        machine.run()
        assert machine.read_register(16) == expected[offset]


@pytest.mark.parametrize(
    ("operation", "expected"),
    (
        (
            "swl",
            (
                b"\xaa\x22\x33\x44",
                b"\xbb\xaa\x33\x44",
                b"\xcc\xbb\xaa\x44",
                b"\xdd\xcc\xbb\xaa",
            ),
        ),
        (
            "swr",
            (
                b"\xdd\xcc\xbb\xaa",
                b"\x11\xdd\xcc\xbb",
                b"\x11\x22\xdd\xcc",
                b"\x11\x22\x33\xdd",
            ),
        ),
    ),
)
def test_swl_swr_all_little_endian_offsets(
    operation: str, expected: tuple[bytes, bytes, bytes, bytes]
) -> None:
    for offset in range(4):
        program = assemble(
            [
                SourceUnit(
                    "unaligned-store.s",
                    ".data\nbytes: .byte 0x11, 0x22, 0x33, 0x44\n"
                    f".text\nmain: li $t0, 0xaabbccdd\n"
                    f" {operation} $t0, bytes + {offset}\n jr $ra\n",
                )
            ]
        )
        machine = Machine(program)
        machine.run()
        assert machine.memory.read_bytes(program.symbols["bytes"], 4) == expected[offset]


def test_signed_overflow_and_division_by_zero_are_atomic() -> None:
    add = assemble([SourceUnit("overflow.s", ".text\nmain: add $s0, $t0, $t1\n")])
    machine = Machine(add)
    machine.write_register(8, 0x7FFF_FFFF)
    machine.write_register(9, 1)
    with pytest.raises(RuntimeFault) as overflow:
        machine.step()
    assert overflow.value.code == "R109"
    assert machine.pc == add.entry
    assert machine.read_register(16) == 0

    divide = assemble([SourceUnit("divide.s", ".text\nmain: div $t0, $t1\n")])
    machine = Machine(divide)
    machine.write_register(8, 7)
    machine.write_register(9, 0)
    with pytest.raises(RuntimeFault) as zero:
        machine.step()
    assert zero.value.code == "R108"
    assert not machine.hi_initialized
    assert not machine.lo_initialized
