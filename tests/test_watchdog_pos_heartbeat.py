"""
tests/test_watchdog_pos_heartbeat.py
Unit tests for scripts/watchdog_pos_heartbeat.py
"""

import os
import sys
import json
import tempfile
from datetime import datetime, time, timedelta, timezone
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.watchdog_pos_heartbeat import (
    is_within_operating_hours,
    parse_last_seen,
    calculate_diff_minutes,
    read_heartbeat_data,
    check_alert_throttling,
    save_alert_state,
    clear_alert_throttle,
    build_alert_message,
    build_test_message,
    run_watchdog_check,
    OPERATING_START,
    OPERATING_END,
)


class TestOperatingHours:
    def test_inside_operating_hours(self):
        assert is_within_operating_hours(time(5, 30)) is True
        assert is_within_operating_hours(time(5, 31)) is True
        assert is_within_operating_hours(time(12, 0)) is True
        assert is_within_operating_hours(time(18, 45)) is True
        assert is_within_operating_hours(time(23, 30)) is True

    def test_outside_operating_hours(self):
        assert is_within_operating_hours(time(5, 29, 59)) is False
        assert is_within_operating_hours(time(5, 0)) is False
        assert is_within_operating_hours(time(23, 30, 1)) is False
        assert is_within_operating_hours(time(23, 31)) is False
        assert is_within_operating_hours(time(0, 0)) is False
        assert is_within_operating_hours(time(1, 0)) is False
        assert is_within_operating_hours(time(3, 0)) is False


class TestParseLastSeen:
    def test_parse_iso_string(self):
        dt = parse_last_seen("2026-09-15T12:00:00")
        assert dt == datetime(2026, 9, 15, 12, 0, 0)

    def test_parse_iso_with_microseconds(self):
        dt = parse_last_seen("2026-09-08T13:19:31.697012")
        assert dt == datetime(2026, 9, 8, 13, 19, 31, 697012)

    def test_parse_iso_with_z(self):
        dt = parse_last_seen("2026-09-15T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parse_iso_with_tz_offset(self):
        dt = parse_last_seen("2026-09-15T12:00:00+07:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parse_datetime_string(self):
        dt = parse_last_seen("2026-09-15 12:00:00")
        assert dt == datetime(2026, 9, 15, 12, 0, 0)

    def test_parse_numeric_timestamp(self):
        ts = 1789462800.0
        expected = datetime.fromtimestamp(ts)
        assert parse_last_seen(ts) == expected
        assert parse_last_seen(int(ts)) == datetime.fromtimestamp(int(ts))
        assert parse_last_seen(str(ts)) == expected

    def test_parse_invalid(self):
        assert parse_last_seen(None) is None
        assert parse_last_seen("") is None
        assert parse_last_seen("   ") is None
        assert parse_last_seen("invalid-date-string") is None


class TestCalculateDiffMinutes:
    def test_calculate_diff_naive(self):
        now = datetime(2026, 9, 15, 12, 50, 0)
        last_seen = datetime(2026, 9, 15, 12, 0, 0)
        diff = calculate_diff_minutes(now, last_seen)
        assert diff == 50.0

    def test_calculate_diff_aware_and_naive(self):
        now = datetime(2026, 9, 15, 12, 50, 0, tzinfo=timezone.utc)
        last_seen = datetime(2026, 9, 15, 12, 0, 0)
        diff = calculate_diff_minutes(now, last_seen)
        assert diff == 50.0


class TestAlertThrottling:
    def test_no_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            throttled, elapsed = check_alert_throttling(state_file, datetime.now())
            assert throttled is False
            assert elapsed is None

    def test_throttled_under_60_minutes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            now = datetime(2026, 9, 15, 12, 30, 0)
            past = now - timedelta(minutes=30)
            save_alert_state(state_file, past, 50.0, past.isoformat())

            throttled, elapsed = check_alert_throttling(state_file, now, throttle_minutes=60)
            assert throttled is True
            assert pytest.approx(elapsed, 0.1) == 30.0

    def test_unthrottled_over_60_minutes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            now = datetime(2026, 9, 15, 12, 30, 0)
            past = now - timedelta(minutes=65)
            save_alert_state(state_file, past, 50.0, past.isoformat())

            throttled, elapsed = check_alert_throttling(state_file, now, throttle_minutes=60)
            assert throttled is False
            assert pytest.approx(elapsed, 0.1) == 65.0

    def test_clear_throttle_on_recovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            now = datetime(2026, 9, 15, 12, 30, 0)
            past = now - timedelta(minutes=20)
            save_alert_state(state_file, past, 50.0, past.isoformat())

            clear_alert_throttle(state_file, now)
            throttled, elapsed = check_alert_throttling(state_file, now, throttle_minutes=60)
            assert throttled is False


class TestWatchdogRunLogic:
    def test_outside_hours_skips_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_file = os.path.join(tmpdir, "hb.json")
            st_file = os.path.join(tmpdir, "st.json")
            # 03:00 morning
            simulated_now = datetime(2026, 9, 15, 3, 0, 0)

            result = run_watchdog_check(
                heartbeat_file=hb_file,
                state_file=st_file,
                now=simulated_now,
                dry_run=True
            )

            assert result["in_operating_hours"] is False
            assert result["alert_triggered"] is False

    def test_inside_hours_healthy_pos(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_file = os.path.join(tmpdir, "hb.json")
            st_file = os.path.join(tmpdir, "st.json")
            simulated_now = datetime(2026, 9, 15, 10, 0, 0)
            recent_seen = simulated_now - timedelta(minutes=15)

            with open(hb_file, "w", encoding="utf-8") as f:
                json.dump({
                    "cafe_ip": "203.0.113.10",
                    "last_seen": recent_seen.isoformat(),
                    "updated_at": recent_seen.strftime("%Y-%m-%d %H:%M:%S")
                }, f)

            result = run_watchdog_check(
                heartbeat_file=hb_file,
                state_file=st_file,
                now=simulated_now,
                dry_run=True
            )

            assert result["in_operating_hours"] is True
            assert result["is_healthy"] is True
            assert result["diff_minutes"] == 15.0
            assert result["alert_triggered"] is False

    def test_inside_hours_stale_pos_triggers_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_file = os.path.join(tmpdir, "hb.json")
            st_file = os.path.join(tmpdir, "st.json")
            simulated_now = datetime(2026, 9, 15, 10, 0, 0)
            stale_seen = simulated_now - timedelta(minutes=55)

            with open(hb_file, "w", encoding="utf-8") as f:
                json.dump({
                    "cafe_ip": "203.0.113.10",
                    "last_seen": stale_seen.isoformat(),
                    "updated_at": stale_seen.strftime("%Y-%m-%d %H:%M:%S")
                }, f)

            result = run_watchdog_check(
                heartbeat_file=hb_file,
                state_file=st_file,
                now=simulated_now,
                dry_run=True
            )

            assert result["in_operating_hours"] is True
            assert result["is_healthy"] is False
            assert result["diff_minutes"] == 55.0
            assert result["alert_triggered"] is True
            assert result["alert_throttled"] is False

    def test_inside_hours_stale_pos_throttled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_file = os.path.join(tmpdir, "hb.json")
            st_file = os.path.join(tmpdir, "st.json")
            simulated_now = datetime(2026, 9, 15, 10, 0, 0)
            stale_seen = simulated_now - timedelta(minutes=60)

            with open(hb_file, "w", encoding="utf-8") as f:
                json.dump({
                    "cafe_ip": "203.0.113.10",
                    "last_seen": stale_seen.isoformat()
                }, f)

            # Pre-populate state with alert 25 minutes ago
            last_alert_time = simulated_now - timedelta(minutes=25)
            save_alert_state(st_file, last_alert_time, 35.0, stale_seen.isoformat())

            result = run_watchdog_check(
                heartbeat_file=hb_file,
                state_file=st_file,
                now=simulated_now,
                dry_run=True
            )

            assert result["is_healthy"] is False
            assert result["alert_triggered"] is False
            assert result["alert_throttled"] is True

    def test_missing_heartbeat_file_triggers_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_file = os.path.join(tmpdir, "non_existent_hb.json")
            st_file = os.path.join(tmpdir, "st.json")
            simulated_now = datetime(2026, 9, 15, 14, 0, 0)

            result = run_watchdog_check(
                heartbeat_file=hb_file,
                state_file=st_file,
                now=simulated_now,
                dry_run=True
            )

            assert result["in_operating_hours"] is True
            assert result["is_healthy"] is False
            assert result["alert_triggered"] is True

    def test_build_alert_message_dynamic_threshold(self):
        now = datetime(2026, 9, 16, 20, 30, 0)
        last_seen = datetime(2026, 9, 16, 16, 15, 2)
        diff_minutes = 255.0
        msg_250 = build_alert_message(diff_minutes, last_seen, "116.96.78.89", now, threshold_minutes=250)
        assert "Quá 250 phút không nhận được tín hiệu Heartbeat" in msg_250
        assert "Thời gian mất kết nối: ~255 phút" in msg_250

        msg_300 = build_alert_message(diff_minutes, last_seen, "116.96.78.89", now, threshold_minutes=300)
        assert "Quá 300 phút không nhận được tín hiệu Heartbeat" in msg_300

