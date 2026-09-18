"""Functional test for the CalculiX package.

A build that merely links is not enough here: this recipe has shipped
executables that started fine and then produced non-converging or
locale-mangled results.  So run five models and look at the numbers.  Each
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

The contact model is then run a second time on four threads.  That checks the
multithreaded solver is wired up at all -- ccx says "Using up to N cpu(s) for
spooles" only when -DUSE_MT=1 and spoolesMT.a both took effect -- and that it
gets the right answer on a model small enough to be worth running here.

Last, cfd.inp -- CalculiX's test/coucylcent2.inp, a 320-node *CFD model with
MPCs -- runs on four threads.  Unpatched 2.23 split the boundary conditions
over the CFD threads and got it wrong in 17 of 20 runs at four threads, and it
created threads for every loop of every iteration, which made every small
*CFD model several times slower threaded than on one core.  The patches apply
the boundary conditions on one thread and keep a mesh this small on one
thread altogether, so ccx has to say so, and the answer has to match the
reference.

The contact check is deliberately not the guard against SPOOLES' MT data races, which
returned silently wrong results on weakly ordered CPUs before spooles build
1006: a model this small does not reliably trip them.  spooles' own test does
that, on a problem sized for it.  What this catches is the build going quiet
-- the define dropped, the library unlinked, the link order reversed.
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


def run(jobname, want_frd=True, threads="1"):
    completed = subprocess.run(
        [ccx, jobname],
        env=dict(os.environ, OMP_NUM_THREADS=threads),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0:
        sys.exit(
            f"ccx {jobname} exited {completed.returncode} on {threads}"
            f" thread(s):\n{completed.stdout}"
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

want = [float(value) for value in NUMBER.findall(reference)]


def check_contact(dat, threads):
    got = [float(value) for value in NUMBER.findall(dat)]
    if len(got) != len(want):
        sys.exit(
            f"contact.dat holds {len(got)} numbers, the reference holds"
            f" {len(want)}, on {threads} thread(s); the solver did not run the"
            f" analysis to the end:\n{dat}"
        )
    scale = CONTACT_TOLERANCE * max(abs(value) for value in want)
    for index, (value, expected) in enumerate(zip(got, want)):
        if abs(value - expected) > scale:
            sys.exit(
                f"contact.dat value {index}: {value!r}, expected {expected!r}"
                f" (tolerance {scale!r}) on {threads} thread(s)\n{dat}"
            )


check_contact(dat, "1")

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

# 5. the same contact model on four threads: the multithreaded SPOOLES solver
#    has to be compiled in, and it has to get the same answer
dat, output = run("contact", threads="4")
if "cpu(s) for spooles" not in output:
    sys.exit(
        "ccx did not report the multithreaded spooles solver on 4 threads;"
        " -DUSE_MT=1 or spoolesMT.a did not take effect:\n" + output
    )
check_contact(dat, "4")

# 6. a small *CFD model on four threads: it has to stay on one thread, and it
#    has to reproduce CalculiX's own reference, block by block as datcheck.pl
#    compares it
dat, output = run("cfd", want_frd=False, threads="4")
if "Using up to 1 cpu(s) for CFD" not in output:
    sys.exit(
        "ccx threaded a 320-node *CFD model; fix-cfd-small-mesh-threads.patch"
        " did not take effect:\n" + output
    )
with open("cfd.dat.ref") as handle:
    reference = handle.read()


def cfd_blocks(text):
    # one list of numbers per " velocities ...", " static pressures ..." block
    return [NUMBER.findall(block) for block in re.split(r"\n \w[^\n]*for set", text)[1:]]


got_blocks, want_blocks = cfd_blocks(dat), cfd_blocks(reference)
if [len(block) for block in got_blocks] != [len(block) for block in want_blocks]:
    sys.exit(f"cfd.dat does not have the reference's blocks:\n{dat}")
for got_block, want_block in zip(got_blocks, want_blocks):
    got_block = [float(value) for value in got_block]
    want_block = [float(value) for value in want_block]
    scale = CONTACT_TOLERANCE * max(abs(value) for value in want_block)
    for value, expected in zip(got_block, want_block):
        if abs(value - expected) > scale:
            sys.exit(
                f"cfd.dat value {value!r}, expected {expected!r}"
                f" (tolerance {scale!r}) on 4 threads\n{dat}"
            )

print("CalculiX tests passed")
