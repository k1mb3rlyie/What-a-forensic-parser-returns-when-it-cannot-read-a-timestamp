#!/usr/bin/env python3
"""Prove the manuscript checker actually catches errors.

The paper states that its figure checker was validated by injecting known
errors and confirming each was caught. That claim is only worth making if a
reader can reproduce it, so the injection lives here rather than in somebody's
terminal history. Each mutation below is one error of a different kind, applied
to a copy of the manuscript; the checker must notice every one, and the
unmutated original is reported first so there is no doubt what it started from.

A mutation whose pattern is absent from the manuscript is reported as SKIPPED
rather than counted as a pass, because a mutation that never applied has tested
nothing. That distinction is the whole point: a validation harness that quietly
does nothing is the same defect this study is about.

Usage:
    python verify_checker.py paper.md
    python verify_checker.py paper.md --checker check_paper.py
    python verify_checker.py paper.md --show-baseline
"""

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile

VERSION = "4: detection by what the checker named, not by how many it counted"

# (name, pattern, replacement, what class of error this represents)
MUTATIONS = [
    ("rate off by 0.1", r"38\.5", "38.6",
     "a reported rate altered in the last digit"),
    ("observation total", r"1,716|1\{,\}716", "1,717",
     "an aggregate count altered by one"),
    ("per-reader count", r"\b78\b", "79",
     "a per-run count altered"),
    ("case identifier", r"\bT4\b", "T5",
     "a case label swapped for another real label"),
    # Two hex mutations rather than one, because the journal manuscript
    # tabulates every stored value while the six-page conference version
    # quotes only the saturated one. Whichever is absent reports SKIPPED, so
    # the harness states which manuscript it was able to test rather than
    # appearing to have tested both.
    ("hex, epoch value", r"0x019DB1DED53E8000", "0x019DB1DED53E8001",
     "a stored value altered in its last nibble"),
    ("hex, too-large", r"0xFFFFFFFFFFFFFFFF", "0xFFFFFFFFFFFFFFFE",
     "the saturated value altered in its last nibble"),
    ("release date", r"2019-12-28|28 December 2019", "2019-12-29",
     "a provenance date moved by one day"),
    ("version string", r"\b0\.4\.3\b", "0.4.4",
     "a version number altered"),
    ("em-dash inserted", "The trigger is", "The trigger" + chr(0x2014) + "is",
     "a punctuation rule the checker also enforces"),
]

# Mutations whose pattern is a plain string rather than a regex, so that a
# replacement containing no backslashes cannot be misread as a group
# reference.
LITERAL = {"em-dash inserted"}


def run_checker(checker, manuscript):
    """(exit code, output) for one checker run.

    Deliberately no count is extracted. An earlier version of this harness
    compared the number of problems reported before and after each mutation,
    and that is unsound: a checker that reports distinct unmatched figures
    gives the same count when a mutation REPLACES a figure that was already
    unmatched, so a detection the checker had plainly made was recorded as a
    miss. The count is a lossy summary of the finding. What the checker named
    is the finding.
    """
    proc = subprocess.run(
        [sys.executable, checker, manuscript],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def normalise(out, manuscript):
    """Strip anything that varies with the file's location, not its content."""
    out = out.replace(manuscript, "<manuscript>")
    out = out.replace(os.path.basename(manuscript), "<manuscript>")
    # Durations and temp paths would otherwise register as differences.
    out = re.sub(r"/tmp/[\w./-]+", "<tmp>", out)
    out = re.sub(r"\d+\.\d+\s*(?:s|ms|sec)\b", "<elapsed>", out)
    return out


def findings(out):
    """The lines that look like a reported finding, for display."""
    keep = []
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^[A-Z][A-Z \-]{4,}\(\d+", s) or s.startswith(("FAIL", "MISSING")):
            keep.append(s)
        elif line.startswith("  ") and keep:
            keep.append("    " + s[:76])
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manuscript")
    ap.add_argument("--checker", default="check_paper.py")
    ap.add_argument("--show-baseline", action="store_true",
                    help="print what the checker already reports before any mutation")
    args = ap.parse_args()

    for path in (args.manuscript, args.checker):
        if not os.path.exists(path):
            sys.exit("no such file: %s" % path)

    print("verify_checker %s" % VERSION)
    src = open(args.manuscript, encoding="utf-8").read()

    code, base_out = run_checker(args.checker, args.manuscript)
    base_norm = normalise(base_out, args.manuscript)
    base_findings = findings(base_out)

    print("baseline: exit %d on the unmutated manuscript, %d reported line(s)"
          % (code, len(base_findings)))
    if code != 0:
        print("  it does not pass cleanly. That does not invalidate what")
        print("  follows: each mutation is judged by what the checker says")
        print("  about the mutated value, not by a total.")
        if not args.show_baseline:
            print("  run with --show-baseline to see the existing complaints")
    if args.show_baseline and base_findings:
        print()
        print("  existing complaints:")
        for line in base_findings[:40]:
            print("   " + line)
        if len(base_findings) > 40:
            print("    ... %d more" % (len(base_findings) - 40))
    print()

    print("  %-18s %-6s %-6s %s" % ("mutation", "sites", "exit", "verdict"))
    caught = skipped = missed = 0
    details = []
    tmp = tempfile.mkdtemp(prefix="verify_checker_")
    try:
        for name, pattern, repl, _why in MUTATIONS:
            # Every occurrence is corrupted, not just the first. Mutating one
            # site is a weak test: the first match is often a prose mention
            # that no assertion anchors on, and the result then says more
            # about where the match landed than about the checker.
            if name in LITERAL:
                n = src.count(pattern)
                mutated = src.replace(pattern, repl)
            else:
                mutated, n = re.subn(pattern, repl, src)
            if n == 0:
                print("  %-18s %-6s %-6s SKIPPED, pattern absent"
                      % (name, "-", "-"))
                skipped += 1
                continue

            path = os.path.join(tmp, os.path.basename(args.manuscript))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(mutated)
            code, out = run_checker(args.checker, path)

            # Strongest evidence: the checker printed the value we injected.
            named = repl.strip() in out
            # Weaker but still decisive: its report changed at all.
            changed = normalise(out, path) != base_norm

            if named:
                verdict = "caught, named the value"
            elif changed:
                verdict = "caught, report changed"
            else:
                verdict = "NOT CAUGHT"

            print("  %-18s %-6d %-6s %s" % (name, n, code, verdict))

            if named or changed:
                caught += 1
                if not named:
                    diff = [l for l in difflib.unified_diff(
                        base_norm.splitlines(), normalise(out, path).splitlines(),
                        lineterm="", n=0) if l.startswith("+") and not l.startswith("+++")]
                    details.append((name, diff[:4]))
            else:
                missed += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if details:
        print()
        print("  what changed where the value was not quoted back:")
        for name, diff in details:
            print("    %s" % name)
            for line in diff:
                print("      %s" % line[1:].strip()[:76])

    print()
    print("  %d of %d applicable mutations caught; %d skipped"
          % (caught, caught + missed, skipped))
    if skipped:
        print("  a skipped mutation means its pattern is not in this")
        print("  manuscript, so that class of error was not tested here")
    if missed:
        print("  a missed mutation means the checker does not cover that class")
        print("  of error, and the paper should not claim that it does")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())