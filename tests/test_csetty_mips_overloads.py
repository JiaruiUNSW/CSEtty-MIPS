from __future__ import annotations

import pytest

from csetty_mips import Machine, SourceUnit, assemble
from csetty_mips.errors import AssemblyError

BINARY_VALUE_OPERATIONS = (
    "add",
    "addu",
    "sub",
    "subu",
    "and",
    "or",
    "xor",
    "nor",
    "slt",
    "sltu",
    "mul",
)

PAIR_VALUE_OPERATIONS = (
    "mult",
    "multu",
    "div",
    "divu",
    "tge",
    "tgeu",
    "tlt",
    "tltu",
    "teq",
    "tne",
)

RELATIONAL_BRANCHES = ("blt", "ble", "bgt", "bge", "bltu", "bleu", "bgtu", "bgeu")
RELATIONAL_SETS = ("seq", "sne", "sge", "sgt", "sle", "sgeu", "sgtu", "sleu")

BLACK_BOX_OVERLOAD_FORMS = (
    *(f"{operation} $s0, $t0, 7" for operation in BINARY_VALUE_OPERATIONS),
    *(f"{operation} $s0, 7, $t0" for operation in BINARY_VALUE_OPERATIONS),
    *(f"{operation} $s0, $t0" for operation in BINARY_VALUE_OPERATIONS),
    *(f"{operation} $s0, 7" for operation in BINARY_VALUE_OPERATIONS),
    *(f"{operation} $s0, 7" for operation in ("addi", "addiu", "andi", "ori", "xori")),
    *(f"{operation} $s0, 7" for operation in ("slti", "sltiu")),
    *(f"{operation} $t0, 7" for operation in PAIR_VALUE_OPERATIONS),
    *(f"{operation} 7, $t0" for operation in PAIR_VALUE_OPERATIONS),
    "mthi 7",
    "mtlo 7",
    *(f"{operation} $s0, 3" for operation in ("sll", "srl", "sra", "rotr")),
    *(f"{operation} $s0, $t0" for operation in ("sllv", "srlv", "srav", "rotrv")),
    *(f"{operation} $s0, 7, 3" for operation in ("sll", "srl", "sra")),
    *(f"{operation} $s0, 7, $t0" for operation in ("sllv", "srlv", "srav", "rotrv")),
    *(f"{operation} $s0" for operation in ("clz", "clo", "seb", "seh")),
    *(f"{operation} $s0" for operation in ("abs", "neg", "negu", "not")),
    "not $s0, 7",
    "beq $t0, 7, target",
    "beq 7, $t0, target",
    "bne $t0, 7, target",
    "bne 7, $t0, target",
    *(f"{operation} $t0, 7, target" for operation in RELATIONAL_BRANCHES),
    *(f"{operation} 7, $t0, target" for operation in RELATIONAL_BRANCHES),
    *(f"{operation} $s0, $t0, 7" for operation in RELATIONAL_SETS),
    *(f"{operation} $s0, 7, $t0" for operation in RELATIONAL_SETS),
    "div $s0, $t0, 7",
    "div $s0, 7, $t0",
    "rem $s0, $t0, 7",
    "rem $s0, 7, $t0",
    "remu $s0, $t0, 7",
    "remu $s0, 7, $t0",
    "rem $s0, $t0",
    "rem $s0, 7",
    "remu $s0, $t0",
    "remu $s0, 7",
    "rol $s0, $t0",
    "rol $s0, 7",
    "ror $s0, $t0",
    "ror $s0, 7",
    "la $s0, 7",
    "rol $s0, $t0, 7",
    "ror $s0, $t0, 7",
    "lw $s0, 7",
    "sw $s0, 7",
)

BLACK_BOX_REJECTED_BOUNDARIES = (
    "movz $s0, $t0, 7",
    "movn $s0, $t0, 7",
    "clz $s0, 7",
    "clo $s0, 7",
    "seb $s0, 7",
    "seh $s0, 7",
    "madd $t0, 7",
    "maddu $t0, 7",
    "msub $t0, 7",
    "msubu $t0, 7",
    "madd 7, $t0",
    "maddu 7, $t0",
    "msub 7, $t0",
    "msubu 7, $t0",
    "jr 7",
    "jalr 7",
    "beqz 7, target",
    "bnez 7, target",
    "mtc1 7, $f0",
    "mfc1 $s0, 7",
    "sw 7, 0($t0)",
    "sh 7, 0($t0)",
    "sb 7, 0($t0)",
    "sc 7, 0($t0)",
    "ulw $s0, 0($t0)",
    "usw $s0, 0($t0)",
    "ulh $s0, 0($t0)",
    "ulhu $s0, 0($t0)",
    "ush $s0, 0($t0)",
    "subi $s0, $t0, 7",
    "subiu $s0, $t0, 7",
    "tgt 7, $t0",
    "tgt $t0, 7",
    "tgtu 7, $t0",
    "tgtu $t0, 7",
    "tle 7, $t0",
    "tle $t0, 7",
    "tleu 7, $t0",
    "tleu $t0, 7",
    "sll $s0, $t0, $t1",
    "sllv $s0, $t0, 7",
    "rotr $s0, 7, 3",
)


def test_black_box_audit_inventory_is_complete() -> None:
    assert len(BLACK_BOX_OVERLOAD_FORMS) == 152
    assert len(BLACK_BOX_REJECTED_BOUNDARIES) == 42


@pytest.mark.parametrize("instruction", BLACK_BOX_OVERLOAD_FORMS)
def test_black_box_confirmed_integer_overload_forms_assemble(instruction: str) -> None:
    program = assemble(
        [SourceUnit("overload.s", f".text\nmain:\n {instruction}\ntarget:\n nop\n")]
    )
    assert program.text_words


def test_two_operand_and_immediate_overloads_execute_in_operand_order() -> None:
    machine = Machine(
        assemble(
            [
                SourceUnit(
                    "overload-semantics.s",
                    ".text\nmain:\n"
                    " li $s0, 10\n add $s0, 5\n sub $s0, 2\n and $s0, 7\n ori $s0, 8\n"
                    " li $t0, 3\n add $s1, 7, $t0\n sub $s2, 7, $t0\n"
                    " sll $s3, 3, 2\n not $s4, 0\n"
                    " mult 7, $t0\n mflo $s5\n"
                    " div 20, $t0\n mflo $s6\n"
                    " mthi 9\n mfhi $s7\n"
                    " jr $ra\n",
                )
            ]
        )
    )
    machine.run()

    assert tuple(machine.read_register(index) for index in range(16, 24)) == (
        13,
        10,
        4,
        12,
        0xFFFF_FFFF,
        21,
        6,
        9,
    )


@pytest.mark.parametrize(
    "instruction", ("divu $s0, $t0, 7", "divu $s0, 7, $t0")
)
def test_divu_result_overload_deliberately_accepts_immediates_as_a_local_extension(
    instruction: str,
) -> None:
    program = assemble([SourceUnit("divu-extension.s", f".text\nmain: {instruction}\n")])
    assert len(program.text_words) == 3


def test_left_immediate_branch_and_set_overloads_execute() -> None:
    machine = Machine(
        assemble(
            [
                SourceUnit(
                    "overload-control.s",
                    ".text\nmain:\n"
                    " li $t0, 8\n li $s0, 0\n"
                    " beq 8, $t0, equal\n li $s0, 99\n"
                    "equal: blt 7, $t0, less\n li $s0, 98\n"
                    "less: seq $s1, 8, $t0\n sgt $s2, 9, $t0\n"
                    " li $s0, 1\n jr $ra\n",
                )
            ]
        )
    )
    machine.run()

    assert tuple(machine.read_register(index) for index in range(16, 19)) == (1, 1, 1)


@pytest.mark.parametrize(
    "instruction",
    (
        "add $s0, 7, 8",
        "mult 7, 8",
        "beq 7, 8, target",
        "seq $s0, 7, 8",
        "div $s0, 7, 8",
    ),
)
def test_overloads_reject_two_immediate_source_operands(instruction: str) -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble(
            [SourceUnit("two-immediates.s", f".text\nmain:\n {instruction}\ntarget: nop\n")]
        )
    assert caught.value.code == "A242"


@pytest.mark.parametrize("instruction", BLACK_BOX_REJECTED_BOUNDARIES)
def test_black_box_rejected_boundaries_remain_assembly_errors(instruction: str) -> None:
    with pytest.raises(AssemblyError):
        assemble(
            [SourceUnit("rejected-boundary.s", f".text\nmain:\n {instruction}\ntarget: nop\n")]
        )


@pytest.mark.parametrize(
    "instruction",
    (
        "add $s0, $t0, 7",
        "mult $t0, 7",
        "beq 7, $t0, target",
        "sll $s0, 7, 3",
        "mthi 7",
    ),
)
def test_immediate_overloads_obey_noat(instruction: str) -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble(
            [
                SourceUnit(
                    "overload-noat.s",
                    f".set noat\n.text\nmain:\n {instruction}\ntarget: nop\n",
                )
            ]
        )
    assert caught.value.code == "A241"


@pytest.mark.parametrize(
    "instruction",
    (
        "add $s0, $t0",
        "addi $s0, 7",
        "sll $s0, 3",
        "clz $s0",
        "abs $s0",
    ),
)
def test_self_form_overloads_obey_nomacro(instruction: str) -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble(
            [
                SourceUnit(
                    "overload-nomacro.s",
                    f".set nomacro\n.text\nmain:\n {instruction}\n",
                )
            ]
        )
    assert caught.value.code == "A240"
