# Databricks notebook source
# Creates everything the other steps need. Safe to rerun.

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
DB = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {DB}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {DB}.raw_logs")
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {DB}.triage_feedback (
  result_id STRING, model_category STRING, corrected_category STRING,
  reviewed_by STRING, reviewed_at TIMESTAMP, note STRING
)""")
print(f"ready: {DB}")