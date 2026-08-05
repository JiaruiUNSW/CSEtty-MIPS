from __future__ import annotations

import struct
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .errors import RuntimeFault, SourceRef
from .filesystem import FileSystemState, VirtualFileSystem
from .integers import checked_add_i32, checked_sub_i32, s32, sign_extend, u32
from .isa import is_supported_encoding
from .limits import DEFAULT_LIMITS, Limits
from .memory import MemoryByteChange, SparseMemory
from .model import DATA_BASE, DATA_MAX_BYTES, STACK_TOP, Program
from .runtime_io import RuntimeIO

RETURN_SENTINEL = 0xFFFF_FFFC


@dataclass(frozen=True, slots=True)
class StepRecord:
    pc: int
    word: int
    registers: tuple[int, ...]
    initialized_registers: int
    fpu_registers: tuple[int, ...]
    initialized_fpu_registers: int
    hi: int
    hi_initialized: bool
    lo: int
    lo_initialized: bool
    reservation: int | None
    heap_break: int
    data_end: int
    exited: bool
    exit_status: int
    input_position: int
    output_length: int
    filesystem_state: FileSystemState
    stdio_open: int
    memory_changes: tuple[MemoryByteChange, ...]


class Machine:
    def __init__(
        self,
        program: Program,
        *,
        argv: tuple[str, ...] = ("program",),
        input_data: bytes = b"",
        input_provider: Callable[[], bytes] | None = None,
        output_sink: Callable[[bytes], None] | None = None,
        limits: Limits = DEFAULT_LIMITS,
        history_limit: int | None = None,
        filesystem_root: Path | None = None,
        initial_files: Mapping[str, bytes] | None = None,
        strict_initialization: bool = True,
    ) -> None:
        self.program = program
        self.limits = limits
        self.strict_initialization = strict_initialization
        self.memory = SparseMemory(program, limits, strict_initialization=strict_initialization)
        self.io = RuntimeIO(
            input_data,
            output_limit=limits.max_output_bytes,
            input_limit=limits.max_input_bytes,
            token_limit=limits.max_input_token_bytes,
            input_provider=input_provider,
            output_sink=output_sink,
        )
        self.filesystem = VirtualFileSystem(
            limits,
            root=filesystem_root,
            initial_files=initial_files,
        )
        self.stdio_open = 0b111
        self.registers = [0] * 32
        self.initialized_registers = 1
        self.fpu_registers = [0] * 32
        self.initialized_fpu_registers = 0
        self.hi = 0
        self.hi_initialized = False
        self.lo = 0
        self.lo_initialized = False
        self.pc = program.entry
        self.steps = 0
        self.reservation: int | None = None
        self.heap_break = (program.data_base + len(program.data) + 3) & ~3
        self.exited = False
        self.exit_status = 0
        selected_limit = limits.max_history if history_limit is None else history_limit
        self.history: deque[StepRecord] = deque(maxlen=max(0, selected_limit))
        for index in range(16, 24):
            self._write_register_initial(index, 0)
        self._write_register_initial(28, DATA_BASE + 0x8000)
        self._write_register_initial(29, STACK_TOP)
        self._write_register_initial(31, RETURN_SENTINEL)
        self._install_arguments(argv)
        self._write_register_initial(30, self.registers[29])

    def _source(self) -> SourceRef | None:
        entry = self.program.source_map.get(self.pc)
        return entry.source if entry is not None else None

    def _write_register_initial(self, index: int, value: int) -> None:
        if index:
            self.registers[index] = u32(value)
            self.initialized_registers |= 1 << index

    def read_register(self, index: int, source: SourceRef | None = None) -> int:
        if not self.initialized_registers & (1 << index):
            if not self.strict_initialization:
                return 0
            raise RuntimeFault(
                "R100",
                f"read from uninitialized register ${index}",
                source or self._source(),
                pc=self.pc,
            )
        return self.registers[index]

    def write_register(self, index: int, value: int) -> None:
        if index:
            self.registers[index] = u32(value)
            self.initialized_registers |= 1 << index

    def read_fpu_register(self, index: int, source: SourceRef | None = None) -> int:
        if not self.initialized_fpu_registers & (1 << index):
            if not self.strict_initialization:
                return 0
            raise RuntimeFault(
                "R118",
                f"read from uninitialized floating-point register $f{index}",
                source or self._source(),
                pc=self.pc,
            )
        return self.fpu_registers[index]

    def write_fpu_register(self, index: int, value: int) -> None:
        self.fpu_registers[index] = u32(value)
        self.initialized_fpu_registers |= 1 << index

    def _install_arguments(self, argv: tuple[str, ...]) -> None:
        encoded: list[bytes] = []
        for index, item in enumerate(argv):
            try:
                encoded.append(item.encode("utf-8") + b"\0")
            except UnicodeEncodeError as error:
                raise RuntimeFault(
                    "R313", f"program argument {index} is not valid UTF-8"
                ) from error
        cursor = STACK_TOP + 4
        pointers: list[int] = []
        for payload in reversed(encoded):
            cursor -= len(payload)
            self.memory.write_bytes(cursor, payload)
            pointers.append(cursor)
        pointers.reverse()
        cursor &= ~3
        cursor -= 4
        self.memory.write_u32(cursor, 0)
        for pointer in reversed(pointers):
            cursor -= 4
            self.memory.write_u32(cursor, pointer)
        argv_address = cursor
        cursor &= ~7
        self._write_register_initial(4, len(argv))
        self._write_register_initial(5, argv_address)
        self._write_register_initial(29, cursor)

    def _snapshot(self, word: int) -> StepRecord:
        return StepRecord(
            pc=self.pc,
            word=word,
            registers=tuple(self.registers),
            initialized_registers=self.initialized_registers,
            fpu_registers=tuple(self.fpu_registers),
            initialized_fpu_registers=self.initialized_fpu_registers,
            hi=self.hi,
            hi_initialized=self.hi_initialized,
            lo=self.lo,
            lo_initialized=self.lo_initialized,
            reservation=self.reservation,
            heap_break=self.heap_break,
            data_end=self.memory.data_end,
            exited=self.exited,
            exit_status=self.exit_status,
            input_position=self.io.input_position,
            output_length=len(self.io.output),
            filesystem_state=self.filesystem.snapshot(),
            stdio_open=self.stdio_open,
            memory_changes=(),
        )

    def _restore_record(self, record: StepRecord) -> None:
        self.memory.restore(record.memory_changes)
        self.pc = record.pc
        self.registers[:] = record.registers
        self.initialized_registers = record.initialized_registers
        self.fpu_registers[:] = record.fpu_registers
        self.initialized_fpu_registers = record.initialized_fpu_registers
        self.hi = record.hi
        self.hi_initialized = record.hi_initialized
        self.lo = record.lo
        self.lo_initialized = record.lo_initialized
        self.reservation = record.reservation
        self.heap_break = record.heap_break
        self.memory.restore_data_end(record.data_end)
        self.exited = record.exited
        self.exit_status = record.exit_status
        self.io.restore(
            input_position=record.input_position,
            output_length=record.output_length,
        )
        self.filesystem.restore(record.filesystem_state)
        self.stdio_open = record.stdio_open

    def reverse_step(self) -> StepRecord:
        if not self.history:
            raise RuntimeFault(
                "R101", "no recorded instruction is available to reverse", pc=self.pc
            )
        record = self.history.pop()
        self._restore_record(record)
        self.steps = max(0, self.steps - 1)
        return record

    def _read_hi(self, source: SourceRef | None) -> int:
        if not self.hi_initialized:
            if not self.strict_initialization:
                return 0
            raise RuntimeFault("R102", "read from uninitialized HI register", source, pc=self.pc)
        return self.hi

    def _read_lo(self, source: SourceRef | None) -> int:
        if not self.lo_initialized:
            if not self.strict_initialization:
                return 0
            raise RuntimeFault("R103", "read from uninitialized LO register", source, pc=self.pc)
        return self.lo

    def _write_memory(
        self,
        address: int,
        value: int,
        width: int,
        source: SourceRef | None,
        changes: list[MemoryByteChange],
    ) -> None:
        if width == 1:
            changes.extend(self.memory.write_u8(address, value, source=source, pc=self.pc))
        elif width == 2:
            changes.extend(self.memory.write_u16(address, value, source=source, pc=self.pc))
        else:
            changes.extend(self.memory.write_u32(address, value, source=source, pc=self.pc))
        self.reservation = None

    def _execute_syscall(self, source: SourceRef | None, changes: list[MemoryByteChange]) -> None:
        service = self.read_register(2, source)
        if service == 1:
            self.io.write(str(s32(self.read_register(4, source))).encode("ascii"), source, self.pc)
        elif service == 2:
            raw = self.read_fpu_register(12, source)
            value = struct.unpack("<f", struct.pack("<I", raw))[0]
            self.io.write(format(value, ".8f").encode("ascii"), source, self.pc)
        elif service == 3:
            raw = self.read_fpu_register(12, source) | (self.read_fpu_register(13, source) << 32)
            value = struct.unpack("<d", raw.to_bytes(8, "little"))[0]
            self.io.write(format(value, ".18g").encode("ascii"), source, self.pc)
        elif service == 4:
            address = self.read_register(4, source)
            self.io.write(
                self.memory.read_c_string(
                    address, limit=self.limits.max_string_bytes, source=source, pc=self.pc
                ),
                source,
                self.pc,
            )
        elif service == 5:
            self.write_register(2, self.io.read_int(source, self.pc))
        elif service == 6:
            value = self.io.read_float(source, self.pc)
            try:
                raw = struct.unpack("<I", struct.pack("<f", value))[0]
            except OverflowError as error:
                raise RuntimeFault(
                    "R308", "input value does not fit in a float", source, pc=self.pc
                ) from error
            self.write_fpu_register(0, raw)
        elif service == 7:
            value = self.io.read_float(source, self.pc)
            raw = int.from_bytes(struct.pack("<d", value), "little")
            self.write_fpu_register(0, raw & 0xFFFF_FFFF)
            self.write_fpu_register(1, raw >> 32)
        elif service == 8:
            address = self.read_register(4, source)
            length = s32(self.read_register(5, source))
            if length > 0:
                payload = self.io.read_line(max(0, length - 1))[: max(0, length - 1)] + b"\0"
                changes.extend(self.memory.write_bytes(address, payload, source=source, pc=self.pc))
                self.reservation = None
        elif service == 9:
            amount = s32(self.read_register(4, source))
            if amount < 0:
                raise RuntimeFault("R304", "sbrk size cannot be negative", source, pc=self.pc)
            old_break = self.heap_break
            new_break = (old_break + amount + 3) & ~3
            heap_limit = DATA_BASE + min(DATA_MAX_BYTES, self.limits.max_data_bytes)
            if new_break > heap_limit:
                raise RuntimeFault("R305", "simulated heap limit exceeded", source, pc=self.pc)
            self.memory.grow_data(new_break, source=source, pc=self.pc)
            self.heap_break = new_break
            self.write_register(2, old_break)
        elif service == 10:
            self.exited = True
            self.exit_status = 0
        elif service == 11:
            self.io.write(bytes((self.read_register(4, source) & 0xFF,)), source, self.pc)
        elif service == 12:
            value = self.io.read_byte()
            self.write_register(2, 0xFFFF_FFFF if value is None else value)
        elif service == 13:
            address = self.read_register(4, source)
            path_bytes = self.memory.read_c_string(
                address,
                limit=self.limits.max_path_bytes,
                source=source,
                pc=self.pc,
            )
            try:
                path = path_bytes.decode("utf-8")
            except UnicodeDecodeError:
                descriptor = -1
            else:
                descriptor = self.filesystem.open(path, s32(self.read_register(5, source)))
            self.write_register(2, descriptor)
        elif service == 14:
            descriptor = s32(self.read_register(4, source))
            address = self.read_register(5, source)
            maximum = s32(self.read_register(6, source))
            if maximum < 0 or maximum > self.limits.max_file_bytes:
                payload = None
            elif descriptor == 0 and self.stdio_open & 1:
                payload = self.io.read_bytes(maximum)
            else:
                payload = self.filesystem.read(descriptor, maximum)
            if payload is None:
                self.write_register(2, -1)
            else:
                changes.extend(self.memory.write_bytes(address, payload, source=source, pc=self.pc))
                if payload:
                    self.reservation = None
                self.write_register(2, len(payload))
        elif service == 15:
            descriptor = s32(self.read_register(4, source))
            address = self.read_register(5, source)
            count = s32(self.read_register(6, source))
            if count < 0 or count > self.limits.max_file_bytes:
                written = -1
            else:
                payload = self.memory.read_bytes(address, count, source=source, pc=self.pc)
                if descriptor in {1, 2} and self.stdio_open & (1 << descriptor):
                    self.io.write(payload, source, self.pc)
                    written = len(payload)
                else:
                    written = self.filesystem.write(descriptor, payload)
            self.write_register(2, written)
        elif service == 16:
            descriptor = s32(self.read_register(4, source))
            if descriptor in {0, 1, 2} and self.stdio_open & (1 << descriptor):
                self.stdio_open &= ~(1 << descriptor)
                closed = True
            else:
                closed = self.filesystem.close(descriptor)
            self.write_register(2, 0 if closed else -1)
        elif service == 17:
            self.exited = True
            self.exit_status = s32(self.read_register(4, source))
        else:
            raise RuntimeFault("R307", f"unsupported syscall {service}", source, pc=self.pc)

    def step(self) -> StepRecord:
        if self.exited:
            raise RuntimeFault("R104", "program has already exited", pc=self.pc)
        if self.steps >= self.limits.max_steps:
            raise RuntimeFault(
                "R105",
                f"instruction limit {self.limits.max_steps} exceeded",
                self._source(),
                pc=self.pc,
            )
        if self.pc == RETURN_SENTINEL:
            self.exited = True
            self.exit_status = 0
            raise RuntimeFault("R106", "cannot step after main returned", pc=self.pc)
        source = self._source()
        word = self.memory.read_u32(self.pc, source=source, pc=self.pc, execute=True)
        snapshot = self._snapshot(word)
        changes: list[MemoryByteChange] = []
        next_pc = u32(self.pc + 4)
        opcode = word >> 26
        rs = (word >> 21) & 0x1F
        rt = (word >> 16) & 0x1F
        rd = (word >> 11) & 0x1F
        shamt = (word >> 6) & 0x1F
        funct = word & 0x3F
        immediate = word & 0xFFFF
        signed_immediate = sign_extend(immediate, 16)

        if not is_supported_encoding(word):
            raise RuntimeFault(
                "R121", f"reserved instruction encoding 0x{word:08x}", source, pc=self.pc
            )

        try:
            if opcode == 0:
                if funct in {0x00, 0x02, 0x03}:
                    value = self.read_register(rt, source)
                    if funct == 0x00:
                        result = value << shamt
                    elif funct == 0x02 and rs == 1:
                        result = value if shamt == 0 else (value >> shamt) | (value << (32 - shamt))
                    elif funct == 0x02:
                        result = value >> shamt
                    else:
                        result = s32(value) >> shamt
                    self.write_register(rd, result)
                elif funct in {0x04, 0x06, 0x07}:
                    amount = self.read_register(rs, source) & 0x1F
                    value = self.read_register(rt, source)
                    if funct == 0x04:
                        result = value << amount
                    elif funct == 0x06 and shamt == 1:
                        result = (
                            value if amount == 0 else (value >> amount) | (value << (32 - amount))
                        )
                    elif funct == 0x06:
                        result = value >> amount
                    else:
                        result = s32(value) >> amount
                    self.write_register(rd, result)
                elif funct == 0x08:
                    next_pc = self.read_register(rs, source)
                elif funct == 0x09:
                    target = self.read_register(rs, source)
                    self.write_register(rd, next_pc)
                    next_pc = target
                elif funct in {0x0A, 0x0B}:
                    condition = self.read_register(rt, source) == 0
                    if condition == (funct == 0x0A):
                        self.write_register(rd, self.read_register(rs, source))
                elif funct == 0x0C:
                    self._execute_syscall(source, changes)
                elif funct == 0x0D:
                    raise RuntimeFault("R107", "break instruction executed", source, pc=self.pc)
                elif funct == 0x10:
                    self.write_register(rd, self._read_hi(source))
                elif funct == 0x11:
                    self.hi = self.read_register(rs, source)
                    self.hi_initialized = True
                elif funct == 0x12:
                    self.write_register(rd, self._read_lo(source))
                elif funct == 0x13:
                    self.lo = self.read_register(rs, source)
                    self.lo_initialized = True
                elif funct in {0x18, 0x19}:
                    left = self.read_register(rs, source)
                    right = self.read_register(rt, source)
                    product = s32(left) * s32(right) if funct == 0x18 else left * right
                    product &= 0xFFFF_FFFF_FFFF_FFFF
                    self.lo = product & 0xFFFF_FFFF
                    self.hi = (product >> 32) & 0xFFFF_FFFF
                    self.lo_initialized = self.hi_initialized = True
                elif funct in {0x1A, 0x1B}:
                    left = self.read_register(rs, source)
                    right = self.read_register(rt, source)
                    if right == 0:
                        raise RuntimeFault("R108", "division by zero", source, pc=self.pc)
                    if funct == 0x1A:
                        signed_left, signed_right = s32(left), s32(right)
                        quotient = abs(signed_left) // abs(signed_right)
                        if (signed_left < 0) != (signed_right < 0):
                            quotient = -quotient
                        remainder = signed_left - quotient * signed_right
                    else:
                        quotient, remainder = divmod(left, right)
                    self.lo, self.hi = u32(quotient), u32(remainder)
                    self.lo_initialized = self.hi_initialized = True
                elif funct in {0x30, 0x31, 0x32, 0x33, 0x34, 0x36}:
                    left = self.read_register(rs, source)
                    right = self.read_register(rt, source)
                    condition = {
                        0x30: s32(left) >= s32(right),
                        0x31: left >= right,
                        0x32: s32(left) < s32(right),
                        0x33: left < right,
                        0x34: left == right,
                        0x36: left != right,
                    }[funct]
                    if condition:
                        raise RuntimeFault("R116", "trap condition was true", source, pc=self.pc)
                elif funct in {0x20, 0x21, 0x22, 0x23}:
                    left, right = self.read_register(rs, source), self.read_register(rt, source)
                    if funct == 0x20:
                        checked_result = checked_add_i32(left, right)
                        if checked_result is None:
                            raise RuntimeFault(
                                "R109", "signed addition overflow", source, pc=self.pc
                            )
                        alu_result = checked_result
                    elif funct == 0x21:
                        alu_result = u32(left + right)
                    elif funct == 0x22:
                        checked_result = checked_sub_i32(left, right)
                        if checked_result is None:
                            raise RuntimeFault(
                                "R110", "signed subtraction overflow", source, pc=self.pc
                            )
                        alu_result = checked_result
                    else:
                        alu_result = u32(left - right)
                    self.write_register(rd, alu_result)
                elif funct in {0x24, 0x25, 0x26, 0x27}:
                    left, right = self.read_register(rs, source), self.read_register(rt, source)
                    result = {
                        0x24: left & right,
                        0x25: left | right,
                        0x26: left ^ right,
                        0x27: ~(left | right),
                    }[funct]
                    self.write_register(rd, result)
                elif funct in {0x2A, 0x2B}:
                    left, right = self.read_register(rs, source), self.read_register(rt, source)
                    self.write_register(
                        rd, int((s32(left) < s32(right)) if funct == 0x2A else (left < right))
                    )
                else:
                    raise RuntimeFault(
                        "R111", f"unknown SPECIAL function 0x{funct:02x}", source, pc=self.pc
                    )
            elif opcode == 0x01:
                value = self.read_register(rs, source)
                if rt in {0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0E}:
                    unsigned_immediate = u32(signed_immediate)
                    trap_condition = {
                        0x08: s32(value) >= signed_immediate,
                        0x09: value >= unsigned_immediate,
                        0x0A: s32(value) < signed_immediate,
                        0x0B: value < unsigned_immediate,
                        0x0C: value == unsigned_immediate,
                        0x0E: value != unsigned_immediate,
                    }[rt]
                    if trap_condition:
                        raise RuntimeFault("R116", "trap condition was true", source, pc=self.pc)
                else:
                    branch_condition = {
                        0x00: s32(value) < 0,
                        0x01: s32(value) >= 0,
                        0x10: s32(value) < 0,
                        0x11: s32(value) >= 0,
                    }.get(rt)
                    if branch_condition is None:
                        raise RuntimeFault(
                            "R112", f"unknown REGIMM selector 0x{rt:02x}", source, pc=self.pc
                        )
                    if branch_condition:
                        next_pc = u32(next_pc + signed_immediate * 4)
                    if rt in {0x10, 0x11}:
                        self.write_register(31, u32(self.pc + 4))
            elif opcode in {0x02, 0x03}:
                if opcode == 0x03:
                    self.write_register(31, next_pc)
                next_pc = (next_pc & 0xF000_0000) | ((word & 0x03FF_FFFF) << 2)
            elif opcode in {0x04, 0x05}:
                equal = self.read_register(rs, source) == self.read_register(rt, source)
                if equal == (opcode == 0x04):
                    next_pc = u32(next_pc + signed_immediate * 4)
            elif opcode in {0x06, 0x07}:
                value = s32(self.read_register(rs, source))
                if (value <= 0) == (opcode == 0x06):
                    next_pc = u32(next_pc + signed_immediate * 4)
            elif opcode in {0x08, 0x09}:
                left = self.read_register(rs, source)
                if opcode == 0x08:
                    checked_result = checked_add_i32(left, signed_immediate)
                    if checked_result is None:
                        raise RuntimeFault("R113", "signed addition overflow", source, pc=self.pc)
                    immediate_result = checked_result
                else:
                    immediate_result = u32(left + signed_immediate)
                self.write_register(rt, immediate_result)
            elif opcode in {0x0A, 0x0B}:
                left = self.read_register(rs, source)
                right = u32(signed_immediate)
                self.write_register(
                    rt, int((s32(left) < signed_immediate) if opcode == 0x0A else (left < right))
                )
            elif opcode in {0x0C, 0x0D, 0x0E}:
                left = self.read_register(rs, source)
                result = {0x0C: left & immediate, 0x0D: left | immediate, 0x0E: left ^ immediate}[
                    opcode
                ]
                self.write_register(rt, result)
            elif opcode == 0x0F:
                self.write_register(rt, immediate << 16)
            elif opcode == 0x11:
                coprocessor_operation = rs
                if coprocessor_operation == 0:
                    self.write_register(rt, self.read_fpu_register(rd, source))
                elif coprocessor_operation == 4:
                    self.write_fpu_register(rd, self.read_register(rt, source))
                else:
                    raise RuntimeFault(
                        "R119",
                        f"unsupported COP1 selector 0x{coprocessor_operation:02x}",
                        source,
                        pc=self.pc,
                    )
            elif opcode == 0x1C:
                if funct in {0x00, 0x01, 0x04, 0x05}:
                    accumulator = (self._read_hi(source) << 32) | self._read_lo(source)
                    left = self.read_register(rs, source)
                    right = self.read_register(rt, source)
                    product = s32(left) * s32(right) if funct in {0x00, 0x04} else left * right
                    result = (
                        accumulator - product if funct in {0x04, 0x05} else accumulator + product
                    )
                    result &= 0xFFFF_FFFF_FFFF_FFFF
                    self.hi = (result >> 32) & 0xFFFF_FFFF
                    self.lo = result & 0xFFFF_FFFF
                    self.hi_initialized = self.lo_initialized = True
                elif funct == 0x02:
                    self.write_register(
                        rd,
                        s32(self.read_register(rs, source)) * s32(self.read_register(rt, source)),
                    )
                elif funct in {0x20, 0x21}:
                    value = self.read_register(rs, source)
                    if funct == 0x21:
                        value = u32(~value)
                    count = 32 if value == 0 else 32 - value.bit_length()
                    self.write_register(rd, count)
                else:
                    raise RuntimeFault(
                        "R114", f"unknown SPECIAL2 function 0x{funct:02x}", source, pc=self.pc
                    )
            elif opcode == 0x1F:
                if funct == 0x20 and rs == 0 and shamt in {0x10, 0x18}:
                    width = 8 if shamt == 0x10 else 16
                    self.write_register(rd, sign_extend(self.read_register(rt, source), width))
                else:
                    raise RuntimeFault(
                        "R117", f"unknown SPECIAL3 encoding 0x{word:08x}", source, pc=self.pc
                    )
            elif opcode in {0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B, 0x30, 0x38}:
                address = u32(self.read_register(rs, source) + signed_immediate)
                if opcode == 0x20:
                    self.write_register(
                        rt, sign_extend(self.memory.read_u8(address, source=source, pc=self.pc), 8)
                    )
                elif opcode == 0x21:
                    self.write_register(
                        rt,
                        sign_extend(self.memory.read_u16(address, source=source, pc=self.pc), 16),
                    )
                elif opcode in {0x23, 0x30}:
                    self.write_register(
                        rt, self.memory.read_u32(address, source=source, pc=self.pc)
                    )
                    if opcode == 0x30:
                        self.reservation = address
                elif opcode == 0x24:
                    self.write_register(rt, self.memory.read_u8(address, source=source, pc=self.pc))
                elif opcode == 0x25:
                    self.write_register(
                        rt, self.memory.read_u16(address, source=source, pc=self.pc)
                    )
                elif opcode == 0x28:
                    self._write_memory(address, self.read_register(rt, source), 1, source, changes)
                elif opcode == 0x29:
                    self._write_memory(address, self.read_register(rt, source), 2, source, changes)
                elif opcode == 0x2B:
                    self._write_memory(address, self.read_register(rt, source), 4, source, changes)
                else:
                    if self.reservation == address:
                        self._write_memory(
                            address, self.read_register(rt, source), 4, source, changes
                        )
                        self.write_register(rt, 1)
                    else:
                        self.memory.validate_write(
                            address, 4, alignment=4, source=source, pc=self.pc
                        )
                        self.write_register(rt, 0)
                    self.reservation = None
            elif opcode in {0x22, 0x26, 0x2A, 0x2E}:
                self._execute_unaligned(opcode, rs, rt, signed_immediate, source, changes)
            elif opcode in {0x31, 0x35, 0x39, 0x3D}:
                address = u32(self.read_register(rs, source) + signed_immediate)
                if opcode == 0x31:
                    self.write_fpu_register(
                        rt, self.memory.read_u32(address, source=source, pc=self.pc)
                    )
                elif opcode == 0x35:
                    if rt & 1 or rt == 31:
                        raise RuntimeFault(
                            "R120",
                            "LDC1 requires an even floating-point register pair",
                            source,
                            pc=self.pc,
                        )
                    raw = int.from_bytes(
                        self.memory.read_bytes(address, 8, alignment=8, source=source, pc=self.pc),
                        "little",
                    )
                    self.write_fpu_register(rt, raw & 0xFFFF_FFFF)
                    self.write_fpu_register(rt + 1, raw >> 32)
                elif opcode == 0x39:
                    changes.extend(
                        self.memory.write_u32(
                            address,
                            self.read_fpu_register(rt, source),
                            source=source,
                            pc=self.pc,
                        )
                    )
                    self.reservation = None
                else:
                    if rt & 1 or rt == 31:
                        raise RuntimeFault(
                            "R120",
                            "SDC1 requires an even floating-point register pair",
                            source,
                            pc=self.pc,
                        )
                    raw = self.read_fpu_register(rt, source) | (
                        self.read_fpu_register(rt + 1, source) << 32
                    )
                    changes.extend(
                        self.memory.write_bytes(
                            address,
                            raw.to_bytes(8, "little"),
                            alignment=8,
                            source=source,
                            pc=self.pc,
                        )
                    )
                    self.reservation = None
            else:
                raise RuntimeFault("R115", f"unknown opcode 0x{opcode:02x}", source, pc=self.pc)
            if next_pc == RETURN_SENTINEL:
                self.exited = True
                self.exit_status = 0
            self.pc = next_pc
        except RuntimeFault:
            snapshot_with_changes = replace(snapshot, memory_changes=tuple(changes))
            self._restore_record(snapshot_with_changes)
            raise

        record = StepRecord(
            pc=snapshot.pc,
            word=snapshot.word,
            registers=snapshot.registers,
            initialized_registers=snapshot.initialized_registers,
            fpu_registers=snapshot.fpu_registers,
            initialized_fpu_registers=snapshot.initialized_fpu_registers,
            hi=snapshot.hi,
            hi_initialized=snapshot.hi_initialized,
            lo=snapshot.lo,
            lo_initialized=snapshot.lo_initialized,
            reservation=snapshot.reservation,
            heap_break=snapshot.heap_break,
            data_end=snapshot.data_end,
            exited=snapshot.exited,
            exit_status=snapshot.exit_status,
            input_position=snapshot.input_position,
            output_length=snapshot.output_length,
            filesystem_state=snapshot.filesystem_state,
            stdio_open=snapshot.stdio_open,
            memory_changes=tuple(changes),
        )
        if self.history.maxlen:
            self.history.append(record)
        self.steps += 1
        return record

    def _execute_unaligned(
        self,
        opcode: int,
        rs: int,
        rt: int,
        immediate: int,
        source: SourceRef | None,
        changes: list[MemoryByteChange],
    ) -> None:
        address = u32(self.read_register(rs, source) + immediate)
        aligned = address & ~3
        offset = address & 3
        current = self.read_register(rt, source)
        if opcode == 0x22:  # LWL, little-endian
            count = offset + 1
            payload = self.memory.read_bytes(aligned, count, source=source, pc=self.pc)
            loaded = int.from_bytes(payload, "little") << (8 * (3 - offset))
            mask = (1 << (8 * (3 - offset))) - 1
            self.write_register(rt, (current & mask) | loaded)
        elif opcode == 0x26:  # LWR, little-endian
            payload = self.memory.read_bytes(address, 4 - offset, source=source, pc=self.pc)
            loaded = int.from_bytes(payload, "little")
            mask = u32(~((1 << (8 * (4 - offset))) - 1))
            self.write_register(rt, (current & mask) | loaded)
        elif opcode == 0x2A:  # SWL, little-endian
            count = offset + 1
            payload = (current >> (8 * (3 - offset))).to_bytes(count, "little")
            changes.extend(self.memory.write_bytes(aligned, payload, source=source, pc=self.pc))
            self.reservation = None
        else:  # SWR, little-endian
            count = 4 - offset
            payload = (current & ((1 << (count * 8)) - 1)).to_bytes(count, "little")
            changes.extend(self.memory.write_bytes(address, payload, source=source, pc=self.pc))
            self.reservation = None

    def run(self) -> int:
        while not self.exited:
            self.step()
        return self.exit_status
