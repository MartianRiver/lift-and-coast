// Race tab: the few things worth a glance mid-race, big enough to read from the corner of an eye,
// plus the radio feed. Data comes from /api/race (same maths as the engineer's brief).

import { esc, lapTime } from './panels.js';
import * as Radio from './radio.js';

const $ = (id) => document.getElementById(id);
const secs = (v, d = 1) => (v == null ? '–' : Number(v).toFixed(d));
const signed = (v, d = 1) => (v == null ? '–' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`);

export function markup() {
  return `<div id="race" class="race">
    <div id="rcStale" class="rc-stale" role="status" hidden></div>
    <section id="rcHero" class="rc-hero" aria-label="Position and lap"></section>
    <div class="rc-main">
      <div id="rcRivals" class="rc-pair"></div>
      <div class="rc-pair"><section class="panel" id="rcTyres" aria-label="Tyres"></section>
        <section class="panel" id="rcCar" aria-label="Fuel, battery, warnings"></section></div>
      <section class="panel" id="rcPlan" aria-label="Strategy plan" hidden></section>
      <section class="panel" id="rcLoss" aria-label="Where the time goes"></section>
      <section class="panel" id="rcLog" aria-label="Race log"></section>
    </div>
    <aside class="panel rc-feed" aria-label="Team radio">
      <h3>Team radio <span id="rcRadioState"></span></h3>
      <div id="rcFeed" aria-live="polite"></div>
      <form id="raceAskForm" class="toolbar rc-ask" data-status="raceAskStatus">
        <input placeholder="Type a question for the engineer" aria-label="Question for the engineer">
        <button class="btn" type="submit">Ask</button>
      </form><div id="raceAskStatus" role="status"></div>
    </aside>
  </div>`;
}

export function update(g, err) {
  if (!$('race')) return;
  if (err && !g) {
    $('rcHero').innerHTML = `<div class="bad">Couldn't load race data: ${esc(err.message)}</div>`;
    return;
  }
  if (!g) {
    $('rcHero').innerHTML = '<div class="muted">Loading…</div>';
    return;
  }
  if (g.waiting) {
    $('rcHero').innerHTML = '<div class="muted">Waiting for session data — go on track.</div>';
    ['rcRivals', 'rcTyres', 'rcCar', 'rcLoss', 'rcLog'].forEach((id) => { $(id).innerHTML = ''; });
    return;
  }
  const quiet = g.silentSecs > 15;
  $('race').classList.toggle('stale', quiet);
  $('rcStale').hidden = !quiet;
  if (quiet) $('rcStale').textContent = `No data from the game for ${duration(g.silentSecs)}: paused, saved or switched off. This is lap ${g.session.lap} as it was.`;
  $('rcHero').innerHTML = hero(g);
  $('rcRivals').innerHTML = g.session.race ? rival('Ahead', g.ahead, true) + rival('Behind', g.behind, false) : board(g.board);
  $('rcTyres').innerHTML = tyres(g.me);
  $('rcCar').innerHTML = car(g.me);
  $('rcPlan').innerHTML = plan(g.team);
  $('rcPlan').hidden = !g.team || !g.session.race;
  $('rcLoss').innerHTML = loss(g.timeLoss);
  $('rcLoss').hidden = !g.timeLoss?.length;
  $('rcLog').innerHTML = raceLog(g.log);
}

// ------------------------------------------------------------------ sections

function hero(g) {
  const s = g.session, me = g.me;
  const lap = s.race ? `${me.lap ?? s.lap}<small>/${s.totalLaps}</small>` : `${s.lap}`;
  const flags = [];
  if (s.sc) flags.push(`<span class="pill sc">${esc(s.sc.toUpperCase())}</span>`);
  if (me.pit) flags.push(`<span class="pill">${esc(me.pit.toUpperCase())}</span>`);
  if (me.invalid) flags.push('<span class="pill bad">LAP INVALID</span>');
  return `<div class="rc-pos"><span class="label">POS</span><b>P${me.position ?? '–'}</b><small>/${s.cars}</small></div>
    <div class="rc-stat"><span class="label">LAP</span><b>${lap}</b></div>
    <div class="rc-stat"><span class="label">LAST</span><b class="${me.lastValid === false ? 'bad' : ''}">${lapTime(me.lastLapMs)}</b></div>
    <div class="rc-stat"><span class="label">BEST</span><b class="purple">${lapTime(me.bestLapMs)}</b></div>
    <div class="rc-flags">${flags.join('')}</div>
    <div class="rc-where muted">${esc(s.track)} · ${esc(s.type)} · ${esc(s.weather)} ${s.trackTemp ?? ''}°</div>`;
}

function rival(title, r, ahead) {
  if (!r) return `<section class="panel rc-rival"><h3>${title}</h3><div class="rc-lead">${ahead ? 'Leading' : 'Nobody behind'}</div></section>`;
  // ahead: gap shrinking is good news; behind: it's a threat
  const tone = r.closing == null ? '' : r.closing === ahead ? 'good' : 'warn';
  const drs = r.gap != null && r.gap < 1 ? '<span class="pill drs">DRS</span>' : '';
  return `<section class="panel rc-rival" style="--team:${esc(r.colour || 'var(--line)')}">
    <h3>${title} · P${r.position}</h3>
    <div class="rc-name"><b>${esc(r.name)}</b> <span class="muted">${esc(r.team || '')}</span></div>
    <div class="rc-gap ${tone}">${r.gap == null ? '–' : `${ahead ? '−' : '+'}${secs(r.gap)}`}<small>s</small> ${drs}</div>
    ${r.lastLap ? `<div class="${tone}">${esc(r.lastLap)} <span class="muted">last lap</span></div>` : ''}
    ${r.trend ? `<div class="muted">${esc(r.trend)} over ${r.trendLaps} laps</div>` : ''}
    ${r.atFlag ? `<div>${esc(r.atFlag)}</div>` : ''}
    <div class="muted small">${tyreChip(r.tyre, r.tyreAge)} ${r.wearMax != null ? `worst ${Math.round(r.wearMax)}%` : ''}
      ${r.lastLapMs ? ` · last ${lapTime(r.lastLapMs)}` : ''}${r.pit ? ` · <span class="warn">${esc(r.pit)}</span>` : ''}</div>
  </section>`;
}

function board(rows) {
  if (!rows?.length) return '<section class="panel rc-wide"><h3>Times</h3><p class="muted">No laps set yet.</p></section>';
  return `<section class="panel rc-wide"><h3>Best laps</h3><table><tbody>${rows.map((r) => `
    <tr class="${r.me ? 'player' : ''}"><td>P${r.position}</td>
      <td><span class="team" style="background:${esc(r.colour || 'var(--line)')}"></span>${esc(r.name)}</td>
      <td class="r big-ish">${lapTime(r.bestMs)}</td>
      <td class="r">${r.gapToMe == null ? '' : `<span class="${r.gapToMe < 0 ? 'warn' : 'good'}">${signed(r.gapToMe, 3)}</span>`}</td>
      <td>${tyreChip(r.tyre, r.tyreAge)}</td></tr>`).join('')}</tbody></table></section>`;
}

function tyres(me) {
  const t = me.tyre;
  if (!t) return '<h3>Tyres</h3><p class="muted">No tyre data yet.</p>';
  const head = `<h3>Tyres · ${tyreChip(t.name, null)} ${esc(t.name || '')}, ${t.age} lap${t.age === 1 ? '' : 's'}</h3>`;
  if (!t.wear) return head + (me.wearMax != null ? `<div class="rc-gap">${Math.round(me.wearMax)}<small>% worst</small></div>` : '');
  const worst = Math.max(...t.wear);
  const cells = t.corners.map((c, i) => {
    const w = t.wear[i];
    const tone = w >= 60 ? 'bad' : w >= 40 ? 'warn' : '';
    return `<div class="rc-corner ${w === worst ? 'worst' : ''}"><span class="label">${c}</span>
      <b class="${tone}">${Math.round(w)}%</b>${t.rate ? `<span class="muted small">+${t.rate[i].toFixed(1)}/lap</span>` : ''}
      <div class="bar"><i style="width:${Math.min(100, w)}%;background:var(--${tone || 'good'})"></i></div></div>`;
  }).join('');
  return head + `<div class="rc-corners">${cells}</div>` + (t.worn ? `<div class="muted small">${esc(t.worn.corner)} at ${t.worn.pct}% in ~${t.worn.laps} lap${t.worn.laps === 1 ? '' : 's'}</div>` : '');
}

function car(me) {
  const rows = [];
  if (me.fuelDelta != null) rows.push(['Fuel', `<b class="${me.fuelDelta < 0 ? 'bad' : ''}">${signed(me.fuelDelta)} laps</b>`]);
  if (me.ersPct != null) {
    rows.push(['Battery', `<b>${me.ersPct}%</b> <span class="muted">${esc(me.ersMode || '')}</span>
      <div class="bar"><i style="width:${me.ersPct}%;background:var(--wet)"></i></div>`]);
  }
  const cc = me.cornerCutting ?? 0, at = me.penaltyAt ?? 3;
  const pips = Array.from({ length: at }, (_, i) => `<i class="${i < cc ? 'on' : ''} ${i === at - 1 ? 'last' : ''}"></i>`).join('');
  rows.push(['Limits', `<span class="pips ${cc === at - 1 ? 'warn' : ''}">${pips}</span> <b class="${cc >= at - 1 ? 'warn' : ''}">${cc}/${at}</b>${cc === at - 1 ? ' <span class="warn">next is a penalty</span>' : ''}`]);
  const owed = [me.penaltiesSec ? `+${me.penaltiesSec}s` : '', me.driveThroughs ? `${me.driveThroughs} drive-through` : '',
    me.stopGos ? `${me.stopGos} stop-go` : ''].filter(Boolean);
  if (owed.length) rows.push(['Penalty', `<b class="bad">${owed.join(', ')}</b>`]);
  if (me.damage?.length) rows.push(['Damage', `<span class="warn">${me.damage.map(esc).join(', ')}</span>`]);
  if (me.powerUnit) rows.push(['PU', `<span class="muted">engine ${me.powerUnit.engine}% · gearbox ${me.powerUnit.gearbox}% (season wear)</span>`]);
  if (me.stops != null) rows.push(['Stops', `<b>${me.stops}</b>`]);
  return `<h3>Car</h3><dl class="rc-kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
}

function loss(rows) {
  if (!rows?.length) return '';
  const span = (z, verb, cls) => {
    if (!z) return '';
    const bits = [];
    if (Math.abs(z.apex) >= 2) bits.push(`apex ${signed(z.apex, 0)} km/h`);
    if (Math.abs(z.top) >= 2) bits.push(`top ${signed(z.top, 0)} km/h`);
    if (z.later != null && Math.abs(z.later) >= 5) bits.push(`braking ${Math.abs(z.later).toFixed(0)} m ${z.later > 0 ? 'later' : 'earlier'}`);
    return `<div class="rc-zone"><b class="${cls}">${verb} ${z.secs.toFixed(2)}s</b> at ${z.from}–${z.to} m
      ${bits.length ? `<span class="muted">· ${esc(bits.join(', '))}</span>` : ''}</div>`;
  };
  return '<h3>Where the time goes</h3>' + rows.map((r) => `<div class="rc-loss">
    <div>vs <b>${esc(r.name)}</b> <span class="muted">(${esc(r.label)}) · net</span>
      <b class="${r.net > 0.02 ? 'warn' : r.net < -0.02 ? 'good' : ''}">${r.net > 0 ? 'losing' : 'gaining'} ${Math.abs(r.net).toFixed(2)}s/lap</b></div>
    ${span(r.lose, 'Losing', 'warn')}${span(r.gain, 'Gaining', 'good')}</div>`).join('');
}

function plan(t) {
  if (!t) return '';
  const head = t.active ? `Plan ${esc(t.active)}${t.box ? ` · box end of L${t.box}` : ''}` : 'No plan yet';
  return `<h3>Pit wall${t.running ? ' <span class="muted">· thinking…</span>' : ''}</h3>
    <div class="rc-plan"><b>${head}</b>${t.plan ? ` <span class="muted">${esc(t.plan)}</span>` : ''}</div>
    ${t.call ? `<div class="muted">L${t.call.lap}: ${esc(t.call.text)}</div>` : ''}`;
}

function raceLog(rows) {
  if (!rows?.length) return '<h3>Race log</h3><p class="muted">Nothing yet.</p>';
  return `<h3>Race log</h3><ul class="rc-log">${rows.map((e) => `<li class="${e.mine ? 'mine' : ''}">
    <span class="lap">L${e.lap}</span>${esc(e.text)}</li>`).join('')}</ul>`;
}

function tyreChip(name, age) {
  if (!name) return '';
  return `<span class="tyre ${esc(name.split(' ')[0])}" title="${esc(name)}">${esc(name[0])}</span>${age ?? ''}`;
}

// ------------------------------------------------------------------ radio feed

export function updateFeed() {
  const el = $('rcFeed');
  if (!el) return;
  const { messages, replies, calls, radio, streamUp } = Radio.feed();
  $('rcRadioState').innerHTML = !streamUp ? '<span class="warn">· reconnecting…</span>'
    : radio.status === 'open' ? '<span class="pill live">● LIVE</span>'
    : radio.status === 'transcribing' ? '<span class="muted">· sending…</span>' : '';
  const items = [...messages.map((m) => ({ at: m.at, m })), ...calls.map((c) => ({ at: c.at, c }))]
    .sort((a, b) => b.at - a.at).slice(0, 8);
  if (!items.length) {
    el.innerHTML = '<p class="muted">Nothing yet. Hold the radio button (or Space) and ask, or type below.</p>';
    return;
  }
  el.innerHTML = items.map((it, i) => {
    const ago = it.at ? `<span class="muted small">${clock(it.at)}</span>` : '';
    if (it.c) {
      return `<div class="rc-msg call ${i === 0 ? 'latest' : ''}"><div class="rc-said muted">Engineer · L${it.c.lap} ${ago}</div>`
        + `<div class="rc-answer">${esc(it.c.text)}</div></div>`;
    }
    const m = it.m, r = replies[m.id];
    const said = m.text ? `“${esc(m.text)}”` : `<span class="muted">(${esc(m.note || 'nothing heard')})</span>`;
    let answer = '';
    if (r?.status === 'error') answer = `<div class="bad">${esc(r.error)}</div>`;
    else if (r?.status === 'thinking') answer = '<div class="muted">…</div>';
    else if (r) answer = `<div class="rc-answer">${esc(r.text)}${r.status === 'streaming' ? '▍' : ''}</div>`;
    return `<div class="rc-msg ${i === 0 ? 'latest' : ''}"><div class="rc-said">${said} ${ago}</div>${answer}</div>`;
  }).join('');
}

function duration(s) {
  return s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
}

function clock(t) {
  const d = new Date(t * 1000);
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}
