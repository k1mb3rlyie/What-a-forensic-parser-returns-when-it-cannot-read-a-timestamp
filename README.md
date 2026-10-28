# What a forensic parser returns when it cannot read a timestamp

Test corpus, harness, raw records and verification scripts for a study of how Windows Shortcut readers behave on timestamps they cannot decode.

## Finding

On Windows, `pylnk3` returns the time of examination in place of any timestamp it cannot decode: a value before 1 January 1970, a zero field denoting no recorded time, and a value too large to represent. The trigger is the stored value, not damage to the file. Every file in the corpus is well formed, the same files read correctly on Linux, and the operating system's own reader returned the correct value for every representable case on the same Windows machine.

Five readers were measured on Windows 11 and three of them on Linux under WSL2, each under two time-zone offsets, UTC and UTC+1.

## Reproduction

Requirements: Python 3.x, a Windows 11 host with WSL2 for the full grid, and the five readers (installed per-environment by `setup_envs.py`). Interpreter and reader versions are recorded by `claims.py`.

Full instructions are in [RUN.md](RUN.md). In short:

```
python setup_envs.py          # one virtual environment per reader
python make_cases.py          # regenerate and verify the corpus
python run_study.py --tag <name> --gap 60
python tabulate.py results/<file>.jsonl
```

`make_cases.py` prints the byte offsets it used. They must read `creation_time: 28`, `access_time: 36`, `write_time: 44`, `icon_index=0x38`. If they do not, stop: the corpus is wrong and nothing downstream means anything.

The generator is deterministic, so `cases/` is byte-identical on every platform and `make_cases.py` is a verification step rather than a dependency. The committed corpus is the one the reported figures were measured against, and `verify_corpus.py` confirms a clone still holds those exact bytes.

## Verifying figures

No figure in the paper is transcribed. Each script checks for a different thing:

| Script | Checks |
| --- | --- |
| `verify_corpus.py` | That the corpus is byte-for-byte the one the figures describe |
| `claims.py` | Environments, interpreter versions, reader source, release history |
| `vercheck.py` | Release history reconstructed from published PyPI artefacts |
| `check_paper.py` | Every figure in the manuscript against the raw records |
| `verify_checker.py` | That `check_paper.py` actually catches injected errors |

The last one exists because a validation step that quietly does nothing is the failure mode. It mutates a copy of the manuscript, one error per class, and reports which classes are caught rather than asserting that all are.

```
python verify_corpus.py
python claims.py results/*.jsonl --pypi
python check_paper.py <manuscript>
python verify_checker.py <manuscript> --checker check_paper.py
```

The manuscript is not in this repository while it is under submission, which is why `check_paper.py` takes it as an argument rather than finding it here. The scripts are the artefact; point them at the published paper.

On Windows, PowerShell does not expand `results/*.jsonl`; name the files or run these under WSL.

## Project layout

| Path | Contents |
| --- | --- |
| `cases/` | The corpus and `manifest.json`, the expected value of every field |
| `harness/`, `make_cases.py` | Generator, which writes each file from the MS-SHLLINK specification |
| `adapters/` | One per reader; each records what was returned without judging it |
| `run_study.py` | Runs the grid twice with a measured pause between passes |
| `tabulate.py` | Grades the records; collection and grading are deliberately separate |
| `results/` | Raw records from every run, including an archived earlier corpus |
| `predict_windows.py` | Demonstrates the Windows conversion path from a Linux host |
| `setup_envs.py` | Builds the environments on either platform |

Expected values are established from the format specification rather than from a reference implementation, because two parsers that share an assumption agree on the same wrong answer. The generator records the value written and the byte offset for every field, so the correct reading is known by construction. Collection and grading are separate programs: the adapters record what a reader returned, including its type and literal representation, and a second program decides what that meant. Grading rules can therefore be revised and reapplied to records already collected, and a defect in the rules cannot be concealed by the collection.

A returned value is classified as fabricated when it falls within five seconds of the moment of examination. Every case runs twice with a pause between passes: a fabricated value moves with the clock, a value read from the file does not. The second test needs no threshold, which is why both are reported.

## Licence

The code is under the MIT licence; see LICENSE. The corpus in `cases/` and the records in `results/` are under CC BY 4.0; see LICENSE-DATA. Splitting the two is the usual arrangement for a research artefact: it lets the code be reused without restriction while the data carries an attribution requirement.
