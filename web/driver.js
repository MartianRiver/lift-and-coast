// Who's driving: asked on first run (the game's name for you is the default), changed from the header.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

let current = null;
let touched = false;
let poll = null;

export async function start() {
  try {
    current = await (await fetch('/api/driver')).json();
  } catch {
    return; // the server's down: app.js shows that already
  }
  label();
  $('driverBtn').addEventListener('click', open);
  if (!current.name) open();
}

function label() {
  $('driverBtn').textContent = current.name ? `${current.name} (${current.pronouns})` : 'Who\'s driving?';
}

function open() {
  const d = $('driverDialog');
  touched = false;
  d.innerHTML = `<form method="dialog" id="driverForm">
    <h2 id="driverTitle">Who's driving?</h2>
    <p class="muted">The name your engineer and strategy team use for you on the radio.</p>
    <label>Name <input id="driverName" required maxlength="40" autocomplete="off" value="${esc(current.name || current.fromGame || '')}"></label>
    <p class="muted small" id="driverHint">${hint()}</p>
    <fieldset><legend>Pronouns</legend>
      ${current.choices.map((p) => `<label class="choice"><input type="radio" name="pronouns" value="${esc(p)}" ${p === current.pronouns ? 'checked' : ''}> ${esc(p)}</label>`).join('')}
    </fieldset>
    <p class="bad small" id="driverError" role="alert"></p>
    <div class="toolbar"><button class="btn primary" value="save">Save</button>
      ${current.name ? '<button class="btn" value="cancel" formnovalidate>Cancel</button>' : ''}</div>
  </form>`;
  $('driverName').addEventListener('input', () => { touched = true; });
  $('driverForm').addEventListener('submit', save);
  d.addEventListener('cancel', (e) => { if (!current.name) e.preventDefault(); }); // first run: no way round it
  d.showModal();
  clearInterval(poll);
  poll = setInterval(refresh, 3000); // the game may send your name while this is open
}

function hint() {
  if (current.fromGame) return `The game has you as ${esc(current.fromGame)}.`;
  return 'Start a session in the game and your name there fills in here.';
}

async function refresh() {
  if (!$('driverDialog').open) return clearInterval(poll);
  try {
    const got = await (await fetch('/api/driver')).json();
    if (got.fromGame && got.fromGame !== current.fromGame) {
      current.fromGame = got.fromGame;
      $('driverHint').innerHTML = hint();
      if (!touched && !current.name) $('driverName').value = got.fromGame;
    }
  } catch { /* try again next tick */ }
}

async function save(e) {
  if (e.submitter?.value === 'cancel') return;
  e.preventDefault();
  const pronouns = $('driverForm').querySelector('input[name=pronouns]:checked')?.value;
  try {
    const r = await fetch('/api/driver', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: $('driverName').value, pronouns }),
    });
    const got = await r.json();
    if (!r.ok) throw new Error(got.error || r.status);
    current = { ...current, ...got };
    label();
    $('driverDialog').close();
  } catch (err) {
    $('driverError').textContent = `Couldn't save: ${err.message}`;
  }
}
