#!/usr/bin/env python3
"""Grade the raw records and print the tables."""

import argparse
import datetime as _dt
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "cases", "manifest.json")

TICKS = 10_000_000
EPOCH_DELTA = 11_644_473_600     # seconds from 1601-01-01 to 1970-01-01
TOLERANCE = 1 * TICKS            # implementations may truncate sub-second
FABRICATION_WINDOW = 5 * TICKS   # |returned - examined| < 5s
DRIFT_FLOOR = 1 * TICKS
EPOCH_1601_TICKS = 0

TIME_FIELDS = ("creation_time", "access_time", "write_time")
RAW_FIELDS = tuple(f + "_raw" for f in TIME_FIELDS)
ALL_FIELDS = TIME_FIELDS + ("icon_index",)

CORRECT = ("AWARE_OK", "NAIVE_UTC_OK", "NAIVE_LOCAL_OK", "RAW_OK")
LOUD = ("ABSENT", "FIELD_ERROR", "FILE_ERROR")
SILENT_WRONG = ("WRONG", "GARBAGE_AS_EPOCH", "UNSIGNED_MISREAD", "FABRICATED")
EXCLUDED = ("NOT_TESTED", "NO_RESULT")

ORDER = CORRECT + LOUD + SILENT_WRONG + EXCLUDED

MARK = {"AWARE_OK": "A", "NAIVE_UTC_OK": "U", "NAIVE_LOCAL_OK": "L",
        "RAW_OK": "R", "ABSENT": "-", "FIELD_ERROR": "E", "FILE_ERROR": "F",
        "WRONG": "W", "GARBAGE_AS_EPOCH": "Z", "UNSIGNED_MISREAD": "M",
        "FABRICATED": "!", "NOT_TESTED": ".", "NO_RESULT": "?"}


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


def truth_for(meta, field):
    base = field[:-4] if field.endswith("_raw") else field

    if base == "icon_index":
        v = meta.get("icon_index")
        if v is None:
            v = meta.get("expected_icon_index")
        return ("not_tested", None) if v is None else ("icon", v)

    ef = meta.get("expected_fields", {}).get(base)
    if not ef:
        return ("not_tested", None)
    if ef.get("decoded_utc") is None:
        return ("unrepresentable", ef.get("filetime"))
    return ("ticks", ef.get("filetime"))


def _ticks_from_iso(iso, offset_s):
    try:
        d = _dt.datetime.fromisoformat(iso)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone(_dt.timedelta(seconds=offset_s)))
        secs = (d.astimezone(_dt.timezone.utc)
                - _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
                ).total_seconds()
        return int(round((secs + EPOCH_DELTA) * TICKS))
    except BaseException:
        return None


def candidates(desc, tz_offset_s=None):
    out = []
    if desc.get("kind") == "int":
        out.append(("raw", desc["int"]))
    for reading in ("ft_if_utc", "ft_if_local"):
        v = desc.get(reading)
        if isinstance(v, int):
            out.append((reading, v))

    if not any(r == "ft_if_local" for r, _ in out) \
            and desc.get("naive") and desc.get("iso") \
            and tz_offset_s is not None:
        derived = _ticks_from_iso(desc["iso"], tz_offset_s)
        if derived is not None:
            out.append(("ft_if_local_derived", derived))
    return out


def grade(desc, meta, field, examined_ft, tz_offset_s=None):
    kind, truth = truth_for(meta, field)
    if kind == "not_tested":
        return "NOT_TESTED", ""

    if desc is None:
        return "NO_RESULT", "field not returned by the adapter"
    dkind = desc.get("kind")
    if dkind == "raised":
        return "FIELD_ERROR", "%s: %s" % (desc.get("exc"),
                                          desc.get("message", "")[:80])
    if dkind == "none":
        return "ABSENT", "returned None"

    cands = candidates(desc, tz_offset_s)

    # Fabrication outranks everything, and is tested on every reading.
    if examined_ft is not None:
        for reading, ticks in cands:
            if abs(ticks - examined_ft) < FABRICATION_WINDOW:
                return "FABRICATED", "within %ds of examination, %s reading" % (
                    FABRICATION_WINDOW // TICKS, reading)

    if kind == "icon":
        if dkind != "int":
            return "WRONG", "non-integer icon index %s" % desc.get("repr", "")[:50]
        got = desc["int"]
        if got == truth:
            return "AWARE_OK", "exact"
        if got == meta.get("misread_if_unsigned"):
            return "UNSIGNED_MISREAD", "%s read as %s" % (truth, got)
        return "WRONG", "returned %s, expected %s" % (got, truth)

    if kind == "unrepresentable":
        # The stored ticks decode to no valid date. Handing the ticks back is
        # honest. Refusing is honest. Naming a date is not.
        if dkind == "int" and truth is not None and desc["int"] == truth:
            return "RAW_OK", "stored ticks returned unconverted"
        for reading, ticks in cands:
            if abs(ticks - EPOCH_1601_TICKS) <= TOLERANCE:
                return "GARBAGE_AS_EPOCH", \
                       "0x%X reported as 1601-01-01, indistinguishable from unset" \
                       % truth
        return "WRONG", "a date was named for an input that decodes to none"

    for reading, ticks in cands:
        if abs(ticks - truth) <= TOLERANCE:
            if reading == "raw":
                return "RAW_OK", "stored ticks exact"
            if reading == "ft_if_utc":
                return ("NAIVE_UTC_OK" if desc.get("naive") else "AWARE_OK"), \
                       "instant correct"
            note = "instant correct when read as local time"
            if reading.endswith("_derived"):
                note += ", derived here from the host offset in the run header"
            return ("NAIVE_LOCAL_OK" if desc.get("naive") else "AWARE_OK"), note

    if cands:
        reading, ticks = cands[0]
        return "WRONG", "off by %+.1fs, %s reading" % ((ticks - truth) / TICKS,
                                                       reading)
    return "WRONG", "unusable value %s" % desc.get("repr", "")[:50]


def collect(paths):
    cases = load_manifest()
    obs, headers = [], []
    for path in paths:
        tag = os.path.basename(path)
        tz_off = None
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("record") == "run_header":
                    headers.append(rec)
                    tag = rec["tag"]
                    tz_off = rec.get("tz_offset_s")
                    continue
                case = rec["case"]
                meta = cases.get(case, {})
                res = rec.get("result")
                common = dict(tag=tag, adapter=rec["adapter"], case=case,
                              pass_idx=rec.get("pass"))

                if res is None:
                    for f in ALL_FIELDS:
                        obs.append(dict(common, field=f, verdict="NO_RESULT",
                                        note=rec.get("harness_error", ""),
                                        ticks=None, naive=None,
                                        examined_ft=rec.get("runner_started_ft")))
                    continue

                examined = res.get("examined_at_ft") or rec.get("runner_started_ft")

                if not res.get("ok"):
                    for f in ALL_FIELDS:
                        k, _ = truth_for(meta, f)
                        obs.append(dict(
                            common, field=f,
                            verdict=("NOT_TESTED" if k == "not_tested"
                                     else "FILE_ERROR"),
                            note=(res.get("error") or "")[:100],
                            ticks=None, naive=None, examined_ft=examined))
                    continue

                fields = res.get("fields", {})
                for f in ALL_FIELDS + RAW_FIELDS:
                    if f in RAW_FIELDS and f not in fields:
                        continue
                    desc = fields.get(f)
                    verdict, note = grade(desc, meta, f, examined, tz_off)
                    cs = candidates(desc, tz_off) if desc else []
                    obs.append(dict(common, field=f, verdict=verdict, note=note,
                                    ticks=(cs[0][1] if cs else None),
                                    naive=(desc.get("naive") if desc else None),
                                    examined_ft=examined))
    return headers, obs


def drift_rows(obs):
    by_key = defaultdict(dict)
    for o in obs:
        if o["ticks"] is not None and o["pass_idx"] is not None:
            by_key[(o["tag"], o["adapter"], o["case"], o["field"])][o["pass_idx"]] = o
    rows = []
    for key, passes in sorted(by_key.items()):
        if len(passes) < 2:
            continue
        idx = sorted(passes)
        a, b = passes[idx[0]], passes[idx[-1]]
        delta = b["ticks"] - a["ticks"]
        if abs(delta) >= DRIFT_FLOOR:
            gap = ((b["examined_ft"] or 0) - (a["examined_ft"] or 0)) / TICKS
            rows.append((key, delta / TICKS, gap))
    return rows


def pct(n, d):
    return "%5.1f%%" % (100.0 * n / d) if d else "    -"


def mislabelled(headers):
    out = []
    for h in headers:
        tag = (h.get("tag") or "").lower()
        plat = h.get("platform", "?")
        unixish = any(k in tag for k in ("wsl", "linux", "mac", "darwin"))
        windowsish = "win" in tag and not unixish
        if windowsish and plat != "win32":
            out.append((h.get("tag"), plat,
                        "tag says Windows, the run was on %s" % plat))
        elif unixish and plat == "win32":
            out.append((h.get("tag"), plat,
                        "tag names a Unix host, the run was on win32"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args()

    headers, obs = collect(args.runs)
    if not obs:
        sys.exit("no observations")

    for h in headers:
        print("run %-12s %-34s tz=%s %+ds  gap=%ds passes=%d"
              % (h["tag"], h.get("platform_full", "")[:34], h["tz_name"][0],
                 h.get("tz_offset_s") or 0, h["gap_s"], h["passes"]))
        for name, reason in h.get("skipped", []):
            print("    not run: %-14s %s" % (name, reason))
        for pkg, why in sorted(h.get("unusable_packages", {}).items()):
            print("    unusable: %-20s %s" % (pkg, why))
    print()

    bad = mislabelled(headers)
    if bad:
        print("!" * 72)
        print("MISLABELLED RUN. The tag disagrees with the platform recorded in")
        print("the run header, so the tag is wrong and these numbers mix hosts.")
        for tag, plat, why in bad:
            print("  %-14s %s" % (tag, why))
        print("Delete or rename the file and re-run on the intended host before")
        print("reporting anything below.")
        print("!" * 72)
        print()

    adapters = sorted({o["adapter"] for o in obs})
    cases = sorted({o["case"] for o in obs})
    p1 = [o for o in obs if o["pass_idx"] == 0]

    tags = [h["tag"] for h in headers] or sorted({o["tag"] for o in obs})

    def cell(ad, case, fields, tag=None):
        marks = []
        for f in fields:
            m = [o for o in p1 if o["adapter"] == ad and o["case"] == case
                 and o["field"] == f and (tag is None or o["tag"] == tag)]
            marks.append(MARK.get(m[0]["verdict"], "?") if m else " ")
        return "".join(marks)

    def outcome_table(label, fields, tag=None):
        print("%s  %s" % (label, "pass 1"
                          if tag is None else "pass 1, run %s" % tag))
        print("  %-14s %s" % ("parser", " ".join("%-5s" % c for c in cases)))
        for ad in adapters:
            row = " ".join("%-5s" % cell(ad, c, fields, tag) for c in cases)
            if row.strip():
                print("  %-14s %s" % (ad, row))

    per_run = len(tags) > 1
    for tag in (tags if per_run else [None]):
        outcome_table("TABLE 3  timestamp outcomes, one mark per field "
                      "(creation, access, write),", TIME_FIELDS, tag)
        print()
    print("  A aware+correct   U correct as UTC   L correct as local   "
          "R raw ticks")
    print("  W wrong   Z garbage as 1601   ! FABRICATED   E raised   "
          "F file failed   - absent   . not tested")
    print()

    for tag in (tags if per_run else [None]):
        outcome_table("TABLE 3b  icon index outcomes,", ("icon_index",), tag)
        print()
    print("  M signed field read as unsigned")
    print()

    fab = [o for o in obs if o["verdict"] == "FABRICATED"]
    print("TABLE 4  fabricated values, returned within %ds of examination"
          % (FABRICATION_WINDOW // TICKS))
    if not fab:
        print("  none in these runs")
    else:
        seen = set()
        for o in sorted(fab, key=lambda r: (r["tag"], r["adapter"], r["case"])):
            k = (o["tag"], o["adapter"], o["case"], o["field"])
            if k in seen:
                continue
            seen.add(k)
            print("  %-11s %-14s %-4s %-14s %s" % (o["tag"], o["adapter"],
                                                   o["case"], o["field"],
                                                   o["note"]))
    print()

    rows = drift_rows(obs)
    print("TABLE 4b  values that changed between passes")
    if not rows:
        print("  none: every value was identical in both passes")
    else:
        print("  %-11s %-14s %-4s %-14s %9s %9s"
              % ("run", "parser", "case", "field", "moved_s", "gap_s"))
        for (tag, ad, case, field), delta, gap in rows:
            print("  %-11s %-14s %-4s %-14s %9.1f %9.1f"
                  % (tag, ad, case, field, delta, gap))
        print("  a value that moves with the gap is a clock read, not a file read")
    print()

    print("TABLE 5  outcome classes per parser, timestamp fields, both passes")
    print("  %-14s %7s %7s %7s %7s   %s"
          % ("parser", "graded", "correct", "loud", "silent", "silent wrong rate"))
    for ad in adapters:
        mine = [o for o in obs if o["adapter"] == ad and o["field"] in TIME_FIELDS
                and o["verdict"] not in EXCLUDED]
        c = sum(1 for o in mine if o["verdict"] in CORRECT)
        l = sum(1 for o in mine if o["verdict"] in LOUD)
        s = sum(1 for o in mine if o["verdict"] in SILENT_WRONG)
        print("  %-14s %7d %7d %7d %7d   %s"
              % (ad, len(mine), c, l, s, pct(s, len(mine))))
    print()

    print("TABLE 5b  what a naive timestamp means, by parser (pass 1, "
          "representable cases)")
    print("  %-14s %8s %8s %8s %8s"
          % ("parser", "aware", "naive", "as UTC", "as local"))
    for ad in adapters:
        mine = [o for o in p1 if o["adapter"] == ad and o["field"] in TIME_FIELDS
                and o["verdict"] in CORRECT]
        aware = sum(1 for o in mine if o["naive"] is False)
        naive = sum(1 for o in mine if o["naive"] is True)
        asutc = sum(1 for o in mine if o["verdict"] == "NAIVE_UTC_OK")
        aslocal = sum(1 for o in mine if o["verdict"] == "NAIVE_LOCAL_OK")
        print("  %-14s %8d %8d %8d %8d" % (ad, aware, naive, asutc, aslocal))
    print("  a parser with a count in both of the last two columns would be")
    print("  self-inconsistent; a count in only one names its convention,")
    print("  which nothing in the returned value discloses")
    print()

    raws = [o for o in obs if o["field"] in RAW_FIELDS
            and o["verdict"] not in EXCLUDED]
    if raws:
        print("TABLE 5c  parsers exposing the stored ticks alongside the "
              "converted value")
        for ad in sorted({o["adapter"] for o in raws}):
            mine = [o for o in raws if o["adapter"] == ad]
            ok = sum(1 for o in mine if o["verdict"] in CORRECT)
            print("  %-14s %d of %d raw reads exact" % (ad, ok, len(mine)))
        print("  where conversion fails, only these parsers let an examiner")
        print("  recover what the file actually stored")
        print()

    print("TOTALS  timestamp fields, all passes, all runs")
    tot = defaultdict(int)
    for o in obs:
        if o["field"] in TIME_FIELDS:
            tot[o["verdict"]] += 1
    graded = sum(v for k, v in tot.items() if k not in EXCLUDED)
    for v in ORDER:
        if tot[v]:
            flag = ("correct" if v in CORRECT else
                    "loud" if v in LOUD else
                    "silent wrong" if v in SILENT_WRONG else "excluded")
            print("  %-17s %5d  %s   %s" % (v, tot[v], pct(tot[v], graded), flag))
    s = sum(tot[v] for v in SILENT_WRONG)
    print("  %-17s %5d" % ("graded", graded))
    print("  silent wrong rate %s of graded timestamp observations" % pct(s, graded))


if __name__ == "__main__":
    main()
