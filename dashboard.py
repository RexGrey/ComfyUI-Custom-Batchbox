#!/usr/bin/env python3
"""
BatchBox Usage Dashboard

Standalone viewer for student usage logs. No ComfyUI dependency.

Usage:
    python dashboard.py [--port 9090] [--data-dir "Z:\\ComfyUI_Master\\shared_cache"]

The dashboard reads JSONL files from {data-dir}/usage_logs/*/usage_*.jsonl
and serves a real-time HTML dashboard on localhost.
"""

import argparse
import json
import os
import sys
import webbrowser
import glob
import socket
import threading
import time
import ctypes
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

_TZ_CST = timezone(timedelta(hours=8))


def find_data_dir():
    """Auto-detect NAS shared_cache directory."""
    env = os.environ.get("BATCHBOX_SHARED_CACHE")
    if env and os.path.isdir(env):
        return env
    for letter in "ZYXWVUTSRQPONMLKJIHGF":
        candidate = f"{letter}:\\ComfyUI_Master\\shared_cache"
        if os.path.isdir(candidate):
            return candidate
    return None


def load_all_records(data_dir: str, date_filter: str = "all",
                     machine_filter: str = "", date_exact: str = "", status_filter: str = "all") -> list:
    """
    Load all JSONL records from usage_logs subdirectories.

    Args:
        data_dir: Root directory containing usage_logs/
        date_filter: "today", "week", or "all"
        machine_filter: If set, only load records from this machine
        date_exact: If set (YYYY-MM-DD), only load records from this date
        status_filter: "all", "success", or "fail"
    """
    logs_dir = os.path.join(data_dir, "usage_logs")
    if not os.path.isdir(logs_dir):
        return []

    records = []
    now = datetime.now(_TZ_CST)
    today_str = now.strftime("%Y-%m-%d")

    for machine_dir in glob.glob(os.path.join(logs_dir, "*")):
        if not os.path.isdir(machine_dir):
            continue
        # Machine filter
        if machine_filter:
            dir_name = os.path.basename(machine_dir)
            if dir_name != machine_filter:
                continue

        for jsonl_file in glob.glob(os.path.join(machine_dir, "usage_*.jsonl")):
            basename = os.path.basename(jsonl_file)
            file_date = basename.replace("usage_", "").replace(".jsonl", "")

            # Date exact filter (drill-down)
            if date_exact:
                if file_date != date_exact:
                    continue
            elif date_filter == "today" and file_date != today_str:
                continue
            elif date_filter == "week":
                try:
                    file_dt = datetime.strptime(file_date, "%Y-%m-%d").replace(tzinfo=_TZ_CST)
                    if (now - file_dt).days > 7:
                        continue
                except ValueError:
                    continue

            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                r = json.loads(line)
                                # Apply machine filter on record level too
                                if machine_filter and r.get("machine", "") != machine_filter:
                                    continue
                                # Apply status filter
                                if status_filter == "success" and not r.get("ok", False):
                                    continue
                                if status_filter == "fail" and r.get("ok", False):
                                    continue
                                records.append(r)
                            except json.JSONDecodeError:
                                pass
            except (IOError, PermissionError):
                pass

    return records


def compute_stats(records: list, date_filter: str = "today",
                  date_exact: str = "") -> dict:
    """Compute aggregate statistics from records."""
    empty = {
        "total_tasks": 0, "total_generated": 0, "total_saved": 0,
        "success_rate": 0, "total_api_calls": 0,
        "dur_avg": 0, "dur_min": 0, "dur_max": 0,
        "machines": [], "models": {}, "nodes": {},
        "recent": [], "timeline": {}, "machine_list": [],
        "providers_usage": [],
    }
    if not records:
        return empty

    total_tasks = len(records)
    total_gen = sum(r.get("gen", 0) for r in records)
    total_saved = sum(r.get("saved", 0) for r in records)
    total_api_calls = sum(r.get("batch", 1) for r in records)
    success_count = sum(1 for r in records if r.get("ok"))
    success_rate = round(success_count / total_tasks * 100, 1) if total_tasks else 0

    # Duration stats
    durations = [r.get("dur_s", 0) for r in records if r.get("dur_s", 0) > 0]
    dur_avg = round(sum(durations) / len(durations), 1) if durations else 0
    dur_min = round(min(durations), 1) if durations else 0
    dur_max = round(max(durations), 1) if durations else 0

    # Per-machine stats
    machine_map = {}
    for r in records:
        mid = r.get("machine", "unknown")
        if mid not in machine_map:
            machine_map[mid] = {
                "name": mid, "tasks": 0, "gen": 0, "saved": 0,
                "api_calls": 0, "success": 0, "fail": 0,
                "last_ts": "", "durations": [],
            }
        m = machine_map[mid]
        m["tasks"] += 1
        m["gen"] += r.get("gen", 0)
        m["saved"] += r.get("saved", 0)
        m["api_calls"] += r.get("batch", 1)
        if r.get("ok"):
            m["success"] += 1
        else:
            m["fail"] += 1
        d = r.get("dur_s", 0)
        if d > 0:
            m["durations"].append(d)
        ts = r.get("ts", "")
        if ts > m["last_ts"]:
            m["last_ts"] = ts

    # Finalize machine stats
    for m in machine_map.values():
        ds = m.pop("durations")
        m["dur_avg"] = round(sum(ds) / len(ds), 1) if ds else 0

    machines = sorted(machine_map.values(), key=lambda x: x["name"])
    machine_list = sorted(machine_map.keys())

    # Per-model stats
    model_map = {}
    for r in records:
        model = r.get("model", "unknown")
        model_map[model] = model_map.get(model, 0) + 1

    # Per-node type stats
    node_map = {}
    for r in records:
        node = r.get("node", "unknown")
        node_map[node] = node_map.get(node, 0) + 1

    # Per-provider/key image counts. Only direct provider_usage records are used.
    provider_map = {}
    for r in records:
        entries = r.get("provider_usage", [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                gen = int(entry.get("gen", 0))
            except (TypeError, ValueError):
                continue
            if gen <= 0:
                continue
            provider = str(entry.get("provider") or entry.get("provider_label") or "unknown")
            provider_label = str(entry.get("provider_label") or provider)
            key_label = str(entry.get("key_label") or "未记录Key")
            if provider not in provider_map:
                provider_map[provider] = {
                    "provider": provider,
                    "provider_label": provider_label,
                    "gen": 0,
                    "keys": {},
                }
            p = provider_map[provider]
            p["gen"] += gen
            p["keys"][key_label] = p["keys"].get(key_label, 0) + gen

    providers_usage = []
    for provider_data in provider_map.values():
        keys = [
            {"key_label": key_label, "gen": gen}
            for key_label, gen in provider_data.pop("keys").items()
        ]
        keys.sort(key=lambda x: (-x["gen"], x["key_label"]))
        provider_data["keys"] = keys
        providers_usage.append(provider_data)
    providers_usage.sort(key=lambda x: (-x["gen"], x["provider_label"]))

    # Timeline aggregation
    # If viewing a single day (today or date_exact), group by hour.
    # If viewing week/all, group by day.
    use_hourly = (date_filter == "today" or date_exact != "")
    timeline = {}
    for r in records:
        ts = r.get("ts", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
            if use_hourly:
                key = dt.strftime("%H:00")
            else:
                key = dt.strftime("%m-%d")
        except Exception:
            continue
        if key not in timeline:
            timeline[key] = {"tasks": 0, "api_calls": 0, "gen": 0}
        timeline[key]["tasks"] += 1
        timeline[key]["api_calls"] += r.get("batch", 1)
        timeline[key]["gen"] += r.get("gen", 0)

    # Sort timeline keys
    sorted_tl = dict(sorted(timeline.items()))

    # Recent records (last 50)
    sorted_records = sorted(records, key=lambda x: x.get("ts", ""), reverse=True)
    recent = sorted_records[:50]

    return {
        "total_tasks": total_tasks,
        "total_generated": total_gen,
        "total_saved": total_saved,
        "total_api_calls": total_api_calls,
        "success_rate": success_rate,
        "dur_avg": dur_avg,
        "dur_min": dur_min,
        "dur_max": dur_max,
        "machines": machines,
        "machine_list": machine_list,
        "models": model_map,
        "nodes": node_map,
        "recent": recent,
        "timeline": sorted_tl,
        "providers_usage": providers_usage,
    }


def get_valid_dates(data_dir: str) -> list:
    """Scan usage_logs and return all dates (YYYY-MM-DD) that have records."""
    logs_dir = os.path.join(data_dir, "usage_logs")
    if not os.path.isdir(logs_dir):
        return []
    dates = set()
    for machine_dir in glob.glob(os.path.join(logs_dir, "*")):
        if not os.path.isdir(machine_dir):
            continue
        for f in glob.glob(os.path.join(machine_dir, "usage_*.jsonl")):
            basename = os.path.basename(f)
            d = basename.replace("usage_", "").replace(".jsonl", "")
            dates.add(d)
    return sorted(list(dates))


def _notes_path(data_dir: str) -> str:
    return os.path.join(data_dir, "machine_notes.json")


def load_machine_notes(data_dir: str) -> dict:
    """Load machine notes from JSON file."""
    path = _notes_path(data_dir)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_machine_notes(data_dir: str, notes: dict):
    """Save machine notes to JSON file."""
    path = _notes_path(data_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


# ==========================================
# Embedded HTML Dashboard
# ==========================================
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BatchBox Usage Dashboard</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/themes/dark.css">
<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<script src="https://cdn.jsdelivr.net/npm/flatpickr/dist/l10n/zh.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117; --card-bg: #1a1d27; --border: #2d3142;
    --text: #e4e6eb; --text-dim: #8b8fa3; --accent: #6c5ce7;
    --green: #00b894; --red: #e17055; --blue: #0984e3; --yellow: #fdcb6e;
    --orange: #e67e22; --teal: #00cec9;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
    padding: 20px; max-width: 1400px; margin: 0 auto;
  }
  h1 { font-size: 1.5rem; margin-bottom: 0; }
  .header { display:flex; justify-content:space-between; align-items:center;
    margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
  .header-left { display:flex; align-items:center; gap: 12px; }
  .status-dot { width:8px; height:8px; border-radius:50%; background:var(--green);
    display:inline-block; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }

  /* Tab navigation */
  .tab-bar { display:flex; gap:0; margin-bottom:16px; border-bottom:2px solid var(--border); }
  .tab-btn {
    padding:10px 20px; border:none; background:transparent; color:var(--text-dim);
    cursor:pointer; font-size:0.95rem; font-weight:600; position:relative;
    transition: color 0.2s;
  }
  .tab-btn.active { color:var(--accent); }
  .tab-btn.active::after {
    content:''; position:absolute; bottom:-2px; left:0; right:0;
    height:2px; background:var(--accent);
  }
  .tab-btn:hover { color:var(--text); }
  .tab-page { display:none; }
  .tab-page.active { display:block; }

  /* Controls bar */
  .controls { display:flex; justify-content:space-between; align-items:center;
    margin-bottom:16px; flex-wrap:wrap; gap:10px; }
  .controls-left { display:flex; align-items:center; gap:10px; }
  .filters { display:flex; gap:6px; position:relative; }
  .filters button {
    padding:6px 14px; border:1px solid var(--border); border-radius:6px;
    background:transparent; color:var(--text-dim); cursor:pointer;
    font-size:0.85rem; transition:all 0.2s;
  }
  .filters button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
  .filters button:hover { border-color:var(--accent); }
  .date-picker {
    padding:5px 12px; border:1px solid var(--border); border-radius:6px;
    background:var(--card-bg); color:var(--text); font-size:0.85rem; cursor:pointer;
  }
  /* Fix flatpickr: position the calendar dropdown */
  .fp-cal-wrap {
    position:absolute; top:calc(100% + 4px); right:0; z-index:999999;
    display:none;
  }
  .fp-cal-wrap .flatpickr-calendar {
    box-shadow: 0 6px 24px rgba(0,0,0,0.5);
    position:static !important;
    left:auto !important; top:auto !important;
  }
  .date-picker:hover, .date-picker:focus { border-color:var(--accent); }
  .date-picker.fp-active { background:var(--accent); color:#fff; border-color:var(--accent); }
  select {
    padding:6px 10px; border:1px solid var(--border); border-radius:6px;
    background:var(--card-bg); color:var(--text); font-size:0.85rem;
    cursor:pointer; outline:none;
  }
  select:focus { border-color:var(--accent); }

  /* Cards */
  .cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap:12px; margin-bottom:16px; }
  .card {
    background:var(--card-bg); border:1px solid var(--border); border-radius:10px;
    padding:14px; transition:transform 0.2s;
  }
  .card:hover { transform:translateY(-2px); }
  .card-label { font-size:0.75rem; color:var(--text-dim); text-transform:uppercase;
    letter-spacing:0.5px; margin-bottom:2px; }
  .card-value { font-size:1.6rem; font-weight:700; }
  .card-value.green { color:var(--green); }
  .card-value.blue { color:var(--blue); }
  .card-value.yellow { color:var(--yellow); }
  .card-value.orange { color:var(--orange); }
  .card-value.teal { color:var(--teal); }
  .card-value.red { color:var(--red); }

  /* Sections */
  .section { margin-bottom:20px; }
  .section-title { font-size:1rem; margin-bottom:10px; color:var(--text-dim);
    border-bottom:1px solid var(--border); padding-bottom:6px; }

  /* Charts */
  .chart-row { display:grid; grid-template-columns:1fr; gap:16px; margin-bottom:16px; }
  .chart-row-2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
  .chart-box {
    background:var(--card-bg); border:1px solid var(--border); border-radius:10px;
    padding:16px; min-height:260px; position:relative;
  }
  .chart-box canvas { max-height:280px; }
  .chart-label { font-size:0.85rem; color:var(--text-dim); margin-bottom:8px; font-weight:600; }
  .drill-hint {
    position:absolute; top:12px; right:16px; font-size:0.7rem;
    color:var(--text-dim); background:var(--border); padding:2px 8px;
    border-radius:4px; display:none;
  }

  /* Tables */
  table { width:100%; border-collapse:collapse; font-size:0.85rem; }
  th { text-align:left; padding:8px 10px; border-bottom:2px solid var(--border);
    color:var(--text-dim); font-weight:600; white-space:nowrap; }
  td { padding:8px 10px; border-bottom:1px solid var(--border); }
  tr:hover td { background:rgba(108,92,231,0.08); }
  .success-badge { color:var(--green); }
  .fail-badge { color:var(--red); }
  .recent-table { max-height:400px; overflow-y:auto; }
  .recent-table::-webkit-scrollbar { width:6px; }
  .recent-table::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }

  /* Provider usage */
  .provider-usage-list {
    display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr));
    gap:12px;
  }
  .provider-card {
    background:var(--card-bg); border:1px solid var(--border); border-radius:10px;
    padding:14px;
  }
  .provider-card-head {
    display:flex; justify-content:space-between; align-items:center; gap:10px;
    font-weight:700; margin-bottom:10px; padding-bottom:8px;
    border-bottom:1px solid var(--border);
  }
  .provider-total { color:var(--green); white-space:nowrap; }
  .provider-key-row {
    display:flex; justify-content:space-between; gap:10px;
    font-size:0.82rem; color:var(--text-dim); padding:5px 0;
  }
  .provider-key-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .provider-key-gen { color:var(--text); font-weight:600; white-space:nowrap; }
  .empty-block {
    color:var(--text-dim); background:var(--card-bg); border:1px solid var(--border);
    border-radius:10px; padding:18px; text-align:center;
  }

  /* Machine detail grid (Tab 2) */
  .machine-grid {
    display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr));
    gap:14px;
  }
  .machine-card {
    background:var(--card-bg); border:1px solid var(--border); border-radius:10px;
    padding:16px; display:flex; flex-direction:column; gap:8px;
  }
  .machine-card-header {
    font-weight:700; font-size:0.9rem; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; border-bottom:1px solid var(--border); padding-bottom:6px;
  }
  .machine-card-chart { width:120px; height:120px; margin:0 auto; }
  .machine-card-stats { font-size:0.8rem; color:var(--text-dim); display:flex;
    flex-wrap:wrap; gap:4px 12px; }
  .machine-card-stats span { white-space:nowrap; }
  .machine-card-stats .val { color:var(--text); font-weight:600; }
  .m-note {
    font-size:0.75rem; color:var(--text-dim); cursor:pointer;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    max-width: 170px; display:inline-block; vertical-align:middle;
  }
  .m-note:hover { color:var(--accent); }
  .m-note-input {
    font-size:0.75rem; background:var(--bg); color:var(--text); border:1px solid var(--accent);
    border-radius:4px; padding:1px 4px; width:130px; outline:none;
  }

  .refresh-info { font-size:0.75rem; color:var(--text-dim); }
  @media (max-width:768px) {
    .chart-row-2 { grid-template-columns:1fr; }
    .cards { grid-template-columns:repeat(auto-fit, minmax(130px,1fr)); }
  }
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <h1>📊 BatchBox 用量监控</h1>
    <span class="status-dot"></span>
    <span class="refresh-info" id="refreshInfo">加载中...</span>
  </div>
</div>

<!-- Tab bar -->
<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('overview')">📊 总览</button>
  <button class="tab-btn" onclick="switchTab('machines')">👥 机器详情</button>
  <button class="tab-btn" onclick="switchTab('providers')">供应商/API数量详情</button>
</div>

<!-- Controls -->
<div class="controls">
  <div class="controls-left">
    <select id="machineSelect" onchange="onMachineChange()">
      <option value="">全部机器</option>
    </select>
    <select id="statusSelect" onchange="onStatusChange()">
      <option value="all">所有状态</option>
      <option value="success">✅ 仅成功</option>
      <option value="fail">❌ 仅失败</option>
    </select>
    <span id="drillBack" style="display:none; cursor:pointer; font-size:0.85rem; color:var(--accent);"
          onclick="clearDrill()">← 取消日期筛选</span>
  </div>
  <div class="filters" id="filterBtns">
    <button id="dateBtn" class="date-picker" onclick="toggleDatePicker(event)">📅 日期</button>
    <div class="fp-cal-wrap" id="fpCalWrap"></div>
    <button class="active" onclick="setFilter('today')">今日</button>
    <button onclick="setFilter('week')">本周</button>
    <button onclick="setFilter('all')">全部</button>
  </div>
</div>

<!-- =================== Tab 1: Overview =================== -->
<div class="tab-page active" id="page-overview">
  <div class="cards" id="summaryCards"></div>

  <!-- Timeline chart -->
  <div class="chart-row">
    <div class="chart-box">
      <div class="chart-label">📈 生成活动时间线</div>
      <div class="drill-hint" id="drillHint">💡 点击柱子钻取该日详情</div>
      <canvas id="timelineChart"></canvas>
    </div>
  </div>

  <!-- Machine bar + Model doughnut -->
  <div class="chart-row-2">
    <div class="chart-box">
      <div class="chart-label">📊 机器生图排行</div>
      <canvas id="machineChart"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-label">🥧 模型使用分布</div>
      <canvas id="modelChart"></canvas>
    </div>
  </div>

  <!-- Recent activity table -->
  <div class="section">
    <div class="section-title">🕐 最近活动 (附失败分析)</div>
    <div class="recent-table">
      <table id="recentTable"><thead><tr>
        <th>时间</th><th>机器</th><th>节点</th><th>模型</th><th>批次</th>
        <th>供应商</th><th>生成</th><th>保存</th><th>状态 (鼠标悬浮看原因)</th><th>耗时</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </div>
</div>

<!-- =================== Tab 2: Machine Details =================== -->
<div class="tab-page" id="page-machines">
  <div style="margin-bottom:16px; display:flex; gap:10px; align-items:center; background:var(--card-bg); padding:10px 16px; border:1px solid var(--border); border-radius:10px;">
    <span style="font-size:0.85rem; color:var(--text-dim);">排序方式：</span>
    <select id="mSortBy" onchange="onSortChange()">
      <option value="success">成功率</option>
      <option value="gen">生成数量</option>
      <option value="dur_avg">均耗 (秒)</option>
    </select>
    <select id="mSortOrder" onchange="onSortChange()">
      <option value="asc">递增 (从小到大)</option>
      <option value="desc">递减 (从大到小)</option>
    </select>
  </div>
  <div class="machine-grid" id="machineGrid"></div>
</div>

<!-- =================== Tab 3: Provider/API Details =================== -->
<div class="tab-page" id="page-providers">
  <div class="chart-row">
    <div class="chart-box provider-chart-box">
      <div class="chart-label">供应商生图占比</div>
      <canvas id="providerChart"></canvas>
    </div>
  </div>
  <div class="section">
    <div class="section-title">供应商 / API Key 生图统计</div>
    <div id="providerUsageList" class="provider-usage-list"></div>
  </div>
</div>
</div>

<script>
// ==================== State ====================
let currentFilter = 'today';
let currentMachine = '';
let currentStatus = 'all';
let drillDate = '';   // '' = no drill;  'YYYY-MM-DD' = drilled
let refreshTimer = null;
let chartTimeline = null, chartMachine = null, chartModel = null;
let chartProvider = null;
let machineChartInstances = {};  // Tab2 mini pies
let fpInstance = null;
let fpOpen = false;
let mSortBy = 'success';
let mSortOrder = 'asc';
let machineNotes = {};  // { machineName: "note text" }

const NODE_LABELS = {
  'image':'🎨 图片','independent':'🚀 独立','editor':'🔧 编辑',
  'blur_upscale':'🔍 放大','text':'📝 文本','video':'🎬 视频','audio':'🎵 音频'
};
const PALETTE = ['#6c5ce7','#0984e3','#00b894','#fdcb6e','#e17055','#00cec9',
  '#a29bfe','#74b9ff','#55efc4','#ffeaa7','#fab1a0','#81ecec'];

// ==================== Helpers ====================
function fmt(ts) {
  if (!ts) return '-';
  try { return new Date(ts).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
  catch { return ts; }
}
function fmtDT(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    return d.toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'})
      + ' ' + d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
  } catch { return ts; }
}
function fmtDur(s) {
  if (!s || s <= 0) return '-';
  return s >= 60 ? (s/60).toFixed(1)+'m' : s.toFixed(1)+'s';
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));
}
function getNote(name) { return machineNotes[name] || ''; }
function displayName(name) {
  const n = getNote(name);
  return n ? name + ' (' + n + ')' : name;
}
function providerSummary(record) {
  const entries = Array.isArray(record.provider_usage) ? record.provider_usage : [];
  if (!entries.length) return '';
  const totals = {};
  entries.forEach(item => {
    const label = item.provider_label || item.provider || '';
    if (!label) return;
    totals[label] = (totals[label] || 0) + (Number(item.gen) || 0);
  });
  return Object.entries(totals)
    .sort((a,b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([label, gen]) => gen > 0 ? `${label}(${gen})` : label)
    .join(' / ');
}

// ==================== Machine Notes ====================
async function loadNotes() {
  try {
    const resp = await fetch('/api/notes');
    machineNotes = await resp.json();
  } catch(e) { machineNotes = {}; }
}
async function saveNote(machine, note) {
  machineNotes[machine] = note;
  try {
    await fetch('/api/notes', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({machine, note})
    });
  } catch(e) { console.error('Save note failed', e); }
}
function startEditNote(machine, spanEl) {
  const cur = getNote(machine);
  const input = document.createElement('input');
  input.className = 'm-note-input';
  input.value = cur;
  input.placeholder = '输入备注…';
  spanEl.replaceWith(input);
  input.focus();
  const finish = () => {
    const val = input.value.trim();
    saveNote(machine, val);
    const span = document.createElement('span');
    span.className = 'm-note';
    span.title = '点击编辑备注';
    span.textContent = val ? '📝 ' + val : '📝 添加备注';
    span.onclick = () => startEditNote(machine, span);
    input.replaceWith(span);
  };
  input.onblur = finish;
  input.onkeydown = (e) => { if (e.key === 'Enter') input.blur(); };
}

// ==================== Tab switching ====================
function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));
  const tabIndex = { overview: 1, machines: 2, providers: 3 }[tab] || 1;
  const pageId = 'page-' + (tabIndex === 1 ? 'overview' : tabIndex === 2 ? 'machines' : 'providers');
  document.querySelector(`.tab-btn:nth-child(${tabIndex})`).classList.add('active');
  document.getElementById(pageId).classList.add('active');
}

// ==================== Filter / Machine / Drill ====================
function setFilter(f) {
  currentFilter = f;
  drillDate = '';
  document.getElementById('drillBack').style.display = 'none';
  document.getElementById('fpCalWrap').style.display = 'none';
  document.getElementById('dateBtn').textContent = '📅 日期';
  document.getElementById('dateBtn').classList.remove('fp-active');
  fpOpen = false;
  if (fpInstance) fpInstance.clear();
  document.querySelectorAll('#filterBtns button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  fetchStats();
}
function onMachineChange() {
  currentMachine = document.getElementById('machineSelect').value;
  fetchStats();
}
function onStatusChange() {
  currentStatus = document.getElementById('statusSelect').value;
  fetchStats();
}
function onSortChange() {
  mSortBy = document.getElementById('mSortBy').value;
  mSortOrder = document.getElementById('mSortOrder').value;
  fetchStats();
}
function selectMachine(name) {
  currentMachine = name;
  document.getElementById('machineSelect').value = name;
  fetchStats();
}
function clearDrill() {
  drillDate = '';
  document.getElementById('drillBack').style.display = 'none';
  document.getElementById('fpCalWrap').style.display = 'none';
  document.getElementById('dateBtn').textContent = '📅 日期';
  document.getElementById('dateBtn').classList.remove('fp-active');
  fpOpen = false;
  if (fpInstance) fpInstance.clear();
  // revert to week
  currentFilter = 'week';
  document.querySelectorAll('#filterBtns button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#filterBtns button')[2].classList.add('active');
  fetchStats();
}

function initFlatpickr(validDates) {
    if (fpInstance) {
        fpInstance.set('enable', validDates);
        return;
    }
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    
    // Create a hidden input inside the calendar wrapper 
    const wrap = document.getElementById('fpCalWrap');
    const hiddenInput = document.createElement('input');
    hiddenInput.type = 'text';
    hiddenInput.style.display = 'none';
    wrap.appendChild(hiddenInput);

    fpInstance = flatpickr(hiddenInput, {
        appendTo: wrap,
        inline: true,
        locale: "zh",
        minDate: new Date().getFullYear() + "-04-01",
        enable: validDates,
        onChange: function(selectedDates, dateStr) {
            if (dateStr) {
                drillDate = dateStr;
                document.getElementById('dateBtn').textContent = '\ud83d\udcc5 ' + dateStr;
                document.querySelectorAll('#filterBtns button').forEach(b => b.classList.remove('active'));
                document.getElementById('drillBack').style.display = 'inline';
                fpOpen = false;
                wrap.style.display = 'none';
                document.getElementById('dateBtn').classList.remove('fp-active');
                fetchStats();
            }
        },
        onDayCreate: function(dObj, dStr, fp, dayElem) {
            const y = dayElem.dateObj.getFullYear();
            const m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
            const d = String(dayElem.dateObj.getDate()).padStart(2, '0');
            const ds = `${y}-${m}-${d}`;

            if (ds === todayStr) {
                dayElem.style.backgroundColor = '#6c5ce7';
                dayElem.style.color = '#fff';
                dayElem.style.fontWeight = 'bold';
                dayElem.style.borderColor = '#6c5ce7';
                if (validDates.includes(todayStr)) {
                   dayElem.innerHTML += '<span style="display:block;width:4px;height:4px;border-radius:50%;background:#fff;margin:0 auto;position:absolute;bottom:3px;left:50%;transform:translateX(-50%);"></span>';
                }
            } else if (validDates.includes(ds)) {
                dayElem.style.backgroundColor = 'rgba(108, 92, 231, 0.3)';
            }
        }
    });
}

function toggleDatePicker(e) {
    e && e.stopPropagation();
    const wrap = document.getElementById('fpCalWrap');
    const btn = document.getElementById('dateBtn');
    fpOpen = !fpOpen;
    wrap.style.display = fpOpen ? 'block' : 'none';
    btn.classList.toggle('fp-active', fpOpen);
}

// Close calendar when clicking outside
document.addEventListener('click', function(e) {
    if (!fpOpen) return;
    const wrap = document.getElementById('fpCalWrap');
    const btn = document.getElementById('dateBtn');
    if (!wrap.contains(e.target) && e.target !== btn) {
        fpOpen = false;
        wrap.style.display = 'none';
        btn.classList.remove('fp-active');
    }
});

// ==================== Data fetch ====================
async function fetchStats() {
  try {
    let url = '/api/stats?filter=' + currentFilter;
    if (currentMachine) url += '&machine=' + encodeURIComponent(currentMachine);
    if (currentStatus !== 'all') url += '&status=' + encodeURIComponent(currentStatus);
    if (drillDate) url += '&date=' + drillDate;
    const resp = await fetch(url);
    const data = await resp.json();
    if (data.valid_dates) initFlatpickr(data.valid_dates);
    renderOverview(data);
    renderMachineDetails(data);
    updateMachineSelect(data.machine_list);
    document.getElementById('refreshInfo').textContent =
      '上次刷新: ' + new Date().toLocaleTimeString('zh-CN') + ' (每5秒自动)';
  } catch(e) {
    document.getElementById('refreshInfo').textContent = '⚠️ 加载失败: ' + e.message;
  }
}

function updateMachineSelect(list) {
  const sel = document.getElementById('machineSelect');
  const cur = sel.value;
  const opts = '<option value="">全部机器</option>' +
    list.map(m => {
      const n = getNote(m);
      const label = n ? m + ' (' + n + ')' : m;
      return `<option value="${m}" ${m===cur?'selected':''}>${label}</option>`;
    }).join('');
  sel.innerHTML = opts;
}

// ==================== Tab 1: Overview ====================
function renderOverview(data) {
  // --- Summary cards ---
  document.getElementById('summaryCards').innerHTML = `
    <div class="card"><div class="card-label">任务数${currentStatus==='fail'?'(过滤后)':''}</div>
      <div class="card-value">${data.total_tasks}</div></div>
    <div class="card"><div class="card-label">API 调用</div>
      <div class="card-value blue">${data.total_api_calls}</div></div>
    <div class="card"><div class="card-label">生成图片</div>
      <div class="card-value green">${data.total_generated}</div></div>
    <div class="card"><div class="card-label">成功率</div>
      <div class="card-value green">${data.success_rate}%</div></div>
    <div class="card"><div class="card-label">活跃机器</div>
      <div class="card-value">${data.machines.length}</div></div>
    <div class="card"><div class="card-label">⏱ 平均耗时</div>
      <div class="card-value teal">${fmtDur(data.dur_avg)}</div></div>
    <div class="card"><div class="card-label">⚡ 最短耗时</div>
      <div class="card-value green">${fmtDur(data.dur_min)}</div></div>
    <div class="card"><div class="card-label">🐢 最长耗时</div>
      <div class="card-value orange">${fmtDur(data.dur_max)}</div></div>
  `;

  // --- Timeline chart ---
  const tlKeys = Object.keys(data.timeline);
  const tlTasks = tlKeys.map(k => data.timeline[k].tasks);
  const tlAPI = tlKeys.map(k => data.timeline[k].api_calls);
  const isWeekOrAll = (currentFilter === 'week' || currentFilter === 'all') && !drillDate;

  document.getElementById('drillHint').style.display = isWeekOrAll ? 'block' : 'none';

  if (!chartTimeline) {
    chartTimeline = new Chart(document.getElementById('timelineChart'), {
      type: 'bar',
      data: {
        labels: tlKeys,
        datasets: [
          { label: '任务数', data: tlTasks, backgroundColor: 'rgba(108,92,231,0.7)',
            borderColor: '#6c5ce7', borderWidth: 1, borderRadius: 4, order: 2 },
          { label: 'API 调用', data: tlAPI, type: 'line',
            borderColor: '#0984e3', backgroundColor: 'rgba(9,132,227,0.1)',
            tension: 0.3, pointRadius: 3, fill: true, order: 1 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        animation: { duration: 400 },
        plugins: {
          legend: { labels: { color: '#8b8fa3', usePointStyle: true, pointStyle: 'circle' } },
        },
        scales: {
          x: { ticks: { color: '#8b8fa3' }, grid: { color: 'rgba(45,49,66,0.5)' } },
          y: { beginAtZero: true, ticks: { color: '#8b8fa3' }, grid: { color: 'rgba(45,49,66,0.5)' } },
        },
        onClick: (evt, elems) => {
          if (!isWeekOrAll || !elems.length) return;
          const idx = elems[0].index;
          const label = chartTimeline.data.labels[idx];
          const now = new Date();
          const year = now.getFullYear();
          const parts = label.split('-');
          drillDate = year + '-' + parts[0].padStart(2,'0') + '-' + parts[1].padStart(2,'0');
          if (fpInstance) fpInstance.setDate(drillDate);
          document.getElementById('dateBtn').textContent = '📅 ' + drillDate;
          document.getElementById('drillBack').style.display = 'inline';
          document.querySelectorAll('#filterBtns button').forEach(b => b.classList.remove('active'));
          fetchStats();
        },
      },
    });
  } else {
    chartTimeline.data.labels = tlKeys;
    chartTimeline.data.datasets[0].data = tlTasks;
    chartTimeline.data.datasets[1].data = tlAPI;
    chartTimeline.update('none'); // Update without full animation for smoother feel
  }

  // --- Machine bar chart ---
  const mSorted = [...data.machines].sort((a,b) => b.gen - a.gen).slice(0, 15);
  const mNames = mSorted.map(m => m.name); // Keep full name for tooltip
  const mGen = mSorted.map(m => m.gen);
  const mColors = mSorted.map((_,i) => PALETTE[i % PALETTE.length]);

  if (!chartMachine) {
    chartMachine = new Chart(document.getElementById('machineChart'), {
      type: 'bar',
      data: {
        labels: mNames,
        datasets: [{ data: mGen, backgroundColor: mColors, borderRadius: 4 }],
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, ticks: { color: '#8b8fa3' }, grid: { color: 'rgba(45,49,66,0.5)' } },
          y: { 
            ticks: { 
              autoSkip: false,
              color: '#8b8fa3', 
              font: { size: 11 },
              callback: function(value, index, values) {
                const label = this.getLabelForValue(value);
                return label.length > 15 ? '…' + label.substring(label.length - 15) : label;
              }
            }, 
            grid: { display: false } 
          },
        },
        onClick: (evt, elems) => {
          if (!elems.length) return;
          const idx = elems[0].index;
          selectMachine(mSorted[idx].name);
        },
      },
    });
  } else {
    chartMachine.data.labels = mNames;
    chartMachine.data.datasets[0].data = mGen;
    chartMachine.data.datasets[0].backgroundColor = mColors;
    chartMachine.update('none');
  }

  // --- Model doughnut chart ---
  const modelEntries = Object.entries(data.models).sort((a,b) => b[1]-a[1]);
  const modelNames = modelEntries.map(e => e[0]);
  const modelCounts = modelEntries.map(e => e[1]);
  const modelColors = modelNames.map((_,i) => PALETTE[i % PALETTE.length]);

  if (!chartModel) {
    chartModel = new Chart(document.getElementById('modelChart'), {
      type: 'doughnut',
      data: {
        labels: modelNames,
        datasets: [{ data: modelCounts,
          backgroundColor: modelColors,
          borderWidth: 0, hoverOffset: 6 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        cutout: '55%',
        animation: { duration: 400 },
        plugins: {
          legend: { position: 'right', labels: { color: '#8b8fa3', padding: 10, usePointStyle: true, pointStyle: 'circle' } },
        },
      },
    });
  } else {
    chartModel.data.labels = modelNames;
    chartModel.data.datasets[0].data = modelCounts;
    chartModel.data.datasets[0].backgroundColor = modelColors;
    chartModel.update('none');
  }

  renderProviderUsage(data.providers_usage || []);

  // --- Recent activity table ---
  const rtb = document.querySelector('#recentTable tbody');
  if (!data.recent.length) {
    rtb.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-dim)">暂无数据</td></tr>';
  } else {
    rtb.innerHTML = data.recent.map(r => {
      let statusHtml;
      if (r.ok) {
        statusHtml = '<span class="success-badge">✅</span>';
      } else {
        const fullErr = r.err || 'Unknown Error';
        const safeErr = fullErr.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const shortErr = fullErr.length > 35 ? fullErr.substring(0, 35) + '...' : fullErr;
        statusHtml = '<span class="fail-badge" style="cursor:help;" title="' + safeErr + '">❌ ' + shortErr + '</span>';
      }
      
      const node = NODE_LABELS[r.node] || r.node;
      const mNote = getNote(r.machine);
      const mLabel = mNote ? r.machine + ' <span style="font-size:0.75rem;color:var(--text-dim)">(' + mNote + ')</span>' : r.machine;
      const providerText = providerSummary(r);
      return `<tr>
        <td>${fmt(r.ts)}</td>
        <td style="cursor:pointer; color:var(--accent);" onclick="selectMachine('${r.machine}')" title="点击查看此机器详情">${mLabel}</td><td>${node}</td>
        <td>${r.model}</td><td>${r.batch}</td>
        <td>${esc(providerText)}</td>
        <td>${r.gen}</td><td>${r.saved}</td>
        <td>${statusHtml}</td><td>${fmtDur(r.dur_s)}</td>
      </tr>`;
    }).join('');
  }
}

function renderProviderUsage(items) {
  renderProviderChart(items);
  const box = document.getElementById('providerUsageList');
  if (!box) return;
  if (!items.length) {
    box.innerHTML = '<div class="empty-block">暂无供应商 / API Key 明细；新版本记录后会自动显示</div>';
    return;
  }

  box.innerHTML = items.map(provider => {
    const keys = provider.keys || [];
    const keyRows = keys.length
      ? keys.map(k => `
        <div class="provider-key-row">
          <span class="provider-key-name" title="${esc(k.key_label)}">${esc(k.key_label)}</span>
          <span class="provider-key-gen">${k.gen} 张</span>
        </div>
      `).join('')
      : '<div class="provider-key-row"><span class="provider-key-name">未记录Key</span><span class="provider-key-gen">0 张</span></div>';
    return `
      <div class="provider-card">
        <div class="provider-card-head">
          <span title="${esc(provider.provider)}">${esc(provider.provider_label || provider.provider)}</span>
          <span class="provider-total">${provider.gen} 张</span>
        </div>
        ${keyRows}
      </div>
    `;
  }).join('');
}

function renderProviderChart(items) {
  const canvas = document.getElementById('providerChart');
  if (!canvas) return;

  const hasData = items.length > 0;
  const labels = hasData
    ? items.map(p => p.provider_label || p.provider || '未知供应商')
    : ['暂无数据'];
  const counts = hasData ? items.map(p => p.gen || 0) : [1];
  const colors = hasData
    ? labels.map((_, i) => PALETTE[i % PALETTE.length])
    : ['#2d3142'];

  if (!chartProvider) {
    chartProvider = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: counts,
          backgroundColor: colors,
          borderWidth: 0,
          hoverOffset: hasData ? 6 : 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '58%',
        animation: { duration: 400 },
        plugins: {
          legend: {
            position: 'right',
            labels: { color: '#8b8fa3', padding: 12, usePointStyle: true, pointStyle: 'circle' },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => hasData ? `${ctx.label}: ${ctx.parsed} 张` : '暂无数据',
            },
          },
        },
      },
    });
  } else {
    chartProvider.data.labels = labels;
    chartProvider.data.datasets[0].data = counts;
    chartProvider.data.datasets[0].backgroundColor = colors;
    chartProvider.data.datasets[0].hoverOffset = hasData ? 6 : 0;
    chartProvider.update('none');
  }
}

// ==================== Tab 2: Machine Details ====================
function renderMachineDetails(data) {
  const grid = document.getElementById('machineGrid');
  if (!data.machines.length) {
    grid.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:60px 20px">暂无数据</div>';
    return;
  }

  // Remove existing "暂无数据" placeholder or old machines
  const currentMachinesSet = new Set(data.machines.map(m => m.name));
  Array.from(grid.children).forEach(child => {
    if (child.id && child.id.startsWith('mcard-')) {
      const mNameUrlSafe = child.getAttribute('data-mname');
      if (!currentMachinesSet.has(mNameUrlSafe)) {
        const canvasId = 'pie-' + mNameUrlSafe.replace(/[^a-zA-Z0-9]/g, '_');
        if (machineChartInstances[canvasId]) {
          machineChartInstances[canvasId].destroy();
          delete machineChartInstances[canvasId];
        }
        grid.removeChild(child);
      }
    } else {
      // If it has no 'mcard-' ID (like the placeholder "暂无数据" text/div), remove it!
      grid.removeChild(child);
    }
  });

  // Sort dynamically based on user controls
  const sorted = [...data.machines].sort((a,b) => {
    let valA = 0, valB = 0;
    if (mSortBy === 'success') {
      valA = a.tasks ? a.success/a.tasks : 1;
      valB = b.tasks ? b.success/b.tasks : 1;
    } else if (mSortBy === 'gen') {
      valA = a.gen;
      valB = b.gen;
    } else if (mSortBy === 'dur_avg') {
      valA = a.dur_avg;
      valB = b.dur_avg;
    }
    return mSortOrder === 'asc' ? valA - valB : valB - valA;
  });

  // Update existing DOM cards or create new ones
  sorted.forEach(m => {
    const rate = m.tasks ? Math.round(m.success/m.tasks*100) : 0;
    const rateColor = rate >= 80 ? 'var(--green)' : rate >= 50 ? 'var(--yellow)' : 'var(--red)';
    const cleanId = m.name.replace(/[^a-zA-Z0-9]/g, '_');
    const cardId = 'mcard-' + cleanId;
    const canvasId = 'pie-' + cleanId;
    
    let card = document.getElementById(cardId);
    if (!card) {
      // Create new card
      card = document.createElement('div');
      card.className = 'machine-card';
      card.id = cardId;
      card.setAttribute('data-mname', m.name);
      const noteText = getNote(m.name);
      const noteDisplay = noteText ? '📝 ' + noteText : '📝 添加备注';
      card.innerHTML = `
        <div class="machine-card-header" title="${m.name}">
          ${m.name}
          <span class="m-rate" style="float:right;font-size:0.8rem;color:${rateColor}">${rate}%</span>
          <br><span class="m-note" title="点击编辑备注">${noteDisplay}</span>
        </div>
        <div class="machine-card-chart">
          <canvas id="${canvasId}"></canvas>
        </div>
        <div class="machine-card-stats">
          <span>任务: <span class="val m-tasks">${m.tasks}</span></span>
          <span>生成: <span class="val m-gen">${m.gen}</span></span>
          <span>保存: <span class="val m-saved">${m.saved}</span></span>
          <span>均耗: <span class="val m-dur">${fmtDur(m.dur_avg)}</span></span>
          <span>最近: <span class="val m-last">${fmtDT(m.last_ts)}</span></span>
        </div>`;
      grid.appendChild(card);

      // Initialize chart for the new card
      const canvas = document.getElementById(canvasId);
      if (canvas) {
        machineChartInstances[canvasId] = new Chart(canvas, {
          type: 'doughnut',
          data: {
            labels: ['成功', '失败'],
            datasets: [{
              data: [m.success, m.fail],
              backgroundColor: ['#00b894', '#e17055'],
              borderWidth: 0, hoverOffset: 4,
            }],
          },
          options: {
            responsive: true, maintainAspectRatio: true,
            cutout: '50%', animation: { duration: 400 },
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: (ctx) => ctx.label + ': ' + ctx.parsed + ' 次' } },
            },
          },
        });
      }
      // Bind note click handler
      const noteSpan = card.querySelector('.m-note');
      if (noteSpan) noteSpan.onclick = () => startEditNote(m.name, noteSpan);
    } else {
      // Skip update if user is currently editing a note on this card
      if (card.querySelector('.m-note-input')) return;
      // Update DOM values in-place
      card.querySelector('.m-rate').textContent = rate + '%';
      card.querySelector('.m-rate').style.color = rateColor;
      card.querySelector('.m-tasks').textContent = m.tasks;
      card.querySelector('.m-gen').textContent = m.gen;
      card.querySelector('.m-saved').textContent = m.saved;
      card.querySelector('.m-dur').textContent = fmtDur(m.dur_avg);
      card.querySelector('.m-last').textContent = fmtDT(m.last_ts);
      
      // Re-append to grid to respect sorted order 
      // (appendChild moves the node to the end if it already exists)
      grid.appendChild(card);
      
      // Update chart data in-place
      if (machineChartInstances[canvasId]) {
        const cData = machineChartInstances[canvasId].data.datasets[0].data;
        if (cData[0] !== m.success || cData[1] !== m.fail) {
          cData[0] = m.success;
          cData[1] = m.fail;
          machineChartInstances[canvasId].update('none'); // Update without flashing
        }
      }
    }
  });
}

// ==================== Init ====================
loadNotes().then(() => {
  fetchStats();
  refreshTimer = setInterval(fetchStats, 5000);
});
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    data_dir = ""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif parsed.path == "/api/stats":
            params = parse_qs(parsed.query)
            date_filter = params.get("filter", ["today"])[0]
            machine_filter = params.get("machine", [""])[0]
            date_exact = params.get("date", [""])[0]
            status_filter = params.get("status", ["all"])[0]
            records = load_all_records(self.data_dir, date_filter,
                                       machine_filter, date_exact, status_filter)
            stats = compute_stats(records, date_filter, date_exact)
            stats["valid_dates"] = get_valid_dates(self.data_dir)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(stats, ensure_ascii=False).encode("utf-8"))
        elif parsed.path == "/api/notes":
            notes = load_machine_notes(self.data_dir)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(notes, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/notes":
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                machine = payload.get("machine", "")
                note = payload.get("note", "")
                if machine:
                    notes = load_machine_notes(self.data_dir)
                    notes[machine] = note
                    save_machine_notes(self.data_dir, notes)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="BatchBox Usage Dashboard")
    parser.add_argument("--port", type=int, default=9090, help="Server port (default: 9090)")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Data directory (default: auto-detect NAS)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser")
    args = parser.parse_args()

    data_dir = args.data_dir or find_data_dir()
    if not data_dir:
        print("ERROR: Cannot find data directory.")
        print("  Specify with: python dashboard.py --data-dir \"Z:\\ComfyUI_Master\\shared_cache\"")
        print("  Or set BATCHBOX_SHARED_CACHE environment variable.")
        sys.exit(1)

    logs_dir = os.path.join(data_dir, "usage_logs")
    if not os.path.isdir(logs_dir):
        print(f"Note: {logs_dir} does not exist yet. Dashboard will show empty until data arrives.")

    DashboardHandler.data_dir = data_dir

    # Try the requested port, then fall back
    port = args.port
    for attempt in range(10):
        try:
            server = HTTPServer(("127.0.0.1", port), DashboardHandler)
            break
        except OSError:
            port += 1
    else:
        print(f"ERROR: Cannot find free port (tried {args.port}-{port})")
        sys.exit(1)

    url = f"http://localhost:{port}"
    print(f"┌─────────────────────────────────────────┐")
    print(f"│  📊 BatchBox Usage Dashboard            │")
    print(f"│  URL:      {url:<28s} │")
    print(f"│  Data dir: {data_dir[:28]:<28s} │")
    print(f"│  Press Ctrl+C to stop                   │")
    print(f"└─────────────────────────────────────────┘")

    if not args.no_browser:
        webbrowser.open(url)

    # Start the admin warning daemon
    threading.Thread(target=admin_warning_loop, args=(data_dir,), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()

def admin_warning_loop(data_dir):
    """Background loop that warns the admin locally if a machine exceeds usage limits today."""
    admin_warn_tiers = {}
    
    while True:
        try:
            today_str = datetime.now(_TZ_CST).strftime('%Y-%m-%d')
            logs_dir = os.path.join(data_dir, "usage_logs")
            if not os.path.isdir(logs_dir):
                time.sleep(30)
                continue
                
            for machine_dir in glob.glob(os.path.join(logs_dir, "*")):
                if not os.path.isdir(machine_dir):
                    continue
                machine_name = os.path.basename(machine_dir)
                filepath = os.path.join(machine_dir, f"usage_{today_str}.jsonl")
                
                if not os.path.exists(filepath):
                    continue
                    
                total_gen = 0
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            total_gen += json.loads(line).get("gen", 0)
                        except Exception:
                            pass
                
                tier = 0
                if total_gen >= 800:
                    tier = 1 + (total_gen - 800) // 200
                
                if tier > admin_warn_tiers.get(machine_name, 0):
                    admin_warn_tiers[machine_name] = tier
                    warning_msg = f"🚨警告：机器 {machine_name} 今日生图已达 {total_gen} 张！"
                    threading.Thread(
                        target=lambda msg=warning_msg: ctypes.windll.user32.MessageBoxW(0, msg, "学生疯狂生图警报", 0x30 | 0x0),
                        daemon=True
                    ).start()
        except Exception:
            pass
        time.sleep(30)


if __name__ == "__main__":
    main()
