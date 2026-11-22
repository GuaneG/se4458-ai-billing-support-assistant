# AWS live evidence

SE4458 Group 2 · 22 November 2026

## Read-only Gateway checks

The following checks ran against the deployed HTTP API without a bearer
token. The public summary uses the assignment's synthetic subscriber data.

| Request | Observed |
| --- | --- |
| `GET /` | HTTP 200 |
| `GET /api/v1/subscribers/A001/bills/2026/10` | HTTP 200. Total USD 80.00, paid USD 20.00, balance USD 60.00. |
| `GET /api/v1/subscribers/A001/bills/2026/10/details?page=2&pageSize=1` | HTTP 401. Billing returned `{"detail":"A valid bearer token is required"}`. |

The combined live Chat screenshot shows a successful authenticated
`query_bill_details` call through the Agent. A standalone Gateway detail
response showing HTTP 200 and the pagination fields remains to be captured
with the demo subscriber login. The [recording script](DEMO_VIDEO_SCRIPT_TR.md)
has the command.

## Live Agent and payment captures

| Capture | Observed |
| --- | --- |
| [REST-only Chat](evidence/aws-chat-rest-only.png) | The Agent calls `query_bill` and reports the October total of USD 80.00. |
| [REST plus MCP Chat](evidence/aws-chat-rest-and-mcp.png) | The Agent calls `query_bill_details` and `search_billing_documentation`. It reports 35 GB usage, 15 GB overage and a USD 70.00 internet charge supported by sections 3.1 and 3.2. |
| [Confirmed simulated payment](evidence/aws-payment-confirmed.png) | The Chat prepares a USD 20.00 draft and shows the confirmed payment and USD 60.00 outstanding balance after the button is clicked. The read-only summary check independently shows the updated balance. |

The [local MCP-only Agent trace and three distinct retrieval examples](LOCAL_DEMO_EVIDENCE.md)
are recorded separately. A standalone **live MCP-only Chat capture** remains
to be collected for the demo video.

## Operator check

The AWS database check for the synthetic subscriber's November period showed
50 minutes in monthly usage and 40 minutes in the previously calculated bill.
After approving Calculate Bill again, the operator reported 50 minutes on
the bill and a total of USD 50.00. October payment evidence uses a different
billing period.

## Automated verification

The final local test run used a temporary PostgreSQL 17 Docker container
with separate read and write databases. The write suite used
`billing_usage_test`. Tests used synthetic records and their own signing keys.

```text
python -B -m pytest -p no:cacheprovider -q -rs --tb=short
......................................................                   [100%]
54 passed in 2.86s
```

The fast run without the optional PostgreSQL test variables returned
`51 passed, 3 skipped`. The three skipped cases were included in the
full PostgreSQL run. See the [test setup](../README.md#local-development).

The focused MCP retrieval run returned `3 passed, 3 deselected` for
sections **3.2**, **5.1**, and **6.3**.
