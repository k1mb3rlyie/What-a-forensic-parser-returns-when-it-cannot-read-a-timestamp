"""Adapter: the Windows Shell API, through IShellLink (pywin32).

This is the operating system's own reader for its own format, so it is the
reference against which the third-party parsers are compared rather than
just another row.

One caveat has to be stated plainly, because it affects how the row should be
read. IShellLink is a resolver, not a file parser: given a link it may consult
the live filesystem and the distributed link tracking service to find the
target, and GetPath can therefore return information about the file as it is
now instead of as the link recorded it. SLGP_RAWPATH asks for the stored path
without resolution, and the test corpus points at a path that does not exist
on any test machine, so the API has nothing live to resolve against. Whatever
it returns is therefore either the stored data or a failure, and both are
informative. What this row cannot support is a claim that the API was read
with the same semantics as a byte-level parser.

Windows only. The runner skips it elsewhere.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Raised, attempt, run  # noqa: E402

ADAPTER = "a7_shellapi"


def _load(path):
    import pythoncom
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None,
        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.QueryInterface(pythoncom.IID_IPersistFile).Load(
        os.path.abspath(path), 0)
    return link, shell


def parse(path):
    link, shell = _load(path)

    # GetPath returns (path, WIN32_FIND_DATA). The find-data tuple carries the
    # three FILETIMEs at positions 1, 2 and 3, as datetime objects in current
    # pywin32 and PyTime in older builds. Both are recorded as they arrive.
    got = attempt(lambda: link.GetPath(shell.SLGP_RAWPATH))

    def nth(i):
        if isinstance(got, Raised):
            return got
        try:
            find_data = got[1]
            if find_data is None:
                return None
            return find_data[i]
        except BaseException as exc:
            return Raised(exc)

    out = {
        "creation_time": nth(1),
        "access_time": nth(2),
        "write_time": nth(3),
        "icon_index": attempt(lambda: link.GetIconLocation()[1]),
    }

    # Recorded so a reader can tell a resolution failure from a parse failure.
    out["_stored_path"] = (got if isinstance(got, Raised)
                           else attempt(lambda: got[0]))
    return out


if __name__ == "__main__":
    run(ADAPTER, parse)
