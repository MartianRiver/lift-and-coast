// Pit wall tab: the strategy team's plans and their discussion, from /api/pitwall.
import { esc } from './panels.js';

const usd = (v) => (v ? `$${v < 0.1 ? v.toFixed(4) : v.toFixed(2)}` : '$0');
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const short = (model) => (model || '').split('/').pop();

function plans(w) {
  if (!Object.keys(w.plans).length && w.prep?.note?.plans) w = { ...w, ...w.prep.note, plans: w.prep.note.plans };  // before the race: the prep's
  const keys = ['A', 'B', 'C'].filter((k) => w.plans[k]);
  if (!keys.length) {
    return '<p class="muted">No plans yet. The team writes plans A, B and C when the race starts (or when it first sees one already running).</p>';
  }
  return `<ul class="pw-plans">${keys.map((k) => `<li class="${k === w.active ? 'active' : ''}">
    <b>Plan ${k}</b>${k === w.active ? ' <span class="pill drs">active</span>' : ''}<div>${esc(w.plans[k])}</div></li>`).join('')}</ul>
    ${w.box ? `<p>Planned stop: end of lap <b>${w.box}</b></p>` : ''}
    <p class="muted small">Say “go plan B” on the radio to switch.</p>`;
}

function note(n) {
  const head = `<span class="muted small">L${n.lap} · ${clock(n.at)} · ${esc(short(n.model))}${n.cost ? ` · ${usd(n.cost)}` : ''}${n.ms ? ` · ${(n.ms / 1000).toFixed(1)} s` : ''}</span>`;
  if (n.who === 'review') {
    const verdict = n.agree == null ? '' : n.agree ? '<b class="good">agrees</b>' : '<b class="warn">disagrees</b>';
    return `<div class="pw-note review"><div>${head}</div><div>Second opinion ${verdict}: ${esc(n.text)}</div></div>`;
  }
  const why = n.reasons?.length ? `<div class="muted small">Called for: ${n.reasons.map(esc).join(' · ')}</div>` : '';
  if (n.error) return `<div class="pw-note"><div>${head}</div>${why}<div class="bad">Run failed: ${esc(n.error)}</div></div>`;
  return `<div class="pw-note"><div>${head}</div>${why}
    <div class="pw-call">${esc(n.call || '(no call)')}</div>
    ${n.say ? `<div class="pw-say">On the radio: “${esc(n.say)}”</div>` : '<div class="muted small">Nothing for the radio.</div>'}
    ${n.why ? `<div class="pw-why">${esc(n.why)}</div>` : ''}</div>`;
}

function chat(w) {
  const running = w.running ? `<div class="pw-note running"><span class="muted">Thinking… (${w.running.reasons.map(esc).join(' · ')})</span></div>` : '';
  const pending = w.pending.length ? `<p class="muted small">Waiting to run: ${w.pending.map(esc).join(' · ')}</p>` : '';
  // newest call first, each with its second opinion under it
  const leads = w.notes.filter((n) => n.who !== 'review').reverse();
  const reviews = w.notes.filter((n) => n.who === 'review');
  const notes = leads.flatMap((n) => [n, ...reviews.filter((r) => r.of === n.id)]);
  if (!notes.length && !running) {
    return pending + '<p class="muted">Nothing yet. The team runs in races: at the start, when something changes (safety car, rain, a stop around you, tyres nearly done, damage, your strategy questions) and every 5 laps otherwise.</p>';
  }
  return running + pending + notes.map(note).join('');
}

function brief(w) {
  const at = w.brief ? new Date(w.brief.at * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : '';
  return `<form id="pwBriefForm" class="pw-brief">
    <label for="pwBrief" class="muted small">How you want to race this one (the team plans around it). Or on the radio: “tell the team …”</label>
    <textarea id="pwBrief" rows="3" placeholder="e.g. Messed up quali, limited rewinds: damage control, low risk">${esc(w.brief?.text || '')}</textarea>
    <div class="toolbar"><button class="btn" type="submit">Save</button>
      <button class="btn" type="button" id="pwBriefClear">Clear</button>
      <span class="muted small" id="pwBriefStatus" role="status">${w.brief ? `saved ${esc(at)}` : 'nothing saved'}</span></div></form>`;
}

function prep(w) {
  const p = w.prep || {};
  const button = `<button class="btn" type="button" id="pwPrep" ${p.running ? 'disabled' : ''}>${p.running ? 'Preparing…' : p.note ? 'Prepare again' : 'Prepare the race'}</button>`;
  const intro = '<p class="muted small">After qualifying, before the strategy screen: fuel, starting tyre and plans from your qualifying and earlier races. The race picks it up when it loads.</p>';
  if (p.error) return `${intro}${button}<p class="bad">${esc(p.error)}</p>`;
  if (!p.note) return intro + button;
  const n = p.note, when = new Date(p.at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const review = p.review ? `<div class="muted small">Second opinion ${p.review.agree === false ? '<b class="warn">disagrees</b>' : '<b class="good">agrees</b>'}: ${esc(p.review.text)}</div>` : '';
  return `<p class="muted small">${esc(p.track || '')} · ${p.laps ? `≈${p.laps} laps · ` : ''}made ${when}</p>
    <dl class="kv pw-prep"><dt>Fuel</dt><dd>${esc(n.fuel || '–')}</dd><dt>Start on</dt><dd>${esc(n.start || '–')}</dd></dl>
    <div class="pw-call">${esc(n.call || '')}</div><div class="pw-why">${esc(n.why || '')}</div>${review}
    <p>${button}</p>`;
}

export function render(w, error) {
  if (error && !w) return `<div class="empty"><h2>Couldn't load the pit wall</h2><p class="muted">${esc(error.message)}</p></div>`;
  if (!w) return '<div class="empty">Loading…</div>';
  if (w.off) return '<div class="empty"><h2>No pit wall</h2><p class="muted">The server was started with --no-pitwall, or there\'s no API key. The engineer and the code make the strategy calls.</p></div>';
  return `<div class="grid pw">
    <section class="panel"><h3>Race prep</h3>${prep(w)}<h3>Your brief</h3>${brief(w)}<h3>Plans</h3>${plans(w)}
      <p class="muted small">Team: ${w.models.map((m) => esc(short(m))).join(' + ')} · ${usd(w.spent)} of ${usd(w.budget)} this session</p></section>
    <section class="panel pw-chat" aria-live="polite"><h3>Strat chat</h3>${chat(w)}</section></div>`;
}
