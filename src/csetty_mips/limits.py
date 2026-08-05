from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limits:
    max_source_bytes: int = 1_048_576
    max_statements: int = 250_000
    max_symbols: int = 100_000
    max_text_words: int = 64 * 1024
    max_data_bytes: int = 1024 * 1024
    max_kernel_text_words: int = 16 * 1024
    max_kernel_data_bytes: int = 1024 * 1024
    max_stack_bytes: int = 256 * 1024
    max_memory_pages: int = 8192
    max_steps: int = 10_000_000
    max_history: int = 10_000
    max_output_bytes: int = 4 * 1024 * 1024
    max_input_bytes: int = 16 * 1024 * 1024
    max_input_token_bytes: int = 1024 * 1024
    max_string_bytes: int = 1 * 1024 * 1024
    max_open_files: int = 64
    max_path_bytes: int = 4096
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_file_bytes: int = 64 * 1024 * 1024


DEFAULT_LIMITS = Limits()
