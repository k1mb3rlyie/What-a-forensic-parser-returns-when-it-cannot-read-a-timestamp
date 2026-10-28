#!/usr/bin/env python3
"""Reproduce the release-history findings from PyPI.

Three questions, all answered from published artefacts rather than from a
repository, so the answers do not depend on a git history that could be
rewritten:

  history    Is the pylnk3 conversion defect present in every release?
  origin     Was the substitution inherited from pylnk, or added by the fork?
  lnkparse3  How far back does the 1601-01-01 reading of 0xFFFFFFFFFFFFFFFF go?

`history` and `origin` read source out of the published distributions and need
no virtual environments. `lnkparse3` has to execute each release, so it builds
a throwaway environment and installs each version into it in turn, which takes
a few minutes and needs the test corpus to exist.

Usage:
    python vercheck.py history
    python vercheck.py origin
    python vercheck.py lnkparse3
    python vercheck.py all
"""

import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
T2 = os.path.join(HERE, "cases", "T2.lnk")

PATTERNS = {
    "float division": re.compile(r"/\s*10000000\.0"),
    "naive fromtimestamp": re.compile(r"datetime\.fromtimestamp\(\s*unix_time\s*\)"),
    "substitutes clock": re.compile(
        r"except\s+OSError\s*:\s*(?:#[^\n]*)?\s*\n\s*return\s+datetime\.now\(\)"),
}

FUNC = "convert_time_to_unix"


def fetch(url):
    return urllib.request.urlopen(url, timeout=60).read()


def releases(package):
    """[(version, upload_date, [file records])] oldest first."""
    meta = json.load(io.BytesIO(fetch(
        "https://pypi.org/pypi/%s/json" % package)))
    out = [(v, fs[0]["upload_time"][:10], fs)
           for v, fs in meta["releases"].items() if fs]
    out.sort(key=lambda row: row[2][0]["upload_time"])
    return out


def members(filename, blob):
    """Yield (name, text) for every .py file in a distribution."""
    try:
        if filename.endswith((".tar.gz", ".tgz")):
            with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
                for m in tar.getmembers():
                    if m.name.endswith(".py") and m.isfile():
                        yield m.name, tar.extractfile(m).read().decode(
                            "utf8", "replace")
        elif filename.endswith((".whl", ".zip")):
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                for n in zf.namelist():
                    if n.endswith(".py"):
                        yield n, zf.read(n).decode("utf8", "replace")
    except BaseException:
        return


def find_function(files, func=FUNC):
    """(source of the function, containing file) from a release's files.

    Source distributions are preferred over wheels so that the text matches
    what a reader would find in the repository at that tag.
    """
    for prefer in ("sdist", "bdist_wheel"):
        for rec in files:
            if rec.get("packagetype") != prefer:
                continue
            try:
                blob = fetch(rec["url"])
            except BaseException:
                continue
            for name, text in members(rec["filename"], blob):
                found = re.search(r"def %s.*?(?=\ndef |\Z)" % func, text, re.S)
                if found:
                    return found.group(0).rstrip(), name
    return None, None


def cmd_history():
    print("pylnk3: is the defect present in every release?\n")
    names = list(PATTERNS)
    print("  %-9s %-11s %s" % ("version", "released",
                               "  ".join("%-19s" % n for n in names)))
    first, bodies = {}, {}
    for ver, when, files in releases("pylnk3"):
        src, where = find_function(files)
        if src is None:
            print("  %-9s %-11s  could not locate %s" % (ver, when, FUNC))
            continue
        bodies[ver] = src
        marks = []
        for n in names:
            hit = bool(PATTERNS[n].search(src))
            marks.append("%-19s" % ("yes" if hit else "no"))
            if hit and n not in first:
                first[n] = (ver, when)
        print("  %-9s %-11s %s   (%s)" % (ver, when, "  ".join(marks), where))

    print()
    for n, (ver, when) in first.items():
        print("  %-21s first published in %s on %s" % (n, ver, when))

    # Separate a change in behaviour from a change in formatting. Line endings
    # and a type annotation do not alter what the code does, so counting them
    # overstates the history in one direction, while calling the function
    # "byte-identical" overstates it in the other. Report both.
    def normalise(src):
        lines = [ln.rstrip() for ln
                 in src.strip().replace("\r\n", "\n").splitlines()]
        if not lines:
            return ""
        head = re.sub(r"def (\w+)\([^)]*\)[^:]*:", r"def \1():", lines[0])
        return "\n".join([head] + lines[1:])

    raw = {s.strip() for s in bodies.values()}
    norm = {normalise(s) for s in bodies.values()}
    print()
    print("  %d distinct texts across %d readable releases; %d once line "
          "endings and" % (len(raw), len(bodies), len(norm)))
    print("  type annotations are normalised away")
    if len(norm) == 1:
        print("  so the function's behaviour is unchanged in every release")


def cmd_origin():
    print("Was the substitution inherited from pylnk, or added by the fork?\n")
    import difflib

    pairs = [("pylnk", "0.2"), ("pylnk3", "0.2.1")]
    got = {}
    for pkg, ver in pairs:
        for v, when, files in releases(pkg):
            if v != ver:
                continue
            src, where = find_function(files)
            got[(pkg, ver)] = (src, where, when)
            print("=== %s %s, released %s (%s) ===" % (pkg, ver, when, where))
            print(src or "  function not found")
            print()

    a = got.get(("pylnk", "0.2"), (None,))[0]
    b = got.get(("pylnk3", "0.2.1"), (None,))[0]
    if not (a and b):
        print("  could not compare: one side is missing")
        return
    if a.strip() == b.strip():
        print("  identical: the behaviour was inherited, not introduced")
        return
    print("  not identical. The fork changed it:")
    for line in difflib.unified_diff(a.splitlines(), b.splitlines(),
                                     "pylnk 0.2", "pylnk3 0.2.1", lineterm=""):
        print("   " + line)
    added = "datetime.now()" in b and "datetime.now()" not in a
    print()
    print("  substitution added by the fork: %s" % ("yes" if added else "no"))


def cmd_lnkparse3():
    if not os.path.exists(T2):
        sys.exit("need %s; run make_cases.py first" % T2)

    probe = (
        "import LnkParse3\n"
        "with open(%r,'rb') as f:\n"
        "    j = LnkParse3.lnk_file(f).get_json()\n"
        "print(repr(j.get('header',{}).get('creation_time'))[:60])\n"
        % T2)

    print("LnkParse3: what does each release return for T2 "
          "(0xFFFFFFFFFFFFFFFF)?\n")
    rels = releases("LnkParse3")
    with tempfile.TemporaryDirectory() as tmp:
        env = os.path.join(tmp, "v")
        subprocess.run([sys.executable, "-m", "venv", env],
                       capture_output=True)
        py = os.path.join(env, "bin", "python")
        if not os.path.exists(py):
            py = os.path.join(env, "Scripts", "python.exe")

        print("  %-9s %-11s %s" % ("version", "released", "creation_time"))
        epoch = 0
        for ver, when, _ in rels:
            inst = subprocess.run(
                [py, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                 "LnkParse3==%s" % ver], capture_output=True, text=True)
            if inst.returncode != 0:
                print("  %-9s %-11s install failed" % (ver, when))
                continue
            got = subprocess.run([py, "-c", probe],
                                 capture_output=True, text=True, timeout=90)
            line = (got.stdout or got.stderr or "").strip().splitlines()
            out = line[-1] if line else "no output"
            if "1601" in out:
                epoch += 1
            print("  %-9s %-11s %s" % (ver, when, out))

        print()
        print("  %d of %d releases report T2 as 1601-01-01" % (epoch, len(rels)))
        if rels:
            print("  spanning %s to %s" % (rels[0][1], rels[-1][1]))


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    jobs = {"history": cmd_history, "origin": cmd_origin,
            "lnkparse3": cmd_lnkparse3}
    if which == "all":
        for i, (name, fn) in enumerate(jobs.items()):
            if i:
                print("\n" + "=" * 72 + "\n")
            fn()
    elif which in jobs:
        jobs[which]()
    else:
        sys.exit("usage: vercheck.py [history|origin|lnkparse3|all]")


if __name__ == "__main__":
    main()
