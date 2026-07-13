#!/usr/bin/env python3
"""
Local web dashboard for Codex and Claude Code usage.

This file deliberately leaves codex_usage.py untouched. It imports the existing
collector functions, exposes them through a localhost-only JSON endpoint by
default, and serves a small dependency-free HTML dashboard that refreshes on a
timer.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import codex_usage
import claude_usage
import isambard_status


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_REFRESH_SECONDS = 15
MAX_TOP = 100
MAX_DAYS = 365


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex &amp; Claude Code Usage Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1110;
      --ink: #eef7f3;
      --muted: #9badac;
      --panel: #121b1a;
      --panel-strong: #172321;
      --field: #0f1817;
      --line: #263534;
      --accent: #46d3b8;
      --accent-soft: #173a34;
      --good: #55d486;
      --warn: #e5b64a;
      --bad: #ff786d;
      --track: #22302e;
      --heat-empty: #1b2725;
      --heat-1: #164237;
      --heat-2: #1d6b55;
      --heat-3: #28a77e;
      --heat-4: #55d486;
      --shadow: 0 16px 38px rgba(0, 0, 0, 0.32);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    button,
    input,
    select {
      font: inherit;
    }

    .shell {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 42px;
    }

    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }

    h1 {
      margin: 0;
      font-size: 28px;
      letter-spacing: 0;
    }

    .subtitle {
      margin: 6px 0 0;
      max-width: 760px;
      color: var(--muted);
    }

    .status {
      min-width: 240px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
      color: var(--muted);
      text-align: right;
    }

    .status strong {
      display: block;
      color: var(--ink);
      font-size: 13px;
      font-weight: 700;
    }

    .toolbar {
      display: grid;
      grid-template-columns: 1.4fr 0.8fr repeat(3, minmax(110px, 0.6fr)) auto auto;
      gap: 10px;
      align-items: end;
      margin-bottom: 18px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }

    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    select,
    input[type="number"] {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--field);
      color: var(--ink);
      padding: 7px 9px;
    }

    .toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      color: var(--ink);
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }

    button {
      min-height: 38px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #06110f;
      padding: 8px 14px;
      font-weight: 800;
      cursor: pointer;
    }

    button:hover {
      filter: brightness(0.96);
    }

    button:disabled {
      cursor: wait;
      opacity: 0.7;
    }

    .notice {
      display: none;
      margin-bottom: 18px;
      padding: 11px 12px;
      border: 1px solid #66302c;
      border-radius: 8px;
      background: #2a1514;
      color: var(--bad);
      white-space: pre-wrap;
    }

    .notice.show {
      display: block;
    }

    .sections {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .section-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      align-items: stretch;
    }

    .section-row--wide {
      grid-template-columns: 1fr;
    }

    section.panel {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
      height: 100%;
    }

    section.panel h2 {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      margin: 0;
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel-strong);
      font-size: 16px;
    }

    .panel-heading-main {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      min-width: 0;
    }

    .panel-heading-title {
      color: var(--ink);
      font-size: 16px;
      font-weight: 700;
    }

    .panel-heading-extras,
    .panel-heading-end-extras {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .panel-heading-end-extras {
      justify-content: flex-end;
      margin-left: auto;
    }

    .panel-heading-extra {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-height: 23px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--field);
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }

    .panel-heading-extra strong {
      color: var(--ink);
      font-weight: 800;
    }

    .panel-heading-extra--good strong {
      color: var(--good);
    }

    .panel-heading-extra--warn strong {
      color: var(--warn);
    }

    .panel-heading-extra--bad strong {
      color: var(--bad);
    }

    .panel-heading-subtitle {
      margin-left: auto;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .panel-heading-end-extras + .panel-heading-subtitle {
      margin-left: 0;
    }

    .panel-body {
      padding: 14px;
    }

    .bars {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .barbox {
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--field);
    }

    .barhead {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      font-weight: 800;
    }

    .bar-meta {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 12px;
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }

    .bar-meta .subtle {
      margin-top: 0;
    }

    .bar-reset {
      flex: 0 0 auto;
      color: var(--ink);
      font-weight: 700;
      text-align: right;
      white-space: nowrap;
    }

    .compact-facts {
      display: flex;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }

    .compact-fact {
      display: inline-flex;
      align-items: baseline;
      gap: 6px;
      padding: 5px 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--field);
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }

    .compact-fact strong {
      color: var(--ink);
      font-size: 12px;
      font-weight: 800;
    }

    .track {
      height: 10px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--track);
    }

    .fill {
      height: 100%;
      width: 0;
      background: var(--accent);
      transition: width 180ms ease;
    }

    .fill.warn {
      background: var(--warn);
    }

    .fill.bad {
      background: var(--bad);
    }

    .subtle {
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }

    .setup-callout {
      margin-top: 12px;
      padding: 12px;
      border: 1px solid #665226;
      border-radius: 8px;
      background: #2a2415;
      color: var(--warn);
    }

    .setup-callout strong {
      display: block;
      margin-bottom: 4px;
    }

    .setup-command {
      display: block;
      overflow-x: auto;
      margin-top: 9px;
      padding: 9px 10px;
      border-radius: 6px;
      background: #101716;
      color: var(--ink);
      white-space: nowrap;
    }

    .kv-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }

    .kv-item {
      min-width: 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--field);
    }

    .kv-label {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }

    .kv-value {
      display: block;
      margin-top: 5px;
      overflow-wrap: anywhere;
      font-size: 14px;
      font-weight: 800;
    }

    .table-wrap {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 0;
      table-layout: fixed;
    }

    .panel--wide .table-wrap table {
      min-width: 560px;
    }

    th,
    td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }

    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      white-space: nowrap;
    }

    td.num {
      font-variant-numeric: tabular-nums;
      text-align: right;
      white-space: nowrap;
    }

    th.num {
      text-align: right;
    }

    .sqlite-table th:nth-child(1),
    .sqlite-table td:nth-child(1) {
      width: 42%;
    }

    .sqlite-table th:nth-child(2),
    .sqlite-table td:nth-child(2) {
      width: 16%;
    }

    .sqlite-table th:nth-child(3),
    .sqlite-table td:nth-child(3) {
      width: 26%;
    }

    .sqlite-table th:nth-child(4),
    .sqlite-table td:nth-child(4) {
      width: 16%;
    }

    .reset-credits-table th:nth-child(1),
    .reset-credits-table td:nth-child(1) {
      width: 7%;
    }

    .reset-credits-table th:nth-child(2),
    .reset-credits-table td:nth-child(2) {
      width: 15%;
    }

    .reset-credits-table th:nth-child(3),
    .reset-credits-table td:nth-child(3) {
      width: 30%;
    }

    .reset-credits-table th:nth-child(4),
    .reset-credits-table td:nth-child(4) {
      width: 18%;
    }

    .reset-credits-table th:nth-child(5),
    .reset-credits-table td:nth-child(5) {
      width: 30%;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 2px 8px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 800;
    }

    .pill.bad {
      background: #3a1d1b;
      color: var(--bad);
    }

    .pill.warn {
      background: #3c3017;
      color: var(--warn);
    }

    .maintenance-link {
      color: var(--accent);
      font-weight: 800;
      text-decoration: none;
    }

    .maintenance-link:hover {
      text-decoration: underline;
    }

    .detail-link {
      display: inline-block;
      margin-top: 12px;
      color: var(--accent);
      font-weight: 800;
      text-decoration: none;
    }

    .detail-link:hover {
      text-decoration: underline;
    }

    .service-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 10px;
    }

    .service-card {
      border: 1px solid var(--line);
      border-left: 4px solid var(--muted);
      border-radius: 8px;
      background: var(--field);
    }

    .service-card.ok {
      border-left-color: var(--good);
    }

    .service-card.warning {
      border-left-color: var(--warn);
    }

    .service-card.outage {
      border-left-color: var(--bad);
    }

    .service-card summary {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
      padding: 11px 12px;
      cursor: pointer;
      font-weight: 800;
    }

    .service-card summary::marker {
      color: var(--muted);
    }

    .service-card summary span:first-child {
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .service-card p {
      margin: 0;
      padding: 0 12px 12px;
      color: var(--muted);
      white-space: pre-line;
    }

    .heatmap-wrap {
      display: grid;
      gap: 12px;
    }

    .heatmap-meta {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .heatmap-scroll {
      overflow-x: auto;
      padding-bottom: 4px;
    }

    .heatmap-grid {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: 13px;
      grid-template-rows: repeat(7, 13px);
      gap: 4px;
      width: max-content;
      min-width: 100%;
    }

    .heat-cell {
      width: 13px;
      height: 13px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 3px;
      background: var(--heat-empty);
    }

    .heat-cell.blank {
      visibility: hidden;
    }

    .heat-1 {
      background: var(--heat-1);
    }

    .heat-2 {
      background: var(--heat-2);
    }

    .heat-3 {
      background: var(--heat-3);
    }

    .heat-4 {
      background: var(--heat-4);
    }

    .heatmap-legend {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }

    .heatmap-legend .heat-cell {
      flex: 0 0 auto;
    }

    .sqlite-stack {
      display: grid;
      gap: 10px;
      margin-bottom: 14px;
    }

    .sqlite-stack-meta {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .sqlite-stack-bar {
      display: flex;
      height: 18px;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--track);
    }

    .sqlite-stack-segment {
      height: 100%;
      min-width: 2px;
    }

    .model-key {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .model-dot {
      flex: 0 0 auto;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--dot-color);
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.12);
    }

    .model-key-text {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .empty {
      padding: 18px;
      color: var(--muted);
      text-align: center;
    }

    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }

    @media (max-width: 900px) {
      header {
        display: grid;
      }

      .status {
        width: 100%;
        text-align: left;
      }

      .toolbar {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .bars {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .kv-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 640px) {
      .shell {
        width: min(100vw - 22px, 1180px);
        padding-top: 16px;
      }

      h1 {
        font-size: 23px;
      }

      .toolbar,
      .bars,
      .kv-grid,
      .section-row {
        grid-template-columns: 1fr;
      }

      .panel-heading-subtitle {
        width: 100%;
        margin-left: 0;
      }

      .bar-meta {
        align-items: flex-start;
      }

      .bar-reset {
        white-space: normal;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1 data-i18n="appTitle">Codex &amp; Claude Code Usage Dashboard</h1>
        <p class="subtitle" data-i18n="subtitle">A local-only view of Codex and Claude Code rate limits and token usage.</p>
      </div>
      <div class="status" aria-live="polite">
        <strong id="status-title" data-i18n="statusStarting">Starting</strong>
        <span id="status-detail" data-i18n="statusWaiting">Waiting for the first refresh.</span>
      </div>
    </header>

    <div class="toolbar">
      <label>
        <span data-i18n="report">Report</span>
        <select id="report">
          <option value="all" data-i18n="reportAll">Overview: Codex + Claude Code</option>
          <option value="codex-usage" data-i18n="reportCodex">Codex Usage</option>
          <option value="claude-usage" data-i18n="reportClaude">Claude Code Usage</option>
          <option value="isambard-status" data-i18n="reportIsambard">Isambard Service Status</option>
        </select>
      </label>
      <label>
        <span data-i18n="language">Language</span>
        <select id="language">
          <option value="en">English</option>
          <option value="zh">中文 Chinese</option>
        </select>
      </label>
      <label>
        <span data-i18n="topRows">Top Rows</span>
        <input id="top" type="number" min="1" max="100" value="10">
      </label>
      <label>
        <span data-i18n="localDays">Local Days</span>
        <input id="days" type="number" min="1" max="365" value="30">
      </label>
      <label>
        <span data-i18n="refreshSec">Refresh Seconds</span>
        <input id="refresh" type="number" min="3" max="3600" value="__DEFAULT_REFRESH__">
      </label>
      <label class="toggle">
        <input id="auto" type="checkbox" checked>
        <span data-i18n="autoRefresh">Auto Refresh</span>
      </label>
      <button id="refresh-now" type="button" data-i18n="refresh">Refresh</button>
    </div>

    <div id="notice" class="notice"></div>
    <div id="sections" class="sections"></div>
  </main>

  <script>
    const state = {
      timer: null,
      loading: false,
      pendingRefresh: false,
      pendingForceRefresh: false,
      lastPayload: null,
      lang: localStorage.getItem("codexUsageLanguage") || ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en")
    };

    const $ = (id) => document.getElementById(id);

    const TEXT = {
      en: {
        appTitle: "Codex & Claude Code Usage Dashboard",
        subtitle: "A local-only view of Codex and Claude Code rate limits and token usage.",
        statusStarting: "Starting",
        statusWaiting: "Waiting for the first refresh.",
        report: "Report",
        reportAll: "Overview: Codex + Claude Code",
        reportCodex: "Codex Usage",
        reportClaude: "Claude Code Usage",
        reportIsambard: "Isambard Service Status",
        language: "Language",
        topRows: "Top Rows",
        localDays: "Local Days",
        refreshSec: "Refresh Seconds",
        autoRefresh: "Auto Refresh",
        refresh: "Refresh",
        refreshing: "Refreshing",
        refreshingDetail: "Reading Codex, Claude Code, and selected online endpoints.",
        upToDate: "Up to Date",
        loadedWithNotes: "Loaded With Notes",
        lastRefresh: "Last Refresh",
        refreshFailed: "Refresh Failed",
        refreshFailedDetail: "See the message below the controls.",
        metric: "Metric",
        value: "Value",
        emptySection: "No data found for this section.",
        noDailyRows: "No daily usage rows found.",
        now: "now",
        lessThanMinute: "<1 min",
        day: "day",
        daysUnit: "days",
        hr: "hr",
        min: "min",
        left: "left",
        sessions: "Sessions",
        output: "Output",
        totalTokensWindow: "Total Tokens in This Window",
        busiestDay: "Busiest Day",
        less: "Less",
        more: "More",
        totalTokens: "Total Tokens",
        resetCredits: "Codex Reset Credits",
        resetSubtitle: "Read-only Codex reset endpoint",
        retrieved: "Retrieved",
        availableResets: "Available Resets",
        creditsReturned: "Credits Returned",
        totalEarnedCount: "Total Earned Count",
        status: "Status",
        expiresLocally: "Expires Locally",
        timeRemaining: "Time Remaining",
        grantedLocally: "Granted Locally",
        localTokenTotals: "Codex Local Token Totals",
        localTokenSubtitle: "Final counters from local session files",
        sqliteModelCounters: "Codex Models",
        sqliteSubtitle: "Local thread database",
        dailyLocalUsage: "Codex Daily Local Usage",
        dayWindow: "Day Window",
        topSessions: "Codex Top Sessions",
        topSessionsSubtitle: "Largest local session counters",
        field: "Field",
        total: "Total",
        model: "Model",
        models: "Models",
        threads: "Threads",
        tokensUsed: "Tokens Used",
        share: "Share",
        date: "Date",
        project: "Project",
        sessionFile: "Session File",
        onlineRateLimits: "Codex Online Rate Limits",
        onlineSubtitle: "Read-only backend endpoints",
        primaryWindow: "Primary Window",
        weeklyWindow: "Weekly Window",
        primaryHint: "Available before the primary limit is reached",
        weeklyHint: "Available before the weekly limit is reached",
        plan: "Plan",
        limitReached: "Limit Reached",
        resetsIn: "Resets In",
        creditsBalance: "Credits Balance",
        hasCredits: "Has Credits",
        profileStatistics: "Codex Profile Statistics",
        profileSubtitle: "Redacted profile data",
        lifetimeTokens: "Lifetime Tokens",
        peakDailyTokens: "Peak Daily Tokens",
        mostUsedReasoningEffort: "Most-Used Reasoning Effort",
        reasoningEffortShare: "Reasoning Effort Share",
        adminApiStatus: "Admin API Status",
        adminApiSubtitle: "Uses OPENAI_ADMIN_KEY when set",
        completionsUsage: "Completions Usage",
        adminApi: "OpenAI Admin API",
        costs: "Costs",
        days: "Days",
        bucketWidth: "Bucket Width",
        usageStatus: "Usage Status",
        costsStatus: "Costs Status",
        error: "Error",
        bucketStart: "Bucket Start",
        group: "Group",
        input: "Input",
        requests: "Requests",
        amount: "Amount",
        currency: "Currency",
        lineItem: "Line Item",
        inputTokens: "Input Tokens",
        cachedInputTokens: "Cached Input Tokens",
        outputTokens: "Output Tokens",
        reasoningOutputTokens: "Reasoning Output Tokens",
        claudeRateLimits: "Claude Code Rate Limits",
        claudeRateSubtitle: "Official statusLine snapshot for Claude.ai subscribers",
        claudeFiveHour: "5-Hour Window",
        claudeWeekly: "7-Day Window",
        claudeFiveHourHint: "Available before the Claude 5-hour limit is reached",
        claudeWeeklyHint: "Available before the Claude weekly limit is reached",
        claudeSnapshotAge: "Snapshot Age",
        claudeSnapshotState: "Snapshot State",
        claudeFresh: "Fresh",
        claudeStale: "Stale",
        claudeCapture: "Status Line Capture",
        claudeInstalled: "Installed",
        claudeNotInstalled: "Not Installed",
        claudeSetupTitle: "Claude rate-limit capture is not ready",
        claudeSetupHint: "Run this command once, then complete one Claude Code response:",
        claudeLocalTokens: "Claude Code Local Token Totals",
        claudeLocalSubtitle: "Deduplicated assistant usage records from local JSONL files",
        cacheCreationTokens: "Cache Creation Tokens",
        cacheReadTokens: "Cache Read Tokens",
        uniqueRequests: "Unique Requests",
        duplicateRowsSkipped: "Duplicate Rows Skipped",
        claudeModels: "Claude Code Models",
        claudeModelsSubtitle: "Token totals grouped by model",
        viewClaudeDetails: "View full Claude Code details →",
        viewCodexDetails: "View full Codex details →",
        claudeProjects: "Claude Code Projects",
        claudeProjectsSubtitle: "Highest local token totals by project",
        claudeDailyUsage: "Claude Code Daily Usage",
        claudeTopSessions: "Claude Code Top Sessions",
        claudeTopSessionsSubtitle: "Largest deduplicated local session totals",
        isambardStatus: "Isambard Service Status",
        isambardSubtitle: "Public service-status and planned-maintenance pages",
        serviceStatus: "Current Service Status",
        plannedMaintenance: "Planned Maintenance",
        fetchedAt: "Source Fetched",
        dataSource: "Data Source",
        liveFetch: "Live Fetch",
        cachedData: "Cached Result",
        cacheAge: "Cache Age",
        maintenanceWindows: "Maintenance Windows",
        viewMaintenance: "View full schedule →",
        operational: "Operational",
        degraded: "Warning",
        outage: "Outage",
        unknown: "Unknown"
      },
      zh: {
        appTitle: "Codex 与 Claude Code 用量仪表盘",
        subtitle: "在同一个本地网页中查看 Codex 与 Claude Code 的限额和 token 用量。",
        statusStarting: "正在启动",
        statusWaiting: "等待第一次刷新。",
        report: "报告",
        reportAll: "总览：Codex + Claude Code",
        reportCodex: "Codex 用量",
        reportClaude: "Claude Code 用量",
        reportIsambard: "Isambard 服务状态",
        language: "语言",
        topRows: "顶部行数",
        localDays: "本地天数",
        refreshSec: "刷新秒数",
        autoRefresh: "自动刷新",
        refresh: "刷新",
        refreshing: "刷新中",
        refreshingDetail: "正在读取 Codex、Claude Code 和选中的在线接口。",
        upToDate: "已更新",
        loadedWithNotes: "已加载，有提示",
        lastRefresh: "上次刷新",
        refreshFailed: "刷新失败",
        refreshFailedDetail: "请查看控件下方的提示信息。",
        metric: "指标",
        value: "值",
        emptySection: "这个区域没有找到数据。",
        noDailyRows: "没有找到每日用量数据。",
        now: "现在",
        lessThanMinute: "少于 1 分钟",
        day: "天",
        daysUnit: "天",
        hr: "小时",
        min: "分钟",
        left: "剩余",
        sessions: "会话",
        output: "输出",
        totalTokensWindow: "此时间窗口内的总 token",
        busiestDay: "最高用量日",
        less: "少",
        more: "多",
        totalTokens: "总 token",
        resetCredits: "Codex 重置额度",
        resetSubtitle: "只读 Codex 重置额度接口",
        retrieved: "获取时间",
        availableResets: "可用重置次数",
        creditsReturned: "返回额度数",
        totalEarnedCount: "累计获得数",
        status: "状态",
        expiresLocally: "本地过期时间",
        timeRemaining: "剩余时间",
        grantedLocally: "本地授予时间",
        localTokenTotals: "Codex 本地 token 总量",
        localTokenSubtitle: "来自本地 session 文件的最终计数",
        sqliteModelCounters: "Codex 模型用量",
        sqliteSubtitle: "本地 thread 数据库",
        dailyLocalUsage: "Codex 每日本地用量",
        dayWindow: "天窗口",
        topSessions: "Codex 最高用量 session",
        topSessionsSubtitle: "本地 token 计数最大的 session",
        field: "字段",
        total: "总计",
        model: "模型",
        models: "模型",
        threads: "线程",
        tokensUsed: "已用 token",
        share: "占比",
        date: "日期",
        project: "项目",
        sessionFile: "Session 文件",
        onlineRateLimits: "Codex 在线速率限制",
        onlineSubtitle: "只读后端接口",
        primaryWindow: "Primary 窗口",
        weeklyWindow: "Weekly 窗口",
        primaryHint: "距离 primary 限制前仍可使用的比例",
        weeklyHint: "距离 weekly 限制前仍可使用的比例",
        plan: "套餐",
        limitReached: "是否达到限制",
        resetsIn: "重置倒计时",
        creditsBalance: "额度余额",
        hasCredits: "是否有额度",
        profileStatistics: "Codex 资料统计",
        profileSubtitle: "已脱敏的资料数据",
        lifetimeTokens: "生命周期 token",
        peakDailyTokens: "单日峰值 token",
        mostUsedReasoningEffort: "最常用推理强度",
        reasoningEffortShare: "推理强度占比",
        adminApiStatus: "Admin API 状态",
        adminApiSubtitle: "设置 OPENAI_ADMIN_KEY 后使用",
        completionsUsage: "Completions 用量",
        adminApi: "OpenAI Admin API",
        costs: "成本",
        days: "天数",
        bucketWidth: "桶宽",
        usageStatus: "用量状态",
        costsStatus: "成本状态",
        error: "错误",
        bucketStart: "桶开始",
        group: "分组",
        input: "输入",
        requests: "请求数",
        amount: "金额",
        currency: "货币",
        lineItem: "项目",
        inputTokens: "输入 token",
        cachedInputTokens: "缓存输入 token",
        outputTokens: "输出 token",
        reasoningOutputTokens: "推理输出 token",
        claudeRateLimits: "Claude Code 用量限制",
        claudeRateSubtitle: "来自 Claude.ai 订阅 statusLine 的官方快照",
        claudeFiveHour: "5 小时窗口",
        claudeWeekly: "7 天窗口",
        claudeFiveHourHint: "距离 Claude 5 小时限制前仍可使用的比例",
        claudeWeeklyHint: "距离 Claude Weekly 限制前仍可使用的比例",
        claudeSnapshotAge: "快照时长",
        claudeSnapshotState: "快照状态",
        claudeFresh: "新鲜",
        claudeStale: "已过期",
        claudeCapture: "statusLine 采集",
        claudeInstalled: "已安装",
        claudeNotInstalled: "未安装",
        claudeSetupTitle: "Claude 限额采集尚未就绪",
        claudeSetupHint: "请运行一次下面的命令，然后让 Claude Code 完成一次回复：",
        claudeLocalTokens: "Claude Code 本地 token 总量",
        claudeLocalSubtitle: "从本地 JSONL 去重得到的 assistant 用量记录",
        cacheCreationTokens: "缓存创建 token",
        cacheReadTokens: "缓存读取 token",
        uniqueRequests: "唯一请求数",
        duplicateRowsSkipped: "跳过的重复记录",
        claudeModels: "Claude Code 模型用量",
        claudeModelsSubtitle: "按模型汇总的 token",
        viewClaudeDetails: "查看完整 Claude Code 详情 →",
        viewCodexDetails: "查看完整 Codex 详情 →",
        claudeProjects: "Claude Code 项目用量",
        claudeProjectsSubtitle: "本地 token 用量最高的项目",
        claudeDailyUsage: "Claude Code 每日用量",
        claudeTopSessions: "Claude Code 最高用量会话",
        claudeTopSessionsSubtitle: "去重后的最大本地会话用量",
        isambardStatus: "Isambard 服务状态",
        isambardSubtitle: "公开服务状态和计划维护页面",
        serviceStatus: "当前服务状态",
        plannedMaintenance: "计划维护",
        fetchedAt: "源数据抓取时间",
        dataSource: "数据来源",
        liveFetch: "实时抓取",
        cachedData: "缓存结果",
        cacheAge: "缓存时长",
        maintenanceWindows: "个维护窗口",
        viewMaintenance: "查看完整维护计划 →",
        operational: "正常",
        degraded: "警告",
        outage: "中断",
        unknown: "未知"
      }
    };

    function t(key) {
      return TEXT[state.lang]?.[key] || TEXT.en[key] || key;
    }

    function applyLanguage() {
      document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
      document.title = t("appTitle");
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        if (node.id === "status-title" || node.id === "status-detail") {
          return;
        }
        node.textContent = t(node.dataset.i18n);
      });
      $("language").value = state.lang;
    }

    function esc(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function get(obj, path, fallback = undefined) {
      let cur = obj;
      for (const key of path) {
        if (cur == null || typeof cur !== "object" || !(key in cur)) {
          return fallback;
        }
        cur = cur[key];
      }
      return cur;
    }

    function asNumber(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    function fmtNumber(value) {
      const number = asNumber(value);
      if (number === null) {
        return value === undefined || value === null || value === "" ? "-" : String(value);
      }
      return Math.round(number).toLocaleString();
    }

    function fmtPercent(value) {
      const number = asNumber(value);
      return number === null ? "-" : `${number.toFixed(1)}%`;
    }

    function fmtDurationSeconds(value) {
      const seconds = asNumber(value);
      if (seconds === null) {
        return "-";
      }
      if (seconds <= 0) {
        return t("now");
      }
      const totalMinutes = Math.floor(seconds / 60);
      if (totalMinutes < 1) {
        return t("lessThanMinute");
      }
      const days = Math.floor(totalMinutes / 1440);
      const hours = Math.floor((totalMinutes % 1440) / 60);
      const minutes = totalMinutes % 60;
      if (days > 0) {
        const dayUnit = state.lang === "zh" ? t("day") : days === 1 ? t("day") : t("daysUnit");
        return `${days} ${dayUnit} ${hours} ${t("hr")} ${minutes} ${t("min")}`;
      }
      if (hours > 0) {
        return `${hours} ${t("hr")} ${minutes} ${t("min")}`;
      }
      return `${minutes} ${t("min")}`;
    }

    function setStatus(title, detail) {
      $("status-title").textContent = title;
      $("status-detail").textContent = detail;
    }

    function showNotice(lines) {
      const notice = $("notice");
      const clean = (lines || []).filter(Boolean);
      notice.textContent = clean.join("\n");
      notice.classList.toggle("show", clean.length > 0);
    }

    function summarizeError(value) {
      if (value == null || value === "") {
        return "";
      }
      if (typeof value === "string") {
        return value;
      }
      if (typeof value !== "object") {
        return String(value);
      }
      if (value.message) {
        return summarizeError(value.message);
      }
      if (value.error) {
        return summarizeError(value.error);
      }
      if (value.reason) {
        return summarizeError(value.reason);
      }
      if (value.body_excerpt) {
        return summarizeError(value.body_excerpt);
      }
      try {
        return JSON.stringify(value);
      } catch {
        return String(value);
      }
    }

    function pill(value, tone = "") {
      return `<span class="pill ${tone}">${esc(value)}</span>`;
    }

    function table(headers, rows, numericIndexes = [], className = "") {
      if (!rows || rows.length === 0) {
        return `<div class="empty">${esc(t("emptySection"))}</div>`;
      }
      const numeric = new Set(numericIndexes);
      const head = headers.map((h, i) => `<th${numeric.has(i) ? " class=\"num\"" : ""}>${esc(h)}</th>`).join("");
      const body = rows.map((row) => {
        return `<tr>${row.map((cell, i) => {
          const cls = numeric.has(i) ? " class=\"num\"" : "";
          return `<td${cls}>${cell}</td>`;
        }).join("")}</tr>`;
      }).join("");
      const cls = className ? ` class="${esc(className)}"` : "";
      return `<div class="table-wrap"><table${cls}><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function kvGrid(rows) {
      if (!rows || rows.length === 0) {
        return `<div class="empty">${esc(t("emptySection"))}</div>`;
      }
      return `
        <div class="kv-grid">
          ${rows.map((row) => `
            <div class="kv-item">
              <span class="kv-label">${row[0]}</span>
              <span class="kv-value">${row[1]}</span>
            </div>`).join("")}
        </div>`;
    }

    function compactFacts(rows) {
      if (!rows || rows.length === 0) {
        return "";
      }
      return `
        <div class="compact-facts">
          ${rows.map((row) => `
            <span class="compact-fact">
              <span>${row[0]}</span>
              <strong>${row[1]}</strong>
            </span>`).join("")}
        </div>`;
    }

    function panel(title, subtitle, body, wide = false, id = title, headerExtras = []) {
      const extras = Array.isArray(headerExtras) ? headerExtras : [];
      const renderHeaderExtras = (items, className) => items.length
        ? `<span class="${className}">${items.map((item) => `
            <span class="panel-heading-extra${item.tone ? ` panel-heading-extra--${esc(item.tone)}` : ""}">
              <span>${esc(item.label || "")}</span>
              <strong>${esc(item.value ?? "-")}</strong>
            </span>`).join("")}</span>`
        : "";
      const leadingExtras = renderHeaderExtras(
        extras.filter((item) => item.position !== "end"),
        "panel-heading-extras"
      );
      const trailingExtras = renderHeaderExtras(
        extras.filter((item) => item.position === "end"),
        "panel-heading-end-extras"
      );
      const html = `
        <section class="panel${wide ? " panel--wide" : ""}">
          <h2>
            <span class="panel-heading-main">
              <span class="panel-heading-title">${esc(title)}</span>
              ${leadingExtras}
            </span>
            ${trailingExtras}
            <span class="panel-heading-subtitle">${esc(subtitle || "")}</span>
          </h2>
          <div class="panel-body">${body}</div>
        </section>`;
      return { html, title: id, wide: Boolean(wide) };
    }

    // Greedy row packing that preserves order: wide panels take a full row,
    // compact panels pair up two-per-row. No dense reflow, so reading order
    // stays intact and there are no floating gaps.
    function packSections(panels) {
      const rows = [];
      let hold = null;
      const flush = (items, wide) => {
        const cls = wide ? "section-row section-row--wide" : "section-row";
        rows.push(`<div class="${cls}">${items.map((p) => p.html).join("")}</div>`);
      };
      for (const p of panels) {
        if (!p) {
          continue;
        }
        if (p.wide) {
          if (hold) {
            flush([hold], false);
            hold = null;
          }
          flush([p], true);
        } else if (hold) {
          flush([hold, p], false);
          hold = null;
        } else {
          hold = p;
        }
      }
      if (hold) {
        flush([hold], false);
      }
      return rows.join("");
    }

    function limitLeft(usedValue) {
      const used = asNumber(usedValue);
      return used === null ? null : Math.max(0, Math.min(100, 100 - used));
    }

    function leftBar(label, usedValue, hint, footer = "") {
      const left = limitLeft(usedValue);
      const percent = left === null ? 0 : left;
      const tone = left !== null && left <= 10 ? "bad" : left !== null && left <= 25 ? "warn" : "";
      const valueText = left === null ? "-" : state.lang === "zh" ? `${t("left")} ${left.toFixed(1)}%` : `${left.toFixed(1)}% ${t("left")}`;
      return `
        <div class="barbox">
          <div class="barhead"><span>${esc(label)}</span><span>${esc(valueText)}</span></div>
          <div class="track"><div class="fill ${tone}" style="width: ${percent}%"></div></div>
          <div class="bar-meta">
            <span class="subtle">${esc(hint || "")}</span>
            ${footer ? `<span class="bar-reset">${esc(footer)}</span>` : ""}
          </div>
        </div>`;
    }

    function hasRateLimitWindow(window) {
      return Boolean(window) && typeof window === "object" && Object.values(window).some((value) => value !== null && value !== undefined);
    }

    function visibleRateLimitWindows(rateLimit) {
      const primary = get(rateLimit, ["primary_window"]);
      const weekly = get(rateLimit, ["secondary_window"]);
      const hasPrimary = hasRateLimitWindow(primary);
      const hasWeekly = hasRateLimitWindow(weekly);

      // When Codex temporarily has only a weekly limit, /wham/usage returns it
      // in primary_window and omits secondary_window. Present that one window
      // as weekly, while retaining the normal mapping when both are available.
      if (hasPrimary && !hasWeekly) {
        return { primary: null, weekly: primary };
      }
      return {
        primary: hasPrimary ? primary : null,
        weekly: hasWeekly ? weekly : null
      };
    }

    function parseLocalDate(value) {
      const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!match) {
        return null;
      }
      return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    }

    function dateKey(date) {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function addDays(date, days) {
      const next = new Date(date);
      next.setDate(next.getDate() + days);
      return next;
    }

    function heatLevel(total, maxTotal) {
      const value = asNumber(total) || 0;
      if (value <= 0 || !maxTotal) {
        return 0;
      }
      const ratio = value / maxTotal;
      if (ratio <= 0.25) {
        return 1;
      }
      if (ratio <= 0.5) {
        return 2;
      }
      if (ratio <= 0.75) {
        return 3;
      }
      return 4;
    }

    function dailyHeatmap(daily) {
      if (!Array.isArray(daily) || daily.length === 0) {
        return `<div class="empty">${esc(t("noDailyRows"))}</div>`;
      }
      const rows = daily
        .filter((row) => parseLocalDate(row.date))
        .sort((a, b) => parseLocalDate(a.date) - parseLocalDate(b.date));
      if (rows.length === 0) {
        return `<div class="empty">${esc(t("noDailyRows"))}</div>`;
      }
      const byDate = new Map(rows.map((row) => [row.date, row]));
      const totals = rows.map((row) => asNumber(row.total_tokens) || 0);
      const maxTotal = Math.max(...totals, 0);
      const totalTokens = totals.reduce((sum, value) => sum + value, 0);
      const busiest = rows.reduce((best, row) => {
        const current = asNumber(row.total_tokens) || 0;
        const previous = asNumber(best.total_tokens) || 0;
        return current > previous ? row : best;
      }, rows[0]);
      const start = parseLocalDate(rows[0].date);
      const end = parseLocalDate(rows[rows.length - 1].date);
      const cells = [];
      for (let i = 0; i < start.getDay(); i += 1) {
        cells.push(`<span class="heat-cell blank" aria-hidden="true"></span>`);
      }
      for (let day = start; day <= end; day = addDays(day, 1)) {
        const key = dateKey(day);
        const row = byDate.get(key) || { date: key, sessions: 0, total_tokens: 0 };
        const total = asNumber(row.total_tokens) || 0;
        const level = heatLevel(total, maxTotal);
        const title = `${key}: ${fmtNumber(total)} ${t("totalTokens")}, ${fmtNumber(row.sessions || 0)} ${t("sessions")}`;
        cells.push(`<span class="heat-cell heat-${level}" title="${esc(title)}" aria-label="${esc(title)}"></span>`);
      }
      return `
        <div class="heatmap-wrap">
          <div class="heatmap-meta">
            <span>${esc(fmtNumber(totalTokens))} ${esc(t("totalTokensWindow"))}</span>
            <span>${esc(t("busiestDay"))}: ${esc(busiest.date || "-")} (${esc(fmtNumber(busiest.total_tokens))})</span>
          </div>
          <div class="heatmap-scroll">
            <div class="heatmap-grid">${cells.join("")}</div>
          </div>
          <div class="heatmap-legend">
            <span>${esc(t("less"))}</span>
            <span class="heat-cell heat-0"></span>
            <span class="heat-cell heat-1"></span>
            <span class="heat-cell heat-2"></span>
            <span class="heat-cell heat-3"></span>
            <span class="heat-cell heat-4"></span>
            <span>${esc(t("more"))}</span>
          </div>
        </div>`;
    }

    const MODEL_COLORS = [
      "#55d486",
      "#46d3b8",
      "#69a7ff",
      "#c58cff",
      "#f0b45c",
      "#ff7a90",
      "#8bd36f",
      "#55c7f0",
      "#d4d46a",
      "#f08be8"
    ];

    function modelColor(index) {
      return MODEL_COLORS[index % MODEL_COLORS.length];
    }

    function sqliteModelKey(model, index) {
      const color = modelColor(index);
      return `
        <span class="model-key" title="${esc(model || "-")}">
          <span class="model-dot" style="--dot-color: ${color}"></span>
          <span class="model-key-text">${esc(model || "-")}</span>
        </span>`;
    }

    function sqliteModelStack(sqliteModels) {
      if (!Array.isArray(sqliteModels) || sqliteModels.length === 0) {
        return "";
      }
      const rows = sqliteModels.map((row, index) => ({
        model: row.model || "-",
        tokens: asNumber(row.tokens_used) || 0,
        color: modelColor(index)
      }));
      const total = rows.reduce((sum, row) => sum + row.tokens, 0);
      if (total <= 0) {
        return "";
      }
      const segments = rows.map((row) => {
        const share = row.tokens / total * 100;
        const title = `${row.model}: ${fmtNumber(row.tokens)} ${t("tokensUsed")} (${fmtPercent(share)})`;
        return `<span class="sqlite-stack-segment" style="width: ${share}%; background: ${row.color}" title="${esc(title)}" aria-label="${esc(title)}"></span>`;
      }).join("");
      return `
        <div class="sqlite-stack">
          <div class="sqlite-stack-meta">
            <span>${esc(fmtNumber(total))} ${esc(t("tokensUsed"))}</span>
            <span>${esc(rows.length)} ${esc(t("models"))}</span>
          </div>
          <div class="sqlite-stack-bar">${segments}</div>
        </div>`;
    }

    function modelTokenStack(rows) {
      if (!Array.isArray(rows)) {
        return "";
      }
      return sqliteModelStack(rows.map((row) => ({
        model: row.model || "-",
        tokens_used: asNumber(row.total_tokens) || 0
      })));
    }

    function splitSections(data, report) {
      return {
        resets: ["all", "codex-usage"].includes(report) ? data?.reset_credits : (report === "resets" ? data : null),
        local: ["all", "codex-usage"].includes(report) ? data?.local_usage : (report === "local-usage" ? data : null),
        online: ["all", "codex-usage"].includes(report) ? data?.online_usage : (report === "online-usage" ? data : null),
        claude: report === "all" ? data?.claude_usage : (report === "claude-usage" ? data : null),
        api: report === "all" ? data?.api_usage : (report === "codex-usage" ? data?.api_usage : (report === "api-usage" ? data : null)),
        isambard: report === "all" ? data?.isambard_status : (report === "isambard-status" ? data : null)
      };
    }

    function usageFieldLabel(field) {
      return {
        input_tokens: t("inputTokens"),
        cached_input_tokens: t("cachedInputTokens"),
        output_tokens: t("outputTokens"),
        reasoning_output_tokens: t("reasoningOutputTokens"),
        cache_creation_input_tokens: t("cacheCreationTokens"),
        cache_read_input_tokens: t("cacheReadTokens"),
        total_tokens: t("totalTokens")
      }[field] || field.replaceAll("_", " ");
    }

    function renderResets(resets) {
      if (!resets) {
        return [];
      }
      const rows = (Array.isArray(resets.credits) ? resets.credits : []).map((credit, index) => {
        const tone = credit.status === "available" ? "" : credit.status === "expired" ? "bad" : "warn";
        return [
          esc(index + 1),
          pill(credit.status || "unknown", tone),
          esc(credit.expires_at_local || "-"),
          esc(credit.time_remaining || "-"),
          esc(credit.granted_at_local || "-")
        ];
      });
      const overview = table([t("metric"), t("value")], [
        [esc(t("retrieved")), esc(resets.retrieved_at_local || "-")],
        [esc(t("availableResets")), esc(fmtNumber(resets.available_count))],
        [esc(t("creditsReturned")), esc(fmtNumber(resets.credits_returned))],
        [esc(t("totalEarnedCount")), esc(fmtNumber(resets.total_earned_count))]
      ]);
      const credits = table(["#", t("status"), t("expiresLocally"), t("timeRemaining"), t("grantedLocally")], rows, [], "reset-credits-table");
      return [panel(t("resetCredits"), t("resetSubtitle"), overview + credits, true)];
    }

    function renderLocal(local, showDetailsLink = false) {
      if (!local) {
        return [];
      }
      const sessions = local.sessions || {};
      const totals = sessions.final_token_totals_sum || {};
      const daily = Array.isArray(sessions.daily_usage) ? sessions.daily_usage : [];
      const topSessions = Array.isArray(sessions.top_sessions_by_total_tokens) ? sessions.top_sessions_by_total_tokens : [];
      const sqliteModels = get(local, ["sqlite_threads", "selected", "by_model"], []);

      const tokenRows = ["input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"]
        .map((field) => [esc(usageFieldLabel(field)), esc(fmtNumber(totals[field]))]);
      const topRows = topSessions.map((item) => [
        esc(item.date || "-"),
        esc(item.model || "-"),
        esc(fmtNumber(get(item, ["usage", "total_tokens"]))),
        esc(fmtNumber(get(item, ["usage", "output_tokens"]))),
        esc(item.project || "-"),
        `<span class="mono">${esc(item.session_file || "-")}</span>`
      ]);
      const sqliteTotal = Array.isArray(sqliteModels)
        ? sqliteModels.reduce((sum, row) => sum + (asNumber(row.tokens_used) || 0), 0)
        : 0;
      const sqliteRows = Array.isArray(sqliteModels) ? sqliteModels.map((row, index) => [
        sqliteModelKey(row.model || "-", index),
        esc(fmtNumber(row.threads)),
        esc(fmtNumber(row.tokens_used)),
        esc(fmtPercent(sqliteTotal > 0 ? (asNumber(row.tokens_used) || 0) / sqliteTotal * 100 : null))
      ]) : [];
      const detailsLink = showDetailsLink
        ? `<a class="detail-link" href="/?report=codex-usage">${esc(t("viewCodexDetails"))}</a>`
        : "";

      return [
        panel(t("localTokenTotals"), t("localTokenSubtitle"), table([t("field"), t("total")], tokenRows, [1]), false, "codex-totals"),
        panel(t("sqliteModelCounters"), t("sqliteSubtitle"), sqliteModelStack(sqliteModels) + table([t("model"), t("threads"), t("tokensUsed"), t("share")], sqliteRows, [1, 2, 3], "sqlite-table") + detailsLink, false, "codex-models"),
        panel(t("dailyLocalUsage"), `${daily.length} ${t("dayWindow")}`, dailyHeatmap(daily), false, "daily"),
        panel(t("topSessions"), t("topSessionsSubtitle"), table([t("date"), t("model"), t("total"), t("output"), t("project"), t("sessionFile")], topRows, [2, 3]), true, "codex-sessions")
      ];
    }

    function renderOnline(online) {
      if (!online) {
        return [];
      }
      const rate = get(online, ["endpoints", "rate_limit_status", "data"], {});
      const profile = get(online, ["endpoints", "profile", "data"], {});
      const rateLimit = get(rate, ["rate_limit"], {});
      const windows = visibleRateLimitWindows(rateLimit);
      const limitReached = get(rateLimit, ["limit_reached"], "-");
      const headerExtras = [
        { label: t("plan"), value: rate.plan_type || "-" },
        {
          label: t("limitReached"),
          value: limitReached,
          tone: limitReached === true ? "bad" : limitReached === false ? "good" : ""
        },
        { label: t("creditsBalance"), value: fmtNumber(get(rate, ["credits", "balance"])), position: "end" },
        { label: t("hasCredits"), value: get(rate, ["credits", "has_credits"], "-"), position: "end" }
      ];
      const stats = profile.stats || {};
      const profileRows = [
        [esc(t("lifetimeTokens")), esc(fmtNumber(stats.lifetime_tokens))],
        [esc(t("peakDailyTokens")), esc(fmtNumber(stats.peak_daily_tokens))],
        [esc(t("mostUsedReasoningEffort")), esc(stats.most_used_reasoning_effort || "-")],
        [esc(t("reasoningEffortShare")), esc(fmtPercent(stats.most_used_reasoning_effort_percentage))]
      ];
      const primaryReset = `${t("resetsIn")} ${fmtDurationSeconds(windows.primary ? windows.primary.reset_after_seconds : undefined)}`;
      const weeklyReset = `${t("resetsIn")} ${fmtDurationSeconds(windows.weekly ? windows.weekly.reset_after_seconds : undefined)}`;
      const bars = `<div class="bars">${leftBar(t("primaryWindow"), windows.primary ? windows.primary.used_percent : undefined, t("primaryHint"), primaryReset)}${leftBar(t("weeklyWindow"), windows.weekly ? windows.weekly.used_percent : undefined, t("weeklyHint"), weeklyReset)}</div>`;
      return [
        panel(t("onlineRateLimits"), t("onlineSubtitle"), bars, true, "codex-rate", headerExtras),
        panel(t("profileStatistics"), t("profileSubtitle"), table([t("metric"), t("value")], profileRows, [1]), false, "profile")
      ];
    }

    function renderClaude(claude, showDetailsLink = false) {
      if (!claude) {
        return [];
      }
      const rate = claude.rate_limits || {};
      const local = claude.local_usage || {};
      const fiveHour = rate.five_hour || null;
      const sevenDay = rate.seven_day || null;
      const headerExtras = [
        { label: t("claudeSnapshotAge"), value: fmtDurationSeconds(rate.age_seconds) },
        {
          label: t("claudeSnapshotState"),
          value: rate.available ? (rate.stale ? t("claudeStale") : t("claudeFresh")) : t("unknown"),
          position: "end",
          tone: rate.available && !rate.stale ? "good" : "warn"
        },
        {
          label: t("claudeCapture"),
          value: rate.capture_installed ? t("claudeInstalled") : t("claudeNotInstalled"),
          position: "end",
          tone: rate.capture_installed ? "good" : "warn"
        }
      ];
      const planValue = rate.plan_type || rate.plan;
      if (planValue !== undefined && planValue !== null && planValue !== "") {
        headerExtras.push({ label: t("plan"), value: planValue });
      }
      if (rate.limit_reached !== undefined && rate.limit_reached !== null) {
        headerExtras.push({ label: t("limitReached"), value: rate.limit_reached });
      }
      const setup = rate.available && rate.capture_installed ? "" : `
        <div class="setup-callout">
          <strong>${esc(t("claudeSetupTitle"))}</strong>
          <span>${esc(t("claudeSetupHint"))}</span>
          <code class="setup-command mono">${esc(rate.install_command || "python3 claude_usage_statusline.py --install")}</code>
        </div>`;
      const fiveHourReset = `${t("resetsIn")} ${fmtDurationSeconds(fiveHour?.reset_after_seconds)}`;
      const sevenDayReset = `${t("resetsIn")} ${fmtDurationSeconds(sevenDay?.reset_after_seconds)}`;
      const bars = `<div class="bars">${leftBar(t("claudeFiveHour"), fiveHour?.used_percentage, t("claudeFiveHourHint"), fiveHourReset)}${leftBar(t("claudeWeekly"), sevenDay?.used_percentage, t("claudeWeeklyHint"), sevenDayReset)}</div>`;

      const totals = local.token_totals || {};
      const tokenRows = ["input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "total_tokens"]
        .map((field) => [esc(usageFieldLabel(field)), esc(fmtNumber(totals[field]))]);
      const localMeta = kvGrid([
        [esc(t("uniqueRequests")), esc(fmtNumber(local.unique_usage_records))],
        [esc(t("sessions")), esc(fmtNumber(local.session_files))],
        [esc(t("duplicateRowsSkipped")), esc(fmtNumber(local.duplicate_usage_records_skipped))]
      ]);

      const models = Array.isArray(local.by_model) ? local.by_model : [];
      const modelTotal = models.reduce((sum, row) => sum + (asNumber(row.total_tokens) || 0), 0);
      const modelRows = models.map((row, index) => [
        sqliteModelKey(row.model || "-", index),
        esc(fmtNumber(row.requests)),
        esc(fmtNumber(row.total_tokens)),
        esc(fmtPercent(modelTotal > 0 ? (asNumber(row.total_tokens) || 0) / modelTotal * 100 : null))
      ]);

      const projects = Array.isArray(local.by_project) ? local.by_project : [];
      const projectRows = projects.map((row) => [
        `<span class="mono">${esc(row.project || "-")}</span>`,
        esc(fmtNumber(row.requests)),
        esc(fmtNumber(row.input_tokens)),
        esc(fmtNumber(row.output_tokens)),
        esc(fmtNumber(row.total_tokens))
      ]);

      const daily = Array.isArray(local.daily_usage) ? local.daily_usage : [];
      const topSessions = Array.isArray(local.top_sessions) ? local.top_sessions : [];
      const topRows = topSessions.map((item) => [
        esc(item.date || "-"),
        esc(Array.isArray(item.models) ? item.models.join(", ") : "-"),
        esc(fmtNumber(item.requests)),
        esc(fmtNumber(get(item, ["usage", "total_tokens"]))),
        esc(fmtNumber(get(item, ["usage", "output_tokens"]))),
        esc(item.project || "-"),
        `<span class="mono">${esc(item.session_file || "-")}</span>`
      ]);
      const detailsLink = showDetailsLink
        ? `<a class="detail-link" href="/?report=claude-usage">${esc(t("viewClaudeDetails"))}</a>`
        : "";

      return [
        panel(t("claudeRateLimits"), t("claudeRateSubtitle"), bars + setup, true, "claude-rate", headerExtras),
        panel(t("claudeLocalTokens"), t("claudeLocalSubtitle"), localMeta + table([t("field"), t("total")], tokenRows, [1]), false, "claude-totals"),
        panel(t("claudeModels"), t("claudeModelsSubtitle"), modelTokenStack(models) + table([t("model"), t("requests"), t("total"), t("share")], modelRows, [1, 2, 3]) + detailsLink, false, "claude-models"),
        panel(t("claudeDailyUsage"), `${daily.length} ${t("dayWindow")}`, dailyHeatmap(daily), false, "claude-daily"),
        panel(t("claudeProjects"), t("claudeProjectsSubtitle"), table([t("project"), t("requests"), t("input"), t("output"), t("total")], projectRows, [1, 2, 3, 4]), true, "claude-projects"),
        panel(t("claudeTopSessions"), t("claudeTopSessionsSubtitle"), table([t("date"), t("model"), t("requests"), t("total"), t("output"), t("project"), t("sessionFile")], topRows, [2, 3, 4]), true, "claude-sessions")
      ];
    }

    function renderApiUsage(api) {
      if (!api) {
        return [];
      }
      const usageRows = get(api, ["usage", "rows"], []);
      const costRows = get(api, ["costs", "rows"], []);
      const usageTableRows = Array.isArray(usageRows) ? usageRows
        .slice()
        .sort((a, b) => (asNumber(b.total_tokens) || 0) - (asNumber(a.total_tokens) || 0))
        .map((row) => [
          esc(row.start_time_local || "-"),
          esc(row.model || row.project_id || row.api_key_id || "(all)"),
          esc(fmtNumber(row.input_tokens)),
          esc(fmtNumber(row.output_tokens)),
          esc(fmtNumber(row.total_tokens)),
          esc(fmtNumber(row.num_model_requests))
        ]) : [];
      const costTableRows = Array.isArray(costRows) ? costRows
        .slice()
        .sort((a, b) => (asNumber(b.amount) || 0) - (asNumber(a.amount) || 0))
        .map((row) => [
          esc(row.start_time_local || "-"),
          esc(row.line_item || row.project_id || row.api_key_id || "(all)"),
          esc(row.amount ?? "-"),
          esc((row.currency || "-").toUpperCase())
        ]) : [];
      const statusRows = [
        [esc(t("retrieved")), esc(api.retrieved_at_local || "-")],
        [esc(t("days")), esc(fmtNumber(api.days))],
        [esc(t("bucketWidth")), esc(api.bucket_width || "-")],
        [esc(t("usageStatus")), esc(get(api, ["usage", "ok"], false) ? "ok" : "error")],
        [esc(t("costsStatus")), esc(get(api, ["costs", "skipped"], false) ? "skipped" : (get(api, ["costs", "ok"], false) ? "ok" : "error"))],
        [esc(t("error")), esc(api.error || get(api, ["usage", "error", "error"], "") || "")]
      ];
      return [
        panel(t("adminApiStatus"), t("adminApiSubtitle"), table([t("metric"), t("value")], statusRows)),
        panel(t("completionsUsage"), t("adminApi"), table([t("bucketStart"), t("group"), t("input"), t("output"), t("total"), t("requests")], usageTableRows, [2, 3, 4, 5]), true),
        panel(t("costs"), t("adminApi"), table([t("bucketStart"), t("group"), t("amount"), t("currency")], costTableRows, [2]), true)
      ];
    }

    function isambardStatusKind(item) {
      const sourceClass = String(item?.class || "").toLowerCase();
      const title = String(item?.title || "").toLowerCase();
      if (sourceClass.includes("success") || title.includes("no known issue")) {
        return "ok";
      }
      if (sourceClass.includes("warning") || title.includes("degraded") || title.includes("at risk")) {
        return "warning";
      }
      if (sourceClass.includes("failure") || title.includes("outage")) {
        return "outage";
      }
      return "unknown";
    }

    function isambardStatusLabel(kind) {
      return {
        ok: t("operational"),
        warning: t("degraded"),
        outage: t("outage"),
        unknown: t("unknown")
      }[kind] || t("unknown");
    }

    function renderIsambard(isambard) {
      if (!isambard) {
        return [];
      }
      const snapshot = isambard.status || {};
      const statuses = Array.isArray(snapshot.statuses) ? snapshot.statuses : [];
      const source = isambard.source === "live" ? "live" : "cache";
      const rows = Array.isArray(snapshot.maintenance_rows) ? snapshot.maintenance_rows : [];
      const sourceRows = [
        [esc(t("fetchedAt")), esc(snapshot.fetched_at || "-")],
        [esc(t("dataSource")), esc(source === "live" ? t("liveFetch") : t("cachedData"))]
      ];
      if (source === "cache") {
        sourceRows.push([esc(t("cacheAge")), esc(fmtDurationSeconds(isambard.cache_age_seconds))]);
      }
      sourceRows.push([
        esc(t("plannedMaintenance")),
        `<a class="maintenance-link" href="/isambard-maintenance">${esc(`${fmtNumber(rows.length)} ${t("maintenanceWindows")}`)} · ${esc(t("viewMaintenance"))}</a>`
      ]);
      const statusCards = statuses.map((item) => {
        const kind = isambardStatusKind(item);
        const tone = kind === "ok" ? "" : kind === "outage" ? "bad" : "warn";
        return `
          <details class="service-card ${esc(kind)}">
            <summary>
              <span>${esc(item.title || "-")}</span>
              ${pill(isambardStatusLabel(kind), tone)}
            </summary>
            <p>${esc(item.body || t("emptySection"))}</p>
          </details>`;
      }).join("");
      const cards = statusCards || `<div class="empty">${esc(t("emptySection"))}</div>`;

      return [
        panel(
          t("isambardStatus"),
          t("isambardSubtitle"),
          kvGrid(sourceRows) + `<div class="subtle">${esc(t("serviceStatus"))}</div><div class="service-cards">${cards}</div>`,
          true
        )
      ];
    }

    function render(payload) {
      const report = payload.report;
      const data = payload.data || {};
      const sections = splitSections(data, report);
      sections.retrieved = data.retrieved_at_local || payload.served_at_local || "-";

      const warnings = [];
      if (Array.isArray(payload.errors)) {
        payload.errors.forEach((item) => warnings.push(`${item.section || "report"}: ${item.message || item}`));
      }
      for (const [name, sectionData] of Object.entries(sections)) {
        if (name === "retrieved" || !sectionData || typeof sectionData !== "object") {
          continue;
        }
        if (sectionData.ok === false) {
          warnings.push(`${name}: ${summarizeError(sectionData.error || "not available")}`);
        }
        if (sectionData.warning) {
          warnings.push(`${name}: ${summarizeError(sectionData.warning)}`);
        }
        if (sectionData.endpoints && typeof sectionData.endpoints === "object") {
          for (const [endpointName, endpoint] of Object.entries(sectionData.endpoints)) {
            if (endpoint && endpoint.ok === false) {
              warnings.push(`${name}.${endpointName}: ${summarizeError(endpoint.error || "not available")}`);
            }
          }
        }
      }
      showNotice(warnings);

      const onlinePanels = renderOnline(sections.online);
      const localPanels = renderLocal(sections.local, report === "all");
      const claudePanels = renderClaude(sections.claude, report === "all");
      const profilePanelIndex = onlinePanels.findIndex((p) => p.title === "profile");
      const dailyPanelIndex = localPanels.findIndex((p) => p.title === "daily");
      const claudeRatePanelIndex = claudePanels.findIndex((p) => p.title === "claude-rate");
      const profilePanel = profilePanelIndex >= 0 ? onlinePanels.splice(profilePanelIndex, 1)[0] : null;
      const dailyPanel = dailyPanelIndex >= 0 ? localPanels.splice(dailyPanelIndex, 1)[0] : null;
      const claudeRatePanel = claudeRatePanelIndex >= 0 ? claudePanels.splice(claudeRatePanelIndex, 1)[0] : null;
      const claudeModelPanelIndex = claudePanels.findIndex((p) => p.title === "claude-models");
      const codexModelPanelIndex = localPanels.findIndex((p) => p.title === "codex-models");
      const claudeModelPanel = claudeModelPanelIndex >= 0 ? claudePanels.splice(claudeModelPanelIndex, 1)[0] : null;
      const codexModelPanel = codexModelPanelIndex >= 0 ? localPanels.splice(codexModelPanelIndex, 1)[0] : null;
      const modelPanels = [claudeModelPanel, codexModelPanel].filter(Boolean);
      const claudeDetailPanelIds = new Set([
        "claude-totals",
        "claude-daily",
        "claude-projects",
        "claude-sessions"
      ]);
      const visibleClaudePanels = report === "all"
        ? claudePanels.filter((panel) => !claudeDetailPanelIds.has(panel.title))
        : claudePanels;
      const codexDetailPanelIds = new Set(["codex-totals", "codex-sessions"]);
      const visibleLocalPanels = report === "all"
        ? localPanels.filter((panel) => !codexDetailPanelIds.has(panel.title))
        : localPanels;
      const pairedPanels = report === "all" ? [] : [profilePanel, dailyPanel].filter(Boolean);
      const panels = [
        ...onlinePanels,
        claudeRatePanel,
        ...renderIsambard(sections.isambard),
        ...modelPanels,
        ...visibleClaudePanels,
        ...pairedPanels,
        ...renderResets(sections.resets),
        ...visibleLocalPanels,
        ...renderApiUsage(sections.api)
      ];
      $("sections").innerHTML = packSections(panels);
    }

    function queryUrl(forceIsambardRefresh = false) {
      const params = new URLSearchParams({
        report: $("report").value,
        top: $("top").value,
        days: $("days").value,
        warn_days: "7",
        _: Date.now().toString()
      });
      if (forceIsambardRefresh && ["all", "isambard-status"].includes($("report").value)) {
        params.set("isambard_force_refresh", "true");
      }
      return `/api/usage?${params.toString()}`;
    }

    async function refresh(forceIsambardRefresh = false) {
      if (state.loading) {
        state.pendingRefresh = true;
        state.pendingForceRefresh = state.pendingForceRefresh || forceIsambardRefresh;
        return;
      }
      state.loading = true;
      $("refresh-now").disabled = true;
      setStatus(t("refreshing"), t("refreshingDetail"));
      try {
        const response = await fetch(queryUrl(forceIsambardRefresh), { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || `HTTP ${response.status}`);
        }
        state.lastPayload = payload;
        render(payload);
        const when = new Date().toLocaleTimeString();
        setStatus(payload.ok ? t("upToDate") : t("loadedWithNotes"), `${t("lastRefresh")} ${when}`);
      } catch (error) {
        showNotice([error.message || String(error)]);
        setStatus(t("refreshFailed"), t("refreshFailedDetail"));
      } finally {
        state.loading = false;
        $("refresh-now").disabled = false;
        if (state.pendingRefresh) {
          const pendingForce = state.pendingForceRefresh;
          state.pendingRefresh = false;
          state.pendingForceRefresh = false;
          refresh(pendingForce);
        } else {
          schedule();
        }
      }
    }

    function schedule() {
      if (state.timer) {
        clearTimeout(state.timer);
        state.timer = null;
      }
      const enabled = $("auto").checked;
      const seconds = Math.max(3, Number($("refresh").value) || __DEFAULT_REFRESH__);
      if (enabled) {
        state.timer = setTimeout(refresh, seconds * 1000);
      }
    }

    $("refresh-now").addEventListener("click", () => refresh(true));
    $("report").addEventListener("change", refresh);
    $("top").addEventListener("change", refresh);
    $("days").addEventListener("change", refresh);
    $("refresh").addEventListener("change", schedule);
    $("auto").addEventListener("change", schedule);
    $("language").addEventListener("change", () => {
      state.lang = $("language").value === "zh" ? "zh" : "en";
      localStorage.setItem("codexUsageLanguage", state.lang);
      applyLanguage();
      if (state.lastPayload) {
        render(state.lastPayload);
        const when = new Date().toLocaleTimeString();
        setStatus(state.lastPayload.ok ? t("upToDate") : t("loadedWithNotes"), `${t("lastRefresh")} ${when}`);
      } else {
        setStatus(t("statusStarting"), t("statusWaiting"));
      }
    });

    const requestedReport = new URLSearchParams(window.location.search).get("report");
    if (requestedReport && Array.from($("report").options).some((option) => option.value === requestedReport)) {
      $("report").value = requestedReport;
    }
    applyLanguage();
    setStatus(t("statusStarting"), t("statusWaiting"));
    refresh();
  </script>
</body>
</html>
"""


MAINTENANCE_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Planned Maintenance · Codex &amp; Claude Code Usage Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1110;
      --ink: #eef7f3;
      --muted: #9badac;
      --panel: #121b1a;
      --panel-strong: #172321;
      --field: #0f1817;
      --line: #263534;
      --accent: #46d3b8;
      --bad: #ff786d;
      --shadow: 0 16px 38px rgba(0, 0, 0, 0.32);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .shell {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 42px;
    }

    .back {
      display: inline-block;
      margin-bottom: 18px;
      color: var(--accent);
      font-weight: 800;
      text-decoration: none;
    }

    .back:hover { text-decoration: underline; }

    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }

    h1 { margin: 0; font-size: 28px; }

    .meta { margin: 6px 0 0; color: var(--muted); }

    button {
      min-height: 38px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #06110f;
      padding: 8px 14px;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }

    button:disabled { cursor: wait; opacity: .7; }

    .notice {
      display: none;
      margin-bottom: 18px;
      padding: 11px 12px;
      border: 1px solid #66302c;
      border-radius: 8px;
      background: #2a1514;
      color: var(--bad);
      white-space: pre-wrap;
    }

    .notice.show { display: block; }

    section {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }

    section h2 {
      margin: 0;
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel-strong);
      font-size: 16px;
    }

    .panel-body { padding: 14px; }

    .table-wrap { overflow-x: auto; }

    table { width: 100%; min-width: 760px; border-collapse: collapse; }

    th, td {
      padding: 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }

    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      white-space: nowrap;
    }

    tr:last-child td { border-bottom: 0; }

    .empty { padding: 18px; color: var(--muted); text-align: center; }

    @media (max-width: 640px) {
      .shell { width: min(100vw - 22px, 1180px); padding-top: 16px; }
      header { display: grid; }
      h1 { font-size: 23px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <a class="back" href="/" data-i18n="back">← Back to Dashboard</a>
    <header>
      <div>
        <h1 data-i18n="title">Planned Maintenance</h1>
        <p id="meta" class="meta"></p>
      </div>
      <button id="refresh" type="button" data-i18n="refresh">Refresh Source</button>
    </header>
    <div id="notice" class="notice"></div>
    <section>
      <h2 data-i18n="schedule">Maintenance Schedule</h2>
      <div id="content" class="panel-body"><div class="empty" data-i18n="loading">Loading…</div></div>
    </section>
  </main>
  <script>
    const state = {
      loading: false,
      lang: localStorage.getItem("codexUsageLanguage") || ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en")
    };

    const $ = (id) => document.getElementById(id);
    const TEXT = {
      en: {
        back: "← Back to Dashboard",
        title: "Planned Maintenance",
        schedule: "Maintenance Schedule",
        refresh: "Refresh Source",
        refreshing: "Refreshing…",
        loading: "Loading…",
        noRows: "No planned maintenance is currently listed.",
        fetchedAt: "Source Fetched",
        liveFetch: "Live Fetch",
        cachedData: "Cached Result",
        failed: "Could not load maintenance details."
      },
      zh: {
        back: "← 返回仪表盘",
        title: "计划维护",
        schedule: "维护计划",
        refresh: "刷新源数据",
        refreshing: "刷新中…",
        loading: "正在加载…",
        noRows: "当前没有列出的计划维护。",
        fetchedAt: "源数据抓取时间",
        liveFetch: "实时抓取",
        cachedData: "缓存结果",
        failed: "无法加载维护详情。"
      }
    };

    function t(key) {
      return TEXT[state.lang]?.[key] || TEXT.en[key] || key;
    }

    function esc(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function applyLanguage() {
      document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
      document.title = `${t("title")} · Codex & Claude Code Usage Dashboard`;
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        node.textContent = t(node.dataset.i18n);
      });
    }

    function showNotice(lines) {
      const clean = lines.filter(Boolean);
      $("notice").textContent = clean.join("\n");
      $("notice").classList.toggle("show", clean.length > 0);
    }

    function maintenanceTable(headers, rows) {
      if (!headers.length) {
        return `<div class="empty">${esc(t("noRows"))}</div>`;
      }
      const head = headers.map((item) => `<th>${esc(item)}</th>`).join("");
      const body = rows.length
        ? rows.map((row) => `<tr>${row.map((item) => `<td>${esc(item)}</td>`).join("")}</tr>`).join("")
        : `<tr><td colspan="${headers.length}">${esc(t("noRows"))}</td></tr>`;
      return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function render(payload) {
      const data = payload.data || {};
      const snapshot = data.status || {};
      const headers = Array.isArray(snapshot.maintenance_headers) ? snapshot.maintenance_headers : [];
      const rows = Array.isArray(snapshot.maintenance_rows)
        ? snapshot.maintenance_rows.filter(Array.isArray)
        : [];
      $("content").innerHTML = maintenanceTable(headers, rows);
      const source = data.source === "live" ? t("liveFetch") : t("cachedData");
      $("meta").textContent = `${t("fetchedAt")}: ${snapshot.fetched_at || "-"} · ${source}`;
      const warnings = [data.warning];
      if (Array.isArray(payload.errors)) {
        payload.errors.forEach((item) => warnings.push(`${item.section || "report"}: ${item.message || item}`));
      }
      showNotice(warnings);
    }

    async function load(forceRefresh = false) {
      if (state.loading) {
        return;
      }
      state.loading = true;
      $("refresh").disabled = true;
      $("refresh").textContent = t("refreshing");
      try {
        const params = new URLSearchParams({ report: "isambard-status", _: Date.now().toString() });
        if (forceRefresh) {
          params.set("isambard_force_refresh", "true");
        }
        const response = await fetch(`/api/usage?${params.toString()}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.data?.status) {
          throw new Error(payload.data?.error?.message || payload.error || t("failed"));
        }
        render(payload);
      } catch (error) {
        showNotice([error.message || t("failed")]);
        $("content").innerHTML = `<div class="empty">${esc(t("failed"))}</div>`;
      } finally {
        state.loading = false;
        $("refresh").disabled = false;
        $("refresh").textContent = t("refresh");
      }
    }

    applyLanguage();
    $("refresh").addEventListener("click", () => load(true));
    load();
  </script>
</body>
</html>
"""


def positive_int_query(
    query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = query.get(name, [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


def optional_positive_int_query(query: dict[str, list[str]], name: str) -> int | None:
    raw = query.get(name, [""])[0]
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def list_query(query: dict[str, list[str]], name: str) -> list[str]:
    values: list[str] = []
    for item in query.get(name, []):
        values.extend(part.strip() for part in item.split(",") if part.strip())
    return values


def error_message(exc: BaseException, stderr_text: str) -> str:
    if stderr_text.strip():
        return codex_usage.strip_ansi(stderr_text.strip())
    if isinstance(exc, SystemExit):
        return f"collector exited with code {exc.code}"
    return f"{type(exc).__name__}: {exc}"


def safe_collect(
    section: str, collector: Callable[[], dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, str] | None]:
    stderr_buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr_buffer):
            return collector(), None
    except SystemExit as exc:
        message = error_message(exc, stderr_buffer.getvalue())
    except Exception as exc:  # Keep the dashboard alive if one collector changes.
        message = error_message(exc, stderr_buffer.getvalue())

    return (
        {
            "ok": False,
            "retrieved_at_local": codex_usage.local_now_text(),
            "error": {"message": message},
        },
        {"section": section, "message": message},
    )


def collect_report(
    report: str,
    top: int,
    days: int,
    warn_days: int,
    bucket_width: str,
    limit: int | None,
    group_by: list[str],
    no_costs: bool,
    isambard_force_refresh: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []

    if report == "all":
        reset_data, error = safe_collect("reset_credits", codex_usage.collect_resets)
        if error:
            errors.append(error)
        local_data, error = safe_collect(
            "local_usage", lambda: codex_usage.collect_local_usage(codex_usage.CODEX_HOME, top_n=top)
        )
        if error:
            errors.append(error)
        else:
            codex_usage.limit_local_usage_days(local_data, days)
        online_data, error = safe_collect("online_usage", codex_usage.collect_online_usage)
        if error:
            errors.append(error)
        claude_data, error = safe_collect(
            "claude_usage",
            lambda: claude_usage.collect_usage(top_n=top, days=days),
        )
        if error:
            errors.append(error)
        isambard_data, error = safe_collect(
            "isambard_status",
            lambda: isambard_status.collect_status(
                force_refresh=isambard_force_refresh,
            ),
        )
        if error:
            errors.append(error)
        return (
            {
                "retrieved_at_local": codex_usage.local_now_text(),
                "reset_credits": reset_data,
                "local_usage": local_data,
                "online_usage": online_data,
                "claude_usage": claude_data,
                "isambard_status": isambard_data,
            },
            errors,
        )

    if report == "resets":
        data, error = safe_collect("reset_credits", codex_usage.collect_resets)
    elif report == "codex-usage":
        reset_data, reset_error = safe_collect(
            "reset_credits",
            codex_usage.collect_resets,
        )
        if reset_error:
            errors.append(reset_error)
        local_data, local_error = safe_collect(
            "local_usage",
            lambda: codex_usage.collect_local_usage(
                codex_usage.CODEX_HOME,
                top_n=top,
            ),
        )
        if local_error:
            errors.append(local_error)
        else:
            codex_usage.limit_local_usage_days(local_data, days)
        online_data, online_error = safe_collect(
            "online_usage",
            codex_usage.collect_online_usage,
        )
        if online_error:
            errors.append(online_error)
        api_args = argparse.Namespace(
            days=days,
            top=top,
            bucket_width=bucket_width,
            limit=limit,
            group_by=group_by,
            no_costs=no_costs,
        )
        api_data, api_error = safe_collect(
            "api_usage",
            lambda: codex_usage.collect_api_usage(api_args),
        )
        if api_error:
            errors.append(api_error)
        return (
            {
                "retrieved_at_local": codex_usage.local_now_text(),
                "reset_credits": reset_data,
                "local_usage": local_data,
                "online_usage": online_data,
                "api_usage": api_data,
            },
            errors,
        )
    elif report == "local-usage":
        data, error = safe_collect(
            "local_usage", lambda: codex_usage.collect_local_usage(codex_usage.CODEX_HOME, top_n=top)
        )
        if not error:
            codex_usage.limit_local_usage_days(data, days)
    elif report == "online-usage":
        data, error = safe_collect("online_usage", codex_usage.collect_online_usage)
    elif report == "claude-usage":
        data, error = safe_collect(
            "claude_usage",
            lambda: claude_usage.collect_usage(top_n=top, days=days),
        )
    elif report == "api-usage":
        args = argparse.Namespace(
            days=days,
            top=top,
            bucket_width=bucket_width,
            limit=limit,
            group_by=group_by,
            no_costs=no_costs,
        )
        data, error = safe_collect("api_usage", lambda: codex_usage.collect_api_usage(args))
    elif report == "isambard-status":
        data, error = safe_collect(
            "isambard_status",
            lambda: isambard_status.collect_status(
                force_refresh=isambard_force_refresh,
            ),
        )
    else:
        data = {
            "ok": False,
            "retrieved_at_local": codex_usage.local_now_text(),
            "error": {"message": f"unknown report: {report}"},
        }
        error = {"section": "request", "message": f"unknown report: {report}"}

    if error:
        errors.append(error)
    return data, errors


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def report_has_error(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("ok") is False:
        return True
    endpoints = data.get("endpoints")
    if isinstance(endpoints, dict):
        for item in endpoints.values():
            if isinstance(item, dict) and item.get("ok") is False:
                return True
    for key in (
        "reset_credits",
        "local_usage",
        "online_usage",
        "claude_usage",
        "api_usage",
        "isambard_status",
    ):
        if report_has_error(data.get(key)):
            return True
    return False


class UsageWebHandler(BaseHTTPRequestHandler):
    server_version = "CodingUsageWeb/1.0"

    def do_HEAD(self) -> None:  # noqa: N802 - http.server API name.
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.send_html(include_body=False)
            return
        if parsed.path == "/isambard-maintenance":
            self.send_maintenance_html(include_body=False)
            return
        if parsed.path == "/healthz":
            self.send_json({"ok": True, "time": time.time()}, include_body=False)
            return
        self.send_json({"ok": False, "error": "not found"}, status=404, include_body=False)

    def do_GET(self) -> None:  # noqa: N802 - http.server API name.
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.send_html()
            return
        if parsed.path == "/isambard-maintenance":
            self.send_maintenance_html()
            return
        if parsed.path == "/api/usage":
            self.send_usage(parsed.query)
            return
        if parsed.path == "/healthz":
            self.send_json({"ok": True, "time": time.time()})
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self.send_json({"ok": False, "error": "not found"}, status=404)

    def send_html(self, include_body: bool = True) -> None:
        refresh = str(getattr(self.server, "refresh_seconds", DEFAULT_REFRESH_SECONDS))
        body = INDEX_HTML.replace("__DEFAULT_REFRESH__", refresh).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_maintenance_html(self, include_body: bool = True) -> None:
        body = MAINTENANCE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_usage(self, raw_query: str) -> None:
        query = urllib.parse.parse_qs(raw_query)
        report = query.get("report", ["all"])[0]
        top = positive_int_query(query, "top", 10, 1, MAX_TOP)
        days = positive_int_query(query, "days", 30, 1, MAX_DAYS)
        warn_days = positive_int_query(query, "warn_days", 7, 0, 365)
        bucket_width = query.get("bucket_width", ["1d"])[0]
        if bucket_width not in {"1d", "1h", "1m"}:
            bucket_width = "1d"
        limit = optional_positive_int_query(query, "limit")
        group_by = list_query(query, "group_by")
        no_costs = query.get("no_costs", ["false"])[0].lower() in {"1", "true", "yes"}
        isambard_force_refresh = query.get("isambard_force_refresh", ["false"])[0].lower() in {
            "1",
            "true",
            "yes",
        }

        data, errors = collect_report(
            report=report,
            top=top,
            days=days,
            warn_days=warn_days,
            bucket_width=bucket_width,
            limit=limit,
            group_by=group_by,
            no_costs=no_costs,
            isambard_force_refresh=isambard_force_refresh,
        )
        payload = {
            "ok": not errors and not report_has_error(data),
            "report": report,
            "served_at_local": codex_usage.local_now_text(),
            "settings": {
                "top": top,
                "days": days,
                "warn_days": warn_days,
                "bucket_width": bucket_width,
                "limit": limit,
                "group_by": group_by,
                "no_costs": no_costs,
                "isambard_force_refresh": isambard_force_refresh,
            },
            "errors": errors,
            "data": data,
        }
        self.send_json(payload)

    def send_json(self, payload: Any, status: int = 200, include_body: bool = True) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(fmt, *args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve a local browser dashboard for Codex and Claude Code usage."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind. Default: {DEFAULT_HOST}. Use with care if changing it.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind. Default: {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Default browser refresh interval in seconds. Default: {DEFAULT_REFRESH_SECONDS}.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-request access logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), UsageWebHandler)
    server.refresh_seconds = max(3, int(args.refresh))
    server.quiet = bool(args.quiet)
    url = f"http://{args.host}:{args.port}"
    print(f"Codex & Claude Code Usage dashboard running at {url}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Codex & Claude Code Usage dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
