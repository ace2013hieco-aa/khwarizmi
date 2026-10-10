"""Opt-in fault-injection harness (AUDIT-P-AUTO-6 F1, R-4).

The P-AUTO-6 red legs lived only in ``%TEMP%`` mutation plugins: the method was
portable but not reproducible from the repository, so "envelope removed ->
these tests fail" was an oral tradition rather than part of the suite's
operating contract. This package commits the method: a CLOSED registry of
envelope seams that can be killed on demand (see ``kills.py``), plus the
refusals that keep it off unless explicitly asked for.

Nothing here patches anything unless ``HERMES_FAULT_KILL`` selects a kill.
"""
