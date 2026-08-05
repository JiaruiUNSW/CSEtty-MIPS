from __future__ import annotations

from dataclasses import replace

import pytest

from csetty_mips import Program, SourceUnit, assemble
from csetty_mips.errors import RuntimeFault
from csetty_mips.limits import DEFAULT_LIMITS
from csetty_mips.machine import Machine
from csetty_mips.model import DATA_BASE


def _program(body: str) -> Program:
    return assemble([SourceUnit("syscall.s", body)])


def test_read_string_size_edges_and_remaining_input_match_fgets_style_behavior() -> None:
    program = _program(
        ".data\nzero: .space 1\none: .space 1\ntext: .space 4\n"
        ".text\nmain:\n"
        " la $a0, zero\n li $a1, 0\n li $v0, 8\n syscall\n"
        " la $a0, one\n li $a1, 1\n li $v0, 8\n syscall\n"
        " la $a0, text\n li $a1, 4\n li $v0, 8\n syscall\n"
        " li $v0, 12\n syscall\n move $s0, $v0\n"
        " li $v0, 10\n syscall\n"
    )
    machine = Machine(program, input_data=b"abcde\n")
    machine.run()
    with pytest.raises(RuntimeFault) as untouched:
        machine.memory.read_u8(program.symbols["zero"])
    assert untouched.value.code == "R205"
    assert machine.memory.read_u8(program.symbols["one"]) == 0
    assert machine.memory.read_bytes(program.symbols["text"], 4) == b"abc\0"
    assert machine.read_register(16) == ord("d")


def test_read_character_eof_and_exit2_status() -> None:
    program = _program(
        ".text\nmain:\n li $v0, 12\n syscall\n move $s0, $v0\n li $a0, -3\n li $v0, 17\n syscall\n"
    )
    machine = Machine(program)
    assert machine.run() == -3
    assert machine.read_register(16) == 0xFFFF_FFFF


def test_sbrk_returns_aligned_previous_breaks() -> None:
    program = _program(
        ".text\nmain:\n"
        " li $a0, 1\n li $v0, 9\n syscall\n move $s0, $v0\n"
        " li $a0, 1\n li $v0, 9\n syscall\n move $s1, $v0\n"
        " li $v0, 10\n syscall\n"
    )
    machine = Machine(program)
    machine.run()
    assert machine.read_register(16) == DATA_BASE
    assert machine.read_register(17) == DATA_BASE + 4
    assert machine.heap_break == DATA_BASE + 8


def test_unsupported_syscall_and_overlong_string_fail_atomically() -> None:
    unsupported = _program(".text\nmain: li $v0, 99\ncall: syscall\n")
    machine = Machine(unsupported)
    machine.step()
    before = machine.io.input_position
    with pytest.raises(RuntimeFault) as caught:
        machine.step()
    assert caught.value.code == "R307"
    assert machine.pc == unsupported.symbols["call"]
    assert machine.io.input_position == before

    overlong = _program(
        '.data\ntext: .ascii "abcd"\n.text\nmain: la $a0, text\n li $v0, 4\n syscall\n'
    )
    limits = replace(DEFAULT_LIMITS, max_string_bytes=4)
    machine = Machine(overlong, limits=limits)
    with pytest.raises(RuntimeFault) as string_error:
        machine.run()
    assert string_error.value.code == "R206"
    assert machine.io.output == b""


def test_output_limit_preserves_prior_output_when_the_next_write_fails() -> None:
    program = _program(".text\nmain:\n li $a0, 65\n li $v0, 11\n syscall\n li $a0, 66\n syscall\n")
    limits = replace(DEFAULT_LIMITS, max_output_bytes=1)
    machine = Machine(program, limits=limits)
    with pytest.raises(RuntimeFault) as caught:
        machine.run()
    assert caught.value.code == "R303"
    assert machine.io.output == b"A"


def test_failed_numeric_input_restores_the_stream_position() -> None:
    program = _program(".text\nmain: li $v0, 5\nread: syscall\n")
    machine = Machine(program, input_data=b"2147483648\n")
    machine.step()
    with pytest.raises(RuntimeFault) as caught:
        machine.step()
    assert caught.value.code == "R302"
    assert machine.pc == program.symbols["read"]
    assert machine.io.input_position == 0
