# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 csetty-mips contributors
"""Independent educational MIPS32 assembler, simulator, and debugger."""

from .assembler import assemble
from .debugger import Debugger
from .errors import AssemblyError, CsettyMipsError, ParseError, RuntimeFault
from .limits import DEFAULT_LIMITS, Limits
from .machine import Machine
from .model import Program, SourceUnit

__all__ = [
    "DEFAULT_LIMITS",
    "AssemblyError",
    "CsettyMipsError",
    "Debugger",
    "Limits",
    "Machine",
    "ParseError",
    "Program",
    "RuntimeFault",
    "SourceUnit",
    "assemble",
]

__version__ = "0.1.1"
