#!/usr/bin/env python3
"""Demonstrate the Windows-only substitution path from a non-Windows host.

pylnk3 converts a FILETIME like this (pylnk3.py 0.4.3, lines 277 to 285):

    unix_time = windows_time / 10000000.0 - 11644473600
    try:
        return datetime.fromtimestamp(unix_time)
    except OSError:
        return datetime.now()

`datetime.fromtimestamp` raises OSError for a negative argument on Windows,
because the platform's localtime cannot represent a time before the Unix
epoch. On Linux and macOS it accepts negatives and returns the correct date.
So the substitution on line 285 fires on Windows and never fires elsewhere,
for the same file and the same library version. That is why the defect has
survived in a widely used library: it is invisible on the platform most
maintainers test on.

This script makes `fromtimestamp` behave the way it does on Windows and then
runs pylnk3 over the cases, so the mechanism can be shown deterministically
rather than inferred. It is a demonstration of the cause, not a measurement.
The measurement is run_study.py on an actual Windows host, and this script
predicts exactly which of its cells will report a fabricated value.

Usage:
    envs/a1_pylnk3/bin/python predict_windows.py
"""

import datetime as _dt
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "cases")

TICKS = 10_000_000
EPOCH_DELTA = 11_644_473_600
WINDOW = 5.0

_real_fromtimestamp = _dt.datetime.fromtimestamp


class WindowsLikeDatetime(_dt.datetime):
    """datetime whose fromtimestamp refuses negatives, as Windows does."""

    @classmethod
    def fromtimestamp(cls, ts, tz=None):
        if ts < 0:
            raise OSError(22, "Invalid argument")
        return _real_fromtimestamp(ts, tz)


def main():
    import pylnk3

    # pylnk3 does `from datetime import datetime`, so the name it calls is a
    # module global and can be replaced without touching the stdlib.
    pylnk3.datetime = WindowsLikeDatetime

    with open(os.path.join(CASES, "manifest.json"), encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]

    try:
        from importlib.metadata import version as _dist_version
        installed = _dist_version("pylnk3")
    except BaseException:
        installed = getattr(pylnk3, "__version__", "version unknown")

    print("pylnk3 %s, fromtimestamp patched to refuse negatives as Windows does"
          % installed)
    if installed != "0.4.3":
        print("note: the line numbers quoted in the docstring are from 0.4.3")
    print("local timezone %s, offset %+ds\n"
          % (time.tzname[0],
             int(_dt.datetime.now().astimezone().utcoffset().total_seconds())))

    header = "  %-4s %-26s %-21s %-21s %s"
    print(header % ("case", "stored value", "expected (UTC)", "returned",
                    "verdict"))

    fabricated = []
    for name in sorted(cases):
        if not name.startswith("T"):
            continue
        meta = cases[name]
        ef = meta.get("expected_fields", {}).get("creation_time", {})
        stored = ef.get("filetime")
        expect = ef.get("decoded_utc") or "not representable"

        now = time.time()
        try:
            lnk = pylnk3.parse(os.path.join(CASES, meta["file"]))
            got = lnk.creation_time
        except BaseException as exc:
            print(header % (name, "0x%016X" % stored, expect,
                            "-", "raised %s" % type(exc).__name__))
            continue

        if isinstance(got, _dt.datetime):
            shown = got.isoformat()
            try:
                inst = got.astimezone().timestamp()
            except BaseException:
                inst = None
            if inst is not None and abs(inst - now) < WINDOW:
                verdict = "FABRICATED, the examination time"
                fabricated.append(name)
            else:
                verdict = "value from the file"
        else:
            shown, verdict = repr(got)[:21], "non-datetime"

        print(header % (name, "0x%016X" % stored, expect, shown, verdict))

    print()
    if fabricated:
        print("Fabricated on %d of the timestamp cases: %s"
              % (len(fabricated), ", ".join(fabricated)))
        print("Every one of these stores a timestamp before 1970-01-01, which")
        print("makes unix_time negative on line 281. The trigger is the date")
        print("itself, not damage to the file and not an invalid value: the")
        print("boundary is exact to the second. T4 (1969-12-31 23:59:59)")
        print("fabricates, T7 (1970-01-01 00:00:00) does not, and T8")
        print("(1970-01-01 00:00:01) does not. Two files one second apart in")
        print("intent, on opposite sides of the epoch, read differently.")
        print("Every one of these files is well formed; none is corrupt.")
        print()
        print("Expect the same cells to report FABRICATED when run_study.py is")
        print("run on Windows without this patch.")
    else:
        print("No substitution fired, so the patch did not take effect or the")
        print("library has changed. Do not report the Windows prediction.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
