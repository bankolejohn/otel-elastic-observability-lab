#!/bin/zsh
# Stage K: a lightweight, steady (deliberately NOT bursty) traffic
# generator, so the ML jobs (service_request_spikes, obs_shop_error_spikes)
# accumulate a real baseline over time instead of the handful of manual
# test requests every other stage relied on. See docs/stages/stage-k-ml-maturity.md.
#
# Run: ./scripts/steady_traffic.sh
# Stop: Ctrl+C, or `kill <pid>` if run in the background.

PRODUCTS=(1 2 3)
i=0

while true; do
  i=$((i + 1))
  pid=${PRODUCTS[$((RANDOM % 3 + 1))]}
  curl -s -o /dev/null -X POST http://localhost:8000/api/orders \
    -H "Content-Type: application/json" \
    -d "{\"product_id\": ${pid}, \"quantity\": 1}"

  # Restock periodically so orders keep succeeding (a steady stream of
  # successful requests is more useful for a baseline than a steady
  # stream of "insufficient stock" 409s).
  if (( i % 40 == 0 )); then
    docker compose exec -T postgres psql -U app -d appdb \
      -c "UPDATE inventory.products SET stock = 50;" >/dev/null 2>&1
  fi

  # Randomized 15-30s gap -- deliberately not a fixed interval, so the
  # traffic pattern itself doesn't look artificially periodic.
  sleep $(( 15 + RANDOM % 15 ))
done
