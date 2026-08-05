from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest

from csetty_mips import SourceUnit, assemble
from csetty_mips.debugger import Debugger
from csetty_mips.limits import DEFAULT_LIMITS


def test_scripted_debugger_exercises_break_watch_inspect_and_reverse_commands() -> None:
    program = assemble(
        [
            SourceUnit(
                "debug.s",
                ".data\n"
                "value: .word 1\n"
                ".text\n"
                "main:\n"
                " li $t0, 7\n"
                "store: sw $t0, value\n"
                " mult $t0, $t0\n"
                " mflo $s0\n"
                " mtc1 $t0, $f0\n"
                " li $a0, 65\n"
                " li $v0, 11\n"
                " syscall\n"
                " li $v0, 10\n"
                " syscall\n",
            )
        ]
    )
    commands = iter(
        (
            "break debug.s:6",
            "breaks",
            "watch $t0",
            "run",
            "unwatch $t0",
            "watch value",
            "continue",
            "unwatch value",
            "delete store",
            "step",
            "print hi",
            "print lo + 1",
            "step",
            "watch $f0",
            "step",
            "unwatch $f0",
            "registers",
            "fregisters",
            "examine value 1",
            "disassemble main 4",
            "context",
            "labels",
            "continue",
            "output",
            "back 3",
            "output",
            "delete all",
            "reset",
            "x value",
            "help",
            "definitely-not-a-command",
            "quit",
        )
    )
    output = io.StringIO()
    debugger = Debugger(program, input_fn=lambda _prompt: next(commands), output=output)

    assert debugger.repl() == 0
    rendered = output.getvalue()
    assert "breakpoint set at 0x" in rendered
    assert "watchpoint: $t0 changed" in rendered
    assert "watchpoint: memory 0x10000000 changed" in rendered
    assert "50 (0x00000032)" in rendered
    assert "watchpoint: $f0 changed" in rendered
    assert "$f0 =0x00000007" in rendered
    assert "0x10000000: 0x00000007" in rendered
    assert "sw $t0, 0($at)" in rendered
    assert "0x10000000 value" in rendered
    assert "program exited with status 0" in rendered
    assert "[program output was rewound]" in rendered
    assert "commands:" in rendered
    assert "unknown debugger command 'definitely-not-a-command'" in rendered


def test_debugger_without_a_program_can_recover_from_errors_and_load_a_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "loaded program.s"
    source.write_text(".text\nmain: li $v0, 10\n syscall\n", encoding="utf-8")
    commands = iter(("context", f'load "{source}"', "labels", "run", "quit"))
    output = io.StringIO()
    debugger = Debugger(input_fn=lambda _prompt: next(commands), output=output)

    assert debugger.repl() == 0
    rendered = output.getvalue()
    assert "csetty-mips[D100]: no program is loaded" in rendered
    assert "loaded 2 instruction words" in rendered
    assert "main" in rendered
    assert "program exited with status 0" in rendered


def test_debugger_load_enforces_source_size_and_utf8_then_recovers(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.s"
    oversized.write_bytes(b"x" * 65)
    invalid = tmp_path / "invalid.s"
    invalid.write_bytes(b".text\nmain: \xff\n")
    valid = tmp_path / "valid.s"
    valid.write_text(".text\nmain: li $v0, 10\n syscall\n", encoding="utf-8")
    commands = iter((f'load "{oversized}"', f'load "{invalid}"', f'load "{valid}"', "quit"))
    output = io.StringIO()
    debugger = Debugger(
        limits=replace(DEFAULT_LIMITS, max_source_bytes=64),
        input_fn=lambda _prompt: next(commands),
        output=output,
    )

    assert debugger.repl() == 0
    rendered = output.getvalue()
    assert "csetty-mips[P100]" in rendered
    assert "csetty-mips[P110]" in rendered
    assert "loaded 2 instruction words" in rendered


def test_committing_debugger_files_clears_irreversible_history(tmp_path: Path) -> None:
    program = assemble(
        [
            SourceUnit(
                "commit.s",
                '.data\npath: .asciiz "result.txt"\npayload: .ascii "ok"\n'
                ".text\nmain:\n"
                " la $a0, path\n li $a1, 1\n li $a2, 0\n li $v0, 13\n syscall\n"
                " move $a0, $v0\n la $a1, payload\n li $a2, 2\n li $v0, 15\n syscall\n"
                " li $v0, 10\n syscall\n",
            )
        ]
    )
    commands = iter(("run", "commit-files", "back", "quit"))
    output = io.StringIO()
    debugger = Debugger(
        program,
        input_fn=lambda _prompt: next(commands),
        output=output,
        filesystem_root=tmp_path,
    )

    assert debugger.repl() == 0
    assert (tmp_path / "result.txt").read_bytes() == b"ok"
    rendered = output.getvalue()
    assert "committed 1 file(s)" in rendered
    assert "no recorded instruction is available to reverse" in rendered


def test_a_failed_host_commit_still_clears_irreversible_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = assemble([SourceUnit("commit-failure.s", ".text\nmain: nop\n jr $ra\n")])
    debugger = Debugger(program, output=io.StringIO(), filesystem_root=tmp_path)
    assert debugger.machine is not None
    debugger.machine.step()
    assert debugger.machine.history

    def fail_commit() -> int:
        raise OSError("simulated host commit failure")

    monkeypatch.setattr(debugger.machine.filesystem, "commit", fail_commit)
    with pytest.raises(OSError, match="simulated host commit failure"):
        debugger._execute_command("commit-files")
    assert not debugger.machine.history
