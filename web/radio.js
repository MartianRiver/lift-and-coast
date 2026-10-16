// Team radio UI. The server owns the radio (button edges, mic, STT); this only renders what
// /api/stream says: the header badge, the broadcast-style radio card, and the Radio tab.

const $ = (s) => document.getElementById(s);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const CARD_HOLD_MS = 9000;
const QUICK_FLASH_MS = 1500;

let build = null;
let names = [];
let buttons = 0;
let radio = { status: 'connecting' };
let level = 0;
let streamUp = false;
let quickAt = null;
let cardMsg = null;      // message currently shown on the card
let cardTimer = null;
const messages = [];     // newest first
let fixes = [];          // taught mishearings, {heard, meant}
const replies = {};      // engineer replies by the message id they answer
const calls = [];        // the engineer's unprompted calls, newest first
let engineer = {};       // {model, error}
const presses = [];
const watchers = [];     // other views showing the radio (Race tab)

const held = (mask, b) => Math.floor(mask / 2 ** b) % 2 === 1; // >>> breaks on bit 31

function connect() {
  const es = new EventSource('/api/stream');
  es.addEventListener('hello', (m) => {
    const d = JSON.parse(m.data);
    // server restarted (maybe with new code): reload rather than run stale JS against it
    if (build && d.build !== build) return location.reload();
    build = d.build;
    names = d.buttonNames;
    buttons = d.buttons;
    radio = d.radio;
    messages.splice(0, messages.length, ...d.messages.reverse());
    fixes = d.fixes || [];
    for (const r of d.replies || []) replies[r.to] = r;
    calls.splice(0, calls.length, ...(d.calls || []));
    engineer = d.engineer || {};
    renderFixes();
    streamUp = true;
    update();
  });
  es.addEventListener('buttons', (m) => onButtons(JSON.parse(m.data)));
  es.addEventListener('call', (m) => {
    calls.unshift(JSON.parse(m.data));
    calls.length = Math.min(calls.length, 30);
    update();
  });
  es.addEventListener('radio', (m) => {
    radio = JSON.parse(m.data);
    if (radio.status === 'open') showCard(null);
    update();
  });
  es.addEventListener('level', (m) => {
    level = JSON.parse(m.data).rms;
    drawLevel();
  });
  es.addEventListener('message', (m) => {
    const msg = JSON.parse(m.data);
    messages.unshift(msg);
    messages.length = Math.min(messages.length, 30);
    showCard(msg);
    update();
  });
  es.addEventListener('reply', (m) => onReply(JSON.parse(m.data)));
  es.addEventListener('quick', () => {
    quickAt = performance.now();
    setTimeout(update, QUICK_FLASH_MS);
    update();
  });
  es.onerror = () => {
    streamUp = false;
    console.warn('[radio] stream dropped, browser will retry');
    update();
  };
}

function onButtons(d) {
  const prev = buttons;
  buttons = d.status;
  const now = performance.now();
  for (let b = 0; b < 32; b++) {
    if (!held(prev, b) && held(buttons, b)) presses.unshift({ b, start: now, dur: null });
    if (held(prev, b) && !held(buttons, b)) {
      const p = presses.find((x) => x.b === b && x.dur == null);
      if (p) p.dur = now - p.start;
    }
  }
  presses.length = Math.min(presses.length, 20);
  update();
}

// Space mirrors the radio button (POSTed so the server applies the same toggle/hold rules)
function onKey(e) {
  if (e.code !== 'Space' || (e.target instanceof Element && e.target.closest('input, select, textarea'))) return;
  e.preventDefault();
  if (e.repeat) return;
  fetch('/api/radio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pressed: e.type === 'keydown' }) })
    .catch((err) => console.error('[radio] key post failed', err));
}

// keep the card up while the engineer answers, then for the usual hold after
function onReply(r) {
  replies[r.to] = r;
  if (r.status === 'error') console.error('[radio] engineer reply failed', r.error);
  const msg = messages.find((m) => m.id === r.to);
  if (msg && radio.status !== 'open') showCard(msg);
  if (r.status === 'thinking' || r.status === 'streaming') clearTimeout(cardTimer);
  update();
}

function replyHtml(r, full) {
  if (!r) return '';
  if (r.status === 'error') return `<div class="reply bad">Engineer: ${esc(r.error)}</div>`;
  if (r.status === 'thinking') return '<div class="reply muted">Engineer: …</div>';
  const meta = full && r.status === 'done' && !r.local
    ? `<div class="muted small">${esc(r.model)} · first word ${r.firstMs ?? '–'}ms · ${((r.totalMs || 0) / 1000).toFixed(1)}s${r.cost != null ? ` · $${r.cost.toFixed(4)}` : ''}</div>` : '';
  return `<div class="reply">${esc(r.text)}${r.status === 'streaming' ? '▍' : ''}</div>${meta}`;
}

async function onAsk(e) {
  e.preventDefault();
  const input = e.target.querySelector('input'), status = $(e.target.dataset.status || 'askStatus');
  const text = input.value.trim();
  if (!text) return;
  try {
    const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    input.value = '';
    status.textContent = '';
  } catch (err) {
    console.error('[radio] ask failed', err);
    status.innerHTML = `<span class="bad">Couldn't send: ${esc(err.message)}</span>`;
  }
}

// ------------------------------------------------------------------ card

function showCard(msg) {
  cardMsg = msg;
  clearTimeout(cardTimer);
  if (msg) cardTimer = setTimeout(() => { cardMsg = null; update(); }, CARD_HOLD_MS);
}

function surname(name) {
  const parts = String(name || 'Driver').split(' ');
  return parts.length > 1 ? `${esc(parts.slice(0, -1).join(' '))} <b>${esc(parts.at(-1).toUpperCase())}</b>` : `<b>${esc(name)}</b>`;
}

function renderCard() {
  const card = $('radioCard');
  const open = radio.status === 'open';
  const busy = radio.status === 'transcribing';
  card.hidden = !(open || busy || cardMsg);
  if (card.hidden) return;
  const driver = cardMsg?.driver;
  card.style.setProperty('--team', driver?.colour || 'var(--accent)');
  let body;
  if (open) body = '<div class="rc-live">● LIVE<span id="rcLevel" class="rc-level"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span></div>';
  else if (busy) body = '<div class="rc-live muted">…</div>';
  else if (cardMsg.text) body = `<div class="rc-quote">“${marked(cardMsg)}”</div>${replyHtml(replies[cardMsg.id], false)}`;
  else body = `<div class="rc-quote muted">(${esc(cardMsg.note || 'nothing heard')})</div>`;
  card.innerHTML = `<div class="rc-head">TEAM RADIO</div>
    <div class="rc-driver">${surname(driver?.name)}${driver?.team ? `<span class="rc-team">${esc(driver.team)}</span>` : ''}</div>${body}`;
  drawLevel();
}

function drawLevel() {
  const bars = document.querySelectorAll('#rcLevel i, #radioMeter i');
  // speech on the laptop mic sits around 0.02-0.15 rms; log-ish scale so quiet speech still shows
  const lit = Math.round(Math.min(1, Math.log10(1 + level * 300) / 1.6) * 8);
  bars.forEach((b, i) => b.classList.toggle('on', (i % 8) < lit));
}

// corrected words get underlined, with what speech-to-text actually heard on hover
function marked(m) {
  let html = esc(m.text);
  for (const c of m.changes || []) {
    html = html.replace(esc(c.meant), `<mark class="fixed" title="heard “${esc(c.heard)}” (${esc(c.how)})">${esc(c.meant)}</mark>`);
  }
  return html;
}

// ------------------------------------------------------------------ fixes

async function postFixes(path, body) {
  const status = $('fixStatus');
  try {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    fixes = d;
    status.textContent = '';
    renderFixes();
    return true;
  } catch (err) {
    console.error('[radio] fix save failed', err);
    status.innerHTML = `<span class="bad">Couldn't save: ${esc(err.message)}</span>`;
    return false;
  }
}

async function onTeach(e) {
  e.preventDefault();
  const heard = $('fixHeard').value.trim(), meant = $('fixMeant').value.trim();
  if (!heard || !meant) return ($('fixStatus').innerHTML = '<span class="warn">Fill in both.</span>');
  if (await postFixes('/api/fixes', { heard, meant })) $('fixHeard').value = $('fixMeant').value = '';
}

function renderFixes() {
  const el = $('fixList');
  if (!el) return;
  el.innerHTML = fixes.length
    ? `<table><tbody>${fixes.map((f) => `<tr><td>${esc(f.heard)}</td><td class="muted">→</td><td>${esc(f.meant)}</td>
        <td class="r"><button class="btn" data-forget="${esc(f.heard)}" aria-label="Forget fix for ${esc(f.heard)}">✕</button></td></tr>`).join('')}</tbody></table>`
    : '<p class="muted">No taught fixes yet. Names in the session, teams, tracks and radio jargon are matched automatically.</p>';
}

// one player outside the DOM: the table is re-rendered while the radio level updates, which would cut it off
const player = new Audio();
player.addEventListener('error', () => console.error('[radio] clip playback failed', player.src));

function onTabClick(e) {
  const play = e.target.closest('[data-clip]');
  if (play) {
    player.src = `/api/clip?name=${encodeURIComponent(play.dataset.clip)}`;
    return player.play().catch((err) => console.error('[radio] clip playback failed', err));
  }
  const forget = e.target.closest('[data-forget]');
  if (forget) return postFixes('/api/fixes/forget', { heard: forget.dataset.forget });
  const teach = e.target.closest('[data-teach]');
  if (teach) {
    $('fixHeard').value = teach.dataset.teach;
    $('fixMeant').focus();
  }
}

// ------------------------------------------------------------------ tab

export const feed = () => ({ messages, replies, calls, radio, streamUp });
export function watch(fn) { watchers.push(fn); }


export function markup() {
  return `<div id="radio" class="grid">
    <section class="panel radio-main">
      <div id="radioDisc" class="radio-disc" role="status" aria-live="assertive">
        <div class="radio-label" id="radioLabel">RADIO</div>
        <div class="radio-timer" id="radioTimer"></div>
      </div>
      <div id="radioMeter" class="meter" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <p id="radioHint"></p>
      <div id="quickFlash" class="quick-flash" role="status" aria-live="polite"></div>
      <p class="muted" id="radioInfo"></p>
      <p class="muted">Space in this page acts as the radio button.</p>
    </section>
    <section class="panel"><h3>Radio messages</h3>
      <form id="askForm" class="toolbar">
        <input id="askText" placeholder="Type a question for the engineer" aria-label="Question for the engineer">
        <button class="btn" type="submit">Ask</button>
      </form>
      <div id="askStatus" role="status"></div><p class="muted small" id="engineerInfo"></p>
      <div id="radioMsgs"></div></section>
    <section class="panel"><h3>Fixes</h3>
      <form id="fixForm" class="toolbar">
        <input id="fixHeard" placeholder="heard (e.g. look like)" aria-label="What speech-to-text heard">
        <input id="fixMeant" placeholder="meant (e.g. Leclerc)" aria-label="What you actually said">
        <button class="btn" type="submit">Teach</button>
      </form>
      <div id="fixStatus" role="status"></div><div id="fixList"></div></section>
    <section class="panel"><h3>Buttons held now</h3><div id="radioPad" class="pad"></div>
      <h3 style="margin-top:12px">Recent presses</h3><div id="radioPresses"></div></section>
  </div>`;
}

const STATUS_TEXT = {
  connecting: 'Connecting to server…',
  loading: 'Loading speech model (~10s)…',
  transcribing: 'Transcribing…',
  off: 'Radio disabled (server started with --no-radio).',
};

export function update() {
  const open = radio.status === 'open';
  const badge = $('radioBadge');
  if (badge) badge.hidden = !open;
  renderCard();
  for (const fn of watchers) fn();
  if (!$('radio')) return;
  if (!$('fixList').childElementCount) renderFixes(); // tab just mounted

  $('radioDisc').classList.toggle('open', open);
  $('radioDisc').classList.toggle('busy', radio.status === 'transcribing');
  $('radioLabel').textContent = open ? 'RADIO OPEN' : radio.status === 'transcribing' ? 'SENDING' : 'RADIO';
  const toggle = radio.mode === 'toggle';
  const hint = radio.status === 'error' ? `<span class="bad">${esc(radio.error)}</span>`
    : radio.status === 'off' && radio.error ? esc(radio.error)
    : STATUS_TEXT[radio.status] ? esc(STATUS_TEXT[radio.status])
    : open ? `Talk now — ${toggle ? 'tap' : 'release'} <b>${esc(radio.trigger)}</b> to send.`
    : `${toggle ? 'Tap' : 'Hold'} <b>${esc(radio.trigger)}</b> (or Space) to talk.`;
  $('radioHint').innerHTML = streamUp ? hint : '<span class="warn">Stream disconnected — retrying…</span>';
  $('engineerInfo').innerHTML = engineer.error ? `<span class="warn">Engineer: ${esc(engineer.error)}</span>` : engineer.model ? `Engineer: ${esc(engineer.model)}` : '';
  $('radioInfo').textContent = radio.device ? `Mic: ${radio.device} · mode: ${radio.mode} · quick brief: ${radio.quick}` : '';

  const quickOn = quickAt != null && performance.now() - quickAt < QUICK_FLASH_MS;
  $('quickFlash').textContent = quickOn ? 'QUICK BRIEF REQUESTED' : '';
  $('quickFlash').classList.toggle('on', quickOn);

  $('radioMsgs').innerHTML = messages.length
    ? `<table><thead><tr><th>Said</th><th class="r">Audio</th><th class="r">STT</th><th class="r">Release→text</th></tr></thead><tbody>${messages.map((m) => `<tr>
        <td style="white-space:normal">${m.text ? marked(m) : `<span class="muted">(${esc(m.note)})</span>`}
          ${m.heard && m.heard !== m.text ? `<div class="muted small">heard “${esc(m.heard)}”</div>` : ''}
          ${m.heard && m.source !== 'typed' ? `<button class="btn link" data-teach="${esc(m.heard)}" aria-label="Teach a fix from this message">fix…</button>` : ''}
          ${m.clip ? `<button class="btn link" data-clip="${esc(m.clip)}" aria-label="Play the audio of this message">▶ clip</button>
            <a class="btn link" href="/api/clip?name=${encodeURIComponent(m.clip)}" download="${esc(m.clip)}" aria-label="Download the audio of this message">save</a>` : ''}
          ${replyHtml(replies[m.id], true)}</td>
        ${m.source === 'typed' ? '<td class="r muted" colspan="3">typed</td>'
          : `<td class="r muted">${m.audioSec.toFixed(1)}s</td><td class="r muted">${m.sttMs}ms</td><td class="r muted">${m.releaseToTextMs}ms</td>`}</tr>`).join('')}</tbody></table>`
    : '<p class="muted">Nothing yet — open the radio and say something.</p>';

  const trig = names.indexOf(radio.trigger), quick = names.indexOf(radio.quick);
  $('radioPad').innerHTML = names.map((n, i) => `<span class="key ${held(buttons, i) ? 'on' : ''} ${i === trig ? 'trigger' : ''} ${i === quick ? 'quick' : ''}">${esc(n)}</span>`).join('');
  $('radioPresses').innerHTML = presses.length
    ? `<table><tbody>${presses.map((p) => `<tr class="${p.b === trig ? 'warn' : p.b === quick ? 'purple' : ''}"><td>${esc(names[p.b])}</td><td class="r">${p.dur == null ? 'held…' : `${(p.dur / 1000).toFixed(2)}s`}</td></tr>`).join('')}</tbody></table>`
    : '<p class="muted">No presses yet.</p>';
  drawLevel();
}

function tickTimer() {
  const t = $('radioTimer');
  if (t) t.textContent = radio.status === 'open' && radio.openedAt ? `${(Date.now() / 1000 - radio.openedAt).toFixed(1)}s` : '';
  requestAnimationFrame(tickTimer);
}

$('radioCard')?.addEventListener('click', () => { cardMsg = null; update(); });
connect();
window.addEventListener('keydown', onKey);
// the tab is re-mounted on navigation, so listen at the document
document.addEventListener('submit', (e) => {
  if (e.target.id === 'fixForm') onTeach(e);
  if (e.target.id === 'askForm' || e.target.id === 'raceAskForm') onAsk(e);
});
document.addEventListener('click', (e) => { if (e.target instanceof Element && e.target.closest('#radio')) onTabClick(e); });
window.addEventListener('keyup', onKey);
requestAnimationFrame(tickTimer);
