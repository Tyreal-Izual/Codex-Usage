from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import native_backend as native
import claude_usage
import claude_usage_statusline as statusline
import usage_reports


class NativeBackendTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.radar = Mock()
        self.backend = native.NativeBackend(sources=frozenset(), cache_dir=Path(self.temp.name), radar=self.radar)
        self.addCleanup(self.backend.close)

    def test_disabled_sources_never_collect(self):
        with patch.object(native, 'collect_report', wraps=native.collect_report), patch.object(native.codex_usage, 'collect_local_usage') as collect:
            result = self.backend.handle({'action': 'report', 'report': 'local-usage'})
        collect.assert_not_called()
        self.assertTrue(result['data']['disabled'])
        self.assertTrue(self.backend.handle({'action': 'radar'})['disabled'])
        self.radar.start.assert_not_called()

    def test_sqlite_failure_is_reported_without_discarding_session_metadata(self):
        home = Path(self.temp.name)
        (home / 'state_5.sqlite').write_bytes(b'not a SQLite database')
        with patch.object(native.codex_usage, 'CODEX_HOME', home):
            self.backend.handle({'action': 'configure', 'sources': ['codex']})
            result = self.backend.handle({'action': 'report', 'report': 'local-usage'})
        self.assertFalse(result['ok'])
        self.assertIn('SQLite:', result['errors'][0]['message'])
        self.assertIn('not a database', result['data']['sqlite_threads']['selected']['error'])
        self.assertEqual(result['data']['sessions']['session_files'], 0)

    def test_configure_validates_and_toggles_worker(self):
        self.backend.handle({'action': 'configure', 'sources': ['radar']})
        self.radar.set_enabled.assert_called_with(True)
        self.radar.start.assert_called_once()
        self.backend.handle({'action': 'configure', 'sources': []})
        self.radar.set_enabled.assert_called_with(False)
        for sources in ('all', ['unknown'], [3]):
            with self.assertRaises(ValueError): self.backend.handle({'action': 'configure', 'sources': sources})

    def test_report_integer_fields_reject_floats_booleans_and_strings(self):
        for key in ('days', 'top'):
            for value in (30.0, 1.5, True, '30'):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'integer'):
                    self.backend.handle({'action': 'report', 'report': 'local-usage', key: value})
        self.assertTrue(self.backend.handle({'action': 'report', 'report': 'local-usage', 'days': 30, 'top': 20})['ok'])

    def test_bad_request_does_not_corrupt_next_response(self):
        incoming = io.StringIO('not-json\n[]\n{"id":true,"action":"hello"}\n{"id":1,"action":"hello"}\n')
        outgoing = io.StringIO()
        native.serve(self.backend, incoming, outgoing)
        replies = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual([r['ok'] for r in replies], [False, False, False, True])
        self.assertEqual(replies[-1]['result']['protocol'], 1)

    def test_settings_respond_while_report_is_blocked(self):
        incoming, outgoing = queue.Queue(), queue.Queue()
        entered, release = threading.Event(), threading.Event()
        reader = Mock(readline=lambda *args: incoming.get(timeout=5))
        writer = Mock(write=lambda line: outgoing.put(json.loads(line)), flush=lambda: None)
        def slow(*args, **kwargs):
            entered.set()
            release.wait(5)
            return {'ok': True}, []
        with patch.object(native, 'collect_report', side_effect=slow):
            worker = threading.Thread(target=native.serve, args=(self.backend, reader, writer))
            worker.start()
            try:
                incoming.put('{"id":1,"action":"report","report":"local-usage"}\n')
                self.assertTrue(entered.wait(2))
                incoming.put('{"id":2,"action":"configure","sources":[]}\n')
                self.assertEqual(outgoing.get(timeout=2)['id'], 2)
                release.set()
                self.assertEqual(outgoing.get(timeout=2)['id'], 1)
            finally:
                release.set()
                incoming.put('')
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_hello_responds_while_two_reports_are_blocked(self):
        incoming, outgoing = queue.Queue(), queue.Queue()
        entered = threading.Barrier(3)
        release = threading.Event()
        reader = Mock(readline=lambda *args: incoming.get(timeout=5))
        writer = Mock(write=lambda line: outgoing.put(json.loads(line)), flush=lambda: None)
        def slow(*args, **kwargs):
            entered.wait(timeout=3)
            release.wait(5)
            return {'ok': True}, []
        with patch.object(native, 'collect_report', side_effect=slow):
            worker = threading.Thread(target=native.serve, args=(self.backend, reader, writer))
            worker.start()
            try:
                incoming.put('{"id":1,"action":"report","report":"local-usage"}\n')
                incoming.put('{"id":2,"action":"report","report":"online-usage"}\n')
                entered.wait(timeout=3)
                incoming.put('{"id":3,"action":"hello"}\n')
                heartbeat = outgoing.get(timeout=2)
                self.assertEqual(heartbeat['id'], 3)
                self.assertEqual(heartbeat['result']['protocol'], 1)
                release.set()
                self.assertEqual({outgoing.get(timeout=3)['id'], outgoing.get(timeout=3)['id']}, {1, 2})
            finally:
                release.set()
                incoming.put('')
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_repeated_online_polls_do_not_block_other_reports_or_start_more_collectors(self):
        incoming, outgoing = queue.Queue(), queue.Queue()
        entered, release = threading.Event(), threading.Event()
        reader = Mock(readline=lambda *args: incoming.get(timeout=5))
        writer = Mock(write=lambda line: outgoing.put(json.loads(line)), flush=lambda: None)
        self.backend.handle({'action': 'configure', 'sources': ['codex', 'claude']})

        def slow():
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test did not release collector')
            return {'endpoints': {}}

        def send(identifier, report, **values):
            incoming.put(json.dumps({'id': identifier, 'action': 'report', 'report': report, **values}) + '\n')

        with (patch.object(native.codex_usage, 'collect_online_usage', side_effect=slow) as online,
              patch.object(native.codex_usage, 'collect_local_usage', return_value={'sessions': {}}),
              patch.object(usage_reports.claude_usage, 'collect_usage', return_value={'local_usage': {}})):
            worker = threading.Thread(target=native.serve, args=(self.backend, reader, writer))
            worker.start()
            try:
                send(1, 'online-usage')
                self.assertTrue(entered.wait(2))
                # A timed-out client can keep polling, including changed display options.
                for identifier in range(2, 14):
                    send(identifier, 'online-usage', days=identifier, top=identifier)
                busy = [outgoing.get(timeout=2) for _ in range(12)]
                self.assertEqual({r['id'] for r in busy}, set(range(2, 14)))
                self.assertTrue(all(not r['ok'] and 'still collecting' in r['error'] for r in busy))
                for identifier, report in ((20, 'local-usage'), (21, 'claude-usage')):
                    send(identifier, report)
                incoming.put('{"id":22,"action":"hello"}\n')
                replies = {r['id']: r for r in (outgoing.get(timeout=2) for _ in range(3))}
                self.assertEqual(set(replies), {20, 21, 22})
                self.assertTrue(all(r['ok'] for r in replies.values()))
                self.assertEqual(online.call_count, 1)
                self.assertFalse(release.is_set())
                release.set()
                self.assertEqual(outgoing.get(timeout=2)['id'], 1)
                send(23, 'online-usage')
                self.assertTrue(outgoing.get(timeout=2)['result']['ok'])
                self.assertEqual(online.call_count, 1)  # The late result populated the shared cache.
            finally:
                release.set()
                incoming.put('')
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_blocked_reports_leave_capacity_for_every_other_report(self):
        incoming, outgoing = queue.Queue(), queue.Queue()
        blocked = native.REPORTS - {'local-usage', 'claude-usage'}
        entered = threading.Barrier(len(blocked) + 1)
        release = threading.Event()
        reader = Mock(readline=lambda *args: incoming.get(timeout=5))
        writer = Mock(write=lambda line: outgoing.put(json.loads(line)), flush=lambda: None)
        def collect(report, *args, **kwargs):
            if report in blocked:
                entered.wait(timeout=3)
                release.wait(5)
            return {'ok': True}, []
        with patch.object(native, 'collect_report', side_effect=collect):
            worker = threading.Thread(target=native.serve, args=(self.backend, reader, writer))
            worker.start()
            try:
                for identifier, report in enumerate(sorted(blocked), 1):
                    incoming.put(json.dumps({'id': identifier, 'action': 'report', 'report': report}) + '\n')
                entered.wait(timeout=3)
                for identifier, report in ((20, 'local-usage'), (21, 'claude-usage')):
                    incoming.put(json.dumps({'id': identifier, 'action': 'report', 'report': report}) + '\n')
                replies = [outgoing.get(timeout=2) for _ in range(2)]
                self.assertEqual({r['id'] for r in replies}, {20, 21})
                self.assertTrue(all(r['ok'] for r in replies))
                self.assertFalse(release.is_set())
            finally:
                release.set()
                incoming.put('')
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_report_slot_is_reusable_after_failure_and_unknown_names_are_rejected(self):
        incoming, outgoing = queue.Queue(), queue.Queue()
        reader = Mock(readline=lambda *args: incoming.get(timeout=5))
        writer = Mock(write=lambda line: outgoing.put(json.loads(line)), flush=lambda: None)
        with patch.object(native, 'collect_report', side_effect=[RuntimeError('fixture'), ({'ok': True}, [])]) as collect:
            worker = threading.Thread(target=native.serve, args=(self.backend, reader, writer))
            worker.start()
            try:
                for identifier, report in ((1, 'unknown'), (2, ['online-usage']), (3, 'online-usage'), (4, 'online-usage')):
                    incoming.put(json.dumps({'id': identifier, 'action': 'report', 'report': report}) + '\n')
                    reply = outgoing.get(timeout=2)
                    self.assertEqual(reply['id'], identifier)
                    self.assertEqual(reply['ok'], identifier == 4)
                self.assertEqual(collect.call_count, 2)
            finally:
                incoming.put('')
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_subprocess_stdout_contains_only_protocol_and_eof_exits(self):
        env = {**os.environ, 'CODEX_HOME': self.temp.name, 'CLAUDE_CONFIG_DIR': self.temp.name}
        result = subprocess.run([sys.executable, '-B', native.__file__, '--sources', 'codex'],
            input='{"id":1,"action":"hello"}\n{"id":2,"action":"report","report":"local-usage"}\n',
            text=True, capture_output=True, env=env, timeout=8, check=True)
        replies = {r['id']: r for r in map(json.loads, result.stdout.splitlines())}
        self.assertEqual(replies[2]['result']['data']['sessions']['session_files'], 0)
        self.assertEqual(replies[1]['result']['protocol'], 1)

    def test_frozen_capture_command_uses_helper_dispatch(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', '/Applications/Usage App.app/helper'):
            command = statusline.command_text()
            self.assertEqual(command, "'/Applications/Usage App.app/helper' --statusline")
            self.assertTrue(statusline.is_ours({'command': command}))
            self.assertEqual(claude_usage.statusline_install_command(), command + ' --install')
            home = Path(self.temp.name)
            (home / 'settings.json').write_text(json.dumps({'statusLine': {'command': command}}))
            self.assertTrue(claude_usage.statusline_is_installed(home))


if __name__ == '__main__':
    unittest.main()
