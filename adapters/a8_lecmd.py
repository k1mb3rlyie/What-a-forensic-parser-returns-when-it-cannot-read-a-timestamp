import csv
import glob
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Raised, run  # noqa: E402

ADAPTER = "a8_lecmd"

CANDIDATES = {
    "creation_time": ("targetcreated", "targetcreationtime", "createdon"),
    "access_time": ("targetaccessed", "targetlastaccessed", "accessedon"),
    "write_time": ("targetmodified", "targetlastmodified", "modifiedon"),
    "icon_index": ("iconindex", "icon_index"),
}


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

    out = {"_csv_header": ",".join(sorted(lowered))}
    for field, names in CANDIDATES.items():
        value = None
        for n in names:
            if n in lowered:
                value = lowered[n]
                break
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
            out[field] = value if str(value).strip() else None
    return out


if __name__ == "__main__":
    run(ADAPTER, parse)
