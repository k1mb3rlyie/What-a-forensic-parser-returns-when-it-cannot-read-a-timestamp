import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import attempt, run  # noqa: E402

# 0.2.1 ships its module as pylnk.py; the name pylnk3 arrives in 0.3.0. Each
# release has its own environment, so the fallback cannot pick up the
# unrelated PyPI package of the same name.
try:
    import pylnk3  # noqa: E402
except ImportError:
    import pylnk as pylnk3  # noqa: E402

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
