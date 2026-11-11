#!/bin/bash
# Applies ALL Elasticsearch- and Kibana-side configuration for this project:
#   1. index/component templates + the reroute ingest pipeline (Elastic Streams pattern)
#   2. the two ML anomaly-detection jobs and their datafeeds
#   3. the five Kibana alert rules (with an email action if ALERT_EMAIL is set)
#   4. the RED dashboard v2
#
# Safe to re-run: templates/pipeline are overwritten with identical content,
# ML jobs / rules / the dashboard are skipped if they already exist.
#
# Needs a filled-in .env (ELASTIC_ENDPOINT, ELASTIC_API_KEY, KIBANA_ENDPOINT;
# optional ALERT_EMAIL). See docs/REPRODUCE.md.
cd "$(dirname "$0")/.." || exit 1
set -a; source .env; set +a
for v in ELASTIC_ENDPOINT ELASTIC_API_KEY KIBANA_ENDPOINT; do
  [ -n "${!v:-}" ] || { echo "ERROR: $v is not set in .env"; exit 1; }
done

TMP=$(mktemp)
FAILS=0
es() {  # es METHOD PATH [json-file]   -> prints HTTP code, body in $TMP
  curl -s -o "$TMP" -w "%{http_code}" -X "$1" -H "Authorization: ApiKey $ELASTIC_API_KEY" \
    -H "Content-Type: application/json" "$ELASTIC_ENDPOINT$2" ${3:+-d @"$3"}
}
report() {  # report LABEL CODE  -> OK / exists / FAIL
  local label="$1" code="$2"
  if [ "$code" = "200" ] || [ "$code" = "201" ]; then printf "  %-58s OK\n" "$label"
  elif grep -q "already_exists\|already exists\|resource_already_exists" "$TMP" 2>/dev/null; then printf "  %-58s exists (skipped)\n" "$label"
  else printf "  %-58s FAIL (HTTP %s)\n" "$label" "$code"; head -c 300 "$TMP"; echo; FAILS=$((FAILS+1)); fi
}

state() {  # state LABEL CODE -> for open/start calls: 409 just means "already running"
  if [ "$2" = "200" ]; then printf "  %-58s OK\n" "$1"
  elif [ "$2" = "409" ]; then printf "  %-58s already running (skipped)\n" "$1"
  else printf "  %-58s FAIL (HTTP %s)\n" "$1" "$2"; head -c 300 "$TMP"; echo; FAILS=$((FAILS+1)); fi
}

echo "== 1. Elastic Streams hierarchy =="
report "component template obs-shop-errors-mappings" "$(es PUT /_component_template/obs-shop-errors-mappings elastic/component-template-obs-shop-errors-mappings.json)"
report "ingest pipeline logs.obs-shop.errors@reroutes" "$(es PUT '/_ingest/pipeline/logs.obs-shop.errors@reroutes' elastic/ingest-pipeline-logs.obs-shop.errors-reroutes.json)"
for c in query_timeout connection_failed pool_exhausted unavailable; do
  report "child index template logs.obs-shop.errors.$c" "$(es PUT "/_index_template/logs.obs-shop.errors.$c" "elastic/index-template-logs.obs-shop.errors.$c.json")"
done
report "parent index template logs.obs-shop.errors" "$(es PUT /_index_template/logs.obs-shop.errors elastic/index-template-logs.obs-shop.errors.json)"

echo "== 2. ML anomaly detection =="
for job in service_request_spikes obs_shop_error_spikes; do
  report "job $job" "$(es PUT "/_ml/anomaly_detectors/$job" "elastic/ml/$job.job.json")"
  report "datafeed datafeed-$job" "$(es PUT "/_ml/datafeeds/datafeed-$job" "elastic/ml/$job.datafeed.json")"
  code=$(es POST "/_ml/anomaly_detectors/$job/_open"); state "open job $job" "$code"
  code=$(es POST "/_ml/datafeeds/datafeed-$job/_start" /dev/null); state "start datafeed datafeed-$job" "$code"
done

echo "== 3. Kibana alert rules =="
python3 - <<'EOF'
import glob, json, os, subprocess
K, KEY, EMAIL = os.environ["KIBANA_ENDPOINT"], os.environ["ELASTIC_API_KEY"], os.environ.get("ALERT_EMAIL", "").strip()
H = ["-H", f"Authorization: ApiKey {KEY}", "-H", "kbn-xsrf: true", "-H", "Content-Type: application/json"]
def curl(method, url, body=None):
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method] + H + [url] + (["-d", json.dumps(body)] if body else [])
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    text, code = out.rsplit("\n", 1)
    return int(code), text
code, text = curl("GET", f"{K}/api/alerting/rules/_find?per_page=200&fields=name")
existing = {r["name"] for r in json.loads(text).get("data", [])} if code == 200 else set()
for path in sorted(glob.glob("kibana/rules/*.json")):
    rule = json.load(open(path))
    if rule["name"] in existing:
        print(f"  {rule['name']:<58} exists (skipped)"); continue
    if EMAIL:
        for a in rule.get("actions", []):
            a["params"]["to"] = [EMAIL]
    else:
        rule["actions"] = []   # no recipient configured: create the rule without notifications
    code, text = curl("POST", f"{K}/api/alerting/rule", rule)
    note = "" if code == 200 else " " + text[:200]
    print(f"  {rule['name']:<58} {'OK' if code == 200 else 'FAIL (HTTP %d)' % code}{note}" + ("" if EMAIL else "  [no ALERT_EMAIL: created without email]"))
EOF

echo "== 4. Dashboard =="
code=$(curl -s -o "$TMP" -w "%{http_code}" -X POST -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "kbn-xsrf: true" \
  "$KIBANA_ENDPOINT/api/saved_objects/_import?overwrite=false" --form file=@kibana/dashboards/obs-shop-red-dashboard-v2.ndjson)
if grep -q '"success":true' "$TMP"; then printf "  %-58s OK\n" "RED dashboard v2"
elif grep -q "conflict" "$TMP"; then printf "  %-58s exists (skipped)\n" "RED dashboard v2"
else printf "  %-58s FAIL (HTTP %s)\n" "RED dashboard v2" "$code"; head -c 300 "$TMP"; echo; FAILS=$((FAILS+1)); fi

rm -f "$TMP"
echo
if [ "$FAILS" -eq 0 ]; then echo "Done: no failures."; else echo "Done with $FAILS failure(s) - see above."; exit 1; fi
