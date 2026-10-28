#!/usr/bin/env python3
"""Create one virtual environment per parser. Windows, WSL2, Linux or macOS.

This replaces setup.ps1 and setup.sh. A Python script is not subject to the
PowerShell execution policy, which refuses to run an unsigned .ps1 carrying the
internet-zone mark that arrives with any downloaded archive. Anyone reproducing
the study would hit that, so the setup path is the same file on every platform.

One environment per parser is not tidiness. The Python bindings to liblnk
install a module named `pylnk`, and so does the unrelated PyPI package of the
same name, so in a shared environment the two shadow each other and a result
cannot be attributed to a library.

Every environment is attempted independently. A parser that will not install
here is reported and skipped, and run_study.py records it as a skipped row with
its reason, so a missing row in the results is explained by the results rather
than by recollection.

Usage:
    python setup_envs.py
    python setup_envs.py --only a1_pylnk3 a3_lnkparse3
    python setup_envs.py --recreate
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENVS = os.path.join(HERE, "envs")

# (environment name, pinned requirement or None, platforms or None for any)
SPECS = [
    ("a1_pylnk3", "pylnk3==0.4.3", None),
    ("a3_lnkparse3", "LnkParse3==1.6.0", None),
    ("a5_liblnk", "liblnk-python==20260525", None),
    ("a7_shellapi", "pywin32", ("win32",)),
    ("a8_lecmd", None, None),
]


def venv_python(env_dir):
    for rel in ("bin/python", "bin/python3", "Scripts/python.exe"):
        cand = os.path.join(env_dir, *rel.split("/"))
        if os.path.exists(cand):
            return cand
    return None


def dist_name(requirement):
    for sep in ("==", ">=", "<=", "~=", ">", "<"):
        if sep in requirement:
            return requirement.split(sep)[0]
    return requirement


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def setup_one(name, requirement, recreate):
    env_dir = os.path.join(ENVS, name)
    print("-- %s" % name)

    if recreate and os.path.isdir(env_dir):
        shutil.rmtree(env_dir, ignore_errors=True)

    py = venv_python(env_dir)
    if py is None:
        code, out = run([sys.executable, "-m", "venv", env_dir])
        py = venv_python(env_dir)
        if py is None:
            print("   could not create the environment")
            for line in out.strip().splitlines()[-3:]:
                print("     " + line)
            return False

    if requirement is None:
        print("   ready: standard library only")
        return True

    code, out = run([py, "-m", "pip", "install", "--quiet",
                     "--disable-pip-version-check", requirement])
    # pip can report success for a package that did not land, so the install
    # is confirmed by asking the environment what it has rather than by
    # trusting the exit status alone.
    ok_import = run([py, "-m", "pip", "show", dist_name(requirement)])[0] == 0
    if code != 0 or not ok_import:
        print("   install failed: %s" % requirement)
        for line in out.strip().splitlines()[-3:]:
            print("     " + line)
        return False

    print("   ready: %s" % requirement)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--recreate", action="store_true",
                    help="delete and rebuild each environment")
    args = ap.parse_args()

    os.makedirs(ENVS, exist_ok=True)
    print("python: %s" % sys.version.split()[0])
    print("platform: %s" % sys.platform)
    print()

    ready, failed, skipped = [], [], []
    for name, requirement, platforms in SPECS:
        if args.only and name not in args.only:
            continue
        if platforms and sys.platform not in platforms:
            skipped.append(name)
            continue
        (ready if setup_one(name, requirement, args.recreate)
         else failed).append(name)

    print()
    print("ready:   %s" % (", ".join(ready) or "none"))
    if skipped:
        print("skipped: %s  (not applicable on %s)"
              % (", ".join(skipped), sys.platform))
    if failed:
        print("failed:  %s" % ", ".join(failed))
        print("A parser that will not install is a result, not a problem.")
        print("run_study.py records the reason in the run header.")

    exe = "python" if sys.platform == "win32" else "python3"
    sep = "\\" if sys.platform == "win32" else "/"
    tag = "win-lagos" if sys.platform == "win32" else "wsl-lagos"
    print()
    print("Next:")
    print("  %s make_cases.py" % exe)
    print("     must print  creation_time: 28, access_time: 36, "
          "write_time: 44  icon_index=0x38")
    print("  %s run_study.py --tag %s --gap 60" % (exe, tag))
    print("  %s tabulate.py results%srun_%s.jsonl" % (exe, sep, tag))

    return 1 if failed and not ready else 0


if __name__ == "__main__":
    sys.exit(main())
