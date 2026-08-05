from __future__ import annotations

from dataclasses import dataclass

from .errors import RuntimeFault, SourceRef
from .limits import Limits
from .model import (
    DATA_BASE,
    DATA_INITIAL_BYTES,
    DATA_MAX_BYTES,
    KDATA_BASE,
    KDATA_MAX_BYTES,
    KTEXT_BASE,
    KTEXT_INITIAL_BYTES,
    STACK_MAX_BYTES,
    STACK_TOP,
    TEXT_BASE,
    TEXT_INITIAL_BYTES,
    Program,
)

PAGE_SIZE = 4096
PAGE_MASK = PAGE_SIZE - 1


@dataclass(frozen=True, slots=True)
class MemoryRegion:
    name: str
    start: int
    end: int
    readable: bool
    writable: bool
    executable: bool = False

    def contains(self, address: int, width: int) -> bool:
        return self.start <= address and address + width <= self.end


@dataclass(frozen=True, slots=True)
class MemoryByteChange:
    address: int
    old_value: int
    old_initialized: bool
    page_was_present: bool


class SparseMemory:
    def __init__(
        self, program: Program, limits: Limits, *, strict_initialization: bool = True
    ) -> None:
        text_end = program.text_base + len(program.text_words) * 4
        ktext_end = program.ktext_base + len(program.ktext_words) * 4
        stack_size = min(STACK_MAX_BYTES, limits.max_stack_bytes)
        data_capacity = min(DATA_MAX_BYTES, limits.max_data_bytes)
        self._data_end = max(
            program.data_base + len(program.data),
            DATA_BASE + min(DATA_INITIAL_BYTES, data_capacity),
        )
        self._regions = (
            MemoryRegion(
                "text",
                TEXT_BASE,
                max(text_end, TEXT_BASE + TEXT_INITIAL_BYTES),
                True,
                True,
                True,
            ),
            MemoryRegion(
                "data/heap",
                DATA_BASE,
                DATA_BASE + data_capacity,
                True,
                True,
            ),
            MemoryRegion("stack", STACK_TOP - stack_size + 4, STACK_TOP + 4, True, True),
            MemoryRegion(
                "kernel text",
                KTEXT_BASE,
                max(ktext_end, KTEXT_BASE + KTEXT_INITIAL_BYTES),
                False,
                False,
                False,
            ),
            MemoryRegion(
                "kernel data",
                KDATA_BASE,
                KDATA_BASE + min(KDATA_MAX_BYTES, limits.max_kernel_data_bytes),
                False,
                False,
                False,
            ),
        )
        self._limits = limits
        self.strict_initialization = strict_initialization
        self._pages: dict[int, bytearray] = {}
        self._initialized: dict[int, bytearray] = {}
        for index, word in enumerate(program.text_words):
            self.load(program.text_base + index * 4, word.to_bytes(4, "little"))
        self.load_masked(program.data_base, program.data, program.data_initialized)
        for index, word in enumerate(program.ktext_words):
            self.load(program.ktext_base + index * 4, word.to_bytes(4, "little"))
        self.load_masked(program.kdata_base, program.kdata, program.kdata_initialized)

    @property
    def regions(self) -> tuple[MemoryRegion, ...]:
        return self._regions

    @property
    def data_end(self) -> int:
        return self._data_end

    def _region(
        self,
        address: int,
        width: int,
        *,
        source: SourceRef | None,
        pc: int | None,
        access: str,
    ) -> MemoryRegion:
        if width <= 0 or address < 0 or address > 0xFFFF_FFFF or address + width > 1 << 32:
            raise RuntimeFault(
                "R200", f"invalid {access} range at 0x{address & 0xFFFF_FFFF:08x}", source, pc=pc
            )
        for region in self._regions:
            if region.contains(address, width):
                if region.name == "data/heap" and address + width > self._data_end:
                    continue
                if not region.readable and not region.writable and not region.executable:
                    raise RuntimeFault(
                        "R207",
                        f"cannot {access} protected {region.name} memory at 0x{address:08x}",
                        source,
                        pc=pc,
                    )
                if access == "read" and not region.readable:
                    break
                if access == "write" and not region.writable:
                    raise RuntimeFault(
                        "R201",
                        f"cannot write to read-only {region.name} memory at 0x{address:08x}",
                        source,
                        pc=pc,
                    )
                if access == "execute" and not region.executable:
                    break
                return region
        raise RuntimeFault(
            "R202", f"unmapped {access} at 0x{address & 0xFFFF_FFFF:08x}", source, pc=pc
        )

    def _page(
        self, address: int, *, create: bool, source: SourceRef | None, pc: int | None
    ) -> tuple[bytearray | None, bytearray | None]:
        page_number = address // PAGE_SIZE
        page = self._pages.get(page_number)
        initialized = self._initialized.get(page_number)
        if page is None and create:
            if len(self._pages) >= self._limits.max_memory_pages:
                raise RuntimeFault(
                    "R203",
                    f"allocated memory exceeds {self._limits.max_memory_pages} pages",
                    source,
                    pc=pc,
                )
            page = bytearray(PAGE_SIZE)
            initialized = bytearray(PAGE_SIZE)
            self._pages[page_number] = page
            self._initialized[page_number] = initialized
        return page, initialized

    def load(self, address: int, payload: bytes) -> None:
        for offset, value in enumerate(payload):
            page, initialized = self._page(address + offset, create=True, source=None, pc=None)
            assert page is not None and initialized is not None
            index = (address + offset) & PAGE_MASK
            page[index] = value
            initialized[index] = 1

    def load_masked(self, address: int, payload: bytes, initialized_mask: bytes) -> None:
        if len(payload) != len(initialized_mask):
            raise ValueError("data payload and initialization mask lengths differ")
        for offset, (value, is_initialized) in enumerate(
            zip(payload, initialized_mask, strict=True)
        ):
            if not is_initialized:
                continue
            page, initialized = self._page(address + offset, create=True, source=None, pc=None)
            assert page is not None and initialized is not None
            index = (address + offset) & PAGE_MASK
            page[index] = value
            initialized[index] = 1

    def _check_alignment(
        self, address: int, alignment: int, source: SourceRef | None, pc: int | None
    ) -> None:
        if alignment > 1 and address % alignment:
            raise RuntimeFault(
                "R204",
                f"address 0x{address:08x} is not aligned to {alignment} bytes",
                source,
                pc=pc,
            )

    def read_bytes(
        self,
        address: int,
        width: int,
        *,
        alignment: int = 1,
        source: SourceRef | None = None,
        pc: int | None = None,
        execute: bool = False,
    ) -> bytes:
        if width == 0:
            return b""
        self._check_alignment(address, alignment, source, pc)
        self._region(address, width, source=source, pc=pc, access="execute" if execute else "read")
        result = bytearray()
        for offset in range(width):
            selected = address + offset
            page, initialized = self._page(selected, create=False, source=source, pc=pc)
            index = selected & PAGE_MASK
            if page is None or initialized is None or not initialized[index]:
                if self.strict_initialization:
                    raise RuntimeFault(
                        "R205",
                        f"read from uninitialized memory at 0x{selected:08x}",
                        source,
                        pc=pc,
                    )
                result.append(0)
            else:
                result.append(page[index])
        return bytes(result)

    def read_u8(
        self, address: int, *, source: SourceRef | None = None, pc: int | None = None
    ) -> int:
        return self.read_bytes(address, 1, source=source, pc=pc)[0]

    def read_u16(
        self, address: int, *, source: SourceRef | None = None, pc: int | None = None
    ) -> int:
        return int.from_bytes(
            self.read_bytes(address, 2, alignment=2, source=source, pc=pc), "little"
        )

    def read_u32(
        self,
        address: int,
        *,
        source: SourceRef | None = None,
        pc: int | None = None,
        execute: bool = False,
    ) -> int:
        return int.from_bytes(
            self.read_bytes(address, 4, alignment=4, source=source, pc=pc, execute=execute),
            "little",
        )

    def write_bytes(
        self,
        address: int,
        payload: bytes,
        *,
        alignment: int = 1,
        source: SourceRef | None = None,
        pc: int | None = None,
    ) -> list[MemoryByteChange]:
        if not payload:
            return []
        self.validate_write(
            address,
            len(payload),
            alignment=alignment,
            source=source,
            pc=pc,
        )
        changes: list[MemoryByteChange] = []
        try:
            for offset, value in enumerate(payload):
                selected = address + offset
                page_was_present = selected // PAGE_SIZE in self._pages
                page, initialized = self._page(selected, create=True, source=source, pc=pc)
                assert page is not None and initialized is not None
                index = selected & PAGE_MASK
                changes.append(
                    MemoryByteChange(
                        selected,
                        page[index],
                        bool(initialized[index]),
                        page_was_present,
                    )
                )
                page[index] = value
                initialized[index] = 1
        except RuntimeFault:
            self.restore(changes)
            raise
        return changes

    def validate_write(
        self,
        address: int,
        width: int,
        *,
        alignment: int = 1,
        source: SourceRef | None = None,
        pc: int | None = None,
    ) -> None:
        if width == 0:
            return
        self._check_alignment(address, alignment, source, pc)
        self._region(address, width, source=source, pc=pc, access="write")

    def grow_data(
        self, new_end: int, *, source: SourceRef | None = None, pc: int | None = None
    ) -> None:
        maximum = DATA_BASE + min(DATA_MAX_BYTES, self._limits.max_data_bytes)
        if new_end < DATA_BASE or new_end > maximum:
            raise RuntimeFault(
                "R208",
                f"invalid data-segment end 0x{new_end & 0xFFFF_FFFF:08x}",
                source,
                pc=pc,
            )
        self._data_end = max(self._data_end, new_end)

    def restore_data_end(self, data_end: int) -> None:
        maximum = DATA_BASE + min(DATA_MAX_BYTES, self._limits.max_data_bytes)
        if not DATA_BASE <= data_end <= maximum:
            raise ValueError(f"invalid saved data-segment end: 0x{data_end:08x}")
        self._data_end = data_end

    def write_u8(
        self,
        address: int,
        value: int,
        *,
        source: SourceRef | None = None,
        pc: int | None = None,
    ) -> list[MemoryByteChange]:
        return self.write_bytes(address, bytes((value & 0xFF,)), source=source, pc=pc)

    def write_u16(
        self,
        address: int,
        value: int,
        *,
        source: SourceRef | None = None,
        pc: int | None = None,
    ) -> list[MemoryByteChange]:
        return self.write_bytes(
            address,
            (value & 0xFFFF).to_bytes(2, "little"),
            alignment=2,
            source=source,
            pc=pc,
        )

    def write_u32(
        self,
        address: int,
        value: int,
        *,
        source: SourceRef | None = None,
        pc: int | None = None,
    ) -> list[MemoryByteChange]:
        return self.write_bytes(
            address,
            (value & 0xFFFF_FFFF).to_bytes(4, "little"),
            alignment=4,
            source=source,
            pc=pc,
        )

    def restore(self, changes: list[MemoryByteChange] | tuple[MemoryByteChange, ...]) -> None:
        newly_allocated_pages = {
            change.address // PAGE_SIZE for change in changes if not change.page_was_present
        }
        for change in reversed(changes):
            if change.address // PAGE_SIZE in newly_allocated_pages:
                continue
            page, initialized = self._page(change.address, create=False, source=None, pc=None)
            assert page is not None and initialized is not None
            index = change.address & PAGE_MASK
            page[index] = change.old_value
            initialized[index] = int(change.old_initialized)
        for page_number in newly_allocated_pages:
            del self._pages[page_number]
            del self._initialized[page_number]

    def read_c_string(
        self,
        address: int,
        *,
        limit: int,
        source: SourceRef | None = None,
        pc: int | None = None,
    ) -> bytes:
        result = bytearray()
        for offset in range(limit):
            value = self.read_u8(address + offset, source=source, pc=pc)
            if value == 0:
                return bytes(result)
            result.append(value)
        raise RuntimeFault(
            "R206", f"string at 0x{address:08x} exceeds {limit} bytes", source, pc=pc
        )
