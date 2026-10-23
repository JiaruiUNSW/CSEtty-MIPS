# Test coverage

Use this page to find tests when working on the engine. For supported
instructions and runtime behavior, see the [reference](SPEC.md); for setup
and test commands, see [Development](DEVELOPMENT.md).

## Where to add a regression

| Area | Tests | What they cover |
|---|---|---|
| Parsing and assembly | [core](../tests/test_csetty_mips_core.py), [contract](../tests/test_csetty_mips_contract.py) | Literals, expressions, local/global symbols, sections, entry points, and source errors |
| Data alignment | [alignment](../tests/test_csetty_mips_alignment.py) | Explicit and automatic alignment, aliases, constants, section/file boundaries, and runtime stores |
| Encodings and disassembly | [differential](../tests/test_csetty_mips_differential.py), [ISA](../tests/test_csetty_mips_isa.py) | Expected words for every declared real instruction, reserved fields, and decoded forms |
| Integer operations and control flow | [semantics](../tests/test_csetty_mips_semantics.py), [differential](../tests/test_csetty_mips_differential.py) | Signed/wrapping arithmetic, shifts, HI/LO, branches, jumps, and traps |
| Pseudo-instructions | [pseudo](../tests/test_csetty_mips_pseudo.py), [overloads](../tests/test_csetty_mips_overloads.py) | Immediate and shorter forms, symbolic operands, stack helpers, and assembler-temporary checks |
| Course-guide instruction forms | [26T2 guide](../tests/test_comp1521_26t2_guide.py) | Assembly of the forms listed in the COMP1521 26T2 guide |
| Memory | [core](../tests/test_csetty_mips_core.py), [contract](../tests/test_csetty_mips_contract.py), [differential](../tests/test_csetty_mips_differential.py) | Initialization, bounds, permissions, cross-page writes, and every byte offset for unaligned word operations |
| Floating-point transfers and syscalls | [ISA](../tests/test_csetty_mips_isa.py) | Raw register pairs, loads/stores, input/output, and reversal; not floating-point arithmetic |
| Syscalls | [syscalls](../tests/test_csetty_mips_syscalls.py), [contract](../tests/test_csetty_mips_contract.py) | Formatting, numeric prefix parsing, EOF, buffers, allocation, and exit status |
| Files | [filesystem](../tests/test_csetty_mips_filesystem.py) | Open modes, descriptors, path restrictions, staged writes, limits, and commit behavior |
| Debugger and reverse execution | [debugger](../tests/test_csetty_mips_debugger.py), [CLI](../tests/test_csetty_mips_cli.py), [core](../tests/test_csetty_mips_core.py) | Breakpoints, watchpoints, inspection, error recovery, and restoring registers, memory, input, and output |
| Command line | [CLI](../tests/test_csetty_mips_cli.py) | Arguments, input streaming, traces, encoded output, diagnostics, and exit codes |

Many runtime tests also check the state after an error or a reverse step.
These matter as much as the successful result: a failed instruction should
leave no partial register or memory changes. Filesystem tests check staged
writes and reversal separately from host-file commits.

## Comparisons with other simulators

[The SPIM test](../tests/test_csetty_mips_spim.py) runs a small original assembly
program and compares its output with SPIM when the executable is available.
The same fixture always runs against csetty-mips. SPIM is optional and is not
a package dependency.

The dated reports below record broader comparisons made for particular fixes:

- [Operand forms, August 2026](MIPSY_OVERLOAD_AUDIT_2026-08-19.md)
- [Data alignment, October 2026](ALIGNMENT_AUDIT_2026-10-21.md)

Their results apply to the cases and simulator versions tested, rather than
every possible program. The [reference notes](PROVENANCE.md) explain how those
comparisons were made and which sources informed the implementation.

## CI and packages

[CI](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/.github/workflows/ci.yml)
runs Ruff, mypy, pytest, and package builds on
Python 3.11, 3.12, and 3.13. Check the latest workflow run for current results;
test counts in historical reports describe those releases.

Package checks include a wheel and source archive build plus strict metadata
validation. The release process also checks installation and the CLI/Python
entry points. License files, the component notice, and `py.typed` belong in the
wheel; the source archive includes tests and documentation.

The browser debugger is maintained separately. Its UI and deployment checks
do not replace engine tests, and engine tests alone do not cover browser behavior.
