# Databricks notebook source
# Fails the job if the gold tables stop finding the three planted problems.

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
DB = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

# COMMAND ----------

flaky = [r.test_name for r in spark.sql(f"SELECT test_name FROM {DB}.gold_test_flakiness WHERE is_flaky").collect()]
assert flaky == ["brightness_slider"], f"flaky tests: {flaky}"

regs = [(r.build_version, r.test_name, int(r.display_count))
        for r in spark.sql(f"SELECT * FROM {DB}.gold_build_regressions").collect()]
assert regs == [("v2.4.1", "cold_boot_time", 2)], f"regressions: {regs}"

duo = spark.sql(f"""
  SELECT avg(CASE WHEN night <= '2026-10-10' THEN pass_rate END) AS early,
         avg(CASE WHEN night >= '2026-10-23' THEN pass_rate END) AS recent
  FROM {DB}.gold_bench_nightly_health WHERE bench_id = 'DUO-03'""").first()
assert duo.recent < duo.early - 0.05, f"DUO-03 not degrading: {duo}"

print("all three stories found")