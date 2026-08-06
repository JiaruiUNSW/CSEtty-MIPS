# csetty-mips

`csetty-mips` is an independently implemented, typed MIPS32 teaching
assembler, simulator, disassembler, and time-travel debugger. It is the MIPS
runtime used by CSEExamTTY, but is developed and released as a standalone
Python package.

This project is not a fork, port, or redistribution of `insou22/mipsy`. It
contains no upstream mipsy source, binary, tests, generated files, or copied
diagnostic text. The [provenance record](docs/PROVENANCE.md) documents the
clean-room boundary and public architectural references.

The project is not made, managed, endorsed, or authenticated by UNSW or the
UNSW School of Computer Science and Engineering.

## Install

Python 3.11 or newer is required.

```sh
python3 -m pip install git+https://github.com/JiaruiUNSW/CSEtty-MIPS.git@v0.1.0
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
resource-limit contracts are documented in the [specification](docs/SPEC.md).
The [acceptance matrix](docs/ACCEPTANCE_MATRIX.md) records executable coverage
and deliberate non-goals.

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
License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
