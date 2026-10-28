"""Adapter: pylnk3 (https://github.com/strayge/pylnk), pure Python."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import attempt, run  # noqa: E402

import pylnk3  # noqa: E402

ADAPTER = "a1_pylnk3"


def parse(path):
    lnk = pylnk3.parse(path)
    return {
        "creation_time": attempt(lambda: lnk.creation_time),
        "access_time": attempt(lambda: lnk.access_time),
        "write_time": attempt(lambda: lnk.modification_time),
        "icon_index": attempt(lambda: lnk.icon_index),
    }


if __name__ == "__main__":
    run(ADAPTER, parse)
