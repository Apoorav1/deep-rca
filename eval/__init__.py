"""Offline evaluation plane.

This package is the ONLY place allowed to touch benchmark ground truth
(label.json / injection.json / causal_graph.json and the ops-lite GT columns).

Nothing under ``src/deeprca`` may import this package. Enforced by
tests/isolation/test_import_ban.py.
"""
