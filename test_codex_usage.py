from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_usage as codex
from usage_common import CollectionError


class SessionCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.file = self.home / 'sessions/2026/10/05/test.jsonl'
        self.file.parent.mkdir(parents=True)
        codex._SESSION_CACHE.clear()

    def row(self, total):
        return json.dumps({'payload': {'model': 'example-model', 'cwd': '/example',
                          'info': {'total_token_usage': {'total_tokens': total}}}}) + '\n'

    def test_unchanged_files_are_read_once_and_final_cumulative_total_is_used(self):
        self.file.write_text(self.row(10) + self.row(25))
        with patch.object(codex, 'scan_session_file', wraps=codex.scan_session_file) as scan:
            first = codex.scan_sessions_metadata(self.home)
            second = codex.scan_sessions_metadata(self.home)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first['final_token_totals_sum']['total_tokens'], 25)

    def test_append_truncate_replace_and_delete_invalidate_cache(self):
        for content, expected in [(self.row(10), 10), (self.row(10)+self.row(30), 30), (self.row(5), 5)]:
            self.file.write_text(content)
            self.assertEqual(codex.scan_sessions_metadata(self.home)['final_token_totals_sum']['total_tokens'], expected)
        replacement = self.file.with_suffix('.tmp')
        replacement.write_text(self.row(9))
        replacement.replace(self.file)
        self.assertEqual(codex.scan_sessions_metadata(self.home)['final_token_totals_sum']['total_tokens'], 9)
        self.file.unlink()
        result = codex.scan_sessions_metadata(self.home)
        self.assertEqual(result['session_files'], 0)
        self.assertFalse(codex._SESSION_CACHE)

    def test_bad_rows_and_nonfinite_tokens_do_not_discard_valid_history(self):
        self.file.write_text('not-json\n[]\n'+self.row(10)+'\n'+self.row(float('nan')))
        result = codex.scan_sessions_metadata(self.home)
        self.assertGreater(result['parse_or_read_errors'], 0)
        self.assertEqual(result['final_token_totals_sum']['total_tokens'], 10)
        # Non-finite values are never emitted as token totals.
        json.dumps(result, allow_nan=False)

    def test_empty_home_has_empty_statistics(self):
        result = codex.collect_local_usage(self.home, 10)
        self.assertEqual(result['sessions']['session_files'], 0)
        self.assertEqual(result['sessions']['final_token_totals_sum'], {})

    def test_missing_home_raises_message_without_replacing_stderr(self):
        original = sys.stderr
        with self.assertRaisesRegex(CollectionError, 'Codex home not found'):
            codex.collect_local_usage(self.home / 'missing', 10)
        self.assertIs(sys.stderr, original)

    def test_export_output_directory_is_honoured(self):
        target = self.home / 'exports'
        with patch.object(codex, 'export_json', return_value={'ok': True}):
            result = codex.export_report('all', 'json', 10, 30, 7, output_dir=target)
        self.assertEqual(result.parent, target)
        self.assertEqual(json.loads(result.read_text()), {'ok': True})

    def test_cli_export_passes_output_option(self):
        args = codex.build_parser().parse_args(['export', '--output-dir', str(self.home)])
        with patch.object(codex, 'export_report', return_value=self.home / 'report.json') as export, patch('builtins.print'):
            args.func(args)
        self.assertEqual(export.call_args.kwargs['output_dir'], self.home)

    def test_cli_failure_retains_clean_exit_message(self):
        import os
        env = {**os.environ, 'CODEX_HOME': str(self.home / 'missing')}
        result = subprocess.run([sys.executable, '-B', str(Path(codex.__file__)), 'local-usage'],
                                env=env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Codex home not found', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
