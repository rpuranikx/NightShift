CREATE OR REFRESH MATERIALIZED VIEW workspace.nightshift.gold_bench_nightly_health
COMMENT "Pass rate and watchdog reboots per bench per night"
AS
WITH results AS (
  SELECT bench_id, display_count, pcm_link,
         to_date(started_at - INTERVAL 12 HOURS) AS night,
         count(*) AS tests,
         count_if(status <> 'PASS') AS failures
  FROM workspace.nightshift.silver_test_results
  GROUP BY ALL
),
reboots AS (
  SELECT bench_id,
         to_date(rebooted_at - INTERVAL 12 HOURS) AS night,
         count(*) AS reboots
  FROM workspace.nightshift.silver_watchdog_events
  GROUP BY ALL
)
SELECT r.bench_id, r.display_count, r.pcm_link, r.night, r.tests, r.failures,
       round(1 - r.failures / r.tests, 4) AS pass_rate,
       coalesce(w.reboots, 0) AS reboots
FROM results r
LEFT JOIN reboots w ON r.bench_id = w.bench_id AND r.night = w.night;

CREATE OR REFRESH MATERIALIZED VIEW workspace.nightshift.gold_test_flakiness
COMMENT "Flaky = fails intermittently (8-50%) on at least 4 different builds, so it isn't one bad build"
AS
WITH per_build AS (
  SELECT test_name, suite, build_version,
         count(*) AS runs,
         count_if(status <> 'PASS') / count(*) AS fail_rate
  FROM workspace.nightshift.silver_test_results
  GROUP BY test_name, suite, build_version
)
SELECT test_name, suite,
       sum(runs) AS runs,
       round(avg(fail_rate), 3) AS avg_fail_rate,
       count_if(fail_rate BETWEEN 0.08 AND 0.5) AS builds_intermittent,
       count_if(fail_rate BETWEEN 0.08 AND 0.5) >= 4 AS is_flaky
FROM per_build
GROUP BY test_name, suite;

CREATE OR REFRESH MATERIALIZED VIEW workspace.nightshift.gold_build_regressions
COMMENT "Tests that fail on most runs of a build, split by single vs dual display"
AS
SELECT build_version, test_name, display_count,
       count(*) AS runs,
       count_if(status <> 'PASS') AS failures,
       round(count_if(status <> 'PASS') / count(*), 3) AS fail_rate
FROM workspace.nightshift.silver_test_results
GROUP BY build_version, test_name, display_count
HAVING count(*) >= 5 AND count_if(status <> 'PASS') / count(*) >= 0.5;
