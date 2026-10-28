"""Generate the .lnk test corpus and a manifest of expected values.

Every file is written from the MS-SHLLINK specification by lnkbuild.py, so the
correct reading of every field is known by construction and owes nothing to any
parser under test.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harness.lnkbuild import LnkSpec, build, to_filetime   # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "cases"
TS_FIELDS = ("creation_time", "access_time", "write_time")
EPOCH = _dt.datetime(1601, 1, 1, tzinfo=_dt.timezone.utc)


def ft(d: _dt.datetime) -> int:
    return to_filetime(d)


# (id, filetime value or None for "leave as built", what it represents, expectation)
TIMESTAMP_CASES = [
    ("T0", None,
     "ordinary modern timestamps, three distinct values",
     "return each field's own value"),
    ("T1", 0,
     "unset, not recorded",
     "report absent, or the 1601 epoch; never a current date"),
    ("T2", 0xFFFFFFFFFFFFFFFF,
     "beyond the representable range (year 60056)",
     "signal an error"),
    ("T3", ft(_dt.datetime(1950, 6, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)),
     "a valid, legitimate pre-epoch date",
     "return 1950-06-01 12:00:00Z"),
    ("T4", ft(_dt.datetime(1969, 12, 31, 23, 59, 59, tzinfo=_dt.timezone.utc)),
     "one second before the Unix epoch",
     "return 1969-12-31 23:59:59Z"),
    ("T5", ft(_dt.datetime(1971, 1, 1, 0, 0, 1, tzinfo=_dt.timezone.utc)),
     "a year after the Unix epoch",
     "return 1971-01-01 00:00:01Z"),
    ("T6", 1,
     "one tick past the FILETIME epoch",
     "return the 1601 epoch, distinguishable from T1"),

    # T4, T7, T8, T9 and T5 form a ladder across the Unix epoch: one second
    # before, exactly on it, one second after, one day after, one year after.
    # A conversion that routes negative values through a different path shows
    # up as a verdict that changes between two cases one second apart, and the
    # wider rungs show whether the boundary sits at the epoch itself or moves
    # with the local offset.
    ("T7", ft(_dt.datetime(1970, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)),
     "the Unix epoch exactly",
     "return 1970-01-01 00:00:00Z"),
    ("T8", ft(_dt.datetime(1970, 1, 1, 0, 0, 1, tzinfo=_dt.timezone.utc)),
     "one second after the Unix epoch",
     "return 1970-01-01 00:00:01Z"),
    ("T9", ft(_dt.datetime(1970, 1, 2, 0, 0, 0, tzinfo=_dt.timezone.utc)),
     "one day after the Unix epoch, clear of any local offset",
     "return 1970-01-02 00:00:00Z"),
]

ICON_CASES = [("I0", 0), ("I1", -1), ("I2", -7)]

# LinkTargetIDList for C:\Users\analyst\Documents\q3.docx, a path present on no
# test machine. The Windows Shell API reports the header timestamps only for a
# link that carries an IDList; without one, GetPath returns an empty path and
# zeroed times for every file, which measures nothing.
#
# MS-SHLLINK leaves the item contents to the shell, so these bytes were taken
# from Windows itself: IShellLink.SetPath on that absent path, saved, and read
# back (Windows 11 26300, 24 October 2026). Every DOS date in the file-entry
# items is zero, so the header remains the only source of a timestamp. The
# bytes are fixed here so that the corpus is identical on every platform.
TARGET_IDLIST = bytes.fromhex(
    "14001f50e04fd020ea3a6910a2d808002b30309d19002f433a5c00000000000000000000"
    "00000000000000000050003100000000000000000010005573657273003c0009000400ef"
    "be00000000000000002e0000000000000000000000000000000000000000000000000000"
    "00000055007300650072007300000014005600310000000000000000001000616e616c79"
    "737400400009000400efbe00000000000000002e00000000000000000000000000000000"
    "0000000000000000000000000061006e0061006c00790073007400000016005c00310000"
    "000000000000001000446f63756d656e747300440009000400efbe00000000000000002e"
    "000000000000000000000000000000000000000000000000000000000044006f00630075"
    "006d0065006e007400730000001800560032000000000000000000000071332e646f6378"
    "00400009000400efbe00000000000000002e000000000000000000000000000000000000"
    "0000000000000000000000710033002e0064006f0063007800000016000000"
)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    manifest = {"generated": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "cases": {}}

    base_spec = LnkSpec(sample_id="base", id_list=TARGET_IDLIST)
    base_data, gt = build(base_spec)

    offsets = {n: gt.by_name(n).offset for n in TS_FIELDS}
    icon_off = gt.by_name("icon_index").offset
    print(f"offsets: {offsets}  icon_index=0x{icon_off:02x}")

    for cid, value, represents, expectation in TIMESTAMP_CASES:
        b = bytearray(base_data)
        expected = {}
        for name in TS_FIELDS:
            if value is None:
                v = to_filetime(getattr(base_spec, name))
            else:
                v = value
                struct.pack_into("<Q", b, offsets[name], v)
            try:
                decoded = (EPOCH + _dt.timedelta(microseconds=v // 10)
                           ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                decoded = None
            expected[name] = {"filetime": v, "decoded_utc": decoded,
                              "unix": v / 10_000_000 - 11_644_473_600}
        path = OUT / f"{cid}.lnk"
        path.write_bytes(bytes(b))
        manifest["cases"][cid] = {
            "file": path.name, "kind": "timestamp", "represents": represents,
            "expectation": expectation, "expected_fields": expected,
            "icon_index": base_spec.icon_index,
        }
        print(f"  {cid}  {path.name:<10} {represents}")

    # The icon cases keep the base timestamps untouched, so they also serve as
    # replicates of T0. Recording their expected timestamps costs nothing and
    # means no file in the corpus goes ungraded on any field.
    base_expected = {}
    for name in TS_FIELDS:
        v = to_filetime(getattr(base_spec, name))
        base_expected[name] = {
            "filetime": v,
            "decoded_utc": (EPOCH + _dt.timedelta(microseconds=v // 10)
                            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unix": v / 10_000_000 - 11_644_473_600,
        }

    for cid, iv in ICON_CASES:
        b = bytearray(base_data)
        struct.pack_into("<i", b, icon_off, iv)
        path = OUT / f"{cid}.lnk"
        path.write_bytes(bytes(b))
        manifest["cases"][cid] = {
            "file": path.name, "kind": "icon_index",
            "represents": f"IconIndex = {iv} (signed 32-bit per MS-SHLLINK)",
            "expectation": f"return {iv}",
            "expected_icon_index": iv,
            "misread_if_unsigned": struct.unpack("<I", struct.pack("<i", iv))[0],
            "expected_fields": base_expected,
        }
        print(f"  {cid}  {path.name:<10} IconIndex = {iv}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n{len(manifest['cases'])} cases written to {OUT}")


if __name__ == "__main__":
    main()
