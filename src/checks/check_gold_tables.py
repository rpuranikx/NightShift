# Databricks notebook source
# Nightshift data checks: run after the pipeline, before the model and the agent.
#
# The pipeline's expectations catch bad rows. These checks catch a bad pipeline:
# a change to silver or gold that still runs fine but quietly stops finding things.
# Because the data is generated with a fixed seed, the gold tables should find
# exactly the three planted problems, so the checks can be exact.
#
# If one fails, the job stops here and the model and agent never run on bad data.
# These were the queries I ran by hand while building the gold layer; as asserts,
# they run every time.

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
DB = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

failures = []


def check(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)

# COMMAND ----------
# Silver: every failure in the answer key made it through cleaning.

silver_failures = spark.sql(f"SELECT count(*) FROM {DB}.silver_test_results WHERE status <> 'PASS'").first()[0]
truth = spark.sql(f"SELECT count(*) FROM {DB}.bronze_ground_truth").first()[0]
check("silver keeps every failure", silver_failures == truth, f"{silver_failures} in silver, {truth} in ground truth")

dupes = spark.sql(f"SELECT count(*) - count(DISTINCT result_id) FROM {DB}.silver_test_results").first()[0]
check("silver has no duplicate results", dupes == 0, f"{dupes} duplicates")

# COMMAND ----------
# Story 1: DUO-03's cable is going bad, so its recent pass rate should be well
# below where it started.

duo03 = spark.sql(f"""
  SELECT avg(CASE WHEN night < date_add(min_night, 14) THEN pass_rate END) AS early,
         avg(CASE WHEN night > date_sub(max_night, 5) THEN pass_rate END) AS recent
  FROM {DB}.gold_bench_nightly_health,
       (SELECT min(night) AS min_night, max(night) AS max_night FROM {DB}.gold_bench_nightly_health)
  WHERE bench_id = 'DUO-03'
""").first()
check("DUO-03 is degrading", duo03.recent < duo03.early - 0.05,
      f"pass rate {duo03.early:.3f} early vs {duo03.recent:.3f} in the last 5 nights")

# COMMAND ----------
# Story 2: exactly one flaky test, and it's brightness_slider.

flaky = [r.test_name for r in spark.sql(f"SELECT test_name FROM {DB}.gold_test_flakiness WHERE is_flaky").collect()]
check("only brightness_slider is flaky", flaky == ["brightness_slider"], f"flagged {flaky}")

# COMMAND ----------
# Story 3: exactly one regression, v2.4.1 cold boot on dual-display benches.

regs = [(r.build_version, r.test_name, int(r.display_count))
        for r in spark.sql(f"SELECT * FROM {DB}.gold_build_regressions").collect()]
check("only the v2.4.1 boot regression", regs == [("v2.4.1", "cold_boot_time", 2)], f"found {regs}")

# COMMAND ----------

assert not failures, f"data checks failed: {failures}"
print("all checks passed")
