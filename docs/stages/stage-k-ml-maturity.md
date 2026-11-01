# Stage K — Letting the ML jobs mature (ongoing)

Status: **Started, ongoing** — this stage doesn't "complete" in one sitting.

Third post-completion extension, following Stage H (browser
instrumentation) and Stage I (live alert rules).

## What

A lightweight, steady, deliberately-not-bursty traffic generator
(`scripts/steady_traffic.sh`), running continuously in the background,
so `service_request_spikes` (Stage F) and `obs_shop_error_spikes`
(Stage 2) accumulate real history instead of relying on manual test
bursts.

## Why

Both ML jobs have been under-trained every time they were checked:

| job | checked | non-empty buckets |
|---|---|---|
| `service_request_spikes` | Stage F | 5 of 1119 |
| `obs_shop_error_spikes` | Stage 2 | 1 of 10 |
| `service_request_spikes` | Stage K start (2026-11-01) | 64 of 4294 |
| `obs_shop_error_spikes` | Stage K start (2026-11-01) | 4 of 1723 |

`service_request_spikes` has grown organically just from the normal
course of testing every other stage (64 non-empty buckets now, up from
5) — but that's still mostly bursty, clustered test traffic, not the
steady background load a real baseline needs. The whole point of this
stage is to actually generate that, deliberately, rather than keep
reading the same "not enough data" result at every future check-in.

## How it works

```bash
./scripts/steady_traffic.sh
```

Places one order every 15-30 seconds (randomized, not a fixed interval,
so the traffic pattern itself doesn't look artificially periodic to the
model), cycling across all three products, restocking every 40 orders so
requests keep succeeding rather than degrading into "insufficient stock"
409s (which don't exercise the error-classification pipeline at all).

Started as a background process in this session
(`control_bash_process`), independent of this conversation — it keeps
running as long as the machine and `docker compose` stack are up,
regardless of whether anyone is actively working on this project.

## How to check progress later

```bash
set -a; source .env; set +a
for job in service_request_spikes obs_shop_error_spikes; do
  echo "--- $job ---"
  curl -s -H "Authorization: ApiKey ${ELASTIC_API_KEY}" \
    "${ELASTIC_ENDPOINT}/_ml/anomaly_detectors/${job}/_stats" \
    | python3 -c "
import json,sys
d = json.load(sys.stdin)['jobs'][0]['data_counts']
print('bucket_count:', d['bucket_count'], 'non-empty:', d['bucket_count'] - d.get('empty_bucket_count', 0))
"
done
```

A real baseline is probably somewhere in the range of "a few hundred
non-empty buckets with a stable count distribution," not a specific
magic number — the honest signal to look for is the anomaly scores
starting to show *some* variation (not every bucket scoring exactly
`0.0`), and specifically, re-running the Stage F/2 burst tests
afterward and checking whether they now score meaningfully above 0.

## What's next

Nothing to actively do — check back after real time has passed (hours,
ideally a day or more), re-run the verification query above, and if
there's finally enough history, re-trigger a deliberate burst (same
technique as Stage F/2) to see whether the model can finally tell the
difference between normal and anomalous. Remember to stop
`scripts/steady_traffic.sh` (Ctrl+C or killing its process) before it
runs indefinitely unattended, especially given the Elastic Cloud trial's
finite lifetime (see the earlier reminder to check its expiration date).
