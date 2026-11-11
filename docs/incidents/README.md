# Incident drills

This directory is the deliverable of SRE practice-plan point 3: running
incident drills against the obs-shop system and writing a blameless
postmortem for each.

## Why drills, and why postmortems

The chaos tooling (Stage G) lets us *cause* a failure on demand. A drill turns
that into practice at the actual on-call job: get "paged," diagnose from
telemetry alone, find root cause, and -- most importantly -- write down what
would have made it faster. In a real org, the postmortem (not the fix) is the
artifact that compounds: it's how the whole team gets better at the next
incident, and it's blameless on purpose (the target is the *system and the
signals*, never the person).

## How we run a drill (the honest rules)

The whole value is in diagnosing *without already knowing the answer*, so:

1. **Dashboard up first.** The RED dashboard (`docs/stages/stage-j-red-dashboard.md`)
   is the "pager view." Have it open on "Last 1 hour", ~30s refresh, before
   starting.
2. **Blind injection.** The person/agent running the drill picks a `/chaos`
   mode (or a container stop) *without telling the responder which one*. The
   responder does NOT look at the chaos command.
3. **Start the clock at "page."** The responder only starts from the
   dashboard/alert -- as if woken by a notification -- not from "I know I just
   broke X."
4. **Work the funnel, narrate it.** Dashboard (which signal moved?) -> which
   service -> a representative trace -> the correlated log on that trace ->
   stated root cause and error category. Write down each step and its
   timestamp.
5. **Stop the clock at confident root cause.** Then reveal the actual injected
   fault and score it.
6. **Write the postmortem** from the template below, same day, while it's
   fresh.

## The scorecard (what "good" looks like)

- **TTD (time to detect)**: page/first-signal -> "yes, something is wrong."
  Faster is better, but *correct* beats fast.
- **TTR-diagnosis (time to root cause)**: first-signal -> confident, correct
  root cause. This is the number drills are really training.
- **Correctness**: did the stated root cause match the actual injected fault?
  A confident *wrong* answer is the most important kind to catch.
- **"What would've been faster?"**: the single most valuable line in the whole
  exercise -- it's the input to points 2 (dashboard) and 4 (alert tuning).

## Index
- [`drill-template.md`](drill-template.md) — copy this for each new drill
- [`example-drill-pool-exhaustion.md`](example-drill-pool-exhaustion.md) — a
  fully worked example, so you can see the shape of a good one before running
  your own

## Running a blind drill

`./scripts/run_blind_drill.sh &` picks one of `slow`, `query_timeout`, `connection_failed`, `pool_exhausted` at random, injects it for ~4 minutes under concurrent load, and resets chaos mode automatically. The chosen fault is sealed in `/tmp/obs-drill-answer.txt`; do not read it until a root cause has been committed to.

## Drills so far
- [2026-11-11 drill 1 — connection_failed](2026-11-11-drill-1-connection-failed.md) — partially correct
- [2026-11-11 drill 2 — pool_exhausted](2026-11-11-drill-2-pool-exhausted.md) — correct
