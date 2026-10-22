import * as P from './panels.js';
import * as Radio from './radio.js';
import * as Race from './race.js';
import * as Diag from './diagnostics.js';
import * as Wall from './pitwall.js';
import * as Driver from './driver.js';
import * as Settings from './settings.js';

const POLL_MS = 250;
const $ = (s) => document.querySelector(s);
const ui = { tab: 'race', carIdx: null, rawId: null, logFilter: { level: '', module: '' } };
let snap = null, carData = null, rawData = null, logEntries = [], lastError = null;
let race = null, raceError = null;
let diag = null, diagError = null, diagAt = 0;
let wall = null, wallError = null;
const DIAG_MS = 2000; // it's SQL behind it, and nothing there moves faster

function setTab(tab) {
  ui.tab = tab;
  document.body.dataset.tab = tab; // the floating radio card hides on Race, which has its own feed
  history.replaceState(null, '', `#${tab}`);
  document.querySelectorAll('#tabs button').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === tab));
  render();
  tick();
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return r.json();
}

async function tick() {
  try {
    snap = await getJSON('/api/state');
    if (ui.tab === 'car') {
      const idx = ui.carIdx ?? snap.playerIdx ?? snap.cars[0]?.idx;
      carData = idx == null ? null : await getJSON(`/api/car?idx=${idx}`);
    }
    if (ui.tab === 'race') await pollRace();
    if (ui.tab === 'diagnostics') await pollDiag();
    if (ui.tab === 'pitwall') await pollWall();
    if (ui.tab === 'packets' && ui.rawId != null) rawData = await getJSON(`/api/raw?id=${ui.rawId}`);
    if (ui.tab === 'logs') {
      const since = logEntries.at(-1)?.t ?? 0;
      logEntries = logEntries.concat(await getJSON(`/api/logs?since=${since}`)).slice(-2000);
    }
    lastError = null;
  } catch (e) {
    lastError = e;
    console.error('[app] poll failed', e);
  }
  render();
}

async function pollRace() {
  try {
    const r = await fetch('/api/race');
    if (!r.ok) throw new Error(`/api/race → HTTP ${r.status}`);
    race = await r.json();
    raceError = null;
  } catch (e) {
    raceError = e;
    console.error('[app] race poll failed', e);
  }
}

async function pollWall() {
  try {
    wall = await getJSON('/api/pitwall');
    wallError = null;
  } catch (e) {
    wallError = e;
    console.error('[app] pit wall poll failed', e);
  }
}

async function pollDiag() {
  if (Date.now() - diagAt < DIAG_MS) return;
  diagAt = Date.now();
  try {
    diag = await getJSON('/api/diagnostics');
    diagError = null;
  } catch (e) {
    diagError = e;
    console.error('[app] diagnostics poll failed', e);
  }
}

function header() {
  const conn = $('#conn');
  if (lastError && !snap) {
    conn.className = 'conn err';
    conn.innerHTML = '<span class="dot"></span>dashboard server not reachable';
    return;
  }
  if (!snap) return;
  const m = snap.meta;
  if (lastError) {
    conn.className = 'conn err';
    conn.innerHTML = `<span class="dot"></span>lost contact with dashboard server`;
  } else if (m.receiving) {
    const hz = snap.packets.find((p) => p.id === 2)?.rate ?? 0;
    conn.className = 'conn ok';
    conn.innerHTML = `<span class="dot"></span>live · game v${P.esc(m.gameVersion)} · ${hz.toFixed(0)} Hz${m.listen.recording ? ' · ● rec' : ''}`;
  } else {
    conn.className = 'conn stale';
    conn.innerHTML = `<span class="dot"></span>${m.totalPackets ? `no data for ${m.lastPacketAgeSec.toFixed(0)}s (paused / menus?)` : `waiting on ${P.esc(m.listen.ip)}:${m.listen.udpPort}`}`;
  }
  const s = snap.session;
  const me = snap.cars.find((c) => c.isPlayer);
  $('#sessionBar').innerHTML = s ? [
    ['', `${s.names.track} · ${s.names.sessionType}`],
    ['Lap', me ? (s.ruleSet === 1 ? `${me.lap}/${s.totalLaps}` : me.lap) : '–'],
    ['P', me?.position ?? '–'],
    s.ruleSet === 1 && me ? ['To go', Math.max(0, s.totalLaps - me.lap)]
      : ['Left', `${Math.floor(s.sessionTimeLeft / 60)}:${String(s.sessionTimeLeft % 60).padStart(2, '0')}`],
    ['Wx', `${s.names.weather} ${s.trackTemperature}°/${s.airTemperature}°`],
    ...(m.sessionCost ? [['$', m.sessionCost.toFixed(m.sessionCost < 1 ? 3 : 2)]] : []),
    ...(s.safetyCarStatus ? [['', `<span class="warn">${P.esc(s.names.safetyCar)}</span>`]] : []),
  ].map(([k, v]) => `<span>${k ? `<b>${k}</b>` : ''}${k === '' && String(v).startsWith('<') ? v : P.esc(v)}</span>`).join('') : '';

  const warn = [];
  if (Object.keys(m.wrongFormats).length) warn.push(`<div class="banner warn">The game is sending UDP format ${P.esc(Object.keys(m.wrongFormats).join(', '))}. Set <b>UDP Format</b> to <b>2026</b> (F1 25), <b>2025</b> or <b>2024</b> (F1 24) in the game's telemetry settings.</div>`);
  if (m.errorCount) warn.push(`<div class="banner err">${m.errorCount} packets failed to decode — latest: ${P.esc(m.recentErrors.at(-1)?.msg)}</div>`);
  $('#banner').innerHTML = warn.join('');
  $('#logsTab').hidden = !m.listen.dev;
}

function emptyState(m) {
  return `<div class="empty"><h2>Waiting for telemetry</h2>
    <p>In F1 25 → Settings → Telemetry Settings:</p>
    <p>UDP Telemetry <code>On</code> · Broadcast <code>Off</code> · IP <code>${P.esc(m.listen.ip)}</code> · Port <code>${m.listen.udpPort}</code> · Format <code>2026</code></p>
    <p>Then go on track — most packets only flow while driving or spectating.</p></div>`;
}

// keep scroll positions across re-renders
function preserveScroll(fn) {
  const els = [...document.querySelectorAll('#view .scroll, #view pre.json')].map((e) => [e.scrollTop, e.scrollLeft]);
  fn();
  document.querySelectorAll('#view .scroll, #view pre.json').forEach((e, i) => {
    if (els[i]) [e.scrollTop, e.scrollLeft] = els[i];
  });
}

function render() {
  header();
  // don't yank an open dropdown out from under the user
  if (['SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName) && $('#view').contains(document.activeElement)) return;
  const view = $('#view');
  if (!snap) {
    view.innerHTML = lastError ? `<div class="empty"><h2>Can't reach the dashboard server</h2><p>Is <code>uv run python -m engineer.server</code> running?</p><p class="muted">${P.esc(lastError.message)}</p></div>` : '<div class="empty">Loading…</div>';
    return;
  }
  if (ui.tab === 'radio') {
    // mounted once and updated in place so the hold timer and animation don't reset every poll
    if (!view.querySelector('#radio')) {
      view.innerHTML = Radio.markup();
      Radio.update();
    }
    return;
  }
  if (ui.tab === 'settings') {
    // mounted once: it has inputs, and it only changes when you change something
    if (!view.querySelector('#settings')) {
      view.innerHTML = Settings.markup();
      Settings.load();
    }
    return;
  }
  if (ui.tab === 'race' && snap.meta.totalPackets) {
    if (!view.querySelector('#race')) {
      view.innerHTML = Race.markup();
      Race.updateFeed();
    }
    Race.update(race, raceError);
    return;
  }
  if (!snap.meta.totalPackets && !['logs', 'diagnostics', 'pitwall'].includes(ui.tab)) {
    view.innerHTML = emptyState(snap.meta);
    return;
  }
  preserveScroll(() => {
    switch (ui.tab) {
      case 'timing': view.innerHTML = P.timing(snap); break;
      case 'car': view.innerHTML = carData ? P.car(carData, snap.cars, snap) : '<p class="muted">No car data yet.</p>'; break;
      case 'session': view.innerHTML = P.session(snap.session); break;
      case 'events': view.innerHTML = P.events(snap); break;
      case 'packets': view.innerHTML = P.packets(snap, ui.rawId, rawData); break;
      case 'logs': view.innerHTML = P.logs(logEntries, ui.logFilter); break;
      case 'diagnostics': view.innerHTML = Diag.render(diag, diagError); break;
      case 'pitwall': view.innerHTML = Wall.render(wall, wallError); break;
    }
  });
}

function download(name, text, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

$('#tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]');
  if (b) setTab(b.dataset.tab);
});

function activate(e) {
  const car = e.target.closest('[data-car]');
  if (car) {
    ui.carIdx = Number(car.dataset.car);
    carData = null;
    return setTab('car');
  }
  const raw = e.target.closest('[data-raw]');
  if (raw) {
    ui.rawId = Number(raw.dataset.raw);
    rawData = null;
    tick();
  }
  if (e.target.id === 'logExportTxt') download('lift-and-coast-log.txt', logEntries.map((l) => `${new Date(l.t * 1000).toISOString()} [${l.level}] [${l.module}] ${l.msg}${l.data ? ' ' + JSON.stringify(l.data) : ''}${l.exc ? '\n' + l.exc : ''}`).join('\n'), 'text/plain');
  if (e.target.id === 'logExportJson') download('lift-and-coast-log.json', JSON.stringify(logEntries, null, 1), 'application/json');
}
async function saveBrief(text) {
  const status = $('#pwBriefStatus');
  try {
    const r = await fetch('/api/pitwall/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    wall = await r.json();
    document.activeElement?.blur();
    render();
  } catch (e) {
    if (status) status.textContent = `couldn't save: ${e.message}`;
    console.error('[app] brief save failed', e);
  }
}
$('#view').addEventListener('submit', (e) => {
  if (e.target.id !== 'pwBriefForm') return;
  e.preventDefault();
  saveBrief($('#pwBrief').value);
});
async function prepare() {
  try {
    const r = await fetch('/api/pitwall/prep', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    wall = await r.json();
    render();
  } catch (e) {
    wallError = e;
    console.error('[app] race prep failed', e);
  }
}
async function makeBundle() {
  const b = Diag.bundle;
  b.state = 'making';
  render();
  try {
    const r = await fetch('/api/bundle', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: b.note, audio: b.audio, telemetry: b.telemetry }) });
    const out = await r.json();
    if (!r.ok) throw new Error(out.error || `HTTP ${r.status}`);
    Object.assign(b, { state: 'done', files: out.files, folder: out.folder });
  } catch (e) {
    Object.assign(b, { state: 'error', error: e.message });
    console.error('[app] debug bundle failed', e);
  }
  render();
}
$('#view').addEventListener('input', (e) => {
  if (e.target.id === 'bundleNote') Diag.bundle.note = e.target.value;
  if (e.target.id === 'bundleAudio') Diag.bundle.audio = e.target.checked;
  if (e.target.id === 'bundleTelemetry') Diag.bundle.telemetry = e.target.checked;
});
$('#view').addEventListener('click', (e) => {
  if (e.target.id === 'bundleMake') makeBundle();
  if (e.target.id === 'pwBriefClear') saveBrief('');
  if (e.target.id === 'pwPrep') prepare();
});
$('#view').addEventListener('click', activate);
$('#view').addEventListener('keydown', (e) => { if (e.key === 'Enter') activate(e); });
$('#view').addEventListener('change', (e) => {
  if (e.target.id === 'carSel') { ui.carIdx = Number(e.target.value); e.target.blur(); tick(); }
  if (e.target.id === 'logLevel') { ui.logFilter.level = e.target.value; e.target.blur(); render(); }
  if (e.target.id === 'logModule') { ui.logFilter.module = e.target.value; e.target.blur(); render(); }
});

const TABS = [...document.querySelectorAll('#tabs button')].map((b) => b.dataset.tab);
const initial = location.hash.slice(1);
setTab(TABS.includes(initial) ? initial : 'race');
window.addEventListener('hashchange', () => {
  const tab = location.hash.slice(1);
  if (TABS.includes(tab) && tab !== ui.tab) setTab(tab);
});
Radio.watch(Race.updateFeed);

async function loop() {
  await tick();
  setTimeout(loop, POLL_MS);
}
loop();
Driver.start();
