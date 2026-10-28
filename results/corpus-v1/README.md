# Corpus v1 runs

These runs used the first corpus, whose files carry no LinkTargetIDList. Without
one the Windows Shell API returns an empty path and zeroed times for every
file, so `a7_shellapi` measured nothing here (tabulate grades it
INSTRUMENT_FAULT).

Corpus v2 differs from v1 in exactly two ways, verified byte for byte: the
HasLinkTargetIDList bit in LinkFlags (header byte 0x14), and the 393-byte
IDList inserted after the header. Every other byte, including all three
FILETIMEs and IconIndex, is identical. The three byte-level parsers read the
header directly, so these records stay valid for them, and
`run_linux-lagos.jsonl` (a separate Linux 6.18 machine) serves as an
independent replication of the v2 WSL2 runs.

`manifest.json` here is the manifest the v1 corpus was generated with.
`excluded/` holds a run mislabelled `win-lecmd` that actually ran under WSL2
without LECmd.
