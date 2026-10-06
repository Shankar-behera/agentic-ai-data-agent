"""LLM prompt templates for the Data Agent system."""

# ── SQL agent ────────────────────────────────────────────────────
SQL_SYSTEM = "You are a PostgreSQL expert. Reply with a single SQL query and nothing else."

SQL_CURATE_PROMPT = """Rewrite the question below so it is clear and specific for SQL generation.
Keep every entity, number and condition. Reply with the rewritten question only, on one line.

Original: {question}

Rewritten:"""

SQL_GENERATE_PROMPT = """Database schema:
{schema}

Write ONE PostgreSQL query that answers this question:
{question}

Rules:
- Read-only: a single SELECT (or WITH ... SELECT). Never modify data.
- Use only the tables and columns listed above, and the relationships shown.
- Do NOT join tables unless their columns are explicitly needed in SELECT or WHERE (e.g., `rides` already has `driver_id` and `rider_id`; do not join `vehicles` unless vehicle details like `make` or `model` are asked).
- For total payment revenue or money spent questions, sum `payments.amount` with `payments.payment_status = 'completed'`.
- For "top", "bottom", "highest", "lowest", "most" or "least" questions: aggregate, ORDER BY the measure
  (DESC for top/highest/most, ASC for bottom/lowest/least) and LIMIT to the number asked. Never rely on
  the model reading a longer list; the SQL itself must return exactly the ranked rows.
- Otherwise add LIMIT 10 unless the user asks for more or the query is an aggregate returning few rows.
- No comments, no explanation, no markdown fences. Output the SQL only.

Example (unrelated schema, shows the pattern only):
Question: Which 3 categories have the highest total sales?
SELECT c.name, SUM(s.amount) AS total_sales FROM sales s JOIN categories c ON c.id = s.category_id GROUP BY c.name ORDER BY total_sales DESC LIMIT 3"""

SQL_RETRY_SUFFIX = """

Your previous query failed.
Previous query:
{sql}
Database error:
{error}
Write a corrected query that follows the same rules."""

SQL_VALIDATE_PROMPT = """Review this PostgreSQL query for safety:

{sql}

It is safe only if it strictly reads data (SELECT / WITH ... SELECT), changes nothing, and does not call
file-system, network or administrative functions. Aggregations without a WHERE clause are fine."""

SQL_ANSWER_PROMPT = """Question: {question}

Result of the SQL query (first row is the column names):
{result}

Answer the question in clear, concise natural language using only the result above.
If the result is empty, say that no matching data was found. Do not invent numbers."""

SQL_SAFETY_SYSTEM = "You are a SQL security reviewer."

# ── ETL agent ────────────────────────────────────────────────────
ETL_PLAN_PROMPT = """You plan data tasks. Choose exactly one tool for the request.

Tools:
- "extract": download JSON from an API and save it. Needs: url, output_folder, format (csv|json|parquet).
- "transform": transform an existing data file with pandas. Needs: input_file_path, output_format (csv|json|parquet).

Request: {question}

Reply with JSON only. Example:
{{"tool": "extract", "url": "https://pokeapi.co/api/v2/pokemon", "output_folder": "extract", "format": "csv"}}"""

ETL_CODE_GENERATE_PROMPT = """Write pandas code that transforms a DataFrame named `df`.
The data has {rows} rows. Columns: {columns}
Sample rows: {sample_data}

Task: {question}

Rules:
- `df`, `pd` (pandas) and `np` (numpy) are already available. Do not import anything else.
- Do not read or write files. Assign the final DataFrame to `result`.
- No eval/exec, no attribute names starting with an underscore.
- Output Python code only, no explanation and no markdown fences."""

ETL_ANSWER_PROMPT = """The following ETL operation just ran:
{result}

Summarise in 2-4 sentences: what data was processed, what was done to it, where the output was saved,
and any problems. Use only the facts above."""

# ── Router ───────────────────────────────────────────────────────
ROUTER_SYSTEM = "You are a query router. Classify requests as SQL or ETL."

ROUTER_PROMPT = """Classify the request:
- "sql": answering a question about the data already in the database (counts, averages, rankings, trends).
- "etl": downloading data from an API, or transforming/cleaning/converting a data file.

Request: {question}"""