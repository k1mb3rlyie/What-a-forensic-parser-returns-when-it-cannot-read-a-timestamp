import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import attempt, run  # noqa: E402

from dissect.shellitem.lnk import Lnk  # noqa: E402
from dissect.util import ts  # noqa: E402

ADAPTER = "a9_dissect"


def parse(path):
    # dissect.target's windows/lnk plugin reads the header through this class
    # and converts with ts.wintimestamp; it reports them as target_*time.
    with open(path, "rb") as fh:
        lnk = Lnk(fh)
        h = lnk.link_header
        return {
            "creation_time": attempt(lambda: ts.wintimestamp(h.creation_time)),
            "access_time": attempt(lambda: ts.wintimestamp(h.access_time)),
            "write_time": attempt(lambda: ts.wintimestamp(h.write_time)),
            "icon_index": attempt(lambda: h.icon_index),
        }


if __name__ == "__main__":
    run(ADAPTER, parse)
