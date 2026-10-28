"""Adapter: liblnk (libyal, C) through its Python binding.

The binding installs a module named `pylnk`, which collides with the
unrelated PyPI package of the same name. That is why each parser gets its
own virtual environment: in a shared one the two shadow each other and a
result cannot be attributed to a library.

This binding is the only one of the set that exposes raw FILETIME ticks
alongside the converted value, so both are recorded. Where they disagree,
the conversion is the defect rather than the read.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import attempt, run  # noqa: E402

import pylnk as liblnk  # noqa: E402

ADAPTER = "a5_liblnk"

_FIELDS = (
    ("creation_time", "get_file_creation_time"),
    ("access_time", "get_file_access_time"),
    ("write_time", "get_file_modification_time"),
)


def parse(path):
    handle = liblnk.file()
    handle.open(path)
    try:
        out = {"_liblnk_version": attempt(lambda: liblnk.get_version())}
        for name, method in _FIELDS:
            out[name] = attempt(lambda m=method: getattr(handle, m)())
            out[name + "_raw"] = attempt(
                lambda m=method: getattr(handle, m + "_as_integer")())
        out["icon_index"] = attempt(lambda: handle.get_icon_index())
        return out
    finally:
        try:
            handle.close()
        except BaseException:
            pass


if __name__ == "__main__":
    run(ADAPTER, parse)
