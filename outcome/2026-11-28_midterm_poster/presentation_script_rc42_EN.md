# Midterm poster talk: English script (2026-11-28)

Poster: `midterm_poster_A0_rc42_a_en.pptx`. This is variant a, tariff A only, revised after Prof. Urabe's reply of 19 November.

- **Length.** About 1,100 words, or 8–9 minutes at a calm pace. Parts marked *(short version: skip)* take about 2 minutes.
- **[Point: …]** tells you what to point at on the poster.
- **Numbers.** All numbers are DIAGNOSTIC. They come from the 24 runs with tariff A in rc42 (19dc0780), and every run passed verification.
- **Costs.** Every cost leaves out the CO₂ cost and includes the basic charge. Diesel is counted as fuel used × 150 yen per litre. The electricity price leaves out the fuel-cost adjustment and the renewable levy.

---

## 0. Opening (30 s)

Good morning. My name is Liu, a first-year master's student. My research is about **trip assignment and charging optimization for electric buses that run alongside diesel buses**, toward green transformation, or GX.

My question is this: when a bus company switches to electric buses, how should it decide which bus runs which trip, and when each electric bus charges? And how much grid connection does it really need?

---

## 1. Background and aim (1 min)

**[Point: Section 1, blue box]**

Japan aims for carbon neutrality by 2050. Transport produces 19.3 percent of Japan's CO₂, so route buses are being electrified.

A bus company cannot replace its whole fleet at once. For many years, electric and diesel buses will run together.

Electric buses charge at the depot. If many of them charge at the same time, the depot draws a lot of power from the grid. In Japan, a larger contract also means a larger monthly basic charge.

**[Point: "Aim"]**

So my aim is to cut CO₂ by electrification, while keeping today's timetable and limiting the grid power.

---

## 2. Method (2 min)

**[Point: "Decisions"]**

The model decides two things:
- which bus, electric or diesel, runs each trip;
- when, and at how many kilowatts, each electric bus charges.

Every timetabled trip is run.

**[Point: objective]**

The objective is the total cost of one week. It adds up vehicle use, electricity, diesel, and a small CO₂ cost. The CO₂ cost only steers the plan. It is not part of any cost I report.

**[Point: electricity formula]**

The electricity cost follows TEPCO's high-voltage tariff. g and s are energies per 15 minutes, in kilowatt-hours. It has three terms:
1. **Energy**: 17.43 yen per kilowatt-hour, without the fuel-cost adjustment or the renewable levy.
2. **Basic charge**: 2,530 yen per kilowatt per month, times 0.85 for a 100 percent power factor, times the grid limit P. I convert this monthly charge to a weekly one.
3. **Excess**: a tentative 500 yen for each kilowatt-hour above the limit.

The second term depends only on P, so it is a constant within each case. I add it to the result instead of optimizing it. The limit is a target kept by pricing the excess, so it can be exceeded: at 200 kW in winter the peak was 690 kW. The contract power is not revised when that happens.

**[Point: Fig. 1]** *(short version: skip the details)*

The calculation has four steps:
1. Assign the 1,704 trips to 60 buses.
2. Plan the charging the day before, every 15 minutes.
3. Re-plan every hour with the actual sunshine.
4. Count cost and CO₂ from what was actually run.

Each case runs all four steps twice, from an electric-first and a diesel-first initial assignment, and the run with the lower step-4 total is adopted. I call these the adopted solutions. The choice is made on the executed total, not on the step-1 objective: at 90 kW in winter, electric-first was cheaper in step 1 but caused excess when run, so diesel-first was adopted.

The battery follows a rule: it charges only from surplus PV, never from the grid, and covers charging that PV cannot.

---

## 3. Case study (30 s)

**[Point: Fig. 2 and Table 2]**

The case is Tokyu Bus routes Shibu 21 to 23, run from the Tsurumaki depot, with 1,704 trips a week.
- The fleet has 35 electric and 25 diesel buses.
- The depot has ten 90 kW chargers, 1,000 kW of PV and a 6,000 kWh battery.

I tried four grid limits, 90, 200, 400 and 900 kW, in a winter, a spring and a summer week. That makes 12 cases.

---

## 4. Results (2 min)

**[Point: Fig. 3]**

In 11 of the 12 cases, electric buses ran 93.4 to 97.5 percent of the trips. The exception is 90 kW in winter. There, a diesel-heavy solution was cheaper, and electric buses ran only 22.0 percent of the trips. CO₂ was 1.1 to 2.3 tonnes a week in the 11 cases and 7.2 tonnes at 90 kW in winter.

**[Point: Table 3]**

Here is the main finding: **a higher grid limit is not cheaper.**
- The lowest total cost, shaded blue, was at 200 kW in spring and summer, and at 400 kW in winter.
- 900 kW was the most expensive in every season.

**[Point: Fig. 4]**

First, the total of the 12 adopted solutions is 4,199 to 4,574 thousand yen a week; the box above the chart says so. The bars show what remains after vehicle use, which is 4,020 to 4,080 thousand yen a week. The breakdown shows why.
- The basic charge grows with the limit: from 45 thousand yen a week at 90 kW to 447 thousand at 900 kW.
- Once the limit is large enough, energy and diesel hardly change.
- If the limit is too small, other costs grow instead. At 200 kW in winter, the excess costs 267 thousand yen a week. At 90 kW in winter, diesel rises to 411 thousand yen a week, and CO₂ is about 3.1 times that at 400 kW in winter.
- At 400 kW, spring costs more than winter in Table 3 but less in Fig. 4, because spring has 60 thousand yen a week more vehicle use.


---

## 5. Discussion and outlook (1 min 30 s)

**[Point: second bullet]**

Under these conditions, my operating guidance is this:
- Do not take a large grid limit.
- Spread the charging over time.
- Aim for about 400 kW.

At 400 kW, the peak grid power was 400.0 to 400.5 kW, against 570 to 794 kW at 900 kW; the only excess was 0.1 kWh in spring. Electric buses still run 93.7 to 96.0 percent of the trips, and the week costs about 244 thousand yen less than at 900 kW, on average over the three seasons. Against 200 kW the order changes with the season: 400 kW is 165 thousand yen a week cheaper in winter, and 200 kW is 131 and 100 thousand cheaper in spring and summer. Also, 200 kW drew up to 690 kW in winter. So I cannot say which of those two is better.

**[Point: Fig. 5]**

In the 12 adopted solutions, the runs stopped at a time or memory limit, but the objective had almost stopped improving before that point.
- In the trip assignment, the last 30 minutes improved the result by at most 0.11 percent.
- Of the 100 hourly re-plans that hit the time limit, out of 2,092, 91 had already reached their final solution by 240 seconds.

However, a gap to the lower bound remains: 44.8 to 49.5 percent for the assignment, and a median of 25 percent for the timed-out re-plans. So these are good solutions, not proven optimal ones. Optimizing the basic charge and the limit together is the next step.

**[Point: Fig. 6]**

My plan:
- **March 2027:** present this work at the IEEJ National Convention.
- **Fiscal 2027:** multi-day planning and battery optimization.
- **November 2027, second-year midterm:** gains over day-by-day planning.
- **February 2028, master's final:** guidance on choosing the grid limit, the battery and the chargers.

Thank you. I am happy to take questions.

---

## If asked: be honest

- All numbers are diagnostic and not yet used for research conclusions.
- The assignment stops at its time or memory limit and does not reach the 5 percent target gap; its gap to the lower bound is 44.8 to 49.5 percent. Solving in two stages also means the result is not a global optimum.
- The battery follows a fixed rule; it is not optimized.
- The 200 kW summer, electric-first run hit the 14 GiB day-ahead memory limit on its first try. It was rerun once at 24 GiB.
- Of the 174–175 hourly re-plans per run, at most 44 timed out over all 24 runs, and at most 35, 100 in total, in the 12 adopted ones.
- The excess price of 500 yen per kWh and the grid CO₂ factor of 0.5 kg per kWh are tentative values.

## Short answers to likely questions

| Question | Answer |
|---|---|
| Why is 900 kW the most expensive? | The basic charge grows with the limit: 447 thousand yen a week at 900 kW, about 250 thousand more than at 400 kW. Energy and diesel barely change. |
| So which limit is best? | Under these conditions, about 400 kW, where excess is almost zero. Against 200 kW the order changes with the season and optimality is not shown, so I cannot rank those two. |
| Is this optimal? | No. The target gap is 5 percent, but the assignment stops at its time or memory limit with a 44.8 to 49.5 percent gap, and the two-stage method is not a global optimum. Fig. 5 shows the objective had almost stopped improving before the cut-off. |
| Why is the basic charge not optimized? | The limit P is fixed in each case, so the basic charge is a constant. Choosing P together with the schedule is future work. |
| Why two initial assignments? | The search tends to stay near its start. Starting from two very different assignments and keeping the cheaper one gives a better result in limited time. |
| Would the basic charge not rise if the contract power is exceeded? | Yes, in a real contract it can be revised upward. I do not model that; the excess energy is only priced at a tentative 500 yen per kWh. The 200 kW results may look better than they would be, and this is future work. |
| How is diesel cost counted? | Fuel actually used × 150 yen per litre, not fuel bought. |
