#!/usr/bin/env python3
"""Regression tests for Isambard service-status parsing."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from isambard_status import PageParser, collect_status


class PageParserTest(unittest.TestCase):
    def test_status_admonitions_and_details_keep_source_order(self) -> None:
        parser = PageParser()
        parser.feed(
            """
            <article class="md-content__inner md-typeset">
              <div class="admonition success">
                <p class="admonition-title">Isambard-AI Phase 2: <em>Restored</em></p>
                <p>Compute work has been resumed. <strong>Check jobs.</strong></p>
              </div>
              <details class="success">
                <summary>Isambard 3 Grace: <em>No Known Issues</em></summary>
                <p>There are no known issues.</p>
              </details>
            </article>
            """
        )

        self.assertEqual(
            parser.statuses,
            [
                {
                    "title": "Isambard-AI Phase 2: Restored",
                    "body": "Compute work has been resumed. Check jobs.",
                    "class": "admonition success",
                },
                {
                    "title": "Isambard 3 Grace: No Known Issues",
                    "body": "There are no known issues.",
                    "class": "success",
                },
            ],
        )

    def test_void_elements_do_not_drop_admonition_or_leak_content(self) -> None:
        parser = PageParser()
        parser.feed(
            """
            <article class="md-content__inner md-typeset">
              <div class="admonition warning">
                <p class="admonition-title">Isambard-AI Phase 2: <em>Degraded</em></p>
                <p>First line<br>Second line <img src="incident.png" alt=""> image<hr>Third line</p>
              </div>
              <details class="success">
                <summary>Grace: <em>No Known Issues</em></summary>
                <p>Everything is normal.<br/>No action is required.<img src="ok.png"/></p>
              </details>
            </article>
            <details class="failure">
              <summary>Outside the article</summary>
              <p>This must not be parsed.</p>
            </details>
            """
        )

        self.assertEqual(
            parser.statuses,
            [
                {
                    "title": "Isambard-AI Phase 2: Degraded",
                    "body": "First line Second line image Third line",
                    "class": "admonition warning",
                },
                {
                    "title": "Grace: No Known Issues",
                    "body": "Everything is normal. No action is required.",
                    "class": "success",
                },
            ],
        )
        self.assertEqual(parser.article_depth, 0)
        self.assertIsNone(parser._status)

    def test_nested_admonition_stays_with_outer_status(self) -> None:
        parser = PageParser()
        parser.feed(
            """
            <article class="md-content__inner md-typeset">
              <div class="admonition warning">
                <p class="admonition-title">Isambard-AI Phase 2: <em>Degraded</em></p>
                <p>Outer incident text.</p>
                <div class="admonition info">
                  <p class="admonition-title">Additional information</p>
                  <p>Inner note text.</p>
                </div>
                <p>Outer follow-up text.</p>
              </div>
              <details class="success">
                <summary>Grace: <em>No Known Issues</em></summary>
                <p>Everything is normal.</p>
              </details>
            </article>
            """
        )

        self.assertEqual(
            parser.statuses,
            [
                {
                    "title": "Isambard-AI Phase 2: Degraded",
                    "body": (
                        "Outer incident text. Additional information Inner note text. "
                        "Outer follow-up text."
                    ),
                    "class": "admonition warning",
                },
                {
                    "title": "Grace: No Known Issues",
                    "body": "Everything is normal.",
                    "class": "success",
                },
            ],
        )
        self.assertEqual(parser.article_depth, 0)
        self.assertIsNone(parser._status)

    def test_nested_details_stays_with_outer_status(self) -> None:
        parser = PageParser()
        parser.feed(
            """
            <article class="md-content__inner md-typeset">
              <details class="warning">
                <summary>Isambard-AI Phase 2: <em>Degraded</em></summary>
                <p>Outer incident text.</p>
                <details class="info">
                  <summary>Additional information</summary>
                  <p>Inner note text.</p>
                </details>
                <p>Outer follow-up text.</p>
              </details>
              <details class="success">
                <summary>Grace: <em>No Known Issues</em></summary>
                <p>Everything is normal.</p>
              </details>
            </article>
            """
        )

        self.assertEqual(
            parser.statuses,
            [
                {
                    "title": "Isambard-AI Phase 2: Degraded",
                    "body": (
                        "Outer incident text. Additional information Inner note text. "
                        "Outer follow-up text."
                    ),
                    "class": "warning",
                },
                {
                    "title": "Grace: No Known Issues",
                    "body": "Everything is normal.",
                    "class": "success",
                },
            ],
        )
        self.assertEqual(parser.article_depth, 0)
        self.assertIsNone(parser._status)

    def test_mixed_nested_status_containers_stay_with_outer_status(self) -> None:
        parser = PageParser()
        parser.feed(
            '<article class="md-content__inner md-typeset">'
            '<div class="admonition warning">'
            '<p class="admonition-title">Outer admonition</p><p>Before.</p>'
            '<details class="info"><summary>Inner details</summary><p>Inner one.</p></details>'
            '<p>After.</p></div>'
            '<details class="warning"><summary>Outer details</summary><p>Before.</p>'
            '<div class="admonition info"><p class="admonition-title">Inner admonition</p>'
            '<p>Inner two.</p></div><p>After.</p></details>'
            '</article>'
        )

        self.assertEqual(
            parser.statuses,
            [
                {
                    "title": "Outer admonition",
                    "body": "Before. Inner details Inner one. After.",
                    "class": "admonition warning",
                },
                {
                    "title": "Outer details",
                    "body": "Before. Inner admonition Inner two. After.",
                    "class": "warning",
                },
            ],
        )
        self.assertEqual(parser.article_depth, 0)
        self.assertIsNone(parser._status)

    def test_table_cells_are_separated_in_admonition_body(self) -> None:
        parser = PageParser()
        parser.feed(
            """
            <article class="md-content__inner md-typeset">
              <div class="admonition warning">
                <p class="admonition-title">Planned outage</p>
                <table><tr><th>Date</th><th>Impact</th></tr><tr><td>2026-09-10</td><td>Downtime</td></tr></table>
              </div>
            </article>
            """
        )

        self.assertEqual(
            parser.statuses,
            [
                {
                    "title": "Planned outage",
                    "body": "Date Impact 2026-09-10 Downtime",
                    "class": "admonition warning",
                }
            ],
        )

    def test_empty_live_parse_keeps_last_known_good_cache(self) -> None:
        cached = {
            "fetched_at": "2026-08-10T08:00:00+00:00",
            "statuses": [
                {
                    "title": "Isambard-AI Phase 2: Degraded",
                    "body": "Last known incident details.",
                    "class": "warning",
                }
            ],
            "maintenance_headers": [],
            "maintenance_rows": [],
        }
        status_html_without_cards = (
            '<article class="md-content__inner md-typeset">'
            "<h1>Redesigned service status</h1>"
            "</article>"
        )
        maintenance_html = '<article class="md-content__inner md-typeset"></article>'

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "isambard-status.json"
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            with patch(
                "isambard_status.fetch",
                side_effect=[status_html_without_cards, maintenance_html],
            ):
                result = collect_status(cache_path=cache_path, force_refresh=True)

            self.assertEqual(result["source"], "cache")
            self.assertTrue(result["stale"])
            self.assertIn("no service status cards", result["warning"])
            self.assertEqual(result["status"], cached)
            self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8")), cached)


if __name__ == "__main__":
    unittest.main()
