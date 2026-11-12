# Production-like traffic with k6

`scripts/k6_production_like.js` replaces the flat `steady_traffic.sh` when you want realistic load. Install k6 (`brew install k6`) and run:

```
docker compose exec -T postgres psql -U app -d appdb -c "UPDATE inventory.products SET stock = 3000;"
k6 run scripts/k6_production_like.js                      # one compressed day, 24 minutes
k6 run -e DAY_MINUTES=2 scripts/k6_production_like.js     # quick check
k6 run -e DAY_MINUTES=60 -e DAYS=3 scripts/k6_production_like.js   # multi-day baseline for ML
```

## What it models

| Feature | Why it matters |
|---|---|
| Daily curve (night low, lunch and evening peaks), compressed into `DAY_MINUTES` | ML jobs learn a rhythm instead of a flat line, so anomalies are measured against a realistic baseline. |
| Mixed endpoints: 55% browse, 15% history, 25% purchase, 5% client mistakes | Real traffic is mostly reads. 404s and 409s must not trip 5xx alerts. |
| Open-model arrivals (`ramping-arrival-rate`) | Users keep arriving when the service slows, so queues build as in production. A closed loop would back off and hide the problem. |
| Retries with backoff on 5xx | Retries amplify failures, which is how many real outages escalate. The `retries` counter shows it. |
| Flash sale burst (`FLASH_RPS`, `FLASH_HOUR`) | A sudden spike layered on the curve, to test the volume alert and the ML job. |
| Thresholds from `docs/slo.md` (<1% 5xx, p95 < 1 s on orders) | k6 reports pass or fail against the same SLO the alerts use. |

## What it does not model

It generates traffic only. Faults still come from `/chaos` modes, `docker stop`, or the blind drill script. Run the two together: start k6, then run `./scripts/run_blind_drill.sh`. Network faults (Toxiproxy), multiple replicas and host metrics are separate work and are not included.

## Verified

A 2-minute run (`DAY_MINUTES=2`) against the local stack: 431 requests, 0 5xx, order p95 458 ms, all 375 checks passed, all thresholds met. A long run and a run together with a drill have not been tried.
