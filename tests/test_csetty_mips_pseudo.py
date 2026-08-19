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


def test_add_and_addu_accept_immediate_overloads() -> None:
    program = assemble(
        [
            SourceUnit(
                "add-immediate.s",
                ".text\nmain:\n"
                " li $a2, 41\n"
                " add $a1, $a2, 1\n"
                " addu $s0, $a1, 0xffffffff\n"
                " jr $ra\n",
            )
        ]
    )
    machine = Machine(program)
    machine.run()

    assert machine.read_register(5) == 42
    assert machine.read_register(16) == 41
    assert program.source_map[program.entry + 4].rendered == "addiu $at, $zero, 1"
    assert program.source_map[program.entry + 8].rendered == "add $a1, $a2, $at"
    assert program.source_map[program.entry + 20].rendered == "addu $s0, $a1, $at"


def test_add_immediate_preserves_signed_overflow_semantics() -> None:
    program = assemble(
        [
            SourceUnit(
                "add-overflow.s",
                ".text\nmain:\n li $t0, 0x7fffffff\n add $t1, $t0, 1\n",
            )
        ]
    )
    machine = Machine(program)

    with pytest.raises(RuntimeFault) as caught:
        machine.run()
    assert caught.value.code == "R109"
    assert caught.value.source is not None
    assert caught.value.source.line == 4


def test_add_register_form_remains_a_real_instruction() -> None:
    program = assemble(
        [SourceUnit("add-register.s", ".text\nmain: add $a1, $a2, $a3\n")]
    )

    assert len(program.text_words) == 1
    assert program.source_map[program.entry].rendered == "add $a1, $a2, $a3"


def test_add_immediate_overload_obeys_reserved_at_and_macro_controls() -> None:
    with pytest.raises(AssemblyError) as noat:
        assemble(
            [
                SourceUnit(
                    "add-noat.s",
                    ".set noat\n.text\nmain: add $a1, $a2, 1\n",
                )
            ]
        )
    assert noat.value.code == "A241"

    with pytest.raises(AssemblyError) as collision:
        assemble(
            [SourceUnit("add-at.s", ".text\nmain: add $a1, $at, 0x10000\n")]
        )
    assert collision.value.code == "A230"

    with pytest.raises(AssemblyError) as nomacro:
        assemble(
            [
                SourceUnit(
                    "add-nomacro.s",
                    ".set nomacro\n.text\nmain: add $a1, $a2, 1\n",
                )
            ]
        )
    assert nomacro.value.code == "A240"


def test_division_result_pseudos_accept_small_and_full_width_immediate_divisors() -> None:
    machine = _run(
        ".eqv FULL_WIDTH, 0x10000\n"
        ".text\nmain:\n"
        " li $t0, -17\n"
        " div $s0, $t0, 5\n rem $s1, $t0, 5\n"
        " li $t0, 0xfffffff1\n"
        " divu $s2, $t0, 5\n remu $s3, $t0, 5\n"
        " li $t0, 0x20000\n div $s4, $t0, FULL_WIDTH\n"
        " jr $ra\n"
    )
    assert tuple(machine.read_register(index) for index in range(16, 21)) == (
        0xFFFF_FFFD,
        0xFFFF_FFFE,
        0x3333_3330,
        1,
        2,
    )


@pytest.mark.parametrize("operation", ("div", "divu", "rem", "remu"))
def test_immediate_divisor_expansion_obeys_reserved_at_controls(operation: str) -> None:
    with pytest.raises(AssemblyError) as noat:
        assemble(
            [
                SourceUnit(
                    "division-noat.s",
                    f".set noat\n.text\nmain: {operation} $s0, $t0, 2\n",
                )
            ]
        )
    assert noat.value.code == "A241"

    with pytest.raises(AssemblyError) as collision:
        assemble(
            [SourceUnit("division-at.s", f".text\nmain: {operation} $s0, $at, 2\n")]
        )
    assert collision.value.code == "A230"


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
