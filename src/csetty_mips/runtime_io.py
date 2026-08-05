from __future__ import annotations

import re
from collections.abc import Callable

from .errors import RuntimeFault, SourceRef


class RuntimeIO:
    def __init__(
        self,
        input_data: bytes = b"",
        *,
        output_limit: int,
        input_limit: int,
        token_limit: int,
        input_provider: Callable[[], bytes] | None = None,
        output_sink: Callable[[bytes], None] | None = None,
    ) -> None:
        if len(input_data) > input_limit:
            raise RuntimeFault("R311", f"program input exceeds {input_limit} bytes")
        self.input_buffer = bytearray(input_data)
        self.input_position = 0
        self.output = bytearray()
        self.output_limit = output_limit
        self.input_limit = input_limit
        self.token_limit = token_limit
        self.input_provider = input_provider
        self.output_sink = output_sink

    def _refill(self) -> bool:
        if self.input_provider is None:
            return False
        added = self.input_provider()
        if not added:
            return False
        if len(self.input_buffer) + len(added) > self.input_limit:
            raise RuntimeFault("R311", f"program input exceeds {self.input_limit} bytes")
        self.input_buffer.extend(added)
        return True

    def read_byte(self) -> int | None:
        while self.input_position >= len(self.input_buffer):
            if not self._refill():
                return None
        value = self.input_buffer[self.input_position]
        self.input_position += 1
        return value

    def _read_token(
        self, source: SourceRef | None, pc: int, description: str, eof_code: str
    ) -> bytes:
        value = self.read_byte()
        while value is not None and value in b" \t\n\r\v\f":
            value = self.read_byte()
        if value is None:
            raise RuntimeFault(
                eof_code, f"expected {description} but reached end of input", source, pc=pc
            )
        token = bytearray()
        while value is not None and value not in b" \t\n\r\v\f":
            if len(token) >= self.token_limit:
                raise RuntimeFault(
                    "R312",
                    f"input token exceeds {self.token_limit} bytes",
                    source,
                    pc=pc,
                )
            token.append(value)
            value = self.read_byte()
        return bytes(token)

    def read_int(self, source: SourceRef | None, pc: int) -> int:
        token = self._read_token(source, pc, "an integer", "R300")
        match = re.match(rb"[+-]?[0-9]+", token)
        if match is None:
            return 0
        parsed = int(match.group(0))
        if not -(1 << 31) <= parsed <= (1 << 31) - 1:
            raise RuntimeFault("R302", "input integer does not fit in 32 bits", source, pc=pc)
        return parsed

    def read_float(self, source: SourceRef | None, pc: int) -> float:
        token = self._read_token(source, pc, "a floating-point number", "R309")
        match = re.match(
            rb"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|inf(?:inity)?|nan)",
            token,
            re.IGNORECASE,
        )
        if match is None:
            return 0.0
        try:
            return float(match.group(0).decode("ascii"))
        except (UnicodeDecodeError, ValueError) as error:
            raise RuntimeFault(
                "R310", "input is not a floating-point number", source, pc=pc
            ) from error

    def read_line(self, maximum: int) -> bytes:
        result = bytearray()
        while len(result) < maximum:
            value = self.read_byte()
            if value is None:
                break
            result.append(value)
            if value == ord("\n"):
                break
        return bytes(result)

    def read_bytes(self, maximum: int) -> bytes:
        result = bytearray()
        while len(result) < maximum:
            value = self.read_byte()
            if value is None:
                break
            result.append(value)
        return bytes(result)

    def write(self, payload: bytes, source: SourceRef | None, pc: int) -> None:
        if len(self.output) + len(payload) > self.output_limit:
            raise RuntimeFault(
                "R303", f"program output exceeds {self.output_limit} bytes", source, pc=pc
            )
        self.output.extend(payload)
        if self.output_sink is not None:
            self.output_sink(payload)

    def restore(self, *, input_position: int, output_length: int) -> None:
        self.input_position = input_position
        del self.output[output_length:]
