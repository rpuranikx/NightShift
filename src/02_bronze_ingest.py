# Databricks notebook source
# Nightshift 02: load raw bench logs into bronze Delta tables.
#
# Bronze is a faithful copy of what the benches wrote, plus where and when each
# line came from. No cleaning happens here, so if silver ever has a bug, it can be
# rebuilt from bronze without going back to the bench PCs.

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
DB = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"
RAW = f"/Volumes/{dbutils.widgets.get('catalog')}/{dbutils.widgets.get('schema')}/raw_logs"
CHK = f"{RAW}/_checkpoints"

# COMMAND ----------
# Run logs: Auto Loader.
#
# Every night each bench adds a new file. Auto Loader remembers which files it has
# already loaded (in the checkpoint), so each run only picks up new ones instead
# of rereading 30 nights of history. availableNow processes whatever is new and
# then stops, which fits a scheduled job better than an always-on stream.
#
# Schema inference is off for the values: every column comes in as a string.
# Some benches log timestamps as epoch numbers and some as ISO text, so letting
# Spark infer types would either fail or silently null out one of the formats.
# Bronze keeps the text exactly as written and silver decides how to parse it.

(spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", f"{CHK}/runs_schema")
    .option("cloudFiles.inferColumnTypes", "false")
    .load(f"{RAW}/runs/")
    # Lineage columns: which file a line came from and when it was loaded.
    # Silver uses _ingested_at to keep the first copy of duplicated lines.
    .withColumn("_source_file", F.col("_metadata.file_path"))
    .withColumn("_ingested_at", F.current_timestamp())
    .writeStream
    .option("checkpointLocation", f"{CHK}/runs")
    .trigger(availableNow=True)
    .toTable(f"{DB}.bronze_runs")
    .awaitTermination())

# COMMAND ----------
# Reference data: benches, builds, and the true failure causes.
#
# These are small files that get rewritten as a whole, so a plain overwrite is
# simpler and more correct than streaming them. Everything stays a string here too.

spark.read.option("header", True).csv(f"{RAW}/benches.csv") \
    .write.mode("overwrite").saveAsTable(f"{DB}.bronze_benches")

spark.read.option("multiLine", True).json(f"{RAW}/builds.json") \
    .write.mode("overwrite").saveAsTable(f"{DB}.bronze_builds")

# The answer key. Only the triage model (as training labels) and the demo
# reviewer in 05 read it. Nothing in silver or gold uses it, so the gold tables
# and the dashboard find the planted problems without knowing about them.
spark.read.option("header", True).csv(f"{RAW}/ground_truth.csv") \
    .write.mode("overwrite").saveAsTable(f"{DB}.bronze_ground_truth")

# COMMAND ----------

display(spark.sql(f"SELECT event, count(*) AS lines FROM {DB}.bronze_runs GROUP BY event"))
