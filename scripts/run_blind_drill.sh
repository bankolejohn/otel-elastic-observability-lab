#!/bin/bash
# Blind incident drill runner (SRE practice plan, point 3).
#
# Picks a fault at RANDOM, injects it for ~4 minutes under concurrent load,
# then resets chaos mode to "none" automatically. The chosen fault is sealed
# in /tmp/obs-drill-answer.txt and deliberately NOT printed -- neither the
# responder nor the drill runner should read it until a root cause has been
# committed to. See docs/incidents/README.md for the rules.
#
# Run in the background:  ./scripts/run_blind_drill.sh &

MODES=(slow query_timeout connection_failed pool_exhausted)
MODE=${MODES[$((RANDOM % ${#MODES[@]}))]}
ANSWER=/tmp/obs-drill-answer.txt

# Always put the system back to normal, even if this script is killed.
trap 'curl -s -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d "{\"mode\":\"none\"}" >/dev/null' EXIT

echo "$MODE" > "$ANSWER"
date -u +%Y-%m-%dT%H:%M:%SZ > /tmp/obs-drill-start.txt

curl -s -X POST http://localhost:8002/chaos -H "Content-Type: application/json" \
  -d "{\"mode\":\"${MODE}\"}" >/dev/null

# ~4 minutes: every 3s, a burst of 6 concurrent orders. 6 > the pool size of
# 5, so pool_exhausted can genuinely occur; other modes just see steady load.
for i in $(seq 1 80); do
  for j in 1 2 3 4 5 6; do
    curl -s -o /dev/null -m 15 -X POST http://localhost:8000/api/orders \
      -H "Content-Type: application/json" \
      -d "{\"product_id\": $(( (j % 3) + 1 )), \"quantity\": 1}" &
  done
  sleep 3
done
wait
