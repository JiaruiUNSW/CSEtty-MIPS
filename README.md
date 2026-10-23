# csetty-mips

`csetty-mips` is a MIPS32 assembler, simulator, and debugger written in Python.
Run assembly programs, set breakpoints, inspect registers and memory, and
step backward through execution.

**[Try the web debugger](https://mips.jiarui.academy/)**

MIPS Studio uses the same engine with a source editor, terminal, and interactive
control-flow map. Navigate between functions and fold branches and loops to
make larger programs easier to follow. Programs run locally in your browser,
with no installation needed.

New to the debugger? [Start with a short walkthrough](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/docs/GETTING_STARTED.md).

## Install

For the command-line tool or Python library, install from
[PyPI](https://pypi.org/project/csetty-mips/). Requires Python 3.11 or newer.

```sh
python3 -m pip install csetty-mips
```

## Command line

```sh
csetty-mips program.s                 # Run a program
csetty-mips --interactive program.s   # Open the debugger
csetty-mips --check program.s         # Check assembly without running
csetty-mips program.s -- arg1 arg2    # Pass arguments to the program
```

In the debugger, use `step` and `back` to move through execution, `break` to
set breakpoints, and `print` to inspect values. Run `csetty-mips --help` for
more options.

## Python API

```python
from csetty_mips import Machine, SourceUnit, assemble

source = """
.text
main:
    li $a0, 42
    li $v0, 1
    syscall
    jr $ra
"""

program = assemble([SourceUnit("answer.s", source)])
machine = Machine(program)
machine.run()
print(machine.io.output.decode())  # 42
```

See the [reference](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/docs/SPEC.md) for supported instructions, syscalls, and
debugger commands, or [releases](https://github.com/JiaruiUNSW/CSEtty-MIPS/releases)
for version history and downloads.

## License

MPL-2.0. See [LICENSE](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/LICENSE)
and [NOTICE](https://github.com/JiaruiUNSW/CSEtty-MIPS/blob/main/NOTICE).
