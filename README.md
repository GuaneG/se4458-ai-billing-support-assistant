# AI Billing Support Assistant

SE4458 Group 2 midterm project. The Billing REST API implements the five
assignment operations and uses PostgreSQL in Docker for local development.

## API contracts and data model

- [Billing OpenAPI](docs/openapi/billing.openapi.json)
- [Chat and Operator OpenAPI](docs/openapi/chat.openapi.json)
- [PostgreSQL ER diagram](docs/ER_DIAGRAM.md)
- [MCP tool schema](docs/MCP_TOOL_SCHEMA.json)
- [Local demonstration evidence](docs/LOCAL_DEMO_EVIDENCE.md)

The OpenAPI files were exported from the corresponding FastAPI apps. When a
service is running, it also exposes Swagger UI at `/docs` and the live schema
at `/openapi.json`. Gateway URLs and route mappings belong to the AWS stage.

## AWS deployment

The selected AWS design uses one ARM64 EC2 instance, EBS, an HTTP API
in API Gateway, and private integrations through VPC Link and Cloud Map.
Both external API requests and the Agent's Billing REST requests use the
Gateway URL. The Agent reaches MCP over EC2 loopback. Billing and Chat use
PostgreSQL on the same instance.

**Live application and API base URL** [se4458-billing-assistant](https://suj7bul3re.execute-api.eu-north-1.amazonaws.com)

The HTTP API uses the `$default` stage. Both private integrations use the
`se4458-link` VPC Link. Cloud Map resolves `chat` to port 8002 and
`billing` to port 8000. FastAPI checks the JWT and role on protected routes.

- [AWS deployment plan, routes and acceptance checks](docs/AWS_DEPLOY_PLAN.md)
- [Illustrated AWS Console guide (Turkish)](docs/AWS_CONSOLE_GUIDE.html)
- [Interactive architecture guide (Turkish)](docs/AWS_OGRENME_REHBERI.html)
- [Live AWS evidence and final test output](docs/AWS_LIVE_EVIDENCE.md)

### Deployed Gateway routes

| Method | Path | Integration | Access |
| --- | --- | --- | --- |
| GET | `/` | Chat | Login and Chat page |
| ANY | `/chat-assets/{proxy+}` | Chat | Static files, requested with GET by the browser |
| POST | `/api/v1/auth/login` | Chat | Valid demo or operator credentials |
| POST | `/api/v1/chat` | Chat | Subscriber JWT |
| POST | `/api/v1/chat/payments/confirm` | Chat | Draft owner's JWT and explicit confirmation |
| POST | `/api/v1/operator/operations/prepare` | Chat | Operator JWT with `billing:write` |
| POST | `/api/v1/operator/operations/confirm` | Chat | Operator JWT with `billing:write` and draft confirmation |
| GET | `/api/v1/subscribers/{subscriber_no}/bills/{year}/{month}` | Billing | Owner JWT or flagged synthetic public summary |
| GET | `/api/v1/subscribers/{subscriber_no}/bills/{year}/{month}/details` | Billing | Owner JWT, with `page` and `pageSize` |
| POST | `/api/v1/subscribers/{subscriber_no}/bills/{year}/{month}/payments` | Billing | Owner JWT |
| POST | `/api/v1/usage` | Billing | Operator JWT with `billing:write` |
| POST | `/api/v1/bills/calculate` | Billing | Operator JWT with `billing:write` |

The assets method reflects the last console capture. The deploy guide uses
`GET` for that route when setting up a new instance.

### Instructor walkthrough

1. Open the live application and sign in as the synthetic subscriber
   `A001` with the separately shared demo password. For the public API check,
   open `/api/v1/subscribers/A001/bills/2026/10`. The documented live total is
   USD 80.00 and the outstanding balance reflects recorded simulated payments.
2. Try a policy question about exceeding a 20 GB plan by 1 GB, the stored
   October 2026 bill amount, then the reason for the USD 70 October internet
   charge. The expected tool paths are MCP, REST, and REST plus MCP.
   Open **Tool trace** to see the calls. The combined example uses 35 GB of
   recorded usage and billing-guide sections 3.1 and 3.2.
3. Append `/details?page=2&pageSize=1` to the public summary path. With the
   authorization header absent, the live endpoint returns HTTP 401 and
   `{"detail":"A valid bearer token is required"}`. Use the owner-authenticated
   check in the [AWS deployment guide](docs/AWS_DEPLOY_PLAN.md)
   to inspect the response and pagination.
4. In Chat, request a simulated payment within the current outstanding
   balance and confirm it in the UI. The shown proof records a USD 20.00
   payment and a balance change from USD 80.00 to USD 60.00.

**Automated verification** The [full local run](docs/AWS_LIVE_EVIDENCE.md#automated-verification)
passed all **54 tests**, including the Docker PostgreSQL integration checks.
The [MCP section](#mcp-billing-guide) includes three distinct retrieval inputs
and expected passages. The test suite and scripted demo run without an
OpenAI API key or AWS.

**Demo video** Recording and submission link pending. The
[recording script](docs/DEMO_VIDEO_SCRIPT_TR.md) includes the narration,
screen order and verification commands.

## Local development

The Docker Compose service runs PostgreSQL with a persistent volume. The
database port is bound to loopback. On first initialization, it loads the
schema and the fictitious bill `A001` for October 2026.

The local `.env` file holds `POSTGRES_PASSWORD` for Docker Compose and
`BILLING_DATABASE_URL` for FastAPI. The API process reads the database URL
from its environment. It reads its separate JWT signing key from
`BILLING_JWT_SECRET`. The local credentials belong in the ignored `.env`
file or the process environment.

```powershell
py -m venv '.venv'
& '.\.venv\Scripts\python.exe' -m pip install -r 'requirements.txt'
docker compose up -d --wait
& '.\.venv\Scripts\python.exe' -m pytest -q
```

Tests run without a live LLM or AWS. To include PostgreSQL tests, set
`BILLING_TEST_DATABASE_URL` to the local Compose demo database for read-only
checks and `BILLING_TEST_WRITE_DATABASE_URL` to the dedicated
`billing_usage_test` database for write checks. Initialize the write
database with `schema.sql`, `usage.sql`, and `payments.sql` from
`billing_api/db` in that order. Tests create synthetic records and use
their own JWT signing keys.

## Bill details

`GET /api/v1/subscribers/{subscriber_no}/bills/{year}/{month}/details`

An authenticated subscriber can read their own stored bill. The optional
`page` and `pageSize` query parameters paginate the charge breakdown while
keeping the full totals and usage summary on each page. Currency amounts
are stored as integer cents and serialized as decimal strings in USD.

The initial demo bill contains 1,350 phone minutes and 35,000 MB. Its
charges are $10.00 for phone usage and $70.00 for internet usage, for a
total of $80.00. A fresh seed starts with the full $80.00 outstanding.
Use a fresh test bill to repeat the payment evidence if the existing
demo bill has already been paid.


## Usage and bill calculation

- `POST /api/v1/usage` receives `subscriberNo`, `year`, `month` and
  `usageType`. A `Phone` event adds 10 minutes. An `Internet` event adds
  1 MB. Each accepted request records one event by increasing its monthly
  totals.
- `POST /api/v1/bills/calculate` receives `subscriberNo`, `year` and
  `month`. It saves the usage and charges for the period, preserving any
  amount already paid. Calculating a known subscriber with zero usage
  creates a bill for the $50 internet base charge.
- Both return `{"status": "success"}` and require a signed JWT with the
  space-delimited `scope` claim containing `billing:write`. Ordinary
  subscriber tokens can still read their own bill details.
- PostgreSQL stores usage counters separately from calculated bills. The
  formula uses 1 GB = 1,000 MB and charges a full extra block for any part
  of that block used.

A fresh Docker volume applies `billing_api/db/usage.sql` during initialization.
For an existing development volume, apply the same repeatable migration once
while PostgreSQL is running:

```powershell
Get-Content -Raw -LiteralPath 'billing_api/db/usage.sql' |
    docker compose exec -T postgres psql --username=billing --dbname=billing_dev --set=ON_ERROR_STOP=1 --single-transaction -f -
```

Write integration tests use `BILLING_TEST_WRITE_DATABASE_URL` and require a
separate `billing_usage_test` database initialized with `schema.sql` and
`usage.sql`. Each run creates a distinct synthetic subscriber in that database.


## Summary and simulated payments

- `GET /api/v1/subscribers/{subscriber_no}/bills/{year}/{month}` returns
  the stored total, cumulative paid amount, remaining balance and
  `paid` or `unpaid` status. For the assignment's anonymous mobile
  operation, only explicitly public synthetic bills are visible without
  a token. The October `A001` demo is the initial public summary. A request
  supplying a Bearer token must use the bill owner's identity.
- `POST /api/v1/subscribers/{subscriber_no}/bills/{year}/{month}/payments`
  requires the owner's token and a JSON body with `amount` in USD and a
  `transactionId`. Its response reports the amount of this transaction
  and the remaining balance. A duplicate transaction ID or an amount
  above the current balance returns `409`.
- PostgreSQL locks the bill and commits the payment record and balance
  update together. The Chat workflow calls this simulated payment route
  after explicit confirmation.

The initial Compose setup also applies `billing_api/db/payments.sql` and
`billing_api/db/demo_public.sql`. On an existing development volume, use
the same `psql` pattern above to apply both files in that order. An
existing write-test database also needs `payments.sql`. It uses private
synthetic payment fixtures.


## MCP billing guide

The standalone MCP server uses the official Python SDK and Streamable HTTP.
It loads `mcp_server/Mobile_Provider_Billing_Guide.md` once per process.
Each numbered section with policy text becomes a passage. Section 9
contains assignment guidance, so the policy index covers sections 1–8.
The server builds an in-memory inverted index that maps each normalized
term to matching passages. For example, `extra` and `overage` map to
`additional`. A matching term contributes 4 points if it appears in the
heading or 1 point if it appears only in the body. Search reads the
postings for the query terms and returns at most three qualifying passages
by score, breaking ties in document order.

Run the server locally:

```powershell
& '.\.venv\Scripts\python.exe' -m mcp_server.server
```

Connect an MCP client to `http://127.0.0.1:8001/mcp` and invoke
`search_billing_documentation` with a `query` string (1–300 characters after
trimming). The [MCP tool schema](docs/MCP_TOOL_SCHEMA.json) is the local
server's `tools/list` response with its input and output schemas. The structured tool
result contains `document_id` and up to three `passages`. Each passage
contains `section`, `heading`, and the original `excerpt`. For a multi-term
query, a passage needs at least two distinct normalized term matches. A
single-term query can match one term. If no passage meets that rule, the tool
returns an empty list. This keeps a shared term such as "internet" from
returning ordinary billing sections for an unsupported roaming question.

| Demo query | Expected policy section |
| --- | --- |
| How much does extra internet cost beyond 20 GB? | 3.2 Additional internet blocks |
| Can I make a partial payment? | 5.1 Full and partial payments |
| When can my service be restricted after the due date? | 6.3 Service restriction |

`tests/test_mcp_billing_guide.py` exercises MCP tool discovery and all three
queries over the Streamable HTTP protocol using an in-process transport.


## CLI policy Agent

In one terminal, start the MCP server using the command in the MCP section.
In another terminal, run the scripted-model demo:

```powershell
& '.\.venv\Scripts\python.exe' -m agent --offline-demo
```

The demo uses the actual MCP server. It prints the tool name, arguments,
and result, followed by the guide excerpt and section citation. The model
turns are scripted in this mode, which uses no OpenAI credits.

With a funded API project and `OPENAI_API_KEY` in the local `.env`, select
live mode explicitly:

```powershell
& '.\.venv\Scripts\python.exe' -m agent --live 'Ek internet kac dolar?'
```

Live mode calls the Responses API with `gpt-6-luna`. The application
executes each policy tool call and sends a `function_call_output` with
the matching call ID. Responses are sent with `store=False`. The CLI
currently runs in billing-policy mode. Agent callers that supply an
authenticated BillingClient can also use `query_bill` for the stored bill
summary and `query_bill_details` for recorded usage and charges. To explain a
charge, the Agent can return both bill details and the relevant MCP guide
passage to the model.

## Chat HTTP API

`POST /api/v1/chat` accepts JSON with a `question` and uses the Bearer JWT
to identify the subscriber. It returns `answer` and `tool_trace` as JSON.
The caller must already have a valid subscriber JWT. The server also provides
a local sign-in page and `POST /api/v1/auth/login` for the fictitious account
`A001`. Configure `DEMO_LOGIN_PASSWORD` privately to enable sign-in when
running the standalone Chat API. When payment preparation
succeeds, Chat returns a `pending_payment` with the billing period, USD amount,
and `confirmation_id`. Send that ID to `POST /api/v1/chat/payments/confirm`
with the same subscriber's JWT after explicit user approval. The confirmation
expires after five minutes. Only the confirmation endpoint requests a payment
from Billing, and Billing uses a stable transaction ID for the confirmation.

For separate local processes, start the Billing API on port 8000
and start [the MCP server](#mcp-billing-guide) on port 8001 in another
terminal. Then start Chat on port 8002:

```powershell
& '.\.venv\Scripts\python.exe' -m uvicorn 'billing_api.main:app' --host 127.0.0.1 --port 8000 --env-file '.env'
```

```powershell
& '.\.venv\Scripts\python.exe' -m uvicorn 'agent.chat_api:app' --host 127.0.0.1 --port 8002 --env-file '.env'
```

The Chat process uses the existing `BILLING_JWT_SECRET` and
`OPENAI_API_KEY` settings. Set `BILLING_API_BASE_URL` to the API Gateway
base URL in a deployed environment. `MCP_URL` is separately configurable
and defaults to `http://127.0.0.1:8001/mcp` locally. The Billing and Chat
processes use the same `BILLING_JWT_SECRET`. Keep Chat on one worker for
the demo because pending approvals are held in that worker's memory.

`tests/test_chat_api.py` exercises the route in process with a scripted
model and fixture bill. It does not invoke OpenAI or require servers to be
started manually.

## Operator demo

Create an operator in the configured PostgreSQL database:

```powershell
python -m agent.operator_accounts operator
```

The command reads `BILLING_DATABASE_URL` from the process environment or local
`.env`, prompts for a password, and creates the `operator_accounts` table if
needed. It stores a salted password hash and rejects an existing username.

Restart the local web demo and sign in with that operator account. Choose
**Kullanım ekle** or **Fatura hesapla**, enter the subscriber and billing period,
select **İşlemi hazırla**, then review and approve the instruction. A useful
demo sequence is adding one Internet usage event for `A001` in a fresh month
and then calculating that month's bill. The operation uses the existing Billing
API routes through the configured billing base URL and consumes no OpenAI credit.

The operator JWT contains `billing:write`. A subscriber account cannot prepare
or confirm an operator operation. The operator approval reaches only the
operator who prepared it, expires after five minutes, and accepts one execution
attempt. A separate confirmation ID is required for each operation.

## Local Chat UI demo

Start the local Docker database, then run the offline demo from the project
root:

```powershell
docker compose up -d --wait
& '.\.venv\Scripts\python.exe' -m agent.chat_demo
```

The launcher prompts for a demo password in the terminal when
`DEMO_LOGIN_PASSWORD` is absent from the environment and local `.env`.
Use `A001` and that password to sign in at [Fatura Destek](http://127.0.0.1:8002/).
Then select an example. The demo
supports scripted MCP-only pricing, a REST-only bill summary, a combined
internet-charge explanation, and a payment example. Select a row in **Tool trace**
to see the tool's arguments and result for the latest question. Open
**Agent ↔ LLM** to follow the question and tool definitions, the model's
selected calls, the Agent's results, and the final reply. Each call and its
result share the same `call_id`. Rows expand to show the corresponding JSON.

The demo runs the Chat and Billing FastAPI routes and the MCP server inside
one local process. Billing reads the Docker `billing_dev` database. The demo
issues a short-lived token after verifying the demo password, using its own
process-local signing key. The LLM replies are scripted. The demo uses no
OpenAI credits.

To demonstrate payment, choose **Ödeme** and review the period and USD amount
in the **Simüle ödeme** card. Select **Ödemeyi onayla** to record the payment
and see the remaining balance. The confirmation uses the local demo database
and updates the fictitious subscriber’s bill. If its balance is $80 before
confirmation, the $20 payment leaves $60.

### Live model on the local Chat UI

Stop the offline Chat process and start the same screen in live mode.
Use the OpenAI project API key in the existing local `.env` or process
environment. The API project must have access to `gpt-6-luna` and a
usable quota.

```powershell
& '.\.venv\Scripts\python.exe' -m agent.chat_demo --live
```

Open [Fatura Destek](http://127.0.0.1:8002/) and look for **Canlı OpenAI**.
You can type a new question such as “Ekim 2026’da internet paketimi aşmış
mıyım?” and inspect the real tool calls in **Agent ↔ LLM**. The server
makes bill and MCP calls against the same local demo data. Sending a
question in this mode uses the OpenAI API. At the standard short-context
rate, `gpt-6-luna` costs $0.10 per million uncached input tokens and
$0.50 per million output tokens as of November 21, 2026. A tool-using
question can involve several model requests. Launching without `--live`
uses scripted responses and consumes no OpenAI credit.
[OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)
