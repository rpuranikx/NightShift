-- Nightshift silver layer: clean, typed, one row per real event.
--
-- Bronze keeps the logs exactly as the benches wrote them. Silver is where the
-- mess gets fixed: duplicate lines, two timestamp formats, and missing error
-- messages. Table names are unqualified on purpose; the pipeline's catalog and
-- schema come from the bundle (resources/nightshift.pipeline.yml).
--
-- These are materialized views rather than streaming tables. 30 nights of logs
-- is small, and the dedupe and joins below need the whole table anyway.

CREATE OR REFRESH MATERIALIZED VIEW silver_test_results (
  -- A result with an unknown status or no timestamp can't be counted toward a
  -- pass rate or placed on a night, so it's dropped instead of guessed at.
  CONSTRAINT valid_status EXPECT (status IN ('PASS', 'FAIL', 'ERROR')) ON VIOLATION DROP ROW,
  CONSTRAINT has_timestamp EXPECT (started_at IS NOT NULL) ON VIOLATION DROP ROW,
  -- A failure with no error message is still a real failure, so this one only
  -- warns. The event log tracks how often it happens, and the triage model has
  -- to cope with it using context instead of text.
  CONSTRAINT failure_has_message EXPECT (status = 'PASS' OR error_message IS NOT NULL)
)
COMMENT "One row per test result: deduped, typed, joined to bench and build"
AS
WITH dedup AS (
  -- The result uploader sometimes retries and writes the same line twice.
  -- result_id is unique per test per display per run, so keep the first copy.
  SELECT *, row_number() OVER (PARTITION BY result_id ORDER BY _ingested_at) AS rn
  FROM bronze_runs
  WHERE event = 'test_result'
)
SELECT
  r.result_id, r.run_id, r.bench_id,
  CAST(b.display_count AS INT) AS display_count, b.pcm_link,
  r.build_id, bl.version AS build_version,
  r.suite, r.test_name, CAST(r.display AS INT) AS display,
  -- Older bench PCs log epoch seconds, newer ones log ISO strings. Bronze kept
  -- both as text, so the format is detected here and both become TIMESTAMP.
  CASE WHEN r.started_at RLIKE '^[0-9]+$'
       THEN timestamp_seconds(CAST(r.started_at AS BIGINT))
       ELSE to_timestamp(r.started_at) END AS started_at,
  CAST(r.duration_s AS DOUBLE) AS duration_s,
  r.status, r.error_message, r.screenshot_path
FROM dedup r
-- Bench type and build version are joined in once here so every downstream
-- table can split by single vs dual display or by build without repeating joins.
LEFT JOIN bronze_benches b ON r.bench_id = b.bench_id
LEFT JOIN bronze_builds bl ON r.build_id = bl.build_id
WHERE r.rn = 1;

-- Watchdog reboots are their own event type. They matter on their own: a bench
-- that keeps rebooting points at hardware, not at the build or the scripts.
CREATE OR REFRESH MATERIALIZED VIEW silver_watchdog_events
COMMENT "Watchdog reboots, one row per event"
AS
SELECT DISTINCT run_id, bench_id,
  CASE WHEN `at` RLIKE '^[0-9]+$'
       THEN timestamp_seconds(CAST(`at` AS BIGINT))
       ELSE to_timestamp(`at`) END AS rebooted_at,
  reason
FROM bronze_runs
WHERE event = 'watchdog_reboot';
