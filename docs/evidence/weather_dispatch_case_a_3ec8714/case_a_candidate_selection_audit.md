# Case A candidate-generation and selection audit

Verdict: **FIXED**. The previous normal path evaluated one candidate; the fixed policy evaluates the neutral 22-candidate composition/frontier coverage. No weather bias was added.

| scenario | candidates | proxy/canonical reversals | winner | second-place delta JPY | six checks |
|---|---:|---:|---|---:|---|
| SUNNY | 22 | 0 | 76fb6a9b635b | 5180.298562 | PASS |
| RAIN | 22 | 0 | 213b2ccd4095 | 566.622470 | PASS |
