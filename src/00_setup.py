# Databricks notebook source
# Nightshift 00: create the schema, the raw-file volume, and the feedback table.
#
# Everything that has to exist before the other steps run is created here, once,
# so the other notebooks can assume it's there. Safe to rerun: every statement is
# IF NOT EXISTS, and nothing here deletes data.
#
# catalog and schema come from the job parameters (or the widgets at the top when
# you run it by hand), so nothing in the project hardcodes where tables live.

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
DB = f"{CATALOG}.{SCHEMA}"

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {DB} COMMENT 'Nightshift: overnight test-bench triage'")

# Raw logs land in a Unity Catalog volume, the same way a lab would drop files
# from bench PCs into cloud storage. Using a volume (not DBFS) keeps the raw files
# governed by the same permissions as the tables built from them.
spark.sql(f"CREATE VOLUME IF NOT EXISTS {DB}.raw_logs COMMENT 'Raw bench logs, as written by the bench PCs'")

# Engineer corrections to the triage model (see 05_triage_feedback). Created here
# because 03_triage_model reads it on every run, even before anyone has reviewed
# anything. It's append-only: the latest review per result_id wins, and the full
# history shows how often people overrode the model.
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {DB}.triage_feedback (
  result_id STRING,
  model_category STRING,
  corrected_category STRING,
  reviewed_by STRING,
  reviewed_at TIMESTAMP,
  note STRING
)
COMMENT 'Engineer corrections to the triage model. Latest row per result_id wins.'
""")

print(f"ready: {DB}, volume {DB}.raw_logs, table {DB}.triage_feedback")
