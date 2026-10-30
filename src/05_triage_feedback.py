# Databricks notebook source
# Nightshift 05: the human feedback loop.
#
# The model is only as good as its labels. In a real lab the labels come from
# engineers: when someone reviews a failure and says "that wasn't a script bug,
# it was the cable", that correction is saved here. 03_triage_model trains on
# corrections first, so every review makes the next morning's triage better.
#
# This notebook is run by hand, not by the nightly job. Reviewing is a person's job.

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
# Demo only, see the last cells. Off by default so nobody fakes reviews by accident.
dbutils.widgets.dropdown("simulate_reviews", "false", ["false", "true"])
DB = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

# Same threshold the morning agent uses for "needs a human look", so the review
# queue is exactly the list the report tells people to check.
LOW_CONFIDENCE = 0.7

# COMMAND ----------
# Review queue: last night's low-confidence calls that nobody has looked at yet.
#
# Only low-confidence calls are queued. Reviewing all ~60 failures a night would
# be the same manual triage this project is meant to remove; reviewing the few the
# model is unsure about is where a person's time teaches the model the most.

queue = spark.sql(f"""
  SELECT t.result_id, t.bench_id, t.test_name, t.error_message,
         t.predicted_category, t.confidence
  FROM {DB}.gold_failure_triage t
  LEFT ANTI JOIN {DB}.triage_feedback f ON t.result_id = f.result_id
  WHERE t.night = (SELECT max(night) FROM {DB}.gold_failure_triage)
    AND t.confidence < {LOW_CONFIDENCE}
  ORDER BY t.confidence
""")
display(queue)

# COMMAND ----------
# Record a review. Use the result_id from the queue above.
#
# The model's original call is stored next to the correction, so the table shows
# not just the right answer but how often and in which direction the model was wrong.
# Values go in as SQL parameters, not string formatting, since notes are free text.

CATEGORIES = {"script", "framework", "hardware_adb", "real_defect"}


def review(result_id, category, note=""):
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {sorted(CATEGORIES)}")
    spark.sql(f"""
      INSERT INTO {DB}.triage_feedback
      SELECT result_id, predicted_category, :category, current_user(), current_timestamp(), :note
      FROM {DB}.gold_failure_triage WHERE result_id = :result_id
    """, args={"result_id": result_id, "category": category, "note": note})
    print(f"saved: {result_id} -> {category}")


# Example:
# review("R27-SOLO-04-sanity-sanity_display_02-d1", "framework", "harness crashed, checked the log by hand")

# COMMAND ----------
# Demo only: simulate an engineer working through the review queue.
#
# The synthetic data has the true answers in bronze_ground_truth, so they stand
# in for a person. Rows are tagged 'simulated-reviewer' so they're easy to find
# and delete. In a real lab this cell wouldn't exist.

if dbutils.widgets.get("simulate_reviews") == "true":
    spark.sql(f"""
      INSERT INTO {DB}.triage_feedback
      SELECT t.result_id, t.predicted_category, g.true_category,
             'simulated-reviewer', current_timestamp(), 'simulated from ground truth'
      FROM {DB}.gold_failure_triage t
      JOIN {DB}.bronze_ground_truth g ON t.result_id = g.result_id
      LEFT ANTI JOIN {DB}.triage_feedback f ON t.result_id = f.result_id
      WHERE t.confidence < {LOW_CONFIDENCE}
    """)

# COMMAND ----------
# How often were engineers overriding the model?

display(spark.sql(f"""
  WITH latest AS (
    SELECT * FROM {DB}.triage_feedback
    QUALIFY row_number() OVER (PARTITION BY result_id ORDER BY reviewed_at DESC) = 1
  )
  SELECT model_category, corrected_category, count(*) AS reviews
  FROM latest
  GROUP BY ALL
  ORDER BY reviews DESC
"""))

# Rerun 03_triage_model to retrain on the corrections.
