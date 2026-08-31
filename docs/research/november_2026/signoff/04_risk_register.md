# Risk register

| Risk | Detection | Stop rule |
|---|---|---|
| candidate evidence missing | normalized candidate blockers | block binary stability |
| requested/effective drift | effective_controls.json | reject profile |
| Prepared/fixed-input/SHA drift | identity and hash comparison | interrupt family |
| duplicate/missing trip | 264 unique-trip audit | reject candidate |
| fallback, repair, or proxy | explicit candidate/run gates | reject candidate/profile |
| exact-oracle gate failure | exact eligibility fields | omit distance |
| dirty worktree | before/after process Git check | interrupt |
| time or disk budget exceeded | signed family budget | stop safely and retain checkpoint |
