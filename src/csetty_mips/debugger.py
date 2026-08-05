from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from .assembler import assemble
from .disassembler import disassemble
from .errors import CsettyMipsError, ParseError, RuntimeFault, SourceRef
from .expression import evaluate
from .integers import s32
from .isa import parse_fpu_register, parse_register, register_name
from .limits import DEFAULT_LIMITS, Limits
from .machine import Machine, StepRecord
from .model import Program, SourceUnit

_HELP = """commands:
  load FILE...             assemble and load source files
  run                      reset and run from main
  continue | c             continue execution
  step [N] | s [N]         execute N instructions (default 1)
  back [N]                 reverse N recorded instructions
  break TARGET             set breakpoint at label/address/file:line
  delete TARGET|all        remove a breakpoint
  breaks                   list breakpoints
  watch $REG|$fN|ADDRESS   stop when a register or memory byte changes
  unwatch TARGET|all       remove a watchpoint
  print EXPR               print register, symbol, address, HI, LO, or PC
  registers                print all registers
  fregisters               print all floating-point registers
  examine ADDRESS [COUNT]  print memory words
  disassemble [ADDR] [N]   decode instructions
  context                  show current source and instruction
  labels                   list program labels
  output                   show buffered program output
  commit-files             commit staged files below the configured --fs-root
  reset                    restore initial machine state
  help                     show this help
  quit | exit              leave the debugger
"""


class Debugger:
    def __init__(
        self,
        program: Program | None = None,
        *,
        argv: tuple[str, ...] = ("program",),
        limits: Limits = DEFAULT_LIMITS,
        input_fn: Callable[[str], str] = input,
        output: TextIO,
        filesystem_root: Path | None = None,
        strict_initialization: bool = True,
    ) -> None:
        self.program = program
        self.argv = argv
        self.limits = limits
        self.input_fn = input_fn
        self.output = output
        self.filesystem_root = filesystem_root
        self.strict_initialization = strict_initialization
        self.machine: Machine | None = None
        self.breakpoints: set[int] = set()
        self.watch_registers: set[int] = set()
        self.watch_fpu_registers: set[int] = set()
        self.watch_addresses: set[int] = set()
        self._shown_output = 0
        if program is not None:
            self.reset()

    def _program_input(self) -> bytes:
        try:
            return (self.input_fn("program input> ") + "\n").encode()
        except EOFError:
            return b""

    def reset(self) -> None:
        if self.program is None:
            raise RuntimeFault("D100", "no program is loaded")
        self.machine = Machine(
            self.program,
            argv=self.argv,
            limits=self.limits,
            input_provider=self._program_input,
            filesystem_root=self.filesystem_root,
            strict_initialization=self.strict_initialization,
        )
        self._shown_output = 0

    def _require_machine(self) -> Machine:
        if self.machine is None:
            raise RuntimeFault("D100", "no program is loaded")
        return self.machine

    def _read_source_units(self, paths: Sequence[Path]) -> list[SourceUnit]:
        units: list[SourceUnit] = []
        total = 0
        for path in paths:
            remaining = self.limits.max_source_bytes - total
            with path.open("rb") as source_file:
                payload = source_file.read(remaining + 1)
            total += len(payload)
            if total > self.limits.max_source_bytes:
                raise ParseError(
                    "P100",
                    f"source input is larger than the {self.limits.max_source_bytes} byte limit",
                )
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ParseError("P110", f"{path}: source is not valid UTF-8: {error}") from error
            units.append(SourceUnit(str(path), text))
        return units

    def _resolve_target(self, text: str) -> int:
        program = self.program
        if program is None:
            raise RuntimeFault("D100", "no program is loaded")
        if text in program.symbols:
            return program.symbols[text]
        if ":" in text:
            filename, line_text = text.rsplit(":", 1)
            try:
                line = int(line_text)
            except ValueError:
                pass
            else:
                matches = [
                    address
                    for address, entry in program.source_map.items()
                    if Path(entry.source.filename).name == Path(filename).name
                    and entry.source.line == line
                ]
                if matches:
                    return min(matches)
        try:
            return int(text, 0) & 0xFFFF_FFFF
        except ValueError as error:
            raise RuntimeFault("D101", f"unknown label or address {text!r}") from error

    def _flush_program_output(self) -> None:
        machine = self._require_machine()
        if len(machine.io.output) < self._shown_output:
            self._shown_output = len(machine.io.output)
            self.output.write("[program output was rewound]\n")
        if len(machine.io.output) > self._shown_output:
            payload = machine.io.output[self._shown_output :].decode("utf-8", errors="replace")
            self.output.write(payload)
            self._shown_output = len(machine.io.output)

    def _watch_trigger(self, record: StepRecord) -> str | None:
        machine = self._require_machine()
        for index in sorted(self.watch_registers):
            old_initialized = bool(record.initialized_registers & (1 << index))
            new_initialized = bool(machine.initialized_registers & (1 << index))
            if (
                old_initialized != new_initialized
                or record.registers[index] != machine.registers[index]
            ):
                return f"watchpoint: {register_name(index)} changed"
        for index in sorted(self.watch_fpu_registers):
            old_initialized = bool(record.initialized_fpu_registers & (1 << index))
            new_initialized = bool(machine.initialized_fpu_registers & (1 << index))
            if (
                old_initialized != new_initialized
                or record.fpu_registers[index] != machine.fpu_registers[index]
            ):
                return f"watchpoint: $f{index} changed"
        changed_addresses = {change.address for change in record.memory_changes}
        matches = sorted(changed_addresses & self.watch_addresses)
        if matches:
            return f"watchpoint: memory 0x{matches[0]:08x} changed"
        return None

    def _context(self) -> None:
        machine = self._require_machine()
        if machine.exited:
            self.output.write(f"program exited with status {machine.exit_status}\n")
            return
        entry = machine.program.source_map.get(machine.pc)
        word = machine.memory.read_u32(machine.pc, pc=machine.pc, execute=True)
        self.output.write(f"pc=0x{machine.pc:08x}  0x{word:08x}  {disassemble(word, machine.pc)}\n")
        if entry is not None:
            self.output.write(
                f"  {entry.source.filename}:{entry.source.line}: {entry.source.text.strip()}\n"
            )

    def _step(self, count: int) -> None:
        machine = self._require_machine()
        for _ in range(count):
            if machine.exited:
                break
            record = machine.step()
            self._flush_program_output()
            reason = self._watch_trigger(record)
            if reason is not None:
                self.output.write(f"{reason}\n")
                break
        self._context()

    def _continue(self, *, ignore_current_breakpoint: bool) -> None:
        machine = self._require_machine()
        first = True
        while not machine.exited:
            if machine.pc in self.breakpoints and not (first and ignore_current_breakpoint):
                self.output.write(f"breakpoint at 0x{machine.pc:08x}\n")
                break
            record = machine.step()
            self._flush_program_output()
            reason = self._watch_trigger(record)
            if reason is not None:
                self.output.write(f"{reason}\n")
                break
            first = False
        self._context()

    @staticmethod
    def _count(arguments: Sequence[str]) -> int:
        if len(arguments) > 1:
            raise RuntimeFault("D102", "expected at most one count")
        try:
            count = 1 if not arguments else int(arguments[0], 0)
        except ValueError as error:
            raise RuntimeFault("D103", "count must be an integer") from error
        if not 1 <= count <= 1_000_000:
            raise RuntimeFault("D104", "count must be between 1 and 1000000")
        return count

    def _print_value(self, expression: str) -> None:
        machine = self._require_machine()
        symbols = dict(machine.program.symbols)
        identifiers = re.findall(r"%hi|%lo|[A-Za-z_.$][A-Za-z0-9_.$]*", expression)
        for identifier in identifiers:
            lowered = identifier.lower()
            if lowered in {"%hi", "%lo"}:
                continue
            if lowered == "pc":
                symbols[identifier] = machine.pc
            elif lowered == "hi":
                symbols[identifier] = machine._read_hi(None)
            elif lowered == "lo":
                symbols[identifier] = machine._read_lo(None)
            elif lowered.startswith("$f"):
                index = parse_fpu_register(identifier, self._debug_source())
                symbols[identifier] = machine.read_fpu_register(index)
            elif identifier.startswith("$"):
                index = parse_register(identifier, self._debug_source())
                symbols[identifier] = machine.read_register(index)
        value = evaluate(expression, symbols, self._debug_source())
        self.output.write(f"{s32(value)} (0x{value & 0xFFFF_FFFF:08x})\n")

    @staticmethod
    def _debug_source() -> SourceRef:
        return SourceRef("<debugger>", 1, 1, "")

    def _registers(self) -> None:
        machine = self._require_machine()
        for start in range(0, 32, 4):
            fields: list[str] = []
            for index in range(start, start + 4):
                if machine.initialized_registers & (1 << index):
                    fields.append(f"{register_name(index):>5}=0x{machine.registers[index]:08x}")
                else:
                    fields.append(f"{register_name(index):>5}=????????")
            self.output.write("  ".join(fields) + "\n")

    def _fpu_registers(self) -> None:
        machine = self._require_machine()
        for start in range(0, 32, 4):
            fields: list[str] = []
            for index in range(start, start + 4):
                if machine.initialized_fpu_registers & (1 << index):
                    fields.append(f"$f{index:<2}=0x{machine.fpu_registers[index]:08x}")
                else:
                    fields.append(f"$f{index:<2}=????????")
            self.output.write("  ".join(fields) + "\n")

    def _execute_command(self, line: str) -> bool:
        try:
            words = shlex.split(line)
        except ValueError as error:
            raise RuntimeFault("D105", f"cannot parse debugger command: {error}") from error
        if not words:
            return True
        command, *arguments = words
        command = {
            "c": "continue",
            "s": "step",
            "q": "quit",
            "r": "run",
            "p": "print",
            "x": "examine",
        }.get(command, command)
        if command in {"quit", "exit"}:
            return False
        if command == "help":
            self.output.write(_HELP)
        elif command == "load":
            if not arguments:
                raise RuntimeFault("D106", "load requires at least one source file")
            paths = [Path(value) for value in arguments]
            units = self._read_source_units(paths)
            self.program = assemble(units)
            self.argv = (str(paths[0]),)
            self.breakpoints.clear()
            self.watch_registers.clear()
            self.watch_fpu_registers.clear()
            self.watch_addresses.clear()
            self.reset()
            self.output.write(f"loaded {len(self.program.text_words)} instruction words\n")
            self._context()
        elif command == "run":
            if arguments:
                raise RuntimeFault("D107", "run takes no arguments")
            self.reset()
            self._continue(ignore_current_breakpoint=False)
        elif command == "continue":
            if arguments:
                raise RuntimeFault("D108", "continue takes no arguments")
            self._continue(ignore_current_breakpoint=True)
        elif command == "step":
            self._step(self._count(arguments))
        elif command == "back":
            machine = self._require_machine()
            for _ in range(self._count(arguments)):
                machine.reverse_step()
            self._flush_program_output()
            self._context()
        elif command == "break":
            if len(arguments) != 1:
                raise RuntimeFault("D109", "break requires one target")
            break_address = self._resolve_target(arguments[0])
            self.breakpoints.add(break_address)
            self.output.write(f"breakpoint set at 0x{break_address:08x}\n")
        elif command == "delete":
            if len(arguments) != 1:
                raise RuntimeFault("D110", "delete requires one target or all")
            if arguments[0] == "all":
                self.breakpoints.clear()
            else:
                self.breakpoints.discard(self._resolve_target(arguments[0]))
        elif command == "breaks":
            for address in sorted(self.breakpoints):
                self.output.write(f"0x{address:08x}\n")
        elif command in {"watch", "unwatch"}:
            if len(arguments) != 1:
                raise RuntimeFault("D111", f"{command} requires one register, address, or all")
            watch_target = arguments[0]
            if command == "unwatch" and watch_target == "all":
                self.watch_registers.clear()
                self.watch_fpu_registers.clear()
                self.watch_addresses.clear()
            elif watch_target.lower().startswith("$f"):
                index = parse_fpu_register(watch_target, self._debug_source())
                update_watch = (
                    self.watch_fpu_registers.add
                    if command == "watch"
                    else self.watch_fpu_registers.discard
                )
                update_watch(index)
            elif watch_target.startswith("$"):
                index = parse_register(watch_target, self._debug_source())
                (self.watch_registers.add if command == "watch" else self.watch_registers.discard)(
                    index
                )
            else:
                address = self._resolve_target(watch_target.removeprefix("*"))
                (self.watch_addresses.add if command == "watch" else self.watch_addresses.discard)(
                    address
                )
        elif command == "print":
            if not arguments:
                raise RuntimeFault("D112", "print requires an expression")
            self._print_value(" ".join(arguments))
        elif command == "registers":
            self._registers()
        elif command == "fregisters":
            self._fpu_registers()
        elif command == "examine":
            if not 1 <= len(arguments) <= 2:
                raise RuntimeFault("D113", "examine requires an address and optional count")
            machine = self._require_machine()
            address = self._resolve_target(arguments[0].removeprefix("*"))
            count = self._count(arguments[1:])
            for offset in range(count):
                selected = address + offset * 4
                value = machine.memory.read_u32(selected, pc=machine.pc)
                self.output.write(f"0x{selected:08x}: 0x{value:08x}\n")
        elif command == "disassemble":
            if len(arguments) > 2:
                raise RuntimeFault("D114", "disassemble accepts optional address and count")
            machine = self._require_machine()
            address = machine.pc if not arguments else self._resolve_target(arguments[0])
            count = 10 if len(arguments) < 2 else self._count(arguments[1:])
            for offset in range(count):
                selected = address + offset * 4
                word = machine.memory.read_u32(selected, pc=machine.pc, execute=True)
                marker = "=>" if selected == machine.pc else "  "
                self.output.write(
                    f"{marker} 0x{selected:08x}: 0x{word:08x}  {disassemble(word, selected)}\n"
                )
        elif command == "context":
            self._context()
        elif command == "labels":
            if self.program is None:
                raise RuntimeFault("D100", "no program is loaded")
            for name, address in sorted(
                self.program.symbols.items(), key=lambda item: (item[1], item[0])
            ):
                self.output.write(f"0x{address:08x} {name}\n")
        elif command == "output":
            machine = self._require_machine()
            self.output.write(machine.io.output.decode("utf-8", errors="replace") + "\n")
        elif command == "commit-files":
            if arguments:
                raise RuntimeFault("D116", "commit-files takes no arguments")
            machine = self._require_machine()
            if self.filesystem_root is None:
                raise RuntimeFault("D117", "no filesystem root is configured")
            try:
                count = machine.filesystem.commit()
            finally:
                machine.history.clear()
            self.output.write(f"committed {count} file(s)\n")
        elif command == "reset":
            self.reset()
            self._context()
        else:
            raise RuntimeFault("D115", f"unknown debugger command {command!r}")
        return True

    def repl(self) -> int:
        self.output.write("csetty-mips interactive debugger; type 'help' for commands\n")
        if self.machine is not None:
            self._context()
        while True:
            try:
                line = self.input_fn("(csetty-mips) ")
            except EOFError:
                self.output.write("\n")
                return 0
            try:
                if not self._execute_command(line):
                    return 0
            except (CsettyMipsError, OSError) as error:
                rendered = error.render() if isinstance(error, CsettyMipsError) else str(error)
                self.output.write(rendered + "\n")
