from flask import Flask, request, jsonify, render_template_string
import anthropic
import os
import sqlite3
import json
from datetime import datetime

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

DB_PATH = os.environ.get("DB_PATH", "trentradar.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saved_trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            desc TEXT,
            momentum TEXT,
            signals TEXT,
            sources TEXT,
            format_hint TEXT,
            tag TEXT,
            region TEXT,
            saved_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trentradar</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f9f9f7; color: #1a1a1a; min-height: 100vh; }
.dash { max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem; }
.top-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 12px; }
.logo { font-size: 16px; font-weight: 600; color: #1a1a1a; letter-spacing: -0.3px; }
.logo span { color: #888; font-weight: 400; }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
select { font-size: 12px; padding: 5px 12px; border-radius: 20px; border: 1px solid #ddd; background: #fff; color: #555; cursor: pointer; outline: none; }
.btn { font-size: 13px; padding: 8px 18px; border-radius: 8px; border: 1px solid #ddd; background: #fff; color: #1a1a1a; cursor: pointer; font-weight: 500; white-space: nowrap; }
.btn:hover { background: #f0f0f0; }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn.primary { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
.btn.primary:hover { background: #333; }
.source-bar { display: flex; gap: 6px; margin-bottom: 1.5rem; flex-wrap: wrap; }
.src-tag { font-size: 11px; padding: 4px 10px; border-radius: 20px; border: 1px solid #e0e0e0; background: #fff; color: #888; cursor: pointer; user-select: none; }
.src-tag.on { border-color: #5DCAA5; background: #E1F5EE; color: #0F6E56; }
.status-row { font-size: 12px; color: #aaa; margin-bottom: 1.5rem; }
.nav-tabs { display: flex; margin-bottom: 2rem; border-bottom: 1px solid #e8e8e8; }
.nav-tab { font-size: 13px; padding: 8px 18px; cursor: pointer; color: #aaa; border-bottom: 2px solid transparent; margin-bottom: -1px; font-weight: 500; }
.nav-tab.active { color: #1a1a1a; border-bottom-color: #1a1a1a; }
.grid { display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; }
@media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
.section-label { font-size: 10px; font-weight: 600; color: #aaa; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 10px; }
.tab-row { display: flex; margin-bottom: 1rem; border-bottom: 1px solid #e8e8e8; }
.tab { font-size: 13px; padding: 6px 14px; cursor: pointer; color: #aaa; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab.active { color: #1a1a1a; border-bottom-color: #1a1a1a; font-weight: 500; }
.trend-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 10px; }
.trend-card.saved { border-left: 3px solid #1D9E75; }
.trend-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
.trend-name { font-size: 15px; font-weight: 600; color: #1a1a1a; line-height: 1.3; }
.mbadge { font-size: 10px; padding: 3px 8px; border-radius: 20px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
.m-rising { background: #EAF3DE; color: #3B6D11; }
.m-emerging { background: #FAEEDA; color: #854F0B; }
.m-established { background: #E6F1FB; color: #185FA5; }
.m-shifting { background: #FBEAF0; color: #993556; }
.trend-desc { font-size: 13px; color: #555; line-height: 1.6; margin-bottom: 8px; }
.trend-signals { font-size: 12px; color: #999; line-height: 1.5; }
.trend-footer { display: flex; gap: 6px; margin-top: 10px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
.src-chip { font-size: 10px; padding: 2px 8px; border-radius: 20px; background: #f5f5f5; color: #888; border: 1px solid #e8e8e8; }
.act-btn { font-size: 11px; padding: 4px 10px; border-radius: 6px; border: 1px solid #ddd; background: transparent; color: #888; cursor: pointer; }
.act-btn:hover { background: #f5f5f5; }
.act-btn.is-saved { color: #0F6E56; border-color: #5DCAA5; background: #E1F5EE; }
.hint-box { display: none; margin-top: 8px; font-size: 12px; font-style: italic; color: #185FA5; border-top: 1px solid #f0f0f0; padding-top: 8px; }
.signal-item { display: flex; gap: 10px; padding: 9px 0; border-bottom: 1px solid #f0f0f0; }
.signal-item:last-child { border-bottom: none; }
.sig-dot { width: 6px; height: 6px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.d-reddit { background: #E24B4A; } .d-news { background: #185FA5; } .d-research { background: #1D9E75; } .d-trends { background: #BA7517; }
.sig-text { font-size: 13px; color: #1a1a1a; line-height: 1.4; }
.sig-meta { font-size: 11px; color: #aaa; margin-top: 2px; }
.saved-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.saved-item:last-child { border-bottom: none; }
.tag-input { font-size: 11px; border: 1px solid #e0e0e0; border-radius: 6px; padding: 3px 8px; background: #f9f9f7; color: #555; width: 90px; outline: none; }
.format-card { background: #f5f5f3; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 10px; border: 1px solid #e8e8e8; }
.format-title { font-size: 14px; font-weight: 600; color: #1a1a1a; margin-bottom: 4px; }
.format-desc { font-size: 13px; color: #555; line-height: 1.6; }
.format-hook { font-size: 12px; color: #999; margin-top: 6px; font-style: italic; }
.empty { text-align: center; padding: 2.5rem; color: #bbb; font-size: 13px; }
.errbox { background: #fff0f0; border: 1px solid #ffcccc; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #c00; margin-bottom: 1rem; }
.loader { display: inline-block; width: 10px; height: 10px; border: 1.5px solid #ddd; border-top-color: #888; border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; margin-right: 5px; }
@keyframes spin { to { transform: rotate(360deg); } }
.archive-grid { display: grid; grid-template-columns: 200px 1fr; gap: 1.5rem; }
@media (max-width: 700px) { .archive-grid { grid-template-columns: 1fr; } }
.date-list { border-right: 1px solid #e8e8e8; padding-right: 1.5rem; }
.date-item { padding: 8px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; font-size: 13px; color: #555; }
.date-item:hover { background: #f0f0f0; }
.date-item.active { background: #1a1a1a; color: #fff; }
.date-count { font-size: 11px; opacity: 0.6; margin-left: 6px; }
.archive-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 10px; }
.archive-card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.archive-name { font-size: 14px; font-weight: 600; color: #1a1a1a; }
.archive-meta { font-size: 11px; color: #aaa; margin-bottom: 6px; }
.archive-desc { font-size: 13px; color: #555; line-height: 1.5; }
.appearances { font-size: 11px; color: #aaa; margin-top: 6px; font-style: italic; }
</style>
</head>
<body>
<div class="dash">
  <div class="top-bar">
    <div class="logo">Trentradar <span>— cultural signals for unscripted formats</span></div>
    <div class="controls" id="scan-controls">
      <select id="region-sel">
        <option value="nl">NL focus</option>
        <option value="eu">EU / global</option>
        <option value="all">All markets</option>
      </select>
      <select id="horizon-sel">
        <option value="emerging">Emerging</option>
        <option value="rising">Rising</option>
        <option value="all">All signals</option>
      </select>
      <button class="btn primary" id="scan-btn" onclick="runScan()">Scan now</button>
    </div>
  </div>

  <div class="nav-tabs">
    <div class="nav-tab active" id="nav-dashboard" onclick="switchView('dashboard')">Dashboard</div>
    <div class="nav-tab" id="nav-archive" onclick="switchView('archive')">Archive</div>
  </div>

  <div id="view-dashboard">
    <div class="source-bar">
      <span class="src-tag on" data-src="Reddit" onclick="this.classList.toggle('on')">Reddit</span>
      <span class="src-tag on" data-src="NL nieuws" onclick="this.classList.toggle('on')">NL nieuws</span>
      <span class="src-tag on" data-src="Research" onclick="this.classList.toggle('on')">Research</span>
      <span class="src-tag on" data-src="Trend reports" onclick="this.classList.toggle('on')">Trend reports</span>
      <span class="src-tag on" data-src="Global culture" onclick="this.classList.toggle('on')">Global culture</span>
    </div>
    <div id="err-box"></div>
    <div class="status-row" id="status-row">Last scan: —</div>
    <div class="grid">
      <div>
        <div class="tab-row">
          <div class="tab active" id="tab-t" onclick="switchTab('trends')">Cultural trends</div>
          <div class="tab" id="tab-f" onclick="switchTab('formats')">Format ideas</div>
        </div>
        <div id="pane-trends">
          <div class="section-label">Detected trends</div>
          <div id="trends-list"><div class="empty">Press "Scan now" to detect cultural trends.</div></div>
        </div>
        <div id="pane-formats" style="display:none">
          <div class="section-label">Format concepts</div>
          <div id="formats-list"><div class="empty">Save some trends, then generate format ideas.</div></div>
        </div>
      </div>
      <div>
        <div class="section-label">Live signals</div>
        <div id="signal-feed"><div class="empty">Signals appear here after scanning.</div></div>
        <div style="margin-top:1.5rem">
          <div class="section-label">Saved this session</div>
          <div id="saved-list"><div class="empty">No saved trends yet.</div></div>
          <div id="gen-row" style="display:none;margin-top:12px">
            <button class="btn" style="width:100%" onclick="generateFormats()">Generate format ideas</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div id="view-archive" style="display:none">
    <div id="archive-err"></div>
    <div class="archive-grid">
      <div class="date-list">
        <div class="section-label">Browse by date</div>
        <div id="date-list"><div class="empty" style="padding:1rem 0">Loading...</div></div>
      </div>
      <div>
        <div class="section-label" id="archive-heading">Select a date</div>
        <div id="archive-content"><div class="empty">Select a date to browse saved trends.</div></div>
      </div>
    </div>
  </div>
</div>

<script>
var saved = [];
var trends = [];

function switchView(v) {
  document.getElementById('view-dashboard').style.display = v==='dashboard' ? '' : 'none';
  document.getElementById('view-archive').style.display = v==='archive' ? '' : 'none';
  document.getElementById('scan-controls').style.display = v==='dashboard' ? '' : 'none';
  document.getElementById('nav-dashboard').className = 'nav-tab' + (v==='dashboard' ? ' active' : '');
  document.getElementById('nav-archive').className = 'nav-tab' + (v==='archive' ? ' active' : '');
  if (v === 'archive') loadArchive();
}

function switchTab(t) {
  document.getElementById('pane-trends').style.display = t==='trends' ? '' : 'none';
  document.getElementById('pane-formats').style.display = t==='formats' ? '' : 'none';
  document.getElementById('tab-t').className = 'tab' + (t==='trends' ? ' active' : '');
  document.getElementById('tab-f').className = 'tab' + (t==='formats' ? ' active' : '');
}

function showErr(msg) { document.getElementById('err-box').innerHTML = '<div class="errbox"><strong>Error:</strong> ' + msg + '</div>'; }
function clearErr() { document.getElementById('err-box').innerHTML = ''; }

async function callClaude(prompt, maxTokens) {
  var res = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_tokens: maxTokens || 1500, messages: [{ role: 'user', content: prompt }] })
  });
  var data = await res.json();
  if (!res.ok) throw new Error('Server error: ' + (data.error || res.status));
  var text = data.content.filter(function(b){ return b.type==='text'; }).map(function(b){ return b.text; }).join('\n');
  if (!text) throw new Error('Empty response');
  return text;
}

function parseJSON(text) {
  var cleaned = text.replace(/```json\n?/g,'').replace(/```\n?/g,'').trim();
  var match = cleaned.match(/\{[\s\S]*\}/);
  if (!match) throw new Error('No JSON in response');
  return JSON.parse(match[0]);
}

async function runScan() {
  clearErr();
  var btn = document.getElementById('scan-btn');
  btn.disabled = true; btn.textContent = 'Scanning...';
  document.getElementById('status-row').innerHTML = '<span class="loader"></span>Scanning sources...';
  document.getElementById('trends-list').innerHTML = '<div class="empty"><span class="loader"></span>Detecting trends...</div>';
  document.getElementById('signal-feed').innerHTML = '<div class="empty"><span class="loader"></span>Processing...</div>';

  var region = document.getElementById('region-sel').value;
  var horizon = document.getElementById('horizon-sel').value;
  var sources = Array.from(document.querySelectorAll('.src-tag.on')).map(function(e){ return e.dataset.src; });
  var regionLabel = {nl:'Dutch / Netherlands',eu:'European and global',all:'global including NL EU US Asia'}[region];
  var horizonLabel = {emerging:'emerging (weak signals, not yet mainstream)',rising:'rising (growing momentum)',all:'all momentum stages'}[horizon];

  var prompt = 'You are a cultural trend analyst for a Dutch unscripted TV format development team. Identify meaningful, durable human and cultural trends - not viral hypes.\n\nContext:\n- Region focus: ' + regionLabel + '\n- Trend horizon: ' + horizonLabel + '\n- Simulated sources: ' + sources.join(', ') + '\n- Today: ' + new Date().toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric'}) + '\n- Focus areas: human connection, identity, belonging, loneliness, relationships, lifestyle, work culture, aging, youth, family, technology\'s emotional impact\n\nRespond with ONLY a JSON object. No text before or after. Start with { and end with }.\n\n{"signalCount":34,"trends":[{"name":"trend name here","momentum":"rising","desc":"Two sentences describing the trend.","signals":"Two concrete signals supporting this.","sources":["Reddit","NL nieuws"],"formatHint":"One-line TV format angle."}],"rawSignals":[{"type":"reddit","text":"Signal headline max 12 words","meta":"Source and timeframe"}]}\n\nGenerate exactly 5 trends and 8 rawSignals. Make them specific, human, relevant to reality and entertainment TV.';

  try {
    var text = await callClaude(prompt, 2000);
    var result = parseJSON(text);
    if (!result.trends || !Array.isArray(result.trends)) throw new Error('No trends array in response');
    trends = result.trends;
    renderTrends(region);
    renderSignals(result.rawSignals || []);
    var now = new Date().toLocaleTimeString('nl-NL',{hour:'2-digit',minute:'2-digit'});
    document.getElementById('status-row').textContent = 'Last scan: ' + now + ' — ' + (result.signalCount || (result.rawSignals ? result.rawSignals.length : 0)) + ' signals processed';
  } catch(e) {
    showErr(e.message);
    document.getElementById('status-row').textContent = 'Scan failed.';
    document.getElementById('trends-list').innerHTML = '<div class="empty">Scan failed — see error above.</div>';
    document.getElementById('signal-feed').innerHTML = '<div class="empty">—</div>';
  }
  btn.disabled = false; btn.textContent = 'Scan now';
}

function renderTrends(region) {
  var el = document.getElementById('trends-list');
  if (!trends.length) { el.innerHTML='<div class="empty">No trends detected.</div>'; return; }
  el.innerHTML = trends.map(function(t,i) {
    var isSaved = saved.find(function(s){ return s.name===t.name; });
    var mc = {rising:'m-rising',emerging:'m-emerging',established:'m-established',shifting:'m-shifting'}[t.momentum]||'m-emerging';
    return '<div class="trend-card' + (isSaved?' saved':'') + '" id="tc-' + i + '">' +
      '<div class="trend-top"><div class="trend-name">' + t.name + '</div><span class="mbadge ' + mc + '">' + t.momentum + '</span></div>' +
      '<div class="trend-desc">' + t.desc + '</div>' +
      '<div class="trend-signals">' + t.signals + '</div>' +
      '<div class="trend-footer">' +
        '<div style="display:flex;gap:4px;flex-wrap:wrap">' + (t.sources||[]).map(function(s){ return '<span class="src-chip">'+s+'</span>'; }).join('') + '</div>' +
        '<div style="display:flex;gap:6px">' +
          (t.formatHint ? '<button class="act-btn" onclick="toggleHint(' + i + ')">format hint</button>' : '') +
          '<button class="act-btn' + (isSaved?' is-saved':'') + '" id="sb-' + i + '" onclick="doSave(' + i + ',\'' + (region||'nl') + '\')">' + (isSaved?'saved':'save') + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="hint-box" id="hint-' + i + '">' + (t.formatHint||'') + '</div>' +
    '</div>';
  }).join('');
}

function toggleHint(i) {
  var h = document.getElementById('hint-'+i);
  h.style.display = h.style.display==='block' ? 'none' : 'block';
}

async function doSave(i, region) {
  var t = trends[i];
  if (saved.find(function(s){ return s.name===t.name; })) return;
  saved.push({name:t.name, desc:t.desc, tag:''});
  document.getElementById('sb-'+i).textContent = 'saved';
  document.getElementById('sb-'+i).classList.add('is-saved');
  document.getElementById('tc-'+i).classList.add('saved');
  renderSaved();
  try {
    await fetch('/archive/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: t.name, desc: t.desc, momentum: t.momentum, signals: t.signals, sources: t.sources, format_hint: t.formatHint, tag: '', region: region || 'nl' })
    });
  } catch(e) { console.error('Archive save failed:', e); }
}

function renderSaved() {
  var el = document.getElementById('saved-list');
  document.getElementById('gen-row').style.display = saved.length ? '' : 'none';
  if (!saved.length) { el.innerHTML='<div class="empty">No saved trends yet.</div>'; return; }
  el.innerHTML = saved.map(function(t,i){
    return '<div class="saved-item">' +
      '<div style="font-size:13px;color:#1a1a1a">' + t.name + '</div>' +
      '<div style="display:flex;gap:6px;align-items:center">' +
        '<input class="tag-input" placeholder="tag..." value="' + t.tag + '" oninput="saved['+i+'].tag=this.value"/>' +
        '<span style="cursor:pointer;font-size:12px;color:#aaa" onclick="saved.splice('+i+',1);renderSaved()">&#x2715;</span>' +
      '</div></div>';
  }).join('');
}

function renderSignals(signals) {
  var el = document.getElementById('signal-feed');
  if (!signals.length) { el.innerHTML='<div class="empty">No signals.</div>'; return; }
  el.innerHTML = signals.map(function(s){
    return '<div class="signal-item"><div class="sig-dot d-' + (s.type||'news') + '"></div><div><div class="sig-text">' + s.text + '</div><div class="sig-meta">' + s.meta + '</div></div></div>';
  }).join('');
}

async function generateFormats() {
  if (!saved.length) return;
  switchTab('formats');
  document.getElementById('formats-list').innerHTML='<div class="empty"><span class="loader"></span>Generating format concepts...</div>';
  var trendList = saved.map(function(t,i){ return (i+1)+'. "'+t.name+'": '+t.desc+(t.tag?' [tag: '+t.tag+']':''); }).join('\n');
  var prompt = 'You are a senior unscripted TV format developer at a Dutch production company. Generate format concepts based on these cultural trends:\n\n' + trendList + '\n\nRespond with ONLY a JSON object. No text before or after. Start with { end with }.\n\n{"formats":[{"title":"Format title","logline":"One punchy sentence.","trendBasis":"Which trend(s)","hook":"What makes this emotionally compelling for Dutch audience?","channel":"e.g. NPO1, RTL4, Netflix NL"}]}\n\nGenerate exactly 3 specific, pitchable format concepts.';
  try {
    var text = await callClaude(prompt, 1200);
    var result = parseJSON(text);
    document.getElementById('formats-list').innerHTML = result.formats.map(function(f){
      return '<div class="format-card"><div class="format-title">' + f.title + '</div><div class="format-desc">' + f.logline + '</div><div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap"><span class="src-chip">' + f.channel + '</span><span class="src-chip" style="font-style:italic">' + f.trendBasis + '</span></div><div class="format-hook">"' + f.hook + '"</div></div>';
    }).join('');
  } catch(e) {
    showErr('Format generation failed: ' + e.message);
    document.getElementById('formats-list').innerHTML='<div class="empty">Failed — see error above.</div>';
  }
}

async function loadArchive() {
  document.getElementById('date-list').innerHTML = '<div class="empty" style="padding:1rem 0"><span class="loader"></span></div>';
  try {
    var res = await fetch('/archive/dates');
    var data = await res.json();
    if (!data.dates || !data.dates.length) {
      document.getElementById('date-list').innerHTML = '<div class="empty" style="padding:1rem 0;font-size:12px">No archived trends yet.<br>Save trends from the dashboard first.</div>';
      return;
    }
    document.getElementById('date-list').innerHTML = data.dates.map(function(d){
      return '<div class="date-item" onclick="loadDate(\'' + d.date + '\', this)">' + d.date + '<span class="date-count">' + d.count + '</span></div>';
    }).join('');
    var first = document.querySelector('.date-item');
    if (first) first.click();
  } catch(e) {
    document.getElementById('archive-err').innerHTML = '<div class="errbox">Could not load archive: ' + e.message + '</div>';
  }
}

async function loadDate(date, el) {
  document.querySelectorAll('.date-item').forEach(function(d){ d.classList.remove('active'); });
  el.classList.add('active');
  document.getElementById('archive-heading').textContent = 'Saved on ' + date;
  document.getElementById('archive-content').innerHTML = '<div class="empty"><span class="loader"></span>Loading...</div>';
  try {
    var res = await fetch('/archive/by-date?date=' + encodeURIComponent(date));
    var data = await res.json();
    if (!data.trends || !data.trends.length) {
      document.getElementById('archive-content').innerHTML = '<div class="empty">No trends for this date.</div>';
      return;
    }
    document.getElementById('archive-content').innerHTML = data.trends.map(function(t){
      var mc = {rising:'m-rising',emerging:'m-emerging',established:'m-established',shifting:'m-shifting'}[t.momentum]||'m-emerging';
      return '<div class="archive-card">' +
        '<div class="archive-card-top"><div class="archive-name">' + t.name + '</div><span class="mbadge ' + mc + '">' + (t.momentum||'') + '</span></div>' +
        '<div class="archive-meta">' + t.saved_at + (t.region ? ' &middot; ' + t.region.toUpperCase() : '') + (t.tag ? ' &middot; <strong>' + t.tag + '</strong>' : '') + '</div>' +
        '<div class="archive-desc">' + (t.desc||'') + '</div>' +
        (t.appearances > 1 ? '<div class="appearances">Spotted ' + t.appearances + 'x — first saved ' + t.first_seen + '</div>' : '') +
      '</div>';
    }).join('');
  } catch(e) {
    document.getElementById('archive-content').innerHTML = '<div class="empty">Could not load trends.</div>';
  }
}
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/chat", methods=["POST"])
def chat():
    body = request.json
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=body.get("max_tokens", 2000),
        messages=body.get("messages", [])
    )
    return jsonify({"content": [{"type": "text", "text": message.content[0].text}]})

@app.route("/archive/save", methods=["POST"])
def archive_save():
    body = request.json
    conn = get_db()
    conn.execute("""
        INSERT INTO saved_trends (name, desc, momentum, signals, sources, format_hint, tag, region, saved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        body.get("name"),
        body.get("desc"),
        body.get("momentum"),
        body.get("signals"),
        json.dumps(body.get("sources", [])),
        body.get("format_hint"),
        body.get("tag", ""),
        body.get("region", "nl"),
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/archive/dates")
def archive_dates():
    conn = get_db()
    rows = conn.execute("""
        SELECT substr(saved_at, 1, 10) as date, COUNT(*) as count
        FROM saved_trends
        GROUP BY date
        ORDER BY date DESC
    """).fetchall()
    conn.close()
    return jsonify({"dates": [{"date": r["date"], "count": r["count"]} for r in rows]})

@app.route("/archive/by-date")
def archive_by_date():
    date = request.args.get("date", "")
    conn = get_db()
    rows = conn.execute("""
        SELECT *,
               COUNT(*) OVER (PARTITION BY name) as appearances,
               MIN(saved_at) OVER (PARTITION BY name) as first_seen
        FROM saved_trends
        WHERE substr(saved_at, 1, 10) = ?
        ORDER BY saved_at DESC
    """, (date,)).fetchall()
    conn.close()
    return jsonify({"trends": [dict(r) for r in rows]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
