"""Functional test for the CalculiX package.

A build that merely links is not enough here: this recipe has shipped
executables that started fine and then produced non-converging or
locale-mangled results.  So run two models and look at the numbers.

  smoketest.inp  one linear hexahedron, answer known in closed form
  contact.inp    CalculiX's own test/contact4.inp, a nonlinear face-to-face
                 contact model, compared against its shipped reference
"""

import os
import re
import shutil
import subprocess
import sys

# u = -p * L / E = -1.0 * 100.0 / 210000.0, and the .dat file carries six
# significant digits, so compare at that precision
EXPECTED_UZ = -100.0 / 210000.0
SMOKE_TOLERANCE = 1.0e-6 * abs(EXPECTED_UZ)

# same criterion as CalculiX's own datcheck.pl: a value may deviate by up to
# 0.1% of the largest value in its block
CONTACT_TOLERANCE = 1.0e-3

NUMBER = re.compile(r"-?\d+\.\d+E[-+]\d+")

ccx = shutil.which("ccx")
if ccx is None:
    sys.exit("ccx is not on PATH")


def run(jobname):
    subprocess.run(
        [ccx, jobname], check=True, env=dict(os.environ, OMP_NUM_THREADS="1")
    )
    with open(jobname + ".dat") as handle:
        dat = handle.read()
    with open(jobname + ".frd") as handle:
        frd = handle.read()
    for name, text in ((jobname + ".dat", dat), (jobname + ".frd", frd)):
        if not text.strip():
            sys.exit(f"{name} is empty -- the solver wrote no results")
        # "-1.#IND", "NaN", "-nan(ind)": the solver diverged
        if re.search(r"nan|#ind|#inf", text, re.IGNORECASE):
            sys.exit(f"{name} contains a non-finite number:\n{text}")
        # " 0,00000E+00": the C runtime picked up the user's regional settings
        if re.search(r"\d,\d*[eE][-+]\d", text):
            sys.exit(f"{name} uses a comma as the decimal separator:\n{text}")
    return dat


# 1. one element, exact answer
dat = run("smoketest")
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

# 2. nonlinear contact, compared against CalculiX's own reference
dat = run("contact")
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

print("CalculiX tests passed")
