# Advisor decision sheet

| Decision | Options | Added runs | Maximum wall time | Permitted claim | Forbidden claim | Failure treatment |
|---|---|---:|---:|---|---|---|
| Conference primary result | Small oracle / RAIN stability | 3 / 4 | 12 h / 8 h | bounded subset reference distance / four-profile stability | 264-trip approximation guarantee / global search completeness | report blocked or negative result |
| RAIN practical-equivalence threshold | approve a percent, e.g. 0.1%, or reject | 0 | 0 | preregistered within-profile equivalence | post-hoc threshold | no binary verdict |
| Oracle scope | RAIN 8/12/24 / add SUNNY 8/12/24 | 3 / 6 | 12 h / 24 h | selected scenarios only | weather generalization | retain completed cases, mark interruption |
| Stage 1 gap | disclose and use / require 1% | 0 / unbounded | declared cap only | physically valid time-limit incumbent / accepted <=1% result | optimality when target missed | label diagnostic or stop |

Advisor records these decisions only in the two approval JSON files. Null fields never authorize execution.
