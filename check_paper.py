#!/usr/bin/env python3
"""Refuse any figure in the paper that cannot be traced to a computed claim.

Every number in the paper is extracted and matched against the values in
`claims.json`. Anything that does not match is listed for review. The check
cannot tell a true statement from a false one, but it can tell a figure that
came from the records from one that came from memory, and in this study every
error was the second kind.

Numbers that legitimately have no claim behind them, such as a source line
number or a year in a citation, are declared in EXEMPT below. That list is
deliberately short and explicit: adding to it is a decision, not a default.

Also checks: em-dashes, which the author does not use; implementations
described as tested that have no records; and claim keys quoted in the paper
that do not exist.

Usage:
    python check_paper.py ../out/LNK-paper-v2.md
    python check_paper.py paper.md --claims claims.json
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Figures with no computed claim behind them. A plain string allows the token
# anywhere. A (reason, pattern) pair allows it only on a line matching the
# pattern, which matters more than it sounds: exempting a bare small integer
# for one reason otherwise exempts it everywhere, and a measured value that
# happens to share it passes unchecked. That hole let a fabrication count
# through once, so every ambiguous token is now scoped to its context.
EXEMPT_SCOPED = {
    "28": ("creation_time offset in decimal, or a journal volume",
           r"offset|Horsman|Digital Investigation 28"),
    "36": ("access_time offset in decimal", r"offset"),
    "44": ("write_time offset in decimal", r"offset"),
    "5": ("the fabrication window in seconds, a stated parameter",
          r"five second|within 5|fabricat|seconds of"),
    "60": ("the inter-pass gap in seconds, a stated parameter",
           r"sixty|gap|60 second|minute"),
    "30": ("DFIR Review submission number", r"submission 30|DFIR Review"),
    "42": ("journal volume", r"Nordvik|Digital Investigation 4"),
    "43": ("journal volume", r"Nordvik|Digital Investigation 4"),
    "49": ("journal volume", r"Vanini|Digital Investigation 49"),
    "40": ("HICSS number", r"HICSS|Beckett"),
    "7": ("journal volume", r"Garfinkel|Digital Investigation 7"),
    "28": ("journal volume or field offset in decimal",
           r"Horsman|Digital Investigation 28|creation_time: 28|offset"),
    "21": ("module count after the 1.0.0a1 split", r"module|twenty-one|rewrite"),
    "9": ("line count of the quoted function", r"nine lines|line"),
    "8": ("line count of the quoted function", r"eight lines|line"),
    "24": ("the registered prediction, stated as four cases times three "
           "fields times two passes and recorded in the paper as falsified",
           r"expected 24|predict"),
}

# Figures with no claim behind them, each with the reason it is allowed.
EXEMPT = {
    "277": "pylnk3.py source line, quoted",
    "281": "pylnk3.py source line, quoted",
    "283": "pylnk3.py source line, quoted",
    "284": "pylnk3.py source line, quoted",
    "285": "pylnk3.py source line, quoted",
    "562": "pylnk.py source line, in the unusable-package reason",
    "76": "MS-SHLLINK header size, from the specification",
    "0x1C": "MS-SHLLINK field offset, from the specification",
    "0x24": "MS-SHLLINK field offset, from the specification",
    "0x2C": "MS-SHLLINK field offset, from the specification",
    "0x38": "MS-SHLLINK field offset, from the specification",
    "32": "field width in bits, from the specification",
    "64": "field width in bits, from the specification",
    "53": "float64 mantissa bits",
    "100": "nanoseconds per FILETIME tick",
    "10": "decimal scale in the conversion formula",
    "1601": "FILETIME epoch year, from the specification",
    "1970": "Unix epoch year",
    "11644473600": "seconds between the two epochs, from the specification",
    "10000000": "ticks per second, from the specification",
    "134774": "days between the epochs, quoted from the source comment",
    "17025": "ISO standard number",
    "1993": "Daubert citation year",
    "2005": "Carrier citation year",
    "2007": "Beckett citation year",
    "2010": "Garfinkel citation year",
    "2019": "Horsman citation year",
    "2022": "Nordvik citation year",
    "2024": "Vanini citation year",
    "1998": "McKeeman citation year",
    "509": "Daubert reporter volume",
    "579": "Daubert reporter page",
    "163": "Horsman page range",
    "175": "Horsman page range",
    "S64": "Garfinkel page range",
    "S73": "Garfinkel page range",
    "301476": "Nordvik article number",
    "301759": "Vanini article number",
    "107": "McKeeman page range",
}

NUM = re.compile(r"(?<![\w.])(0x[0-9A-Fa-f]+|\d+(?:\.\d+)?)(?![\w])")
# Written as a code point so this file contains no literal one.
EM_DASH = chr(0x2014)

CLAIM_REF = re.compile(r"\{\{([a-zA-Z0-9_.\-]+)\}\}")
CODE_FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")

# Tokens are matched whole, longest kind first, so a date is never shredded
# into a year and two small integers and a version is never read as a decimal.
# A checker that cries wolf gets ignored, and an ignored checker is worse than
# none, so anything structurally not a figure is removed before matching.
DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME = re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b")
VERSION = re.compile(r"\b\d+\.\d+(?:\.\d+)?(?:[ab]\d+)?\b")
HEXNUM = re.compile(r"0x[0-9A-Fa-f]+")
PLAIN = re.compile(r"(?<![\w.\-])-?\d+(?:\.\d+)?(?![\w.])")

# Cross-references and structure, never assertions about data.
STRUCTURAL = re.compile(
    r"(?:Sections?|Tables?|Figures?|Appendix|step|version)\s+"
    r"\d+(?:\.\d+)*(?:[ab]\d+)?"
    r"(?:\s*(?:to|and|,|through)\s*\d+(?:\.\d+)*)*",
    re.I)
BARE_SECTION_REF = re.compile(r"\(\s*\d+\.\d+(?:\s*,\s*\d+\.\d+)*\s*\)")
THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
PROSE_DATE = re.compile(
    r"\b(?:\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})\b")


def figures_in(text):
    """Yield (token, line number) for every figure the paper asserts.

    Longest token kind first, so a timestamp is never shredded into a year and
    three small integers, and a version is never read as a decimal. Structural
    cross-references are removed before matching.
    """
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.replace("−", "-").replace("–", "-")
        if line.lstrip().startswith("#"):
            continue                      # headings carry section numbers
        if line.lstrip().startswith(("- [", "|---", "|:--")):
            continue                      # reference list, table rules
        line = THOUSANDS.sub("", line)
        line = STRUCTURAL.sub(" ", line)
        line = BARE_SECTION_REF.sub(" ", line)

        # A prose date is matched whole, so "28 December 2019" is checked as a
        # date against the release metadata rather than as the integers 28
        # and 2019.
        for m in PROSE_DATE.finditer(line):
            yield m.group(0), lineno
        line = PROSE_DATE.sub(" ", line)

        for rx in (DATETIME, DATE, TIME, VERSION, HEXNUM, PLAIN):
            for m in rx.finditer(line):
                yield m.group(0), lineno
            line = rx.sub(" ", line)


MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
ISO_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def date_spellings(iso):
    """The ways a date may legitimately appear in prose.

    A release date is a claim whether it is written 2019-12-28 or
    28 December 2019, so both spellings resolve to the same claim and neither
    is flagged.
    """
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        name = MONTHS[m - 1]
        return {iso, "%d %s %d" % (d, name, y), "%s %d, %d" % (name, d, y),
                "%s %d %d" % (name, d, y)}
    except BaseException:
        return {iso}


def claim_values(claims):
    """Every value in claims.json, flattened to comparable strings."""
    out = set()

    def add(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.add(str(v))
            if isinstance(v, float) and v.is_integer():
                out.add(str(int(v)))
            if isinstance(v, int):
                out.add("0x%016X" % v)
                out.add("%.1f" % v)
            return
        if isinstance(v, str):
            out.add(v)
            if ISO_DATE_ONLY.match(v):
                out.update(date_spellings(v))
            # Tokens inside a string are claims too: a version in
            # "LnkAnalyser==0.0.1", a date inside a longer sentence. They are
            # consumed longest-kind-first and removed as they are taken, for
            # the same reason the paper side does it. Extracting bare numbers
            # from "09:15:30" would add 09, 15 and 30 to the permitted set and
            # thereby permit any two-digit figure anywhere in the paper. That
            # is not a hypothetical: it let an unverified fabrication count
            # pass as though a claim backed it.
            rest = v
            for rx in (DATETIME, DATE, TIME, VERSION, HEXNUM, PLAIN):
                for m in rx.finditer(rest):
                    out.add(m.group(0))
                rest = rx.sub(" ", rest)
            return
        if isinstance(v, (list, tuple)):
            for x in v:
                add(x)
            return
        if isinstance(v, dict):
            for x in v.values():
                add(x)

    for v in claims.values():
        add(v)
    return out


BIBLIOGRAPHY = re.compile(
    r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.S)
TEX_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)
TEX_WRAPPER = re.compile(
    r"\\(?:texttt|textit|textbf|emph|textsc|mbox|text)\{([^{}]*)\}")
TEX_DROPPED = re.compile(r"\\(?:label|ref|cite|citep|eqref|input|include)\{[^{}]*\}")


def delatex(text):
    """Make LaTeX source comparable with the figures claims.py computes.

    Four things in LaTeX would otherwise defeat the figure scan, and the first
    is the one that matters:

    A thousands separator is written {,} so that LaTeX sets it with the right
    spacing, which means 1{,}716 tokenises as 1 and 716. The paper's headline
    count was therefore never checked, and worse, 716 and 938 and the other
    fragments entered the permitted set from the claims side as well, so the
    checker reported no problem while verifying nothing about the figure. That
    is the same failure this study describes, in the instrument.

    The bibliography is removed. A DOI, an arXiv identifier, a page range and
    a publication year are figures in the typographical sense and claims about
    nothing the study measured; leaving them in produced dozens of complaints
    that trained the reader to ignore the output.

    Comments are removed because a commented-out figure is not in the paper,
    and \\texttt{} and friends are unwrapped so a value set in monospace is
    read as the value rather than as part of a macro name.
    """
    text = BIBLIOGRAPHY.sub(" ", text)
    text = TEX_COMMENT.sub("", text)
    text = TEX_DROPPED.sub(" ", text)
    for _ in range(3):           # nested wrappers, bounded rather than while
        text, n = TEX_WRAPPER.subn(r"\1", text)
        if not n:
            break
    text = text.replace("{,}", ",")
    text = text.replace("$-$", "-").replace(r"\%", "%")
    text = text.replace("~", " ")
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--claims", default=os.path.join(HERE, "claims.json"))
    ap.add_argument("--show-exempt", action="store_true")
    ap.add_argument("--render", metavar="OUT",
                    help="write a copy with every {{claim.key}} replaced by "
                         "its computed value; refuses if any key is unknown")
    args = ap.parse_args()

    if not os.path.exists(args.claims):
        sys.exit("no %s; run claims.py first" % args.claims)
    with open(args.claims, encoding="utf-8") as fh:
        claims = json.load(fh)
    with open(args.paper, encoding="utf-8") as fh:
        text = fh.read()

    if args.paper.lower().endswith((".tex", ".ltx")):
        text = delatex(text)
        print("LaTeX source: bibliography and comments removed, {,} restored")
        print()

    values = claim_values(claims)
    problems = 0

    # 1. claim keys quoted in the paper must exist
    bad_keys = sorted({k for k in CLAIM_REF.findall(text) if k not in claims})
    if bad_keys:
        problems += len(bad_keys)
        print("UNKNOWN CLAIM KEYS (%d)" % len(bad_keys))
        for k in bad_keys:
            print("  {{%s}}" % k)
        print()

    # 2. em-dashes
    dashes = text.count(EM_DASH)
    if dashes:
        problems += dashes
        print("EM-DASHES (%d)" % dashes)
        for i, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                print("  line %d: %s" % (i, line.strip()[:88]))
        print()

    # 3. numbers with no computed claim behind them.
    #
    # Fenced blocks are excluded: they are quoted source and program output,
    # where a figure is a transcript rather than an assertion the paper makes.
    #
    # Inline code spans are NOT excluded, and that is deliberate. Every stored
    # FILETIME in Table 1 is written as `0x019DB1DED53E8000`, every version as
    # `0.4.3`, and excluding them put the study's own inputs beyond the reach
    # of the checker: a wrong digit in a stored value was invisible. Verifying
    # the paper's prose while skipping the table of values it rests on is the
    # kind of validation that passes without checking anything.
    prose = CODE_FENCE.sub(" ", text)
    prose_lines = prose.splitlines()
    unmatched = {}
    for tok, lineno in figures_in(prose):
        bare = tok.lstrip("-")
        if tok in values or bare in values:
            continue
        if tok in EXEMPT or bare in EXEMPT:
            continue
        scoped = EXEMPT_SCOPED.get(tok) or EXEMPT_SCOPED.get(bare)
        if scoped:
            line = prose_lines[lineno - 1] if lineno <= len(prose_lines) else ""
            if re.search(scoped[1], line, re.I):
                continue
        unmatched.setdefault(tok, []).append(lineno)

    if unmatched:
        problems += len(unmatched)
        print("FIGURES WITH NO COMPUTED CLAIM (%d distinct)" % len(unmatched))
        print("Each is either stale, mistyped, or needs an EXEMPT entry.")
        for tok in sorted(unmatched, key=lambda t: (-len(unmatched[t]), t)):
            lines = unmatched[tok]
            shown = ", ".join(str(n) for n in lines[:6])
            more = "" if len(lines) <= 6 else " +%d more" % (len(lines) - 6)
            print("  %-22s lines %s%s" % (tok, shown, more))
        print()

    # 4. an implementation called tested must have records
    run_adapters = set()
    for k, v in claims.items():
        if k.endswith(".adapters_run") and isinstance(v, list):
            run_adapters.update(v)
    names = {"pylnk3": "a1_pylnk3", "LnkParse3": "a3_lnkparse3",
             "liblnk": "a5_liblnk", "Shell API": "a7_shellapi",
             "LECmd": "a8_lecmd"}
    claimed_tested = []
    for row in re.findall(r"^\|.*\|$", text, re.M):
        if "Tested" not in row:
            continue
        for label, adapter in names.items():
            if label in row and adapter not in run_adapters:
                claimed_tested.append((label, adapter))
    if claimed_tested:
        problems += len(claimed_tested)
        print("DESCRIBED AS TESTED WITH NO RECORDS (%d)" % len(claimed_tested))
        for label, adapter in claimed_tested:
            print("  %-14s no run records for %s" % (label, adapter))
        print()

    if args.show_exempt:
        print("EXEMPT figures in use:")
        for tok, why in sorted(EXEMPT.items()):
            if tok in text:
                print("  %-14s %s" % (tok, why))
        print()

    if args.render:
        if bad_keys:
            print("not rendering: %d claim key(s) do not exist yet"
                  % len(bad_keys))
        else:
            def fmt(v):
                if isinstance(v, bool):
                    return "yes" if v else "no"
                if isinstance(v, (list, tuple)):
                    return ", ".join(str(x) for x in v)
                return str(v)

            rendered = CLAIM_REF.sub(
                lambda m: fmt(claims[m.group(1)]), text)
            with open(args.render, "w", encoding="utf-8") as fh:
                fh.write(rendered)
            n = len(CLAIM_REF.findall(text))
            print("rendered %d claim reference(s) -> %s" % (n, args.render))

    print("claims loaded: %d    distinct values: %d" % (len(claims), len(values)))
    print("problems: %d" % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())