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

Then two axisymmetric models with rotational DOFs, which such elements do not
have.  gen3dboun.f and gen3dforc.f send a rotational SPC or moment on a plane
or axisymmetric node into their mean rotation code, whose loop bounds are set
only for shells and beams, so ccx indexes memory with whatever is on the
stack.  axirot.inp fixes DOFs 4 to 6 on its base, as the model in
FreeCAD/FreeCAD#10865 does, which dies silently after "STEP 1" on Windows;
with integers poisoned by -finit-integer it segfaults at that point on macOS
too, and otherwise builds a meaningless MPC there that happens to change
nothing.  So it has to say it ignored the SPCs, and get the closed-form
answer.  axirotload.inp puts a moment on a node, which crashes unpatched ccx
on macOS as built; it has to stop with an error instead.

bleedtap.inp is a gas network bleed tapping: orifice.f passed its curve
number to cd_bleedtapping.f as a real*8 where an integer is read, so no
curve was used and printing the element summary stopped ccx.

contact.inp is also run with its contact made LINEAR and, as the same
straight line, TABULAR: springforc_f2f.f and springstiff_f2f.f passed an
82-entry plconloc to materialdata_sp.f, which writes entries 801 and 802,
and read the curve length from entry 81, so every face-to-face model with a
tabular pressure-overclosure crashed or failed to converge.

Last, smoketest.inp is broken in seven ways a hand-edited deck can be --
element nodes that are 0 or undefined, no *NODE card, node number 0,
*END STEP without *STEP, a section on undefined elements, a negative
degree of freedom -- and every one has to be rejected with an *ERROR and
exit code 201.  Fuzzing such variants of 518 decks found 71 places where
ccx instead crashed, hung or silently worked on memory it did not own.

hcfnoinput.inp is an *HCF card without INPUT=.  hcfs.f called inputerror.f
without its ier argument, so reporting the error stored through a bogus
pointer and ccx segfaulted; it has to exit with the error message.

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

# axirot.inp: the same load on a cylinder of radius 10; ccx reports ur for the
# faces of the 2 degree wedge it models a CAX element with, along the r axis
EXPECTED_UR = 0.3 * 1.0 * 10.0 / 210000.0 * math.cos(math.radians(1.0))

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

# 7. rotational SPCs on an axisymmetric model are ignored, with a warning
dat, output = run("axirot", want_frd=False)
if output.count("*WARNING in gen3dboun") != 6:
    sys.exit(
        "ccx did not report ignoring the 6 rotational SPCs of axirot.inp;"
        " fix-2d-rotational-dofs.patch did not take effect:\n" + output
    )
displacements = re.findall(
    r"^\s*([1-4])((?:\s+-?\d\.\d+E[-+]\d+){3})\s*$", dat, re.MULTILINE
)
if len(displacements) != 4:
    sys.exit(f"expected 4 nodal displacements, parsed {len(displacements)}:\n{dat}")
for node, values in displacements:
    ur, uz, _ = (float(value) for value in values.split())
    expected_ur = EXPECTED_UR if node in "23" else 0.0
    expected_uz = EXPECTED_UZ if node in "34" else 0.0
    if (
        abs(ur - expected_ur) > 1.0e-5 * EXPECTED_UR
        or abs(uz - expected_uz) > SMOKE_TOLERANCE
    ):
        sys.exit(
            f"axirot node {node}: (ur, uz) = ({ur!r}, {uz!r}), expected"
            f" ({expected_ur!r}, {expected_uz!r})\n{dat}"
        )

# 8. a moment on an axisymmetric model is an input error, not a crash
completed = subprocess.run(
    [ccx, "axirotload"],
    env=dict(os.environ, OMP_NUM_THREADS="1"),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)
if completed.returncode != 201 or "*ERROR in gen3dforc" not in completed.stdout:
    sys.exit(
        f"ccx axirotload exited {completed.returncode}; expected 201 and"
        f" \"*ERROR in gen3dforc\":\n{completed.stdout}"
    )

# 9. an input error in *HCF is reported, not a segfault
completed = subprocess.run(
    [ccx, "hcfnoinput"],
    env=dict(os.environ, OMP_NUM_THREADS="1"),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)
if completed.returncode != 201 or "no input file specified" not in completed.stdout:
    sys.exit(
        f"ccx hcfnoinput exited {completed.returncode}; expected 201 and"
        f" \"no input file specified\":\n{completed.stdout}"
    )

# 10. a bleed tapping has to use the discharge curve it was given
run("bleedtap")
with open("bleedtap.net") as handle:
    net = handle.read()
summary = re.search(
    r"P2/P1 =\s*(\S+) , ps1pt1 =\s*(\S+) , DAB =\s*(\S+) , curve No =\s*(\d+)"
    r" , cd =\s*(\S+)",
    net,
)
if summary is None:
    sys.exit(f"bleedtap.net has no bleed tapping summary:\n{net}")
p2p1, ps1pt1, dab, curve, cd = summary.groups()
p2p1, ps1pt1, dab, cd = (float(v) for v in (p2p1, ps1pt1, dab, cd))
# the summary prints four significant digits
if curve != "1" or abs(dab - (1 - p2p1) / (1 - ps1pt1)) > 1.0e-3 * dab:
    sys.exit(f"bleedtap: curve {curve}, DAB {dab!r} from P2/P1 {p2p1!r}:\n{net}")
expected_cd = 0.167 + (0.310 - 0.167) * (dab - 0.24) / (0.52 - 0.24)
if not 0.24 < dab < 0.52 or abs(cd - expected_cd) > 1.0e-3 * expected_cd:
    sys.exit(f"bleedtap: cd {cd!r}, expected {expected_cd!r} at DAB {dab!r}:\n{net}")

# 11. face-to-face contact with a tabular pressure-overclosure curve has to
#     give what the same straight line gives as PRESSURE-OVERCLOSURE=LINEAR
with open("contact.inp") as handle:
    contact = handle.read()
hard = "*SURFACE BEHAVIOR,PRESSURE-OVERCLOSURE=HARD\n**1.E7,1.\n"
if hard not in contact:
    sys.exit("contact.inp no longer has the contact definition this test edits")
with open("contactlin.inp", "w") as handle:
    handle.write(contact.replace(
        hard, "*SURFACE BEHAVIOR,PRESSURE-OVERCLOSURE=LINEAR\n1.E7,1.E-3\n"))
with open("contacttab.inp", "w") as handle:
    # pressure, overclosure
    handle.write(contact.replace(
        hard, "*SURFACE BEHAVIOR,PRESSURE-OVERCLOSURE=TABULAR\n0.,0.\n1.E7,1.\n"))
linear, _ = run("contactlin")
tabular, _ = run("contacttab")
got = [float(v) for v in NUMBER.findall(tabular)]
want = [float(v) for v in NUMBER.findall(linear)]
scale = CONTACT_TOLERANCE * max(abs(v) for v in want)
if len(got) != len(want) or any(abs(a - b) > scale for a, b in zip(got, want)):
    sys.exit(f"tabular overclosure differs from linear:\n{tabular}\nlinear:\n{linear}")

# 12. malformed input has to be rejected with an *ERROR, not crash or run
with open("smoketest.inp") as handle:
    smoke = handle.read()
first_node, element = "8,   0., 100., 100.", "1, 1, 2, 3, 4, 5, 6, 7, 8"
section = "*SOLID SECTION, ELSET=Eall"
if first_node not in smoke or element not in smoke or section not in smoke:
    sys.exit("smoketest.inp no longer has the lines test 12 edits")
malformed = {
    # an element node that is 0, or beyond every defined node
    "badnode0": smoke.replace(element, "1, 1, 2, 3, 4, 5, 6, 7, 0"),
    "badnode99": smoke.replace(element, "1, 1, 2, 3, 4, 5, 6, 7, 99"),
    # no *NODE card at all
    "badnonode": smoke[:smoke.index("*NODE")] + smoke[smoke.index("*ELEMENT"):],
    # a *NODE line with node number 0
    "badnodenum": smoke.replace(first_node, "0,   0., 100., 100."),
    # *END STEP without *STEP
    "badnostep": smoke.replace("*STEP\n", ""),
    # a section on a set with elements that do not exist
    "badelset": smoke.replace(section, "*ELSET, ELSET=Ebad\n1, 5\n" + section[:-4] + "Ebad"),
    # a negative degree of freedom
    "baddof": smoke.replace("Nfix, 3, 3, 0.", "Nfix, -3, 3, 0."),
}
for name, deck in malformed.items():
    with open(name + ".inp", "w") as handle:
        handle.write(deck)
    try:
        completed = subprocess.run(
            [ccx, name],
            env=dict(os.environ, OMP_NUM_THREADS="1"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        sys.exit(f"ccx {name} did not finish in 300 s on malformed input")
    if completed.returncode != 201 or "*ERROR" not in completed.stdout:
        sys.exit(
            f"ccx {name} exited {completed.returncode} on malformed input;"
            f" expected 201 and an *ERROR:\n{completed.stdout}"
        )

print("CalculiX tests passed")
