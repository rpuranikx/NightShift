# Databricks notebook source
# Nightshift 01: generate synthetic overnight test-bench logs.
#
# This stands in for the benches. It's modeled on the hardware-in-the-loop
# benches I work with: single and dual display units, ADB and RS-232 per display,
# a PCM link over Molex or BroadR-Reach, suites that run overnight, and a
# watchdog that reboots the bench when a run hangs. No real company data is used.
#
# Writes to a Unity Catalog volume:
#   benches.csv, builds.json, ground_truth.csv, runs/<date>_<bench>.jsonl
#
# Three realistic problems are planted in the data (see the "Story" comments
# below). The rest of the project has to find them without being told.
#
# The raw logs are deliberately messy (mixed timestamp formats, duplicates,
# missing error messages) because real bench logs are, and a pipeline that only
# works on clean data doesn't prove much. The true cause of every failure goes
# ONLY to ground_truth.csv, never into the logs.

import csv
import json
import os
import random
from datetime import datetime, timedelta

# Fixed seed so every run produces the same data, and the numbers in the README
# can be reproduced exactly.
random.seed(42)

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nightshift")
# "true" regenerates everything. Left at "false", the nightly job skips this step
# once the logs exist, since in a real lab the benches write them, not this notebook.
dbutils.widgets.text("overwrite", "false")

OUT = f"/Volumes/{dbutils.widgets.get('catalog')}/{dbutils.widgets.get('schema')}/raw_logs"
START = datetime(2026, 9, 28)
NIGHTS = 30

# COMMAND ----------
# Benches: the name carries the display count only (SOLO = 1 display, DUO = 2),
# because that's the first thing you need to know when reading a failure.
# Everything else about the bench (PCM link, PC, lab) is a column, not part of the
# name, so names stay short and nobody has to decode them.

def make_benches():
    benches = []
    for kind, displays, count in [("SOLO", 1, 8), ("DUO", 2, 7)]:
        for i in range(1, count + 1):
            benches.append({
                "bench_id": f"{kind}-{i:02d}",
                "display_count": displays,
                "pcm_link": "broadr_reach" if i % 3 == 0 else "molex",
                "pc_hostname": f"HIL-PC-{len(benches) + 1:02d}",
                "lab": "Lab A" if len(benches) < 8 else "Lab B",
                "commissioned_on": (START - timedelta(days=random.randint(90, 900))).date().isoformat(),
            })
    return benches

# COMMAND ----------
# Builds: one new build every few days. v2.4.1 is the bad one (boot-time
# regression on dual-display benches) and is replaced by v2.4.2.

def make_builds():
    schedule = [("v2.3.0", 0), ("v2.3.1", 4), ("v2.4.0", 8),
                ("v2.4.1", 12), ("v2.4.2", 16), ("v2.5.0", 22), ("v2.5.1", 27)]
    return [{
        "build_id": f"B{idx + 1001}",
        "version": version,
        "built_at": (START + timedelta(days=day, hours=17, minutes=random.randint(0, 59))).isoformat(),
        "release_night": day,
    } for idx, (version, day) in enumerate(schedule)]


def build_for_night(builds, night):
    return [b for b in builds if b["release_night"] <= night][-1]

# COMMAND ----------
# Suites and tests. The average seconds per test is chosen so suite lengths match
# real runs: smoke ~40 min, sanity ~90 min. dm and coverage only run some nights,
# like on the real benches, so the number of tests per night varies.

SUITES = {
    "smoke":    (96,  ["boot_to_home", "launcher_loads", "settings_opens", "brightness_slider",
                       "volume_control", "can_heartbeat", "serial_echo", "clock_sync",
                       "touch_calibration", "nav_back_button", "camera_feed", "radio_tuner",
                       "bluetooth_scan", "wifi_scan", "usb_mount", "alerts_banner",
                       "gauge_render", "units_toggle", "language_switch", "night_mode",
                       "screen_timeout", "factory_reset_menu", "about_page", "log_export", "shutdown"]),
    "sanity":   (108, [f"sanity_{area}_{n:02d}" for area in
                       ["display", "can", "serial", "settings", "nav", "media", "connectivity", "power"]
                       for n in range(1, 8)]),
    "bootup":   (120, ["cold_boot_time", "warm_boot_time", "boot_splash", "boot_can_ready", "boot_adb_ready"]),
    "dm":       (60,  [f"dm_diag_{n:02d}" for n in range(1, 21)]),
    "coverage": (45,  [f"coverage_{area}_{n:02d}" for area in
                       ["display", "can", "serial", "settings", "media"] for n in range(1, 13)]),
}

FLAKY_TEST = "brightness_slider"   # story 2: flaky script, every bench

def suites_for_night(night):
    suites = ["smoke", "sanity", "bootup"]
    if night % 7 == 2:
        suites.append("dm")         # mid-week diagnostics
    if night % 7 == 5:
        suites.append("coverage")   # weekend long run
    return suites

# COMMAND ----------
# Failure categories and their error-message templates.

ERRORS = {
    "script": [
        "ElementNotFound: id/{test}",
        "TimeoutError: waiting for screen 'Home' after 30s",
        "AssertionError: expected 'Settings' got 'Settings '",
        "StaleElementReference: {test} element detached",
    ],
    "framework": [
        "HarnessError: session lost during {test}",
        "KeyError: 'display_{display}' in config loader",
        "RuntimeError: result writer closed unexpectedly",
    ],
    "hardware_adb": [
        "adb: device '{serial}' not found",
        "error: device offline ({serial})",
        "adb: protocol fault (couldn't read status): connection reset",
    ],
    "real_defect": [
        "Display {display} brightness unchanged after set to 80%",
        "CAN frame 0x18FEF100 missing for 5s",
        "Serial echo mismatch: sent 'PING' got ''",
    ],
}
# Background mix of failure causes, matching what actually happens on benches:
# most failures are broken scripts, then framework bugs, then ADB/hardware, and
# only a small share are real product defects. That imbalance is the whole reason
# morning triage is tedious, and the triage model has to handle it.
BACKGROUND_MIX = (["script"] * 55 + ["framework"] * 20 +
                  ["hardware_adb"] * 15 + ["real_defect"] * 10)
BACKGROUND_FAIL_RATE = 0.025


def pick_failure(bench, build, test, display, night):
    """Return a failure category, a specific error message, or None if the test passes."""
    serial = f"{bench['pc_hostname'].lower()}-d{display}"

    # Story 3: v2.4.1 regresses boot time on dual-display benches only.
    if test == "cold_boot_time" and build["version"] == "v2.4.1" and bench["display_count"] == 2:
        return "real_defect", f"Boot time {random.uniform(38, 46):.1f}s exceeds limit 30.0s"

    # Story 1: DUO-03's ADB cable on display 2 starts degrading on night 18.
    if bench["bench_id"] == "DUO-03" and display == 2 and night >= 18:
        if random.random() < 0.04 + 0.01 * (night - 18):
            return "hardware_adb", random.choice(ERRORS["hardware_adb"]).format(serial=serial)

    # Story 2: one flaky script on every bench.
    if test == FLAKY_TEST and random.random() < 0.15:
        return "script", "ElementNotFound: id/brightness_slider"

    if random.random() < BACKGROUND_FAIL_RATE:
        category = random.choice(BACKGROUND_MIX)
        msg = random.choice(ERRORS[category]).format(test=test, display=display, serial=serial)
        return category, msg
    return None

# COMMAND ----------
# One bench, one night: a list of log lines plus ground-truth rows.

MESSY_TS_BENCHES = {"SOLO-03", "SOLO-04", "SOLO-05"}   # old PCs log epoch seconds

def fmt_ts(bench, ts):
    if bench["bench_id"] in MESSY_TS_BENCHES:
        return int(ts.timestamp())
    return ts.isoformat()


def make_run(bench, build, night):
    run_id = f"R{night:02d}-{bench['bench_id']}"
    ts = START + timedelta(days=night, hours=22, minutes=random.randint(0, 30))
    lines, truth = [], []
    consecutive_adb = 0

    for suite in suites_for_night(night):
        avg_secs, tests = SUITES[suite]
        for test in tests:
            for display in range(1, bench["display_count"] + 1):
                duration = max(5, random.gauss(avg_secs, avg_secs * 0.2))
                result_id = f"{run_id}-{suite}-{test}-d{display}"
                failure = pick_failure(bench, build, test, display, night)

                line = {
                    "event": "test_result",
                    "result_id": result_id,
                    "run_id": run_id,
                    "bench_id": bench["bench_id"],
                    "build_id": build["build_id"],
                    "suite": suite,
                    "test_name": test,
                    "display": display,
                    "started_at": fmt_ts(bench, ts),
                    "duration_s": round(duration, 1),
                    "status": "PASS",
                    "error_message": None,
                    "screenshot_path": None,
                }
                if failure:
                    category, msg = failure
                    line["status"] = "ERROR" if category in ("framework", "hardware_adb") else "FAIL"
                    # ~10% of failures lose their message (log truncated, crash, etc.)
                    line["error_message"] = None if random.random() < 0.10 else msg
                    line["screenshot_path"] = f"C:/nightshift/screens/{run_id}/{suite}_{test}_d{display}.png"
                    truth.append({"result_id": result_id, "true_category": category})
                    consecutive_adb = consecutive_adb + 1 if category == "hardware_adb" else 0

                lines.append(line)
                ts += timedelta(seconds=duration)

                # Watchdog: after repeated ADB errors the run hangs and the bench reboots.
                if consecutive_adb >= 3:
                    ts += timedelta(minutes=15)
                    lines.append({
                        "event": "watchdog_reboot",
                        "run_id": run_id,
                        "bench_id": bench["bench_id"],
                        "at": fmt_ts(bench, ts),
                        "reason": "no heartbeat for 15 min",
                    })
                    ts += timedelta(minutes=4)   # reboot time
                    consecutive_adb = 0

    # ~1% duplicate lines (result uploader retried)
    dupes = [l for l in lines if random.random() < 0.01]
    lines.extend(dupes)
    return lines, truth

# COMMAND ----------
# Write everything to the volume. The schema and volume come from 00_setup.

def write_all(out=OUT):
    os.makedirs(f"{out}/runs", exist_ok=True)
    benches, builds = make_benches(), make_builds()

    with open(f"{out}/benches.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(benches[0].keys()))
        w.writeheader()
        w.writerows(benches)

    with open(f"{out}/builds.json", "w") as f:
        json.dump([{k: v for k, v in b.items() if k != "release_night"} for b in builds], f, indent=2)

    all_truth, n_lines = [], 0
    for night in range(NIGHTS):
        build = build_for_night(builds, night)
        date = (START + timedelta(days=night)).date().isoformat()
        for bench in benches:
            lines, truth = make_run(bench, build, night)
            all_truth.extend(truth)
            n_lines += len(lines)
            with open(f"{out}/runs/{date}_{bench['bench_id']}.jsonl", "w") as f:
                for line in lines:
                    f.write(json.dumps(line) + "\n")

    with open(f"{out}/ground_truth.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["result_id", "true_category"])
        w.writeheader()
        w.writerows(all_truth)

    print(f"{len(benches)} benches, {len(builds)} builds, {n_lines:,} log lines, {len(all_truth):,} failures")


if dbutils.widgets.get("overwrite") == "true" or not os.path.exists(f"{OUT}/ground_truth.csv"):
    write_all()
else:
    print(f"raw logs already in {OUT}, skipping (set overwrite=true to regenerate)")
