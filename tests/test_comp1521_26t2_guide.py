from __future__ import annotations

import pytest

from csetty_mips import SourceUnit, assemble

# One concrete assembly form for every real-instruction row in the public
# COMP1521 26T2 MIPS guide:
# https://cgi.cse.unsw.edu.au/~cs1521/26T2/resources/mips-guide.html
# Duplicate mnemonics represent distinct operand forms.
GUIDE_REAL_FORMS = (
    "add $s0, $t0, $t1",
    "addi $t1, $t0, 7",
    "addu $s0, $t0, $t1",
    "addiu $t1, $t0, 7",
    "sub $s0, $t0, $t1",
    "subu $s0, $t0, $t1",
    "mul $s0, $t0, $t1",
    "mult $t0, $t1",
    "multu $t0, $t1",
    "madd $t0, $t1",
    "maddu $t0, $t1",
    "msub $t0, $t1",
    "msubu $t0, $t1",
    "div $t0, $t1",
    "divu $t0, $t1",
    "clo $s0, $t0",
    "clz $s0, $t0",
    "seb $s0, $t0",
    "seh $s0, $t0",
    "slt $s0, $t0, $t1",
    "sltu $s0, $t0, $t1",
    "slti $t1, $t0, 7",
    "sltiu $t1, $t0, 7",
    "and $s0, $t0, $t1",
    "andi $t1, $t0, 7",
    "or $s0, $t0, $t1",
    "ori $t1, $t0, 7",
    "nor $s0, $t0, $t1",
    "xor $s0, $t0, $t1",
    "xori $t1, $t0, 7",
    "rotr $s0, $t1, 3",
    "rotrv $s0, $t1, $t0",
    "sll $s0, $t1, 3",
    "sllv $s0, $t1, $t0",
    "sra $s0, $t1, 3",
    "srav $s0, $t1, $t0",
    "srl $s0, $t1, 3",
    "srlv $s0, $t1, $t0",
    "lui $t1, 7",
    "lb $t1, 4($t2)",
    "lbu $t1, 4($t2)",
    "lh $t1, 4($t2)",
    "lhu $t1, 4($t2)",
    "lw $t1, 4($t2)",
    "sb $t1, 4($t2)",
    "sh $t1, 4($t2)",
    "sw $t1, 4($t2)",
    "mfhi $s0",
    "mflo $s0",
    "mthi $s0",
    "mtlo $s0",
    "movz $s0, $t0, $t1",
    "movn $s0, $t0, $t1",
    "beq $t0, $t1, target",
    "bne $t0, $t1, target",
    "bgez $t0, target",
    "bgtz $t0, target",
    "bltz $t0, target",
    "blez $t0, target",
    "j target",
    "jal target",
    "jr $t0",
    "jalr $t0",
    "jalr $s0, $t0",
    "syscall",
    "break",
    "teq $t0, $t1",
    "teqi $t0, 7",
    "tne $t0, $t1",
    "tnei $t0, 7",
    "tge $t0, $t1",
    "tgeu $t0, $t1",
    "tgei $t0, 7",
    "tgeiu $t0, 7",
    "tlt $t0, $t1",
    "tltu $t0, $t1",
    "tlti $t0, 7",
    "tltiu $t0, 7",
)


# One concrete assembly form for every pseudo-instruction or overload row in
# the same guide. Register and immediate overload rows are deliberately separate.
GUIDE_PSEUDO_FORMS = (
    "div $s0, $t0, $t1",
    "divu $s0, $t0, $t1",
    "rem $s0, $t0, $t1",
    "remu $s0, $t0, $t1",
    "seq $s0, $t0, $t1",
    "sne $s0, $t0, $t1",
    "sle $s0, $t0, $t1",
    "sleu $s0, $t0, $t1",
    "sgt $s0, $t0, $t1",
    "sgtu $s0, $t0, $t1",
    "sge $s0, $t0, $t1",
    "sgeu $s0, $t0, $t1",
    "abs $s0, $t0",
    "neg $s0, $t0",
    "negu $s0, $t0",
    "not $s0, $t0",
    "rol $s0, $t1, $t0",
    "ror $s0, $t1, $t0",
    "li $t1, 7",
    "la $t1, target",
    "push $t0",
    "pop $t0",
    "begin",
    "end",
    "move $t1, $t0",
    "b target",
    "beq $t0, 7, target",
    "beqz $t0, target",
    "bne $t0, 7, target",
    "bnez $t0, target",
    "bge $t0, $t1, target",
    "bge $t0, 7, target",
    "bgeu $t0, $t1, target",
    "bgeu $t0, 7, target",
    "bgt $t0, $t1, target",
    "bgt $t0, 7, target",
    "bgtu $t0, $t1, target",
    "bgtu $t0, 7, target",
    "blt $t0, $t1, target",
    "blt $t0, 7, target",
    "bltu $t0, $t1, target",
    "bltu $t0, 7, target",
    "ble $t0, $t1, target",
    "ble $t0, 7, target",
    "bleu $t0, $t1, target",
    "bleu $t0, 7, target",
    "tgt $t0, $t1",
    "tgtu $t0, $t1",
    "tgti $t0, 7",
    "tgtiu $t0, 7",
    "tle $t0, $t1",
    "tleu $t0, $t1",
    "tlei $t0, 7",
    "tleiu $t0, 7",
    "nop",
)


def test_guide_row_inventory_is_complete() -> None:
    assert len(GUIDE_REAL_FORMS) == 78
    assert len(GUIDE_PSEUDO_FORMS) == 55


@pytest.mark.parametrize("instruction", GUIDE_REAL_FORMS + GUIDE_PSEUDO_FORMS)
def test_every_comp1521_26t2_guide_instruction_form_assembles(instruction: str) -> None:
    assemble(
        [
            SourceUnit(
                "comp1521-26t2-guide.s",
                f".text\nmain: {instruction}\ntarget: nop\n",
            )
        ]
    )
