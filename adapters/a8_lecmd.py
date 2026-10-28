"""Adapter: LECmd (Eric Zimmerman), the tool most examiners actually run.

LECmd is a .NET command-line tool, so it is driven as a subprocess and read
back from the CSV it writes. Its presence matters to the study out of
proportion to its share of the table: a defect in a library affects whoever
imported it, while a defect here affects reports that go to court.

The column mapping was verified against LECmd 2026.10.2 on 24 October 2026:
the header times are TargetCreated, TargetAccessed and TargetModified, written
as naive UTC to the second. Column names are still matched case-insensitively
against a list of candidates, and if nothing matches the CSV header actually
found is recorded instead of a guess, so a later release that renames a column
fails visibly.

IconIndex is in neither the CSV nor the JSON output. LECmd prints it only in
its console report ("Icon index: -1"), which the same invocation captures, so
that is where it is read from. The CSV's Anomalies column is recorded too,
because it is where LECmd reports a timestamp it refused to convert.

Set LECMD to the full path of LECmd.exe, or place it beside this file.
Windows, or any host with the .NET runtime.
"""

import csv
import glob
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Raised, run  # noqa: E402

ADAPTER = "a8_lecmd"

# The embedded header timestamps, which are what this study measures, are the
# "target" columns. The "source" columns are the .lnk file's own filesystem
# times and must not be read as the stored values.
CANDIDATES = {
    "creation_time": ("targetcreated", "targetcreationtime", "createdon"),
    "access_time": ("targetaccessed", "targetlastaccessed", "accessedon"),
    "write_time": ("targetmodified", "targetlastmodified", "modifiedon"),
    "icon_index": ("iconindex", "icon_index"),
}

ICON_LINE = re.compile(r"^\s*Icon index:\s*(-?\d+)\s*$", re.MULTILINE)
VERSION_LINE = re.compile(r"^LECmd version (\S+)", re.MULTILINE)


def _executable():
    env = os.environ.get("LECMD")
    if env and os.path.exists(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("LECmd.exe", "LECmd"):
        for base in (here, os.path.dirname(here)):
            cand = os.path.join(base, name)
            if os.path.exists(cand):
                return cand
    raise RuntimeError(
        "LECmd not found; set the LECMD environment variable to its full path")


def parse(path):
    exe = _executable()
    with tempfile.TemporaryDirectory() as out_dir:
        proc = subprocess.run(
            [exe, "-f", os.path.abspath(path), "--csv", out_dir],
            capture_output=True, text=True, timeout=90)
        found = glob.glob(os.path.join(out_dir, "*.csv"))
        if not found:
            raise RuntimeError(
                "LECmd wrote no CSV (exit %s): %s"
                % (proc.returncode, (proc.stderr or proc.stdout or "")[:300]))
        with open(found[0], newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))

    if not rows:
        raise RuntimeError("LECmd CSV had a header but no rows")
    row = rows[0]
    lowered = {(k or "").strip().lower(): v for k, v in row.items()}

    out = {"_csv_header": ",".join(sorted(lowered)),
           "_anomalies": lowered.get("anomalies"),
           "_version": (VERSION_LINE.search(proc.stdout or "") or [None, None])[1]}
    for field, names in CANDIDATES.items():
        value = None
        for n in names:
            if n in lowered:
                value = lowered[n]
                break
        if value is None and field == "icon_index":
            m = ICON_LINE.search(proc.stdout or "")
            value = m.group(1) if m else None
        if value is None:
            out[field] = Raised(KeyError(
                "no column matched %s; header was %s"
                % (list(names), ",".join(sorted(lowered))[:200])))
        elif field == "icon_index":
            try:
                out[field] = int(str(value).strip())
            except BaseException as exc:
                out[field] = Raised(exc)
        else:
            # Left as the literal string. _common parses a timestamp spelling
            # and records both readings of it; a non-timestamp string is kept
            # verbatim rather than coerced.
            out[field] = value if str(value).strip() else None
    return out


if __name__ == "__main__":
    run(ADAPTER, parse)
