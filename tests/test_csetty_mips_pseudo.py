from __future__ import annotations

import pytest

from csetty_mips import SourceUnit, assemble
from csetty_mips.errors import AssemblyError, RuntimeFault
from csetty_mips.machine import Machine


def _run(body: str) -> Machine:
    machine = Machine(assemble([SourceUnit("pseudo.s", body)]))
    machine.run()
    return machine


def test_course_stack_frame_and_immediate_mul_pseudos() -> None:
    machine = _run(
        ".text\nmain:\n"
        " begin\n push $ra\n li $a0, 21\n jal twice\n move $s0, $v0\n"
        " pop $ra\n end\n move $a0, $s0\n li $v0, 1\n syscall\n jr $ra\n"
        "twice:\n begin\n push $ra\n mul $v0, $a0, 2\n pop $ra\n end\n jr $ra\n"
    )
    assert machine.io.output == b"42"
    assert machine.read_register(29) == machine.read_register(30)


def test_immediate_branch_overloads_cover_small_and_full_width_values() -> None:
    machine = _run(
        ".text\nmain:\n"
        " li $t0, 1000000\n beq $t0, 1000000, first\n li $s0, 99\n"
        "first: bne $t0, 3, second\n li $s0, 98\n"
        "second: bge $t0, 999999, third\n li $s0, 97\n"
        "third: ble $t0, 1000000, fourth\n li $s0, 96\n"
        "fourth: bltu $zero, 0xffffffff, fifth\n li $s0, 95\n"
        "fifth: li $s0, 7\n li $v0, 10\n syscall\n"
    )
    assert machine.read_register(16) == 7


def test_set_immediate_aliases_and_rotate_pseudos() -> None:
    machine = _run(
        ".text\nmain:\n"
        " li $t0, 5\n"
        " seqi $s0, $t0, 5\n snei $s1, $t0, 6\n"
        " sgei $s2, $t0, 5\n sgti $s3, $t0, 4\n"
        " slei $s4, $t0, 5\n sgtui $s5, $t0, 4\n"
        " li $t1, 0x12345678\n li $t2, 4\n"
        " rol $s6, $t1, $t2\n ror $s7, $t1, $t2\n"
        " li $v0, 10\n syscall\n"
    )
    assert tuple(machine.read_register(index) for index in range(16, 22)) == (1, 1, 1, 1, 1, 1)
    assert machine.read_register(22) == 0x2345_6781
    assert machine.read_register(23) == 0x8123_4567


def test_symbolic_immediate_overloads_keep_two_pass_layout_stable() -> None:
    program = assemble(
        [
            SourceUnit(
                "symbolic.s",
                ".eqv SMALL, 2\n.text\nmain:\n"
                " li $t0, 2\n mul $s0, $t0, SMALL\n"
                " beq $s0, SMALL + 2, done\n li $s0, 99\n"
                "done: li $v0, 10\n syscall\n",
            )
        ]
    )
    machine = Machine(program)
    machine.run()
    assert machine.read_register(16) == 4
    assert len(program.text_words) == 10


def test_documented_symbolic_memory_address_forms() -> None:
    machine = _run(
        ".data\nvalues: .word 11, 22\ncopy: .space 8\n"
        ".text\nmain:\n"
        " lw $s0, values\n lw $s1, values + 4\n"
        " sw $s1, copy\n"
        " li $t0, -4\n lw $s2, values + 4($t0)\n"
        " la $t1, copy\n lw $s3, ($t1)\n"
        " li $v0, 10\n syscall\n"
    )
    assert tuple(machine.read_register(index) for index in range(16, 20)) == (11, 22, 11, 22)


def test_expanded_store_rejects_using_the_reserved_at_value() -> None:
    with pytest.raises(AssemblyError, match="cannot hold a value"):
        assemble(
            [
                SourceUnit(
                    "bad-at.s",
                    ".data\nvalue: .word 0\n.text\nmain: sw $at, value\n",
                )
            ]
        )


@pytest.mark.parametrize("instruction", ("tgt $t0, $t1", "tlei $t0, 5"))
def test_trap_aliases_execute_the_documented_condition(instruction: str) -> None:
    program = assemble(
        [
            SourceUnit(
                "trap-pseudo.s",
                f".text\nmain: li $t0, 5\n li $t1, 4\ntrigger: {instruction}\n",
            )
        ]
    )
    machine = Machine(program)
    with pytest.raises(RuntimeFault, match="trap condition") as caught:
        machine.run()
    assert caught.value.source is not None
    assert caught.value.source.line == 4
    assert machine.pc >= program.symbols["trigger"]
