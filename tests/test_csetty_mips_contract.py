from __future__ import annotations

import io
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from csetty_mips import SourceUnit, assemble
from csetty_mips.debugger import Debugger
from csetty_mips.disassembler import disassemble
from csetty_mips.errors import AssemblyError, ParseError, RuntimeFault, SourceRef
from csetty_mips.expression import evaluate
from csetty_mips.filesystem import VirtualFileSystem
from csetty_mips.limits import DEFAULT_LIMITS
from csetty_mips.machine import Machine
from csetty_mips.memory import PAGE_SIZE
from csetty_mips.model import DATA_BASE, DATA_INITIAL_BYTES
from csetty_mips.parser import parse_sources


def _unit(body: str, filename: str = "contract.s") -> SourceUnit:
    return SourceUnit(filename, body)


def test_check_no_main_accepts_a_data_only_translation_unit() -> None:
    program = assemble([_unit(".data\nitem: .word 7\n")], require_main=False)
    assert program.text_words == ()
    assert program.entry == program.text_base
    assert program.symbols["item"] == DATA_BASE


def test_api_source_that_cannot_be_encoded_as_utf8_has_a_stable_diagnostic() -> None:
    with pytest.raises(ParseError) as caught:
        assemble([_unit(".text\nmain: \ud800\n")])
    assert caught.value.code == "P110"


def test_api_program_argument_that_is_not_utf8_has_a_stable_diagnostic() -> None:
    program = assemble([_unit(".text\nmain: jr $ra\n")])
    with pytest.raises(RuntimeFault) as caught:
        Machine(program, argv=("program", "\ud800"))
    assert caught.value.code == "R313"


def test_each_source_file_starts_in_text_with_fresh_assembler_settings() -> None:
    program = assemble(
        [
            _unit(".set noat\n.data\nitem: .word 1\n", "data.s"),
            _unit(
                "main: li $t0, 0\n bge $t0, $zero, done\ndone: li $v0, 10\n syscall\n",
                "main.s",
            ),
        ]
    )
    assert Machine(program).run() == 0


def test_set_noat_nomacro_and_setting_stack_have_enforced_semantics() -> None:
    assemble(
        [_unit(".set noat\n.set nomacro\n.text\nmain:\n addiu $t0, $zero, 1\n lw $t1, 0($sp)\n")]
    )
    with pytest.raises(AssemblyError) as no_macro:
        assemble([_unit(".set nomacro\n.text\nmain: move $t0, $zero\n")])
    assert no_macro.value.code == "A240"

    with pytest.raises(AssemblyError) as no_at:
        assemble([_unit(".set noat\n.text\nmain: blt $t0, $t1, main\n")])
    assert no_at.value.code == "A241"

    with pytest.raises(AssemblyError) as restored:
        assemble(
            [_unit(".set noat\n.set push\n.set at\n.set pop\n.text\nmain: seq $t0, $t1, $t2\n")]
        )
    assert restored.value.code == "A241"


@pytest.mark.parametrize(
    "instruction",
    (
        "mul $s0, $at, 100000",
        "beq $at, 100000, target",
        "bge $at, 100000, target",
        "seqi $s0, $at, 100000",
        "rol $s0, $at, $t0",
        "tgti $at, 100000",
    ),
)
def test_macro_expansion_never_silently_clobbers_an_at_input(instruction: str) -> None:
    with pytest.raises(AssemblyError) as caught:
        assemble([_unit(f".text\nmain: {instruction}\ntarget: nop\n")])
    assert caught.value.code == "A230"


def test_direct_absolute_65535_is_not_encoded_as_a_negative_offset() -> None:
    program = assemble([_unit(".text\nmain: lw $t0, 65535\n li $v0, 10\n syscall\n")])
    assert program.text_words[:2] == (0x3401_FFFF, 0x8C28_0000)


def test_branch_and_link_writes_ra_even_when_the_branch_is_not_taken() -> None:
    program = assemble(
        [
            _unit(
                ".text\nmain:\n"
                " li $t0, -1\n"
                "first_link: bltzal $t0, first_taken\n"
                "first_taken: move $s0, $ra\n"
                " li $t1, -1\n"
                "second_link: bgezal $t1, should_not_run\n"
                " move $s1, $ra\n"
                " li $v0, 10\n syscall\n"
                "should_not_run: break\n"
            )
        ]
    )
    machine = Machine(program)
    machine.run()
    assert machine.read_register(16) == program.symbols["first_link"] + 4
    assert machine.read_register(17) == program.symbols["second_link"] + 4


def test_sbrk_mapping_and_reverse_step_restore_the_data_segment_boundary() -> None:
    program = assemble(
        [
            _unit(
                ".text\nmain:\n"
                f" li $a0, {DATA_INITIAL_BYTES + 4}\n"
                " li $v0, 9\n"
                "grow: syscall\n"
                " li $v0, 10\n syscall\n"
            )
        ]
    )
    machine = Machine(program)
    while machine.pc != program.symbols["grow"]:
        machine.step()
    assert machine.memory.data_end == DATA_BASE + DATA_INITIAL_BYTES
    machine.step()
    selected = DATA_BASE + DATA_INITIAL_BYTES
    machine.memory.write_u8(selected, 1)
    machine.reverse_step()
    assert machine.memory.data_end == DATA_BASE + DATA_INITIAL_BYTES
    with pytest.raises(RuntimeFault) as caught:
        machine.memory.read_u8(selected)
    assert caught.value.code == "R202"


def test_failed_sc_still_validates_its_target_address() -> None:
    program = assemble([_unit(".text\nmain: li $t0, 1\n li $t1, 7\n sc $t1, 0($t0)\n")])
    with pytest.raises(RuntimeFault) as caught:
        Machine(program).run()
    assert caught.value.code == "R204"


def test_a_syscall_memory_write_invalidates_an_ll_sc_reservation() -> None:
    program = assemble(
        [
            _unit(
                ".data\nvalue: .word 9\nbuffer: .space 2\n"
                ".text\nmain:\n"
                " ll $t0, value\n"
                " la $a0, buffer\n li $a1, 2\n li $v0, 8\n syscall\n"
                " sc $t0, value\n move $s0, $t0\n"
                " li $v0, 10\n syscall\n"
            )
        ]
    )
    machine = Machine(program, input_data=b"x\n")
    machine.run()
    assert machine.read_register(16) == 0
    assert machine.memory.read_u32(program.symbols["value"]) == 9


def test_reserved_instruction_fields_are_not_executed_as_a_valid_opcode() -> None:
    malformed_sll = 0x0020_0000
    program = assemble(
        [_unit(f".text\nmain: .word 0x{malformed_sll:08x}\n li $v0, 10\n syscall\n")]
    )
    assert disassemble(malformed_sll, program.entry) == ".word 0x00200000"
    with pytest.raises(RuntimeFault) as caught:
        Machine(program).step()
    assert caught.value.code == "R121"


def test_atol_style_integer_tokens_accept_prefixes_and_return_zero_for_no_conversion() -> None:
    program = assemble(
        [
            _unit(
                ".text\nmain:\n"
                " li $v0, 5\n syscall\n move $s0, $v0\n"
                " li $v0, 5\n syscall\n move $s1, $v0\n"
                " li $v0, 5\n syscall\n move $s2, $v0\n"
                " li $v0, 10\n syscall\n"
            )
        ]
    )
    machine = Machine(program, input_data=b"-12junk nope 7\n")
    machine.run()
    assert tuple(machine.read_register(index) for index in range(16, 19)) == (
        0xFFFF_FFF4,
        0,
        7,
    )


def test_atof_style_float_tokens_accept_prefixes_and_return_zero_for_no_conversion() -> None:
    program = assemble(
        [
            _unit(
                ".text\nmain:\n"
                " li $v0, 6\n syscall\n mfc1 $s0, $f0\n"
                " li $v0, 6\n syscall\n mfc1 $s1, $f0\n"
                " li $v0, 6\n syscall\n mfc1 $s2, $f0\n"
                " li $v0, 10\n syscall\n"
            )
        ]
    )
    machine = Machine(program, input_data=b"2.5junk bad -1e2x\n")
    machine.run()
    expected = (
        struct.unpack("<I", struct.pack("<f", 2.5))[0],
        0,
        struct.unpack("<I", struct.pack("<f", -100.0))[0],
    )
    assert tuple(machine.read_register(index) for index in range(16, 19)) == expected


def test_input_expression_and_statement_limits_fail_with_stable_errors() -> None:
    tiny_input = replace(DEFAULT_LIMITS, max_input_bytes=3)
    program = assemble([_unit(".text\nmain: li $v0, 10\n syscall\n")])
    with pytest.raises(RuntimeFault) as input_error:
        Machine(program, input_data=b"four", limits=tiny_input)
    assert input_error.value.code == "R311"

    ref = SourceRef("expr.s", 1, 1, "")
    with pytest.raises(AssemblyError) as nesting:
        evaluate("(" * 300 + "1" + ")" * 300, {}, ref)
    assert nesting.value.code == "A109"
    with pytest.raises(AssemblyError) as tokens:
        evaluate(" + ".join("1" for _ in range(5000)), {}, ref)
    assert tokens.value.code == "A109"
    with pytest.raises(AssemblyError, match="shift count exceeds"):
        evaluate("1 << 1000001", {}, ref)
    assert evaluate("1 + 2 * 3 == 7 && !0", {}, ref) == 1
    assert evaluate("0 || 3 < 2 | 1", {}, ref) == 1
    assert evaluate("0 && (1 / 0)", {}, ref) == 0
    assert evaluate("1 || (1 << 1000001)", {}, ref) == 1

    with pytest.raises(AssemblyError) as alignment:
        assemble([_unit(".data\n.align -1\n.text\nmain: nop\n")])
    assert alignment.value.code == "A204"

    statement_limit = replace(DEFAULT_LIMITS, max_statements=1)
    with pytest.raises(ParseError) as statements:
        parse_sources([_unit("one:\ntwo:\n")], limits=statement_limit)
    assert statements.value.code == "P107"


def test_a_failed_cross_page_write_is_atomic_and_releases_new_pages() -> None:
    limits = replace(DEFAULT_LIMITS, max_memory_pages=3)
    program = assemble([_unit(".text\nmain: li $v0, 10\n syscall\n")], limits=limits)
    machine = Machine(program, limits=limits)
    address = DATA_BASE + PAGE_SIZE - 1

    with pytest.raises(RuntimeFault) as caught:
        machine.memory.write_bytes(address, b"xy")
    assert caught.value.code == "R203"
    with pytest.raises(RuntimeFault) as uninitialized:
        machine.memory.read_u8(address)
    assert uninitialized.value.code == "R205"

    machine.memory.write_u8(DATA_BASE + 2 * PAGE_SIZE, 1)


def test_reverse_step_releases_pages_allocated_by_the_reversed_store() -> None:
    limits = replace(DEFAULT_LIMITS, max_memory_pages=3)
    program = assemble(
        [
            _unit(
                ".data\nhole: .space 4\n"
                ".text\nmain:\n"
                " li $t0, 7\n lui $t1, 0x1000\n store: sw $t0, 0($t1)\n"
            )
        ],
        limits=limits,
    )
    machine = Machine(program, limits=limits)
    machine.step()
    machine.step()
    machine.step()
    assert machine.memory.read_u32(DATA_BASE) == 7

    machine.reverse_step()
    with pytest.raises(RuntimeFault) as uninitialized:
        machine.memory.read_u32(DATA_BASE)
    assert uninitialized.value.code == "R205"
    machine.memory.write_u8(DATA_BASE + PAGE_SIZE, 1)


def test_virtual_filesystem_enforces_total_host_file_and_utf8_path_limits(
    tmp_path: Path,
) -> None:
    (tmp_path / "one").write_bytes(b"12")
    (tmp_path / "two").write_bytes(b"34")
    limits = replace(
        DEFAULT_LIMITS,
        max_file_bytes=10,
        max_total_file_bytes=3,
        max_path_bytes=4,
    )
    filesystem = VirtualFileSystem(limits, root=tmp_path)
    assert filesystem.open("one", 0) == 3
    assert filesystem.open("two", 0) == -1
    assert filesystem.open("abcde", 0) == -1


def test_debugger_supports_fpu_watchpoints_and_register_expressions() -> None:
    program = assemble([_unit(".text\nmain:\n li $t0, 7\n mtc1 $t0, $f0\n li $v0, 10\n syscall\n")])
    commands = iter(("watch $f0", "run", "print $t0 + 1", "quit"))
    output = io.StringIO()
    debugger = Debugger(program, input_fn=lambda _prompt: next(commands), output=output)
    assert debugger.repl() == 0
    rendered = output.getvalue()
    assert "watchpoint: $f0 changed" in rendered
    assert "8 (0x00000008)" in rendered
