#!/usr/bin/env python3
"""Recheck the reported figures from the raw records without using tabulate.py.

    python recheck.py results/run_w2-lagos.jsonl ... (the six main runs)
"""

import json
import sys
from collections import defaultdict

TICKS = 10_000_000
FAB_WINDOW = 5 * TICKS
TOLERANCE = 1 * TICKS
FIELDS = ("creation_time", "access_time", "write_time")


def readings(d):
    r = {}
    for k in ("ft_if_utc", "ft_if_local"):
        if isinstance(d.get(k), int):
            r[k] = d[k]
    if d.get("kind") == "int":
        r["raw"] = d["int"]
    return r


def main(manifest, paths):
    cases = json.load(open(manifest))
    cases = cases.get("cases", cases)

    counts = defaultdict(int)
    fab = defaultdict(set)
    correct = []
    ret, exam = {}, {}
    naive = defaultdict(int)

    for path in paths:
        recs = [json.loads(l) for l in open(path) if l.strip()]
        tag = recs[0]["tag"]
        for o in recs[1:]:
            res = o.get("result") or {}
            ad, case, pi = o["adapter"], o["case"], o["pass"]
            eft = res.get("examined_at_ft")
            if eft is not None:
                exam[(tag, ad, case, pi)] = eft
            for f in FIELDS:
                ef = (cases.get(case, {}).get("expected_fields") or {}).get(f)
                if not ef:
                    continue
                counts[ad] += 1
                d = (res.get("fields") or {}).get(f)
                if not isinstance(d, dict):
                    continue
                rs = readings(d)
                truth = ef.get("filetime")
                if not rs or truth is None:
                    continue
                ret[(tag, ad, case, f, pi)] = rs
                if eft is not None and any(abs(v - eft) < FAB_WINDOW
                                           for v in rs.values()):
                    fab[(tag, ad)].add(case)
                    continue
                if not ef.get("decoded_utc"):
                    continue
                best = min(abs(v - truth) for v in rs.values())
                if best <= TOLERANCE:
                    correct.append(best)
                if d.get("naive"):
                    u = abs(rs.get("ft_if_utc", truth + 10 ** 18)
                            - truth) <= TOLERANCE
                    l = abs(rs.get("ft_if_local", truth + 10 ** 18)
                            - truth) <= TOLERANCE
                    naive["both" if (u and l) else "utc_only" if u
                          else "local_only" if l else "neither"] += 1

    print("observations")
    for ad in sorted(counts):
        print("  %-14s %4d" % (ad, counts[ad]))
    print("  %-14s %4d" % ("TOTAL", sum(counts.values())))

    print("\nfabricated, |returned - examined| < %ds" % (FAB_WINDOW // TICKS))
    for (tag, ad), cs in sorted(fab.items()):
        print("  %-12s %-14s %2d  %s" % (tag, ad, len(cs), " ".join(sorted(cs))))

    print("\ngraded correct %d; largest distance from the stored instant "
          "%d ticks (%.7f s), tolerance %d"
          % (len(correct), max(correct), max(correct) / TICKS, TOLERANCE))

    print("\nnaive values by the reading that matched")
    for k in ("both", "utc_only", "local_only", "neither"):
        print("  %-11s %4d" % (k, naive[k]))

    print("\ntwo-pass drift")
    worst = 0.0
    for tag in sorted({k[0] for k in ret}):
        rows = []
        for (t, ad, case, f, pi) in list(ret):
            if t != tag or pi != 0 or (t, ad, case, f, 1) not in ret:
                continue
            r1, r2 = ret[(t, ad, case, f, 0)], ret[(t, ad, case, f, 1)]
            key = next((k for k in ("ft_if_local", "ft_if_utc")
                        if k in r1 and k in r2), None)
            e1 = exam.get((t, ad, case, 0))
            e2 = exam.get((t, ad, case, 1))
            if key is None or e1 is None or e2 is None:
                continue
            moved = (r2[key] - r1[key]) / TICKS
            if abs(moved) < 1.0:
                continue
            rows.append((moved, (e2 - e1) / TICKS))
        if rows:
            d = max(abs(m - c) for m, c in rows)
            worst = max(worst, d)
            gaps = [c for _, c in rows]
            print("  %-12s %3d pairs moved; gap %.1f to %.1f s; "
                  "max disagreement %.3f s"
                  % (tag, len(rows), min(gaps), max(gaps), d))
    print("  worst over all runs %.3f s" % worst)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
