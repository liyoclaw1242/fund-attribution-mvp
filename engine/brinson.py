"""Brinson-Fachler attribution engine.

Supports two modes:
  BF2 (default): 2-effect — interaction merged into selection
    Allocation: (Wp,i - Wb,i) * (Rb,i - Rb)
    Selection:  Wp,i * (Rp,i - Rb,i)

  BF3: 3-effect — standard Brinson-Fachler (1985)
    Allocation:  (Wp,i - Wb,i) * (Rb,i - Rb)
    Selection:   Wb,i * (Rp,i - Rb,i)
    Interaction: (Wp,i - Wb,i) * (Rp,i - Rb,i)

Cash: separate industry, return=0%, benchmark weight=0%.
Assertion: effects must sum to excess return (tolerance < 1e-10).
"""

# TODO: Implement — see Issue #6

raise NotImplementedError("See GitHub Issue")
