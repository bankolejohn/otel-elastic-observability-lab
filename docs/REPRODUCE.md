# Reproduce this project, step by step

This guide takes you from an empty folder to everything the project demonstrates: a traced app, telemetry flowing into Elastic Cloud, the Streams hierarchy, ML jobs, alerts that email you, a dashboard, and blind incident drills. Follow the parts in order; each ends with a **check** so you know it worked before moving on.

Time estimates are rough, from our own run: the first Docker build was slow (several minutes) and the Elastic Cloud account setup takes a few more.

## What you need

| need | notes |
|---|---|
| Docker with Compose | Docker Desktop is fine. Make sure it is **running**. |
| `curl` and `git` | already on macOS/Linux |
| `python3` | only used by helper scripts (standard library only) |
| An Elastic Cloud account | a free trial is enough: https://cloud.elastic.co/registration. Only needed from Part 2 onward. |
| ~2-3 hours the first time | plus drills |

The Elastic Cloud trial lasts about two weeks. If you want to keep practising afterwards, see "After the trial" at the end.

---

## Part 1: Run the app locally

```bash
git clone https://github.com/bankolejohn/otel-elastic-observability-lab.git
cd otel-elastic-observability-lab
docker compose up --build
```

The first build downloads images and installs Python packages, so it takes a while. Leave it running in that terminal and open a second one.

**Check:**
```bash
curl http://localhost:8000/health           # api-gateway   -> {"status":"ok"}
curl http://localhost:8001/health           # orders-service
curl http://localhost:8002/health           # inventory-service
curl http://localhost:8000/api/products     # three products
curl -X POST http://localhost:8000/api/orders -H "Content-Type: application/json" \
     -d '{"product_id": 1, "quantity": 1}'  # an order JSON comes back
```
Also open http://localhost:8000 and place an order in the browser.

Without any Elastic credentials the stack still runs: the Collector prints telemetry to its own console (`docker compose logs otel-collector`) and logs failed exports to the placeholder Elastic endpoint. That is expected at this point.

*What this is:* a browser, an `api-gateway`, an `orders-service`, an `inventory-service`, Postgres and Redis. See `ARCHITECTURE.md` and `docs/stages/stage-a-foundation-app.md`.

---

## Part 2: Create the Elastic Cloud project and fill in `.env`

The Elastic Cloud UI changes often; these steps were accurate in November 2026.

1. Sign up at https://cloud.elastic.co/registration and create a **project** (a serverless project; "Observability" or "Elasticsearch" type both work). New trial accounts are steered to projects rather than the older "deployments".
2. **Elasticsearch endpoint.** In Kibana open **Dev Tools**, then the **Console settings**, and copy the **"Elasticsearch host"** value. Use this one.
   > Do **not** use the endpoint from the "Add Observability data -> OpenTelemetry" quickstart screen. In our run that was a write-only ingest gateway: it accepted data but nothing appeared in the project, and `GET /` returned `"name":"managed-inputs"`. See `docs/adr/0010-direct-elasticsearch-endpoint.md`.
3. **API key.** In Kibana use the global search for **API keys**, create a key, and copy the **Encoded** value (one long string, not an id/key pair).
4. **Kibana endpoint.** Copy the origin from your browser's address bar while Kibana is open (the host contains `.kb.`).
5. Create your `.env`:
   ```bash
   cp .env.example .env
   ```
   and fill in `ELASTIC_ENDPOINT`, `ELASTIC_API_KEY`, `KIBANA_ENDPOINT`. Optionally set `ALERT_EMAIL` to the address that should receive alert emails. `.env` is gitignored; never commit it.

**Check:** load the values and test them.
```bash
set -a; source .env; set +a
curl -s -H "Authorization: ApiKey $ELASTIC_API_KEY" "$ELASTIC_ENDPOINT/"
```
You should see `"build_flavor":"serverless"` and **not** `"name":"managed-inputs"`. Then:
```bash
curl -s -H "Authorization: ApiKey $ELASTIC_API_KEY" "$ELASTIC_ENDPOINT/logs-*/_search?size=0"
```
should return a normal JSON response (zero hits is fine at this point), not a plain-text "404 page not found".

---

## Part 3: Ship telemetry to Elastic

```bash
docker compose up -d        # recreates the Collector so it picks up .env
```
Place a few orders (browser or the `curl` from Part 1), wait about 15 seconds, then:

**Check:**
```bash
curl -s -H "Authorization: ApiKey $ELASTIC_API_KEY" "$ELASTIC_ENDPOINT/_data_stream" \
  | python3 -c "import json,sys; print([d['name'] for d in json.load(sys.stdin)['data_streams']])"
```
Expect `logs-generic.otel-default`, `metrics-generic.otel-default` and `traces-generic.otel-default`.

Now follow one request all the way: take a `trace_id` from `docker compose logs orders-service` (log lines contain `trace_id=...`) and search for it in Elasticsearch:
```bash
curl -s -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "Content-Type: application/json" \
  "$ELASTIC_ENDPOINT/traces-generic.otel-default/_search?size=30" \
  -d '{"query":{"term":{"trace_id":"<paste id>"}}}'
```
You should see spans from `api-gateway`, `orders-service` and `inventory-service` (and `frontend` if you used the browser). Same `trace_id`, three services: that is distributed tracing.

*Read:* `docs/stages/stage-b-opentelemetry-instrumentation.md`, `stage-c-otel-collector.md`, `stage-d-elastic-cloud.md`.

---

## Part 4: Apply the Elasticsearch and Kibana configuration

Everything that lives inside Elastic (templates, the reroute pipeline, ML jobs, alert rules, the dashboard) is stored as files and applied by one script:

```bash
./scripts/setup_elastic.sh
```
It is safe to re-run. It creates, in order:
1. the **Elastic Streams hierarchy**: a component template, the `logs.obs-shop.errors@reroutes` ingest pipeline, a parent template and four child templates (`query_timeout`, `connection_failed`, `pool_exhausted`, `unavailable`);
2. two **ML anomaly-detection jobs** and their datafeeds (`service_request_spikes`, `obs_shop_error_spikes`);
3. five **Kibana alert rules** (with an email action if `ALERT_EMAIL` is set);
4. the **RED dashboard v2**.

**Check:** the script ends with `Done: no failures.` Items that already exist print `exists (skipped)`.

The files it applies: `elastic/` (templates, pipeline), `elastic/ml/` (jobs and datafeeds), `kibana/rules/` (alert rules), `kibana/dashboards/` (dashboards).

*Read:* `docs/stages/stage-2-elastic-streams.md` and ADRs 0015-0017 for why the hierarchy works the way it does.

---

## Part 5: Look at the data

In Kibana open **Discover**, switch to **ES|QL** mode, and try:
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders"
| EVAL ms = duration / 1000000
| STATS p50 = PERCENTILE(ms, 50), p95 = PERCENTILE(ms, 95)
```
New to the query language? Start with `docs/esql-cheatsheet.md`: it explains every query used in this project and has exercises with an answer key.

---

## Part 6: Dashboard and alerts

- **Dashboard:** Kibana -> Dashboards -> **obs-shop RED dashboard v2**. Set the time range to the last hour or two. Panels: Rate, Errors vs the 99% SLO, Duration vs the 500 ms SLO, error categories, and a per-span baseline. The SLOs behind it are in `docs/slo.md`.
- **Alerts:** Kibana -> Rules. You should see five `obs-shop` rules. If `ALERT_EMAIL` was set, each emails once when it becomes active. Test the email path directly:
  ```bash
  curl -s -X POST -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "kbn-xsrf: true" -H "Content-Type: application/json" \
    "$KIBANA_ENDPOINT/api/actions/connector/Elastic-Cloud-SMTP/_execute" \
    -d '{"params":{"to":["you@example.com"],"subject":"test","message":"hello"}}'
  ```
  The preconfigured `Elastic-Cloud-SMTP` connector exists on Elastic Cloud; it will not exist on a self-hosted cluster.

---

## Part 7: Generate traffic and break things

Steady background traffic (one order every 15-30 s, restocking periodically):
```bash
./scripts/steady_traffic.sh &
```
A healthy burst, no faults (useful to see the volume-based ML job score a spike):
```bash
./scripts/burst_load.sh 150
```
Inject a fault, place orders, then reset:
```bash
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode":"slow"}'
# ...place orders, watch the dashboard...
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode":"none"}'
```

| fault | how to cause it | what you see |
|---|---|---|
| `slow` | chaos mode `slow` | orders **succeed** but take ~2s+; **no errors**, so only the latency alert and Duration panel notice |
| `query_timeout` | chaos mode `query_timeout` | caller gives up at 5s (504) but the database write still commits: a "phantom success" |
| `connection_failed` | chaos mode `connection_failed` | fast 503s, `error.category = connection_failed` |
| `pool_exhausted` | chaos mode `pool_exhausted` + concurrent load | requests wait ~3s then fail; the DB-pool metric pins at 5/5 |
| Postgres down | `docker compose stop postgres` | `unavailable`; restart with `docker compose start postgres` (the first request afterwards may still fail on a stale connection) |
| Redis down | `docker compose stop redis` | **no errors at all**: the cache silently falls back to inventory-service |

If orders start failing with "Insufficient stock", restock:
```bash
docker compose exec -T postgres psql -U app -d appdb -c "UPDATE inventory.products SET stock = 3000;"
```
*Read:* `docs/stages/stage-g-chaos-engineering.md`.

---

## Part 8: Run a blind incident drill

This is the part that builds the actual skill.

```bash
./scripts/run_blind_drill.sh &        # picks a fault at random, runs ~4 minutes, resets itself
# DRILL_MODE=slow ./scripts/run_blind_drill.sh &   # or force one
```
The chosen fault is sealed in `/tmp/obs-drill-answer.txt`. **Do not read it** until you have committed to a diagnosis.

Your routine, writing down the clock time at each mark:
1. **T1, detect:** when you first know something is wrong (an alert email, or a dashboard panel moving).
2. **Count first, over a fixed window:**
   ```esql
   FROM logs.obs-shop.errors*
   | WHERE @timestamp >= "2026-11-11T14:29:00Z"
   | STATS c = COUNT(*) BY category = attributes.error.category
   | SORT c DESC
   ```
   Use fixed UTC times, not `NOW()`, which drifts once the incident ends. Kibana shows your local time; ES|QL uses UTC.
3. **Check the other signals** before deciding: a fault may produce no errors (check Duration), or show only as saturation (check the DB-pool metric).
4. **Open one trace** and find the deepest erroring or slowest span; compare it with its typical time on the baseline panel.
5. **T2, root cause:** state one cause, the service, and your evidence.

Then reveal the answer and write a blameless postmortem from `docs/incidents/drill-template.md`. Read the worked example and the real drills in `docs/incidents/` first.

---

## Part 9: A suggested reading order

1. `README.md`, then `ARCHITECTURE.md`
2. `docs/stages/` in order: A, B, C, D, E, F, G, 2, then H (browser), I (alerts), J (dashboard), K (ML maturity)
3. `docs/slo.md`, then `docs/incidents/` (template, example, three real drills, the alert review)
4. `docs/retrospective.md`: what worked, what didn't, what we got wrong
5. Dip into `docs/adr/` when a choice looks odd, and `docs/glossary.md` for any unfamiliar term

---

## Part 10: Troubleshooting (every row happened to us)

| symptom | cause | fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop not running | start it, retry |
| Image build: `No matching distribution found for greenlet` | transient PyPI/network hiccup | retry `docker compose up --build` |
| Collector exits: `endpoint must not be empty` | empty Elastic variables | `docker-compose.yml` now has safe defaults; or fill `.env` |
| `curl: (6) Could not resolve host` | typo in `ELASTIC_ENDPOINT` | print and re-copy the value (the endpoint is not a secret) |
| Exporter looks fine but no data in your project; root shows `managed-inputs` | wrong endpoint (the OTel quickstart gateway) | use "Elasticsearch host" from Console settings (ADR-0010) |
| Collector logs `dropping cumulative temporality histogram` | Elasticsearch cannot store cumulative histograms | already handled by the `cumulativetodelta` processor (ADR-0011) |
| ML datafeed: `cannot retrieve field ... has no mappings` | the field is inside a `flattened` object | map classifier fields as explicit `keyword` (ADR-0017) |
| ES|QL returns nothing after an incident | `NOW() - 5 minutes` moved past it | use fixed UTC timestamps |
| ES|QL parse error on a column name like `first` | reserved word | rename the column |
| Browser: no requests to :4318, no errors | two copies of `@opentelemetry/api` | pin versions as in `otel-web.js` (ADR-0019) |
| ML/alert `_open` or `_start` returns HTTP 409 | already running | fine, ignore |
| Kibana `GET /api/saved_objects/_find` returns 400 | not available on serverless | use `POST /api/saved_objects/_export` |
| The ML alert never fires | it points at a job with almost no history | point it at a job with data (see the retrospective) |
| Orders fail: `Insufficient stock` | chaos testing used up the stock | the restock command in Part 7 |

---

## Part 11: What will not reproduce exactly

- **Your numbers and timestamps will differ.** The documented counts, scores and trace IDs are from one run.
- **ML needs history.** The anomaly jobs score nothing useful until they have seen enough varied traffic; expect to run steady traffic and a few bursts first.
- **Versions drift.** The Collector is pinned to 0.153.0 and the Python dependencies are pinned, but the browser SDK is loaded from a CDN (`esm.sh`) and Elastic's UI changes. If something breaks, `docs/adr/0019-browser-instrumentation-dependency-pinning.md` explains the pinning approach.
- **The email connector is Elastic Cloud specific.**
- The Streams hierarchy here is built with plain templates and an ingest pipeline, not Kibana's Streams UI feature, mirroring the article's "build it yourself" section.

## After the trial

Elastic offers [start-local](https://www.elastic.co/search-labs/tutorials/install-elasticsearch/start-local), which runs Elasticsearch and Kibana on your own machine with Docker (its docs say it includes a one-month trial license). It has not been tested with this project; in principle you point `ELASTIC_ENDPOINT` and `ELASTIC_API_KEY` in `.env` at it and run Part 4 again. The Kibana-side scripts need `KIBANA_ENDPOINT` set too, and the email action will not work without an email connector.

## Cleanup

```bash
kill %1                       # stop a background steady_traffic / drill job, or find it with: ps | grep scripts
docker compose down           # stop containers, keep data
docker compose down -v        # also wipe the Postgres volume
```
Delete the Elastic Cloud project from the cloud console when you are finished, and revoke the API key.
