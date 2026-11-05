#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import sys

CORPUS = "cases"
RECORD = "SHA256SUMS"

HEADER_SIZE = 76                                        # MS-SHLLINK 2.1
OFFSETS = {"creation_time": 28, "access_time": 36, "write_time": 44}
ICON_INDEX_OFFSET = 56


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def corpus_files():
    if not os.path.isdir(CORPUS):
        sys.exit("no %s/ directory; run from the repository root" % CORPUS)
    names = sorted(n for n in os.listdir(CORPUS) if n.endswith(".lnk"))
    if not names:
        sys.exit("no .lnk files in %s/" % CORPUS)
    return names


def check_layout():
    problems = []
    print("  header layout")
    for field, off in OFFSETS.items():
        ok = off + 8 <= HEADER_SIZE
        print("    %-14s offset %2d, bytes %2d-%2d  %s"
              % (field, off, off, off + 7, "ok" if ok else "PAST HEADER"))
        if not ok:
            problems.append("%s runs past the %d-byte header" % (field, HEADER_SIZE))
    print("    %-14s offset %2d (0x%02X), signed 32-bit"
          % ("icon_index", ICON_INDEX_OFFSET, ICON_INDEX_OFFSET))

    path = os.path.join(CORPUS, "manifest.json")
    if not os.path.exists(path):
        problems.append("no manifest.json")
        return problems

    cases = json.load(open(path, encoding="utf-8")).get("cases", {})
    print("    manifest records %d cases" % len(cases))
    for name, case in sorted(cases.items()):
        if case.get("kind") != "timestamp":
            continue
        missing = [f for f in OFFSETS if f not in case.get("expected_fields", {})]
        if missing:
            problems.append("case %s has no expectation for %s"
                            % (name, ", ".join(missing)))
    return problems


def write_record(names):
    lines = ["%s  %s\n" % (digest(os.path.join(CORPUS, n)), n) for n in names]
    with open(RECORD, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    print("  wrote %s, %d entries" % (RECORD, len(lines)))
    for line in lines:
        print("    " + line.rstrip())


def compare(names):
    recorded = {}
    for line in open(RECORD, encoding="utf-8"):
        want, _, name = line.strip().partition("  ")
        if name:
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
            print("    %-14s CHANGED\n      recorded %s\n      found    %s"
                  % (name, want, got))
            bad += 1
        else:
            print("    %-14s ok  %s" % (name, got[:16]))

    for name in sorted(set(recorded) - set(names)):
        print("    %-14s MISSING" % name)
        bad += 1
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write " + RECORD)
    args = ap.parse_args()

    names = corpus_files()
    print("corpus: %d .lnk files in %s/\n" % (len(names), CORPUS))
    problems = check_layout()
    print()

    if args.write:
        write_record(names)
        for p in problems:
            print("    %s" % p)
        return 1 if problems else 0

    if not os.path.exists(RECORD):
        sys.exit("no %s; run: python verify_corpus.py --write" % RECORD)

    bad = compare(names)
    print()
    print("  %d file(s) differ; do not run the study against this corpus" % bad
          if bad else "  all %d files match" % len(names))
    for p in problems:
        print("  %s" % p)
    return 1 if (bad or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
