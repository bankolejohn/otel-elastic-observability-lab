# Incident drill — <SHORT TITLE>

**Date:** YYYY-MM-DD
**Responder:** <you>
**Drill runner:** <who injected the fault>
**Status:** resolved / abandoned

> Blameless. The subject of this document is the system and its signals --
> what they showed, what they didn't, and what would have made the truth
> obvious sooner. Never the person.

## Timeline
(Fill in real timestamps as you go -- this is the spine of the whole doc.)

| time | what happened / what I did |
|---|---|
| T+0:00 | "Paged" -- first noticed: <which dashboard panel / alert moved> |
| T+0:__ | <next observation or action> |
| T+0:__ | ... |
| T+0:__ | Confident root cause stated |
| T+0:__ | (reveal) actual injected fault: <...> |

## Scorecard
- **TTD (time to detect):** <mm:ss>
- **TTR-diagnosis (time to confident root cause):** <mm:ss>
- **Correct?:** yes / no / partially -- <stated cause vs actual>

## What actually happened (the real fault)
<The injected fault, revealed after the clock stopped. Chaos mode / container
stopped / etc.>

## How it showed up in telemetry
- **RED dashboard:** <which of Rate / Errors / Duration moved, and how>
- **Which service:** <where the signal pointed, and how you narrowed to it>
- **The trace:** <what one representative trace showed -- the span/status that
  gave it away>
- **The log:** <the correlated log line / error.category that confirmed it>
- **SLO impact:** <did availability / latency SLO breach? by how much? budget
  burned?>

## What worked
<What in the pipeline made this findable -- so we keep it.>

## What was slow or misleading
<Dead ends, ambiguous signals, things that pointed the wrong way, or data you
wished existed and didn't. Be specific -- this is the gold.>

## Action items
(Each should be concrete and ideally map to a practice-plan point.)
- [ ] <e.g. add X to the dashboard so this is obvious next time (point 2)>
- [ ] <e.g. the volume alert fired at T+__, but TTD was T+__ -- tune it (point 4)>
- [ ] <e.g. add a span attribute / log field that would have shortcut the diagnosis>
