# Databricks notebook source
# Nightshift 04: the morning triage agent.
#
# An LLM with tools over the gold tables. Each morning it looks at last night's
# runs and writes the report an engineer would otherwise piece together by hand:
# what to file as a defect, which bench needs hardware attention, which scripts
# to fix, and which failures it isn't sure about.
#
# The design choice that made this work: the LLM does the writing, SQL does the
# analysis. Early versions handed the model raw failure rows, and it listed every
# failure one by one and reported a 53%-confidence guess as a defect. Switching to
# a different model gave nearly the same report. What fixed it was computing trends,
# known flaky tests, and how many benches share a failure in SQL (get_triage_summary)
# and giving the model clear rules for what goes where.
#
# Every model call and tool call is traced in MLflow, so when a report says
# "file a defect", you can see exactly which query results it was based on.

#
# The openai package is the simplest client for Unity Gateway, which speaks the
# OpenAI API. It's installed in the next cell because serverless doesn't ship it.

# COMMAND ----------

# MAGIC %pip install -q openai

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------
# Models are served through Unity Gateway as Unity Catalog model services.
# Browse Catalog > system > ai and pick a chat model that supports tool calling.
# Going through the gateway (instead of a legacy serving endpoint) means usage,
# rate limits and permissions are governed in Unity Catalog like everything else.
#
# Llama 3.3 70B because it handles tool calling well and is available on Free
# Edition. gpt-oss-120b produced nearly the same report, so model size wasn't the
# bottleneck; the tools were.

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
DB = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

MODEL = "system.ai.meta-llama-3-3-70b-instruct"   # or system.ai.gpt-oss-120b
# Same threshold as the review queue in 05: below this, the model's call isn't
# trusted enough to send someone off to fix it, so a person looks first.
LOW_CONFIDENCE = 0.7

# COMMAND ----------

import json
import mlflow
from openai import OpenAI

mlflow.openai.autolog()   # traces every LLM call

# Unity Gateway speaks the OpenAI API at <workspace>/ai-gateway/mlflow/v1.
# The notebook's own token is used, so there's no API key to store or rotate.
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
client = OpenAI(
    api_key=ctx.apiToken().get(),
    base_url=f"https://{spark.conf.get('spark.databricks.workspaceUrl')}/ai-gateway/mlflow/v1",
)


def query(sql, **params):
    """Run SQL and return rows as JSON text for the model.

    Anything the LLM chooses (a bench ID, a category) goes in as a named parameter,
    never pasted into the SQL string, so a bad tool argument can't change the query.
    """
    return (spark.sql(sql, args=params).toPandas()
            .to_json(orient="records", date_format="iso", default_handler=str))


LAST_NIGHT = spark.sql(f"SELECT max(night) AS n FROM {DB}.gold_failure_triage").first()["n"]
print("Reporting on night of", LAST_NIGHT)

# COMMAND ----------
# Tools. Each one is a plain SQL query over the gold layer.
#
# They're narrow on purpose: read-only, scoped to last night or one bench, and
# returning small result sets. The model never writes SQL itself, which keeps it
# from querying the answer key or pulling thousands of rows into its context.

@mlflow.trace(span_type="TOOL")
def get_fleet_summary():
    return query(f"""
        SELECT bench_id, display_count, pcm_link, tests, failures, pass_rate, reboots
        FROM {DB}.gold_bench_nightly_health
        WHERE night = '{LAST_NIGHT}'
        ORDER BY pass_rate""")


@mlflow.trace(span_type="TOOL")
def get_failures(bench_id=None, category=None):
    where, params = [f"night = '{LAST_NIGHT}'"], {}
    if bench_id:
        where.append("bench_id = :bench_id")
        params["bench_id"] = bench_id
    if category:
        where.append("predicted_category = :category")
        params["category"] = category
    return query(f"""
        SELECT bench_id, build_version, suite, test_name, display, error_message,
               predicted_category, confidence
        FROM {DB}.gold_failure_triage
        WHERE {' AND '.join(where)}
        ORDER BY confidence""", **params)


@mlflow.trace(span_type="TOOL")
def get_triage_summary():
    """Do the analysis in SQL so the LLM only has to write: trends, known flaky tests,
    and how many benches share each failure are computed here, not left to the model."""
    return query(f"""
        WITH f AS (
          SELECT * FROM {DB}.gold_failure_triage WHERE night = '{LAST_NIGHT}'
        ),
        flaky AS (
          SELECT test_name FROM {DB}.gold_test_flakiness WHERE is_flaky
        ),
        spread AS (
          SELECT test_name, count(DISTINCT bench_id) AS benches_failing_test
          FROM f GROUP BY test_name
        ),
        trend AS (
          SELECT bench_id,
                 max(CASE WHEN night = '{LAST_NIGHT}' THEN pass_rate END) AS pass_rate_last_night,
                 round(avg(CASE WHEN night < '{LAST_NIGHT}'
                                 AND night >= date_sub('{LAST_NIGHT}', 7) THEN pass_rate END), 4) AS pass_rate_prev_7_nights,
                 max(CASE WHEN night = '{LAST_NIGHT}' THEN reboots END) AS reboots_last_night,
                 sum(CASE WHEN night > date_sub('{LAST_NIGHT}', 7) THEN reboots END) AS reboots_last_7_nights
          FROM {DB}.gold_bench_nightly_health GROUP BY bench_id
        )
        SELECT f.bench_id, f.predicted_category,
               count(*) AS failures,
               count_if(f.confidence < {LOW_CONFIDENCE}) AS low_confidence,
               count_if(fl.test_name IS NOT NULL) AS known_flaky_failures,
               max(s.benches_failing_test) AS max_benches_sharing_a_test,
               collect_set(f.test_name) AS tests,
               first(f.error_message) AS example_error,
               max(t.pass_rate_last_night) AS pass_rate_last_night,
               max(t.pass_rate_prev_7_nights) AS pass_rate_prev_7_nights,
               max(t.reboots_last_night) AS reboots_last_night,
               max(t.reboots_last_7_nights) AS reboots_last_7_nights
        FROM f
        LEFT JOIN flaky fl ON f.test_name = fl.test_name
        LEFT JOIN spread s ON f.test_name = s.test_name
        LEFT JOIN trend t  ON f.bench_id = t.bench_id
        GROUP BY f.bench_id, f.predicted_category
        ORDER BY f.predicted_category, failures DESC""")


@mlflow.trace(span_type="TOOL")
def get_bench_history(bench_id):
    return query(f"""
        SELECT night, pass_rate, reboots
        FROM {DB}.gold_bench_nightly_health
        WHERE bench_id = :bench_id
        ORDER BY night DESC LIMIT 14""", bench_id=bench_id)


@mlflow.trace(span_type="TOOL")
def get_known_issues():
    return json.dumps({
        "flaky_tests": json.loads(query(f"SELECT test_name, avg_fail_rate, builds_intermittent FROM {DB}.gold_test_flakiness WHERE is_flaky")),
        "build_regressions": json.loads(query(f"SELECT * FROM {DB}.gold_build_regressions")),
    })


TOOLS = {
    "get_fleet_summary": get_fleet_summary,
    "get_triage_summary": get_triage_summary,
    "get_failures": get_failures,
    "get_bench_history": get_bench_history,
    "get_known_issues": get_known_issues,
}

# Tool descriptions are part of the prompt. "Start here" on get_triage_summary is
# what gets the model to begin with the summary instead of dumping raw failures.
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_fleet_summary",
        "description": "Last night's pass rate, failure count and watchdog reboots for every bench, worst first.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_triage_summary",
        "description": "Start here. Last night's failures grouped by predicted cause and bench, with counts, low-confidence counts, test names and an example error.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_failures",
        "description": "Last night's failed tests with the ML model's predicted cause and confidence. Filter by bench and/or category.",
        "parameters": {"type": "object", "properties": {
            "bench_id": {"type": "string", "description": "e.g. DUO-03"},
            "category": {"type": "string", "enum": ["script", "framework", "hardware_adb", "real_defect"]}}}}},
    {"type": "function", "function": {
        "name": "get_bench_history",
        "description": "Pass rate and reboots for one bench over the last 14 nights, to tell a trend from a one-off.",
        "parameters": {"type": "object", "properties": {
            "bench_id": {"type": "string"}}, "required": ["bench_id"]}}},
    {"type": "function", "function": {
        "name": "get_known_issues",
        "description": "Known flaky tests and known build regressions across all nights.",
        "parameters": {"type": "object", "properties": {}}}},
]

# COMMAND ----------
# The report sections follow who acts on each failure: dev team, lab, test team,
# framework team, or a person who needs to look first. Every rule below was added
# after a real report got something wrong (listing instead of grouping, calling
# known flaky tests new bugs, reporting one-off failures as confirmed defects).

SYSTEM_PROMPT = f"""You are Nightshift, the morning triage assistant for a hardware test lab.
Benches run overnight test suites on embedded vehicle displays (SOLO = single display, DUO = dual).
An ML model has already labeled each failure as script, framework, hardware_adb or real_defect.

Use the tools to investigate last night ({LAST_NIGHT}), then write a short morning report in Markdown:

1. **Summary**: one or two sentences on overall health.
2. **File a defect**: real product bugs, including known build regressions. These go to the dev team.
3. **Hardware attention**: benches whose failures and reboots point at cables or adapters. Check bench history to say whether it's getting worse.
4. **Fix the scripts**: flaky tests and script failures for the test team.
5. **Framework issues**: harness and config errors.
6. **Needs a human look**: failures where model confidence is below {LOW_CONFIDENCE}.

Rules:
- Start with get_triage_summary, then drill in only where something stands out.
- Only failures with confidence >= {LOW_CONFIDENCE} go in sections 2-5. Everything below that goes in section 6.
- Group, don't list: "DUO-03: 9 ADB failures on display 2, 4 reboots" beats nine separate bullets.
- Use the trend columns: if a bench's pass rate is below its previous 7 nights and reboots are climbing, say it is getting worse and how fast. Lead the report with that.
- known_flaky_failures are known flaky tests: say "known flaky" and don't count them as new script bugs.
- A real_defect that appears once, on one bench (max_benches_sharing_a_test = 1), is probably noise: list it as "single occurrence, watch" rather than a confident defect.
- Known build regressions only belong in "File a defect" if that build ran last night.
- Be specific (bench IDs, test names, counts). Don't invent anything the tools didn't return.
- At most 5 bullets per section, under 300 words total. Engineers read this before coffee."""


def message_text(msg):
    """Reasoning models (like gpt-oss) can return content as a list of parts; keep only the text."""
    content = msg.content
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else getattr(p, "text", "") or ""
                          for p in content
                          if (p.get("type") if isinstance(p, dict) else getattr(p, "type", None)) == "text")
    return content or ""


# A plain tool-calling loop instead of an agent framework: it's 20 lines, every step
# is visible in the MLflow trace, and there's nothing hidden to debug.
# max_steps caps cost and stops a model that keeps calling tools without finishing.
@mlflow.trace(span_type="AGENT")
def run_agent(max_steps=10):
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Write this morning's triage report."}]
    for _ in range(max_steps):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOL_SPECS)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            text = message_text(msg)
            if text.strip():
                return text
            # Some models end a turn with no text; ask once more for the report itself.
            messages.append({"role": "user", "content": "Now write the final report."})
            continue
        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = TOOLS[call.function.name](**args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    return "Stopped: too many tool calls without a final report."


report = run_agent()
print(report)

# COMMAND ----------
# Save the report so the dashboard (or a Slack/email job later) can pick it up.
# Appended, not overwritten, so there's a history of every morning's report.

from datetime import datetime, timezone

(spark.createDataFrame([(str(LAST_NIGHT), report, datetime.now(timezone.utc))],
                       "night STRING, report STRING, created_at TIMESTAMP")
    .write.mode("append").saveAsTable(f"{DB}.gold_morning_reports"))
