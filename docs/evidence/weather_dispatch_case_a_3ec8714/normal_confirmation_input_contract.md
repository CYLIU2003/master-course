# Fresh normal-path input contract

Status: **PASS_FULL_INPUT_CONTRACT**. Every comparable hash matches the frozen A baseline within each scenario.

SUNNY/RAIN differ only in scenario-specific prepared snapshots, the authoritative PV profile, and the canonical contract hash derived from that PV input.

| scenario | prepared input | prepared SHA-256 | frozen-A drift |
|---|---|---|---:|
| SUNNY | prepared-1f1b85053b8c9ea1-453c50ff177c277b-8acc7b3a | 99e49dd72e73d6e2e8c546d71573d3b00a7f00d23ab748da7171e1dd4b6bf05d | 0 |
| RAIN | prepared-a6c5e0a8cdd9b32b-f1e18f252e336f1f-8acc7b3a | 8220f7208b7add87beeb3a30c5d8f727480423427fff5e2f5eca1ed4a8e0ed3f | 0 |
