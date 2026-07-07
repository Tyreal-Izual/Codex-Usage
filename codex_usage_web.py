#!/usr/bin/env python3
"""
Local web dashboard for Codex Usage.

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
  <title>Codex Usage Dashboard</title>
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
      justify-content: space-between;
      gap: 12px;
      margin: 0;
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel-strong);
      font-size: 16px;
    }

    section.panel h2 span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
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
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1 data-i18n="appTitle">Codex Usage Dashboard</h1>
        <p class="subtitle" data-i18n="subtitle">A local-only web view over the existing Codex Usage collectors. The page polls this machine and does not need a package install.</p>
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
          <option value="all" data-i18n="reportAll">Overview: resets + local + online</option>
          <option value="local-usage" data-i18n="reportLocal">Local usage only</option>
          <option value="resets" data-i18n="reportResets">Reset credits only</option>
          <option value="online-usage" data-i18n="reportOnline">Online usage/profile only</option>
          <option value="api-usage" data-i18n="reportApi">OpenAI API usage/costs</option>
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
        <span data-i18n="topRows">Top rows</span>
        <input id="top" type="number" min="1" max="100" value="10">
      </label>
      <label>
        <span data-i18n="localDays">Local days</span>
        <input id="days" type="number" min="1" max="365" value="30">
      </label>
      <label>
        <span data-i18n="refreshSec">Refresh sec</span>
        <input id="refresh" type="number" min="3" max="3600" value="__DEFAULT_REFRESH__">
      </label>
      <label class="toggle">
        <input id="auto" type="checkbox" checked>
        <span data-i18n="autoRefresh">Auto refresh</span>
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
      lastPayload: null,
      lang: localStorage.getItem("codexUsageLanguage") || ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en")
    };

    const $ = (id) => document.getElementById(id);

    const TEXT = {
      en: {
        appTitle: "Codex Usage Dashboard",
        subtitle: "A local-only web view over the existing Codex Usage collectors. The page polls this machine and does not need a package install.",
        statusStarting: "Starting",
        statusWaiting: "Waiting for the first refresh.",
        report: "Report",
        reportAll: "Overview: resets + local + online",
        reportLocal: "Local usage only",
        reportResets: "Reset credits only",
        reportOnline: "Online usage/profile only",
        reportApi: "OpenAI API usage/costs",
        language: "Language",
        topRows: "Top rows",
        localDays: "Local days",
        refreshSec: "Refresh sec",
        autoRefresh: "Auto refresh",
        refresh: "Refresh",
        refreshing: "Refreshing",
        refreshingDetail: "Reading local data and selected online endpoints.",
        upToDate: "Up to date",
        loadedWithNotes: "Loaded with notes",
        lastRefresh: "Last refresh",
        refreshFailed: "Refresh failed",
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
        sessions: "sessions",
        output: "output",
        totalTokensWindow: "total tokens in this window",
        busiestDay: "Busiest day",
        less: "Less",
        more: "More",
        totalTokens: "total tokens",
        resetCredits: "Reset credits",
        resetSubtitle: "Read-only Codex reset endpoint",
        retrieved: "Retrieved",
        availableResets: "Available resets",
        creditsReturned: "Credits returned",
        totalEarnedCount: "Total earned count",
        status: "Status",
        expiresLocally: "Expires locally",
        timeRemaining: "Time remaining",
        grantedLocally: "Granted locally",
        localTokenTotals: "Local token totals",
        localTokenSubtitle: "Final counters from local session files",
        sqliteModelCounters: "SQLite model counters",
        sqliteSubtitle: "Local thread database",
        dailyLocalUsage: "Daily local usage",
        dayWindow: "day window",
        topSessions: "Top sessions",
        topSessionsSubtitle: "Largest local session counters",
        field: "Field",
        total: "Total",
        model: "Model",
        models: "models",
        threads: "Threads",
        tokensUsed: "Tokens used",
        share: "Share",
        date: "Date",
        project: "Project",
        sessionFile: "Session file",
        onlineRateLimits: "Online rate limits",
        onlineSubtitle: "Read-only backend endpoints",
        primaryWindow: "Primary window",
        weeklyWindow: "Weekly window",
        primaryHint: "Available before the primary limit is reached",
        weeklyHint: "Available before the weekly limit is reached",
        plan: "Plan",
        allowed: "Allowed",
        limitReached: "Limit reached",
        primaryLeft: "Primary left",
        weeklyLeft: "Weekly left",
        primaryResetsIn: "Primary resets in",
        weeklyResetsIn: "Weekly resets in",
        creditsBalance: "Credits balance",
        hasCredits: "Has credits",
        profileStatistics: "Profile statistics",
        profileSubtitle: "Redacted profile data",
        lifetimeTokens: "Lifetime tokens",
        peakDailyTokens: "Peak daily tokens",
        mostUsedReasoningEffort: "Most used reasoning effort",
        reasoningEffortShare: "Reasoning effort share",
        adminApiStatus: "Admin API status",
        adminApiSubtitle: "Uses OPENAI_ADMIN_KEY when set",
        completionsUsage: "Completions usage",
        adminApi: "OpenAI Admin API",
        costs: "Costs",
        days: "Days",
        bucketWidth: "Bucket width",
        usageStatus: "Usage status",
        costsStatus: "Costs status",
        error: "Error",
        bucketStart: "Bucket start",
        group: "Group",
        input: "Input",
        requests: "Requests",
        amount: "Amount",
        currency: "Currency",
        lineItem: "Line item",
        inputTokens: "Input tokens",
        cachedInputTokens: "Cached input tokens",
        outputTokens: "Output tokens",
        reasoningOutputTokens: "Reasoning output tokens"
      },
      zh: {
        appTitle: "Codex 用量仪表盘",
        subtitle: "基于现有 Codex Usage 采集逻辑的本地网页视图。页面会轮询本机数据，不需要安装额外依赖。",
        statusStarting: "正在启动",
        statusWaiting: "等待第一次刷新。",
        report: "报告",
        reportAll: "总览：重置额度 + 本地 + 在线",
        reportLocal: "只看本地用量",
        reportResets: "只看重置额度",
        reportOnline: "只看在线用量 / 资料",
        reportApi: "OpenAI API 用量 / 成本",
        language: "语言",
        topRows: "顶部行数",
        localDays: "本地天数",
        refreshSec: "刷新秒数",
        autoRefresh: "自动刷新",
        refresh: "刷新",
        refreshing: "刷新中",
        refreshingDetail: "正在读取本地数据和选中的在线接口。",
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
        resetCredits: "重置额度",
        resetSubtitle: "只读 Codex 重置额度接口",
        retrieved: "获取时间",
        availableResets: "可用重置次数",
        creditsReturned: "返回额度数",
        totalEarnedCount: "累计获得数",
        status: "状态",
        expiresLocally: "本地过期时间",
        timeRemaining: "剩余时间",
        grantedLocally: "本地授予时间",
        localTokenTotals: "本地 token 总量",
        localTokenSubtitle: "来自本地 session 文件的最终计数",
        sqliteModelCounters: "SQLite 模型计数",
        sqliteSubtitle: "本地 thread 数据库",
        dailyLocalUsage: "每日本地用量",
        dayWindow: "天窗口",
        topSessions: "最高用量 session",
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
        onlineRateLimits: "在线速率限制",
        onlineSubtitle: "只读后端接口",
        primaryWindow: "Primary 窗口",
        weeklyWindow: "Weekly 窗口",
        primaryHint: "距离 primary 限制前仍可使用的比例",
        weeklyHint: "距离 weekly 限制前仍可使用的比例",
        plan: "套餐",
        allowed: "是否允许",
        limitReached: "是否达到限制",
        primaryLeft: "Primary 剩余",
        weeklyLeft: "Weekly 剩余",
        primaryResetsIn: "Primary 重置倒计时",
        weeklyResetsIn: "Weekly 重置倒计时",
        creditsBalance: "额度余额",
        hasCredits: "是否有额度",
        profileStatistics: "资料统计",
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
        reasoningOutputTokens: "推理输出 token"
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

    function panel(title, subtitle, body, wide = false, id = title) {
      const html = `
        <section class="panel${wide ? " panel--wide" : ""}">
          <h2>${esc(title)}<span>${esc(subtitle || "")}</span></h2>
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

    function leftBar(label, usedValue, hint) {
      const left = limitLeft(usedValue);
      const percent = left === null ? 0 : left;
      const tone = left !== null && left <= 10 ? "bad" : left !== null && left <= 25 ? "warn" : "";
      const valueText = left === null ? "-" : state.lang === "zh" ? `${t("left")} ${left.toFixed(1)}%` : `${left.toFixed(1)}% ${t("left")}`;
      return `
        <div class="barbox">
          <div class="barhead"><span>${esc(label)}</span><span>${esc(valueText)}</span></div>
          <div class="track"><div class="fill ${tone}" style="width: ${percent}%"></div></div>
          <div class="subtle">${esc(hint || "")}</div>
        </div>`;
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

    function splitSections(data, report) {
      return {
        resets: data?.reset_credits || (report === "resets" ? data : null),
        local: data?.local_usage || (report === "local-usage" ? data : null),
        online: data?.online_usage || (report === "online-usage" ? data : null),
        api: data?.api_usage || (report === "api-usage" ? data : null)
      };
    }

    function usageFieldLabel(field) {
      return {
        input_tokens: t("inputTokens"),
        cached_input_tokens: t("cachedInputTokens"),
        output_tokens: t("outputTokens"),
        reasoning_output_tokens: t("reasoningOutputTokens"),
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
      const credits = table(["#", t("status"), t("expiresLocally"), t("timeRemaining"), t("grantedLocally")], rows);
      return [panel(t("resetCredits"), t("resetSubtitle"), overview + credits, true)];
    }

    function renderLocal(local) {
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

      return [
        panel(t("localTokenTotals"), t("localTokenSubtitle"), table([t("field"), t("total")], tokenRows, [1])),
        panel(t("sqliteModelCounters"), t("sqliteSubtitle"), sqliteModelStack(sqliteModels) + table([t("model"), t("threads"), t("tokensUsed"), t("share")], sqliteRows, [1, 2, 3], "sqlite-table")),
        panel(t("dailyLocalUsage"), `${daily.length} ${t("dayWindow")}`, dailyHeatmap(daily), false, "daily"),
        panel(t("topSessions"), t("topSessionsSubtitle"), table([t("date"), t("model"), t("total"), t("output"), t("project"), t("sessionFile")], topRows, [2, 3]), true)
      ];
    }

    function renderOnline(online) {
      if (!online) {
        return [];
      }
      const rate = get(online, ["endpoints", "rate_limit_status", "data"], {});
      const profile = get(online, ["endpoints", "profile", "data"], {});
      const primary = get(rate, ["rate_limit", "primary_window", "used_percent"]);
      const weekly = get(rate, ["rate_limit", "secondary_window", "used_percent"]);
      const primaryReset = get(rate, ["rate_limit", "primary_window", "reset_after_seconds"]);
      const weeklyReset = get(rate, ["rate_limit", "secondary_window", "reset_after_seconds"]);
      const limitRows = [
        [esc(t("plan")), esc(rate.plan_type || "-")],
        [esc(t("allowed")), esc(get(rate, ["rate_limit", "allowed"], "-"))],
        [esc(t("limitReached")), esc(get(rate, ["rate_limit", "limit_reached"], "-"))],
        [esc(t("primaryLeft")), esc(fmtPercent(limitLeft(primary)))],
        [esc(t("weeklyLeft")), esc(fmtPercent(limitLeft(weekly)))],
        [esc(t("primaryResetsIn")), esc(fmtDurationSeconds(primaryReset))],
        [esc(t("weeklyResetsIn")), esc(fmtDurationSeconds(weeklyReset))],
        [esc(t("creditsBalance")), esc(fmtNumber(get(rate, ["credits", "balance"])))],
        [esc(t("hasCredits")), esc(get(rate, ["credits", "has_credits"], "-"))]
      ];
      const stats = profile.stats || {};
      const profileRows = [
        [esc(t("lifetimeTokens")), esc(fmtNumber(stats.lifetime_tokens))],
        [esc(t("peakDailyTokens")), esc(fmtNumber(stats.peak_daily_tokens))],
        [esc(t("mostUsedReasoningEffort")), esc(stats.most_used_reasoning_effort || "-")],
        [esc(t("reasoningEffortShare")), esc(fmtPercent(stats.most_used_reasoning_effort_percentage))]
      ];
      const bars = `<div class="bars">${leftBar(t("primaryWindow"), primary, t("primaryHint"))}${leftBar(t("weeklyWindow"), weekly, t("weeklyHint"))}</div>`;
      return [
        panel(t("onlineRateLimits"), t("onlineSubtitle"), bars + kvGrid(limitRows), true),
        panel(t("profileStatistics"), t("profileSubtitle"), table([t("metric"), t("value")], profileRows, [1]), false, "profile")
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
      const localPanels = renderLocal(sections.local);
      const profilePanelIndex = onlinePanels.findIndex((p) => p.title === "profile");
      const dailyPanelIndex = localPanels.findIndex((p) => p.title === "daily");
      const profilePanel = profilePanelIndex >= 0 ? onlinePanels.splice(profilePanelIndex, 1)[0] : null;
      const dailyPanel = dailyPanelIndex >= 0 ? localPanels.splice(dailyPanelIndex, 1)[0] : null;
      const pairedPanels = [profilePanel, dailyPanel].filter(Boolean);
      const panels = [
        ...onlinePanels,
        ...pairedPanels,
        ...renderResets(sections.resets),
        ...localPanels,
        ...renderApiUsage(sections.api)
      ];
      $("sections").innerHTML = packSections(panels);
    }

    function queryUrl() {
      const params = new URLSearchParams({
        report: $("report").value,
        top: $("top").value,
        days: $("days").value,
        warn_days: "7",
        _: Date.now().toString()
      });
      return `/api/usage?${params.toString()}`;
    }

    async function refresh() {
      if (state.loading) {
        return;
      }
      state.loading = true;
      $("refresh-now").disabled = true;
      setStatus(t("refreshing"), t("refreshingDetail"));
      try {
        const response = await fetch(queryUrl(), { cache: "no-store" });
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
        schedule();
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

    $("refresh-now").addEventListener("click", refresh);
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

    applyLanguage();
    setStatus(t("statusStarting"), t("statusWaiting"));
    refresh();
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
        return (
            {
                "retrieved_at_local": codex_usage.local_now_text(),
                "reset_credits": reset_data,
                "local_usage": local_data,
                "online_usage": online_data,
            },
            errors,
        )

    if report == "resets":
        data, error = safe_collect("reset_credits", codex_usage.collect_resets)
    elif report == "local-usage":
        data, error = safe_collect(
            "local_usage", lambda: codex_usage.collect_local_usage(codex_usage.CODEX_HOME, top_n=top)
        )
        if not error:
            codex_usage.limit_local_usage_days(data, days)
    elif report == "online-usage":
        data, error = safe_collect("online_usage", codex_usage.collect_online_usage)
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
    for key in ("reset_credits", "local_usage", "online_usage", "api_usage"):
        if report_has_error(data.get(key)):
            return True
    return False


class UsageWebHandler(BaseHTTPRequestHandler):
    server_version = "CodexUsageWeb/1.0"

    def do_HEAD(self) -> None:  # noqa: N802 - http.server API name.
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.send_html(include_body=False)
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

        data, errors = collect_report(
            report=report,
            top=top,
            days=days,
            warn_days=warn_days,
            bucket_width=bucket_width,
            limit=limit,
            group_by=group_by,
            no_costs=no_costs,
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
        description="Serve a local browser dashboard for Codex Usage."
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
    print(f"Codex Usage dashboard running at {url}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Codex Usage dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
