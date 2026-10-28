"""Shared serialisation for the parser adapters.

Every adapter runs inside its own virtual environment, so this module is
imported by explicit path rather than installed. It must therefore depend on
nothing outside the standard library.

The job of an adapter is to record what a parser returned, not to decide
whether it was right. Grading happens later, in tabulate.py, from these
records. So describe() preserves the type and the literal repr of every
value, and where a value is a timestamp it records BOTH possible readings of
it rather than choosing one:

  ft_if_local   the instant, if a naive datetime means local time
  ft_if_utc     the instant, if a naive datetime means UTC

A timezone-aware value gives the same number for both. A naive one does not,
and the gap between them is the measurement, not a nuisance to be resolved.
"""

import datetime as _dt
import json
import os
import sys
import time
import traceback

EPOCH_DELTA = 11_644_473_600  # seconds from 1601-01-01 to 1970-01-01
TICKS = 10_000_000            # 100-nanosecond intervals per second

_UNIX_EPOCH_UTC = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


# --------------------------------------------------------------------------
# failure markers
# --------------------------------------------------------------------------

class Raised:
    """A field access that raised, recorded instead of propagating.

    A parser may read two timestamps and raise on the third. Letting the
    first exception end the call would throw away the other two results, so
    each field is attempted separately.
    """

    def __init__(self, exc):
        self.exc_name = type(exc).__name__
        self.message = str(exc)

    def __repr__(self):
        return "Raised(%s: %s)" % (self.exc_name, self.message)


def attempt(fn):
    """Call fn() and return its value, or a Raised marker."""
    try:
        return fn()
    except BaseException as exc:  # SystemExit from a library is a result too
        return Raised(exc)


# --------------------------------------------------------------------------
# instant conversion
# --------------------------------------------------------------------------

def _ticks_from_aware(d):
    secs = (d.astimezone(_dt.timezone.utc) - _UNIX_EPOCH_UTC).total_seconds()
    return int(round((secs + EPOCH_DELTA) * TICKS))


def ft_if_local(d):
    """Ticks on the reading that a naive value is local time."""
    try:
        if d.tzinfo is None:
            d = d.astimezone()  # attaches the local offset, per the stdlib
        return _ticks_from_aware(d)
    except BaseException:
        return None


def ft_if_utc(d):
    """Ticks on the reading that a naive value is UTC."""
    try:
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return _ticks_from_aware(d)
    except BaseException:
        return None


_STR_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S%z",
)


def _try_parse_datetime(s):
    """Recover a datetime from a parser that stringified one.

    Guarded against bare digit strings. `datetime.fromisoformat` accepts
    "20260525" as a date, so a version number or a tick count would
    otherwise be silently reinterpreted as a timestamp, which is the exact
    class of error this study is about.
    """
    s = s.strip()
    if not s or s.isdigit() or not any(c in s for c in "-:/T "):
        return None
    try:
                                              # handles most ISO-8601 spellings
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except BaseException:
        pass
    for fmt in _STR_FORMATS:
        try:
            return _dt.datetime.strptime(s, fmt)
        except BaseException:
            continue
    return None


# --------------------------------------------------------------------------
# description
# --------------------------------------------------------------------------

def describe(value):
    """Describe one returned value without interpreting it away."""
    d = {"repr": repr(value)[:400], "type": type(value).__name__}

    if isinstance(value, Raised):
        d["kind"] = "raised"
        d["exc"] = value.exc_name
        d["message"] = value.message[:400]

    elif value is None:
        d["kind"] = "none"

    elif isinstance(value, bool):
        d["kind"] = "bool"
        d["int"] = int(value)

    elif isinstance(value, int):
        d["kind"] = "int"
        d["int"] = value
        d["int_str"] = str(value)  # so a 64-bit value survives a non-Python reader

    elif isinstance(value, _dt.datetime):
        d["kind"] = "datetime"
        d["naive"] = value.tzinfo is None
        d["iso"] = value.isoformat()
        d["ft_if_local"] = ft_if_local(value)
        d["ft_if_utc"] = ft_if_utc(value)

    elif isinstance(value, _dt.date):
        d["kind"] = "date"
        d["iso"] = value.isoformat()

    elif isinstance(value, str):
        d["kind"] = "str"
        d["str"] = value[:400]
        parsed = _try_parse_datetime(value)
        if parsed is not None:
            d["parsed_from_str"] = True
            d["naive"] = parsed.tzinfo is None
            d["iso"] = parsed.isoformat()
            d["ft_if_local"] = ft_if_local(parsed)
            d["ft_if_utc"] = ft_if_utc(parsed)

    elif isinstance(value, (bytes, bytearray)):
        d["kind"] = "bytes"
        d["hex"] = bytes(value)[:64].hex()

    else:
        d["kind"] = "other"

    return d


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def _local_offset_seconds():
    try:
        off = _dt.datetime.now().astimezone().utcoffset()
        return int(off.total_seconds()) if off is not None else None
    except BaseException:
        return None


def run(adapter, parse):
    """Run one adapter over one file and print a single JSON line.

    parse(path) returns {field name: value}. Values may be Raised markers.
    If parse itself raises, that is a whole-file failure and is recorded as
    such, which is a different outcome from a per-field failure.
    """
    if len(sys.argv) < 2:
        sys.stderr.write("usage: %s <path.lnk>\n" % sys.argv[0])
        raise SystemExit(2)
    path = sys.argv[1]

    before = time.time()
    rec = {
        "adapter": adapter,
        "path": path,
        "case": os.path.splitext(os.path.basename(path))[0],
        "examined_at_unix": before,
        "examined_at_ft": int(round((before + EPOCH_DELTA) * TICKS)),
        "examined_at_iso": _dt.datetime.fromtimestamp(
            before, _dt.timezone.utc).isoformat(),
        "tz_env": os.environ.get("TZ"),
        "tz_name": list(time.tzname),
        "tz_offset_s": _local_offset_seconds(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }

    try:
        fields = parse(path)
        rec["ok"] = True
        rec["error"] = None
        rec["fields"] = {k: describe(v) for k, v in fields.items()}
    except BaseException as exc:
        rec["ok"] = False
        rec["error"] = "%s: %s" % (type(exc).__name__, exc)
        rec["traceback"] = traceback.format_exc()[-1500:]
        rec["fields"] = {}

    after = time.time()
    rec["returned_at_unix"] = after
    rec["elapsed_s"] = round(after - before, 6)

    sys.stdout.write(json.dumps(rec, default=str) + "\n")
