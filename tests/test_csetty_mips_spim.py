from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from csetty_mips import Machine, SourceUnit, assemble

FIXTURE = Path(__file__).parent / "fixtures" / "csetty_mips" / "spim_overlap.s"
EXPECTED = b"15|-128|14\n"


def test_independent_overlap_fixture_has_the_expected_csetty_mips_result() -> None:
    program = assemble([SourceUnit(str(FIXTURE), FIXTURE.read_text(encoding="utf-8"))])
    machine = Machine(program, argv=(str(FIXTURE),))
    assert machine.run() == 0
    assert machine.io.output == EXPECTED


def test_overlap_fixture_against_spim_when_installed() -> None:
    spim = shutil.which("spim")
    if spim is None:
        pytest.skip("SPIM is an optional black-box oracle and is not installed")
    completed = subprocess.run(
        [spim, "-quiet", "-file", str(FIXTURE)],
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0
    assert completed.stdout.endswith(EXPECTED)
