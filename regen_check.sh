#!/usr/bin/env bash
# Does make_cases.py reproduce the committed corpus, byte for byte?
#
# Run from the repository root. It never writes to cases/, so the corpus the
# figures describe cannot be harmed by running this.
set -u
STUDY="$(pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cp -r "$STUDY/harness" "$STUDY/make_cases.py" "$TMP/" 2>/dev/null
cd "$TMP" || exit 1
python3 -I make_cases.py >/dev/null 2>&1 || { echo "make_cases.py failed in isolation"; exit 1; }

cd "$STUDY" || exit 1
python3 -I - "$TMP/cases" <<'PY'
import hashlib, os, sys
fresh = sys.argv[1]
h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
names = sorted(f for f in os.listdir("cases") if f.endswith(".lnk"))
same, diff, absent = [], [], []
for n in names:
    q = os.path.join(fresh, n)
    if not os.path.exists(q):
        absent.append(n)
    elif h(os.path.join("cases", n)) == h(q):
        same.append(n)
    else:
        diff.append(n)
print("  committed corpus : %d files" % len(names))
print("  reproduced exactly: %d" % len(same))
print("  differing         : %d  %s" % (len(diff), " ".join(diff[:13])))
print("  not generated     : %d  %s" % (len(absent), " ".join(absent[:13])))
print()
if diff or absent:
    print("  The generator does NOT reproduce the committed corpus.")
    print("  Keep cases/ and SHA256SUMS as they are: they are what the")
    print("  figures were measured against. Do not run make_cases.py in")
    print("  place, and change the README so it does not tell anyone to.")
else:
    print("  The generator reproduces the corpus exactly, so make_cases.py")
    print("  is safe to run and the README's claim holds.")
PY
