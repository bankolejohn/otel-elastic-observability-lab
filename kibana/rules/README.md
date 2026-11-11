# Alert rules

Live definitions of the project's five Kibana alert rules, exported from the running cluster.

| file | what it watches |
|---|---|
| `error-volume-spike.json` | more than 5 error documents in `logs.obs-shop.errors*` within 5 minutes |
| `error-routing-pipeline-health.json` | error-classified logs piling up in the raw log stream (routing broke) |
| `order-latency-slo.json` | p95 of successful orders above 500 ms over 5 minutes (min 5 requests) |
| `db-pool-saturation.json` | a service's DB connection pool at its maximum (5 in use) within 3 minutes |
| `ml-anomaly-request-volume.json` | the `service_request_spikes` ML job scoring 50 or above |

Every rule sends an email through Elastic Cloud's preconfigured `Elastic-Cloud-SMTP` connector, once when the alert becomes active.

**The recipient is a placeholder** (`<alert-recipient-email>`) so no personal address is committed to this public repo. Replace it before creating a rule:

```bash
sed 's/<alert-recipient-email>/you@example.com/' kibana/rules/order-latency-slo.json \
 | curl -X POST "$KIBANA_ENDPOINT/api/alerting/rule" \
     -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "kbn-xsrf: true" \
     -H "Content-Type: application/json" -d @-
```
