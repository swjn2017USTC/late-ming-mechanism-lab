"""The frozen validation protocol: outcomes, windows, thresholds and model comparison.

``schema`` defines and loads the protocol; ``freeze`` gives it an identity and refuses anything
scored under another one; ``thresholds`` samples the reading lines; ``robustness`` reports how a
verdict moves with them; ``outcomes`` computes the primary vector from a run; ``comparison`` holds
the pre-registered alternative structures.
"""
