# Predictions registered before the Windows runs

Written on 3 November 2026, after the Linux runs and before any Windows run
on the twenty-case corpus. Recorded here so that a wrong prediction is visible
rather than quietly dropped.

## pylnk3 on Windows

Its conversion uses the naive form of `fromtimestamp`, which fails below
t = 0. Fabrication is therefore predicted for every case whose stored value
decodes below the Unix epoch, plus the two unrepresentable values:

T1, T2, T3, T4, T6, T10, T12, T13, T14, T15, T16

That is 11 of 20 cases, so 66 of the 120 timestamp observations in a Windows
run, a rate of 55.0%. On the thirteen-case corpus the rate was 38.5%; the
rise is an artefact of adding pre-1970 cases, not a change in behaviour, and
must be reported as such.

T5, T7, T8, T9, T11 and the three icon cases are at or above the epoch and
are predicted correct.

## Dissect on Windows

`dissect.util.ts.wintimestamp` uses the **aware** form, whose Windows
boundary is t = -43200 rather than t = 0, and the lnk plugin wraps it in no
exception handler. Predicted:

- T12 (t = -43200 exactly): succeeds
- T13 (t = -43201): raises, one second away from T12
- T3, T15, T16: raise, being far below the boundary
- T4 (t = -1) and T10 (one tick below the epoch): succeed, being above it
- T2 and T14: raise, as they already do on Linux

If T12 succeeds and T13 raises, the aware boundary is established end to end
at one-second resolution, and the two boundaries are shown to differ by
exactly twelve hours. If both raise, or both succeed, the analytic account of
the aware boundary is wrong and the paper must say so.

Dissect is predicted never to fabricate, because it has no handler to
substitute a value. A loud failure where pylnk3 is silent, in the same
conversion, on the same input, is the cleanest statement of the paper's
argument available.

## liblnk and LnkParse3

Predicted unchanged from the thirteen-case runs: liblnk correct with raw
ticks throughout and loud on the unrepresentable values, LnkParse3 absent for
zero and signed-max and garbage-as-1601 for unsigned-max.
