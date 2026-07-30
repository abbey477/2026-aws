# Reconciliation Mismatches: Root Cause Summary

Two false-positive mismatch patterns found between Table A (GoldenGate replication from Sybase) and Table B (custom Java write process). Both are precision-loss bugs upstream of the database — not data corruption or replication issues.

## Issue 1: Floating-Point Mismatches

**Symptom:** Values matched to ~7 digits then diverged (e.g. `149.80506` vs `149.805054`).

**Cause:** Sybase source type is `float` (binary-approximate, ~15-17 digit precision). Both Oracle tables use `FLOAT(126)` — plenty wide. But Table B's Java code read the value as `Float` (32-bit, ~7 digits), truncating it in memory before the wide Oracle column ever saw it.

**Fix:** Change Java from `Float` to `Double` (`getDouble()` instead of `getFloat()`). `Double` matches the source precision exactly — `BigDecimal` isn't needed since the source itself isn't an exact decimal type.

## Issue 2: Datetime Millisecond Mismatches

**Symptom:** Millisecond values appeared mismatched between systems.

**Cause:** Sybase `datetime` only has ~3.33ms resolution (ticks of 1/300 sec), so values like `.903` are real, not rounding noise. Mismatches came from the Oracle column being `DATE` (drops fractional seconds entirely) instead of `TIMESTAMP(3)`, or from string-based transfer/export steps truncating the value before comparison.

**Fix:** Use `TIMESTAMP(3)` in Oracle (never `DATE`) → `LocalDateTime` in Java. Compare full-precision values column-to-column rather than hardcoded string literals.

## Common Thread

Neither issue was a database problem — the target columns were always wide enough. Precision was lost upstream, in the Java type used to hold the value before insert. Fix is a type change, not a redesign.
