# Midterm poster talk — English script (8–12 min)

Poster: `midterm_poster_A0_v3_en_preview.pptx`. Questions are answered in Japanese: see `想定質疑_日本語.md`.

- About 1,250 words. At a calm 120–130 words a minute this is about 10 minutes. The parts marked *(short version: skip)* take about 2 minutes, so the talk can run from 8 to 12 minutes.
- **[Point: …]** tells you what to point at on the poster.
- **[n]** marks a number from the current, earlier-version results. Replace each one after the recomputation (rc42).
- Every cost leaves out the CO₂ cost.

---

## 0. Opening — 30 s

Good morning, everyone. My name is Liu, a first-year master's student. My research is on **trip assignment and charging optimization for electric buses that run alongside diesel buses**, toward green transformation, or GX.

In short: when a bus company switches to electric buses, how should it decide which bus runs which trip, and when each electric bus should charge, so that it does not need a bigger grid connection?

---

## 1. Background and aim — 1 min 30 s

**[Point: Section 1, blue box]**

Let me start with the big picture. In October 2020, Japan declared that it would reach net-zero greenhouse-gas emissions by 2050.

**[Point: "Transport"]**

Transport is a large part of the problem. It produces 19.3 percent of Japan's CO₂, and about 86 percent of that comes from road vehicles. So cutting emissions from road vehicles, including buses, matters.

**[Point: "Route buses"]**

Electric buses are now being introduced on route buses. But a bus company cannot replace its whole fleet at once. Buses are expensive, and they are replaced gradually. For many years, electric buses and diesel buses will run together at the same depot.

That creates a practical problem. Electric buses are charged at the depot, mostly at night. If many buses charge at the same time, the power the depot draws from the grid becomes large. A larger grid connection means more expensive equipment and a higher electricity bill.

**[Point: "Aim"]**

So my aim is to cut CO₂ by electrifying buses, while keeping today's timetable and limiting the cost of grid equipment and electricity.

**[Point: "This study"]**

In this study, I do three things. First, I optimize trip assignment and charging at a depot with both electric and diesel buses. Second, I compare how many trips electric buses can take, the cost and the CO₂ under different grid limits. Third, I look at when and why the grid limit is exceeded.

---

## 2. Method — 2 min 30 s

**[Point: "Decisions"]**

The model makes two kinds of decisions. First, for every trip in the timetable, which vehicle runs it: an electric bus or a diesel bus. Second, for every electric bus, when it charges and at how many kilowatts. Every timetabled trip must be run; we do not cancel any service.

**[Point: the objective function]**

The objective is to minimize the total cost of one week. From left to right, the terms are the cost of using vehicles, electricity including a cost for going over the grid limit, diesel fuel, and a cost on CO₂.

One note: the CO₂ cost is used only as a weight inside the optimization. When I report total costs, I leave it out, and I show CO₂ separately in kilograms.

**[Point: the caption under the objective]**

The main constraints:
- A bus must be able to make the next trip: arrival time, plus turnaround, plus empty running, must be no later than the next departure.
- The battery level of each electric bus must stay within its limits.
- There are only ten chargers.
- There is the grid limit. Power above the limit is allowed but costs 500 yen per kilowatt-hour. This value is tentative.

**[Point: Fig. 1, from left to right]**

The calculation has four steps:
1. Assign the 1,704 trips of one week to 60 buses. This is the hardest part, so I combine integer programming with a search that re-solves part of the assignment at a time.
2. With the assignment fixed, plan charging every 15 minutes for the next day, using a solar forecast based on long-term averages.
3. Every hour, re-plan the charging with the actual sunshine. Up to the morning after the last day, that is 174 to 175 re-plans per week.
4. Count the cost and CO₂ of what was actually carried out.

The battery in this study follows a fixed rule; it is not optimized yet.

**[Point: Table 1]**

The main values: electricity costs 17.43 yen per kilowatt-hour. The basic charge, which depends on the grid limit, is added to the results afterwards. As a comparison, I also calculate with 30 yen per kilowatt-hour including the basic charge. Diesel is 150 yen per litre, and a bus costs 20,000 yen per day to use. Each morning, an electric bus should be charged to 90 percent and never below 80 percent.

*(short version: skip)* For the stopping rule, every case uses the same optimality gap of 5 percent. The assignment step is limited to 3 hours, and each hourly re-plan to 300 seconds.

---

## 3. Case study — 1 min

**[Point: Fig. 2, the map]**

The case study uses real data from Tokyu Bus, routes Shibu 21, 22 and 23, which run from Shibuya Station through Setagaya. All of them are run from the Tsurumaki depot, marked with the red star. The timetable comes from Japan's public-transport open data.

**[Point: Table 2]**

There are 1,704 trips per week. I assume 35 electric and 25 diesel buses, ten 90-kilowatt chargers, 1,000 kilowatts of solar panels and a 6,000 kilowatt-hour battery at the depot.

I compare four grid limits — 90, 200, 400 and 900 kilowatts — in one week each of winter, spring and summer 2025, with actual sunshine. That makes twelve cases.

---

## 4. Results — 3 min

**[Point: Fig. 3]**

This chart shows the share of trips run by electric buses. With a grid limit of 400 kilowatts or more, electric buses ran **[92.0 to 96.5]** percent of all trips in every season.

**[Point: Fig. 4, the table]**

This table shows the total weekly cost for each case, in million yen. With 400 kilowatts or more, the cost is lowest, around **[4.1 to 4.2]** million yen per week.

**[Point: the starred cells]**

At low limits — **[90 kilowatts in winter and spring, and 200 kilowatts in winter]** — the cheapest solution used more diesel buses. Electric buses ran only **[23 to 39]** percent of trips. With so little grid power, charging more electric buses would go over the limit, and that costs more than diesel.

**[Point: "Getting good solutions in limited time"]**

Before Table 3, I want to explain one method point. The assignment problem is very large. Within the time limit, we cannot prove that a solution is optimal, and the search tends to stay near the assignment it starts from. So I start the search from two different assignments: one that uses electric buses first, and one that uses diesel buses first. Then I keep whichever result is cheaper. This is how we get good solutions in limited computing time.

**[Point: Table 3, left two columns]**

Here is the comparison for two winter cases. At 900 kilowatts, the electric-first solution cost **[4.19]** million yen, against **[4.38]** million for diesel-first. That is **[195]** thousand yen cheaper per week, and its CO₂ was **[58]** percent lower: **[2,470]** kilograms against **[5,949]**.

**[Point: right two columns]**

At 90 kilowatts, it is the other way round. The diesel-first solution was about **[408]** thousand yen cheaper. But it emitted about **[3.0]** times as much CO₂. The electric-first solution also went over the limit by **[1,291]** kilowatt-hours in that week.

**[Point: Fig. 5]**

*(short version: skip the details)* Fig. 5 shows all twelve cases. On the left is the cost difference; a negative value means electric-first was cheaper. On the right is CO₂. Electric-first emitted less CO₂ in **[every]** case, and was cheaper in **[9]** of the 12.

---

## 5. Discussion and outlook — 1 min 30 s

**[Point: Section 5, first bullet]**

So, what do these results mean? With enough grid capacity, electrification lowers both cost and CO₂. With a low limit there is a trade-off between cost and CO₂, and which solution is better depends on how much weight you give to CO₂.

**[Point: second bullet]**

Where does the excess over the limit come from? It was concentrated in the early morning after cloudy days, when the battery was already empty. The day-ahead plan forecasts solar power from long-term averages, so it cannot see a cloudy day coming.

**[Point: Fig. 6, left to right]**

Next steps:
- In March 2027 I will present this work, recomputed under uniform settings, at the IEEJ National Convention.
- During 2027 I plan conference papers on planning across days, optimizing the battery, and sensitivity to prices and the CO₂ factor.
- At the master's midterm in November 2027, I will show what multi-day planning gains over day-by-day planning: less battery shortfall in the morning, fewer trips moved to diesel, and less night-time grid use.
- In the final presentation in February 2028, I aim to give guidance on choosing the grid limit, the battery and the number of chargers.

---

## 6. Limitations and close — 30 s

**[Point: the note at the bottom]**

I should be honest about the limits. All numbers shown today are diagnostic: they come from earlier versions of the code, and every case is now being recomputed under the settings in Table 1. The assignment is not proven optimal, and because the problem is solved in two stages, the result is not a global optimum. Some hourly re-plans timed out — up to **[34]** of 174.

That is all. Thank you very much. I am happy to take questions — in Japanese is fine.
