from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

from . import __version__
from .assembler import assemble
from .debugger import Debugger
from .errors import CsettyMipsError, ParseError, RuntimeFault
from .limits import DEFAULT_LIMITS
from .machine import Machine
from .model import SourceUnit


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, f"csetty-mips: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="csetty-mips",
        description="Independent educational MIPS32 assembler, simulator, and debugger",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="assemble and report errors only")
    mode.add_argument(
        "--check-no-main",
        action="store_true",
        help="assemble without requiring a main label",
    )
    mode.add_argument("--compile", action="store_true", help="assemble without running")
    mode.add_argument("--hex", action="store_true", help="print encoded text words")
    parser.add_argument(
        "--hex-pad-zero",
        action="store_true",
        help="print hexadecimal words with eight digits (implies --hex)",
    )
    parser.add_argument(
        "--move-label",
        metavar="OLD=NEW",
        action="append",
        default=[],
        help="make OLD resolve to the address of NEW",
    )
    parser.add_argument("--trace", action="store_true", help="trace each executed instruction")
    parser.add_argument("--interactive", "-i", action="store_true", help="open the debugger")
    parser.add_argument("--max-steps", type=int, help="maximum executed instruction count")
    parser.add_argument("--history", type=int, help="maximum reverse-execution records")
    parser.add_argument(
        "--fs-root",
        type=Path,
        metavar="DIR",
        help="enable sandboxed file syscalls below DIR and commit on exit status 0",
    )
    parser.add_argument(
        "--relaxed",
        "--spim",
        action="store_true",
        help="use SPIM-style zero values for uninitialized registers and memory",
    )
    parser.add_argument("--version", action="version", version=f"csetty-mips {__version__}")
    parser.add_argument("files", nargs="*", metavar="FILE")
    return parser


def _split_program_arguments(arguments: list[str]) -> tuple[list[str], tuple[str, ...]]:
    if "--" not in arguments:
        return arguments, ()
    separator = arguments.index("--")
    return arguments[:separator], tuple(arguments[separator + 1 :])


def _move_labels(values: list[str], parser: argparse.ArgumentParser) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            parser.error(f"--move-label must have OLD=NEW form: {value!r}")
        old, new = value.split("=", 1)
        if not old or not new:
            parser.error(f"--move-label must have non-empty names: {value!r}")
        result[old] = new
    return result


def _read_sources(files: list[str], limit: int) -> list[SourceUnit]:
    result: list[SourceUnit] = []
    total = 0
    for filename in files:
        remaining = limit - total
        if filename == "-":
            payload = sys.stdin.buffer.read(remaining + 1)
            source_name = "<stdin>"
        else:
            with Path(filename).open("rb") as source_file:
                payload = source_file.read(remaining + 1)
            source_name = filename
        total += len(payload)
        if total > limit:
            raise ParseError("P100", f"source input is larger than the {limit} byte limit")
        result.append(SourceUnit(source_name, payload.decode("utf-8")))
    return result


def _terminal_input() -> bytes:
    return sys.stdin.buffer.readline(DEFAULT_LIMITS.max_input_bytes + 1)


def _terminal_output(payload: bytes) -> None:
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _buffered_input(limit: int) -> bytes:
    payload = sys.stdin.buffer.read(limit + 1)
    if len(payload) > limit:
        raise RuntimeFault("R311", f"program input exceeds {limit} bytes")
    return payload


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    option_arguments, program_arguments = _split_program_arguments(raw_arguments)
    parser = _parser()
    options = parser.parse_args(option_arguments)
    if options.hex_pad_zero and any((options.check, options.check_no_main, options.compile)):
        parser.error("--hex-pad-zero cannot be combined with another assembly mode")
    if options.hex_pad_zero:
        options.hex = True
    if options.interactive and any(
        (options.check, options.check_no_main, options.compile, options.hex, options.trace)
    ):
        parser.error("--interactive cannot be combined with another execution mode")
    if program_arguments and any(
        (options.check, options.check_no_main, options.compile, options.hex)
    ):
        parser.error("program arguments are only valid when executing a program")
    if options.max_steps is not None and options.max_steps <= 0:
        parser.error("--max-steps must be positive")
    if options.history is not None and options.history < 0:
        parser.error("--history cannot be negative")
    if options.history is not None and options.history > 100_000:
        parser.error("--history cannot exceed 100000 records")
    if options.fs_root is not None and not options.fs_root.is_dir():
        parser.error("--fs-root must name an existing directory")

    limits = DEFAULT_LIMITS
    if options.max_steps is not None:
        limits = replace(limits, max_steps=options.max_steps)
    if options.history is not None:
        limits = replace(limits, max_history=options.history)

    try:
        if not options.files:
            if any(
                (
                    options.check,
                    options.check_no_main,
                    options.compile,
                    options.hex,
                    options.trace,
                )
            ):
                parser.error("this mode requires at least one source file")
            return Debugger(
                limits=limits,
                output=sys.stdout,
                filesystem_root=options.fs_root,
                strict_initialization=not options.relaxed,
            ).repl()

        sources = _read_sources(options.files, limits.max_source_bytes)
        program = assemble(
            sources,
            require_main=not options.check_no_main,
            move_labels=_move_labels(options.move_label, parser),
            limits=limits,
        )
        if options.check or options.check_no_main or options.compile:
            return 0
        if options.hex:
            for word in program.text_words:
                print(f"{word:08x}" if options.hex_pad_zero else f"{word:x}")
            return 0

        # Match the course runner: arguments after ``--`` are installed as the
        # complete simulated argv.  Source filenames are assembler inputs, not
        # an implicit argv[0].
        runtime_argv = program_arguments
        if options.interactive:
            return Debugger(
                program,
                argv=runtime_argv,
                limits=limits,
                output=sys.stdout,
                filesystem_root=options.fs_root,
                strict_initialization=not options.relaxed,
            ).repl()

        interactive_input = "-" not in options.files and sys.stdin.isatty()
        input_data = (
            b""
            if interactive_input or "-" in options.files
            else _buffered_input(limits.max_input_bytes)
        )
        machine = Machine(
            program,
            argv=runtime_argv,
            input_data=input_data,
            input_provider=_terminal_input if interactive_input else None,
            output_sink=_terminal_output,
            limits=limits,
            history_limit=0 if options.history is None else options.history,
            filesystem_root=options.fs_root,
            strict_initialization=not options.relaxed,
        )
        if options.trace:
            while not machine.exited:
                entry = program.source_map.get(machine.pc)
                if entry is None:
                    trace = f"0x{machine.pc:08x}"
                else:
                    trace = (
                        f"{entry.source.filename}:{entry.source.line} "
                        f"0x{machine.pc:08x} {entry.rendered}"
                    )
                print(trace, file=sys.stderr)
                machine.step()
            status = machine.exit_status
        else:
            status = machine.run()
        if status == 0 and options.fs_root is not None:
            machine.filesystem.commit()
        return status & 0xFF
    except CsettyMipsError as error:
        print(error.render(), file=sys.stderr)
        return 1
    except OSError as error:
        print(f"csetty-mips[I100]: {error}", file=sys.stderr)
        return 1
    except UnicodeError as error:
        print(f"csetty-mips[I101]: source is not valid UTF-8: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("csetty-mips: interrupted", file=sys.stderr)
        return 130
