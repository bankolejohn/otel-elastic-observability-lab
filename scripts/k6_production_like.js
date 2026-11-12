// Production-like traffic for obs-shop (k6).
//
// What it simulates (traffic realism only; faults come from /chaos or docker):
//   - a daily curve: quiet night, morning ramp, lunch peak, evening peak
//     (a "day" is compressed into DAY_MINUTES of wall-clock time)
//   - a realistic endpoint mix: mostly reads, some orders, a few client
//     mistakes (unknown product -> 404, absurd quantity -> 409)
//   - think time that varies per virtual user
//   - client retries with backoff on 5xx (retry storms amplify real incidents)
//   - a flash-sale burst on top of the curve
//   - open-model arrivals: users arrive at a rate regardless of how slow the
//     system is, which is how real traffic behaves (a closed loop would
//     politely back off when the service slows down)
//
// Run:   k6 run scripts/k6_production_like.js
// Tune:  k6 run -e DAY_MINUTES=60 -e PEAK_RPS=4 -e DAYS=2 scripts/k6_production_like.js
// Quick: k6 run -e DAY_MINUTES=2 scripts/k6_production_like.js
//
// Stock note: orders consume stock. Restock first (and between long runs):
//   docker compose exec -T postgres psql -U app -d appdb \
//     -c "UPDATE inventory.products SET stock = 3000;"

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const DAY_MINUTES = parseFloat(__ENV.DAY_MINUTES || '24'); // length of one simulated day
const PEAK_RPS = parseFloat(__ENV.PEAK_RPS || '3');        // requests/sec at the busiest hour
const DAYS = parseInt(__ENV.DAYS || '1', 10);
const FLASH_RPS = parseFloat(__ENV.FLASH_RPS || '12');     // order arrivals/sec during the flash sale
const FLASH_HOUR = parseFloat(__ENV.FLASH_HOUR || '20');   // simulated hour the sale starts

// Relative load for each hour of the day (0-23), 1.0 = peak.
const HOURLY = [
  0.08, 0.05, 0.04, 0.04, 0.06, 0.12, // 00-05 night
  0.25, 0.45, 0.65, 0.75, 0.8, 0.9,   // 06-11 morning ramp
  1.0, 0.95, 0.8, 0.7, 0.7, 0.8,      // 12-17 lunch peak, afternoon dip
  0.9, 0.95, 0.85, 0.6, 0.35, 0.18,   // 18-23 evening peak, wind down
];

const hourSeconds = (DAY_MINUTES * 60) / 24;

// One ramping stage per simulated hour, repeated for DAYS days.
function dailyStages() {
  const stages = [];
  for (let d = 0; d < DAYS; d++) {
    for (let h = 0; h < 24; h++) {
      stages.push({
        target: Math.max(1, Math.round(PEAK_RPS * HOURLY[h])),
        duration: `${Math.max(1, Math.round(hourSeconds))}s`,
      });
    }
  }
  return stages;
}

export const options = {
  scenarios: {
    // Everyday browsing and buying, shaped by the daily curve.
    daily_traffic: {
      executor: 'ramping-arrival-rate',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 200,
      stages: dailyStages(),
      exec: 'shopper',
    },
    // A flash sale: a sharp 3-simulated-hour burst of orders, all day 1.
    flash_sale: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 200,
      startTime: `${Math.round(FLASH_HOUR * hourSeconds)}s`,
      stages: [
        { target: FLASH_RPS, duration: `${Math.max(1, Math.round(hourSeconds * 0.5))}s` },
        { target: FLASH_RPS, duration: `${Math.max(1, Math.round(hourSeconds * 2))}s` },
        { target: 0, duration: `${Math.max(1, Math.round(hourSeconds * 0.5))}s` },
      ],
      exec: 'flashBuyer',
    },
  },
  // These mirror docs/slo.md. They report, they do not abort the run.
  thresholds: {
    'http_req_failed{kind:order}': ['rate<0.01'],        // availability: <1% 5xx
    'http_req_duration{kind:order}': ['p(95)<1000'],     // latency SLO
    retries: ['count<1000'],
  },
};

// Treat 4xx as expected (the server correctly rejected a bad request).
// Only 5xx (and network errors) count as failures, matching the SLO.
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 499 }));

const retries = new Counter('retries');
const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };
const PRODUCT_IDS = [1, 2, 3];

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

// Retry on 5xx with exponential backoff and jitter, like a typical client SDK.
function postOrder(body, maxRetries) {
  let res;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    res = http.post(`${BASE}/api/orders`, JSON.stringify(body), {
      ...JSON_HEADERS,
      tags: { kind: 'order' },
    });
    if (res.status < 500) break;
    retries.add(1);
    sleep(Math.pow(2, attempt) * 0.5 + Math.random() * 0.5);
  }
  return res;
}

// Think time: most people click quickly, a few linger (long tail).
function think() {
  sleep(Math.random() < 0.9 ? 0.5 + Math.random() * 2 : 5 + Math.random() * 10);
}

export function shopper() {
  const r = Math.random();

  if (r < 0.55) {
    // Browse the catalogue (a read).
    const res = http.get(`${BASE}/api/products`, { tags: { kind: 'browse' } });
    check(res, { 'products 200': (x) => x.status === 200 });
  } else if (r < 0.7) {
    // Check order history.
    const res = http.get(`${BASE}/api/orders`, { tags: { kind: 'history' } });
    check(res, { 'orders list 200': (x) => x.status === 200 });
  } else if (r < 0.95) {
    // Buy something: browse first, think, then order (with retries).
    http.get(`${BASE}/api/products`, { tags: { kind: 'browse' } });
    think();
    const res = postOrder({ product_id: pick(PRODUCT_IDS), quantity: 1 + Math.floor(Math.random() * 2) }, 2);
    check(res, { 'order accepted or rejected cleanly': (x) => x.status < 500 });
  } else if (r < 0.98) {
    // Client mistake: product that does not exist (expect 404, not an incident).
    const res = postOrder({ product_id: 9999, quantity: 1 }, 0);
    check(res, { 'unknown product is 4xx': (x) => x.status >= 400 && x.status < 500 });
  } else {
    // Client mistake: absurd quantity (expect 409 insufficient stock).
    const res = postOrder({ product_id: pick(PRODUCT_IDS), quantity: 100000 }, 0);
    check(res, { 'absurd quantity is 4xx': (x) => x.status >= 400 && x.status < 500 });
  }

  think();
}

// Flash-sale buyers go straight to ordering, impatiently, retrying aggressively.
export function flashBuyer() {
  const res = postOrder({ product_id: pick(PRODUCT_IDS), quantity: 1 }, 3);
  check(res, { 'flash order handled': (x) => x.status < 500 });
  sleep(0.2 + Math.random() * 0.8);
}
