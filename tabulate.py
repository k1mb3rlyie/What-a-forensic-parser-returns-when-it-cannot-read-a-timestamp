#!/usr/bin/env python3
"""Grade the run records against the constructive ground truth.

Grading is kept out of the adapters deliberately. The adapters record what a
parser returned; this file decides what that meant. A change to the rules can
therefore be applied to records already collected, and a defect in the rules
cannot be concealed by the collection. An earlier study of ours failed exactly
there, so the separation is not stylistic.

Every returned timestamp is tested against both readings of a naive value,
never one chosen in advance:

  AWARE_OK          timezone-aware, and the instant is right
  NAIVE_UTC_OK      naive; right if the value is taken to mean UTC
  NAIVE_LOCAL_OK    naive; right if the value is taken to mean local time
  RAW_OK            the stored ticks were handed back unconverted
  ABSENT            reported as absent
  FIELD_ERROR       this field raised
  FILE_ERROR        the file would not parse at all
  WRONG             a value, matching neither reading of the truth
  GARBAGE_AS_EPOCH  an unrepresentable input reported as 1601-01-01
  UNSIGNED_MISREAD  a negative signed field read as a large unsigned one
  FABRICATED        the value tracks the examination clock, not the file

These collapse into three classes. CORRECT is the field's own value by some
reading. LOUD is a refusal to answer, which a practitioner can see. SILENT
WRONG is a value that is not the field's value, which a practitioner cannot
see. The last is the quantity the study is about.

FABRICATED outranks every other verdict: a value within five seconds of the
moment of examination did not come out of the file, whatever else is true of
it. The pass-to-pass drift check confirms it without reference to that
threshold.

Two faults belong to the instrument rather than the parser, and are handled
here so that records already collected need not be collected again:

  INSTRUMENT_FAULT  the adapter returned one constant for every timestamp of
                    every case, including T0's three distinct values, so it
                    never read the header. Excluded from grading.

  A naive value whose local reading the adapter could not compute has that
  reading rebuilt from the UTC reading and the offset recorded with the
  result. On Windows `datetime.astimezone()` on a naive value near the Unix
  epoch raises the same OSError the study measures, so without this a
  correct local value is graded WRONG.

Every per-parser table is keyed by run as well as parser. Pooling a parser's
Windows and Linux records would hide the platform difference the study is
about.

Usage:
    python tabulate.py results/run_linux-lagos.jsonl [more.jsonl ...]
"""

import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "cases", "manifest.json")

TICKS = 10_000_000
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
EXCLUDED = ("NOT_TESTED", "NO_RESULT", "INSTRUMENT_FAULT")

ORDER = CORRECT + LOUD + SILENT_WRONG + EXCLUDED

MARK = {"AWARE_OK": "A", "NAIVE_UTC_OK": "U", "NAIVE_LOCAL_OK": "L",
        "RAW_OK": "R", "ABSENT": "-", "FIELD_ERROR": "E", "FILE_ERROR": "F",
        "WRONG": "W", "GARBAGE_AS_EPOCH": "Z", "UNSIGNED_MISREAD": "M",
        "FABRICATED": "!", "NOT_TESTED": ".", "NO_RESULT": "?",
        "INSTRUMENT_FAULT": "X"}


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


def truth_for(meta, field):
    """(kind, value) for one field of one case.

    kind is one of:
      ticks               a representable instant, value is FILETIME ticks
      unrepresentable     the stored ticks decode to no valid date
      icon                value is the expected signed icon index
      not_tested          this case does not exercise this field
    """
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


def candidates(desc, offset_s=None):
    """Possible instants for a described value, as (reading, ticks).

    offset_s is the examining host's UTC offset as recorded with the result.
    It is used only to rebuild a local reading the adapter failed to compute.
    """
    out = []
    if desc.get("kind") == "int":
        out.append(("raw", desc["int"]))
    for reading in ("ft_if_utc", "ft_if_local"):
        v = desc.get(reading)
        if isinstance(v, int):
            out.append((reading, v))
    utc = desc.get("ft_if_utc")
    if (desc.get("naive") and isinstance(utc, int) and offset_s is not None
            and not isinstance(desc.get("ft_if_local"), int)):
        out.append(("ft_if_local_rebuilt", utc - offset_s * TICKS))
    return out


def grade(desc, meta, field, examined_ft, offset_s=None):
    """Grade one returned value. Returns (verdict, note)."""
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

    cands = candidates(desc, offset_s)

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
            return ("NAIVE_LOCAL_OK" if desc.get("naive") else "AWARE_OK"), \
                   ("instant correct when read as local time"
                    + (", local reading rebuilt from recorded offset"
                       if reading == "ft_if_local_rebuilt" else ""))

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
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("record") == "run_header":
                    headers.append(rec)
                    tag = rec["tag"]
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
                offset = res.get("tz_offset_s")
                for f in ALL_FIELDS + RAW_FIELDS:
                    if f in RAW_FIELDS and f not in fields:
                        continue
                    desc = fields.get(f)
                    verdict, note = grade(desc, meta, f, examined, offset)
                    cs = candidates(desc, offset) if desc else []
                    obs.append(dict(common, field=f, verdict=verdict, note=note,
                                    ticks=(cs[0][1] if cs else None),
                                    naive=(desc.get("naive") if desc else None),
                                    examined_ft=examined))
    mark_instrument_faults(obs)
    return headers, obs


def mark_instrument_faults(obs):
    """Exclude an adapter whose timestamps never vary.

    The corpus stores ten different timestamp values, and T0 alone stores
    three. A reader that returns the same instant for all of them is not
    reading the header, so grading its output would score the instrument,
    not the parser. Its timestamp observations are reclassified, per run.
    """
    by_run = defaultdict(list)
    for o in obs:
        if o["field"] in TIME_FIELDS:
            by_run[(o["tag"], o["adapter"])].append(o)
    for (tag, ad), mine in by_run.items():
        valued = [o for o in mine if o["ticks"] is not None]
        if len({o["case"] for o in valued}) < 3:
            continue
        if len({o["ticks"] for o in valued}) == 1:
            for o in mine:
                o["verdict"] = "INSTRUMENT_FAULT"
                o["note"] = "same instant returned for every case"


def drift_rows(obs):
    """Values that changed between passes.

    A value read from the file is identical in both passes. A value taken
    from the clock moves by the gap. This needs no threshold of its own and
    so confirms the fabrication verdict independently.
    """
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

    rows = sorted({(o["tag"], o["adapter"]) for o in obs})
    multi = len({t for t, _ in rows}) > 1
    width = max(len("%s %s" % r) if multi else len(r[1]) for r in rows) + 1

    def label(row):
        return "%s %s" % row if multi else row[1]

    def of(row, pool):
        return [o for o in pool if (o["tag"], o["adapter"]) == row]

    cases = sorted({o["case"] for o in obs})
    p1 = [o for o in obs if o["pass_idx"] == 0]

    def cell(row, case, fields):
        marks = []
        for f in fields:
            m = [o for o in of(row, p1) if o["case"] == case and o["field"] == f]
            marks.append(MARK.get(m[0]["verdict"], "?") if m else " ")
        return "".join(marks)

    def head(*cols):
        return "  %-*s %s" % (width, "parser", " ".join(cols))

    print("TABLE 3  timestamp outcomes, pass 1, one mark per field "
          "(creation, access, write)")
    print(head(*("%-5s" % c for c in cases)))
    for row in rows:
        print("  %-*s %s" % (width, label(row),
                             " ".join("%-5s" % cell(row, c, TIME_FIELDS)
                                      for c in cases)))
    print("  A aware+correct   U correct as UTC   L correct as local   "
          "R raw ticks")
    print("  W wrong   Z garbage as 1601   ! FABRICATED   E raised   "
          "F file failed   - absent   . not tested")
    print("  X instrument fault, excluded: the adapter never read the header")
    print()

    print("TABLE 3b  icon index outcomes, pass 1")
    print(head(*("%-5s" % c for c in cases)))
    for row in rows:
        print("  %-*s %s" % (width, label(row),
                             " ".join("%-5s" % cell(row, c, ("icon_index",))
                                      for c in cases)))
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

    drift = drift_rows(obs)
    print("TABLE 4b  values that changed between passes")
    if not drift:
        print("  none: every value was identical in both passes")
    else:
        print("  %-11s %-14s %-4s %-14s %9s %9s"
              % ("run", "parser", "case", "field", "moved_s", "gap_s"))
        for (tag, ad, case, field), delta, gap in drift:
            print("  %-11s %-14s %-4s %-14s %9.1f %9.1f"
                  % (tag, ad, case, field, delta, gap))
        print("  a value that moves with the gap is a clock read, not a file read")
    print()

    print("TABLE 5  outcome classes per parser, timestamp fields, both passes")
    print("  %-*s %7s %7s %7s %7s   %s"
          % (width, "parser", "graded", "correct", "loud", "silent",
             "silent wrong rate"))
    for row in rows:
        mine = [o for o in of(row, obs) if o["field"] in TIME_FIELDS]
        faulty = sum(1 for o in mine if o["verdict"] == "INSTRUMENT_FAULT")
        mine = [o for o in mine if o["verdict"] not in EXCLUDED]
        c = sum(1 for o in mine if o["verdict"] in CORRECT)
        l = sum(1 for o in mine if o["verdict"] in LOUD)
        s = sum(1 for o in mine if o["verdict"] in SILENT_WRONG)
        print("  %-*s %7d %7d %7d %7d   %s%s"
              % (width, label(row), len(mine), c, l, s, pct(s, len(mine)),
                 "   (%d excluded, instrument fault)" % faulty if faulty else ""))
    print()

    print("TABLE 5b  what a naive timestamp means, by parser (pass 1, "
          "representable cases)")
    print("  %-*s %8s %8s %8s %8s"
          % (width, "parser", "aware", "naive", "as UTC", "as local"))
    for row in rows:
        mine = [o for o in of(row, p1) if o["field"] in TIME_FIELDS
                and o["verdict"] in CORRECT]
        aware = sum(1 for o in mine if o["naive"] is False)
        naive = sum(1 for o in mine if o["naive"] is True)
        asutc = sum(1 for o in mine if o["verdict"] == "NAIVE_UTC_OK")
        aslocal = sum(1 for o in mine if o["verdict"] == "NAIVE_LOCAL_OK")
        print("  %-*s %8d %8d %8d %8d" % (width, label(row), aware, naive,
                                          asutc, aslocal))
    print("  a parser with a count in both of the last two columns would be")
    print("  self-inconsistent; a count in only one names its convention,")
    print("  which nothing in the returned value discloses")
    print()

    raws = [o for o in obs if o["field"] in RAW_FIELDS
            and o["verdict"] not in EXCLUDED]
    if raws:
        print("TABLE 5c  parsers exposing the stored ticks alongside the "
              "converted value")
        for row in sorted({(o["tag"], o["adapter"]) for o in raws}):
            mine = of(row, raws)
            ok = sum(1 for o in mine if o["verdict"] in CORRECT)
            print("  %-*s %d of %d raw reads exact" % (width, label(row), ok,
                                                       len(mine)))
        print("  where conversion fails, only these parsers let an examiner")
        print("  recover what the file actually stored")
        print()

    # Per run. A rate pooled across platforms describes no platform.
    for tag in sorted({t for t, _ in rows}):
        print("TOTALS  %s, timestamp fields, all passes" % tag)
        tot = defaultdict(int)
        for o in obs:
            if o["tag"] == tag and o["field"] in TIME_FIELDS:
                tot[o["verdict"]] += 1
        graded = sum(v for k, v in tot.items() if k not in EXCLUDED)
        for v in ORDER:
            if tot[v]:
                flag = ("correct" if v in CORRECT else
                        "loud" if v in LOUD else
                        "silent wrong" if v in SILENT_WRONG else "excluded")
                print("  %-17s %5d  %s   %s"
                      % (v, tot[v],
                         pct(tot[v], graded) if v not in EXCLUDED else "     ",
                         flag))
        s = sum(tot[v] for v in SILENT_WRONG)
        print("  %-17s %5d" % ("graded", graded))
        print("  silent wrong rate %s of graded timestamp observations"
              % pct(s, graded))
        print()


if __name__ == "__main__":
    main()
