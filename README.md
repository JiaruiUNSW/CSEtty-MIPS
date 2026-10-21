# csetty-mips

`csetty-mips` is an independently implemented, typed MIPS32 teaching
assembler, simulator, disassembler, and time-travel debugger. It is the MIPS
runtime used by CSEExamTTY, but is developed and released as a standalone
Python package.

Version `0.1.4` fixes labels before explicit/automatic alignment, including
standalone labels, aliases and exported symbols.
See [the alignment audit](docs/ALIGNMENT_AUDIT_2026-10-21.md) and the updated
[local specification](docs/SPEC.md) for this build's behavior.

This project is not a fork, port, or redistribution of `insou22/mipsy`. It
contains no upstream mipsy source, binary, tests, generated files, or copied
diagnostic text. The
[provenance record](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/v0.1.4/docs/PROVENANCE.md)
documents the clean-room boundary and public architectural references.

The project is not made, managed, endorsed, or authenticated by UNSW or the
UNSW School of Computer Science and Engineering.

## Install

Python 3.11 or newer is required.

Install the versioned release from PyPI:

```sh
python3 -m pip install csetty-mips==0.1.4
```

The same wheel is also available through GitHub Releases:

```sh
python3 -m pip install https://github.com/JiaruiUNSW/CSEtty-MIPS/releases/download/v0.1.4/csetty_mips-0.1.4-py3-none-any.whl
```

For an editable development checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Command line

```sh
csetty-mips program.s -- arg1 arg2
csetty-mips --check program.s
csetty-mips --hex-pad-zero program.s
csetty-mips --interactive program.s
csetty-mips                         # debugger; then use `load FILE...`
```

Strict initialization diagnostics are enabled by default. `--spim` (also
spelled `--relaxed`) makes uninitialized registers and memory read as zero for
compatibility-oriented runs. Sandboxed file syscalls require an explicit
`--fs-root DIR`.

## Python API

```python
from csetty_mips import Machine, SourceUnit, assemble

program = assemble(
    [SourceUnit("answer.s", ".text\nmain: li $a0, 42\nli $v0, 1\nsyscall\njr $ra\n")]
)
machine = Machine(program)
machine.run()
assert machine.io.output == b"42"
```

The supported instruction, directive, syscall, debugger, filesystem, and
resource-limit contracts are documented in the
[specification](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/v0.1.4/docs/SPEC.md).
The
[acceptance matrix](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/v0.1.4/docs/ACCEPTANCE_MATRIX.md)
records executable coverage and deliberate non-goals.

## Verify

```sh
ruff check src tests
mypy src/csetty_mips
pytest -q
python -m build
```

SPIM is an optional black-box oracle for one independently authored overlap
fixture; its absence causes one test to skip.

## License

The source code in this repository is licensed under the Mozilla Public
License 2.0. See
[LICENSE](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/v0.1.4/LICENSE) and
[NOTICE](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/v0.1.4/NOTICE).
