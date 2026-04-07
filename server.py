from flask import Flask, request, jsonify, render_template_string
import anthropic
import os

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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
.scan-btn { font-size: 13px; padding: 8px 18px; border-radius: 8px; border: 1px solid #ddd; background: #fff; color: #1a1a1a; cursor: pointer; font-weight: 500; }
.scan-btn:hover { background: #f0f0f0; }
.scan-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.scan-btn.primary { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
.scan-btn.primary:hover { background: #333; }
.source-bar { display: flex; gap: 6px; margin-bottom: 1.5rem; flex-wrap: wrap; }
.src-tag { font-size: 11px; padding: 4px 10px; border-radius: 20px; border: 1px solid #e0e0e0; background: #fff; color: #888; cursor: pointer; user-select: none; transition: all 0.15s; }
.src-tag.on { border-color: #5DCAA5; background: #E1F5EE; color: #0F6E56; }
.status-row { font-size: 12px; color: #aaa; margin-bottom: 1.5rem; }
.grid { display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; }
@media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
.section-label { font-size: 10px; font-weight: 600; color: #aaa; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 10px; }
.tab-row { display: flex; margin-bottom: 1rem; border-bottom: 1px solid #e8e8e8; }
.tab { font-size: 13px; padding: 6px 14px; cursor: pointer; color: #aaa; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab.active { color: #1a1a1a; border-bottom-color: #1a1a1a; font-weight: 500; }
.trend-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 10px; transition: border-color 0.15s; }
.trend-card:hover { border-color: #ccc; }
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
.errbox { background: #fff0f0; border: 1px solid #ffcccc; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #c00; margin-bottom: 1rem; word-break: break-all; }
.loader { display: inline-block; width: 10px; height: 10px; border: 1.5px solid #ddd; border-top-color: #888; border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; margin-right: 5px; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="dash">
  <div class="top-bar">
    <div class="logo">Trentradar <span>— cultural signals for unscripted formats</span></div>
    <div class="controls">
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
      <button class="scan-btn primary" id="scan-btn" onclick="runScan()">Scan now ↗</button>
    </div>
  </div>

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
        <div class="section-label">Saved trends</div>
        <div id="saved-list"><div class="empty">No saved trends yet.</div></div>
        <div id="gen-row" style="display:none;margin-top:12px">
          <button class="scan-btn" style="width:100%" onclick="generateFormats()">Generate format ideas ↗</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
let saved = [];
let trends = [];

function showErr(msg) { document.getElementById('err-box').innerHTML = '<div class="errbox"><strong>Error:</strong> ' + msg + '</div>'; }
function clearErr() { document.getElementById('err-box').innerHTML = ''; }

function switchTab(t) {
  document.getElementById('pane-trends').style.display = t==='trends'?'':'none';
  document.getElementById('pane-formats').style.display = t==='formats'?'':'none';
  document.getElementById('tab-t').className='tab'+(t==='trends'?' active':'');
  document.getElementById('tab-f').className='tab'+(t==='formats'?' active':'');
}

async function callClaude(prompt, maxTokens) {
  const res = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_tokens: maxTokens || 1500, messages: [{ role: 'user', content: prompt }] })
  });
  const data = await res.json();
  if (!res.ok) throw new Error('Server error: ' + (data.error || res.status));
  const text = data.content?.filter(b => b.type==='text').map(b => b.text).join('\\n');
  if (!text) throw new Error('Empty response');
  return text;
}

function parseJSON(text) {
  const cleaned = text.replace(/```json\\n?/g,'').replace(/```\\n?/g,'').trim();
  const match = cleaned.match(/\\{[\\s\\S]*\\}/);
  if (!match) throw new Error('No JSON in response');
  return JSON.parse(match[0]);
}

async function runScan() {
  clearErr();
  const btn = document.getElementById('scan-btn');
  btn.disabled = true; btn.textContent = 'Scanning...';
  document.getElementById('status-row').innerHTML = '<span class="loader"></span>Scanning sources...';
  document.getElementById('trends-list').innerHTML = '<div class="empty"><span class="loader"></span>Detecting trends...</div>';
  document.getElementById('signal-feed').innerHTML = '<div class="empty"><span class="loader"></span>Processing...</div>';

  const region = document.getElementById('region-sel').value;
  const horizon = document.getElementById('horizon-sel').value;
  const sources = [...document.querySelectorAll('.src-tag.on')].map(e => e.dataset.src);
  const regionLabel = {nl:'Dutch / Netherlands',eu:'European and global',all:'global including NL EU US Asia'}[region];
  const horizonLabel = {emerging:'emerging (weak signals, not yet mainstream)',rising:'rising (growing momentum)',all:'all momentum stages'}[horizon];

  const prompt = `You are a cultural trend analyst for a Dutch unscripted TV format development team. Identify meaningful, durable human and cultural trends - not viral hypes.

Context:
- Region focus: ${regionLabel}
- Trend horizon: ${horizonLabel}
- Simulated sources: ${sources.join(', ')}
- Today: ${new Date().toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric'})}
- Focus areas: human connection, identity, belonging, loneliness, relationships, lifestyle, work culture, aging, youth, family, technology's emotional impact

Respond with ONLY a JSON object. No text before or after. Start with { and end with }.

{"signalCount":34,"trends":[{"name":"trend name here","momentum":"rising","desc":"Two sentences describing the trend.","signals":"Two concrete signals supporting this.","sources":["Reddit","NL nieuws"],"formatHint":"One-line TV format angle."}],"rawSignals":[{"type":"reddit","text":"Signal headline max 12 words","meta":"Source and timeframe"}]}

Generate exactly 5 trends and 8 rawSignals. Make them specific, human, relevant to reality and entertainment TV.`;

  try {
    const text = await callClaude(prompt, 2000);
    const result = parseJSON(text);
    if (!result.trends || !Array.isArray(result.trends)) throw new Error('No trends array in response');
    trends = result.trends;
    renderTrends();
    renderSignals(result.rawSignals || []);
    const now = new Date().toLocaleTimeString('nl-NL',{hour:'2-digit',minute:'2-digit'});
    document.getElementById('status-row').textContent = 'Last scan: ' + now + ' — ' + (result.signalCount || result.rawSignals?.length || 0) + ' signals processed';
  } catch(e) {
    showErr(e.message);
    document.getElementById('status-row').textContent = 'Scan failed.';
    document.getElementById('trends-list').innerHTML = '<div class="empty">Scan failed — see error above.</div>';
    document.getElementById('signal-feed').innerHTML = '<div class="empty">—</div>';
  }
  btn.disabled = false; btn.textContent = 'Scan now ↗';
}

function renderTrends() {
  const el = document.getElementById('trends-list');
  if (!trends.length) { el.innerHTML='<div class="empty">No trends detected.</div>'; return; }
  el.innerHTML = trends.map(function(t,i) {
    const isSaved = saved.find(function(s){return s.name===t.name;});
    const mc = {rising:'m-rising',emerging:'m-emerging',established:'m-established',shifting:'m-shifting'}[t.momentum]||'m-emerging';
    return '<div class="trend-card' + (isSaved?' saved':'') + '" id="tc-' + i + '">' +
      '<div class="trend-top"><div class="trend-name">' + t.name + '</div><span class="mbadge ' + mc + '">' + t.momentum + '</span></div>' +
      '<div class="trend-desc">' + t.desc + '</div>' +
      '<div class="trend-signals">' + t.signals + '</div>' +
      '<div class="trend-footer">' +
        '<div style="display:flex;gap:4px;flex-wrap:wrap">' + (t.sources||[]).map(function(s){return '<span class="src-chip">'+s+'</span>';}).join('') + '</div>' +
        '<div style="display:flex;gap:6px">' +
          (t.formatHint?'<button class="act-btn" onclick="toggleHint('+i+')">format hint</button>':'') +
          '<button class="act-btn' + (isSaved?' is-saved':'') + '" id="sb-' + i + '" onclick="doSave(' + i + ')">' + (isSaved?'saved':'save') + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="hint-box" id="hint-' + i + '">' + (t.formatHint||'') + '</div>' +
    '</div>';
  }).join('');
}

function toggleHint(i) {
  const h = document.getElementById('hint-'+i);
  h.style.display = h.style.display==='block' ? 'none' : 'block';
}

function doSave(i) {
  const t = trends[i];
  if (saved.find(function(s){return s.name===t.name;})) return;
  saved.push({name:t.name,desc:t.desc,tag:''});
  document.getElementById('sb-'+i).textContent='saved';
  document.getElementById('sb-'+i).classList.add('is-saved');
  document.getElementById('tc-'+i).classList.add('saved');
  renderSaved();
}

function renderSaved() {
  const el = document.getElementById('saved-list');
  document.getElementById('gen-row').style.display = saved.length ? '' : 'none';
  if (!saved.length) { el.innerHTML='<div class="empty">No saved trends yet.</div>'; return; }
  el.innerHTML = saved.map(function(t,i){
    return '<div class="saved-item">' +
      '<div style="font-size:13px;color:#1a1a1a">' + t.name + '</div>' +
      '<div style="display:flex;gap:6px;align-items:center">' +
        '<input class="tag-input" placeholder="tag..." value="' + t.tag + '" oninput="saved['+i+'].tag=this.value"/>' +
        '<span style="cursor:pointer;font-size:12px;color:#aaa" onclick="saved.splice('+i+',1);renderSaved()">✕</span>' +
      '</div></div>';
  }).join('');
}

function renderSignals(signals) {
  const el = document.getElementById('signal-feed');
  if (!signals.length) { el.innerHTML='<div class="empty">No signals.</div>'; return; }
  el.innerHTML = signals.map(function(s){
    return '<div class="signal-item">' +
      '<div class="sig-dot d-' + (s.type||'news') + '"></div>' +
      '<div><div class="sig-text">' + s.text + '</div><div class="sig-meta">' + s.meta + '</div></div>' +
    '</div>';
  }).join('');
}

async function generateFormats() {
  if (!saved.length) return;
  switchTab('formats');
  document.getElementById('formats-list').innerHTML='<div class="empty"><span class="loader"></span>Generating format concepts...</div>';

  const trendList = saved.map(function(t,i){return (i+1)+'. "'+t.name+'": '+t.desc+(t.tag?' [tag: '+t.tag+']':'');}).join('\\n');

  const prompt = `You are a senior unscripted TV format developer at a Dutch production company. Generate format concepts based on these cultural trends:

${trendList}

Respond with ONLY a JSON object. No text before or after. Start with { end with }.

{"formats":[{"title":"Format title","logline":"One punchy sentence.","trendBasis":"Which trend(s)","hook":"What makes this emotionally compelling for Dutch audience?","channel":"e.g. NPO1, RTL4, Netflix NL"}]}

Generate exactly 3 specific, pitchable format concepts.`;

  try {
    const text = await callClaude(prompt, 1200);
    const result = parseJSON(text);
    document.getElementById('formats-list').innerHTML = result.formats.map(function(f){
      return '<div class="format-card">' +
        '<div class="format-title">' + f.title + '</div>' +
        '<div class="format-desc">' + f.logline + '</div>' +
        '<div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">' +
          '<span class="src-chip">' + f.channel + '</span>' +
          '<span class="src-chip" style="font-style:italic">' + f.trendBasis + '</span>' +
        '</div>' +
        '<div class="format-hook">"' + f.hook + '"</div>' +
      '</div>';
    }).join('');
  } catch(e) {
    showErr('Format generation failed: ' + e.message);
    document.getElementById('formats-list').innerHTML='<div class="empty">Failed — see error above.</div>';
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
