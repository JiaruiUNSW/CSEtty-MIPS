# Working on csetty-mips

For running programs, start with [Getting started](GETTING_STARTED.md). This
page is for changing the engine, tests, or documentation.

## Set up a checkout

Use Python 3.11 or newer. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.

The parser, assembler, machine, and debugger live in `src/csetty_mips`.
Tests are in `tests`; [Test coverage](ACCEPTANCE_MATRIX.md) points to the
relevant files for each area.

## Make and check a change

For a bug fix, add a small assembly program that reproduces the problem and
check its result in a regression test. Include nearby edge cases where they
matter: signed values, aliases, an invalid operand, or stepping backward.

Run the relevant test file while working, then the full checks before opening
a pull request:

```sh
python -m pytest tests/test_csetty_mips_alignment.py -q
ruff check src tests
mypy src/csetty_mips
python -m pytest -q
python -m build
```

The first command is an example for alignment changes; choose the test file for
your change. CI also builds and checks distributions on Python 3.11, 3.12, and
3.13. The optional comparison test runs when `spim` is on `PATH`; otherwise
that one test is skipped.

When changing behavior, update the relevant part of the [reference](SPEC.md).
Keep examples small enough that a reader can understand them without a full
assignment or test harness. For documentation changes, run the examples and
check links as well as proofreading the text.

Use original examples and tests. The [reference notes](PROVENANCE.md) record
the project's implementation sources and comparison history; keep that record
up to date when adding a new external reference.

## Report a bug

Include the package version (`csetty-mips --version`), a short assembly example,
any input it needs, the output or error you got, and what you expected. For a
browser issue, include the engine version shown in the footer and your browser.
Share only code you have permission to publish.

## Prepare a release

Documentation-only changes do not need a version bump. When a package release
is needed, follow [Releasing](RELEASING.md) after the pull request has passed
review and CI. Publishing a GitHub Release also publishes to PyPI.
