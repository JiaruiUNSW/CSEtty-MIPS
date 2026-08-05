from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from csetty_mips import Program, SourceUnit, assemble
from csetty_mips.errors import RuntimeFault
from csetty_mips.filesystem import VirtualFileSystem
from csetty_mips.integers import s32
from csetty_mips.limits import DEFAULT_LIMITS
from csetty_mips.machine import Machine

ROOT = Path(__file__).resolve().parents[1]


def _program(body: str) -> Program:
    return assemble([SourceUnit("files.s", body)])


def test_file_read_syscall_and_reverse_step_restore_cursor_and_memory() -> None:
    program = _program(
        '.data\npath: .asciiz "input.txt"\nbuffer: .space 4\n'
        ".text\nmain:\n"
        " la $a0, path\n li $a1, 0\n li $a2, 0\n li $v0, 13\n syscall\n"
        " move $s0, $v0\n move $a0, $s0\n la $a1, buffer\n li $a2, 3\n"
        " li $v0, 14\nread_call: syscall\n li $v0, 10\n syscall\n"
    )
    machine = Machine(program, initial_files={"input.txt": b"abcdef"})
    while machine.pc != program.symbols["read_call"]:
        machine.step()

    machine.step()
    buffer = program.symbols["buffer"]
    assert machine.memory.read_bytes(buffer, 3) == b"abc"
    assert machine.read_register(2) == 3
    assert dict(machine.filesystem.state.handles)[3].position == 3

    machine.reverse_step()
    assert dict(machine.filesystem.state.handles)[3].position == 0
    with pytest.raises(RuntimeFault, match="uninitialized memory"):
        machine.memory.read_bytes(buffer, 1)

    machine.step()
    assert machine.memory.read_bytes(buffer, 3) == b"abc"
    assert dict(machine.filesystem.state.handles)[3].position == 3


def test_file_write_is_staged_then_committed_atomically(tmp_path: Path) -> None:
    program = _program(
        '.data\npath: .asciiz "result.txt"\npayload: .ascii "xyz"\n'
        ".text\nmain:\n"
        " la $a0, path\n li $a1, 1\n li $a2, 0\n li $v0, 13\n syscall\n"
        " move $s0, $v0\n move $a0, $s0\n la $a1, payload\n li $a2, 3\n"
        " li $v0, 15\n syscall\n move $a0, $s0\n li $v0, 16\n syscall\n"
        " li $v0, 10\n syscall\n"
    )
    machine = Machine(program, filesystem_root=tmp_path)
    assert machine.run() == 0
    assert machine.filesystem.file_bytes("result.txt") == b"xyz"
    assert not (tmp_path / "result.txt").exists()

    assert machine.filesystem.commit() == 1
    assert (tmp_path / "result.txt").read_bytes() == b"xyz"
    assert machine.filesystem.commit() == 0


def test_posix_create_truncate_append_and_read_write_flags() -> None:
    filesystem = VirtualFileSystem(DEFAULT_LIMITS, initial_files={"item": b"abcdef"})
    descriptor = filesystem.open("item", 0o1001)
    assert descriptor == 3
    assert filesystem.write(descriptor, b"xy") == 2
    assert filesystem.close(descriptor)
    assert filesystem.file_bytes("item") == b"xy"

    descriptor = filesystem.open("item", 0o2001)
    assert filesystem.write(descriptor, b"z") == 1
    assert filesystem.close(descriptor)
    assert filesystem.file_bytes("item") == b"xyz"

    descriptor = filesystem.open("item", 2)
    assert filesystem.read(descriptor, 2) == b"xy"
    assert filesystem.write(descriptor, b"Q") == 1
    assert filesystem.file_bytes("item") == b"xyQ"

    assert filesystem.open("new", 0o101) >= 3
    assert filesystem.open("item", 0o301) == -1


def test_file_open_rejects_parent_traversal_and_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        (tmp_path / "link").symlink_to(outside, target_is_directory=True)
        for requested in ("../escape.txt", "link/escape.txt", "/absolute.txt"):
            program = _program(
                f'.data\npath: .asciiz "{requested}"\n'
                ".text\nmain:\n"
                " la $a0, path\n li $a1, 1\n li $a2, 0\n li $v0, 13\n syscall\n"
                " move $s0, $v0\n li $v0, 10\n syscall\n"
            )
            machine = Machine(program, filesystem_root=tmp_path)
            machine.run()
            assert s32(machine.read_register(16)) == -1
        assert not (outside / "escape.txt").exists()
    finally:
        outside.rmdir()


def test_cli_fs_root_commits_on_success(tmp_path: Path) -> None:
    source = tmp_path / "writer.s"
    source.write_text(
        '.data\npath: .asciiz "answer.txt"\npayload: .ascii "ok"\n'
        ".text\nmain:\n"
        " la $a0, path\n li $a1, 1\n li $a2, 0\n li $v0, 13\n syscall\n"
        " move $a0, $v0\n la $a1, payload\n li $a2, 2\n li $v0, 15\n syscall\n"
        " li $v0, 10\n syscall\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "csetty_mips", "--fs-root", str(tmp_path), str(source)],
        input=b"",
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert (tmp_path / "answer.txt").read_bytes() == b"ok"


def test_zero_length_file_io_does_not_dereference_the_buffer() -> None:
    program = assemble(
        [
            SourceUnit(
                "zero-length.s",
                ".text\nmain:\n"
                " li $a0, 0\n li $a1, 0\n li $a2, 0\n"
                " li $v0, 14\n syscall\n"
                " move $s0, $v0\n"
                " li $a0, 1\n li $a1, 0\n li $a2, 0\n"
                " li $v0, 15\n syscall\n"
                " move $s1, $v0\n"
                " li $v0, 10\n syscall\n",
            )
        ]
    )
    machine = Machine(program)
    machine.run()
    assert machine.read_register(16) == 0
    assert machine.read_register(17) == 0


def test_standard_file_descriptors_can_be_closed_and_reversed() -> None:
    program = assemble(
        [
            SourceUnit(
                "close-stdio.s",
                '.data\npayload: .ascii "A"\n'
                ".text\nmain:\n"
                " li $a0, 1\n li $v0, 16\nclose_stdout: syscall\n"
                " move $s0, $v0\n"
                " li $a0, 1\n la $a1, payload\n li $a2, 1\n li $v0, 15\n syscall\n"
                " move $s1, $v0\n"
                " li $a0, 1\n li $v0, 16\n syscall\n move $s2, $v0\n"
                " li $v0, 10\n syscall\n",
            )
        ]
    )
    machine = Machine(program)
    while machine.pc != program.symbols["close_stdout"]:
        machine.step()
    machine.step()
    assert machine.stdio_open & 0b010 == 0
    machine.reverse_step()
    assert machine.stdio_open & 0b010
    machine.run()
    assert machine.read_register(16) == 0
    assert s32(machine.read_register(17)) == -1
    assert s32(machine.read_register(18)) == -1
    assert machine.io.output == b""
