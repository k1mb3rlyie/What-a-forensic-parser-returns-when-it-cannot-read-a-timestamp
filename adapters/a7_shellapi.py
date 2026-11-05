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
