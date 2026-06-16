"""
Module 6 — World-Model Decisioning Core (forward-looking judge).

Buildable-now, CPU-only layer per docs/WORLD_MODEL.md:
  - dataset.py     Phase 0 — labeled candidate dataset (the feedback-loop substrate)
  - competence.py  Phase C — calibrated directional competence + abstention
  - ev_head.py     Phase D₀ — gradient-boosted forward EV head, trained per-fold OOS

NOT in scope here: the JEPA encoder or latent world model (Phases A/B/D/E).

Hard invariants (CLAUDE.md §5): M6 may veto/shrink/abstain but NEVER bypasses the
M2 risk gate; no predicted value is ever written to ohlcv_* or fed to lenses as
data; promotion is earned on real OOS walk-forward only.
"""
