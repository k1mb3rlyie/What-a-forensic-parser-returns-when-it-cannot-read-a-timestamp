"""Shared adapter serialisation. Record, never judge."""

import datetime as _dt
import json
import os
import sys
import time
import traceback

EPOCH_DELTA = 11_644_473_600  # seconds from 1601-01-01 to 1970-01-01
TICKS = 10_000_000            # 100-nanosecond intervals per second

_UNIX_EPOCH_UTC = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


class Raised:

    def __init__(self, exc):
        self.exc_name = type(exc).__name__
        self.message = str(exc)

    def __repr__(self):
        return "Raised(%s: %s)" % (self.exc_name, self.message)


def attempt(fn):
    try:
        return fn()
    except BaseException as exc:  # SystemExit from a library is a result too
        return Raised(exc)


def _ticks_from_aware(d):
    secs = (d.astimezone(_dt.timezone.utc) - _UNIX_EPOCH_UTC).total_seconds()
    return int(round((secs + EPOCH_DELTA) * TICKS))


def local_reading(d):
    if d.tzinfo is not None:
        try:
            return _ticks_from_aware(d), False
        except BaseException:
            return None, False

    approx = False
    try:
        offset = d.astimezone().utcoffset()
    except BaseException:
        offset = None
    if offset is None:
        try:
            offset = _dt.datetime.now().astimezone().utcoffset()
            approx = True
        except BaseException:
            return None, False
        if offset is None:
            return None, False
    try:
        return _ticks_from_aware(d.replace(tzinfo=_dt.timezone(offset))), approx
    except BaseException:
        return None, False


def ft_if_local(d):
    return local_reading(d)[0]


def ft_if_utc(d):
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


def describe(value):
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
        d["ft_if_local"], approx = local_reading(value)
        if approx:
            d["ft_if_local_approx"] = True
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


def _local_offset_seconds():
    try:
        off = _dt.datetime.now().astimezone().utcoffset()
        return int(off.total_seconds()) if off is not None else None
    except BaseException:
        return None


def run(adapter, parse):
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
