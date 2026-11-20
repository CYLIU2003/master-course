# Midterm poster talk: English script (2026-11-28)

Poster: `midterm_poster_A0_rc42_a_en.pptx`. This is variant a, tariff A only, revised after Prof. Urabe's reply of 19 November.

- **Length.** About 1,100 words, or 8–9 minutes at a calm pace. Parts marked *(short version: skip)* take about 2 minutes.
- **[Point: …]** tells you what to point at on the poster.
- **Numbers.** All numbers are DIAGNOSTIC. They come from the 24 runs with tariff A in rc42 (19dc0780), and every run passed verification.
- **Costs.** Every cost leaves out the CO₂ cost and includes the basic charge.

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

The electricity cost follows TEPCO's high-voltage tariff. It has three terms:
1. **Energy**: 17.43 yen per kilowatt-hour.
2. **Basic charge**: 2,530 yen per kilowatt per month, times a power-factor discount of 0.85, times the grid limit P. I convert this monthly charge to a weekly one.
3. **Excess**: a tentative 500 yen for each kilowatt-hour above the limit.

The second term depends only on P, so it is a constant within each case. I add it to the result instead of optimizing it.

**[Point: Fig. 1]** *(short version: skip the details)*

The calculation has four steps:
1. Assign the 1,704 trips to 60 buses.
2. Plan the charging the day before, every 15 minutes.
3. Re-plan every hour with the actual sunshine.
4. Count cost and CO₂ from what was actually run.

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

In 11 of the 12 cases, electric buses ran 93 to 97.5 percent of the trips. The exception is 90 kW in winter. There, a diesel-heavy solution was cheaper, and electric buses ran only 22 percent of the trips.

**[Point: Table 3]**

Here is the main finding: **a higher grid limit is not cheaper.**
- The lowest total cost was at 200 kW in spring and summer, and at 400 kW in winter.
- 900 kW was the most expensive in every season.

**[Point: Fig. 4]**

The breakdown shows why. I removed vehicle use, which is almost constant at about 4 million yen a week.
- The basic charge grows with the limit: from 45 thousand yen a week at 90 kW to 447 thousand at 900 kW.
- Once the limit is large enough, energy and diesel hardly change.
- If the limit is too small, other costs grow instead. At 200 kW in winter, the excess costs 267 thousand yen a week. At 90 kW in winter, diesel rises to 411 thousand yen a week.

*(short version: skip)* The assignment cannot be proven optimal. So I solve each case from two starts, electric-first and diesel-first, and keep the cheaper result.

---

## 5. Discussion and outlook (1 min 30 s)

**[Point: second bullet]**

Under these conditions, my operating guidance is this:
- Do not take a large grid limit.
- Spread the charging over time.
- Keep the limit at 400 kW, which avoids excess even in winter.

At 400 kW, electric buses still run 94 to 96 percent of the trips, and the week costs about 244 thousand yen less than at 900 kW. The difference from 200 kW is smaller than the 5 percent gap, so I cannot say which of those two is cheaper.

**[Point: Fig. 5]**

The runs were stopped at a time limit, but the objective had almost stopped improving before that point.
- In the trip assignment, the last 30 minutes improved the result by at most 0.11 percent.
- Of the 100 hourly re-plans that hit the time limit, 91 had already found their final solution by 240 seconds.

However, a gap to the lower bound remains, with a median of 25 percent. So these are good solutions, not proven optimal ones. Optimizing the basic charge and the limit together is the next step.

**[Point: Fig. 6]**

My plan:
- **March 2027:** present this work at the IEEJ National Convention.
- **Fiscal 2027:** multi-day planning and battery optimization.
- **February 2028, master's final:** guidance on choosing the grid limit, the battery and the chargers.

Thank you. I am happy to take questions.

---

## If asked: be honest

- All numbers are diagnostic and not yet used for research conclusions.
- The assignment is not proven optimal. Solving in two stages also means the result is not a global optimum.
- The battery follows a fixed rule; it is not optimized.
- The 200 kW summer, electric-first run hit the 14 GiB memory limit on its first try. It was rerun once at 24 GiB.
- At most 44 of the 174–175 hourly re-plans timed out.
- The excess price of 500 yen per kWh and the grid CO₂ factor of 0.5 kg per kWh are tentative values.

## Short answers to likely questions

| Question | Answer |
|---|---|
| Why is 900 kW the most expensive? | The basic charge grows with the limit: 447 thousand yen a week at 900 kW, about 250 thousand more than at 400 kW. Energy and diesel barely change. |
| So which limit is best? | Under these conditions, 400 kW, because it avoids excess even in winter. The difference from 200 kW is within the gap, so I cannot rank those two. |
| Is this optimal? | No. The runs stop at a 5 percent gap, and the two-stage method is not a global optimum. Fig. 5 shows the objective had almost stopped improving before the cut-off. |
| Why is the basic charge not optimized? | The limit P is fixed in each case, so the basic charge is a constant. Choosing P together with the schedule is future work. |
| Why two initial assignments? | The search tends to stay near its start. Starting from two very different assignments and keeping the cheaper one gives a better result in limited time. |
