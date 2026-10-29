CREATE OR REFRESH MATERIALIZED VIEW workspace.nightshift.silver_test_results (
  CONSTRAINT valid_status EXPECT (status IN ('PASS','FAIL','ERROR')) ON VIOLATION DROP ROW,
  CONSTRAINT has_timestamp EXPECT (started_at IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT failure_has_message EXPECT (status = 'PASS' OR error_message IS NOT NULL)
)
COMMENT "One row per test result: deduped, typed, joined to bench and build"
AS
WITH dedup AS (
  SELECT *, row_number() OVER (PARTITION BY result_id ORDER BY _ingested_at) AS rn
  FROM workspace.nightshift.bronze_runs
  WHERE event = 'test_result'
)
SELECT
  r.result_id, r.run_id, r.bench_id,
  CAST(b.display_count AS INT) AS display_count, b.pcm_link,
  r.build_id, bl.version AS build_version,
  r.suite, r.test_name, CAST(r.display AS INT) AS display,
  CASE WHEN r.started_at RLIKE '^[0-9]+$'
       THEN timestamp_seconds(CAST(r.started_at AS BIGINT))
       ELSE to_timestamp(r.started_at) END AS started_at,
  CAST(r.duration_s AS DOUBLE) AS duration_s,
  r.status, r.error_message, r.screenshot_path
FROM dedup r
LEFT JOIN workspace.nightshift.bronze_benches b ON r.bench_id = b.bench_id
LEFT JOIN workspace.nightshift.bronze_builds bl ON r.build_id = bl.build_id
WHERE r.rn = 1;

CREATE OR REFRESH MATERIALIZED VIEW workspace.nightshift.silver_watchdog_events
COMMENT "Watchdog reboots, one row per event"
AS
SELECT DISTINCT run_id, bench_id,
  CASE WHEN `at` RLIKE '^[0-9]+$'
       THEN timestamp_seconds(CAST(`at` AS BIGINT))
       ELSE to_timestamp(`at`) END AS rebooted_at,
  reason
FROM workspace.nightshift.bronze_runs
WHERE event = 'watchdog_reboot';