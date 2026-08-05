from __future__ import annotations

import struct

import pytest

from csetty_mips import SourceUnit, assemble
from csetty_mips.disassembler import disassemble
from csetty_mips.errors import AssemblyError, RuntimeFault
from csetty_mips.machine import Machine


@pytest.mark.parametrize(
    ("instruction", "word", "rendered"),
    (
        ("madd $t0, $t1", 0x7109_0000, "madd $t0, $t1"),
        ("maddu $t0, $t1", 0x7109_0001, "maddu $t0, $t1"),
        ("msub $t0, $t1", 0x7109_0004, "msub $t0, $t1"),
        ("msubu $t0, $t1", 0x7109_0005, "msubu $t0, $t1"),
        ("seb $t0, $t1", 0x7C09_4420, "seb $t0, $t1"),
        ("seh $t0, $t1", 0x7C09_4620, "seh $t0, $t1"),
        ("rotr $t0, $t1, 4", 0x0029_4102, "rotr $t0, $t1, 4"),
        ("rotrv $t0, $t1, $t2", 0x0149_4046, "rotrv $t0, $t1, $t2"),
        ("teq $t0, $t1", 0x0109_0034, "teq $t0, $t1"),
        ("tne $t0, $t1, 7", 0x0109_01F6, "tne $t0, $t1, 7"),
        ("teqi $t0, -1", 0x050C_FFFF, "teqi $t0, -1"),
        ("tltiu $t0, 9", 0x050B_0009, "tltiu $t0, 9"),
        ("mfc1 $t0, $f12", 0x4408_6000, "mfc1 $t0, $f12"),
        ("mtc1 $t0, $f12", 0x4488_6000, "mtc1 $t0, $f12"),
        ("lwc1 $f12, 0($sp)", 0xC7AC_0000, "lwc1 $f12, 0($sp)"),
        ("ldc1 $f12, 0($sp)", 0xD7AC_0000, "ldc1 $f12, 0($sp)"),
        ("swc1 $f12, 0($sp)", 0xE7AC_0000, "swc1 $f12, 0($sp)"),
        ("sdc1 $f12, 0($sp)", 0xF7AC_0000, "sdc1 $f12, 0($sp)"),
    ),
)
def test_release2_and_trap_encodings(instruction: str, word: int, rendered: str) -> None:
    program = assemble(
        [SourceUnit("encoding.s", f".text\nmain: {instruction}\n li $v0, 10\n syscall\n")]
    )
    assert program.text_words[0] == word
    assert disassemble(word, program.text_base) == rendered


def test_accumulate_sign_extend_and_rotate_semantics() -> None:
    program = assemble(
        [
            SourceUnit(
                "semantics.s",
                ".text\nmain:\n"
                " li $t0, -2\n li $t1, 3\n mult $t0, $t1\n"
                " li $t2, 4\n li $t3, 5\n madd $t2, $t3\n"
                " mfhi $s0\n mflo $s1\n msub $t2, $t3\n mfhi $s2\n mflo $s3\n"
                " li $t4, 0x80\n seb $s4, $t4\n"
                " li $t5, 0x8001\n seh $s5, $t5\n"
                " li $t6, 0x12345678\n rotr $s6, $t6, 8\n"
                " li $t7, 4\n rotrv $s7, $t6, $t7\n"
                " li $v0, 10\n syscall\n",
            )
        ]
    )
    machine = Machine(program)
    machine.run()
    assert machine.read_register(16) == 0
    assert machine.read_register(17) == 14
    assert machine.read_register(18) == 0xFFFF_FFFF
    assert machine.read_register(19) == 0xFFFF_FFFA
    assert machine.read_register(20) == 0xFFFF_FF80
    assert machine.read_register(21) == 0xFFFF_8001
    assert machine.read_register(22) == 0x7812_3456
    assert machine.read_register(23) == 0x8123_4567


@pytest.mark.parametrize(
    "trap",
    (
        "teq $t0, $t1",
        "tne $t0, $zero",
        "tge $t0, $t1",
        "tltu $zero, $t0",
        "teqi $t0, 5",
        "tnei $t0, 6",
        "tgeiu $t0, 5",
        "tlti $t0, 6",
    ),
)
def test_true_trap_condition_is_source_linked_and_atomic(trap: str) -> None:
    program = assemble(
        [
            SourceUnit(
                "trap.s",
                f".text\nmain: li $t0, 5\n li $t1, 5\ntrigger: {trap}\n li $v0, 10\n syscall\n",
            )
        ]
    )
    machine = Machine(program)
    with pytest.raises(RuntimeFault) as caught:
        machine.run()
    assert caught.value.code == "R116"
    assert caught.value.source is not None
    assert caught.value.source.filename == "trap.s"
    assert machine.pc == program.symbols["trigger"]


def test_float_and_double_load_store_transfer_and_print_syscalls() -> None:
    program = assemble(
        [
            SourceUnit(
                "float.s",
                ".data\n"
                "single: .float 1.25\n"
                ".align 3\n"
                "double: .double -3.5\n"
                ".align 3\n"
                "copy: .space 8\n"
                ".text\nmain:\n"
                " lwc1 $f12, single\n"
                " mfc1 $t0, $f12\n"
                " mtc1 $t0, $f14\n"
                " swc1 $f14, copy\n"
                " li $v0, 2\n syscall\n"
                " li $a0, 124\n li $v0, 11\n syscall\n"
                " ldc1 $f12, double\n"
                " sdc1 $f12, copy\n"
                " li $v0, 3\n syscall\n"
                " li $v0, 10\n syscall\n",
            )
        ]
    )
    machine = Machine(program)
    machine.run()
    assert machine.io.output == b"1.25000000|-3.5"
    assert machine.memory.read_bytes(program.symbols["copy"], 8, alignment=8) == struct.pack(
        "<d", -3.5
    )


def test_float_input_syscalls_are_reversible_and_use_fpu_result_registers() -> None:
    program = assemble(
        [
            SourceUnit(
                "read-float.s",
                ".text\nmain:\n"
                " li $v0, 6\n"
                "read_single: syscall\n"
                " mfc1 $t0, $f0\n"
                " mtc1 $t0, $f12\n"
                " li $v0, 2\n syscall\n"
                " li $a0, 124\n li $v0, 11\n syscall\n"
                " li $v0, 7\n syscall\n"
                " mfc1 $t0, $f0\n mfc1 $t1, $f1\n"
                " mtc1 $t0, $f12\n mtc1 $t1, $f13\n"
                " li $v0, 3\n syscall\n"
                " li $v0, 10\n syscall\n",
            )
        ]
    )
    machine = Machine(program, input_data=b"2.5 -7.125\n")
    machine.step()
    assert machine.pc == program.symbols["read_single"]
    machine.step()
    assert machine.read_fpu_register(0) == struct.unpack("<I", struct.pack("<f", 2.5))[0]
    assert machine.io.input_position > 0
    machine.reverse_step()
    assert machine.io.input_position == 0
    assert machine.initialized_fpu_registers == 0
    machine.run()
    assert machine.io.output == b"2.50000000|-7.125"


@pytest.mark.parametrize("instruction", ("ldc1 $f3, 0($sp)", "sdc1 $f31, 0($sp)"))
def test_double_memory_instructions_require_an_even_fpu_pair(instruction: str) -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble([SourceUnit("bad-pair.s", f".text\nmain: {instruction}\n")])
    assert caught.value.code == "A232"
