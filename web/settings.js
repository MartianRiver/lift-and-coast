// Settings tab: the models, the voice, what's said unprompted and the radio buttons, from
// /api/settings. Each change is saved and used straight away, unless its row says otherwise.
import { esc } from './panels.js';
import * as Radio from './radio.js';

const $ = (id) => document.getElementById(id);
const LEVELS = {
  chatty: ['Everything', 'Normal, plus every pass, contact, car out and car into the pits.'],
  normal: ['Normal', 'Gaps, lap times, tyres, fuel, damage, flags and the team’s calls.'],
  quiet: ['Urgent only', 'Safety car, flags, rain, penalties and the team’s urgent calls.'],
  off: ['Nothing', 'Only answers when you ask.'],
};
const GROUPS = { gaps: 'Gaps', tyres: 'Tyres', damage: 'Damage', flags: 'Flags, SC, weather', fuel: 'Fuel', team: 'Team calls' };
const ACCENTS = { bm: 'British male', bf: 'British female', am: 'American male', af: 'American female' };
const ROLES = { engineerModel: 'engineer', engineerFallback: 'engineer', lead: 'lead', second: 'second' };

let data = null, error = null, list = null, listError = null, listAsked = false;
const status = {}; // key -> [class, text] under its row

export const markup = () => '<section id="settings" class="settings" aria-label="Settings"><p class="muted">Loading…</p></section>';

export async function load() {
  try {
    data = await getJSON('/api/settings');
    error = null;
  } catch (e) {
    error = e;
    console.error('[settings] load failed', e);
  }
  render();
  if (!listAsked) loadList();
}

async function loadList() {
  listAsked = true;
  try {
    list = await getJSON('/api/models');
    listError = null;
  } catch (e) {
    listError = e;
    console.error('[settings] model list failed', e);
  }
  render();
}

async function getJSON(url, body) {
  const r = await fetch(url, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const got = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error((got.error || `HTTP ${r.status}`).replace(/^bad request: (\w+: )?/, '')), { status: r.status });
  return got;
}

const price = (v) => (v == null ? '' : v < 0.01 ? '<$0.01 a race' : `≈$${v.toFixed(2)} a race`);

function datalist(role) {
  if (!list) return '';
  const pinned = Object.entries(ROLES).filter(([, r]) => r === role).map(([k]) => data.settings[k].default);
  const rows = [...list.models.filter((m) => pinned.includes(m.id)), ...list.models.filter((m) => !pinned.includes(m.id))];
  return `<datalist id="models-${role}">${rows.map((m) => `<option value="${esc(m.id)}" label="${esc([pinned.includes(m.id) ? 'default' : '', m.name, price(m.race[role])].filter(Boolean).join(' · '))}"></option>`).join('')}</datalist>`;
}

function about(id, role) {
  if (!id) return '';
  if (listError) return `<span class="warn">Couldn’t load the model list (${esc(listError.message)}). You can still type an id.</span>`;
  if (!list) return 'Loading the model list…';
  const m = list.models.find((x) => x.id === id);
  if (!m) return `<span class="warn">Not in ${list.local ? 'that server’s' : 'OpenRouter’s'} list: check the id.</span>`;
  const bits = [esc(m.name), price(m.race[role]), m.context ? `${Math.round(m.context / 1000)}k context` : ''].filter(Boolean).join(' · ');
  return bits + (m.expires ? ` <span class="warn">OpenRouter retires it on ${esc(m.expires)}.</span>` : '');
}

function lockLine(s) {
  if (!s.locked) return '';
  const how = s.locked.startsWith('--') ? 'Start the server without it to set it here.' : 'Remove it there to set it here.';
  return `<p class="small warn">Set by ${esc(s.locked)}. ${how}</p>`;
}

function row(key, label, control, help = '') {
  const s = data.settings[key];
  const [cls, text] = status[key] || [];
  const head = control.includes(`id="set-${key}"`) ? `<label class="set-label" for="set-${key}">${label}</label>` : `<span class="set-label">${label}</span>`;
  return `<div class="set-row">${head}<div>${control}
    ${help ? `<p class="small muted">${help}</p>` : ''}${lockLine(s)}<p class="small ${cls || ''}" role="status">${esc(text || '')}</p></div></div>`;
}

function model(key, optional = false) {
  const s = data.settings[key], role = ROLES[key];
  return `<input id="set-${key}" data-key="${key}" list="models-${role}" value="${esc(s.value || '')}" ${optional ? 'placeholder="none"' : 'required'}
    spellcheck="false" autocomplete="off" ${s.locked ? 'disabled' : ''}>${datalist(role)}<p class="small muted">${about(s.value, role)}</p>`;
}

function choices(key, options, label) {
  const s = data.settings[key];
  return `<div class="seg" role="radiogroup" aria-label="${label}">${Object.entries(options).map(([v, text]) => `<label>
    <input type="radio" name="set-${key}" data-key="${key}" value="${v}" ${s.value === v ? 'checked' : ''} ${s.locked ? 'disabled' : ''}><span>${text}</span></label>`).join('')}</div>`;
}

function select(key, options, label) {
  const s = data.settings[key];
  const opts = options.includes(s.value) ? options : [s.value, ...options];
  return `<select id="set-${key}" data-key="${key}" aria-label="${label}" ${s.locked ? 'disabled' : ''}>${opts.map((v) => `<option value="${esc(v)}" ${v === s.value ? 'selected' : ''}>${esc(voiceName(key, v))}</option>`).join('')}</select>`;
}

function voiceName(key, v) {
  if (key !== 'voice') return v;
  const [engine, voice] = v.split(':');
  return voice ? `${voice} (${ACCENTS[voice.slice(0, 2)] || engine})` : `${engine} (its one voice)`;
}

const offLine = (why) => (why ? `<p class="small warn">Not running: ${esc(why)}. What you set here is used on the next start that has it.</p>` : '');

function engineer() {
  const d = data, calls = d.settings.calls, topics = d.settings.topics;
  const live = d.live.calls && d.live.calls !== calls.value
    ? `<p class="small warn">On the radio you asked for “${esc(LEVELS[d.live.calls][0])}”, which holds until the server restarts or you change it here.</p>` : '';
  return `<section class="set-sec"><h3>Engineer</h3>${offLine(d.off.engineer)}
    ${row('engineerModel', 'Model', model('engineerModel'))}
    ${row('engineerFallback', 'Fallback', model('engineerFallback', true), 'Asked instead when the model hasn’t started answering in 5 s. Empty for none.')}
    ${row('voice', 'Voice', `${offLine(d.off.voice)}<div class="toolbar">${select('voice', d.voices, 'Voice')}
      <label class="check"><input type="checkbox" id="set-radioFx" data-key="radioFx" ${d.settings.radioFx.value ? 'checked' : ''} ${d.settings.radioFx.locked ? 'disabled' : ''}> Radio filter</label>
      <button class="btn" type="button" id="setHear" ${d.off.voice ? 'disabled' : ''}>▶ Hear it</button></div>${lockLine(d.settings.radioFx)}`)}
    ${row('calls', 'Says unprompted', `${offLine(d.off.calls)}${choices('calls', Object.fromEntries(Object.entries(LEVELS).map(([k, v]) => [k, v[0]])), 'How much it says unprompted')}
      <p class="small muted">${esc(LEVELS[calls.value][1])}</p>${live}
      <fieldset class="set-topics"><legend class="small muted">Topics</legend>${Object.entries(GROUPS).map(([g, text]) => `<label class="check">
        <input type="checkbox" data-key="topics" data-group="${g}" ${topics.value[g] ? 'checked' : ''}> ${text}</label>`).join('')}</fieldset>`)}
  </section>`;
}

function team() {
  const d = data;
  return `<section class="set-sec"><h3>Strategy team</h3>${offLine(d.off.team)}
    ${row('lead', 'Lead', model('lead'))}
    ${row('second', 'Second opinion', model('second', true), 'Checks each of the lead’s calls. Empty for none.')}
    ${row('budget', 'Budget', `<input id="set-budget" data-key="budget" type="number" min="0.1" max="50" step="0.5" value="${d.settings.budget.value}" ${d.settings.budget.locked ? 'disabled' : ''}> $ a session`,
      'Past it, the team only runs for urgent reasons and your questions.')}
  </section>`;
}

function radio() {
  const d = data, s = d.settings;
  return `<section class="set-sec"><h3>Radio</h3>${offLine(d.off.radio)}
    ${row('radioButton', 'Radio button', `<div class="toolbar">${select('radioButton', d.buttons, 'Radio button')}
      ${choices('radioMode', { hold: 'Hold', toggle: 'Toggle' }, 'Hold to talk or tap to toggle')}</div>${lockLine(s.radioMode)}
      <p class="small muted">Press it now to test: <span id="setPress">${pressed()}</span></p>`)}
    ${row('quickButton', 'Quick brief', select('quickButton', d.buttons, 'Quick brief button'))}
    ${row('audioOut', 'Output', `<input id="set-audioOut" data-key="audioOut" value="${esc(s.audioOut.value || '')}" placeholder="system output" autocomplete="off" ${s.audioOut.locked ? 'disabled' : ''}>`,
      'A sound device by name. Applies after a restart.')}
  </section>`;
}

function pressed() {
  const { names, buttons } = Radio.pad();
  const held = names.filter((_, i) => Math.floor(buttons / 2 ** i) % 2 === 1);
  return held.length ? `<b>${esc(held.join(', '))}</b>` : 'nothing held';
}

function render() {
  const el = $('settings');
  if (!el) return;
  if (error && !data) {
    el.innerHTML = `<div class="empty"><h2>Couldn’t load the settings</h2><p class="muted">${esc(error.message)}</p>
      <button class="btn" type="button" id="setRetry">Try again</button></div>`;
    return;
  }
  if (!data) return;
  el.innerHTML = `${engineer()}${team()}${radio()}
    <p class="small muted">Your name and pronouns are under the button with your name, at the top.</p>`;
}

function value(t) {
  if (t.dataset.key === 'topics') {
    return Object.fromEntries([...document.querySelectorAll('#settings [data-group]')].map((c) => [c.dataset.group, c.checked]));
  }
  if (t.type === 'checkbox') return t.checked;
  return t.value;
}

const ROW = { radioFx: 'voice', radioMode: 'radioButton' }; // shown under the row they sit in

async function save(e) {
  const t = e.target, key = t.dataset?.key;
  if (!key) return;
  const at = ROW[key] || key;
  try {
    const got = await getJSON('/api/settings', { [key]: value(t) });
    const later = got.later[key] || (key === 'radioFx' && got.later.voice);
    const section = { engineerModel: 'engineer', engineerFallback: 'engineer', voice: 'voice', radioFx: 'voice', calls: 'calls', topics: 'calls',
      lead: 'team', second: 'team', budget: 'team', radioButton: 'radio', radioMode: 'radio', quickButton: 'radio' }[key];
    data = got;
    status[at] = ['good', later ? `Saved: applies ${later}.` : got.off[section] ? 'Saved for the next start.' : 'Saved, in use now.'];
  } catch (err) {
    status[at] = ['bad', `Couldn’t save: ${err.message}`];
    (err.status === 400 ? console.warn : console.error)('[settings] save failed', key, err.message);
  }
  render();
}

async function hear() {
  status.voice = ['muted', 'Playing…'];
  try {
    await getJSON('/api/settings/hear', {});
  } catch (err) {
    status.voice = ['bad', `Couldn’t play it: ${err.message}`];
  }
  render();
}

document.addEventListener('change', (e) => { if (e.target instanceof Element && e.target.closest('#settings')) save(e); });
document.addEventListener('click', (e) => {
  if (!(e.target instanceof Element)) return;
  if (e.target.id === 'setHear') hear();
  if (e.target.id === 'setRetry') load();
});
Radio.watch(() => { const p = $('setPress'); if (p) p.innerHTML = pressed(); });
