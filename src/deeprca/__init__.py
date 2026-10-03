"""Deep-RCA: autonomous, hypothesis-driven root-cause investigation.

HARD RULE: nothing in this package (``deeprca``) may import from ``eval`` or
``eval.ground_truth``. Ground truth is reachable only by the offline evaluation
plane. This is enforced by tests/isolation/test_import_ban.py.
"""

__version__ = "0.1.0"
