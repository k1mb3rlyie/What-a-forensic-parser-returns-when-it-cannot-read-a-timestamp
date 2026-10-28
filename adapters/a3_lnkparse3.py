"""Adapter: LnkParse3 (https://github.com/Matmaus/LnkParse3), pure Python."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import attempt, run  # noqa: E402

import LnkParse3  # noqa: E402

ADAPTER = "a3_lnkparse3"


def parse(path):
    with open(path, "rb") as fh:
        lnk = LnkParse3.lnk_file(fh)
        # get_json() walks the whole file, so it may raise on a damaged one.
        # That is a whole-file failure and is allowed to propagate.
        doc = lnk.get_json()
    header = doc.get("header", {}) if isinstance(doc, dict) else {}
    return {
        "creation_time": attempt(lambda: header.get("creation_time")),
        "access_time": attempt(lambda: header.get("accessed_time")),
        "write_time": attempt(lambda: header.get("modified_time")),
        "icon_index": attempt(lambda: header.get("icon_index")),
    }


if __name__ == "__main__":
    run(ADAPTER, parse)
