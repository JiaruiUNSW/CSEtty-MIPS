from __future__ import annotations

import pytest

from csetty_mips import SourceUnit, assemble
from csetty_mips.errors import AssemblyError, ParseError, RuntimeFault, SourceRef
from csetty_mips.expression import evaluate
from csetty_mips.integers import s32, sign_extend, u32
from csetty_mips.machine import Machine
from csetty_mips.parser import parse_sources


def source(text: str) -> SourceUnit:
    return SourceUnit("test.s", text)


def run(text: str, input_data: bytes = b"") -> Machine:
    machine = Machine(assemble([source(text)]), input_data=input_data)
    machine.run()
    return machine


def test_integer_helpers_are_explicitly_32_bit() -> None:
    assert u32(-1) == 0xFFFF_FFFF
    assert s32(0xFFFF_FFFF) == -1
    assert sign_extend(0x8000, 16) == -32768


def test_expression_precedence_symbols_and_hi_lo() -> None:
    ref = SourceRef("test.s", 1, 1, "value")
    assert evaluate("1 + 2 * 3 << 2", {}, ref) == 28
    assert evaluate("%hi(label) | %lo(label)", {"label": 0x1234_5678}, ref) == 0x1234 | 0x5678
    assert evaluate("-7 / 3", {}, ref) == -2
    assert evaluate("-7 % 3", {}, ref) == -1


def test_parser_preserves_hash_and_commas_inside_string() -> None:
    statements = parse_sources([source('.data\nmsg: .asciiz "a,#;b" # comment\n')])
    assert statements[1].labels == ("msg",)
    assert statements[1].operation == ".asciiz"
    assert statements[1].operands == ('"a,#;b"',)


def test_parser_reports_unbalanced_memory_operand() -> None:
    with pytest.raises(ParseError, match="unclosed parenthesis"):
        parse_sources([source("main: lw $t0, 4($sp\n")])


def test_course_style_constant_assignment_and_legacy_octal_literal() -> None:
    statements = parse_sources([source("ANSWER = 070 + 7\n")])
    assert statements[0].operation == ".equ"
    assert statements[0].operands == ("ANSWER", "070 + 7")
    program = assemble(
        [source("ANSWER = 070 + 7\n.text\nmain: li $s0, ANSWER\n li $v0, 10\n syscall\n")]
    )
    machine = Machine(program)
    machine.run()
    assert machine.read_register(16) == 63


def test_invalid_legacy_octal_literal_has_an_assembly_diagnostic() -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble([source("VALUE = 089\n.text\nmain: nop\n")])
    assert caught.value.code == "A108"


def test_assembler_emits_real_words_and_source_map() -> None:
    program = assemble([source(".text\nmain: li $v0, 10\n syscall\n")])
    assert program.text_words == (0x2402_000A, 0x0000_000C)
    assert program.source_map[program.entry].rendered == "addiu $v0, $zero, 10"


def test_multiple_files_have_local_symbols_and_explicit_global_linkage() -> None:
    program = assemble(
        [
            SourceUnit(
                "main.s",
                ".text\nmain:\n"
                " li $a0, 1\n jal helper\n"
                " move $a0, $v0\n li $v0, 1\n syscall\n"
                " li $v0, 10\n syscall\n"
                "local_loop: b local_loop\n",
            ),
            SourceUnit(
                "helper.s",
                ".text\n.globl helper\nhelper:\n"
                " addiu $v0, $a0, 41\n jr $ra\n"
                "local_loop: b local_loop\n",
            ),
        ]
    )
    machine = Machine(program)
    machine.run()
    assert machine.io.output == b"42"
    assert "helper" in program.symbols
    assert "local_loop" not in program.symbols
    assert "main.s::local_loop" in program.symbols
    assert "helper.s::local_loop" in program.symbols


def test_cross_file_reference_requires_the_definition_to_be_global() -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble(
            [
                SourceUnit("main.s", ".text\nmain: jal hidden\n"),
                SourceUnit("helper.s", ".text\nhidden: jr $ra\n"),
            ]
        )
    assert caught.value.code == "A104"


def test_duplicate_global_definitions_are_rejected() -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble(
            [
                SourceUnit("one.s", ".text\n.globl shared\nshared: nop\nmain: nop\n"),
                SourceUnit("two.s", ".text\n.globl shared\nshared: nop\n"),
            ]
        )
    assert caught.value.code == "A235"


def test_symbolic_li_keeps_first_and_second_pass_sizes_equal() -> None:
    program = assemble(
        [source(".eqv SMALL, 7\n.text\nmain: li $t0, SMALL\n li $v0, 10\n syscall\n")]
    )
    assert program.text_words[:2] == (0x3C08_0000, 0x3508_0007)


def test_signed_immediate_accepts_an_explicit_16_bit_pattern() -> None:
    program = assemble([source(".text\nmain: addiu $t0, $zero, 0xffff\n li $v0, 10\n syscall\n")])
    assert program.text_words[0] == 0x2408_FFFF


def test_data_directives_and_label_address() -> None:
    program = assemble(
        [
            source(
                '.data\nvalue: .word 0x12345678\nmsg: .asciiz "ok"\n'
                ".text\nmain: la $t0, value\n li $v0, 10\n syscall\n"
            )
        ]
    )
    assert program.data[:7] == b"xV4\x12ok\0"
    assert program.data_initialized[:7] == b"\x01" * 7
    assert program.data_base == 0x1000_0000
    assert program.symbols["msg"] == program.data_base + 4


def test_kernel_sections_are_emitted_but_protected_from_user_execution() -> None:
    program = assemble(
        [
            source(
                ".kdata\nsecret: .word 0x12345678\n"
                ".ktext\nhandler: addiu $k0, $zero, 7\n"
                ".text\nmain: lw $t0, secret\n"
            )
        ]
    )
    assert program.symbols["secret"] == 0x9000_0000
    assert program.kdata == b"xV4\x12"
    assert program.symbols["handler"] == 0x8000_0000
    assert program.ktext_words == (0x241A_0007,)
    with pytest.raises(RuntimeFault) as caught:
        Machine(program).run()
    assert caught.value.code == "R207"
    assert "protected kernel data" in caught.value.message


def test_kernel_text_cannot_be_selected_as_the_user_entry_point() -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble([source(".ktext\nmain: nop\n")])
    assert caught.value.code == "A229"


def test_data_directives_are_automatically_aligned_without_double_padding() -> None:
    program = assemble(
        [
            source(
                ".data\n"
                "first: .byte 1\n"
                "half: .half 0x2233\n"
                "word: .word 0x44556677\n"
                "double: .double 1.5\n"
                ".text\nmain: li $v0, 10\n syscall\n"
            )
        ]
    )
    assert program.symbols["first"] == program.data_base
    assert program.symbols["half"] == program.data_base + 2
    assert program.symbols["word"] == program.data_base + 4
    assert program.symbols["double"] == program.data_base + 8
    assert len(program.data) == 16
    assert program.data_initialized[0] == 1
    assert program.data_initialized[1] == 0
    assert program.data_initialized[2:] == b"\x01" * 14


def test_explicit_alignment_only_inserts_the_required_padding_once() -> None:
    program = assemble(
        [source(".data\n.byte 1\n.align 2\naligned: .byte 2\n.text\nmain: li $v0, 10\n syscall\n")]
    )
    assert program.symbols["aligned"] == program.data_base + 4
    assert len(program.data) == 5


def test_space_bytes_are_uninitialized_until_written() -> None:
    program = assemble([source(".data\nhole: .space 4\n.text\nmain: lw $t0, hole\n")])
    assert program.data == b"\0\0\0\0"
    assert program.data_initialized == b"\0\0\0\0"
    with pytest.raises(RuntimeFault) as caught:
        Machine(program).run()
    assert caught.value.code == "R205"


def test_unknown_instruction_has_original_diagnostic() -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble([source(".text\nmain: ad $t0, $t1, $t2\n")])
    assert caught.value.code == "A203"
    assert "did you mean 'add'?" in caught.value.render()


def test_arithmetic_branches_and_syscalls() -> None:
    machine = run(
        ".text\n"
        "main:\n"
        " li $t0, 1\n"
        " li $t1, 6\n"
        " li $a0, 0\n"
        "loop:\n"
        " add $a0, $a0, $t0\n"
        " addi $t0, $t0, 1\n"
        " blt $t0, $t1, loop\n"
        " li $v0, 1\n"
        " syscall\n"
        " li $v0, 10\n"
        " syscall\n"
    )
    assert machine.io.output == b"15"


def test_recursive_stack_program_executes_encoded_loads_and_stores() -> None:
    machine = run(
        ".text\n"
        "main:\n"
        " li $a0, 5\n"
        " jal fact\n"
        " move $a0, $v0\n"
        " li $v0, 1\n"
        " syscall\n"
        " li $v0, 10\n"
        " syscall\n"
        "fact:\n"
        " addi $sp, $sp, -8\n"
        " sw $ra, 4($sp)\n"
        " sw $a0, 0($sp)\n"
        " slti $t0, $a0, 2\n"
        " bnez $t0, base\n"
        " addi $a0, $a0, -1\n"
        " jal fact\n"
        " lw $t1, 0($sp)\n"
        " mul $v0, $v0, $t1\n"
        " b done\n"
        "base: li $v0, 1\n"
        "done:\n"
        " lw $ra, 4($sp)\n"
        " addi $sp, $sp, 8\n"
        " jr $ra\n"
    )
    assert machine.io.output == b"120"


def test_text_memory_is_writable_and_self_modified_code_is_executed() -> None:
    machine = run(
        ".text\n"
        "main:\n"
        " la $t0, target\n"
        " li $t1, 0x2402000a\n"
        " sw $t1, 0($t0)\n"
        " j target\n"
        "target: break\n"
        " syscall\n"
    )
    assert machine.exit_status == 0
    assert machine.memory.read_u32(machine.program.symbols["target"]) == 0x2402_000A


def test_sbrk_is_bounded_by_the_one_mib_data_segment() -> None:
    program = assemble([source(".text\nmain:\n li $a0, 0x100001\n li $v0, 9\n syscall\n")])
    with pytest.raises(RuntimeFault) as caught:
        Machine(program).run()
    assert caught.value.code == "R305"


def test_uninitialized_register_is_a_runtime_fault() -> None:
    program = assemble([source(".text\nmain: add $t0, $t1, $t2\n")])
    with pytest.raises(RuntimeFault) as caught:
        Machine(program).step()
    assert caught.value.code == "R100"
    assert "uninitialized register" in caught.value.render()


def test_callee_saved_registers_have_stable_entry_values_for_abi_save_restore() -> None:
    machine = run(
        ".text\nmain:\n"
        " addiu $sp, $sp, -4\n"
        " sw $s3, 0($sp)\n"
        " li $s3, 99\n"
        " lw $s3, 0($sp)\n"
        " addiu $sp, $sp, 4\n"
        " li $v0, 10\n syscall\n"
    )
    assert machine.read_register(19) == 0


def test_reverse_step_restores_register_memory_input_and_output() -> None:
    program = assemble(
        [
            source(
                ".text\nmain:\n"
                " li $t0, 7\n"
                " addi $sp, $sp, -4\n"
                " sw $t0, 0($sp)\n"
                " li $a0, 65\n"
                " li $v0, 11\n"
                " syscall\n"
                " li $v0, 10\n"
                " syscall\n"
            )
        ]
    )
    machine = Machine(program)
    machine.run()
    assert machine.io.output == b"A"
    for _ in range(3):
        machine.reverse_step()
    assert machine.io.output == b""
    assert not machine.exited
    for _ in range(3):
        machine.reverse_step()
    with pytest.raises(RuntimeFault):
        machine.memory.read_u32(machine.read_register(29))
