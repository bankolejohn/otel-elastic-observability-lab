# SRE practice plan (using the remaining Elastic trial time)

The point of the whole project, from here on: stop *building* the
observability system and start *living in it*, the way a real SRE spends
their time. The trial has ~1 week left (as of 2026-11-01); this is the plan
for using it.

A reality check worth keeping in view: the traffic generator produces steady,
uniform, well-behaved traffic. Real production traffic has daily cycles,
spikes, and genuinely novel failures. Don't over-index on "is my data
realistic" -- it can't be, in a week. What *can* be practiced authentically
is the **workflow and muscle memory**, which is most of the value.

## The four points (in priority order)

### 1. Define what "healthy" means -- SLIs / SLOs
The single most SRE thing there is. Before you can say the system is broken,
you need a measured definition of "working." Candidate SLIs from data we
already have:
- **Availability**: % of `/api/orders` requests returning non-5xx
- **Latency**: p95 duration of the `POST /orders` trace
- **(maybe)** error-category rate from the Streams hierarchy

Then an SLO -- a target, e.g. "99% of orders succeed over a rolling 1h
window." Alerts should fire when an SLO is *at risk*, not on arbitrary
thresholds.

### 2. Build the RED dashboard (the deferred Stage J), to answer a question
The SRE test of a good dashboard: when paged at 3am, can it tell you within
30 seconds whether things are broken and roughly where? Three panels,
top to bottom, the "RED method":
- **R**ate (throughput -- are we serving requests?)
- **E**rrors (error rate vs the SLO -- are they succeeding?)
- **D**uration (latency percentiles -- are they fast?)

### 3. Run incident drills -- the gold
This is what makes the chaos tooling special. The on-call loop:
- Trigger a failure *blind* (something/someone picks the `/chaos` mode without
  telling you)
- Start only from the alert/dashboard, as if paged
- Work down: dashboard -> which service -> the trace -> the correlated log ->
  root cause
- **Time yourself**, then write a mini **blameless postmortem**: what broke,
  how it was detected, time-to-diagnose, what would have made it faster
- The postmortem is the actual SRE deliverable.

### 4. Tune the alerts against reality
The volume alert currently fires at ">5 errors in 5 min" -- an arbitrary
number. After drills, learn its real failure modes: false alarms on normal
traffic? misses a slow burn? fires after you'd already have noticed? Adjusting
a threshold because you *watched it be wrong* is real alert engineering.

## Suggested sequencing
Day 1: SLOs/SLIs. Day 1-2: RED dashboard. Rest of the week: incident drills +
postmortems (where it all comes together and the learning sticks).

## Status
- [ ] 1. SLIs/SLOs defined
- [ ] 2. RED dashboard built
- [ ] 3. First incident drill + postmortem
- [ ] 4. At least one alert threshold tuned based on a drill
