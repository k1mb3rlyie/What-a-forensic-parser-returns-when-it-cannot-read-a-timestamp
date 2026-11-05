#!/usr/bin/env python3
"""Show the Windows conversion path from a Linux host."""

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
                fabricated.append((name, ef.get("unix")))
            else:
                verdict = "value from the file"
        else:
            shown, verdict = repr(got)[:21], "non-datetime"

        print(header % (name, "0x%016X" % stored, expect, shown, verdict))

    print()
    if fabricated:
        names = [n for n, _ in fabricated]
        below = [n for n, u in fabricated if u is not None and u < 0]
        above = [n for n, u in fabricated if u is not None and u >= 0]

        print("Fabricated on %d of the timestamp cases: %s"
              % (len(names), ", ".join(names)))
        print()
        if below:
            print("Below the epoch: %s. These make unix_time negative on line"
                  % ", ".join(below))
            print("281, and the handler on line 285 catches what the platform")
            print("raises for a negative argument. The trigger is the date")
            print("itself, not damage and not an invalid value: the boundary is")
            print("exact to the second. T4 (1969-12-31 23:59:59) fabricates,")
            print("T7 (1970-01-01 00:00:00) does not, and T8 (one second later)")
            print("does not. Two well-formed files one second apart in intent,")
            print("on opposite sides of the epoch, read differently.")
        if above:
            print()
            print("Above the representable range: %s. unix_time here is"
                  % ", ".join(above))
            print("positive, so this is the other end of the domain. Whether it")
            print("fabricates depends on which exception the platform raises.")
            print("Linux raises ValueError, which line 284 does not catch, so")
            print("the file fails loudly. Windows raises OSError, which it does")
            print("catch, so the value is substituted. The library's failure is")
            print("therefore loud or silent at this end according to the host,")
            print("and only the host decides.")
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
