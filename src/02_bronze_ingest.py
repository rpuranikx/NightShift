# Databricks notebook source
from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
CATALOG, SCHEMA = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
DB = f"{CATALOG}.{SCHEMA}"
RAW = f"/Volumes/{CATALOG}/{SCHEMA}/raw_logs"
CHK = f"{RAW}/_checkpoints"

# Run logs: Auto Loader picks up only new files each run
(spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", f"{CHK}/runs_schema")
    .load(f"{RAW}/runs/")
    .withColumn("_source_file", F.col("_metadata.file_path"))
    .withColumn("_ingested_at", F.current_timestamp())
    .writeStream
    .option("checkpointLocation", f"{CHK}/runs")
    .trigger(availableNow=True)
    .toTable(f"{DB}.bronze_runs")
    .awaitTermination())

# Small reference files: plain batch loads
spark.read.option("header", True).csv(f"{RAW}/benches.csv").write.mode("overwrite").saveAsTable(f"{DB}.bronze_benches")
spark.read.option("multiLine", True).json(f"{RAW}/builds.json").write.mode("overwrite").saveAsTable(f"{DB}.bronze_builds")
spark.read.option("header", True).csv(f"{RAW}/ground_truth.csv").write.mode("overwrite").saveAsTable(f"{DB}.bronze_ground_truth")