// Diagnostics tab: what the models cost and how long each step takes, from /api/diagnostics.
import { esc } from './panels.js';

const usd = (v) => (v ? `$${v < 0.1 ? v.toFixed(4) : v.toFixed(2)}` : '$0');
const when = (t) => new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const panel = (title, body, cls = '') => `<section class="panel ${cls}"><h3>${esc(title)}</h3>${body}</section>`;
const none = (what) => `<p class="muted">${what}</p>`;

function roles(spend) {
  const rows = Object.entries(spend.roles);
  if (!rows.length) return none('No model calls yet.');
  return `<table><tr><th>for</th><th>calls</th><th>cost</th></tr>${rows
    .map(([r, x]) => `<tr><td>${esc(r)}</td><td>${x.calls}</td><td>${usd(x.cost)}</td></tr>`).join('')}
    <tr><td><b>total</b></td><td>${spend.calls}</td><td><b>${usd(spend.cost)}</b></td></tr></table>`;
}

function spend(d) {
  const s = d.session;
  const here = s.uid ? `${esc(s.track)} · ${esc(s.type)}` : 'no session';
  return panel(`This session (${here})`, roles(s))
    + panel('Today', roles(d.today))
    + panel('All time', roles(d.allTime));
}

function byType(rows) {
  if (!rows.length) return none('Nothing spent in a session yet.');
  return `<table><tr><th>session type</th><th>sessions</th><th>calls</th><th>cost</th><th>per session</th></tr>${rows
    .map((r) => `<tr><td>${esc(r.type)}</td><td>${r.sessions}</td><td>${r.calls}</td><td>${usd(r.cost)}</td><td>${usd(r.perSession)}</td></tr>`).join('')}</table>`;
}

function recent(rows) {
  if (!rows.length) return none('No sessions with model calls yet.');
  return `<table><tr><th>started</th><th>session</th><th>answers</th><th>calls</th><th>cost</th></tr>${rows
    .map((r) => `<tr><td>${when(r.started)}</td><td>${esc(r.track)} · ${esc(r.type)}</td><td>${r.answers}</td><td>${r.calls}</td><td>${usd(r.cost)}</td></tr>`).join('')}</table>`;
}

function offSession(rows) {
  if (!rows.length) return none('No evals or dev calls this week.');
  return `<table><tr><th>for</th><th>calls</th><th>cost</th></tr>${rows
    .map((r) => `<tr><td>${esc(r.role)}</td><td>${r.calls}</td><td>${usd(r.cost)}</td></tr>`).join('')}</table>`;
}

function latency(rows) {
  const cell = (p, unit) => (p ? `${p.p50}${unit} / ${p.p90}${unit} <span class="muted">(${p.n})</span>` : '<span class="muted">–</span>');
  return `<table><tr><th>step</th><th>this session p50 / p90</th><th>past week p50 / p90</th></tr>${rows
    .map((r) => `<tr><td>${esc(r.label)}</td><td>${cell(r.session, r.unit)}</td><td>${cell(r.week, r.unit)}</td></tr>`).join('')}</table>`;
}

function counts(rows, errors) {
  const list = rows.map((r) => `<dt>${esc(r.label)}</dt><dd>${r.n}</dd>`).join('');
  const errs = errors.recent.map((e) => `<li><span class="muted">${when(e.at)} ${esc(e.role)} · ${esc(e.model)}</span> ${esc(e.error)}</li>`).join('');
  return `<dl class="kv">${list}<dt>model errors</dt><dd>${errors.session}</dd></dl>`
    + (errs ? `<h4>Recent model errors</h4><ul class="errors">${errs}</ul>` : '');
}

function team(t) {
  if (!t) return none('No pit wall running (--no-pitwall, or no API key).');
  const pct = t.budget ? Math.min(100, (t.spent / t.budget) * 100) : 0;
  return `<dl class="kv"><dt>spent this session</dt><dd>${usd(t.spent)} of ${usd(t.budget)}</dd>
    <dt>runs</dt><dd>${t.runs}</dd><dt>models</dt><dd>${t.models.map(esc).join(' · ')}</dd></dl>
    <div class="bar" role="meter" aria-label="Team budget used" aria-valuenow="${pct.toFixed(0)}" aria-valuemin="0" aria-valuemax="100">
    <i style="width:${pct}%;background:${pct >= 100 ? 'var(--bad)' : 'var(--good)'}"></i></div>
    <p class="muted">Past the budget, only urgent changes (safety car, rain, damage, slicks) and your questions get a run.</p>`;
}

function feed(f, version) {
  const wrong = Object.keys(f.wrongFormats);
  return `<dl class="kv"><dt>Lift and Coast</dt><dd>${esc(version ?? '–')}</dd>
    <dt>game version</dt><dd>${esc(f.gameVersion ?? '–')}</dd>
    <dt>UDP format</dt><dd>${esc(f.format ?? '–')}</dd>
    <dt>packets</dt><dd>${f.packets}</dd><dt>decode errors</dt><dd>${f.decodeErrors}</dd>
    <dt>last packet</dt><dd>${f.silentSecs == null ? 'none yet' : `${f.silentSecs.toFixed(0)} s ago`}</dd>
    ${wrong.length ? `<dt>wrong formats</dt><dd>${esc(wrong.join(', '))}</dd>` : ''}</dl>
    <p class="muted">Packet rates and sizes are on the Packets tab.</p>`;
}

// the debug bundle form: kept here so a poll's re-render doesn't lose what's typed
export const bundle = { note: '', audio: true, telemetry: true, state: 'idle', files: [], folder: '', error: '' };

function bundlePanel() {
  const b = bundle;
  const mb = (n) => `${(n / 1e6).toFixed(1)} MB`;
  const result = {
    idle: '',
    making: '<p class="muted" role="status">Making it… a long race takes about half a minute.</p>',
    error: `<p class="bad" role="alert">Couldn't make it: ${esc(b.error)}</p>`,
    done: `<p role="status">Saved in <code>${esc(b.folder)}</code>${b.files.length > 1 ? `, in ${b.files.length} parts: attach them all` : ''}:</p>
      <ul>${b.files.map((f) => `<li><a href="/api/bundle?name=${encodeURIComponent(f.name)}" download>${esc(f.name)}</a> <span class="muted">${mb(f.bytes)}</span></li>`).join('')}</ul>`,
  }[b.state];
  return `<div class="bundle"><p class="muted">One file with this session's recording, the radio, what the models were sent and said, the log and your setup. It stays on this computer until you attach it to an issue yourself.</p>
    <label for="bundleNote">What went wrong</label>
    <textarea id="bundleNote" rows="2" placeholder="e.g. it said 43% for the rear-left on lap 10">${esc(b.note)}</textarea>
    <label><input type="checkbox" id="bundleAudio" ${b.audio ? 'checked' : ''}> radio audio (your voice and the engineer's)</label>
    <label><input type="checkbox" id="bundleTelemetry" ${b.telemetry ? 'checked' : ''}> telemetry (the session's recording)</label>
    <p><button id="bundleMake" ${b.state === 'making' ? 'disabled aria-busy="true"' : ''}>Make a debug bundle</button></p>${result}</div>`;
}

export function render(d, error) {
  if (error && !d) return `<div class="empty"><h2>Couldn't load diagnostics</h2><p class="muted">${esc(error.message)}</p></div>`;
  if (!d) return '<div class="empty">Loading…</div>';
  return `<div class="grid">${spend(d)}
    ${panel('By session type', byType(d.byType))}
    ${panel('Recent sessions', recent(d.recent), 'wide')}
    ${panel('Evals and dev (past week)', offSession(d.offSession))}
    ${panel('Pit wall budget', team(d.team))}
    ${panel('Latency', latency(d.latency), 'wide')}
    ${panel('This session', counts(d.counts, d.errors))}
    ${panel('Telemetry feed', feed(d.feed, d.version))}
    ${panel('Debug bundle', bundlePanel(), 'wide')}</div>`;
}
