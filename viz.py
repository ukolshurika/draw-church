#!/usr/bin/env python3
"""Build interactive vis-network graph from all-nodes.json + all-edges.json.

Splits the graph into connected components to avoid freezing on the full dataset.
Colour-codes by settlement, supports search/filter, and scales node size by degree.
"""

import json, math
from pathlib import Path
from collections import Counter, defaultdict

import networkx as nx

BASE_DIR = Path(__file__).parent
NODES_FILE = BASE_DIR / "all-nodes.json"
EDGES_FILE = BASE_DIR / "all-edges.json"
OUTPUT = BASE_DIR / "graph.html"

RELATION_COLORS = {
    "child_of":       "#e74c3c",
    "godparent_of":   "#f39c12",
    "married_to":     "#e91e63",
    "witnessed_for":  "#95a5a6",
    "other":          "#7f8c8d",
}
RECORD_COLORS = {
    "Родившийся":      "#3498db",
    "Бракосочетание":  "#e91e63",
}

# ── Colour palette for settlements (32 hand-picked colours) ──────────
SETTLEMENT_PALETTE = [
    "#2ecc71", "#3498db", "#9b59b6", "#f1c40f", "#e67e22", "#1abc9c",
    "#e74c3c", "#2980b9", "#8e44ad", "#27ae60", "#f39c12", "#d35400",
    "#16a085", "#c0392b", "#7f8c8d", "#2c3e50", "#00bcd4", "#ff5722",
    "#795548", "#607d8b", "#4caf50", "#ff9800", "#cddc39", "#03a9f4",
    "#e91e63", "#673ab7", "#009688", "#ffc107", "#8bc34a", "#9e9e9e",
    "#ff5252", "#536dfe",
]


def assign_settlement_colours(components: list[dict]) -> dict[str, str]:
    """Assign consistent colour to each settlement across all components."""
    all_settlements: Counter = Counter()
    for c in components:
        for n in c["nodes"]:
            s = n.get("settlement")
            if s:
                all_settlements[s] += 1
    # Most common get first palette entries
    ordered = [s for s, _ in all_settlements.most_common()]
    mapping: dict[str, str] = {}
    for i, s in enumerate(ordered):
        mapping[s] = SETTLEMENT_PALETTE[i % len(SETTLEMENT_PALETTE)]
    mapping[None] = "#444444"
    return mapping


def build_html(components: list[dict]) -> str:
    colour_map = assign_settlement_colours(components)

    # Attach colour + degree to each node
    for c in components:
        degree_counter = Counter()
        for e in c["edges"]:
            degree_counter[e["source_id"]] += 1
            degree_counter[e["target_id"]] += 1
        for n in c["nodes"]:
            n["_deg"] = degree_counter.get(n["id"], 0)
            n["_settc"] = colour_map.get(n.get("settlement"))

    comp_json = json.dumps(components, ensure_ascii=False)
    rel_json  = json.dumps(RELATION_COLORS, ensure_ascii=False)
    rec_json  = json.dumps(RECORD_COLORS, ensure_ascii=False)
    sett_json = json.dumps(colour_map, ensure_ascii=False)
    palette_json = json.dumps(SETTLEMENT_PALETTE, ensure_ascii=False)

    # ── Build options ──────────────────────────────────────────────
    primary_opts = ""
    giant_opts   = ""
    for i, c in enumerate(components):
        lbl = f"#{i+1} – {c['size']}&thinsp;уз, {c['edge_count']}&thinsp;св"
        tag = f'<option value="{i}">{lbl}</option>\n'
        if c["size"] <= 200:
            primary_opts += tag
        else:
            giant_opts   += f'<option value="{i}">{"\u26a0"} {lbl}</option>\n'

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Метрические книги — граф связей</title>
<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box}}
html,body{{height:100%;margin:0;padding:0;font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9}}
#app{{display:flex;flex-direction:column;height:100%}}

/* header */
#toolbar{{display:flex;align-items:center;gap:10px;padding:8px 16px;background:#161b22;border-bottom:1px solid #30363d;flex-shrink:0;flex-wrap:wrap}}
#toolbar h1{{font-size:16px;margin:0;color:#58a6ff;white-space:nowrap}}
#toolbar select,#toolbar input{{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font-size:13px;outline:none}}
#toolbar select:focus,#toolbar input:focus{{border-color:#58a6ff}}
#toolbar input{{width:180px}}
#toolbar input::placeholder{{color:#484f58}}
#phys-btn{{background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:6px;padding:3px 6px;cursor:pointer;font-size:14px;line-height:1}}
#phys-btn:hover{{color:#c9d1d9;border-color:#58a6ff}}
#phys-btn.active{{background:#1f6feb;border-color:#1f6feb;color:#fff}}
#save-btn{{background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:6px;padding:3px 6px;cursor:pointer;font-size:14px;line-height:1}}
#save-btn:hover{{color:#c9d1d9;border-color:#58a6ff}}
#stats{{font-size:11px;color:#8b949e;margin-left:auto;white-space:nowrap}}

/* main area */
#main{{display:flex;flex:1;min-height:0}}
#side{{width:260px;background:#161b22;border-right:1px solid #30363d;display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto;font-size:12px}}
#side h3{{margin:0;padding:10px 12px 4px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#8b949e}}
#side .legend{{padding:4px 12px 8px}}
#side .legend-item{{display:flex;align-items:center;gap:6px;padding:2px 0;cursor:pointer;border-radius:3px;padding:1px 4px;user-select:none}}
#side .legend-item:hover{{background:#21262d}}
#side .legend-item.active{{background:#1f6feb33;outline:1px solid #1f6feb66}}
#side .legend-swatch{{width:10px;height:10px;border-radius:2px;flex-shrink:0}}
#side .legend-label{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}}
#side .legend-count{{color:#484f58;font-size:10px;margin-left:auto}}
#side .legend-rel{{display:flex;align-items:center;gap:6px;padding:1px 4px;font-size:11px}}
#side .legend-rel-line{{width:14px;height:2px;border-radius:1px;flex-shrink:0}}
#filters{{padding:4px 12px 8px;display:flex;flex-wrap:wrap;gap:4px}}
#filters button{{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;font-size:10px;padding:2px 6px;cursor:pointer}}
#filters button.active{{background:#1f6feb;border-color:#1f6feb}}

#hop-ctl{{padding:4px 12px 8px;display:flex;align-items:center;gap:6px;font-size:11px}}
#hop-ctl input[type=range]{{width:80px;accent-color:#1f6feb}}
#hop-ctl .hop-val{{color:#58a6ff;font-weight:bold;min-width:14px;text-align:center}}

#graph-container{{flex:1;position:relative;min-width:0}}
#graph{{width:100%;height:100%}}
#loading{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#8b949e;font-size:15px;pointer-events:none;transition:opacity .3s;z-index:10}}
#loading.hidden{{opacity:0}}
#loading::after{{content:'…';animation:dots 1.5s steps(4,end) infinite}}
@keyframes dots{{0%{{content:''}}25%{{content:'.'}}50%{{content:'..'}}75%{{content:'...'}}}}

#detail{{padding:8px 12px;border-top:1px solid #30363d;font-size:11px;line-height:1.6;display:none}}
#detail.visible{{display:block}}
#detail b{{color:#58a6ff}}
#detail .sett{{color:#f0c000}}
.archive-box{{margin-top:8px;padding-top:6px;border-top:1px solid #30363d}}
.archive-link{{display:block;color:#58a6ff;text-decoration:none;font-size:11px;padding:2px 0}}
.archive-link:hover{{text-decoration:underline}}

#focus-bar{{display:none;align-items:center;gap:6px;padding:3px 10px;background:#1f6feb22;border:1px solid #1f6feb66;border-radius:6px;font-size:12px;white-space:nowrap}}
#focus-bar.visible{{display:flex}}
#focus-bar .focus-name{{color:#58a6ff;font-weight:bold;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
#focus-bar button{{background:none;border:none;color:#8b949e;cursor:pointer;font-size:15px;padding:0 2px;line-height:1}}
#focus-bar button:hover{{color:#f85149}}
#focus-bar .focus-hint{{color:#484f58;font-size:10px}}

/* right panel */
#right-panel{{width:320px;background:#161b22;border-left:1px solid #30363d;display:none;flex-direction:column;flex-shrink:0;font-size:12px;overflow:hidden}}
#right-panel.visible{{display:flex}}
#rp-header{{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid #30363d;flex-shrink:0}}
#rp-title{{font-size:12px;font-weight:600;color:#c9d1d9}}
#rp-close-btn{{background:none;border:none;color:#8b949e;cursor:pointer;font-size:16px;padding:0;line-height:1}}
#rp-close-btn:hover{{color:#f85149}}
#rp-csv-btn{{margin:8px 12px;padding:5px 10px;background:#1f6feb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:11px;flex-shrink:0}}
#rp-csv-btn:hover{{background:#388bfd}}
#rp-list{{overflow-y:auto;flex:1;padding:4px 8px}}
.rp-node-card{{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;margin-bottom:6px;font-size:11px;line-height:1.5}}
.rp-node-card .rp-name{{color:#58a6ff;font-weight:600;font-size:12px}}
.rp-node-card .rp-row{{color:#8b949e}}
.rp-node-card .rp-row b{{color:#c9d1d9;font-weight:500}}
.rp-node-card .rp-src{{margin-top:5px;padding-top:5px;border-top:1px solid #21262d;color:#484f58;font-size:10px}}
.rp-node-card .rp-src a{{color:#58a6ff;text-decoration:none}}
.rp-node-card .rp-src a:hover{{text-decoration:underline}}

/* responsive: hide sidebar on narrow */
@media(max-width:700px){{#side{{display:none}}}}
</style>
</head>
<body>

<div id="app">
  <div id="toolbar">
    <h1>Метрики</h1>
    <select id="comp">{primary_opts}{giant_opts}</select>
    <div id="focus-bar"><span class="focus-name"></span><button title="Esc">×</button><span class="focus-hint">Esc to exit</span></div>
    <input id="search" type="text" placeholder="Поиск …">
    <button id="phys-btn" title="Toggle physics (P)">⚡</button>
    <button id="save-btn" title="Save as PNG">💾</button>
    <div id="stats">—</div>
  </div>
  <div id="main">
    <div id="side">
      <h3>Тип записи</h3>
      <div class="legend" id="rec-legend"></div>
      <h3>Поселения</h3>
      <div class="legend" id="sett-legend"></div>
      <h3>Связи</h3>
      <div class="legend" id="rel-legend"></div>
      <h3>Радиус фокуса</h3>
      <div id="hop-ctl">
        <input type="range" id="hop-slider" min="1" max="10" value="3" step="1">
        <span class="hop-val" id="hop-label">3</span>
      </div>
      <h3>Фильтры</h3>
      <div id="filters">
        <button data-filter="birth"  id="filt-birth">Рождение</button>
        <button data-filter="wedding" id="filt-wedding">Брак</button>
        <button data-filter="all" class="active" id="filt-all">Все</button>
      </div>
      <div id="detail">
        <div id="det-name"></div>
        <div id="det-sett"></div>
        <div id="det-year"></div>
        <div id="det-type"></div>
        <div id="det-role"></div>
        <div id="det-owner"></div>
        <div id="det-archive"></div>
      </div>
    </div>
    <div id="right-panel">
      <div id="rp-header">
        <span id="rp-title">Видимые персоны (0)</span>
        <button id="rp-close-btn">&times;</button>
      </div>
      <div id="rp-list"></div>
      <button id="rp-csv-btn">&#128190; Скачать CSV</button>
    </div>
    <div id="graph-container">
      <div id="loading">Загрузка</div>
      <div id="graph"></div>
    </div>
  </div>
</div>

<script>
var COMPONENTS = {comp_json};
var REL_COLORS = {rel_json};
var REC_COLORS  = {rec_json};
var SETT_COLORS = {sett_json};

var network = null;
var allNodesDs = null;   // vis.DataSet for current component
var allEdgesDs = null;
var currentCompIdx = -1;

var box = document.getElementById('graph');
var loadEl = document.getElementById('loading');
var detail = document.getElementById('detail');
var searchInp = document.getElementById('search');

// ── focus mode ───────────────────────────────────────────────────────
var focusNodeId = null;
var focusHop    = 3;
var focusBar = document.getElementById('focus-bar');

function getNeighborIds(nodeId, maxHop) {{
  var nids = new Set();
  nids.add(nodeId);
  var fringe = [nodeId];
  for (var hop = 0; hop < maxHop; hop++) {{
    var next = [];
    fringe.forEach(function(fid) {{
      allEdgesDs.get().forEach(function(e) {{
        if (e.from === fid && !nids.has(e.to))   {{ nids.add(e.to); next.push(e.to); }}
        if (e.to   === fid && !nids.has(e.from)) {{ nids.add(e.from); next.push(e.from); }}
      }});
    }});
    fringe = next;
    if (fringe.length === 0) break;
  }}
  return nids;
}}

function applyFocus(nodeId) {{
  focusNodeId = nodeId;
  var nids = getNeighborIds(nodeId, focusHop);
  var node = allNodesDs.get(nodeId);
  focusBar.querySelector('.focus-name').textContent = node ? node.label : '?';
  focusBar.classList.add('visible');

  var nodeUpdate = allNodesDs.get().map(function(n) {{
    var visible = nids.has(n.id);
    return {{ id:n.id, hidden:!visible, physics:visible,
      color: visible ? {{ background: n._settc || '#444', border:'#111' }}
           : {{ background: colorAlpha(n._settc || '#444', 0.04), border:'#1a1a1a' }} }};
  }});
  allNodesDs.update(nodeUpdate);

  var hiddenSet = new Set();
  nodeUpdate.forEach(function(u){{ if(u.hidden) hiddenSet.add(u.id); }});
  var edgeUpdate = allEdgesDs.get().map(function(e) {{
    var h = hiddenSet.has(e.from) || hiddenSet.has(e.to);
    return {{
      id: e.id, hidden: h, physics: !h,
      color: h ? {{ color: e._orig_color.color, opacity: 0.05 }} : e._orig_color,
    }};
  }});
  allEdgesDs.update(edgeUpdate);

  updateRightPanel();
  showRightPanel();
}}

function exitFocus() {{
  if (focusNodeId === null) return;
  focusNodeId = null;
  focusBar.classList.remove('visible');
  detail.classList.remove('visible');
  hideRightPanel();
  doFilter();
}}

// ── helpers ─────────────────────────────────────────────────────────
function esc(s) {{ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

// ── physics toggle ───────────────────────────────────────────────────
var physicsOn = true;
var physBtn = document.getElementById('phys-btn');

function setPhysics(on) {{
  physicsOn = on;
  if (network) network.setOptions({{ physics: on }});
  physBtn.classList.toggle('active', on);
  physBtn.title = on ? 'Physics ON — click or P to disable' : 'Physics OFF — click or P to enable';
}}

physBtn.addEventListener('click', function() {{
  setPhysics(!physicsOn);
}});

document.addEventListener('keydown', function(e) {{
  if (e.key === 'p' && e.target.tagName !== 'INPUT') {{
    setPhysics(!physicsOn);
  }}
}});

// ── helpers continued ────────────────────────────────────────────────
function esc(s) {{ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

function colorAlpha(hex, alpha) {{
  var r = parseInt(hex.slice(1,3),16),
      g = parseInt(hex.slice(3,5),16),
      b = parseInt(hex.slice(5,7),16);
  return 'rgba('+r+','+g+','+b+','+alpha+')';
}}

// ── right panel (visible nodes list) ───────────────────────────────
var rightPanel = document.getElementById('right-panel');
var rpList = document.getElementById('rp-list');
var rpTitle = document.getElementById('rp-title');

function showRightPanel() {{ rightPanel.classList.add('visible'); }}
function hideRightPanel() {{ rightPanel.classList.remove('visible'); rpList.innerHTML = ''; rpTitle.textContent = 'Видимые персоны (0)'; }}

function _buildNodeHTML(node) {{
  var label = esc(node._first_name || '');
  if (node._patronymic) label += ' ' + esc(node._patronymic);
  if (node._surname) label += ' ' + esc(node._surname);
  if (node._year) label += ' (' + node._year + ')';

  var html = '<div class="rp-node-card">';
  html += '<div class="rp-name">' + label + '</div>';
  if (node._settlement) html += '<div class="rp-row"><b>Поселение:</b> ' + esc(node._settlement) + '</div>';
  if (node._year) html += '<div class="rp-row"><b>Год:</b> ' + node._year + '</div>';
  html += '<div class="rp-row"><b>Событие:</b> ' + esc(node._record_type || '') + '</div>';
  var roles = (node._all_roles || [node._relation_type] || []).join(', ');
  html += '<div class="rp-row"><b>Роли:</b> ' + esc(roles) + '</div>';
  if (node._landowner) html += '<div class="rp-row"><b>Помещик:</b> ' + esc(node._landowner) + '</div>';

  // archive sources
  var srcs = node._sources || [];
  var aurls = node._archive_urls || [];
  if (srcs.length > 0 || aurls.length > 0) {{
    html += '<div class="rp-src">';
    srcs.forEach(function(s, i) {{
      html += '<div>' + esc(s.archive || '') + ' (Ф. ' + esc(s.fund || '') + ', Оп. ' + esc(s.opis || '') + ', Д. ' + esc(s.delo || '') + ', стр. ' + (s.page || '') + ')</div>';
      if (s.url) html += '<div><a href="' + s.url + '" target="_blank" rel="noopener">Запись ' + (i+1) + ' &rarr;</a></div>';
    }});
    if (srcs.length === 0 && aurls.length > 0) {{
      aurls.forEach(function(url, i) {{
        html += '<div><a href="' + url + '" target="_blank" rel="noopener">Запись ' + (i+1) + ' &rarr;</a></div>';
      }});
    }}
    html += '</div>';
  }}

  html += '</div>';
  return html;
}}

function updateRightPanel() {{
  var nodes = allNodesDs ? allNodesDs.get().filter(function(n){{ return !n.hidden; }}) : [];
  rpTitle.textContent = 'Видимые персоны (' + nodes.length + ')';
  rpList.innerHTML = nodes.map(function(n) {{ return _buildNodeHTML(n); }}).join('');
}}

function csvEsc(v) {{ var s = String(v || ''); if (s.indexOf(',')>=0 || s.indexOf('"')>=0 || s.indexOf('\\n')>=0) return '"'+s.replace(/"/g,'""')+'"'; return s; }}

function exportCSV() {{
  var nodes = allNodesDs ? allNodesDs.get().filter(function(n){{ return !n.hidden; }}) : [];
  if (nodes.length === 0) return;

  var lines = ['Name,Settlement,Year,Record Type,Relation Type,Roles,Landowner,Archive,Fund,Opis,Delo,Page,URL'];
  nodes.forEach(function(n) {{
    var name = ((n._first_name||'')+' '+(n._patronymic||'')+' '+(n._surname||'')).trim();
    var rowBase = [csvEsc(name), csvEsc(n._settlement), n._year||'', csvEsc(n._record_type||''), csvEsc(n._relation_type||''), csvEsc((n._all_roles||[n._relation_type]||[]).join('; ')), csvEsc(n._landowner)];

    var srcs = n._sources || [];
    if (srcs.length > 0) {{
      srcs.forEach(function(s) {{
        var r = rowBase.concat([csvEsc(s.archive), s.fund||'', s.opis||'', s.delo||'', s.page||'', csvEsc(s.url)]);
        lines.push(r.join(','));
      }});
    }} else {{
      var r = rowBase.concat(['','','','','', csvEsc((n._archive_urls||[])[0]||'')]);
      lines.push(r.join(','));
    }}
  }});

  var csv = '\\uFEFF' + lines.join('\\n');
  var blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8' }});
  var link = document.createElement('a');
  link.download = 'persons_' + (currentCompIdx + 1) + '.csv';
  link.href = URL.createObjectURL(blob);
  link.click();
  URL.revokeObjectURL(link.href);
}}

// ── build legends ───────────────────────────────────────────────────
function buildLegends(comp) {{
  // record type
  var rl = document.getElementById('rec-legend');
  var recCounts = {{}};
  comp.nodes.forEach(function(n) {{ recCounts[n.record_type] = (recCounts[n.record_type]||0)+1; }});
  rl.innerHTML = '';
  for (var rt in recCounts) {{
    rl.innerHTML += '<div class="legend-item"><span class="legend-swatch" style="background:'+(REC_COLORS[rt]||'#888')+'"></span><span class="legend-label">'+esc(rt)+'</span><span class="legend-count">'+recCounts[rt]+'</span></div>';
  }}

  // settlement
  var sl = document.getElementById('sett-legend');
  var settCounts = {{}};
  comp.nodes.forEach(function(n) {{
    var s = n.settlement || '(без)';
    settCounts[s] = (settCounts[s]||0)+1;
  }});
  var sortedSetts = Object.entries(settCounts).sort(function(a,b){{ return b[1]-a[1]; }});
  sl.innerHTML = '';
  var shown = 0;
  sortedSetts.forEach(function(pair) {{
    if (shown >= 30) return;
    shown++;
    var c = SETT_COLORS[pair[0]] || SETT_COLORS[null];
    sl.innerHTML += '<div class="legend-item" data-sett="'+esc(pair[0])+'"><span class="legend-swatch" style="background:'+c+'"></span><span class="legend-label">'+esc(pair[0])+'</span><span class="legend-count">'+pair[1]+'</span></div>';
  }});
  _updateLegendUI();

  // relation colours
  var rl2 = document.getElementById('rel-legend');
  rl2.innerHTML = '';
  for (var r in REL_COLORS) {{
    rl2.innerHTML += '<div class="legend-rel"><span class="legend-rel-line" style="background:'+REL_COLORS[r]+'"></span>'+esc(r)+'</div>';
  }}
}}

// ── build network ───────────────────────────────────────────────────
function makeNetwork(comp) {{
  // nodes
  var ns = comp.nodes.map(function(n) {{
    var settc = n._settc;
    var deg = n._deg || 0;
    var size = 6 + Math.min(deg * 2, 26);
    var blw = Math.min(deg * 0.5, 3);

    var tip = '<b>'+esc(n.first_name)+'</b>';
    if (n.patronymic) tip += '<br>Отчество: '+esc(n.patronymic);
    if (n.surname) tip += '<br>Фамилия: '+esc(n.surname);
    tip += '<br>Год: '+(n.year||'–');
    tip += '<br>Событие: '+esc(n.record_type);
    var roles = n.all_roles || [n.relation_type];
    tip += '<br>Роль: '+esc(n.relation_type);
    if (n.settlement) tip += '<br>Поселение: <span style="color:'+settc+'">'+esc(n.settlement)+'</span>';
    if (n.landowner) tip += '<br>Помещик: '+esc(n.landowner);

    return {{
      id: n.id,
      label: n.first_name + (n.patronymic ? ' '+n.patronymic : '') + (n.surname ? ' '+n.surname : '') + (n.year ? ' ('+n.year+')' : ''),
      color: {{ background: settc, border: '#111' }},
      size: size,
      borderWidth: blw,
      borderWidthSelected: 3,
      font: {{ color: '#eee', size: 11, face: 'Segoe UI' }},
      _tip: tip,
      _settc: settc,
      _settlement: n.settlement,
      _record_type: n.record_type,
      _all_roles: roles,
      _archive_urls: n.archive_urls || [],
      _sources: n.sources || [],
      _first_name: n.first_name,
      _patronymic: n.patronymic,
      _surname: n.surname,
      _year: n.year,
      _landowner: n.landowner,
      _relation_type: n.relation_type,
    }};
  }});

  // edges — merge multi-edges into one thick edge per pair
  var REL_PRIORITY = ['child_of', 'married_to', 'godparent_of', 'witnessed_for', 'other'];
  var pairMap = {{}};
  comp.edges.forEach(function(e) {{
    var k = e.source_id + '|' + e.target_id;
    if (!pairMap[k]) pairMap[k] = {{ rels: {{}}, count: 0 }};
    pairMap[k].rels[e.relation] = true;
    pairMap[k].count++;
  }});
  var es = [];
  for (var k in pairMap) {{
    var p = pairMap[k];
    var ids = k.split('|');
    // pick highest-priority relation for colour
    var rel = 'witnessed_for';
    for (var ri = 0; ri < REL_PRIORITY.length; ri++) {{
      if (p.rels[REL_PRIORITY[ri]]) {{ rel = REL_PRIORITY[ri]; break; }}
    }}
    var w = 1 + Math.min(p.count * 1.2, 6);
    var tip = Object.keys(p.rels).join(', ') + ' (' + p.count + ')';
    var origColor = {{ color: REL_COLORS[rel] || '#888', opacity: 0.7 }};
    es.push({{
      id: k,
      from: parseInt(ids[0]),
      to: parseInt(ids[1]),
      title: tip,
      _rels: Object.keys(p.rels),
      _orig_color: origColor,
      color: origColor,
      width: w,
      smooth: {{ type: 'continuous' }},
    }});
  }}

  allNodesDs = new vis.DataSet(ns);
  allEdgesDs = new vis.DataSet(es);

  var phys = {{}};
  if (comp.nodes.length <= 40) {{
    phys = {{ solver:'barnesHut', barnesHut:{{ gravitationalConstant:-3000, centralGravity:0.3, springLength:200, damping:0.09 }}, stabilization:{{ iterations:200 }} }};
  }} else if (comp.nodes.length <= 200) {{
    phys = {{ solver:'barnesHut', barnesHut:{{ gravitationalConstant:-5000, centralGravity:0.3, springLength:180, damping:0.09 }}, stabilization:{{ iterations:300 }} }};
  }} else {{
    phys = {{ solver:'barnesHut', barnesHut:{{ gravitationalConstant:-12000, centralGravity:0.2, springLength:250, damping:0.09 }}, stabilization:{{ iterations:400 }} }};
  }}

  network = new vis.Network(box, {{
    nodes: allNodesDs,
    edges: allEdgesDs,
  }}, {{
    physics: phys,
    interaction: {{ hover:false, navigationButtons:true, keyboard:true, multiselect:false }},
    nodes: {{ shape:'dot' }},
    edges: {{ smooth:{{ type:'continuous' }}, chosen: false }},
  }});

  network.on('stabilizationIterationsDone', function() {{
    loadEl.classList.add('hidden');
    setPhysics(true);
  }});

  network.on('click', function(params) {{
    if (params.nodes.length === 1) {{
      var node = allNodesDs.get(params.nodes[0]);
      // clear sidebar first
      detail.classList.remove('visible');
      ['det-name','det-sett','det-year','det-type','det-role','det-owner','det-archive'].forEach(function(id) {{ document.getElementById(id).innerHTML = ''; }});
      // re-center focus if focus mode is active
      if (focusNodeId !== null && focusNodeId !== params.nodes[0]) {{
        applyFocus(params.nodes[0]);
      }}
      // show new data
      detail.classList.add('visible');
      document.getElementById('det-name').innerHTML = '<b>'+esc(node.label)+'</b>';
      document.getElementById('det-sett').innerHTML = node._tip.split('<br>').filter(function(l){{ return l.includes('Поселение'); }}).join('') || '';
      var parts = node._tip.split('<br>');
      document.getElementById('det-year').innerHTML = parts.filter(function(l){{ return l.includes('Год'); }})[0] || '';
      document.getElementById('det-type').innerHTML = parts.filter(function(l){{ return l.includes('Событие'); }})[0] || '';
      var roles = (node._all_roles || []).join(', ');
      document.getElementById('det-role').innerHTML  = '<b>Роли:</b> '+esc(roles);
      document.getElementById('det-owner').innerHTML = parts.filter(function(l){{ return l.includes('Помещик'); }})[0] || '';
      var aurls = node._archive_urls || [];
      var archiveHtml = '';
      if (aurls.length > 0) {{
        archiveHtml = '<div class="archive-box">';
        aurls.forEach(function(url, i) {{
          archiveHtml += '<a href="' + url + '" target="_blank" rel="noopener" class="archive-link">Запись ' + (i+1) + ' →</a>';
        }});
        archiveHtml += '</div>';
      }}
      document.getElementById('det-archive').innerHTML = archiveHtml;
    }} else {{
      detail.classList.remove('visible');
    }}
  }});

  network.on('deselectNode', function() {{ detail.classList.remove('visible'); }});

  network.on('doubleClick', function(params) {{
    if (params.nodes.length === 1) {{
      applyFocus(params.nodes[0]);
    }}
  }});
}}

// ── load component ──────────────────────────────────────────────────
function loadComponent(idx) {{
  if (focusNodeId !== null) exitFocus();
  var comp = COMPONENTS[idx];
  if (!comp) return;
  currentCompIdx = idx;

  loadEl.classList.remove('hidden');
  if (network) {{ network.destroy(); network = null; }}

  document.getElementById('stats').textContent =
    comp.nodes.length + ' узлов, ' + comp.edges.length + ' связей';

  buildLegends(comp);
  detail.classList.remove('visible');
  searchInp.value = '';
  _selectedSettlements.clear();
  _updateLegendUI();

  // reset filter buttons
  document.querySelectorAll('#filters button').forEach(function(b){{ b.classList.remove('active'); }});
  document.getElementById('filt-all').classList.add('active');

  makeNetwork(comp);  // synchronous — network assigned, event-driven hide
}}

// ── search / filter ─────────────────────────────────────────────────
var searchTimer = null;
searchInp.addEventListener('input', function() {{
  if (focusNodeId !== null) exitFocus();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(doFilter, 200);
}});

function doFilter() {{
  if (focusNodeId !== null) return;
  if (!allNodesDs) return;
  var q = searchInp.value.toLowerCase().trim();
  var activeFilter = document.querySelector('#filters button.active').dataset.filter;

  var update = allNodesDs.get().map(function(n) {{
    var visible = true;

    // record-type filter
    if (activeFilter === 'birth')   visible = n._record_type === 'Родившийся';
    if (activeFilter === 'wedding') visible = n._record_type === 'Бракосочетание';

    // settlement multi-select filter
    if (visible && _selectedSettlements.size > 0) {{
      visible = _selectedSettlements.has(n._settlement) || _selectedSettlements.has(n._settlement || '(без)');
    }}

    // text search
    if (q && visible) {{
      var haystack = (n.label+' '+(n._tip||'')+' '+(n._settlement||'')).toLowerCase();
      visible = haystack.includes(q);
    }}

    return {{ id:n.id, hidden:!visible, physics:visible, color: visible ? {{ background: n._settc || SETT_COLORS['null'] || '#444', border:'#111' }} : {{ background: colorAlpha(n._settc || '#444', 0.05), border:'#1a1a1a' }} }};
  }});
  allNodesDs.update(update);

  // hide edges: by hidden endpoint + by relation type
  var REL_FILTER = {{ birth: ['child_of','godparent_of'], wedding: ['married_to','witnessed_for'] }};
  var hiddenSet = new Set();
  update.forEach(function(u){{ if(u.hidden) hiddenSet.add(u.id); }});
  var edgeUpdates = allEdgesDs.get().map(function(e) {{
    var h = hiddenSet.has(e.from) || hiddenSet.has(e.to);
    if (!h && activeFilter !== 'all') {{
      var match = e._rels.some(function(r){{ return REL_FILTER[activeFilter].indexOf(r) !== -1; }});
      if (!match) h = true;
    }}
    return {{ id:e.id, hidden:h, physics:!h, color: h ? {{ color: e._orig_color.color, opacity: 0.05 }} : e._orig_color }};
  }});
  allEdgesDs.update(edgeUpdates);
}}

document.getElementById('filters').addEventListener('click', function(e) {{
  if (e.target.tagName !== 'BUTTON') return;
  if (focusNodeId !== null) exitFocus();
  document.querySelectorAll('#filters button').forEach(function(b){{ b.classList.remove('active'); }});
  e.target.classList.add('active');
  doFilter();
}});

// ── settlement legend multi-select ─────────────────────────────────
var _selectedSettlements = new Set();

function _updateLegendUI() {{
  document.querySelectorAll('#sett-legend .legend-item').forEach(function(el) {{
    el.classList.toggle('active', _selectedSettlements.has(el.dataset.sett));
  }});
}}

document.getElementById('sett-legend').addEventListener('click', function(e) {{
  var item = e.target.closest('.legend-item');
  if (!item) return;
  var sett = item.dataset.sett;
  if (_selectedSettlements.has(sett)) {{
    _selectedSettlements.delete(sett);
  }} else {{
    _selectedSettlements.add(sett);
  }}
  _updateLegendUI();
  doFilter();
}});

// right-click or long-press to clear all selections
document.getElementById('sett-legend').addEventListener('contextmenu', function(e) {{
  e.preventDefault();
  _selectedSettlements.clear();
  _updateLegendUI();
  doFilter();
}});

// ── hop slider ───────────────────────────────────────────────────────
document.getElementById('hop-slider').addEventListener('input', function() {{
  focusHop = parseInt(this.value);
  document.getElementById('hop-label').textContent = focusHop;
  if (focusNodeId !== null) {{
    applyFocus(focusNodeId);
  }}
}});

// ── component selector ──────────────────────────────────────────────
document.getElementById('comp').addEventListener('change', function() {{
  loadComponent(parseInt(this.value));
}});

// ── focus bar close button ───────────────────────────────────────────
focusBar.querySelector('button').addEventListener('click', function() {{
  exitFocus();
}});

// ── right panel buttons ──────────────────────────────────────────────
document.getElementById('rp-close-btn').addEventListener('click', function() {{
  if (focusNodeId !== null) exitFocus();
}});
document.getElementById('rp-csv-btn').addEventListener('click', function() {{
  exportCSV();
}});

// ── Esc key exits focus ──────────────────────────────────────────────
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape' && focusNodeId !== null) {{
    exitFocus();
  }}
}});

// ── save as PNG ──────────────────────────────────────────────────────
document.getElementById('save-btn').addEventListener('click', function() {{
  if (!network) return;
  var src = network.canvas.frame.canvas;
  var tmp = document.createElement('canvas');
  tmp.width = src.width;
  tmp.height = src.height;
  var ctx = tmp.getContext('2d');
  ctx.fillStyle = '#0d1117';
  ctx.fillRect(0, 0, tmp.width, tmp.height);
  ctx.drawImage(src, 0, 0);
  var link = document.createElement('a');
  link.download = 'graph_' + (currentCompIdx + 1) + '.png';
  link.href = tmp.toDataURL('image/png');
  link.click();
}});

// ── startup ─────────────────────────────────────────────────────────
var defaultIdx = 0;
document.getElementById('comp').value = defaultIdx;
loadComponent(defaultIdx);
</script>
</body>
</html>"""
    return html


def main():
    all_nodes = json.loads(NODES_FILE.read_text(encoding="utf-8"))
    all_edges = json.loads(EDGES_FILE.read_text(encoding="utf-8"))

    G = nx.Graph()
    for n in all_nodes:
        G.add_node(n["id"])
    for e in all_edges:
        G.add_edge(e["source_id"], e["target_id"])

    node_map = {n["id"]: n for n in all_nodes}

    components = []
    for comp_nodes in nx.connected_components(G):
        lst = sorted(comp_nodes)
        st = set(lst)
        comp_edges = [e for e in all_edges if e["source_id"] in st and e["target_id"] in st]
        components.append({
            "size":       len(lst),
            "edge_count": len(comp_edges),
            "nodes":      [node_map[nid] for nid in lst],
            "edges":      comp_edges,
        })

    components.sort(key=lambda c: -c["size"])

    print(f"Components: {len(components)}")
    for i, c in enumerate(components):
        tag = " (heavy)" if c["size"] > 200 else ""
        print(f"  #{i+1}: {c['size']} nodes, {c['edge_count']} edges{tag}")

    html = build_html(components)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"\nSaved: {OUTPUT}")


if __name__ == "__main__":
    main()
