from __future__ import annotations

import pytest

from csetty_mips import Program, SourceUnit, assemble
from csetty_mips.errors import RuntimeFault
from csetty_mips.machine import Machine


def _program(body: str) -> Program:
    return assemble([SourceUnit("semantics-matrix.s", body)])


def test_integer_immediate_variable_shift_move_and_count_semantics() -> None:
    program = _program(
        ".text\nmain:\n"
        " li $t0, 0x80000001\n li $t1, 36\n"
        " sllv $s0, $t0, $t1\n srlv $s1, $t0, $t1\n"
        " srav $s2, $t0, $t1\n rotrv $s3, $t0, $t1\n"
        " li $t2, -1\n slti $s4, $t2, 0\n sltiu $s5, $zero, -1\n"
        " andi $s6, $t0, 0xff\n ori $s7, $zero, 0xabcd\n"
        " xori $t3, $s7, 0xffff\n clz $t4, $t0\n clo $t5, $t2\n"
        " movz $t6, $t0, $zero\n movn $t7, $t1, $t0\n"
        " li $t8, 7\n li $t9, 5\n add $k0, $t8, $t9\n"
        " sub $k1, $t8, $t9\n addi $gp, $t8, -2\n jr $ra\n"
    )
    machine = Machine(program)
    machine.run()

    assert tuple(machine.read_register(index) for index in range(16, 24)) == (
        0x0000_0010,
        0x0800_0000,
        0xF800_0000,
        0x1800_0000,
        1,
        1,
        1,
        0x0000_ABCD,
    )
    assert machine.read_register(11) == 0x5432
    assert machine.read_register(12) == 0
    assert machine.read_register(13) == 32
    assert machine.read_register(14) == 0x8000_0001
    assert machine.read_register(15) == 36
    assert machine.read_register(26) == 12
    assert machine.read_register(27) == 2
    assert machine.read_register(28) == 5


def test_accumulate_and_explicit_hi_lo_move_semantics() -> None:
    program = _program(
        ".text\nmain:\n"
        " li $t0, -1\n li $t1, 2\n mthi $zero\n mtlo $zero\n"
        " maddu $t0, $t1\n mfhi $s0\n mflo $s1\n"
        " msubu $t0, $t1\n mfhi $s2\n mflo $s3\n"
        " madd $t0, $t1\n mfhi $s4\n mflo $s5\n"
        " msub $t0, $t1\n mfhi $s6\n mflo $s7\n"
        " mthi $t0\n mtlo $t1\n mfhi $t2\n mflo $t3\n jr $ra\n"
    )
    machine = Machine(program)
    machine.run()

    assert tuple(machine.read_register(index) for index in range(16, 24)) == (
        1,
        0xFFFF_FFFE,
        0,
        0,
        0xFFFF_FFFF,
        0xFFFF_FFFE,
        0,
        0,
    )
    assert machine.read_register(10) == 0xFFFF_FFFF
    assert machine.read_register(11) == 2


def test_signed_load_store_and_successful_ll_sc_semantics() -> None:
    program = _program(
        ".data\n"
        "bytes: .byte -1, 0x80\n"
        ".align 1\nhalf: .half 0x8001\n"
        "word: .word 0x12345678\n"
        "out: .space 8\n"
        "atom: .word 5\n"
        ".text\nmain:\n"
        " lb $s0, bytes\n lbu $s1, bytes\n"
        " lb $s2, bytes + 1\n lbu $s3, bytes + 1\n"
        " lh $s4, half\n lhu $s5, half\n lw $s6, word\n"
        " li $t0, 0xa1b2c3d4\n"
        " sb $t0, out\n sb $zero, out + 1\n sh $t0, out + 2\n sw $t0, out + 4\n"
        " ll $t1, atom\n addiu $t1, $t1, 1\n sc $t1, atom\n"
        " move $s7, $t1\n lw $t2, atom\n jr $ra\n"
    )
    machine = Machine(program)
    machine.run()

    assert tuple(machine.read_register(index) for index in range(16, 23)) == (
        0xFFFF_FFFF,
        0x0000_00FF,
        0xFFFF_FF80,
        0x0000_0080,
        0xFFFF_8001,
        0x0000_8001,
        0x1234_5678,
    )
    assert machine.memory.read_bytes(program.symbols["out"], 8) == bytes.fromhex("d400d4c3d4c3b2a1")
    assert machine.read_register(23) == 1
    assert machine.read_register(10) == 6


@pytest.mark.parametrize(
    ("instruction", "left", "right", "taken"),
    (
        ("beq $t0, $t1, target", 5, 5, True),
        ("beq $t0, $t1, target", 5, 6, False),
        ("bne $t0, $t1, target", 5, 6, True),
        ("bne $t0, $t1, target", 5, 5, False),
        ("blez $t0, target", 0, 0, True),
        ("blez $t0, target", 1, 0, False),
        ("bgtz $t0, target", 1, 0, True),
        ("bgtz $t0, target", 0, 0, False),
        ("bltz $t0, target", -1, 0, True),
        ("bltz $t0, target", 0, 0, False),
        ("bgez $t0, target", 0, 0, True),
        ("bgez $t0, target", -1, 0, False),
        ("bltzal $t0, target", -1, 0, True),
        ("bltzal $t0, target", 0, 0, False),
        ("bgezal $t0, target", 0, 0, True),
        ("bgezal $t0, target", -1, 0, False),
    ),
)
def test_real_branch_taken_and_fallthrough_semantics(
    instruction: str, left: int, right: int, taken: bool
) -> None:
    program = _program(
        f".text\nmain:\n li $t0, {left}\n li $t1, {right}\n"
        f"branch: {instruction}\nfallthrough: nop\ntarget: jr $ra\n"
    )
    machine = Machine(program)
    while machine.pc != program.symbols["branch"]:
        machine.step()
    machine.step()

    expected = program.symbols["target"] if taken else program.symbols["fallthrough"]
    assert machine.pc == expected
    if instruction.startswith(("bltzal", "bgezal")):
        assert machine.read_register(31) == program.symbols["branch"] + 4


def test_jump_jal_and_both_jalr_forms_write_the_no_delay_slot_link() -> None:
    direct = _program(
        ".text\nmain: j direct_target\n break\n"
        "direct_target: jal subroutine\n after_jal: jr $ra\n"
        "subroutine: jr $ra\n"
    )
    machine = Machine(direct)
    machine.step()
    assert machine.pc == direct.symbols["direct_target"]
    machine.step()
    assert machine.pc == direct.symbols["subroutine"]
    assert machine.read_register(31) == direct.symbols["after_jal"]

    indirect = _program(
        ".text\nmain:\n la $t0, target\n"
        "custom_link: jalr $s0, $t0\n break\n"
        "target: la $t1, finish\n default_link: jalr $t1\n break\n"
        "finish: jr $ra\n"
    )
    machine = Machine(indirect)
    while machine.pc != indirect.symbols["custom_link"]:
        machine.step()
    machine.step()
    assert machine.pc == indirect.symbols["target"]
    assert machine.read_register(16) == indirect.symbols["custom_link"] + 4
    while machine.pc != indirect.symbols["default_link"]:
        machine.step()
    machine.step()
    assert machine.pc == indirect.symbols["finish"]
    assert machine.read_register(31) == indirect.symbols["default_link"] + 4


@pytest.mark.parametrize(
    "instruction",
    (
        "teq $t0, $t2",
        "tne $t0, $t1",
        "tge $t0, $t2",
        "tgeu $t0, $t2",
        "tlt $t2, $t0",
        "tltu $t2, $t0",
        "teqi $t0, 6",
        "tnei $t0, 5",
        "tgei $t0, 6",
        "tgeiu $t0, 6",
        "tlti $t0, 5",
        "tltiu $t0, 5",
    ),
)
def test_false_real_trap_conditions_continue_execution(instruction: str) -> None:
    program = _program(
        f".text\nmain:\n li $t0, 5\n li $t1, 5\n li $t2, 6\n {instruction}\n jr $ra\n"
    )
    assert Machine(program).run() == 0


def test_break_fault_is_source_linked_and_atomic() -> None:
    program = _program(".text\nmain: li $s0, 7\nstop: break 123\n")
    machine = Machine(program)
    machine.step()
    with pytest.raises(RuntimeFault) as caught:
        machine.step()
    assert caught.value.code == "R107"
    assert machine.pc == program.symbols["stop"]
    assert machine.read_register(16) == 7
