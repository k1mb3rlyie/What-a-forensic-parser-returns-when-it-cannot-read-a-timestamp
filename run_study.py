#!/usr/bin/env python3
"""Run every parser over every case, twice, with a gap between the passes.

The second pass is the control, and it is the whole point of the design.
A value that was read out of the file is byte-identical in both passes. A
value that was taken from the system clock moves by the length of the gap.
Nothing else distinguishes those two outcomes, so the gap has to be long
enough to exceed any plausible rounding or caching: sixty seconds by default.

Each parser runs in its own interpreter, in its own virtual environment, as
a separate process. That is not tidiness. The Python binding to liblnk
installs a module called `pylnk`, and so does the unrelated PyPI package of
the same name, so in a shared environment the two shadow each other and a
result cannot be attributed to a library.

Usage:
    python run_study.py --tag linux-lagos
    python run_study.py --tag win-utc --gap 60
"""

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_DIR = os.path.join(HERE, "cases")
# One environment tree per platform. A venv's pyvenv.cfg names the interpreter
# that made it, so WSL2 and Windows sharing one tree on the same disk each
# overwrite the other's, and the next run on the other platform silently
# loses its parsers.
ENVS_DIR = os.path.join(HERE, "envs-win" if sys.platform == "win32"
                        else "envs-posix")
ADAPTERS_DIR = os.path.join(HERE, "adapters")
RESULTS_DIR = os.path.join(HERE, "results")

EPOCH_DELTA = 11_644_473_600
TICKS = 10_000_000

ADAPTERS = {
    "a1_pylnk3": {"env": "a1_pylnk3", "script": "a1_pylnk3.py"},
    "a3_lnkparse3": {"env": "a3_lnkparse3", "script": "a3_lnkparse3.py"},
    "a5_liblnk": {"env": "a5_liblnk", "script": "a5_liblnk.py"},
    "a7_shellapi": {"env": "a7_shellapi", "script": "a7_shellapi.py",
                    "platforms": ("win32",)},
    "a8_lecmd": {"env": "a8_lecmd", "script": "a8_lecmd.py",
                 "needs_lecmd": True},
}

# Packages that advertise .lnk parsing and could not be used, with the reason.
# Recorded in the run so the roster is self-documenting rather than a claim
# made only in the paper.
UNUSABLE = {
    "pylnk==0.2": "SyntaxError on import: Python 2 print statement at pylnk.py:562",
    "LnkAnalyser==0.0.1": "no distribution files published for the only release",
    "lnkfile==0.2.1": "setup.py reads README.md, which the sdist does not ship",
}


def venv_python(name):
    base = os.path.join(ENVS_DIR, name)
    rels = (("Scripts/python.exe",) if sys.platform == "win32"
            else ("bin/python", "bin/python3"))
    for rel in rels:
        cand = os.path.join(base, *rel.split("/"))
        if os.path.exists(cand):
            return cand
    return None


def discover_cases():
    if not os.path.isdir(CASES_DIR):
        sys.exit("no cases directory at %s; run make_cases.py first" % CASES_DIR)
    names = sorted(f for f in os.listdir(CASES_DIR) if f.endswith(".lnk"))
    if not names:
        sys.exit("no .lnk cases in %s; run make_cases.py first" % CASES_DIR)
    return names


def find_lecmd():
    env = os.environ.get("LECMD")
    if env and os.path.exists(env):
        return env
    for base in (HERE, ADAPTERS_DIR):
        for name in ("LECmd.exe", "LECmd"):
            cand = os.path.join(base, name)
            if os.path.exists(cand):
                return cand
    return None


def active_adapters(only=None):
    """Decide which adapters can run here, and why the others cannot.

    A skipped adapter is recorded with its reason and that reason is written
    into the run header, so a missing row in the results is always explained
    by the results themselves rather than by recollection.
    """
    out, skipped = [], []
    for name, spec in sorted(ADAPTERS.items()):
        if only and name not in only:
            continue
        plats = spec.get("platforms")
        if plats and sys.platform not in plats:
            skipped.append((name, "not applicable on %s" % sys.platform))
            continue
        if spec.get("needs_lecmd") and find_lecmd() is None:
            skipped.append((name, "LECmd.exe not found; set LECMD to its path"))
            continue
        py = venv_python(spec["env"])
        path = os.path.join(ADAPTERS_DIR, spec["script"])
        if py is None:
            skipped.append((name, "no interpreter in %s/%s; run the setup "
                                  "script" % (os.path.basename(ENVS_DIR), spec["env"])))
        elif not os.path.exists(path):
            skipped.append((name, "adapter script missing: %s" % spec["script"]))
        else:
            out.append((name, py, path))
    return out, skipped


def invoke(name, py, script, case_path, pass_idx, timeout):
    started = time.time()
    rec = {
        "adapter": name,
        "case": os.path.splitext(os.path.basename(case_path))[0],
        "pass": pass_idx,
        "runner_started_unix": started,
        "runner_started_ft": int(round((started + EPOCH_DELTA) * TICKS)),
    }
    try:
        proc = subprocess.run(
            [py, script, case_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=HERE,
        )
        rec["returncode"] = proc.returncode
        rec["stderr"] = proc.stderr[-1500:] if proc.stderr else ""
        line = (proc.stdout or "").strip().splitlines()
        if line:
            try:
                rec["result"] = json.loads(line[-1])
            except ValueError:
                rec["result"] = None
                rec["harness_error"] = "adapter stdout was not JSON"
                rec["raw_stdout"] = proc.stdout[-1500:]
        else:
            rec["result"] = None
            rec["harness_error"] = "adapter produced no output"
    except subprocess.TimeoutExpired:
        rec["returncode"] = None
        rec["result"] = None
        rec["harness_error"] = "timed out after %ss" % timeout
    rec["runner_elapsed_s"] = round(time.time() - started, 6)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True,
                    help="label for this run, e.g. win-utc or wsl-lagos")
    ap.add_argument("--gap", type=int, default=60,
                    help="seconds between passes (default 60)")
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to these adapter names")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.passes >= 2 and args.gap < 5:
        sys.exit("a gap under 5s cannot separate a clock read from a file "
                 "read; use --gap 60")

    cases = discover_cases()
    adapters, skipped = active_adapters(args.only)
    if not adapters:
        sys.exit("no runnable adapters; check %s/ and adapters/"
                 % os.path.basename(ENVS_DIR))

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = args.out or os.path.join(RESULTS_DIR, "run_%s.jsonl" % args.tag)

    offset = dt.datetime.now().astimezone().utcoffset()
    header = {
        "record": "run_header",
        "tag": args.tag,
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "gap_s": args.gap,
        "passes": args.passes,
        "cases": cases,
        "adapters": [a[0] for a in adapters],
        "skipped": skipped,
        "unusable_packages": UNUSABLE,
        "tz_env": os.environ.get("TZ"),
        "tz_name": list(time.tzname),
        "tz_offset_s": int(offset.total_seconds()) if offset else None,
        "platform": sys.platform,
        "platform_full": platform.platform(),
        "python_runner": sys.version.split()[0],
    }

    print("tag %s   %d adapters x %d cases x %d passes   gap %ds"
          % (args.tag, len(adapters), len(cases), args.passes, args.gap))
    for name, reason in skipped:
        print("  skipped %-14s %s" % (name, reason))
    print("  timezone %s offset %+ds" % (time.tzname[0], header["tz_offset_s"] or 0))

    records = [header]
    for p in range(args.passes):
        if p:
            print("  waiting %ds before pass %d" % (args.gap, p + 1))
            time.sleep(args.gap)
        print("  pass %d" % (p + 1))
        for name, py, script in adapters:
            marks = []
            for case in cases:
                rec = invoke(name, py, script,
                             os.path.join(CASES_DIR, case), p, args.timeout)
                records.append(rec)
                res = rec.get("result")
                if rec.get("harness_error"):
                    marks.append("!")
                elif res and res.get("ok"):
                    marks.append(".")
                else:
                    marks.append("x")
            print("    %-14s %s" % (name, "".join(marks)))

    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=str) + "\n")

    print("\n%d records -> %s" % (len(records) - 1, out_path))
    print("legend: . parsed   x parser reported failure   ! harness problem")


if __name__ == "__main__":
    main()
