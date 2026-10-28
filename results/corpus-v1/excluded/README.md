# Excluded runs

`run_win-lecmd.jsonl` was meant to be the Windows LECmd run. Its own header
records that it ran under WSL2 Linux (`Linux-5.15.167.4-microsoft-standard`)
with LECmd not found, so it contains no LECmd data and duplicates `wsl-lagos`.
It is kept here, outside `results/*.jsonl`, so it cannot enter the tables.
