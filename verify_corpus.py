#!/usr/bin/env python3
"""Record and check the exact bytes of the test corpus.

The thirteen files in cases/ are the measurement in this study. Every reported
figure is a statement about what a reader returned when handed these exact
bytes, so if a file changes in transit the figures stop meaning anything, and
nothing about the change need be visible: these are 298-byte binaries with no
internal checksum, and a single altered byte in a timestamp field still parses
and still returns a date, just not the date the manifest expects.

This script writes a hash of every corpus file to SHA256SUMS, and later checks
the corpus against that record. Run it with --write once, on the machine the
study was run on, and commit the result. Anyone cloning the repository runs it
with no argument and learns in a second whether they have the corpus the
figures describe.

It also re-derives the three timestamp offsets from the MS-SHLLINK header
layout and compares them against the manifest, because a corpus with the right
hashes but the wrong offsets would be a corpus generated from a wrong reading
of the specification.

Usage:
    python verify_corpus.py            # check against SHA256SUMS
    python verify_corpus.py --write    # create or replace SHA256SUMS
"""

import argparse
import hashlib
import json
import os
import sys

CORPUS = "cases"
RECORD = "SHA256SUMS"

# MS-SHLLINK 2.1: the ShellLinkHeader is 76 bytes, and the three FILETIME
# fields sit at these offsets. Stated here rather than imported so that this
# check does not depend on the generator being correct.
HEADER_SIZE = 76
OFFSETS = {"creation_time": 28, "access_time": 36, "write_time": 44}
ICON_INDEX_OFFSET = 56  # 0x38, signed 32-bit


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def corpus_files():
    if not os.path.isdir(CORPUS):
        sys.exit("no %s/ directory; run this from the repository root" % CORPUS)
    names = sorted(n for n in os.listdir(CORPUS) if n.endswith(".lnk"))
    if not names:
        sys.exit("no .lnk files in %s/" % CORPUS)
    return names


def check_layout():
    """Confirm the header layout the corpus was built against.

    Returns a list of complaints, empty if the layout is as expected.
    """
    problems = []
    print("  header layout")
    for field, off in OFFSETS.items():
        end = off + 8
        ok = end <= HEADER_SIZE
        print("    %-14s offset %2d, bytes %2d-%2d  %s"
              % (field, off, off, end - 1, "within header" if ok else "PAST HEADER"))
        if not ok:
            problems.append("%s runs past the %d-byte header" % (field, HEADER_SIZE))
    print("    %-14s offset %2d (0x%02X), signed 32-bit"
          % ("icon_index", ICON_INDEX_OFFSET, ICON_INDEX_OFFSET))

    path = os.path.join(CORPUS, "manifest.json")
    if not os.path.exists(path):
        problems.append("no manifest.json, so expected values cannot be confirmed")
        return problems

    manifest = json.load(open(path, encoding="utf-8"))
    cases = manifest.get("cases", {})
    print("    manifest records %d cases" % len(cases))

    # Every timestamp case must name all three fields, or the grader is
    # scoring against an incomplete expectation.
    for name, case in sorted(cases.items()):
        if case.get("kind") != "timestamp":
            continue
        fields = case.get("expected_fields", {})
        missing = [f for f in OFFSETS if f not in fields]
        if missing:
            problems.append("case %s has no expectation for %s"
                            % (name, ", ".join(missing)))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="create or replace %s" % RECORD)
    args = ap.parse_args()

    names = corpus_files()
    print("corpus: %d .lnk files in %s/" % (len(names), CORPUS))
    print()

    problems = check_layout()
    print()

    if args.write:
        lines = ["%s  %s\n" % (digest(os.path.join(CORPUS, n)), n) for n in names]
        with open(RECORD, "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(lines)
        print("  wrote %s, %d entries" % (RECORD, len(lines)))
        for line in lines:
            print("    " + line.rstrip())
        print()
        if problems:
            print("  but the layout check complained, so this record describes")
            print("  a corpus that may not match the specification:")
            for p in problems:
                print("    %s" % p)
            return 1
        print("  commit this file. It is how anyone else proves they have the")
        print("  same bytes the reported figures describe.")
        return 0

    if not os.path.exists(RECORD):
        print("  no %s to check against." % RECORD)
        print("  run: python verify_corpus.py --write")
        return 1

    recorded = {}
    for line in open(RECORD, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        want, _, name = line.partition("  ")
        recorded[name.strip()] = want.strip()

    print("  corpus integrity")
    bad = 0
    for name in names:
        got = digest(os.path.join(CORPUS, name))
        want = recorded.get(name)
        if want is None:
            print("    %-14s NOT IN RECORD" % name)
            bad += 1
        elif got != want:
            print("    %-14s CHANGED" % name)
            print("      recorded %s" % want)
            print("      found    %s" % got)
            bad += 1
        else:
            print("    %-14s ok  %s" % (name, got[:16]))

    for name in sorted(set(recorded) - set(names)):
        print("    %-14s RECORDED BUT MISSING" % name)
        bad += 1

    print()
    if bad:
        print("  %d file(s) do not match the record." % bad)
        print("  Either the corpus was regenerated, or it was altered in")
        print("  transit. Re-clone and check again before doing anything else.")
        print("  Do not run the study against this corpus; the figures would")
        print("  not be comparable with the published ones.")
    else:
        print("  all %d files match the record" % len(names))

    if problems:
        print()
        print("  layout problems:")
        for p in problems:
            print("    %s" % p)

    return 1 if (bad or problems) else 0


if __name__ == "__main__":
    sys.exit(main())