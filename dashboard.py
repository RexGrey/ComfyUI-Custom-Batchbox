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


def load_all_records(data_dir: str, date_filter: str = "all") -> list:
    """
    Load all JSONL records from usage_logs subdirectories.
    
    Args:
        data_dir: Root directory containing usage_logs/
        date_filter: "today", "week", or "all"
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
        for jsonl_file in glob.glob(os.path.join(machine_dir, "usage_*.jsonl")):
            # Date filter: skip files outside date range
            basename = os.path.basename(jsonl_file)
            file_date = basename.replace("usage_", "").replace(".jsonl", "")
            
            if date_filter == "today" and file_date != today_str:
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
                                records.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            except (IOError, PermissionError):
                pass

    return records


def compute_stats(records: list) -> dict:
    """Compute aggregate statistics from records."""
    if not records:
        return {
            "total_tasks": 0,
            "total_generated": 0,
            "total_saved": 0,
            "success_rate": 0,
            "total_api_calls": 0,
            "machines": [],
            "models": {},
            "nodes": {},
            "recent": [],
        }

    total_tasks = len(records)
    total_gen = sum(r.get("gen", 0) for r in records)
    total_saved = sum(r.get("saved", 0) for r in records)
    total_api_calls = sum(r.get("batch", 1) for r in records)
    success_count = sum(1 for r in records if r.get("ok"))
    success_rate = round(success_count / total_tasks * 100, 1) if total_tasks else 0

    # Per-machine stats
    machine_map = {}
    for r in records:
        mid = r.get("machine", "unknown")
        if mid not in machine_map:
            machine_map[mid] = {"name": mid, "tasks": 0, "gen": 0, "saved": 0,
                                "api_calls": 0, "success": 0, "last_ts": ""}
        m = machine_map[mid]
        m["tasks"] += 1
        m["gen"] += r.get("gen", 0)
        m["saved"] += r.get("saved", 0)
        m["api_calls"] += r.get("batch", 1)
        if r.get("ok"):
            m["success"] += 1
        ts = r.get("ts", "")
        if ts > m["last_ts"]:
            m["last_ts"] = ts

    machines = sorted(machine_map.values(), key=lambda x: x["name"])

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

    # Recent records (last 50)
    sorted_records = sorted(records, key=lambda x: x.get("ts", ""), reverse=True)
    recent = sorted_records[:50]

    return {
        "total_tasks": total_tasks,
        "total_generated": total_gen,
        "total_saved": total_saved,
        "total_api_calls": total_api_calls,
        "success_rate": success_rate,
        "machines": machines,
        "models": model_map,
        "nodes": node_map,
        "recent": recent,
    }


# ==========================================
# Embedded HTML Dashboard
# ==========================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BatchBox Usage Dashboard</title>
<style>
  :root {
    --bg: #0f1117; --card-bg: #1a1d27; --border: #2d3142;
    --text: #e4e6eb; --text-dim: #8b8fa3; --accent: #6c5ce7;
    --green: #00b894; --red: #e17055; --blue: #0984e3; --yellow: #fdcb6e;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
    padding: 20px; max-width: 1400px; margin: 0 auto;
  }
  h1 { font-size: 1.5rem; margin-bottom: 8px; }
  .header { display:flex; justify-content:space-between; align-items:center;
    margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
  .header-left { display:flex; align-items:center; gap: 12px; }
  .status-dot { width:8px; height:8px; border-radius:50%; background:var(--green);
    display:inline-block; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
  .filters { display:flex; gap:6px; }
  .filters button {
    padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px;
    background: transparent; color: var(--text-dim); cursor: pointer;
    font-size: 0.85rem; transition: all 0.2s;
  }
  .filters button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .filters button:hover { border-color: var(--accent); }

  .cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 14px; margin-bottom: 20px; }
  .card {
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; transition: transform 0.2s;
  }
  .card:hover { transform: translateY(-2px); }
  .card-label { font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 4px; }
  .card-value { font-size: 1.8rem; font-weight: 700; }
  .card-value.green { color: var(--green); }
  .card-value.blue { color: var(--blue); }
  .card-value.yellow { color: var(--yellow); }

  .section { margin-bottom: 20px; }
  .section-title { font-size: 1rem; margin-bottom: 10px; color: var(--text-dim);
    border-bottom: 1px solid var(--border); padding-bottom: 6px; }

  table { width:100%; border-collapse:collapse; font-size:0.85rem; }
  th { text-align:left; padding:8px 10px; border-bottom:2px solid var(--border);
    color:var(--text-dim); font-weight:600; white-space:nowrap; }
  td { padding:8px 10px; border-bottom:1px solid var(--border); }
  tr:hover td { background: rgba(108,92,231,0.08); }
  .success-badge { color: var(--green); }
  .fail-badge { color: var(--red); }

  .model-bars { display:flex; flex-direction:column; gap:6px; }
  .model-bar { display:flex; align-items:center; gap:10px; }
  .model-bar-name { width:160px; font-size:0.85rem; text-align:right;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .model-bar-track { flex:1; height:22px; background:var(--border); border-radius:4px;
    overflow:hidden; position:relative; }
  .model-bar-fill { height:100%; background: linear-gradient(90deg, var(--accent), var(--blue));
    border-radius:4px; transition: width 0.5s; min-width:2px; }
  .model-bar-count { width:50px; font-size:0.8rem; color:var(--text-dim); }

  .recent-table { max-height: 400px; overflow-y: auto; }
  .recent-table::-webkit-scrollbar { width:6px; }
  .recent-table::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }

  .refresh-info { font-size:0.75rem; color:var(--text-dim); }
  .empty-state { text-align:center; padding:60px 20px; color:var(--text-dim); }
  .empty-state svg { width:64px; height:64px; margin-bottom:16px; opacity:0.3; }
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <h1>📊 BatchBox 用量监控</h1>
    <span class="status-dot"></span>
    <span class="refresh-info" id="refreshInfo">加载中...</span>
  </div>
  <div class="filters">
    <button class="active" onclick="setFilter('today')">今日</button>
    <button onclick="setFilter('week')">本周</button>
    <button onclick="setFilter('all')">全部</button>
  </div>
</div>

<div class="cards" id="summaryCards"></div>

<div class="section">
  <div class="section-title">📋 按机器统计</div>
  <table id="machineTable"><thead><tr>
    <th>机器</th><th>任务数</th><th>API 调用</th><th>生成图片</th><th>保存图片</th><th>成功率</th><th>最近活跃</th>
  </tr></thead><tbody></tbody></table>
</div>

<div class="section">
  <div class="section-title">📦 模型分布</div>
  <div class="model-bars" id="modelBars"></div>
</div>

<div class="section">
  <div class="section-title">🕐 最近活动</div>
  <div class="recent-table">
    <table id="recentTable"><thead><tr>
      <th>时间</th><th>机器</th><th>节点</th><th>模型</th><th>批次</th><th>生成</th><th>保存</th><th>状态</th><th>耗时</th>
    </tr></thead><tbody></tbody></table>
  </div>
</div>

<script>
let currentFilter = 'today';
let refreshTimer = null;

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll('.filters button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  fetchStats();
}

function formatTime(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  } catch { return ts; }
}

function formatDateTime(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    return d.toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'})
      + ' ' + d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
  } catch { return ts; }
}

const NODE_LABELS = {
  'image':'🎨 图片','independent':'🚀 独立','editor':'🔧 编辑',
  'blur_upscale':'🔍 放大','text':'📝 文本','video':'🎬 视频','audio':'🎵 音频'
};

async function fetchStats() {
  try {
    const resp = await fetch('/api/stats?filter=' + currentFilter);
    const data = await resp.json();
    renderDashboard(data);
    document.getElementById('refreshInfo').textContent =
      '上次刷新: ' + new Date().toLocaleTimeString('zh-CN') + ' (每5秒自动)';
  } catch(e) {
    document.getElementById('refreshInfo').textContent = '⚠️ 加载失败: ' + e.message;
  }
}

function renderDashboard(data) {
  // Summary cards
  document.getElementById('summaryCards').innerHTML = `
    <div class="card"><div class="card-label">总任务数</div>
      <div class="card-value">${data.total_tasks}</div></div>
    <div class="card"><div class="card-label">API 调用次数</div>
      <div class="card-value blue">${data.total_api_calls}</div></div>
    <div class="card"><div class="card-label">生成图片</div>
      <div class="card-value green">${data.total_generated}</div></div>
    <div class="card"><div class="card-label">保存图片</div>
      <div class="card-value yellow">${data.total_saved}</div></div>
    <div class="card"><div class="card-label">成功率</div>
      <div class="card-value green">${data.success_rate}%</div></div>
    <div class="card"><div class="card-label">活跃机器</div>
      <div class="card-value">${data.machines.length}</div></div>
  `;

  // Machine table
  const mtb = document.querySelector('#machineTable tbody');
  if (!data.machines.length) {
    mtb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-dim)">暂无数据</td></tr>';
  } else {
    mtb.innerHTML = data.machines.map(m => {
      const rate = m.tasks ? Math.round(m.success / m.tasks * 100) : 0;
      const rateClass = rate >= 80 ? 'success-badge' : rate >= 50 ? '' : 'fail-badge';
      return `<tr>
        <td><strong>${m.name}</strong></td>
        <td>${m.tasks}</td><td>${m.api_calls}</td>
        <td>${m.gen}</td><td>${m.saved}</td>
        <td class="${rateClass}">${rate}%</td>
        <td>${formatDateTime(m.last_ts)}</td>
      </tr>`;
    }).join('');
  }

  // Model distribution bars
  const mb = document.getElementById('modelBars');
  const modelEntries = Object.entries(data.models).sort((a,b) => b[1]-a[1]);
  const maxCount = modelEntries.length ? modelEntries[0][1] : 1;
  if (!modelEntries.length) {
    mb.innerHTML = '<div style="color:var(--text-dim)">暂无数据</div>';
  } else {
    mb.innerHTML = modelEntries.map(([name, count]) => {
      const pct = Math.round(count / maxCount * 100);
      return `<div class="model-bar">
        <div class="model-bar-name" title="${name}">${name}</div>
        <div class="model-bar-track"><div class="model-bar-fill" style="width:${pct}%"></div></div>
        <div class="model-bar-count">${count}</div>
      </div>`;
    }).join('');
  }

  // Recent activity
  const rtb = document.querySelector('#recentTable tbody');
  if (!data.recent.length) {
    rtb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-dim)">暂无数据</td></tr>';
  } else {
    rtb.innerHTML = data.recent.map(r => {
      const status = r.ok
        ? '<span class="success-badge">✅</span>'
        : '<span class="fail-badge">❌ ' + (r.err||'').substring(0,30) + '</span>';
      const node = NODE_LABELS[r.node] || r.node;
      return `<tr>
        <td>${formatTime(r.ts)}</td>
        <td>${r.machine}</td><td>${node}</td>
        <td>${r.model}</td><td>${r.batch}</td>
        <td>${r.gen}</td><td>${r.saved}</td>
        <td>${status}</td><td>${r.dur_s}s</td>
      </tr>`;
    }).join('');
  }
}

// Initial load + auto-refresh
fetchStats();
refreshTimer = setInterval(fetchStats, 5000);
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
            records = load_all_records(self.data_dir, date_filter)
            stats = compute_stats(records)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(stats, ensure_ascii=False).encode("utf-8"))
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
            server = HTTPServer(("0.0.0.0", port), DashboardHandler)
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

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
