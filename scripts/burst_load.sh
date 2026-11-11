#!/bin/bash
# Healthy burst: sends concurrent orders with NO fault injected, for a given
# number of seconds. Used to give the volume-based ML job an unusual-traffic
# spike to detect, and to test that its alert fires.
#
# Usage: ./scripts/burst_load.sh [seconds]     (default 150)
SECONDS_TO_RUN=${1:-150}
END=$(( $(date +%s) + SECONDS_TO_RUN ))

while [ "$(date +%s)" -lt "$END" ]; do
  for j in 1 2 3 4 5 6; do
    curl -s -o /dev/null -m 15 -X POST http://localhost:8000/api/orders \
      -H "Content-Type: application/json" \
      -d "{\"product_id\": $(( (j % 3) + 1 )), \"quantity\": 1}" &
  done
  sleep 2
done
wait
