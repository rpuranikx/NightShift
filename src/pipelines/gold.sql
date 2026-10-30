-- Nightshift gold layer: the questions people actually ask in the morning.
--
--   Is a bench going bad?            gold_bench_nightly_health
--   Which tests are just flaky?      gold_test_flakiness
--   Did a new build break something? gold_build_regressions
--
-- Each of these maps to one of the three problems planted in the generated data,
-- and the dashboard and morning agent read from here instead of from silver.

-- A "night" is the test session, not the calendar date. Runs start around 10 PM
-- and finish after midnight, so subtracting 12 hours puts the whole session on
-- the date it started.
CREATE OR REFRESH MATERIALIZED VIEW gold_bench_nightly_health
COMMENT "Pass rate and watchdog reboots per bench per night"
AS
WITH results AS (
  SELECT bench_id, display_count, pcm_link,
         to_date(started_at - INTERVAL 12 HOURS) AS night,
         count(*) AS tests,
         count_if(status <> 'PASS') AS failures
  FROM silver_test_results
  GROUP BY ALL
),
reboots AS (
  SELECT bench_id,
         to_date(rebooted_at - INTERVAL 12 HOURS) AS night,
         count(*) AS reboots
  FROM silver_watchdog_events
  GROUP BY ALL
)
SELECT r.bench_id, r.display_count, r.pcm_link, r.night, r.tests, r.failures,
       round(1 - r.failures / r.tests, 4) AS pass_rate,
       coalesce(w.reboots, 0) AS reboots
FROM results r
LEFT JOIN reboots w ON r.bench_id = w.bench_id AND r.night = w.night;

-- Flaky means "fails sometimes, on every build", which is a script problem.
-- The first version flagged any test with a fail rate between 8% and 50%, and
-- that caught about 40 tests that just had a couple of random failures. Requiring
-- the intermittent pattern on at least 4 different builds cut it to the one test
-- that is actually flaky, and it also keeps a single bad build from looking flaky.
CREATE OR REFRESH MATERIALIZED VIEW gold_test_flakiness
COMMENT "Flaky = fails intermittently (8-50%) on at least 4 different builds, so it isn't one bad build"
AS
WITH per_build AS (
  SELECT test_name, suite, build_version,
         count(*) AS runs,
         count_if(status <> 'PASS') / count(*) AS fail_rate
  FROM silver_test_results
  GROUP BY test_name, suite, build_version
)
SELECT test_name, suite,
       sum(runs) AS runs,
       round(avg(fail_rate), 3) AS avg_fail_rate,
       count_if(fail_rate BETWEEN 0.08 AND 0.5) AS builds_intermittent,
       count_if(fail_rate BETWEEN 0.08 AND 0.5) >= 4 AS is_flaky
FROM per_build
GROUP BY test_name, suite;

-- A regression is the opposite pattern: a test that fails on most runs of one
-- build. It's split by display count because hardware variants break differently;
-- averaged together, a build that breaks only dual-display benches would look
-- half-broken everywhere instead of fully broken on the benches it affects.
-- The 5-run minimum keeps a test that ran once or twice from tripping it.
CREATE OR REFRESH MATERIALIZED VIEW gold_build_regressions
COMMENT "Tests that fail on most runs of a build, split by single vs dual display"
AS
SELECT build_version, test_name, display_count,
       count(*) AS runs,
       count_if(status <> 'PASS') AS failures,
       round(count_if(status <> 'PASS') / count(*), 3) AS fail_rate
FROM silver_test_results
GROUP BY build_version, test_name, display_count
HAVING count(*) >= 5 AND count_if(status <> 'PASS') / count(*) >= 0.5;
