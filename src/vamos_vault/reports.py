from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from .media import format_bytes, format_duration


MANIFEST_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_manifest(*, config: dict[str, Any], stats: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "generated_at": utc_now(),
        "telegram": {
            "target": config["telegram"]["target"],
            "upload_mode": "original_document",
            "send_as_document": True,
            "max_file_bytes": int(config["vault"]["max_file_bytes"]),
        },
        "stats": stats,
        "assets": assets,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _json_for_html(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True).replace("</", "<\\/")


_STUDIO_CSS = """
:root {
  color-scheme: light;
  --ink: #111827;
  --muted: #6b7280;
  --line: #e5e7eb;
  --line-strong: #cbd5e1;
  --panel: #ffffff;
  --page: #f6f7f9;
  --accent: #0d7c66;
  --accent-weak: #e6f4ef;
  --accent-ink: #ffffff;
  --warn: #b45309;
  --warn-bg: #fef3c7;
  --bad: #b91c1c;
  --bad-bg: #fee2e2;
  --good: #166534;
  --good-bg: #dcfce7;
  --info: #1e40af;
  --info-bg: #dbeafe;
  --neutral-bg: #eef2f6;
  --neutral-ink: #374151;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: var(--ink);
  background: var(--page);
  font-size: 14px;
  line-height: 1.4;
  -webkit-font-smoothing: antialiased;
}
.topbar {
  background: #0f172a;
  color: #e2e8f0;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.topbar .brand { display: flex; align-items: baseline; gap: 10px; min-width: 0; flex-wrap: wrap; }
.topbar h1 { margin: 0; font-size: 13px; font-weight: 700; letter-spacing: .06em; }
.topbar .meta { color: #94a3b8; font-size: 12px; overflow-wrap: anywhere; }
.topbar .pill {
  border: 1px solid #1e293b; border-radius: 999px; padding: 4px 10px;
  color: #cbd5e1; font-size: 12px; white-space: nowrap;
}

main { max-width: 1480px; margin: 0 auto; padding: 14px 16px 64px; }

.counters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}
.counter {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  min-width: 0;
}
.counter .label {
  display: block; color: var(--muted); font-size: 10px;
  text-transform: uppercase; letter-spacing: .06em; margin-bottom: 4px;
}
.counter .value {
  display: block; font-size: 17px; font-weight: 700; overflow-wrap: anywhere;
}

.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.chip {
  border: 1px solid var(--line-strong); background: var(--panel); color: var(--ink);
  padding: 5px 12px; border-radius: 999px; font-size: 12px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px; font-family: inherit;
}
.chip:hover { border-color: var(--accent); }
.chip.active { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.chip .count { font-size: 11px; opacity: .8; }

.filters {
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 10px;
  display: grid;
  grid-template-columns: minmax(220px, 2fr) repeat(7, minmax(130px, 1fr));
  gap: 8px; align-items: end; margin-bottom: 12px;
}
.field { display: grid; gap: 4px; min-width: 0; }
.field label {
  color: var(--muted); font-size: 10px; text-transform: uppercase;
  letter-spacing: .04em; font-weight: 700;
}
input, select {
  width: 100%; height: 32px; border: 1px solid var(--line-strong);
  border-radius: 4px; padding: 6px 8px; color: var(--ink); background: #fff;
  font-size: 13px; font-family: inherit;
}
input:focus, select:focus { outline: 2px solid var(--accent-weak); border-color: var(--accent); }

.results-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 8px; flex-wrap: wrap;
}
.results-bar .count { color: var(--muted); font-size: 12px; }
.results-bar .hint { color: var(--muted); font-size: 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.results-bar code, .empty code, .exports code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.table-wrap {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; overflow: hidden;
}
.table-scroll { overflow-x: auto; }

table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 1260px; }
thead th {
  position: sticky; top: 0; z-index: 2;
  background: #f1f5f9; border-bottom: 1px solid var(--line-strong);
  text-align: left; padding: 8px 10px; color: var(--neutral-ink);
  font-size: 10px; text-transform: uppercase; letter-spacing: .05em;
  font-weight: 700; white-space: nowrap;
}
tbody tr { border-bottom: 1px solid var(--line); cursor: pointer; }
tbody tr:hover { background: #f8fafc; }
tbody tr.expanded { background: var(--accent-weak); }
tbody tr.expanded:hover { background: var(--accent-weak); }
tbody td {
  padding: 8px 10px; vertical-align: top; max-width: 260px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
tbody td.wrap { white-space: normal; overflow-wrap: anywhere; }
tbody td.expand { color: var(--muted); width: 18px; text-align: center; user-select: none; }
tbody tr.expanded td.expand { color: var(--accent); }
.thumb-cell { width: 84px; max-width: 84px; }
.thumb {
  width: 68px; height: 42px; border-radius: 4px; border: 1px solid var(--line);
  background: #e5e7eb; object-fit: cover; display: block;
}
.thumb.placeholder {
  display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: .04em;
  text-transform: uppercase;
}
.detail-thumb {
  width: 220px; max-width: 100%; max-height: 140px; object-fit: cover;
  border: 1px solid var(--line); border-radius: 6px; margin: 0 0 10px;
  background: #e5e7eb;
}
.file { font-weight: 600; }
.star { color: var(--accent); margin-right: 4px; font-weight: 700; }
.muted { color: var(--muted); }

.badge {
  display: inline-block; border-radius: 4px; padding: 2px 8px;
  font-size: 11px; font-weight: 700; letter-spacing: .02em;
  background: var(--neutral-bg); color: var(--neutral-ink); white-space: nowrap;
}
.b-remote { background: var(--neutral-bg); color: var(--neutral-ink); }
.b-uploaded { background: var(--good-bg); color: var(--good); }
.b-downloaded { background: var(--info-bg); color: var(--info); }
.b-done { background: #dcfce7; color: #065f46; }
.b-remote-deleted { background: var(--bad-bg); color: var(--bad); }
.b-dry-run { background: var(--warn-bg); color: var(--warn); }
.b-cataloged { background: var(--neutral-bg); color: var(--neutral-ink); }

a.tg { color: var(--accent); text-decoration: none; }
a.tg:hover { text-decoration: underline; }

tr.detail { background: #fbfcfd; cursor: default; }
tr.detail:hover { background: #fbfcfd; }
tr.detail td { padding: 0; border-bottom: 1px solid var(--line); }
.detail-panel {
  padding: 14px 16px;
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 14px 28px;
}
.detail-section { min-width: 0; }
.detail-section.commands { grid-column: 1 / -1; }
.detail-section h4 {
  margin: 0 0 6px; font-size: 10px; text-transform: uppercase;
  letter-spacing: .05em; color: var(--muted); font-weight: 700;
}
.detail-grid {
  display: grid; grid-template-columns: 130px 1fr; gap: 3px 10px; font-size: 12px;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; overflow-wrap: anywhere; word-break: break-word; }

.cmd { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; font-size: 12px; }
.cmd code {
  flex: 1; background: #0f172a; color: #e2e8f0; padding: 6px 8px;
  border-radius: 4px; font-size: 12px; overflow-wrap: anywhere; min-width: 0;
}
.cmd.danger code { color: #fecaca; }
.cmd button {
  border: 1px solid var(--line-strong); background: #fff; color: var(--ink);
  padding: 4px 10px; border-radius: 4px; font-size: 11px; cursor: pointer;
  white-space: nowrap; font-family: inherit;
}
.cmd button:hover { border-color: var(--accent); color: var(--accent); }
.cmd.danger button:hover { border-color: var(--bad); color: var(--bad); }
.cmd .copy-ok { color: var(--good); font-size: 11px; min-width: 40px; }
.cmd-label { color: var(--muted); font-size: 11px; font-weight: 600; min-width: 120px; }
.cmd-warn { color: var(--bad); font-size: 11px; margin: 2px 0 6px 126px; }

.group-header {
  background: #eef2f5; font-weight: 700; font-size: 12px; color: var(--neutral-ink);
  cursor: pointer;
}
.group-header td { padding: 8px 10px; }
.group-header:hover { background: #e2e8f0; }
.group-header .chev { color: var(--muted); margin-right: 6px; display: inline-block; min-width: 12px; }

.empty { padding: 40px 16px; text-align: center; color: var(--muted); }
.empty code { background: #eef2f5; padding: 2px 6px; border-radius: 3px; font-size: 12px; }
.results-bar code { background: #eef2f5; padding: 1px 6px; border-radius: 3px; font-size: 12px; }

.exports {
  margin-top: 14px; background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 12px 14px;
}
.exports h3 { margin: 0 0 4px; font-size: 13px; }
.exports .sub { color: var(--muted); font-size: 12px; margin-bottom: 10px; }
.exports .cmd code { background: #f1f5f9; color: var(--ink); }

@media (max-width: 1200px) {
  .filters { grid-template-columns: 1fr 1fr 1fr; }
}
@media (max-width: 820px) {
  .topbar { padding: 10px 12px; }
  .topbar h1 { font-size: 12px; }
  main { padding: 12px 10px 40px; }
  .filters { grid-template-columns: 1fr 1fr; }
  .detail-panel { grid-template-columns: 1fr; }
  .counters { grid-template-columns: repeat(2, 1fr); }
  .cmd-label { display: none; }
  .cmd-warn { margin-left: 0; }
}
@media (max-width: 540px) {
  .filters { grid-template-columns: 1fr; }
  .counters { grid-template-columns: 1fr 1fr; }
  .detail-grid { grid-template-columns: 100px 1fr; }
}
"""


_STUDIO_BODY = """<div class="topbar">
  <div class="brand">
    <h1>VAMOS VAULT STUDIO</h1>
    <span class="meta">Target {target} &middot; Generated {generated}</span>
  </div>
  <div class="actions">
    <span class="pill">Offline dashboard &middot; static HTML</span>
  </div>
</div>

<main>
  <section class="counters" aria-label="Vault summary"></section>
  <section class="chips" aria-label="Quick filters"></section>

  <section class="filters" aria-label="Filters">
    <div class="field"><label>Search</label><input id="q" type="search" placeholder="filename, project, scene, location, people, tags, notes, camera, lens"></div>
    <div class="field"><label>Project</label><select id="project"><option value="">All</option></select></div>
    <div class="field"><label>Status</label><select id="status"><option value="">All</option></select></div>
    <div class="field"><label>Kind</label><select id="kind"><option value="">All</option></select></div>
    <div class="field"><label>Camera</label><select id="camera"><option value="">All</option></select></div>
    <div class="field"><label>Rating</label><select id="rating"><option value="">Any</option><option value="unrated">Unrated</option><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4">4</option><option value="5">5</option></select></div>
    <div class="field"><label>YouTube</label><select id="youtube"><option value="">All</option></select></div>
    <div class="field"><label>Favorite</label><select id="favorite"><option value="">Any</option><option value="1">Favorites only</option></select></div>
    <div class="field"><label>Group by</label><select id="groupby"><option value="">None</option><option value="project">Project</option><option value="shoot_date">Shoot date</option></select></div>
  </section>

  <div class="results-bar">
    <span class="count" id="count"></span>
    <span class="hint">Regenerate: <code>vamos-vault studio --open</code></span>
  </div>

  <section class="table-wrap" aria-label="Assets">
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th class="expand"></th>
            <th>Preview</th><th>File</th><th>Project</th><th>Kind</th><th>Shoot</th>
            <th>Scene / Location</th><th>Kit</th><th>Size</th><th>Dur</th>
            <th>Tags</th><th>Rate</th><th>Status</th><th>Telegram</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <div class="empty" id="empty" hidden>No matching assets. Run <code>vamos-vault sync</code> or adjust filters.</div>
  </section>

  <section class="exports" aria-label="Export commands">
    <h3>Export from the CLI</h3>
    <div class="sub">This is a static HTML file. Run these in PowerShell to export the catalog or refresh this dashboard.</div>
    <div class="cmd"><span class="cmd-label">CSV</span><code>vamos-vault export --format csv --out exports/vamos-catalog.csv</code><button type="button" class="copy" data-cmd="vamos-vault export --format csv --out exports/vamos-catalog.csv">copy</button><span class="copy-ok"></span></div>
    <div class="cmd"><span class="cmd-label">JSON</span><code>vamos-vault export --format json --out exports/vamos-catalog.json</code><button type="button" class="copy" data-cmd="vamos-vault export --format json --out exports/vamos-catalog.json">copy</button><span class="copy-ok"></span></div>
    <div class="cmd"><span class="cmd-label">Manifest</span><code>vamos-vault manifest --out exports/vamos-manifest.json</code><button type="button" class="copy" data-cmd="vamos-vault manifest --out exports/vamos-manifest.json">copy</button><span class="copy-ok"></span></div>
    <div class="cmd"><span class="cmd-label">Studio</span><code>vamos-vault studio --open</code><button type="button" class="copy" data-cmd="vamos-vault studio --open">copy</button><span class="copy-ok"></span></div>
  </section>
</main>"""


_STUDIO_JS = """
const manifest = JSON.parse(document.getElementById("vault-data").textContent);
const assets = manifest.assets || [];
const stats = manifest.stats || {};
const $ = (id) => document.getElementById(id);

function text(v) { return v == null ? "" : String(v); }
function lcase(v) { return text(v).toLowerCase(); }
function int(v) { const n = parseInt(v, 10); return isNaN(n) ? 0 : n; }
function escapeHtml(s) {
  return text(s).replace(/[&<>"']/g, (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
}
function formatBytes(n) {
  n = int(n);
  if (n <= 0) return "0 B";
  const units = ["B","KB","MB","GB","TB"];
  let v = n;
  for (const u of units) {
    if (v < 1024 || u === "TB") return u === "B" ? Math.round(v) + " " + u : v.toFixed(2) + " " + u;
    v /= 1024;
  }
  return n + " B";
}
function formatDuration(s) {
  if (s == null || s === "" || isNaN(s)) return "";
  const t = Math.round(Number(s));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
  return h ? h + ":" + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0")
           : String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
}
function statusClass(s) {
  const map = {
    remote: "b-remote", uploaded: "b-uploaded", downloaded: "b-downloaded",
    done: "b-done", "remote-deleted": "b-remote-deleted",
    "dry-run": "b-dry-run", cataloged: "b-cataloged"
  };
  return map[text(s)] || "b-cataloged";
}
function joinFields(a, b) {
  return [text(a), text(b)].filter(Boolean).join(" \\u00b7 ");
}

const state = {
  q: "", project: "", status: "", kind: "", camera: "",
  rating: "", youtube: "", favorite: "", groupby: "",
  needsMeta: false, activeChip: "all",
};

const chips = [
  { id: "all",       label: "All",             count: () => stats.total_assets },
  { id: "remote",    label: "Remote archive",  count: () => stats.remote_assets },
  { id: "ready",     label: "Ready to edit",   count: () => stats.downloaded_assets },
  { id: "done",      label: "Done",            count: () => stats.done_assets },
  { id: "favorites", label: "Favorites",       count: () => stats.favorites },
  { id: "needs",     label: "Needs metadata",  count: () => stats.needs_metadata },
  { id: "deleted",   label: "Remote-deleted",  count: () => stats.remote_deleted_assets },
];

const counters = [
  { label: "Assets",         value: () => stats.total_assets },
  { label: "Remote only",    value: () => stats.remote_assets },
  { label: "Downloaded",     value: () => stats.downloaded_assets },
  { label: "Done",           value: () => stats.done_assets },
  { label: "Remote-deleted", value: () => stats.remote_deleted_assets },
  { label: "Uploaded",       value: () => stats.uploaded_assets },
  { label: "Favorites",      value: () => stats.favorites },
  { label: "Needs metadata", value: () => stats.needs_metadata },
  { label: "Storage",        value: () => formatBytes(stats.total_bytes) },
  { label: "Runtime",        value: () => formatDuration(stats.total_duration_seconds) },
];

function renderCounters() {
  const host = document.querySelector(".counters");
  host.textContent = "";
  counters.forEach((c) => {
    const div = document.createElement("div");
    div.className = "counter";
    const label = document.createElement("span"); label.className = "label"; label.textContent = c.label;
    const value = document.createElement("span"); value.className = "value"; value.textContent = text(c.value());
    div.appendChild(label); div.appendChild(value);
    host.appendChild(div);
  });
}

function renderChips() {
  const host = document.querySelector(".chips");
  host.textContent = "";
  chips.forEach((c) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip" + (state.activeChip === c.id ? " active" : "");
    btn.textContent = c.label;
    const cnt = document.createElement("span"); cnt.className = "count"; cnt.textContent = text(c.count());
    btn.appendChild(cnt);
    btn.onclick = () => applyChip(c.id);
    host.appendChild(btn);
  });
}

function applyChip(id) {
  state.activeChip = id;
  state.needsMeta = false;
  state.status = "";
  state.favorite = "";
  if (id === "remote") state.status = "remote";
  else if (id === "ready") state.status = "downloaded";
  else if (id === "done") state.status = "done";
  else if (id === "deleted") state.status = "remote-deleted";
  else if (id === "favorites") state.favorite = "1";
  else if (id === "needs") state.needsMeta = true;
  $("status").value = state.status;
  $("favorite").value = state.favorite;
  renderChips();
  render();
}

function distinct(field) {
  const set = new Set();
  assets.forEach((a) => { const v = text(a[field]); if (v) set.add(v); });
  return [...set].sort();
}

function fillSelects() {
  const opts = {
    project: distinct("project"),
    status: distinct("status"),
    kind: distinct("asset_kind"),
    camera: (stats.cameras && stats.cameras.length) ? stats.cameras : distinct("camera"),
    youtube: (stats.youtube_statuses && stats.youtube_statuses.length) ? stats.youtube_statuses : distinct("youtube_status"),
  };
  Object.entries(opts).forEach(([id, values]) => {
    const sel = $(id);
    values.forEach((v) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = v;
      sel.appendChild(o);
    });
  });
}

function syncFromInputs() {
  state.q = $("q").value.trim();
  state.project = $("project").value;
  state.status = $("status").value;
  state.kind = $("kind").value;
  state.camera = $("camera").value;
  state.rating = $("rating").value;
  state.youtube = $("youtube").value;
  state.favorite = $("favorite").value;
  state.groupby = $("groupby").value;
}

function onInput() {
  syncFromInputs();
  state.activeChip = "";
  renderChips();
  render();
}

let qTimer = null;
function onSearchInput() {
  if (qTimer) clearTimeout(qTimer);
  qTimer = setTimeout(onInput, 120);
}

function matches(asset) {
  if (state.q) {
    const hay = [
      asset.filename, asset.project, asset.tags, asset.notes, asset.scene,
      asset.location, asset.people, asset.camera, asset.lens, asset.youtube_status,
      asset.asset_kind, asset.shoot_date, asset.rights, asset.sha256
    ].map(lcase).join(" ");
    if (!hay.includes(state.q.toLowerCase())) return false;
  }
  if (state.project && text(asset.project) !== state.project) return false;
  if (state.status && text(asset.status) !== state.status) return false;
  if (state.kind && text(asset.asset_kind) !== state.kind) return false;
  if (state.camera && text(asset.camera) !== state.camera) return false;
  if (state.youtube && text(asset.youtube_status) !== state.youtube) return false;
  if (state.favorite === "1" && int(asset.favorite) !== 1) return false;
  if (state.rating === "unrated") {
    if (asset.rating != null && asset.rating !== "") return false;
  } else if (state.rating) {
    if (String(asset.rating) !== state.rating) return false;
  }
  if (state.needsMeta) {
    const hasMeta = text(asset.project) && text(asset.tags) && text(asset.rights);
    if (hasMeta) return false;
  }
  return true;
}

function cell(content, cls) {
  const td = document.createElement("td");
  td.textContent = text(content);
  if (cls) td.className = cls;
  return td;
}

function mediaKind(asset) {
  const name = lcase(asset.filename);
  const codec = lcase(asset.codec);
  if (codec.startsWith("video/") || name.match(/\\.(mp4|mov|mkv|webm|avi|mts|mxf)$/)) return "video";
  if (codec.startsWith("image/") || name.match(/\\.(jpg|jpeg|png|heic|dng|raw|cr2|cr3)$/)) return "image";
  if (codec.startsWith("audio/") || name.match(/\\.(wav|mp3|m4a|aac|flac)$/)) return "audio";
  if (name.endsWith(".pdf")) return "pdf";
  return "file";
}

function thumbnailCell(asset) {
  const td = document.createElement("td");
  td.className = "thumb-cell";
  if (asset.thumbnail_uri) {
    const img = document.createElement("img");
    img.className = "thumb";
    img.src = asset.thumbnail_uri;
    img.alt = "Preview for " + text(asset.filename);
    td.appendChild(img);
  } else {
    const ph = document.createElement("span");
    ph.className = "thumb placeholder";
    ph.textContent = mediaKind(asset);
    td.appendChild(ph);
  }
  return td;
}

function rowFor(asset) {
  const tr = document.createElement("tr");
  tr.dataset.sha = text(asset.sha256);
  tr.onclick = (e) => { if (e.target.closest("a,button")) return; toggleDetail(asset, tr); };
  const expand = document.createElement("td");
  expand.className = "expand"; expand.textContent = "\\u203a";
  tr.appendChild(expand);
  tr.appendChild(thumbnailCell(asset));
  const fileCell = cell(asset.filename, "file wrap");
  if (int(asset.favorite) === 1) {
    const star = document.createElement("span");
    star.className = "star"; star.textContent = "\\u2605";
    fileCell.prepend(star);
  }
  tr.appendChild(fileCell);
  tr.appendChild(cell(asset.project, "wrap"));
  tr.appendChild(cell(asset.asset_kind));
  tr.appendChild(cell(asset.shoot_date));
  tr.appendChild(cell(joinFields(asset.scene, asset.location), "wrap"));
  tr.appendChild(cell(joinFields(asset.camera, asset.lens), "wrap"));
  tr.appendChild(cell(asset.size_label || formatBytes(asset.size_bytes)));
  tr.appendChild(cell(asset.duration_label || formatDuration(asset.duration_seconds)));
  tr.appendChild(cell(asset.tags, "wrap"));
  tr.appendChild(cell(asset.rating ? asset.rating + "/5" : ""));
  const stTd = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = "badge " + statusClass(asset.status);
  badge.textContent = text(asset.status);
  stTd.appendChild(badge);
  tr.appendChild(stTd);
  const tg = document.createElement("td");
  if (asset.telegram_link) {
    const a = document.createElement("a");
    a.className = "tg"; a.href = asset.telegram_link; a.target = "_blank"; a.rel = "noopener";
    a.textContent = "open";
    tg.appendChild(a);
  } else { tg.className = "muted"; }
  tr.appendChild(tg);
  return tr;
}

function toggleDetail(asset, tr) {
  const next = tr.nextSibling;
  if (next && next.classList && next.classList.contains("detail")) {
    next.remove();
    tr.classList.remove("expanded");
    return;
  }
  tr.classList.add("expanded");
  const dtr = document.createElement("tr");
  dtr.className = "detail";
  const td = document.createElement("td");
  td.colSpan = 14;
  td.appendChild(detailPanel(asset));
  dtr.appendChild(td);
  tr.parentNode.insertBefore(dtr, tr.nextSibling);
}

function addGridRow(dl, key, value, opts) {
  const dt = document.createElement("dt"); dt.textContent = key;
  const dd = document.createElement("dd");
  if (opts && opts.link && value) {
    const a = document.createElement("a");
    a.className = "tg"; a.href = text(value); a.target = "_blank"; a.rel = "noopener";
    a.textContent = text(value);
    dd.appendChild(a);
  } else {
    dd.textContent = text(value);
  }
  dl.appendChild(dt); dl.appendChild(dd);
}

function detailPanel(asset) {
  const wrap = document.createElement("div");
  wrap.className = "detail-panel";

  const left = document.createElement("div");
  left.className = "detail-section";
  const lh = document.createElement("h4"); lh.textContent = "Metadata"; left.appendChild(lh);
  if (asset.thumbnail_uri) {
    const img = document.createElement("img");
    img.className = "detail-thumb";
    img.src = asset.thumbnail_uri;
    img.alt = "Preview for " + text(asset.filename);
    left.appendChild(img);
  }
  const grid = document.createElement("dl"); grid.className = "detail-grid";
  const rows = [
    ["Filename", asset.filename], ["Project", asset.project],
    ["Shoot date", asset.shoot_date], ["Kind", asset.asset_kind],
    ["Scene", asset.scene], ["Location", asset.location],
    ["Camera", asset.camera], ["Lens", asset.lens],
    ["People", asset.people], ["Rights", asset.rights],
    ["Rating", asset.rating ? asset.rating + "/5" : ""],
    ["Favorite", int(asset.favorite) === 1 ? "yes" : ""],
    ["YouTube", asset.youtube_status], ["Tags", asset.tags],
    ["Notes", asset.notes], ["Status", asset.status],
  ];
  rows.forEach(([k, v]) => addGridRow(grid, k, v));
  left.appendChild(grid);

  const right = document.createElement("div");
  right.className = "detail-section";
  const rh = document.createElement("h4"); rh.textContent = "Storage & links"; right.appendChild(rh);
  const grid2 = document.createElement("dl"); grid2.className = "detail-grid";
  const rows2 = [
    ["Size", asset.size_label || formatBytes(asset.size_bytes)],
    ["Duration", asset.duration_label || formatDuration(asset.duration_seconds)],
    ["Resolution", (asset.width && asset.height) ? asset.width + "x" + asset.height : ""],
    ["Codec / MIME", asset.codec],
    ["SHA-256", asset.sha256], ["Content SHA", asset.content_sha256],
    ["Telegram chat", asset.telegram_chat],
    ["Telegram msg", asset.telegram_message_id],
    ["Telegram link", asset.telegram_link, { link: true }],
    ["Thumbnail", asset.thumbnail_path],
    ["Downloaded path", asset.downloaded_path],
    ["Downloaded at", asset.downloaded_at],
    ["Uploaded at", asset.uploaded_at],
    ["Completed at", asset.completed_at],
    ["Remote deleted", asset.remote_deleted_at],
    ["Created", asset.created_at], ["Updated", asset.updated_at],
  ];
  rows2.forEach(([k, v, o]) => addGridRow(grid2, k, v, o));
  right.appendChild(grid2);

  const cmdSection = document.createElement("div");
  cmdSection.className = "detail-section commands";
  const ch = document.createElement("h4"); ch.textContent = "CLI commands (copy to terminal)"; cmdSection.appendChild(ch);
  const q = asset.sha256 || asset.filename;
  const qstr = '"' + q + '"';
  const cmds = [
    { label: "Download this clip", cmd: "vamos-vault download " + qstr, danger: false },
    { label: "Mark done",          cmd: "vamos-vault done " + qstr + " --notes \\"finished edit\\"", danger: false },
    { label: "Delete local copy",  cmd: "vamos-vault done " + qstr + " --delete-local --yes", danger: false },
    { label: "Delete remote copy", cmd: "vamos-vault done " + qstr + " --delete-remote --yes", danger: true,
      warn: "Removes the Telegram archive copy. Final unless you have another backup." },
  ];
  cmds.forEach((c) => {
    const row = document.createElement("div");
    row.className = "cmd" + (c.danger ? " danger" : "");
    const label = document.createElement("span");
    label.className = "cmd-label"; label.textContent = c.label;
    const code = document.createElement("code"); code.textContent = c.cmd;
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "copy"; btn.textContent = "copy";
    btn.setAttribute("data-cmd", c.cmd);
    btn.addEventListener("click", (e) => { e.stopPropagation(); copyCmd(btn); });
    const ok = document.createElement("span"); ok.className = "copy-ok";
    row.appendChild(label); row.appendChild(code); row.appendChild(btn); row.appendChild(ok);
    cmdSection.appendChild(row);
    if (c.warn) {
      const w = document.createElement("div");
      w.className = "cmd-warn"; w.textContent = c.warn;
      cmdSection.appendChild(w);
    }
  });

  wrap.appendChild(left);
  wrap.appendChild(right);
  wrap.appendChild(cmdSection);
  return wrap;
}

function copyCmd(btn) {
  const cmd = btn.getAttribute("data-cmd");
  const ok = btn.parentNode.querySelector(".copy-ok");
  const finish = () => { if (ok) { ok.textContent = "copied"; setTimeout(() => { ok.textContent = ""; }, 1200); } };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(cmd).then(finish).catch(() => fallbackCopy(cmd, finish));
  } else {
    fallbackCopy(cmd, finish);
  }
}
function fallbackCopy(textValue, cb) {
  const ta = document.createElement("textarea");
  ta.value = textValue; document.body.appendChild(ta); ta.focus(); ta.select();
  try { document.execCommand("copy"); } catch (e) {}
  document.body.removeChild(ta);
  if (cb) cb();
}

function toggleGroup(gh) {
  let n = gh.nextSibling;
  const hide = (gh.dataset.collapsed !== "1");
  gh.dataset.collapsed = hide ? "1" : "0";
  const chev = gh.querySelector(".chev");
  if (chev) chev.textContent = hide ? "\\u25b8" : "\\u25be";
  while (n && !n.classList.contains("group-header")) {
    if (n.style) n.style.display = hide ? "none" : "";
    n = n.nextSibling;
  }
}

function render() {
  const tbody = $("rows");
  tbody.textContent = "";
  const visible = assets.filter(matches);
  $("count").textContent = visible.length + " of " + assets.length + " assets";
  $("empty").hidden = visible.length > 0;
  if (state.groupby) {
    const groups = new Map();
    visible.forEach((a) => {
      const key = text(a[state.groupby]) || "(no " + state.groupby.replace("_", " ") + ")";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(a);
    });
    [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).forEach(([key, items]) => {
      const gh = document.createElement("tr");
      gh.className = "group-header";
      gh.onclick = () => toggleGroup(gh);
      const td = document.createElement("td");
      td.colSpan = 14;
      const totalBytes = items.reduce((s, a) => s + int(a.size_bytes), 0);
      const totalDur = items.reduce((s, a) => s + (Number(a.duration_seconds) || 0), 0);
      td.innerHTML = '<span class="chev">\\u25be</span>' + escapeHtml(key)
        + '  \\u00b7  ' + items.length + ' assets  \\u00b7  '
        + escapeHtml(formatBytes(totalBytes))
        + (totalDur > 0 ? '  \\u00b7  ' + escapeHtml(formatDuration(totalDur)) : '');
      gh.appendChild(td);
      tbody.appendChild(gh);
      items.forEach((a) => tbody.appendChild(rowFor(a)));
    });
  } else {
    visible.forEach((a) => tbody.appendChild(rowFor(a)));
  }
}

$("q").addEventListener("input", onSearchInput);
$("q").addEventListener("keydown", (e) => { if (e.key === "Escape") { $("q").value = ""; onInput(); } });
["project", "status", "kind", "camera", "rating", "youtube", "favorite", "groupby"].forEach((id) => {
  $(id).addEventListener("change", onInput);
});
document.querySelectorAll(".exports .copy").forEach((btn) => {
  btn.addEventListener("click", () => copyCmd(btn));
});

fillSelects();
renderCounters();
renderChips();
syncFromInputs();
render();
"""


def write_studio_html(path: Path, manifest: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    title = "Vamos Telegram Vault Studio"
    data = _json_for_html(manifest)
    body = _STUDIO_BODY.format(
        target=escape(str(manifest["telegram"]["target"])),
        generated=escape(str(manifest["generated_at"])),
    )
    html = (
        '<!doctype html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'  <title>{escape(title)}</title>\n'
        '  <style>\n'
        f'{_STUDIO_CSS}\n'
        '  </style>\n'
        '</head>\n'
        '<body>\n'
        f'{body}\n'
        f'  <script id="vault-data" type="application/json">{data}</script>\n'
        '  <script>\n'
        f'{_STUDIO_JS}\n'
        '  </script>\n'
        '</body>\n'
        '</html>\n'
    )
    path.write_text(html, encoding="utf-8")
    return path


def enrich_assets_for_display(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for asset in assets:
        item = dict(asset)
        item["size_label"] = format_bytes(int(item.get("size_bytes") or 0))
        item["duration_label"] = format_duration(item.get("duration_seconds"))
        thumbnail_path = item.get("thumbnail_path")
        if thumbnail_path and Path(str(thumbnail_path)).exists():
            item["thumbnail_uri"] = Path(str(thumbnail_path)).resolve().as_uri()
        else:
            item["thumbnail_uri"] = None
        enriched.append(item)
    return enriched
