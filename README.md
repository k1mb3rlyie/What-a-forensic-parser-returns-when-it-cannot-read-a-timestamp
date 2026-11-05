# What a forensic parser returns when it cannot read a timestamp

Test corpus, harness, raw records and verification scripts for a study of how
Windows Shortcut readers behave on timestamps they cannot decode.

Five readers were measured on Windows 11, three of them also on Linux under
WSL2, across four time-zone offsets from −4:00 to +5:30. Six runs, 1,716 graded
observations.

On Windows, `pylnk3` returns the time of examination in place of a timestamp
before 1 January 1970, a zero field denoting no recorded time, and a value too
large to represent. The trigger is the stored value, not damage: every file in
the corpus is well formed. On Linux the same library reads the same files
correctly and raises an error on the value it cannot represent, so the same
input that fails loudly on one platform is answered with the clock on the
other. On the same Windows machine the operating system's own reader returned
the correct value for every representable case.

## Reproducing the measurements

Each run covers the readers installed in the environment it is run from, so
the full grid is one run in Windows PowerShell and one per offset in WSL. Set
the offset before the run; `run_study.py` records the effective offset but
does not set it.

```
python setup_envs.py                          # one virtual environment per reader
python make_cases.py                          # regenerate and verify the corpus
python run_study.py --tag win-lagos --gap 60  # --gap is the pause between passes
python tabulate.py results/*.jsonl            # all runs together
```

On Linux, set the offset with `TZ`:

```
TZ=Africa/Lagos    python3 run_study.py --tag wsl-lagos   --gap 60
TZ=UTC             python3 run_study.py --tag wsl-utc     --gap 60
TZ=America/New_York python3 run_study.py --tag wsl-newyork --gap 60
TZ=Asia/Kolkata    python3 run_study.py --tag wsl-kolkata --gap 60
```

`run_study.py` refuses to overwrite an existing results file; use a new tag or
`--force`. On Windows the operating system time zone must be changed in
Settings, because `TZ` alone does not affect the Windows API readers.

`make_cases.py` prints the byte offsets it used. They must read
`creation_time: 28, access_time: 36, write_time: 44, icon_index=0x38`. If they
do not, stop: the corpus is wrong and nothing downstream means anything.

The generator is deterministic, so `cases/` is byte-identical on every platform
and `make_cases.py` is a verification step rather than a dependency. The
committed corpus is the one the reported figures were measured against, and
`verify_corpus.py` confirms a clone still holds those exact bytes.

## Checking the reported figures

Every figure in the paper is recomputed from the records in `results/`. To
check one, recompute it:

```
python verify_corpus.py            # the corpus is the one the figures describe
python tabulate.py results/*.jsonl # every table and total, from the records
python vercheck.py                 # release history, from PyPI
```

`tabulate.py` prints the outcome grid, the fabrication list, the drift between
passes and the per-reader totals. Those are the paper's tables. Nothing is
copied between the two by hand.

A second program recomputes the headline figures without sharing any of that
grading code, so a defect in `tabulate.py` cannot quietly reproduce itself:

```
python recheck.py cases/manifest.json \
    results/run_w2-lagos.jsonl results/run_w2-utc.jsonl \
    results/run_l2-lagos.jsonl results/run_l2-utc.jsonl \
    results/run_l2-newyork.jsonl results/run_l2-kolkata.jsonl
```

It reports the observation count, the fabricated cases, the number graded
correct and how close any of them comes to the one-second tolerance, the
naive-reading split, and the two-pass drift against the measured interval.


On Windows, PowerShell does not expand `results/*.jsonl`; name the files or run
these under WSL.

## Layout

| Path | Contents |
|---|---|
| `cases/` | The corpus and `manifest.json`, the expected value of every field |
| `harness/`, `make_cases.py` | Generator, which writes each file from the MS-SHLLINK specification |
| `adapters/` | One per reader; each records what was returned without judging it |
| `run_study.py` | Runs the grid twice with a measured pause between passes |
| `tabulate.py` | Grades the records; collection and grading are deliberately separate |
| `results/` | Raw records, one file per run: six main runs and three release runs |
| `predict_windows.py` | Demonstrates the Windows conversion path from a Linux host |
| `setup_envs.py` | Builds the environments on either platform |
| `verify_corpus.py`, `SHA256SUMS` | Confirms a clone holds the corpus as measured |
| `vercheck.py`, `release_data.json` | Release history as published on PyPI |
| `recheck.py` | Recomputes the reported figures without `tabulate.py`'s grading code |
| `RELEASE_ARTEFACTS.json` | SHA-256 of every pinned distribution artefact, from PyPI |

## Method in one paragraph

Expected values are established from the format specification rather than from
a reference implementation, because two parsers that share an assumption agree
on the same wrong answer. The generator records the value written and the byte
offset for every field, so the correct reading is known by construction.
Collection and grading are separate programs: the adapters record what a reader
returned, including its type and literal representation, and a second program
decides what that meant. Grading rules can therefore be revised and reapplied
to records already collected, and a defect in the rules cannot be concealed by
the collection.

A returned value is classified as fabricated when it falls within five seconds
of the moment of examination. Every case runs twice with a pause between
passes: a fabricated value moves with the clock, a value read from the file
does not. The second test needs no threshold, which is why both are reported.

## Citation

`[TODO]` once the paper has a venue and identifier.

## Licence

The code is under the MIT licence; see [LICENSE](LICENSE). The corpus in
`cases/` and the records in `results/` are under CC BY 4.0; see
[LICENSE-DATA](LICENSE-DATA). Splitting the two is the usual arrangement for a
research artefact: it lets the code be reused without restriction while the
data carries an attribution requirement.
