# Agentic AI Data Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Read--Only-336791.svg)](https://www.postgresql.org/)
[![Ollama](https://img.shields.io/badge/Ollama-phi3%3Amini-black.svg)](https://ollama.com/)
[![React](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB.svg)](https://vite.dev/)
[![Tests](https://img.shields.io/badge/tests-142%20passed-brightgreen.svg)](#testing--verification-suite)

Ask analytical questions about your database in plain English and get answers backed by verified PostgreSQL queries, or run automated API extraction and Pandas transformation jobs—all locally with **Ollama**, **FastAPI**, **LangGraph**, **PostgreSQL**, and an interactive **React + Vite** console.

No data leaves your machine unless you explicitly configure an external ETL host through the allow-list.

---

## System Architecture

```text
React + Vite UI (Port 3000) / REST Client
       │
       ▼
POST /api/v1/query
       │
       ▼
  RouterAgent
       │
       ├─────────────────────────────────────────────┐
       │                                             │
       ▼                                             ▼
SQLAnalystAgent                              ETLAnalystAgent
       │                                             │
       ├── curate schema                             ├── make_plan
       │                                             │
       ├── get_schema                                 └── execute
       │                                                   │
       ├── generate_sql                         ┌─────────┴─────────┐
       │                                         │                   │
       ├── validate_sql                    extract_load      execute_pandas_code
       │                                         │                   │
       ├── execute_readonly                     │              AST validation
       │                                         │                   │
       ├── self-correct on DB errors             │              subprocess sandbox
       │                                         │                   │
       └── finalize                              ▼                   ▼
                                           data/extract/       data/transform/
```

## Core Capabilities

### Hybrid Intent Routing

RouterAgent combines deterministic routing with LLM classification.

Uses deterministic zero-latency keyword matching for clearly identifiable ETL tasks.

Detects:

- extract
- transform
- http://
- https://
- .csv
- .parquet
- .json

Uses structured LLM classification through RouterSchema for natural-language analytical questions.

Routes database questions to SQLAnalystAgent.

Routes extraction and transformation requests to ETLAnalystAgent.

### Self-Healing SQL Analytics

SQLAnalystAgent provides natural-language analytics over PostgreSQL.

Capabilities include:

- Automatic PostgreSQL schema introspection.
- Cached information_schema metadata.
- Column data types and foreign-key relationships.
- PII-redacted sample rows.
- Join-minimization rules to reduce one-to-many aggregation errors.
- Generated SQL validation before execution.
- Read-only PostgreSQL execution.
- PostgreSQL execution-error capture.
- Automatic SQL self-correction.
- CTE-based query repair when appropriate.
- Explicit failure instead of fabricated numbers when requested schema fields do not exist.

For example, if the LLM initially generates:

```sql
SELECT AVG(r.rating)
FROM rides r;
```

and PostgreSQL reports:

```text
ERROR: column r.rating does not exist
```

the error is returned to the agent so it can attempt a corrected query using the actual schema.

### Single-Pass Sandboxed ETL

ETLAnalystAgent supports controlled extraction and transformation workflows.

#### Extract

extract_load:

- Streams JSON from explicitly allow-listed external REST APIs.
- Performs DNS resolution before connecting.
- Blocks private, loopback, and link-local destinations.
- Refuses HTTP redirects.
- Enforces maximum download size.
- Normalizes nested API records into tabular data.
- Writes output under `data/extract/`.

Supported output formats:

- CSV
- JSON
- Parquet

#### Transform

execute_pandas_code:

- Reads dataset metadata.
- Generates Pandas transformation code.
- Parses generated Python using `ast`.
- Rejects unsafe imports and operations.
- Executes validated code inside an isolated subprocess.
- Applies platform-specific resource controls.
- Writes output under `data/transform/`.

### Interactive Web Console

The `frontend/` application provides:

- React + Vite interface.
- Tailwind-based UI.
- Database question input.
- SQL inspection.
- ETL workflow interaction.
- Dataset drag-and-drop uploads.
- `POST /api/v1/upload`.
- `/health` monitoring.
- `/ready` monitoring.
- One-click verification presets.
- Guardrail status/error badges.
- Generated SQL visibility.

### Defense-in-Depth Security Model

Every LLM output, user prompt, URL, and file path is treated as untrusted input.

Each security layer assumes the layer before it may have failed.

| Layer | Component | Protection Mechanism |
| --- | --- | --- |
| 1. Pre-SQL & AST SQL Validation | SQLAnalystAgent + SQLValidator | Blocks destructive intents including DELETE, DROP, TRUNCATE, UPDATE, and ALTER. Removes comments/literals through sqlparse, enforces single-statement SELECT/WITH queries, and blocks dangerous PostgreSQL functionality such as `pg_*`, `lo_*`, `dblink`, `set_config`, and `COPY`. |
| 2. Database Session Isolation | DatabaseUtil | Opens agent connections with `readonly=True`, executes through a SELECT-only database role, applies `statement_timeout`, and limits returned rows through `DB_MAX_ROWS`. PostgreSQL therefore provides a second independent read-only enforcement layer. |
| 3. Static Code Validation | CodeValidator | Parses generated Pandas code using Python's `ast` module. Restricts imports, blocks `eval`, `exec`, `open`, `getattr`, `type`, probing through `try/except`, private/dunder access, and file/network I/O operations. |
| 4. Subprocess Sandbox | Sandbox + `_sandbox_runner.py` | Executes validated Pandas code inside an isolated `python -I` subprocess with a temporary working directory, restricted environment, restricted builtins, guarded imports, timeouts, and platform-specific CPU/memory/file-size controls. |
| 5. SSRF & Path Confinement | ETLTools + FileValidator | Enforces `ETL_ALLOWED_HOSTS`, resolves DNS addresses, blocks private/loopback/link-local IPs, disables redirects, limits downloads, and confines file access to `DATA_DIR`. |
| 6. API & PII Hardening | `routes.py` + `dependencies.py` | Uses constant-time API-key comparison, sliding-window rate limiting, bounded concurrency, upload-size enforcement, sanitized request IDs, and automatic exclusion of sensitive columns during schema sampling. |

## Quick Start

### Option 1: Docker Compose

Docker Compose can start the main local stack:

- FastAPI backend
- PostgreSQL
- Ollama
- Seed database
- Read-only PostgreSQL role

1. Configure environment

```bash
cp .env.example .env
```

Set at minimum:

```env
DB_PASSWORD=...
DB_READONLY_PASSWORD=...
API_KEY=...
```

2. Start the stack

```bash
docker compose up --build -d
```

On first startup the stack:

- Initializes PostgreSQL.
- Seeds the rides database.
- Creates the read-only analyst role.
- Starts Ollama.
- Pulls `phi3:mini` if configured by the Compose setup.

3. Test the API

```bash
curl \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":"Which 3 cities have the highest completed-payment revenue?"}' \
  http://localhost:8000/api/v1/query
```

### Health Endpoints

#### Liveness

```http
GET /health
```

The liveness endpoint is intentionally lightweight.

It does not require:

- Ollama
- PostgreSQL
- LLM inference

#### Readiness

```http
GET /ready
```

The readiness endpoint verifies dependencies including:

- PostgreSQL connectivity.
- Ollama reachability.
- Configured model availability.

### Option 2: Local Development

The following workflow works on Windows PowerShell, Linux, and macOS.

1. Create a virtual environment

```bash
python -m venv .venv
```

Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS

```bash
source .venv/bin/activate
```

2. Install dependencies

```bash
pip install -e ".[dev]"
```

3. Pull the Ollama model

```bash
ollama pull phi3:mini
```

### PostgreSQL Setup

If PostgreSQL is running locally or through Docker, seed the database using:

```bash
scripts/load_local.sh localhost 5432 postgres
```

Then create the read-only database role:

```bash
POSTGRES_USER=postgres \
POSTGRES_DB=rides_db \
DB_READONLY_USER=analyst_ro \
DB_READONLY_PASSWORD=ro \
PGHOST=localhost \
sh db/init/03_readonly_role.sh
```

The application should execute LLM-generated analytical SQL using the read-only role rather than the database owner.

### Start the Backend

```bash
uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

The API will be available at:

```text
http://127.0.0.1:8000
```

### Offline Development Without Ollama

A local canned Ollama server is included for testing:

```bash
python scripts/fake_ollama.py
```

This allows the API and agent orchestration layers to be exercised without requiring a running Ollama model.

The fake server should only be used for development/testing and must not be treated as a production inference service.

### Frontend Setup

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

The frontend communicates with the FastAPI backend through the configured `VITE_API_URL`.

### Deploying the Frontend to Render

The repository includes a `render.yaml` Blueprint for deploying the React + Vite frontend as a Render Static Site.

| Render Setting | Value |
| --- | --- |
| Service Type | Static Site |
| Root Directory | `frontend` |
| Build Command | `npm install && npm run build` |
| Publish Directory | `dist` |
| Environment Variable | `VITE_API_URL=https://your-backend-url.onrender.com` |

For a deployed backend, configure the backend CORS settings with the actual frontend origin.

Example:

```env
CORS_ORIGINS=["http://localhost:3000","http://localhost:8000","https://your-frontend.onrender.com"]
```

Do not place Markdown link syntax inside environment-variable values.

## Live API Verification Examples

### 1. Multi-Table Aggregation

Question:

```text
Which 3 cities have the highest completed-payment revenue?
```

PowerShell:

```powershell
$body = @{
    question = "Which 3 cities have the highest completed-payment revenue?"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    "http://localhost:8000/api/v1/query" `
    -ContentType "application/json" `
    -Body $body |
    Format-List
```

Example verified response:

```text
answer            : The three cities with the highest completed-payment revenue are
                    Toronto with $123,794.81, Montreal with $123,618.24,
                    and Winnipeg with $122,866.43.

agent_type        : sql

success           : True

sql               : SELECT u.city, SUM(p.amount) AS total_revenue
                    FROM payments p
                    JOIN rides r ON p.ride_id = r.ride_id
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.payment_status = 'completed'
                    GROUP BY u.city
                    ORDER BY total_revenue DESC
                    LIMIT 3
```

The important property is that the natural-language answer is backed by executable SQL rather than being generated as an unsupported textual guess.

### 2. Automatic SQL Self-Correction

Consider:

```text
What is the average rating for each vehicle make?
```

Suppose the first generated query incorrectly references:

```text
r.rating
```

from the `rides` table.

PostgreSQL reports:

```text
ERROR: column r.rating does not exist
```

The SQL agent captures the failure and can attempt another query using the actual schema.

PowerShell:

```powershell
$body = @{
    question = "What is the average rating for each vehicle make?"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    "http://localhost:8000/api/v1/query" `
    -ContentType "application/json" `
    -Body $body |
    Format-List
```

Example corrected SQL:

```sql
WITH RiderRatings AS (
    SELECT
        r.driver_id,
        r.ride_id,
        r.rating
    FROM ratings r
    JOIN rides rd
        ON r.ride_id = rd.ride_id
)
SELECT
    v.make,
    AVG(rr.rating) AS average_rating
FROM vehicles v
JOIN RiderRatings rr
    ON v.driver_id = rr.driver_id
GROUP BY v.make
ORDER BY average_rating DESC
LIMIT 10;
```

Example result:

```text
Ford:    4.4502923976608187
Hyundai: 4.4468690702087287
Tesla:   4.4300100704934542
Toyota:  4.4270298047276465
Nissan:  4.4232245681381958
Honda:   4.3788377192982456
```

### 3. External API Extraction and Sandboxed Pandas Transformation

#### Step 1 — Extract

The ETL agent can extract data from an allow-listed external API.

Example:

```text
Extract data from https://pokeapi.co/api/v2/pokemon
and save it as csv in the extract folder.
```

PowerShell:

```powershell
$body = @{
    question = "Extract data from https://pokeapi.co/api/v2/pokemon and save it as csv in the extract folder"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    "http://localhost:8000/api/v1/query" `
    -ContentType "application/json" `
    -Body $body |
    Format-List
```

The resulting dataset is written under:

```text
data/extract/
```

#### Step 2 — Transform

The extracted dataset can then be transformed through the Pandas sandbox.

Example:

```text
Transform extract/extracted_data.csv and keep only the first 5 rows,
save as csv.
```

PowerShell:

```powershell
$body = @{
    question = "Transform extract/extracted_data.csv and keep only the first 5 rows, save as csv"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    "http://localhost:8000/api/v1/query" `
    -ContentType "application/json" `
    -Body $body |
    Format-List
```

The transformed dataset is written under:

```text
data/transform/
```

## Security and Anti-Hallucination Verification

The project includes explicit security and correctness tests.

| Guardrail | Test Prompt | Expected Result |
| --- | --- | --- |
| Destructive SQL Block | Delete all rows from the payments table | `success: False` — generated SQL rejected by safety validation |
| SSRF Protection | Extract data from http://localhost:11434/api/tags and save it as csv | `success: False` — host not in `ETL_ALLOWED_HOSTS` |
| Path Traversal Block | Extract data from https://pokeapi.co/api/v2/pokemon and save it as csv in ../../outside | `success: False` — path escapes data directory |
| Schema Hallucination Guard | What is the average salary of drivers? | `success: False` — requested schema field does not exist |

## Configuration

All runtime configuration is managed through environment variables.

The primary configuration implementation is:

```text
src/core/config.py
```

See:

```text
.env.example
```

for the complete environment configuration.

| Variable | Default | Description |
| --- | --- | --- |
| `APP_ENV` | `development` | Runtime environment. Production mode disables interactive docs and enables production validation. |
| `API_KEY` | `None` | Required in production. Sent through the `X-API-Key` header. |
| `DB_HOST` | `localhost` | PostgreSQL host. |
| `DB_PORT` | `5432` | PostgreSQL port. |
| `DB_NAME` | `rides_db` | PostgreSQL database name. |
| `DB_USER` | `postgres` | Database owner/application setup user. |
| `DB_PASSWORD` | `postgres` | Database password. |
| `DB_READONLY_USER` | `None` | Read-only PostgreSQL role used for LLM-generated SQL. Required in production. |
| `DB_READONLY_PASSWORD` | `None` | Password for the read-only role. |
| `LLM_MODEL` | `phi3:mini` | Ollama model used by the agents. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint. |
| `MAX_RETRIES` | `2` | LLM transport/parse retries and SQL self-correction attempts. |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | PostgreSQL statement timeout in milliseconds. |
| `DB_MAX_ROWS` | `200` | Maximum rows returned to the agent. |
| `MAX_CONCURRENT_QUERIES` | `2` | Maximum concurrent inference/query operations. |
| `RATE_LIMIT_PER_MINUTE` | `30` | Sliding-window API request limit. |
| `ETL_ALLOWED_HOSTS` | `["pokeapi.co"]` | External hosts permitted for ETL extraction. |
| `ETL_ALLOW_PRIVATE_HOSTS` | `False` | Controls private-address access. Must remain `False` in production. |
| `SANDBOX_TIMEOUT_S` | `20` | Maximum Pandas subprocess execution time. |
| `SANDBOX_MEMORY_MB` | `2048` | Memory limit for sandbox execution where platform controls permit it. |

## Production Security Requirements

Before deploying publicly:

- Set `APP_ENV=production`.
- Configure a strong `API_KEY`.
- Configure a dedicated PostgreSQL read-only role.
- Never use the PostgreSQL owner account for LLM-generated queries.
- Keep `ETL_ALLOW_PRIVATE_HOSTS=False`.
- Explicitly configure `ETL_ALLOWED_HOSTS`.
- Use HTTPS for externally exposed services.
- Configure restrictive `CORS_ORIGINS`.
- Do not commit `.env` files or secrets.
- Review sandbox limits for the deployment platform.
- Keep database credentials separate from frontend configuration.
- Do not expose PostgreSQL directly to the public internet.
- Do not treat the fake Ollama server as a production component.

## Testing & Verification Suite

The project includes 142 automated unit and integration tests.

Run the complete suite:

```powershell
$env:PYTHONPATH = "."
python -m pytest -v
```

Expected result:

```text
142 passed
```

Run with coverage:

```powershell
$env:PYTHONPATH = "."
python -m pytest --cov=src -v
```

### Unit Tests

The unit suite covers:

- SQLValidator
- CodeValidator
- Sandbox
- Sandbox CPU/memory protections
- ETL SSRF validation
- Path confinement
- ETLTools
- ETLAnalystAgent
- SQLAnalystAgent
- SQL self-correction
- RouterAgent
- API-key authentication
- Rate limiting
- Health endpoints
- Non-blocking liveness checks
- Fake LLM behavior
- Agent orchestration

The unit tests do not require a live PostgreSQL database or Ollama server unless a specific test explicitly opts into those dependencies.

### Integration Tests

The integration suite contains live PostgreSQL tests covering:

- PostgreSQL read-only enforcement.
- DELETE rejection.
- CTE write rejection.
- Statement timeout behavior.
- Connection-pool recovery after query errors.
- PII column redaction.
- Database-level safety enforcement.

Integration tests require the configured PostgreSQL environment.

## Project Layout

```text
.
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── render.yaml
│
├── db/
│   ├── init/
│   │   ├── 01_schema.sql
│   │   ├── 02_seed.sh
│   │   └── 03_readonly_role.sh
│   │
│   └── analysis.sql
│
├── data/
│   ├── seed/
│   │   ├── users.csv
│   │   ├── vehicles.csv
│   │   ├── rides.csv
│   │   ├── payments.csv
│   │   └── ratings.csv
│   │
│   ├── extract/
│   ├── transform/
│   └── uploads/
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   │
│   └── src/
│       ├── main.jsx
│       └── App.jsx
│
├── scripts/
│   ├── fake_ollama.py
│   └── load_local.sh
│
├── src/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── routes.py
│   │   ├── dependencies.py
│   │   └── schemas.py
│   │
│   ├── agents/
│   │   ├── data_agent.py
│   │   ├── router_agent.py
│   │   ├── sql_analyst.py
│   │   └── etl_analyst.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   │
│   ├── llm/
│   │   ├── provider.py
│   │   ├── ollama.py
│   │   └── prompts.py
│   │
│   ├── security/
│   │   ├── sql_validator.py
│   │   ├── code_validator.py
│   │   ├── file_validator.py
│   │   ├── sandbox.py
│   │   └── _sandbox_runner.py
│   │
│   └── tools/
│       ├── etl.py
│       ├── sql.py
│       ├── pandas_tools.py
│       └── file_tools.py
│
└── tests/
    ├── conftest.py
    │
    ├── unit/
    │   ├── ...
    │   └── 133 unit/security tests
    │
    └── integration/
        └── test_database.py
```

## API Overview

### Query

```http
POST /api/v1/query
```

Example request:

```json
{
  "question": "Which 3 cities have the highest completed-payment revenue?"
}
```

Example response:

```json
{
  "answer": "...",
  "agent_type": "sql",
  "success": true,
  "sql": "SELECT ..."
}
```

### Upload

```http
POST /api/v1/upload
```

The upload endpoint applies:

- Size limits.
- Filename/path validation.
- Data-directory confinement.
- Sanitization before storage.

Uploaded files are stored under:

```text
data/uploads/
```

### Health

```http
GET /health
```

### Readiness

```http
GET /ready
```

## Design Principles

The project is intentionally built around several principles.

### 1. LLMs Are Planners, Not Authorities

The model proposes:

- SQL
- Routing decisions
- ETL plans
- Pandas transformations

The application validates those proposals before execution.

### 2. Database Permissions Are a Security Boundary

SQL validation is not treated as sufficient.

The database connection itself is read-only.

### 3. Generated Code Is Untrusted

Pandas code generated by the model follows:

```text
LLM
 ↓
AST validation
 ↓
Sandbox
 ↓
Subprocess
 ↓
Resource controls
 ↓
Execution
```

### 4. External Network Access Is Explicit

ETL requests must satisfy:

```text
URL
 ↓
Host allow-list
 ↓
DNS resolution
 ↓
Private-IP protection
 ↓
Redirect protection
 ↓
Download-size limit
 ↓
Request
```

### 5. Fail Closed

When validation fails, the system should return an error rather than execute an uncertain operation or invent an answer.

## Data Flow

### Analytical Question

```text
User
 │
 ▼
React UI / REST
 │
 ▼
FastAPI
 │
 ▼
RouterAgent
 │
 ▼
SQLAnalystAgent
 │
 ├── Schema inspection
 │
 ├── LLM SQL generation
 │
 ├── SQL validation
 │
 ├── PostgreSQL read-only execution
 │
 └── Optional self-correction
 │
 ▼
Verified result
 │
 ▼
FastAPI
 │
 ▼
React UI
```

### ETL Question

```text
User
 │
 ▼
FastAPI
 │
 ▼
RouterAgent
 │
 ▼
ETLAnalystAgent
 │
 ├── URL validation
 │
 ├── SSRF protection
 │
 ├── API extraction
 │
 ├── Dataset normalization
 │
 ├── AST validation
 │
 ├── Pandas subprocess sandbox
 │
 └── File/path validation
 │
 ▼
data/extract/
or
data/transform/
```

## Local-First Architecture

The default architecture is designed for local execution:

```text
┌─────────────────────────────────────────────┐
│                Local Machine                │
│                                             │
│  React + Vite                               │
│       │                                     │
│       ▼                                     │
│  FastAPI                                    │
│       │                                     │
│       ├──────────────► PostgreSQL            │
│       │                Read-only role        │
│       │                                     │
│       ├──────────────► Ollama               │
│       │                phi3:mini             │
│       │                                     │
│       └──────────────► ETL Sandbox          │
│                        Pandas                │
│                                             │
└─────────────────────────────────────────────┘
```

External network access is only used by ETL extraction when the destination is explicitly allow-listed.

## Limitations

The current implementation intentionally has several limitations:

- SQL generation quality depends on the configured LLM.
- Self-correction is bounded by `MAX_RETRIES`.
- The ETL agent only supports explicitly allow-listed hosts.
- The Pandas sandbox is a defense-in-depth mechanism and should not be treated as a substitute for a hardened container or VM boundary against a determined adversary.
- Windows does not provide all of the same kernel-level resource controls available through Linux `rlimit`.
- The demo database uses seeded ride/payment data.
- The frontend is intended as an operational/demo console rather than a full multi-user SaaS application.
- Authentication currently uses API-key protection rather than a complete user identity and authorization system.
- Persistent job history, distributed queues, and multi-user tenancy are outside the current scope.

## Future Improvements

Potential production extensions include:

- PostgreSQL-backed job history.
- Redis-based rate limiting.
- Distributed task queues.
- Per-user authentication and authorization.
- Persistent conversation history.
- Prompt/version tracking.
- SQL query observability.
- LLM cost/token tracking.
- More sophisticated schema-aware SQL planning.
- Human-reviewed analytical evaluation datasets.
- Automated LLM evaluation.
- Expanded document ingestion.
- Additional file formats.
- Container-level ETL isolation.
- Kubernetes deployment.
- Distributed Ollama/inference workers.
- OpenTelemetry tracing.
- Prometheus metrics.
- Grafana dashboards.

## License

Add the project's chosen license here before publishing the repository.

## Summary

Agentic AI Data Agent is a local-first agentic data platform that combines:

- FastAPI for the service layer.
- LangGraph for agent orchestration.
- Ollama for local LLM inference.
- PostgreSQL for structured analytical data.
- React + Vite for the interactive console.
- Pandas for controlled transformations.
- AST validation for generated Python.
- SQL validation for generated database queries.
- Subprocess sandboxing for transformation execution.
- SSRF and path-confinement controls for external data access.
- Read-only database permissions as an independent security boundary.

The central design principle is:

```text
Natural language
      ↓
Agent planning
      ↓
Deterministic validation
      ↓
Restricted execution
      ↓
Verified result
```

The LLM proposes actions, but security boundaries and execution controls remain outside the LLM.