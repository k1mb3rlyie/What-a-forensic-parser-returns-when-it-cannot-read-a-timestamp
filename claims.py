#!/usr/bin/env python3
"""Check the paper's claims that rest on facts outside the run records.

check_paper.py holds the paper to the records. This script holds it to
everything else it asserts: what the runs ran on, which versions are
installed, what the installed source says, how this platform's
`datetime.fromtimestamp` behaves, and, with --pypi, what PyPI publishes.

  runs       run headers: platform, zone, gap, passes, interpreter, and the
             three packages recorded as unusable
  installed  the versions in each platform's environments, and whether each
             environment's interpreter is the one the runs recorded
  source     the installed pylnk3 and LnkParse3 code the paper quotes
  platform   fromtimestamp on this interpreter, against what Section 2.2 and
             Section 5.6 say this platform does
  pypi       (--pypi) Table 7, the fork's origin, the LnkParse3 release span,
             and the reasons the three unusable packages cannot be used

Expected release dates are read from Table 7 of the paper, not repeated here,
so the paper is what gets checked. The 1601-01-01 sweep across every
LnkParse3 release executes each one and takes minutes; it stays in
`vercheck.py lnkparse3`.

Every check prints PASS, FAIL or SKIP; SKIP means the check cannot run here
(the other platform's environments, say), never that it was waved through.
The exit status is 1 if anything failed.

Usage:
    python claims.py results/*.jsonl [--pypi] [--paper paper.md]
"""

import argparse
import datetime as _dt
import glob
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile

import check_paper
import vercheck

HERE = os.path.dirname(os.path.abspath(__file__))

# What the paper says the runs ran on (Sections 4.3, 4.4).
RUNS = {
    "win-lagos": dict(platform="Windows-11-10.0.26300", python="3.13.5", offset=3600),
    "win-utc": dict(platform="Windows-11-10.0.26300", python="3.13.5", offset=0),
    "wsl-lagos": dict(platform="Linux-5.15.167", python="3.13.13", offset=3600),
    "wsl-utc": dict(platform="Linux-5.15.167", python="3.13.13", offset=0),
}
GAP_S, PASSES = 60, 2

# Table 1. pywin32 is the Shell API's binding.
VERSIONS = {"pylnk3": "0.4.3", "LnkParse3": "1.6.0",
            "liblnk-python": "20260525", "pywin32": "312"}
ENV_OF = {"pylnk3": "a1_pylnk3", "LnkParse3": "a3_lnkparse3",
          "liblnk-python": "a5_liblnk", "pywin32": "a7_shellapi"}
UNUSABLE = {"pylnk==0.2", "LnkAnalyser==0.0.1", "lnkfile==0.2.1"}

# Section 5.3: nineteen releases, 2019-04-01 to 2026-02-27.
LNKPARSE3_SPAN = (19, "2019-04-01", "2026-02-27")


class Report:
    def __init__(self):
        self.rows = []

    def add(self, status, where, msg=""):
        self.rows.append((status, where, msg))

    def check(self, where, ok, paper, data):
        self.add("PASS" if ok else "FAIL", where,
                 "" if ok else "paper %s, found %s" % (paper, data))

    def skip(self, where, why):
        self.add("SKIP", where, why)

    def print(self):
        for status, where, msg in self.rows:
            print("  %-5s  %-44s %s" % (status, where, msg))
        n = {s: sum(1 for r in self.rows if r[0] == s)
             for s in ("PASS", "FAIL", "SKIP")}
        print("\n  %d checks: %d passed, %d failed, %d skipped"
              % (len(self.rows), n["PASS"], n["FAIL"], n["SKIP"]))
        return n["FAIL"] == 0


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------

def check_runs(paths, R):
    found = {}
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        head = recs[0]
        pythons = {(r.get("result") or {}).get("python") for r in recs[1:]} - {None}
        found[head["tag"]] = (head, pythons)

    for tag, want in RUNS.items():
        if tag not in found:
            R.check("run %s present" % tag, False, "present", "missing")
            continue
        head, pythons = found[tag]
        R.check("run %s platform" % tag,
                head["platform_full"].startswith(want["platform"]),
                want["platform"], head["platform_full"])
        R.check("run %s parsers' python" % tag, pythons == {want["python"]},
                want["python"], sorted(pythons))
        R.check("run %s UTC offset" % tag,
                (head.get("tz_offset_s") or 0) == want["offset"],
                want["offset"], head.get("tz_offset_s"))
        R.check("run %s gap and passes" % tag,
                (head["gap_s"], head["passes"]) == (GAP_S, PASSES),
                (GAP_S, PASSES), (head["gap_s"], head["passes"]))
        R.check("run %s unusable packages" % tag,
                set(head.get("unusable_packages", {})) == UNUSABLE,
                sorted(UNUSABLE), sorted(head.get("unusable_packages", {})))
    for tag in sorted(set(found) - set(RUNS)):
        R.check("run %s" % tag, False, "not a run the paper reports",
                "present in the records")


# --------------------------------------------------------------------------
# installed
# --------------------------------------------------------------------------

def site_packages(tree, env):
    base = os.path.join(HERE, tree, env)
    if tree == "envs-win":
        return [os.path.join(base, "Lib", "site-packages")]
    return glob.glob(os.path.join(base, "lib", "python3*", "site-packages"))


def installed_version(tree, env, dist):
    norm = re.sub(r"[-_.]+", "_", dist).lower()
    for sp in site_packages(tree, env):
        for d in glob.glob(os.path.join(sp, "*.dist-info")):
            name, _, ver = os.path.basename(d)[:-len(".dist-info")].partition("-")
            if re.sub(r"[-_.]+", "_", name).lower() == norm:
                return ver
    return None


def venv_python_version(tree, env):
    cfg = os.path.join(HERE, tree, env, "pyvenv.cfg")
    if not os.path.exists(cfg):
        return None
    with open(cfg, encoding="utf-8") as fh:
        for line in fh:
            k, _, v = line.partition("=")
            if k.strip() in ("version", "version_info"):
                return v.strip()
    return None


def check_installed(R):
    for tree, want_py in (("envs-win", RUNS["win-lagos"]["python"]),
                          ("envs-posix", RUNS["wsl-lagos"]["python"])):
        if not os.path.isdir(os.path.join(HERE, tree)):
            R.skip(tree, "not set up on this machine")
            continue
        for dist, want in VERSIONS.items():
            if dist == "pywin32" and tree != "envs-win":
                continue
            got = installed_version(tree, ENV_OF[dist], dist)
            R.check("%s %s" % (tree, dist), got == want, want, got)
        # The runs record the interpreter they used. An environment rebuilt
        # with a different one would make the next run disagree with the paper.
        for env in sorted(set(ENV_OF.values()) | {"a8_lecmd"}):
            if env == "a7_shellapi" and tree != "envs-win":
                continue
            got = venv_python_version(tree, env)
            R.check("%s %s interpreter" % (tree, env), got == want_py,
                    want_py, got)


# --------------------------------------------------------------------------
# source
# --------------------------------------------------------------------------

def read_installed(tree, env, rel):
    for sp in site_packages(tree, env):
        p = os.path.join(sp, *rel.split("/"))
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return fh.read()
    return None


def check_source(R):
    tree = "envs-win" if sys.platform == "win32" else "envs-posix"

    src = read_installed(tree, "a1_pylnk3", "pylnk3.py")
    if src is None:
        R.skip("pylnk3 source", "pylnk3.py not installed in %s" % tree)
    else:
        lines = src.splitlines()
        body = "\n".join(lines[276:285])          # lines 277 to 285
        R.check("pylnk3.py:277 starts the function",
                lines[276].startswith("def convert_time_to_unix("),
                "def convert_time_to_unix(", lines[276][:40])
        R.check("pylnk3.py:285 returns datetime.now()",
                lines[284].strip() == "return datetime.now()",
                "return datetime.now()", lines[284].strip())
        for name, pat in vercheck.PATTERNS.items():
            R.check("pylnk3.py:277-285 %s" % name, bool(pat.search(body)),
                    "present", "absent")

    src = read_installed(tree, "a3_lnkparse3", "LnkParse3/utils.py")
    if src is None:
        R.skip("LnkParse3 source", "LnkParse3/utils.py not installed in %s" % tree)
    else:
        for label, pat in (
                ("unpacks FILETIME as signed", r'unpack\("<q",\s*binary\)'),
                ("treats zero as not recorded", r"if nanosec == 0:\s*\n(?:\s*#.*\n)*\s*return None"),
                ("aware UTC fromtimestamp", r"fromtimestamp\(timestamp,\s*tz=timezone\.utc\)"),
                ("catches OSError, returns None",
                 r"except \(OSError, OverflowError, ValueError\):[\s\S]*?warnings\.warn\(msg\)\s*\n\s*return None")):
            R.check("LnkParse3 utils.py %s" % label, bool(re.search(pat, src)),
                    "present", "absent")


# --------------------------------------------------------------------------
# platform
# --------------------------------------------------------------------------

def outcome(fn):
    try:
        fn()
        return "ok"
    except Exception as exc:
        return type(exc).__name__


def check_platform(R):
    """Section 2.2 and the T2 paragraph of Section 5.6, on this interpreter."""
    from datetime import datetime, timezone
    T2 = 0xFFFFFFFFFFFFFFFF / 10000000.0 - 11644473600   # as pylnk3 computes it
    here = "%s, CPython %s" % (sys.platform, ".".join(map(str, sys.version_info[:3])))
    if sys.platform == "win32":
        claims = [
            ("naive fromtimestamp(-1) raises OSError", lambda: datetime.fromtimestamp(-1), "OSError"),
            ("naive fromtimestamp(0) converts", lambda: datetime.fromtimestamp(0), "ok"),
            ("aware fromtimestamp(-43200) converts",
             lambda: datetime.fromtimestamp(-43200, tz=timezone.utc), "ok"),
            ("aware fromtimestamp(-43201) raises OSError",
             lambda: datetime.fromtimestamp(-43201, tz=timezone.utc), "OSError"),
            ("naive fromtimestamp(T2) raises OSError", lambda: datetime.fromtimestamp(T2), "OSError"),
        ]
    else:
        claims = [
            ("naive fromtimestamp(-1) converts", lambda: datetime.fromtimestamp(-1), "ok"),
            ("aware fromtimestamp(-618062400) converts",
             lambda: datetime.fromtimestamp(-618062400, tz=timezone.utc), "ok"),
            ("naive fromtimestamp(T2) raises ValueError", lambda: datetime.fromtimestamp(T2), "ValueError"),
        ]
    for label, fn, want in claims:
        got = outcome(fn)
        R.check("%s (%s)" % (label, here), got == want, want, got)
    other = "Linux" if sys.platform == "win32" else "Windows"
    R.skip("fromtimestamp on %s" % other, "run claims.py there too")


# --------------------------------------------------------------------------
# pypi
# --------------------------------------------------------------------------

def pypi_meta(package):
    return json.load(io.BytesIO(vercheck.fetch("https://pypi.org/pypi/%s/json" % package)))


def sdist_members(files):
    """{name: text} of every file in a release's source distribution."""
    for rec in files:
        if rec.get("packagetype") == "sdist":
            blob = vercheck.fetch(rec["url"])
            out = {}
            if rec["filename"].endswith((".tar.gz", ".tgz")):
                with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
                    for m in tar.getmembers():
                        if m.isfile():
                            out[m.name] = tar.extractfile(m).read().decode("utf8", "replace")
            elif rec["filename"].endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                    for n in zf.namelist():
                        out[n] = zf.read(n).decode("utf8", "replace")
            return out
    return None


def normalise(src):
    """Drop line endings and the signature's annotation, as vercheck does."""
    lines = [ln.rstrip() for ln in src.strip().replace("\r\n", "\n").splitlines()]
    head = re.sub(r"def (\w+)\([^)]*\)[^:]*:", r"def \1():", lines[0])
    return "\n".join([head] + lines[1:])


def check_pypi(paper, R):
    # Table 7, read from the paper so the paper is what is checked.
    with open(paper, encoding="utf-8") as fh:
        t = check_paper.table(fh.read().splitlines(), "**Table 7.**")
    if not t:
        R.check("Table 7", False, "present in %s" % paper, "not found")
        return
    stated = [(r[0], r[1]) for r in t[1]]

    rels = vercheck.releases("pylnk3")
    published = [(v, when) for v, when, _ in rels]
    R.check("Table 7 pylnk3 releases and dates", published == stated,
            stated, published)
    meta = pypi_meta("pylnk3")
    R.check("pylnk3 0.4.3 is the current release",
            meta["info"]["version"] == "0.4.3" and published[-1][0] == "0.4.3",
            "0.4.3", meta["info"]["version"])

    bodies = {}
    for ver, when, files in rels:
        src, where = vercheck.find_function(files)
        if src is None:
            R.check("pylnk3 %s function" % ver, False, "found", "not found")
            continue
        bodies[ver] = src
        hits = [n for n, p in vercheck.PATTERNS.items() if p.search(src)]
        R.check("pylnk3 %s has all three defects" % ver,
                len(hits) == len(vercheck.PATTERNS), list(vercheck.PATTERNS), hits)
        if ver == "1.0.0a1":
            R.check("pylnk3 1.0.0a1 moved it to utils/data.py",
                    where.replace("\\", "/").endswith("pylnk3/utils/data.py"),
                    "pylnk3/utils/data.py", where)
    R.check("pylnk3 function behaviour identical in every release",
            len({normalise(s) for s in bodies.values()}) == 1,
            "one text once normalised",
            "%d texts" % len({normalise(s) for s in bodies.values()}))

    files_1 = dict((v, f) for v, _, f in rels).get("1.0.0a1")
    members = sdist_members(files_1) if files_1 else None
    if members is None:
        R.skip("pylnk3 1.0.0a1 file count", "no source distribution")
    else:
        pkg = [n for n in members if re.search(r"/pylnk3/.*\.py$", n)]
        R.check("pylnk3 1.0.0a1 is twenty-one files", len(pkg) == 21, 21, len(pkg))

    # The fork's origin: pylnk 0.2 has no handler, pylnk3 0.2.1 added one.
    old = dict((v, f) for v, _, f in vercheck.releases("pylnk")).get("0.2")
    a = vercheck.find_function(old)[0] if old else None
    b = bodies.get("0.2.1")
    R.check("pylnk 0.2 has no handler, ends at fromtimestamp",
            bool(a) and "datetime.now()" not in a
            and a.rstrip().endswith("return datetime.fromtimestamp(unix_time)"),
            "no handler", "handler present" if a else "function not found")
    R.check("pylnk3 0.2.1 added the datetime.now() handler",
            bool(b) and "datetime.now()" in b, "added", "absent")

    # pylnk 0.2 cannot be imported: a Python 2 print statement at line 562.
    members = sdist_members(old) if old else None
    src = next((t for n, t in (members or {}).items() if n.endswith("/pylnk.py")), None)
    line = src.splitlines()[561] if src and len(src.splitlines()) > 561 else ""
    R.check("pylnk 0.2 pylnk.py:562 is a Python 2 print",
            bool(re.match(r"\s*print\s+[^(\s]", line)), "print statement", line.strip()[:40])

    # LnkParse3's span, Section 5.3, and its current release, Table 1.
    lp = vercheck.releases("LnkParse3")
    got = (len(lp), lp[0][1], lp[-1][1]) if lp else (0, None, None)
    R.check("LnkParse3 release count and span", got == LNKPARSE3_SPAN,
            LNKPARSE3_SPAN, got)
    R.check("LnkParse3 1.6.0 is the current release",
            pypi_meta("LnkParse3")["info"]["version"] == "1.6.0",
            "1.6.0", pypi_meta("LnkParse3")["info"]["version"])

    lib = pypi_meta("liblnk-python")
    R.check("liblnk-python 20260525 is published",
            bool(lib["releases"].get("20260525")), "published", "absent")

    # The three unusable packages, Table 1.
    la = pypi_meta("LnkAnalyser")["releases"]
    R.check("LnkAnalyser: one release, 0.0.1, with no files",
            list(la) == ["0.0.1"] and not la["0.0.1"],
            "0.0.1, no files", {v: len(f) for v, f in la.items()})

    lf = pypi_meta("lnkfile")["releases"].get("0.2.1")
    members = sdist_members(lf) if lf else None
    if members is None:
        R.check("lnkfile 0.2.1 source distribution", False, "present", "absent")
    else:
        setup = next((t for n, t in members.items() if n.endswith("/setup.py")), "")
        readme = [n for n in members if os.path.basename(n).lower().startswith("readme")]
        R.check("lnkfile 0.2.1 setup.py reads a README it does not ship",
                "README" in setup and not readme,
                "reads README, none shipped",
                "reads README: %s, shipped: %s" % ("README" in setup, readme))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--pypi", action="store_true",
                    help="also check what PyPI publishes (needs network)")
    ap.add_argument("--paper", default=os.path.join(HERE, "paper.md"))
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")

    runs = args.runs or sorted(glob.glob(os.path.join(HERE, "results", "*.jsonl")))
    R = Report()
    check_runs(runs, R)
    check_installed(R)
    check_source(R)
    check_platform(R)
    if args.pypi:
        try:
            check_pypi(args.paper, R)
        except OSError as exc:
            R.check("PyPI reachable", False, "reachable", exc)
    else:
        R.skip("PyPI claims", "pass --pypi to check them")
    sys.exit(0 if R.print() else 1)


if __name__ == "__main__":
    main()
