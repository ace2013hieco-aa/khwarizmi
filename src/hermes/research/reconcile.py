"""Reconciliation loop (v3 §8) — the driver around the task graph.

The loop observes, diffs, plans, dispatches, validates, commits, requeues.
It never invents workflow, bypasses the graph, or mutates state directly.
Implemented as Controller.tick() (controller.py); this module is
intentionally empty (pointer only, no behavior)."""
