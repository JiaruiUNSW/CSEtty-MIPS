"""Original layout/encoding/runtime regressions; no coursework source is included."""
from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from csetty_mips import DEFAULT_LIMITS, Machine, SourceUnit, assemble
from csetty_mips.errors import AssemblyError, RuntimeFault


@pytest.mark.parametrize("section", [".data", ".kdata"])
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize(("directive", "offset"), [
    (".align 0", 3), (".align 1", 4), (".align 2", 4), (".align 3", 8),
    (".align 4", 16), (".balign 1", 3), (".balign 2", 4), (".balign 8", 8),
])
def test_explicit_alignment_binds_labels_to_the_aligned_cursor(
    section: str, inline: bool, directive: str, offset: int,
) -> None:
    separator = " " if inline else "\n# labels can precede padding\n\n"
    source = f"{section}\nbase: .byte 1,2,3\nslot:{separator}{directive}\n.space 4\n"
    program = assemble([SourceUnit("align.s", source)], require_main=False)
    assert program.symbols["slot"] - program.symbols["base"] == offset
    assert program.symbols["base"] == (
        program.data_base if section == ".data" else program.kdata_base
    )


@pytest.mark.parametrize("section", [".data", ".kdata"])
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize(("directive", "offset", "expected"), [
    (".half 0x1234", 4, b"\x34\x12"),
    (".word 0x12345678", 4, b"\x78\x56\x34\x12"),
    (".float 1.5", 4, struct.pack("<f", 1.5)),
    (".double 1.5", 8, struct.pack("<d", 1.5)),
])
def test_auto_alignment_moves_all_aliases_and_emits_data_at_the_same_address(
    section: str, inline: bool, directive: str, offset: int, expected: bytes,
) -> None:
    separator = " " if inline else "\n"
    source = f"{section}\nbase: .byte 1,2,3\nfirst:\nsecond:{separator}{directive}\n"
    program = assemble([SourceUnit("auto.s", source)], require_main=False)
    assert program.symbols["first"] == program.symbols["second"]
    assert program.symbols["second"] == program.symbols["base"] + offset
    data = program.data if section == ".data" else program.kdata
    initialized = program.data_initialized if section == ".data" else program.kdata_initialized
    assert data[offset:offset + len(expected)] == expected
    assert initialized[3:offset] == bytes(offset - 3)
    assert initialized[offset:offset + len(expected)] == b"\x01" * len(expected)


@pytest.mark.parametrize("intervening", [
    "", ".space 0\n", '.ascii ""\n', ".align 0\n", ".globl first\n",
    ".data\n", ".text\nnop\n.data\n", ".kdata\n.byte 1\n.data\n", ".set noat\n",
])
def test_zero_sized_statements_and_section_round_trips_keep_data_aliases_pending(
    intervening: str,
) -> None:
    program = assemble([SourceUnit("pending.s", ".data\nbase: .byte 1,2,3\nfirst:\n"
        + intervening + ".align 2\nsecond:\n.align 3\n.space 8\n")], require_main=False)
    assert program.symbols["first"] == program.symbols["second"] == program.data_base + 8
    assert program.symbols["base"] == program.data_base


@pytest.mark.parametrize("object_directive", [".byte 9", ".space 1", '.asciiz ""'])
def test_nonempty_objects_commit_labels_before_later_padding(object_directive: str) -> None:
    program = assemble([SourceUnit("objects.s", ".data\nbase: .byte 1,2,3\n"
        f"object: {object_directive}\nnext:\n.align 3\n.space 1\n")], require_main=False)
    assert program.symbols["object"] == program.data_base + 3
    assert program.symbols["next"] == program.data_base + 8


def test_align_zero_keeps_automatic_typed_data_alignment_enabled() -> None:
    program = assemble([SourceUnit("zero.s", ".data\n.byte 1,2,3\n.align 0\n"
        "a:\n.word 7\n.byte 1,2,3\n.align 0\n.data\nb:\n.word 8\n")],
        require_main=False)
    assert program.symbols["a"] == program.data_base + 4
    assert program.symbols["b"] == program.data_base + 12


def test_constant_snapshots_are_not_relocated_along_with_labels() -> None:
    program = assemble([SourceUnit("constants.s", ".data\nbase: .byte 1,2,3\nv:\n"
        "CAPTURE = v\nOFFSET = v - base\n.align 2\n.word v, CAPTURE, OFFSET\n")],
        require_main=False)
    assert program.symbols["v"] == program.data_base + 4
    assert program.symbols["CAPTURE"] == program.data_base + 3
    assert program.symbols["OFFSET"] == 3
    assert struct.unpack("<III", program.data[4:16]) == (
        program.data_base + 4, program.data_base + 3, 3,
    )


def test_global_alias_relocation_is_visible_from_other_translation_units() -> None:
    program = assemble([
        SourceUnit("storage.s", ".data\n.byte 1,2,3\n.globl value, alias\n"
                   "value:\nalias:\n.align 2\n.word 0x12345678\n"),
        SourceUnit("main.s", ".text\nmain: lw $s0, value\nlw $s1, alias\njr $ra\n"),
    ])
    machine = Machine(program)
    machine.run()
    assert program.symbols["value"] == program.symbols["alias"] == program.data_base + 4
    assert machine.read_register(16) == machine.read_register(17) == 0x12345678


def test_file_boundary_does_not_move_another_units_dangling_end_label() -> None:
    program = assemble([
        SourceUnit("first.s", ".data\n.byte 1,2,3\n.globl end\nend:\n"),
        SourceUnit("second.s", ".data\n.align 2\nnext: .word 7\n"),
    ], require_main=False)
    assert program.symbols["end"] == program.data_base + 3
    assert program.symbols["next"] == program.data_base + 4


def test_explicit_origin_is_not_padding_for_old_labels() -> None:
    program = assemble([SourceUnit("origin.s", ".data\n.byte 1,2,3\nold_end:\n"
        ".data 0x10000021\nnew:\n.align 2\n.word 7\n")], require_main=False)
    assert program.symbols["old_end"] == program.data_base + 3
    assert program.symbols["new"] == program.data_base + 36


@pytest.mark.parametrize("section", [".text", ".ktext"])
def test_text_label_points_after_alignment_not_at_padding(section: str) -> None:
    source = f"{section}\nbase: nop\ntarget:\n.align 4\nli $s0,7\njr $ra\n"
    source += ".text\nmain: li $v0,10\nsyscall\n" if section == ".ktext" else ""
    program = assemble([SourceUnit("text.s", source)], require_main=False)
    assert program.symbols["target"] - program.symbols["base"] == 16
    assert program.symbols["target"] in program.source_map


def test_runtime_uses_aligned_symbol_and_reverse_undoes_the_store() -> None:
    program = assemble([SourceUnit("store.s", ".data\npad: .byte 1,2,3\nslot:\n"
        ".align 2\n.space 4\n.text\nmain:\nla $t0,slot\nli $t1,7\nsw $t1,0($t0)\n"
        "lw $a0,0($t0)\nli $v0,1\nsyscall\nli $v0,10\nsyscall\n")])
    machine = Machine(program)
    machine.run()
    assert bytes(machine.io.output) == b"7"
    assert machine.memory.read_u32(program.symbols["slot"]) == 7
    while machine.history:
        machine.reverse_step()
    assert bytes(machine.io.output) == b""
    with pytest.raises(RuntimeFault) as uninitialized:
        machine.memory.read_u32(program.symbols["slot"])
    assert uninitialized.value.code != "R204"


def test_deliberately_unaligned_word_access_still_faults() -> None:
    program = assemble([SourceUnit("bad_store.s", ".data\n.byte 1\nslot: .space 4\n"
        ".text\nmain: la $t0,slot\nli $t1,7\nsw $t1,0($t0)\njr $ra\n")])
    with pytest.raises(RuntimeFault) as fault:
        Machine(program).run()
    assert fault.value.code == "R204"


@pytest.mark.parametrize("directive", [".align -1", ".align 21", ".balign 0", ".balign 3"])
def test_invalid_alignment_is_still_rejected(directive: str) -> None:
    with pytest.raises(AssemblyError) as error:
        assemble([SourceUnit("invalid.s", f".data\nslot:\n{directive}\n.space 4\n")],
                 require_main=False)
    assert error.value.code == "A204"


def test_alignment_padding_counts_toward_section_limits() -> None:
    with pytest.raises(AssemblyError) as error:
        assemble([SourceUnit("bounded.s", ".data\n.byte 1,2,3\nslot:\n.align 2\n")],
                 limits=replace(DEFAULT_LIMITS, max_data_bytes=3), require_main=False)
    assert error.value.code == "A217"


def test_alias_relocation_does_not_bypass_duplicate_or_symbol_limit_checks() -> None:
    with pytest.raises(AssemblyError) as duplicate:
        assemble([SourceUnit("duplicate.s", ".data\nslot:\n.align 2\nslot: .space 4\n")],
                 require_main=False)
    assert duplicate.value.code == "A211"
    with pytest.raises(AssemblyError) as limit:
        assemble([SourceUnit("symbols.s", ".data\na:\nb:\n.align 2\n.space 4\n")],
                 limits=replace(DEFAULT_LIMITS, max_symbols=1), require_main=False)
    assert limit.value.code == "A212"
