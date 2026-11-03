# Databricks notebook source
# Nightshift 03: train a failure-triage classifier.
#
# For every failed test result, predict WHY it failed:
#   script | framework | hardware_adb | real_defect
# That is the call an engineer makes by hand every morning from logs and screenshots.
#
# Trained with scikit-learn, tracked in MLflow, registered in Unity Catalog,
# and scored back into a gold table for the dashboard and the agent.
#
# Labels: engineer corrections from triage_feedback (05_triage_feedback) win.
# Everything else falls back to the historical label (here, the synthetic ground truth).

import mlflow
import pandas as pd
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
DB = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"
MODEL_NAME = f"{DB}.failure_triage"
TEST_NIGHTS = 8   # hold out the most recent nights, like predicting "tomorrow morning"

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {DB}.triage_feedback (
  result_id STRING, model_category STRING, corrected_category STRING,
  reviewed_by STRING, reviewed_at TIMESTAMP, note STRING
)""")

# COMMAND ----------
# Features: the failure itself plus the context an engineer would check.
#   - error message text (often enough on its own, but ~10% are missing)
#   - status, suite, test, display, bench type
#   - how many other tests failed in the same run (a bad bench fails lots of tests)
#   - whether the watchdog rebooted that run (hardware hint)
#   - what share of benches failed this test on this build (bad build hint)
#   - how often this test fails overall (flaky script hint)

FEATURES_SQL = f"""
WITH f AS (
  SELECT *, to_date(started_at - INTERVAL 12 HOURS) AS night
  FROM {DB}.silver_test_results
),
run_ctx AS (
  SELECT run_id, count_if(status <> 'PASS') AS run_failures
  FROM f GROUP BY run_id
),
reboot_ctx AS (
  SELECT run_id, count(*) AS run_reboots
  FROM {DB}.silver_watchdog_events GROUP BY run_id
),
build_ctx AS (
  SELECT build_version, test_name, display_count,
         count(DISTINCT CASE WHEN status <> 'PASS' THEN bench_id END)
           / count(DISTINCT bench_id) AS build_bench_fail_share
  FROM f GROUP BY build_version, test_name, display_count
),
feedback AS (
  SELECT result_id, corrected_category
  FROM {DB}.triage_feedback
  QUALIFY row_number() OVER (PARTITION BY result_id ORDER BY reviewed_at DESC) = 1
),
test_ctx AS (
  SELECT test_name, avg(CASE WHEN status <> 'PASS' THEN 1.0 ELSE 0.0 END) AS test_fail_rate
  FROM f GROUP BY test_name
)
SELECT f.result_id, f.night, f.run_id, f.bench_id, f.build_version,
       f.suite, f.test_name, CAST(f.display AS STRING) AS display,
       CAST(f.display_count AS STRING) AS display_count, f.pcm_link, f.status,
       coalesce(f.error_message, '<missing>') AS error_message,
       r.run_failures,
       coalesce(w.run_reboots, 0) AS run_reboots,
       b.build_bench_fail_share,
       t.test_fail_rate,
       coalesce(fb.corrected_category, g.true_category) AS true_category,
       fb.result_id IS NOT NULL AS human_reviewed
FROM f
JOIN {DB}.bronze_ground_truth g ON f.result_id = g.result_id
LEFT JOIN feedback fb  ON f.result_id = fb.result_id
LEFT JOIN run_ctx r    ON f.run_id = r.run_id
LEFT JOIN reboot_ctx w ON f.run_id = w.run_id
LEFT JOIN build_ctx b  ON f.build_version = b.build_version
                      AND f.test_name = b.test_name
                      AND f.display_count = b.display_count
LEFT JOIN test_ctx t   ON f.test_name = t.test_name
WHERE f.status <> 'PASS'
"""

df = spark.sql(FEATURES_SQL).toPandas()
# Spark returns some ratios as DECIMAL; MLflow and sklearn want plain floats
NUMERIC = ["run_failures", "run_reboots", "build_bench_fail_share", "test_fail_rate"]
df[NUMERIC] = df[NUMERIC].astype(float)
print(f"{len(df):,} failures")
df["true_category"].value_counts()

# COMMAND ----------
# Time-based split: train on older nights, test on the most recent ones.

nights = sorted(df["night"].unique())
cutoff = nights[-TEST_NIGHTS]
train, test = df[df["night"] < cutoff], df[df["night"] >= cutoff]
print(f"train {len(train):,} rows (before {cutoff}), test {len(test):,} rows")

TEXT = "error_message"
CATEGORICAL = ["status", "suite", "test_name", "display", "display_count", "pcm_link"]
FEATURES = [TEXT] + CATEGORICAL + NUMERIC


def build_model():
    features = ColumnTransformer([
        ("text", TfidfVectorizer(ngram_range=(1, 2), min_df=2), TEXT),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("num", "passthrough", NUMERIC),
    ])
    return Pipeline([
        ("features", features),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])

# COMMAND ----------
# Train, evaluate and log everything to MLflow.

mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run(run_name="triage_logreg") as run:
    model = build_model()
    model.fit(train[FEATURES], train["true_category"])
    pred = model.predict(test[FEATURES])

    acc = accuracy_score(test["true_category"], pred)
    macro_f1 = f1_score(test["true_category"], pred, average="macro")
    missing = test[TEXT] == "<missing>"
    acc_missing = accuracy_score(test.loc[missing, "true_category"], pred[missing.values])

    mlflow.log_metric("human_reviewed_labels", int(df["human_reviewed"].sum()))
    mlflow.log_params({"model": "logistic_regression", "test_nights": TEST_NIGHTS,
                       "features": ",".join(FEATURES)})
    mlflow.log_metrics({"accuracy": acc, "macro_f1": macro_f1,
                        "accuracy_missing_message": acc_missing})
    mlflow.log_text(classification_report(test["true_category"], pred), "classification_report.txt")

    labels = sorted(df["true_category"].unique())
    cm = pd.DataFrame(confusion_matrix(test["true_category"], pred, labels=labels),
                      index=labels, columns=labels)
    mlflow.log_text(cm.to_string(), "confusion_matrix.txt")

    mlflow.sklearn.log_model(
        model,
        artifact_path="model",
        signature=infer_signature(train[FEATURES], pred),
        input_example=train[FEATURES].head(3),
        registered_model_name=MODEL_NAME,
    )

print(f"accuracy {acc:.3f}  macro F1 {macro_f1:.3f}  accuracy on missing messages {acc_missing:.3f}")
print(classification_report(test["true_category"], pred))
cm

# COMMAND ----------
# Score every failure and save it for the dashboard and the agent.

proba = model.predict_proba(df[FEATURES])
out = df[["result_id", "night", "run_id", "bench_id", "build_version", "suite",
          "test_name", "display", "status", "error_message"]].copy()
out["predicted_category"] = model.classes_[proba.argmax(axis=1)]
out["confidence"] = proba.max(axis=1).round(3)
out["split"] = ["test" if n >= cutoff else "train" for n in df["night"]]

(spark.createDataFrame(out)
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{DB}.gold_failure_triage"))
print(f"wrote {len(out):,} rows to {DB}.gold_failure_triage")
