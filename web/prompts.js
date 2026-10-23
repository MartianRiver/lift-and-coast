// Settings → Prompts: what each model is told, by version. Shipped versions are read-only; an edit
// is saved as a new version of your own, and which one each role uses is a separate choice.
import { esc } from './panels.js';

const $ = (id) => document.getElementById(id);
const FORMAT = {
  lead: 'The code reads the CALL, SAY, WHY and BOX lines of its reply (and A, B, C, ACTIVE for plans): keep asking for them.',
  second: 'The code reads AGREE or DISAGREE at the start of its reply: keep asking for it.',
  prep: 'The code reads the FUEL, START and CALL lines of its plan: keep asking for them.',
};

let data = null, error = null, role = 'engineer', picked = {}, editing = null, status = null;
const texts = {}; // "role/id" -> text, or an Error

export const markup = () => '<section id="prompts" aria-label="Prompts"><p class="muted">Loading…</p></section>';

export async function load() {
  try {
    data = await getJSON('/api/prompts');
    error = null;
  } catch (e) {
    error = e;
    console.error('[prompts] load failed', e);
  }
  render();
}

async function getJSON(url, body) {
  const r = await fetch(url, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const got = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error((got.error || `HTTP ${r.status}`).replace(/^bad request: (\w+: )?/, '')), { status: r.status });
  return got;
}

const shown = () => picked[role] || data[role].active;

async function fetchText(r, id) {
  const k = `${r}/${id}`;
  texts[k] = null; // asked for: a render meanwhile doesn't ask again
  try {
    texts[k] = (await getJSON(`/api/prompts/text?role=${encodeURIComponent(r)}&id=${encodeURIComponent(id)}`)).text;
  } catch (e) {
    texts[k] = e;
    console.error('[prompts] text failed', k, e);
  }
  render();
}

function label(v, now) {
  const bits = [v.id, v.custom ? v.why : 'shipped', v.id === now ? 'in use' : ''].filter(Boolean);
  return bits.join(' · ');
}

function about(v, d) {
  const use = v.id === d.active ? ' In use.' : '';
  if (!v.custom) return `Shipped with the app.${use}`;
  return `Yours, made from ${esc(v.from || '?')}${v.date ? ` on ${esc(v.date)}` : ''}: ${esc(v.why || '')}.${use}`;
}

function diff(lines) {
  return lines.map((l) => {
    const cls = /^(\+\+\+|---|@@)/.test(l) ? 'muted' : l[0] === '+' ? 'good' : l[0] === '-' ? 'bad' : '';
    return `<span class="${cls}">${esc(l)}</span>`;
  }).join('\n');
}

function newer(d) {
  if (!d.newer) return '';
  const now = d.versions.find((v) => v.id === d.active);
  const from = now?.custom ? `, made from ${esc(now.from)}` : '';
  return `<div class="prompt-new"><p><b>${esc(d.newer)} is out.</b> You’re using ${esc(d.active)}${from}. It stays in use until you pick another.</p>
    <details><summary class="small">What changed in ${esc(d.newer)}</summary><pre class="diff">${diff(d.changes)}</pre></details>
    <button class="btn" type="button" data-use="${esc(d.newer)}">Use ${esc(d.newer)}</button></div>`;
}

function body(d) {
  const id = shown(), k = `${role}/${id}`, got = texts[k];
  if (editing) {
    return `<label class="small muted" for="promptText">Your copy of ${esc(editing.from)}</label>
      <textarea id="promptText" class="prompt-text" spellcheck="false">${esc(editing.text)}</textarea>
      <div class="set-row"><label class="set-label" for="promptWhy">Why</label><div>
        <input id="promptWhy" maxlength="200" placeholder="one line: what you changed and why" value="${esc(editing.why)}" autocomplete="off">
        <p class="small muted">${FORMAT[role] || ''}</p></div></div>
      <div class="toolbar"><button class="btn" type="button" id="promptSave">Save as a new version</button>
        <button class="btn" type="button" id="promptCancel">Cancel</button></div>`;
  }
  if (got === undefined) fetchText(role, id);
  if (!got && got !== '') return '<p class="muted">Loading the prompt…</p>';
  if (got instanceof Error) return `<p class="bad">Couldn’t load ${esc(id)}: ${esc(got.message)}</p><button class="btn" type="button" id="promptRetry">Try again</button>`;
  return `<div class="toolbar"><button class="btn" type="button" data-use="${esc(id)}" ${id === d.active ? 'disabled' : ''}>${id === d.active ? 'In use' : 'Use this version'}</button>
      <button class="btn" type="button" id="promptEdit">Edit a copy</button></div>
    <textarea class="prompt-text" readonly aria-label="${esc(d.name)} prompt ${esc(id)}">${esc(got)}</textarea>`;
}

function render() {
  const el = $('prompts');
  if (!el) return;
  if (error && !data) {
    el.innerHTML = `<div class="empty"><h2>Couldn’t load the prompts</h2><p class="muted">${esc(error.message)}</p>
      <button class="btn" type="button" id="promptReload">Try again</button></div>`;
    return;
  }
  if (!data) return;
  const d = data[role], id = shown(), v = d.versions.find((x) => x.id === id) || d.versions[0];
  el.innerHTML = `<p class="muted">What each model is told before the race data. Your edits are kept as new versions next to the
    shipped ones, so nothing is lost. They’re written about River (he/him); your name and pronouns go in when they’re sent.</p>
    <div class="seg" role="radiogroup" aria-label="Whose prompt">${Object.entries(data).map(([r, x]) => `<label>
      <input type="radio" name="promptRole" value="${r}" ${r === role ? 'checked' : ''} ${editing ? 'disabled' : ''}><span>${esc(x.name)}</span></label>`).join('')}</div>
    ${newer(d)}
    <div class="set-row"><label class="set-label" for="promptVersion">Version</label><div>
      <select id="promptVersion" ${editing ? 'disabled' : ''}>${d.versions.map((x) => `<option value="${esc(x.id)}" ${x.id === id ? 'selected' : ''}>${esc(label(x, d.active))}</option>`).join('')}</select>
      <p class="small muted">${about(v, d)}</p>
      <p class="small ${status?.[0] || ''}" role="status">${esc(status?.[1] || '')}</p></div></div>
    ${body(d)}`;
}

function choice(r, id) {
  const out = Object.fromEntries(Object.entries(data).filter(([, x]) => x.active !== x.latest).map(([k, x]) => [k, x.active]));
  if (id === data[r].latest) delete out[r]; // no choice follows the newest shipped one, so a new release reaches it
  else out[r] = id;
  return out;
}

async function use(id) {
  try {
    await getJSON('/api/settings', { prompts: choice(role, id) });
    data = await getJSON('/api/prompts');
    picked[role] = id;
    status = ['good', `${id} in use from the next ${role === 'engineer' ? 'answer' : role === 'prep' ? 'race prep' : 'team run'}.`];
  } catch (e) {
    status = ['bad', `Couldn’t switch: ${e.message}`];
    (e.status === 400 ? console.warn : console.error)('[prompts] use failed', id, e.message);
  }
  render();
}

async function save() {
  editing.text = $('promptText').value;
  editing.why = $('promptWhy').value;
  try {
    const got = await getJSON('/api/prompts', { role, text: editing.text, why: editing.why, from: editing.from });
    data = got.prompts;
    picked[role] = got.saved;
    editing = null;
    status = ['good', `Saved as ${got.saved}. Not in use until you pick it.`];
  } catch (e) {
    status = ['bad', `Couldn’t save: ${e.message}`];
    (e.status === 400 ? console.warn : console.error)('[prompts] save failed', e.message);
  }
  render();
}

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!(t instanceof Element) || !t.closest('#prompts')) return;
  if (t.name === 'promptRole') role = t.value;
  else if (t.id === 'promptVersion') picked[role] = t.value;
  else return; // the edit box and its why: re-rendering on blur would swallow the click on Save
  status = null;
  render();
});
document.addEventListener('input', (e) => {
  if (!editing) return;
  if (e.target.id === 'promptText') editing.text = e.target.value;
  if (e.target.id === 'promptWhy') editing.why = e.target.value;
});
document.addEventListener('click', (e) => {
  const t = e.target;
  if (!(t instanceof Element) || !t.closest('#prompts')) return;
  if (t.dataset.use) use(t.dataset.use);
  if (t.id === 'promptEdit') { editing = { from: shown(), text: texts[`${role}/${shown()}`], why: '' }; status = null; render(); }
  if (t.id === 'promptCancel') { editing = null; render(); }
  if (t.id === 'promptSave') save();
  if (t.id === 'promptRetry') { delete texts[`${role}/${shown()}`]; render(); }
  if (t.id === 'promptReload') load();
});
