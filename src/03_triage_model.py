# Databricks notebook source
# Nightshift 03: train the failure-triage classifier.
#
# For every failed test, predict WHY it failed:
#   script | framework | hardware_adb | real_defect
# That's the call I make by hand every morning from logs and screenshots, and the
# one that decides who the failure goes to (test team, framework team, lab, or dev).
#
# Trained with scikit-learn, tracked in MLflow, registered in Unity Catalog, and
# scored back into a gold table for the dashboard and the morning agent.
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

# Hold out the most recent 8 nights. A random split would let the model train on
# nights after the ones it's tested on, which never happens in real use: every
# morning it has to predict last night from what came before.
TEST_NIGHTS = 8

# COMMAND ----------
# Features: the failure itself plus the context an engineer would check.
#
#   - error message text. Often enough on its own, but about 10% are missing
#     (crashed run, truncated log), so the model can't depend on it alone.
#   - status, suite, test, display, bench type
#   - how many other tests failed in the same run (a bad bench fails lots of tests)
#   - whether the watchdog rebooted that run (points at hardware)
#   - what share of benches failed this test on this build (a bad build fails
#     everywhere it runs, a bad cable fails on one bench)
#   - how often this test fails overall (a flaky script fails a little, everywhere)
#
# The context features are computed in SQL, where they're one GROUP BY each,
# then pulled into pandas. ~2,000 failures fits in memory easily; at real-lab
# scale this would move to a feature table.

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
-- An engineer can review the same failure twice; the latest call wins.
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
       -- A placeholder instead of NULL, so "no message" is itself a signal the model can learn.
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
# Spark returns some ratios as DECIMAL; MLflow and sklearn want plain floats.
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
    """Logistic regression on TF-IDF text plus one-hot and numeric context.

    Why this and not something bigger: ~2,000 labeled failures is small, and a
    linear model trains in seconds, is hard to overfit, and its weights can be read
    to see which words and features drive each call. The interesting signal here
    is in the context features, not in model complexity.
    """
    features = ColumnTransformer([
        # Word pairs catch phrases like "device offline" or "element detached".
        # min_df=2 drops one-off tokens such as specific serial numbers.
        ("text", TfidfVectorizer(ngram_range=(1, 2), min_df=2), TEXT),
        # ignore: a test name or bench type never seen in training shouldn't crash scoring.
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("num", "passthrough", NUMERIC),
    ])
    return Pipeline([
        ("features", features),
        # balanced: real defects are the rarest class but the one that matters most,
        # so the model isn't allowed to ignore them just to score well on scripts.
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])

# COMMAND ----------
# Train, evaluate and log everything to MLflow.
#
# Metrics: accuracy alone would look great by getting script failures right, since
# they're over half the data. Macro F1 weighs every category equally, and the
# missing-message accuracy shows how well the context features carry the model
# when there's no text to go on.

mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run(run_name="triage_logreg") as run:
    model = build_model()
    model.fit(train[FEATURES], train["true_category"])
    pred = model.predict(test[FEATURES])

    acc = accuracy_score(test["true_category"], pred)
    macro_f1 = f1_score(test["true_category"], pred, average="macro")
    missing = test[TEXT] == "<missing>"
    acc_missing = accuracy_score(test.loc[missing, "true_category"], pred[missing.values])

    # Logged so each training run shows how much of its data came from engineer reviews.
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

    # Registered in Unity Catalog so the model has versions, lineage back to the
    # run that trained it, and the same permissions as the tables.
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
#
# Confidence is saved next to each prediction because the downstream steps act on
# it: anything under 0.7 goes to a human instead of being reported as fact.
# split marks which rows the model trained on, so nobody mistakes train-set
# predictions for real performance.

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
