"""Functional test for the CalculiX package.

A build that merely links is not enough here: this recipe has shipped
executables that started fine and then produced non-converging or
locale-mangled results.  So run four models and look at the numbers.  Each
one fails on a specific defect this recipe patches or works around:

  smoketest.inp  one linear hexahedron, answer known in closed form
  contact.inp    CalculiX's test/contact4.inp, a face-to-face contact model;
                 fails outright when springforc_f2f.f's out-of-bounds write
                 is left in and the Fortran sources are built at -O3
  mohr.inp       CalculiX's test/mohr1.inp; exits 201 with "too many
                 cutbacks" without the mohrcoulomb.f sector-selection fix
  restart.inp    *RESTART,WRITE,OVERLAY over two steps; move.f renames the
                 restart file away and then fails to copy it when FFLAGS is
                 missing -cpp
"""

import math
import os
import re
import shutil
import subprocess
import sys

# u = -p * L / E = -1.0 * 100.0 / 210000.0, and the .dat file carries six
# significant digits, so compare at that precision
EXPECTED_UZ = -100.0 / 210000.0
SMOKE_TOLERANCE = 1.0e-6 * abs(EXPECTED_UZ)

# simple shear of 0.01 in a Mohr-Coulomb material that yields at zero stress
EXPECTED_PEEQ = 0.01 / math.sqrt(3.0)

# same criterion as CalculiX's own datcheck.pl: a value may deviate by up to
# 0.1% of the largest value in its block
CONTACT_TOLERANCE = 1.0e-3

NUMBER = re.compile(r"-?\d+\.\d+E[-+]\d+")

ccx = shutil.which("ccx")
if ccx is None:
    sys.exit("ccx is not on PATH")


def run(jobname, want_frd=True):
    completed = subprocess.run(
        [ccx, jobname],
        env=dict(os.environ, OMP_NUM_THREADS="1"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0:
        sys.exit(
            f"ccx {jobname} exited {completed.returncode}:\n{completed.stdout}"
        )
    with open(jobname + ".dat") as handle:
        dat = handle.read()
    texts = [(jobname + ".dat", dat)]
    if want_frd:
        with open(jobname + ".frd") as handle:
            texts.append((jobname + ".frd", handle.read()))
    for name, text in texts:
        if not text.strip():
            sys.exit(f"{name} is empty -- the solver wrote no results")
        # "-1.#IND", "NaN", "-nan(ind)": the solver diverged
        if re.search(r"nan|#ind|#inf", text, re.IGNORECASE):
            sys.exit(f"{name} contains a non-finite number:\n{text}")
        # " 0,00000E+00": the C runtime picked up the user's regional settings
        if re.search(r"\d,\d*[eE][-+]\d", text):
            sys.exit(f"{name} uses a comma as the decimal separator:\n{text}")
    return dat, completed.stdout


# 1. one element, exact answer
dat, _ = run("smoketest")
displacements = re.findall(
    r"^\s*([1-8])((?:\s+-?\d\.\d+E[-+]\d+){3})\s*$", dat, re.MULTILINE
)
if len(displacements) != 8:
    sys.exit(f"expected 8 nodal displacements, parsed {len(displacements)}:\n{dat}")
for node, values in displacements:
    uz = float(values.split()[2])
    expected = EXPECTED_UZ if int(node) > 4 else 0.0
    if abs(uz - expected) > SMOKE_TOLERANCE:
        sys.exit(f"smoketest node {node}: uz = {uz!r}, expected {expected!r}\n{dat}")

# 2. face-to-face contact, compared against CalculiX's own reference
dat, _ = run("contact")
with open("contact.dat.ref") as handle:
    reference = handle.read()

got = [float(value) for value in NUMBER.findall(dat)]
want = [float(value) for value in NUMBER.findall(reference)]
if len(got) != len(want):
    sys.exit(
        f"contact.dat holds {len(got)} numbers, the reference holds {len(want)};"
        f" the solver did not run the analysis to the end:\n{dat}"
    )
scale = CONTACT_TOLERANCE * max(abs(value) for value in want)
for index, (value, expected) in enumerate(zip(got, want)):
    if abs(value - expected) > scale:
        sys.exit(
            f"contact.dat value {index}: {value!r}, expected {expected!r}"
            f" (tolerance {scale!r})\n{dat}"
        )

# 3. Mohr-Coulomb, exact answer
dat, _ = run("mohr")
block = dat.split("equivalent plastic strain")
if len(block) != 2:
    sys.exit(f"mohr.dat has no equivalent plastic strain block:\n{dat}")
peeq = [
    float(value)
    for value in re.findall(
        r"^\s*\d+\s+\d+\s+(-?\d\.\d+E[-+]\d+)\s*$", block[1], re.MULTILINE
    )
]
if len(peeq) != 8:
    sys.exit(f"expected 8 PEEQ values, parsed {len(peeq)}:\n{dat}")
for value in peeq:
    if abs(value - EXPECTED_PEEQ) > CONTACT_TOLERANCE * EXPECTED_PEEQ:
        sys.exit(f"mohr PEEQ = {value!r}, expected {EXPECTED_PEEQ!r}\n{dat}")

# 4. *RESTART,WRITE,OVERLAY has to be able to overwrite its own file
_, output = run("restart", want_frd=False)
if re.search(r"cannot be renamed|Error opening source file", output):
    sys.exit(f"*RESTART,WRITE,OVERLAY failed:\n{output}")

print("CalculiX tests passed")
