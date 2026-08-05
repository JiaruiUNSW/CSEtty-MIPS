from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .limits import Limits

O_ACCMODE = 0o3
O_CREAT = 0o100
O_EXCL = 0o200
O_TRUNC = 0o1000
O_APPEND = 0o2000
_SUPPORTED_FLAGS = O_ACCMODE | O_CREAT | O_EXCL | O_TRUNC | O_APPEND


@dataclass(frozen=True, slots=True)
class OpenFile:
    path: str
    position: int
    readable: bool
    writable: bool
    append: bool


@dataclass(frozen=True, slots=True)
class FileSystemState:
    files: tuple[tuple[str, bytes], ...] = ()
    handles: tuple[tuple[int, OpenFile], ...] = ()
    dirty: frozenset[str] = frozenset()


class VirtualFileSystem:
    """A reversible file layer that commits only to an explicitly selected root."""

    def __init__(
        self,
        limits: Limits,
        *,
        root: Path | None = None,
        initial_files: Mapping[str, bytes] | None = None,
    ) -> None:
        self.limits = limits
        self.root = root.resolve(strict=True) if root is not None else None
        if self.root is not None and not self.root.is_dir():
            raise NotADirectoryError(self.root)
        files: dict[str, bytes] = {}
        for name, payload in (initial_files or {}).items():
            normalized = self._normalize(name)
            if normalized is None or self._path_size(normalized) > limits.max_path_bytes:
                raise ValueError(f"invalid virtual file path: {name!r}")
            files[normalized] = bytes(payload)
        if any(len(payload) > limits.max_file_bytes for payload in files.values()):
            raise ValueError("an initial virtual file exceeds the per-file limit")
        if sum(map(len, files.values())) > limits.max_total_file_bytes:
            raise ValueError("initial virtual files exceed the total file limit")
        self.state = FileSystemState(files=tuple(sorted(files.items())))
        self._host_cache: dict[str, bytes | None] = {}

    @staticmethod
    def _normalize(path: str) -> str | None:
        if not path or "\\" in path or "\x00" in path:
            return None
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
            return None
        return parsed.as_posix()

    @staticmethod
    def _path_size(path: str) -> int:
        try:
            return len(path.encode("utf-8"))
        except UnicodeEncodeError:
            return 1 << 63

    def _candidate(self, path: str, *, must_exist: bool) -> Path | None:
        if self.root is None:
            return None
        candidate = self.root.joinpath(*PurePosixPath(path).parts)
        current = self.root
        parts = PurePosixPath(path).parts
        for part in parts[:-1]:
            current /= part
            if not current.exists() or not current.is_dir() or current.is_symlink():
                return None
        if must_exist:
            if not candidate.exists() or not candidate.is_file() or candidate.is_symlink():
                return None
        elif candidate.exists() and (not candidate.is_file() or candidate.is_symlink()):
            return None
        try:
            candidate.parent.resolve(strict=True).relative_to(self.root)
        except (OSError, ValueError):
            return None
        return candidate

    def _load_host(self, path: str) -> bytes | None:
        if path in self._host_cache:
            return self._host_cache[path]
        candidate = self._candidate(path, must_exist=True)
        if candidate is None:
            payload = None
        else:
            try:
                payload = candidate.read_bytes()
            except OSError:
                payload = None
            if payload is not None and len(payload) > self.limits.max_file_bytes:
                payload = None
        self._host_cache[path] = payload
        return payload

    @staticmethod
    def _replace_handle(
        handles: dict[int, OpenFile], descriptor: int, handle: OpenFile
    ) -> tuple[tuple[int, OpenFile], ...]:
        handles[descriptor] = handle
        return tuple(sorted(handles.items()))

    def snapshot(self) -> FileSystemState:
        return self.state

    def restore(self, state: FileSystemState) -> None:
        self.state = state

    def open(self, path: str, flags: int) -> int:
        normalized = self._normalize(path)
        mars_append = flags == 9
        if (
            normalized is None
            or self._path_size(normalized) > self.limits.max_path_bytes
            or flags < 0
            or (not mars_append and flags & ~_SUPPORTED_FLAGS)
        ):
            return -1
        access = 1 if mars_append else flags & O_ACCMODE
        if access == O_ACCMODE:
            return -1
        readable = access in {0, 2}
        writable = access in {1, 2}
        create = mars_append or flags == 1 or bool(flags & O_CREAT)
        truncate = bool(flags & O_TRUNC)
        append = mars_append or bool(flags & O_APPEND)
        exclusive = bool(flags & O_EXCL)
        if (truncate or append) and not writable:
            return -1
        handles = dict(self.state.handles)
        if len(handles) >= self.limits.max_open_files:
            return -1
        files = dict(self.state.files)
        payload = files.get(normalized)
        if payload is None:
            payload = self._load_host(normalized)
        existed = payload is not None
        if existed and create and exclusive:
            return -1
        if not existed:
            if not create:
                return -1
            if self.root is not None and self._candidate(normalized, must_exist=False) is None:
                return -1
            payload = b""
        assert payload is not None
        changed_on_open = not existed
        if truncate:
            payload = b""
            changed_on_open = True
        total = sum(len(value) for name, value in files.items() if name != normalized) + len(
            payload
        )
        if total > self.limits.max_total_file_bytes:
            return -1
        files[normalized] = payload
        handle = OpenFile(
            normalized,
            len(payload) if append else 0,
            readable,
            writable,
            append,
        )
        dirty = self.state.dirty | ({normalized} if changed_on_open else set())

        descriptor = next(
            value for value in range(3, 3 + self.limits.max_open_files + 1) if value not in handles
        )
        handles[descriptor] = handle
        self.state = FileSystemState(
            files=tuple(sorted(files.items())),
            handles=tuple(sorted(handles.items())),
            dirty=frozenset(dirty),
        )
        return descriptor

    def read(self, descriptor: int, maximum: int) -> bytes | None:
        handles = dict(self.state.handles)
        handle = handles.get(descriptor)
        if handle is None or not handle.readable or maximum < 0:
            return None
        payload = dict(self.state.files)[handle.path]
        selected = payload[handle.position : handle.position + maximum]
        updated = OpenFile(
            handle.path,
            handle.position + len(selected),
            handle.readable,
            handle.writable,
            handle.append,
        )
        self.state = FileSystemState(
            files=self.state.files,
            handles=self._replace_handle(handles, descriptor, updated),
            dirty=self.state.dirty,
        )
        return selected

    def write(self, descriptor: int, payload: bytes) -> int:
        handles = dict(self.state.handles)
        handle = handles.get(descriptor)
        if handle is None or not handle.writable:
            return -1
        files = dict(self.state.files)
        old = files[handle.path]
        position = len(old) if handle.append else handle.position
        end = position + len(payload)
        if end > self.limits.max_file_bytes:
            return -1
        total = sum(len(value) for name, value in files.items() if name != handle.path) + max(
            len(old), end
        )
        if total > self.limits.max_total_file_bytes:
            return -1
        updated_payload = old[:position] + payload
        if end < len(old):
            updated_payload += old[end:]
        files[handle.path] = updated_payload
        updated_handle = OpenFile(
            handle.path,
            end,
            handle.readable,
            handle.writable,
            handle.append,
        )
        self.state = FileSystemState(
            files=tuple(sorted(files.items())),
            handles=self._replace_handle(handles, descriptor, updated_handle),
            dirty=self.state.dirty | {handle.path},
        )
        return len(payload)

    def close(self, descriptor: int) -> bool:
        handles = dict(self.state.handles)
        if descriptor not in handles:
            return False
        del handles[descriptor]
        self.state = FileSystemState(
            files=self.state.files,
            handles=tuple(sorted(handles.items())),
            dirty=self.state.dirty,
        )
        return True

    def file_bytes(self, path: str) -> bytes | None:
        normalized = self._normalize(path)
        return None if normalized is None else dict(self.state.files).get(normalized)

    def commit(self) -> int:
        if not self.state.dirty:
            return 0
        if self.root is None:
            raise RuntimeError("virtual filesystem has no host root")
        files = dict(self.state.files)
        committed = 0
        for path in sorted(self.state.dirty):
            candidate = self._candidate(path, must_exist=False)
            if candidate is None:
                raise OSError(f"unsafe filesystem target: {path}")
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=candidate.parent, delete=False) as temporary:
                    temporary_name = temporary.name
                    temporary.write(files[path])
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, candidate)
                temporary_name = None
            finally:
                if temporary_name is not None:
                    with suppress(FileNotFoundError):
                        Path(temporary_name).unlink()
            committed += 1
        self.state = FileSystemState(
            files=self.state.files,
            handles=self.state.handles,
            dirty=frozenset(),
        )
        return committed
