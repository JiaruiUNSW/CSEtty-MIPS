from __future__ import annotations

import io
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from csetty_mips import SourceUnit, assemble
from csetty_mips.cli import main
from csetty_mips.debugger import Debugger
from csetty_mips.disassembler import disassemble

ROOT = Path(__file__).resolve().parents[1]


def _write_program(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


class _GuardedInputBuffer:
    def __init__(self, lines: tuple[bytes, ...] = ()) -> None:
        self.lines: Iterator[bytes] = iter(lines)
        self.readline_calls = 0

    def read(self) -> bytes:
        raise AssertionError("TTY input must not be read eagerly")

    def readline(self, _limit: int = -1) -> bytes:
        self.readline_calls += 1
        return next(self.lines, b"")


class _TTYInput:
    def __init__(self, lines: tuple[bytes, ...] = ()) -> None:
        self.buffer = _GuardedInputBuffer(lines)

    @staticmethod
    def isatty() -> bool:
        return True


class _OutputBuffer:
    def __init__(self) -> None:
        self.value = bytearray()
        self.flushes = 0

    def write(self, payload: bytes) -> int:
        self.value.extend(payload)
        return len(payload)

    def flush(self) -> None:
        self.flushes += 1


class _TTYOutput:
    def __init__(self) -> None:
        self.buffer = _OutputBuffer()

    @staticmethod
    def write(_value: str) -> int:
        raise AssertionError("program output must use the binary stream")

    @staticmethod
    def flush() -> None:
        return None


def test_cli_tty_runs_without_waiting_for_eof_and_streams_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = _write_program(
        tmp_path / "immediate.s",
        ".text\nmain: li $a0, 42\n li $v0, 1\n syscall\n li $v0, 10\n syscall\n",
    )
    stdin = _TTYInput()
    stdout = _TTYOutput()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert main([str(program)]) == 0
    assert bytes(stdout.buffer.value) == b"42"
    assert stdin.buffer.readline_calls == 0
    assert stdout.buffer.flushes >= 1


def test_cli_tty_reads_program_input_only_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = _write_program(
        tmp_path / "read.s",
        ".text\nmain: li $v0, 5\n syscall\n move $a0, $v0\n"
        " li $v0, 1\n syscall\n li $v0, 10\n syscall\n",
    )
    stdin = _TTYInput((b"-17\n",))
    stdout = _TTYOutput()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert main([str(program)]) == 0
    assert bytes(stdout.buffer.value) == b"-17"
    assert stdin.buffer.readline_calls == 1


def test_module_cli_program_arguments_trace_and_hex(tmp_path: Path) -> None:
    program = _write_program(
        tmp_path / "argc.s",
        ".text\nmain:\n"
        " li $v0, 1\n syscall\n"
        " li $a0, 124\n li $v0, 11\n syscall\n"
        " lw $a0, 0($a1)\n li $v0, 4\n syscall\n"
        " li $v0, 10\n syscall\n",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    executed = subprocess.run(
        [sys.executable, "-m", "csetty_mips", "--trace", str(program), "--", "a", "b"],
        input=b"",
        capture_output=True,
        check=False,
        env=environment,
    )
    assert executed.returncode == 0
    assert executed.stdout == b"2|a"
    assert b"argc.s:3 0x00400000" in executed.stderr

    encoded = subprocess.run(
        [sys.executable, "-m", "csetty_mips", "--hex-pad-zero", str(program)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert encoded.returncode == 0
    assert encoded.stdout.splitlines() == [
        "24020001",
        "0000000c",
        "2404007c",
        "2402000b",
        "0000000c",
        "8ca40000",
        "24020004",
        "0000000c",
        "2402000a",
        "0000000c",
    ]


def test_cli_errors_are_stable_and_have_no_traceback(tmp_path: Path) -> None:
    program = _write_program(tmp_path / "bad.s", ".text\nmain: definitely_not_mips\n")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "csetty_mips", str(program)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert result.returncode == 1
    assert "csetty-mips[A203]" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_preserves_program_output_before_a_runtime_fault(tmp_path: Path) -> None:
    program = _write_program(
        tmp_path / "partial-output.s",
        ".text\nmain:\n li $a0, 65\n li $v0, 11\n syscall\n addu $t0, $t1, $zero\n",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "csetty_mips", str(program)],
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 1
    assert result.stdout == b"A"
    assert b"csetty-mips[R100]" in result.stderr


def test_cli_reports_invalid_utf8_without_a_traceback(tmp_path: Path) -> None:
    program = tmp_path / "invalid.s"
    program.write_bytes(b".text\nmain: \xff\n")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "csetty_mips", str(program)],
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 1
    assert b"csetty-mips[I101]" in result.stderr
    assert b"Traceback" not in result.stderr


def test_cli_check_no_main_accepts_a_data_only_file(tmp_path: Path) -> None:
    program = _write_program(tmp_path / "library.s", ".data\nvalue: .word 1\n")
    assert main(["--check-no-main", str(program)]) == 0


def test_cli_usage_validation_is_consistently_exit_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    program = _write_program(tmp_path / "valid.s", ".text\nmain: jr $ra\n")
    missing_root = tmp_path / "missing"
    invalid_arguments = (
        ["--hex-pad-zero", "--check", str(program)],
        ["--interactive", "--trace", str(program)],
        ["--check", str(program), "--", "argument"],
        ["--max-steps", "0", str(program)],
        ["--history", "-1", str(program)],
        ["--history", "100001", str(program)],
        ["--fs-root", str(missing_root), str(program)],
        ["--check"],
        ["--move-label", "invalid", str(program)],
    )
    for arguments in invalid_arguments:
        with pytest.raises(SystemExit) as caught:
            main(arguments)
        assert caught.value.code == 2
        assert "csetty-mips: error:" in capsys.readouterr().err


def test_cli_move_label_step_limit_stdin_source_and_version(tmp_path: Path) -> None:
    no_main = _write_program(
        tmp_path / "moved.s",
        ".text\nstart: li $a0, 7\n li $v0, 1\n syscall\n jr $ra\n",
    )
    loop = _write_program(tmp_path / "loop.s", ".text\nmain: b main\n")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")

    moved = subprocess.run(
        [
            sys.executable,
            "-m",
            "csetty_mips",
            "--move-label",
            "main=start",
            str(no_main),
        ],
        capture_output=True,
        check=False,
        env=environment,
    )
    assert moved.returncode == 0
    assert moved.stdout == b"7"

    limited = subprocess.run(
        [sys.executable, "-m", "csetty_mips", "--max-steps", "1", str(loop)],
        capture_output=True,
        check=False,
        env=environment,
    )
    assert limited.returncode == 1
    assert b"csetty-mips[R105]" in limited.stderr

    stdin_source = subprocess.run(
        [sys.executable, "-m", "csetty_mips", "-"],
        input=b".text\nmain: li $a0, 5\n li $v0, 1\n syscall\n jr $ra\n",
        capture_output=True,
        check=False,
        env=environment,
    )
    assert stdin_source.returncode == 0
    assert stdin_source.stdout == b"5"

    version = subprocess.run(
        [sys.executable, "-m", "csetty_mips", "--version"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert version.returncode == 0
    assert version.stdout.strip() == "csetty-mips 0.1.0"


def test_debugger_break_step_reverse_and_disassemble() -> None:
    program = assemble(
        [
            SourceUnit(
                "debug.s",
                ".text\nmain: li $t0, 7\n addiu $t0, $t0, 1\n li $v0, 10\n syscall\n",
            )
        ]
    )
    commands = iter(("break main", "run", "step", "back", "context", "quit"))
    output = io.StringIO()
    debugger = Debugger(
        program,
        input_fn=lambda _prompt: next(commands),
        output=output,
    )

    assert debugger.repl() == 0
    rendered = output.getvalue()
    assert "breakpoint at 0x00400000" in rendered
    assert "li $t0, 7" in rendered
    assert debugger.machine is not None
    assert debugger.machine.pc == program.entry
    assert disassemble(program.text_words[0], program.entry) == "addiu $t0, $zero, 7"


def test_cli_relaxed_mode_uses_spim_style_zero_initialization(tmp_path: Path) -> None:
    program = _write_program(
        tmp_path / "relaxed.s",
        ".data\nhole: .space 4\n"
        ".text\nmain:\n"
        " lw $t0, hole\n addu $a0, $t0, $t1\n"
        " li $v0, 1\n syscall\n li $v0, 10\n syscall\n",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "csetty_mips", "--spim", str(program)],
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0
    assert result.stdout == b"0"
