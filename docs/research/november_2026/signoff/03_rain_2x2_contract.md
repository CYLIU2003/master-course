# RAIN 2x2 contract

v3 crosses candidate range with the shared Phase 3 day-ahead budget. BASE and RANGE_ONLY use 585/435/30 seconds; BUDGET_ONLY and FULL_EXPANDED use 1650/1500/30. Range vectors are 22/radius4/BEV15--35 and 44/radius8/BEV5--35. Rolling uses 30 seconds per step and external wall timeout is separate.

Every profile must be ACCEPTED and retained even when REJECTED or INTERRUPTED. Candidate-set Jaccard, retention, winner presence, union, and stability use verified physical `assignment_hash`, never `candidate_hash`. A binary stability verdict is forbidden unless every evaluated row has complete candidate-level formal evidence and the threshold was signed before execution.
