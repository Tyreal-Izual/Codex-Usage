from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import codex_claude_usage_web as web
import isambard_status
import usage_common as common
import usage_sources as sources


class CollectionTest(unittest.TestCase):
    def report(self, report='all', **kwargs):
        return web.collect_report(report, 10, 30, 7, '1d', None, [], False, False, **kwargs)

    def test_concurrent_errors_are_isolated_and_stderr_is_unchanged(self):
        barrier = threading.Barrier(2)
        original = sys.stderr
        def run(name):
            def fail():
                barrier.wait(timeout=3)
                raise common.CollectionError(name)
            return web.safe_collect(name, fail)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ['first error', 'second error']))
        self.assertEqual([r[1]['message'] for r in results], ['first error', 'second error'])
        self.assertIs(sys.stderr, original)

    def test_disabled_sources_do_not_collect(self):
        with patch.object(web.codex_usage, 'collect_resets') as codex, patch.object(web.claude_usage, 'collect_usage') as claude, patch.object(isambard_status, 'collect_status') as status:
            data, errors = self.report(enabled_sources=frozenset())
        self.assertFalse(errors)
        self.assertTrue(all(v.get('disabled') for k, v in data.items() if isinstance(v, dict)))
        for mock in (codex, claude, status): mock.assert_not_called()

    def test_online_source_cache_is_shared_between_report_options(self):
        cache = sources.SourceCache()
        with patch.object(web.codex_usage, 'collect_online_usage', return_value={'endpoints': {}}) as collect:
            self.report('online-usage', source_cache=cache)
            web.collect_report('online-usage', 20, 60, 7, '1d', None, [], False, False, source_cache=cache)
        self.assertEqual(collect.call_count, 1)

    def test_live_isambard_survives_cache_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            status = {'statuses': [{'title': 'OK'}], 'fetched_at': '2026-10-05T00:00:00+00:00'}
            with patch.object(isambard_status, 'fetch', return_value='fixture'), patch.object(isambard_status, 'parse_pages', return_value=status), patch.object(isambard_status, 'atomic_write', side_effect=PermissionError('cache is read-only')):
                result = isambard_status.collect_status(cache_path=Path(directory)/'cache.json')
            self.assertTrue(result['ok'])
            self.assertEqual(result['status'], status)
            self.assertEqual(result['source'], 'live')
            self.assertIn('cache', result['warning'])


class SourceCacheTest(unittest.TestCase):
    def test_expiry_force_and_mutation_isolation(self):
        now = [0]
        cache = sources.SourceCache(lambda: now[0])
        calls = []
        def collect():
            calls.append(1)
            return {'values': [len(calls)]}
        first = cache.get(('one',), collect, 10)
        first['values'].append(99)
        self.assertEqual(cache.get(('one',), collect, 10), {'values': [1]})
        cache.get(('one',), collect, 10, force=True)
        self.assertEqual(len(calls), 2)
        now[0] = 11
        cache.get(('one',), collect, 10)
        self.assertEqual(len(calls), 3)

    def test_same_source_coalesces_but_another_source_can_finish(self):
        cache = sources.SourceCache()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def slow():
            calls.append(1); entered.set()
            self.assertTrue(release.wait(3))
            return {'ok': True}
        with ThreadPoolExecutor(max_workers=3) as pool:
            a = pool.submit(cache.get, ('a',), slow, 60)
            self.assertTrue(entered.wait(3))
            b = pool.submit(cache.get, ('a',), slow, 60)
            c = pool.submit(cache.get, ('c',), lambda: {'fast': True}, 60)
            try:
                self.assertEqual(c.result(1), {'fast': True})
            finally:
                release.set()
            self.assertEqual(a.result(3), b.result(3))
        self.assertEqual(calls, [1])

    def test_exception_releases_source_slot(self):
        cache = sources.SourceCache()
        with self.assertRaises(ValueError):
            cache.get(('a',), lambda: (_ for _ in ()).throw(ValueError('test')), 10)
        self.assertEqual(cache.get(('a',), lambda: 42, 10), 42)


class SetupTest(unittest.TestCase):
    def test_auto_detection_and_explicit_sources(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(Path('/missing/claude'))}), patch.object(sources, 'find_claude_binary', return_value=None):
            self.assertEqual(sources.resolve_sources('auto', Path(directory)), {'codex', 'isambard', 'radar'})
            self.assertEqual(sources.resolve_sources('auto', Path(directory)/'missing'), {'isambard', 'radar'})
            self.assertEqual(sources.resolve_sources('claude,radar', Path(directory)), {'claude', 'radar'})
            with self.assertRaises(ValueError): sources.resolve_sources('typo', Path(directory))

    def test_check_is_read_only_and_never_launches_clients_or_server(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'create_server') as server, patch.object(web.codex_usage, 'load_auth') as auth, patch('subprocess.run') as command, patch('sys.stdout', new_callable=io.StringIO) as output:
            cache = Path(directory)/'uncreated'
            web.main(['--check', '--sources', 'codex', '--cache-dir', str(cache)])
            result = json.loads(output.getvalue())
            self.assertEqual(result['enabled_sources'], ['codex'])
            self.assertFalse(cache.exists())
            server.assert_not_called(); auth.assert_not_called(); command.assert_not_called()

    def test_atomic_json_failure_preserves_previous_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'data.json'
            common.atomic_write_json(target, {'before': True})
            with self.assertRaises(ValueError): common.atomic_write_json(target, {'bad': float('nan')})
            self.assertEqual(json.loads(target.read_text()), {'before': True})
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_cache_path_override(self):
        with patch.dict(os.environ, {'CODEX_USAGE_CACHE_DIR': '~/usage-test-cache'}):
            self.assertEqual(common.cache_directory(), Path.home()/'usage-test-cache')


class LegacyCacheTest(unittest.TestCase):
    def test_default_isambard_cache_uses_legacy_without_writing_or_deleting(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory)/'legacy.json'
            target = Path(directory)/'new/cache.json'
            payload = {'statuses': [{'title': 'fixture'}]}
            legacy.write_text(json.dumps(payload))
            with patch.object(isambard_status, 'DEFAULT_CACHE_PATH', target), patch.object(isambard_status, 'LEGACY_CACHE_PATH', legacy):
                self.assertEqual(isambard_status.load_cache(target), payload)
                self.assertIsNone(isambard_status.load_cache(Path(directory)/'custom.json'))
            self.assertTrue(legacy.exists())
            self.assertFalse(target.exists())

    def test_radar_uses_legacy_only_for_default_path(self):
        import codex_radar
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory)/'legacy.json'
            target = Path(directory)/'new.json'
            legacy.write_text(json.dumps({'schema_version':3,'snapshot':None,'failures':2,'next_attempt_at_epoch':1050}))
            with patch.object(codex_radar, 'DEFAULT_CACHE_PATH', target), patch.object(codex_radar, 'LEGACY_CACHE_PATH', legacy):
                service = codex_radar.RadarService(target, clock=lambda:1000)
                custom = codex_radar.RadarService(Path(directory)/'custom.json', clock=lambda:1000)
            self.assertEqual(service._state['failures'], 2)
            self.assertNotIn('failures', custom._state)
            self.assertFalse(target.exists())
