"""Event accounting regressions: never assign a whole session to its start day."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import claude_usage
import codex_usage
from token_history import CodexParser, daily_history


def usage(total):
    return {"input_tokens": total - 2, "output_tokens": 2, "total_tokens": total,
            "cached_input_tokens": total - 4, "reasoning_output_tokens": 1}


def direct(response, total, stamp, cumulative=None):
    payload = {"response_id": response, "thread_id": "thread", "turn_id": "turn", "usage": usage(total)}
    if cumulative is not None:
        payload["thread_token_usage"] = usage(cumulative)
    return {"type": "token_usage_record", "timestamp": stamp, "payload": payload}


def snapshot(total, last, stamp):
    info = {"total_token_usage": usage(total)}
    if last is not None:
        info["last_token_usage"] = usage(last)
    return {"type": "event_msg", "timestamp": stamp,
            "payload": {"type": "token_count", "turn_id": "turn", "info": info}}


class TokenHistoryTests(unittest.TestCase):
    def parse(self, *events):
        parser = CodexParser(Path("fixture.jsonl"))
        for event in events:
            parser.consume(event)
        return parser.records()[0]

    def day(self, stamp):
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date().isoformat()

    def test_cross_day_direct_usage_and_cache_are_not_added_twice(self):
        first, second = "2026-11-01T12:00:00Z", "2026-11-02T12:00:00Z"
        records = self.parse(direct("a", 10, first), direct("b", 20, second))
        history = daily_history(records)
        self.assertEqual([(r['date'], r['total_tokens']) for r in history['days']],
                         [(self.day(first), 10), (self.day(second), 20)])
        self.assertEqual(history['unknown_date_tokens'], 0)
        self.assertEqual(history['days'][1]['cached_input_tokens'], 16)

    def test_direct_and_legacy_snapshot_reconcile_in_either_order(self):
        stamp = "2026-11-01T12:00:00Z"
        for events in ((direct('a', 20, stamp, 20), snapshot(5020, 20, stamp)),
                       (snapshot(5020, 20, stamp), direct('a', 20, stamp, 20))):
            with self.subTest(order=events[0]['type']):
                records = self.parse(*events, direct('b', 30, stamp, 50), snapshot(5050, 30, stamp))
                history = daily_history(records)
                self.assertEqual(history['days'][0]['total_tokens'], 50)
                self.assertEqual(history['unknown_date_tokens'], 5000)
                self.assertEqual(sum(row['usage']['total_tokens'] for row in records), 5050)

    def test_cumulative_delta_and_unknown_baseline(self):
        first, second = "2026-11-01T12:00:00Z", "2026-11-02T12:00:00Z"
        records = self.parse(snapshot(100, None, first), snapshot(130, None, second))
        history = daily_history(records)
        self.assertEqual(history['unknown_date_tokens'], 100)
        self.assertEqual([(r['date'], r['total_tokens']) for r in history['days']], [(self.day(second), 30)])

    def test_counter_reset_and_repeated_snapshots(self):
        stamp = "2026-11-01T12:00:00Z"
        records = self.parse(snapshot(100, 100, stamp), snapshot(100, 100, stamp),
                             snapshot(10, 10, stamp), snapshot(100, 90, stamp))
        self.assertEqual(daily_history(records)['days'][0]['total_tokens'], 200)

    def test_duplicate_response_keeps_earliest_day_and_fullest_counters(self):
        first, second = "2026-11-01T12:00:00Z", "2026-11-02T12:00:00Z"
        events = [direct('a', 10, first), direct('a', 20, second)]
        for ordered in (events, events[::-1]):
            history = daily_history(self.parse(*ordered))
            self.assertEqual(len(history['days']), 1)
            self.assertEqual(history['days'][0]['date'], self.day(first))
            self.assertEqual(history['days'][0]['total_tokens'], 20)

    def test_archived_copy_does_not_double_count_and_rows_ignore_filename_date(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            active = home / 'sessions/2025/01/01/fixture.jsonl'
            archived = home / 'archived_sessions/fixture-copy.jsonl'
            active.parent.mkdir(parents=True)
            archived.parent.mkdir()
            stamp = '2026-11-02T12:00:00Z'
            content = json.dumps(direct('a', 20, stamp)) + '\n'
            active.write_text(content)
            archived.write_text(content)
            result = codex_usage.scan_sessions_metadata(home)
            self.assertEqual(result['final_token_totals_sum']['total_tokens'], 20)
            self.assertEqual(result['daily_usage'][0]['date'], self.day(stamp))
            self.assertEqual(result['duplicate_usage_records_skipped'], 1)
            codex_usage.limit_local_usage_days({'sessions': result}, 1)
            self.assertEqual(result['daily_tokens']['days'][0]['total_tokens'], 20)

    def test_missing_and_invalid_dates_never_get_assigned_to_today(self):
        for stamp in (None, True, 'invalid'):
            history = daily_history(self.parse(direct('a', 20, stamp)))
            self.assertEqual(history['days'], [])
            self.assertEqual(history['unknown_date_tokens'], 20)

    def test_local_day_uses_event_timezone_not_date_prefix(self):
        # Same instant expressed on different calendar dates must share a bucket.
        records = self.parse(direct('a', 10, '2026-11-01T23:30:00-08:00'),
                             direct('b', 20, '2026-11-02T07:30:00Z'))
        self.assertEqual(len(daily_history(records)['days']), 1)
        self.assertEqual(daily_history(records)['days'][0]['total_tokens'], 30)

    def test_claude_dedup_preserves_first_day_and_full_history_survives_row_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            def row(identifier, amount, stamp):
                return {'type': 'assistant', 'timestamp': stamp, 'message': {'id': identifier,
                    'usage': {'input_tokens': amount, 'output_tokens': 2, 'cache_read_input_tokens': 8}}}
            first, second = '2026-11-01T12:00:00Z', '2026-11-02T12:00:00Z'
            (project / 'a.jsonl').write_text(json.dumps(row('a', 10, first)) + '\n')
            (project / 'b.jsonl').write_text('\n'.join(json.dumps(r) for r in
                [row('a', 20, second), row('b', 30, second), row('c', 40, None)]))
            result = claude_usage.aggregate_local_usage(home, 10, 1)
            self.assertEqual(len(result['daily_usage']), 1)
            history = result['daily_tokens']
            self.assertEqual([r['total_tokens'] for r in history['days']], [30, 40])
            self.assertEqual(history['days'][0]['date'], self.day(first))
            self.assertEqual(history['unknown_date_tokens'], 50)
            self.assertEqual(result['token_totals']['total_tokens'], 120)


if __name__ == '__main__':
    unittest.main()
