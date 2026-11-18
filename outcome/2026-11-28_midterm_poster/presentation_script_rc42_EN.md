# Midterm poster talk — English script, rc42 results (2026-11-28)

**Posters** (built by `build_poster_rc42.js`)

| Variant | File | What it shows |
|---|---|---|
| a | `midterm_poster_A0_rc42_a_en.pptx` | Tariff A (17.43 JPY/kWh + basic charge) in the figures; B compared in Section 5 |
| b | `midterm_poster_A0_rc42_b_en.pptx` | Tariff B (30 JPY/kWh incl. basic charge) in the figures; A compared in Section 5 |
| c | `midterm_poster_A0_rc42_c_en.pptx` | A and B side by side |

**How to use this script**
- The variant will be chosen with the supervisor. In Sections 4 and 5, read only the parts for that variant.
- About 8–10 minutes.
- **[Point: …]** says what to point at on the poster.
- Every cost leaves out the CO₂ cost. Costs under tariff A include the weekly basic charge.
- All numbers are DIAGNOSTIC: rc42 (19dc0780), 48 runs, all verified.

---

## 0. Opening — 30 s

Good morning. My name is Liu, a first-year master's student. My research is on **trip assignment and charging optimization for electric buses that run alongside diesel buses**, toward green transformation, or GX.

My question is this. A bus company is switching to electric buses. Which bus should run which trip? When should each electric bus charge? And can it do this without a bigger grid connection?

---

## 1. Background and aim — 1 min

**[Point: Section 1]**

Japan aims to reach carbon neutrality by 2050. Transport produces 19.3 percent of Japan's CO₂, so electric buses matter.

A bus company cannot replace its whole fleet at once. For many years, electric and diesel buses will run together.

Electric buses charge at the depot. If many buses charge at the same time, the depot draws a lot of power from the grid.

**[Point: "Aim"]**

So my aim is to cut CO₂ by electrification while keeping today's timetable and limiting the grid power.

---

## 2. Method — 1 min 30 s

**[Point: "Decisions"]**

The model makes two decisions:
- which bus, electric or diesel, runs each trip;
- when, and at how many kilowatts, each electric bus charges.

Every timetabled trip is run.

**[Point: objective]**

The objective is the total cost of one week: vehicle use, electricity, diesel, a penalty for power above the grid limit, and a small CO₂ cost. The CO₂ cost only steers the plan. It is not in any cost I report.

**[Point: Fig. 1]**

The calculation has four steps:
1. Trips are assigned to buses.
2. A day-ahead plan sets charging every 15 minutes.
3. Every hour, the plan is redone with the actual sunshine.
4. Cost and CO₂ are counted from what was actually run.

**[Point: Table 1, electricity row]**

I used two electricity tariffs:
- **Tariff A**: 17.43 yen per kilowatt-hour, plus a basic charge. The basic charge grows with the grid limit.
- **Tariff B**: a flat 30 yen per kilowatt-hour that includes the basic charge.

---

## 3. Case study — 30 s

**[Point: Fig. 2 and Table 2]**

The case is Tokyu Bus routes Shibu 21 to 23, from the Tsurumaki depot, with 1,704 trips a week.
- The fleet has 35 electric and 25 diesel buses.
- The depot has ten 90 kW chargers, 1,000 kW of PV and a 6,000 kWh battery.
- I tried four grid limits, 90, 200, 400 and 900 kW, in a winter, a spring and a summer week. That gives 12 cases.

---

## 4. Results — 2 min (read your variant only)

### Variant a (tariff A)

**[Point: Fig. 3]**
In 11 of the 12 cases, electric buses ran 93 to 97.5 percent of the trips.

**[Point: Fig. 4, the star]**
The exception is 90 kW in winter. There, using more diesel buses was cheaper, and electric buses ran only 22 percent of trips. Weekly totals range from about 4.20 to 4.57 million yen.

### Variant b (tariff B)

**[Point: Fig. 3]**
In 10 of the 12 cases, electric buses ran 92 to 96 percent of the trips.

**[Point: Fig. 4, the stars]**
The exceptions are 90 and 200 kW in winter. There, using more diesel buses was cheaper, and electric buses ran 27 to 31 percent of trips. Weekly totals range from about 4.13 to 4.41 million yen.

### Variant c (both)

**[Point: Fig. 3, A and B bars]**
Under both tariffs, electric buses ran 92 to 97.5 percent of the trips in most cases.

**[Point: Fig. 4, the stars]**
The diesel-first solution was adopted at 90 kW in winter under A, and at 90 and 200 kW in winter under B. There, electric buses ran 22 to 31 percent of trips.

### All variants

**[Point: "Two initial assignments"]**

This is the key idea. The assignment problem is too large to prove optimal in the time available, and the search tends to stay near its starting point. So I solve each case twice:
- once from an electric-first start;
- once from a diesel-first start.

I keep the cheaper result.

**[Point: Fig. 5]**

The electric-first solution emitted less CO₂ in every case. It was also cheaper in most cases: 11 under A, 10 under B.

---

## 5. Discussion and outlook — 1 min 30 s

**[Point: Section 5, first bullet]**

With enough grid headroom, electrification lowers both cost and CO₂.

At 90 kW in winter, the diesel-heavy solution saved money: about 560 thousand yen a week under A, or about 380 thousand under B. But it emitted over three times the CO₂.

**[Point: second bullet]**

The two tariffs disagree in only one case: 200 kW in winter. There, the two solutions differ by 57 thousand yen a week under A and 16 thousand under B. Both differences are well inside the 5 percent gap of about 220 thousand yen. So I cannot say which one is truly cheaper.

**[Point: third bullet]**

How the basic charge is counted matters.
- Under A, 900 kW costs about 244 thousand yen a week more than 400 kW. That is almost exactly the difference in basic charge.
- Under B, the difference is only about 11 thousand yen.

**[Point: Fig. 6]**

Next steps:
- **March 2027**: I present this work at the IEEJ National Convention.
- **During fiscal 2027**: multi-day planning and battery optimization.
- **February 2028, master's final**: guidance on choosing the grid limit, the battery and the chargers.

Thank you.

---

## If asked — say honestly

- All numbers are diagnostic and not yet used for research conclusions.
- The assignment is not proven optimal. Because trips and charging are solved in two stages, the result is not a global optimum either.
- The battery follows a fixed rule. It is not optimized.
- Some hourly re-plans timed out: at most 44 of 174–175 under A, and 39 under B.
- Three summer electric-first runs hit the 14 GiB memory limit the first time: A at 200 kW, and B at 90 and 900 kW. Each was rerun once at 24 GiB.
- The excess price of 500 yen per kWh and the grid CO₂ factor of 0.5 kg per kWh are tentative.
