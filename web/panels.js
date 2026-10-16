// Render functions: each takes data and returns an HTML string.

export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function lapTime(ms) {
  if (!ms) return '<span class="muted">–</span>';
  const m = Math.floor(ms / 60000);
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, '0');
  return m ? `${m}:${s}` : (ms / 1000).toFixed(3);
}
const gap = (ms) => (ms ? `+${(ms / 1000).toFixed(3)}` : '<span class="muted">–</span>');
const n = (v, d = 1) => (v == null ? '–' : Number(v).toFixed(d));
const pct = (v) => (v == null ? '–' : `${Math.round(v)}%`);
const MJ = (j) => (j == null ? '–' : (j / 1e6).toFixed(2));
const sector = (min, ms) => min * 60000 + ms;

// wheel arrays are RL, RR, FL, FR
const CORNERS = [['FL', 2], ['FR', 3], ['RL', 0], ['RR', 1]];

function tyreBadge(visual, age) {
  if (!visual) return '<span class="muted">–</span>';
  return `<span class="tyre ${esc(visual.split(' ')[0])}" title="${esc(visual)}">${esc(visual[0])}</span>${age ?? ''}`;
}

function sev(v, warn, bad) {
  return v >= bad ? 'bad' : v >= warn ? 'warn' : '';
}

function fmtValue(v) {
  if (v == null) return '<span class="muted">null</span>';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x !== 'object' || x == null)) return `[${v.map(fmtValue).join(', ')}]`;
    return `<details><summary>${v.length} items</summary><pre class="json">${esc(JSON.stringify(v, null, 1))}</pre></details>`;
  }
  if (typeof v === 'object') return `<pre class="json">${esc(JSON.stringify(v, null, 1))}</pre>`;
  return esc(v);
}

export function kv(obj, skip = []) {
  if (!obj) return '<p class="muted">No data yet.</p>';
  return `<dl class="kv">${Object.entries(obj)
    .filter(([k]) => !skip.includes(k))
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${fmtValue(v)}</dd>`)
    .join('')}</dl>`;
}

const panel = (title, body, cls = '') => `<section class="panel ${cls}"><h3>${esc(title)}</h3>${body}</section>`;

// ---------------------------------------------------------------- timing

export function timing(d) {
  const best = Math.min(...d.cars.map((c) => c.bestLapMs || Infinity));
  const rows = d.cars.map((c) => {
    const flags = [c.pit, c.driverStatus !== 'On track' && c.driverStatus !== 'Flying lap' ? c.driverStatus : '', c.result !== 'Active' ? c.result : '']
      .filter(Boolean).join(' · ');
    const pens = [c.penaltiesSec ? `+${c.penaltiesSec}s` : '', c.unservedDT ? `${c.unservedDT}DT` : '', c.unservedSG ? `${c.unservedSG}SG` : '', c.warnings ? `${c.warnings}W` : '']
      .filter(Boolean).join(' ');
    return `<tr class="click ${c.isPlayer ? 'player' : ''}" data-car="${c.idx}" tabindex="0" aria-label="Open ${esc(c.name)}">
      <td class="r">${c.position ?? '–'}</td>
      <td><span class="team" style="background:${esc(c.colour || '')}"></span>${c.number ?? ''}</td>
      <td>${esc(c.name)}${c.ai === false ? ' <span class="muted">(human)</span>' : ''}</td>
      <td class="muted">${esc(c.team)}</td>
      <td class="r">${c.lap ?? '–'}</td>
      <td class="r">${c.position === 1 ? '<span class="muted">Leader</span>' : gap(c.gapLeaderMs)}</td>
      <td class="r">${c.position === 1 ? '' : gap(c.gapAheadMs)}</td>
      <td class="r">${lapTime(c.lastLapMs)}</td>
      <td class="r ${c.bestLapMs && c.bestLapMs === best ? 'purple' : ''}">${lapTime(c.bestLapMs)}</td>
      <td class="r ${c.invalid ? 'bad' : ''}">${lapTime(c.currentLapMs)}</td>
      <td class="r">${c.sector ?? ''}</td>
      <td>${tyreBadge(c.tyre, c.tyreAge)} <span class="muted">${esc(c.compound || '')}</span></td>
      <td class="r ${sev(c.wearMax, 40, 65)}">${pct(c.wearMax)}</td>
      <td class="r">${c.pitStops ?? ''}</td>
      <td class="r ${c.wingDamage ? 'warn' : ''}">${c.wingDamage ? pct(c.wingDamage) : ''}</td>
      <td class="r">${n(c.fuelLaps, 2)}</td>
      <td class="r">${MJ(c.ersJ)}</td>
      <td class="muted">${esc(c.ersMode || '')}</td>
      <td class="r">${c.speed ?? ''}</td>
      <td>${c.drs ? '<span class="good">DRS</span>' : ''}${c.overtakeActive ? ' <span class="good">OT</span>' : ''}${c.aeroStraight ? ' <span class="muted">X</span>' : ''}</td>
      <td class="warn">${esc(flags)}</td>
      <td class="bad">${esc(pens)}</td>
    </tr>`;
  });
  return panel('Timing tower', `<div class="scroll"><table>
    <thead><tr><th class="r">P</th><th>#</th><th>Driver</th><th>Team</th><th class="r">Lap</th><th class="r">Gap</th><th class="r">Int</th>
    <th class="r">Last</th><th class="r">Best</th><th class="r">Current</th><th class="r">Sec</th><th>Tyre</th><th class="r">Wear</th><th class="r">Stops</th>
    <th class="r">Wing</th><th class="r">Fuel laps</th><th class="r">ERS MJ</th><th>Mode</th><th class="r">kph</th><th>Aero</th><th>Status</th><th>Pens</th></tr></thead>
    <tbody>${rows.join('') || '<tr><td colspan="22" class="muted">No cars yet.</td></tr>'}</tbody></table></div>
    <p class="muted">Click a row for full car detail. Wear/fuel/ERS read zero for online players with restricted telemetry. "Best" fills in as session-history packets cycle through the cars (~1/s).</p>`, 'wide');
}

// ---------------------------------------------------------------- car

function inputs(t, extra) {
  if (!t) return '<p class="muted">No telemetry.</p>';
  const bar = (v, c) => `<div class="bar"><i style="width:${Math.round(v * 100)}%;background:${c}"></i></div>`;
  return `<div class="stat-row">
      <div><div class="label">Speed</div><div class="big">${t.speed}</div></div>
      <div><div class="label">Gear</div><div class="big">${t.gear === 0 ? 'N' : t.gear === -1 ? 'R' : t.gear}</div></div>
      <div><div class="label">RPM</div><div class="big">${t.engineRPM}</div></div>
      ${extra.suggestedGear ? `<div><div class="label">Suggested</div><div class="big muted">${extra.suggestedGear}</div></div>` : ''}
    </div>
    <div class="label muted">Throttle ${pct(t.throttle * 100)}</div>${bar(t.throttle, 'var(--good)')}
    <div class="label muted">Brake ${pct(t.brake * 100)}</div>${bar(t.brake, 'var(--bad)')}
    <div class="label muted">Steer ${n(t.steer, 2)} · Clutch ${t.clutch}% · DRS ${t.drs ? 'open' : 'closed'} · Rev lights ${t.revLightsPercent}% · Engine ${t.engineTemperature}°C</div>`;
}

function corners(c) {
  const t = c.telemetry, d = c.damage;
  if (!t && !d) return '<p class="muted">No tyre data.</p>';
  return `<div class="corners">${CORNERS.map(([name, i]) => `<div class="corner"><h4>${name}</h4><dl class="kv">
    ${t ? `<dt>Surface / inner</dt><dd>${t.tyresSurfaceTemperature[i]}° / ${t.tyresInnerTemperature[i]}°</dd>
    <dt>Pressure</dt><dd>${n(t.tyresPressure[i], 1)} psi</dd>
    <dt>Brake</dt><dd>${t.brakesTemperature[i]}°C</dd>
    <dt>Surface</dt><dd>${esc(t.surfaceNames[i])}</dd>` : ''}
    ${d ? `<dt>Wear</dt><dd class="${sev(d.tyresWear[i], 40, 65)}">${n(d.tyresWear[i], 1)}%</dd>
    <dt>Damage</dt><dd>${d.tyresDamage[i]}%</dd>
    ${d.tyreBlisters ? `<dt>Blisters</dt><dd>${d.tyreBlisters[i]}%</dd>` : ''}
    <dt>Brake dmg</dt><dd>${d.brakesDamage[i]}%</dd>` : ''}
  </dl></div>`).join('')}</div>`;
}

function statusPanel(s) {
  if (!s) return '<p class="muted">No status.</p>';
  return `<dl class="kv">
    <dt>Tyre</dt><dd>${tyreBadge(s.names.tyre)} ${esc(s.names.compound || '')} · ${s.tyresAgeLaps} laps</dd>
    <dt>Fuel</dt><dd>${n(s.fuelInTank, 2)} / ${n(s.fuelCapacity, 1)} kg · ${n(s.fuelRemainingLaps, 2)} laps · ${esc(s.names.fuelMix)}</dd>
    <dt>ERS store</dt><dd>${MJ(s.ersStoreEnergy)} MJ · mode ${esc(s.names.ersMode)}</dd>
    <dt>ERS this lap</dt><dd>deployed ${MJ(s.ersDeployedThisLap)} · harvest K ${MJ(s.ersHarvestedThisLapMGUK)} H ${MJ(s.ersHarvestedThisLapMGUH)} · limit ${MJ(s.ersHarvestedLimitPerLap)} MJ</dd>
    <dt>Power</dt><dd>ICE ${n(s.enginePowerICE / 1000, 0)} kW · MGU-K ${n(s.enginePowerMGUK / 1000, 0)} kW</dd>
    <dt>Brake bias</dt><dd>${s.frontBrakeBias}%</dd>
    <dt>TC / ABS</dt><dd>${s.tractionControl} / ${s.antiLockBrakes}</dd>
    <dt>DRS</dt><dd>${s.drsAllowed ? 'allowed' : 'not allowed'}${s.drsActivationDistance ? ` · in ${s.drsActivationDistance} m` : ''}</dd>
    <dt>Pit limiter</dt><dd>${s.pitLimiterStatus ? 'ON' : 'off'}</dd>
    <dt>FIA flag</dt><dd>${esc(s.names.flag)}</dd>
    <dt>RPM</dt><dd>idle ${s.idleRPM} · max ${s.maxRPM} · ${s.maxGears} gears</dd>
  </dl>`;
}

function historyTable(h) {
  if (!h) return '<p class="muted">Waiting for a session-history packet for this car.</p>';
  const rows = h.lapHistoryData.map((l, i) => {
    const lap = i + 1;
    const ok = (bit) => (l.lapValidBitFlags & bit ? '' : 'bad');
    const cls = (bestLap) => (bestLap === lap ? 'purple' : '');
    return `<tr><td class="r">${lap}</td>
      <td class="r ${ok(1)} ${cls(h.bestLapTimeLapNum)}">${lapTime(l.lapTimeInMS)}</td>
      <td class="r ${ok(2)} ${cls(h.bestSector1LapNum)}">${lapTime(sector(l.sector1TimeMinutesPart, l.sector1TimeMSPart))}</td>
      <td class="r ${ok(4)} ${cls(h.bestSector2LapNum)}">${lapTime(sector(l.sector2TimeMinutesPart, l.sector2TimeMSPart))}</td>
      <td class="r ${ok(8)} ${cls(h.bestSector3LapNum)}">${lapTime(sector(l.sector3TimeMinutesPart, l.sector3TimeMSPart))}</td></tr>`;
  });
  const stints = h.tyreStintsHistoryData.map((s) => `${tyreBadge(s.visual)} ${esc(s.actual || '')} → ${s.endLap === 255 ? 'now' : `lap ${s.endLap}`}`).join('<br>');
  return `<div class="scroll"><table><thead><tr><th class="r">Lap</th><th class="r">Time</th><th class="r">S1</th><th class="r">S2</th><th class="r">S3</th></tr></thead>
    <tbody>${rows.reverse().join('')}</tbody></table></div>
    <h3 style="margin-top:12px">Stints</h3>${stints || '<span class="muted">–</span>'}
    <p class="muted">Purple = personal best; red = invalid.</p>`;
}

function tyreSetsTable(ts) {
  if (!ts) return '<p class="muted">No tyre-set data (only sent for cars you can see; restricted online).</p>';
  return `<div class="scroll"><table><thead><tr><th>#</th><th>Tyre</th><th class="r">Wear</th><th>Avail</th><th class="r">Life left</th><th class="r">Usable</th><th class="r">Δ lap</th><th>Fitted</th></tr></thead><tbody>
    ${ts.tyreSetData.map((s, i) => `<tr class="${s.available ? '' : 'muted'}"><td>${i}</td><td>${tyreBadge(s.visual)} ${esc(s.actual || '')}</td>
      <td class="r">${s.wear}%</td><td>${s.available ? 'yes' : 'no'}</td><td class="r">${s.lifeSpan}</td><td class="r">${s.usableLife}</td>
      <td class="r">${s.lapDeltaTime ? (s.lapDeltaTime / 1000).toFixed(3) : '–'}</td><td>${s.fitted ? '<b class="good">fitted</b>' : ''}</td></tr>`).join('')}
  </tbody></table></div>`;
}

export function car(c, cars, snap) {
  const opts = cars.map((x) => `<option value="${x.idx}" ${x.idx === c.idx ? 'selected' : ''}>P${x.position ?? '?'} ${esc(x.name)}${x.isPlayer ? ' (you)' : ''}</option>`).join('');
  const id = c.identity;
  return `<div class="toolbar"><label for="carSel" class="muted">Car</label><select id="carSel">${opts}</select>
      <span><span class="team" style="background:${esc(id.colour || '')}"></span><b>${esc(id.name)}</b> · ${esc(id.team)} · #${id.number ?? '?'}${c.isPlayer ? ' · <span class="warn">you</span>' : ''}</span></div>
    <div class="grid">
      ${panel('Driver inputs', inputs(c.telemetry, c.isPlayer ? snap : {}))}
      ${panel('Tyres & brakes', corners(c))}
      ${panel('Status', statusPanel(c.status))}
      ${panel('2026: active aero / overtake', kv(c.telemetry2))}
      ${panel('Lap history', historyTable(c.history))}
      ${panel('Tyre sets', tyreSetsTable(c.tyreSets))}
      ${panel('Damage', kv(c.damage, ['tyresWear', 'tyresDamage', 'tyreBlisters', 'brakesDamage']))}
      ${panel('Lap data (raw)', kv(c.lap))}
      ${panel('Setup', kv(c.setup) + (c.nextFrontWing != null ? `<p class="muted">Front wing after next stop: ${c.nextFrontWing}</p>` : ''))}
      ${panel('Participant', kv(c.participant, ['liveryColours']))}
      ${panel('Motion', kv(c.motion))}
      ${c.motionEx ? panel('Motion Ex (player only)', kv(c.motionEx)) : ''}
    </div>`;
}

// ---------------------------------------------------------------- session

export function session(s) {
  if (!s) return '<p class="muted">No session packet yet (sent twice a second).</p>';
  const fc = s.weatherForecastSamples.map((w) => `<tr><td>${esc(w.sessionTypeName)}</td><td class="r">+${w.timeOffset}m</td><td>${esc(w.weatherName)}</td>
    <td class="r">${w.trackTemperature}°</td><td class="r">${w.airTemperature}°</td><td class="r">${w.rainPercentage}%</td></tr>`).join('');
  const zones = (z) => z.map((x) => `${(x.zoneStart * 100).toFixed(1)}–${(x.zoneEnd * 100).toFixed(1)}%`).join(', ') || '–';
  return `<div class="grid">
    ${panel('Session', `<dl class="kv">
      <dt>Track</dt><dd>${esc(s.names.track)} (${s.trackLength} m)</dd>
      <dt>Session</dt><dd>${esc(s.names.sessionType)} · ${esc(s.names.formula)}</dd>
      <dt>Mode</dt><dd>${esc(s.names.gameMode)} · ${esc(s.names.ruleSet)}</dd>
      <dt>Laps</dt><dd>${s.totalLaps}</dd>
      <dt>Time left</dt><dd>${Math.floor(s.sessionTimeLeft / 60)}:${String(s.sessionTimeLeft % 60).padStart(2, '0')} of ${Math.round(s.sessionDuration / 60)} min</dd>
      <dt>Weather</dt><dd>${esc(s.names.weather)} · track ${s.trackTemperature}° · air ${s.airTemperature}°</dd>
      <dt>Safety car</dt><dd>${esc(s.names.safetyCar)} · SC ${s.numSafetyCarPeriods} · VSC ${s.numVirtualSafetyCarPeriods} · red ${s.numRedFlagPeriods}</dd>
      <dt>Pit window</dt><dd>ideal lap ${s.pitStopWindowIdealLap} · latest ${s.pitStopWindowLatestLap} · rejoin P${s.pitStopRejoinPosition}</dd>
      <dt>Pit limit</dt><dd>${s.pitSpeedLimit} kph</dd>
      <dt>Sectors</dt><dd>S2 @ ${n(s.sector2LapDistanceStart, 0)} m · S3 @ ${n(s.sector3LapDistanceStart, 0)} m</dd>
      <dt>Weekend</dt><dd>${esc(s.weekendStructure.join(' → '))}</dd>
      <dt>Active aero</dt><dd>${s.activeAeroTrackStatus == null ? '–' : s.activeAeroTrackStatus ? 'Partial' : 'Full'} · full: ${zones(s.activeAeroZonesFull)} · partial: ${zones(s.activeAeroZonesPartial)}</dd>
      <dt>DRS zones</dt><dd>${zones(s.drsZones)}</dd>
      <dt>AI difficulty</dt><dd>${s.aiDifficulty}</dd>
    </dl>`)}
    ${panel(`Forecast (${s.forecastAccuracy ? 'approximate' : 'perfect'})`, `<div class="scroll"><table><thead><tr><th>Session</th><th class="r">Offset</th><th>Weather</th><th class="r">Track</th><th class="r">Air</th><th class="r">Rain</th></tr></thead><tbody>${fc}</tbody></table></div>`)}
    ${panel('Marshal zones', s.marshalZones.map((z) => `${(z.zoneStart * 100).toFixed(1)}% <span class="${['', 'good', 'muted', 'warn'][z.zoneFlag] || 'muted'}">${['none', 'green', 'blue', 'yellow'][z.zoneFlag] ?? 'unknown'}</span>`).join(' · ') || '–')}
    ${panel('All session fields', kv(s, ['marshalZones', 'weatherForecastSamples', 'names', 'activeAeroZonesFull', 'activeAeroZonesPartial', 'drsZones']), 'wide')}
  </div>`;
}

// ---------------------------------------------------------------- events

function describe(e) {
  const d = e.details || {}, nm = e.names || {};
  switch (e.code) {
    case 'FTLP': return `${esc(nm.vehicleIdx)} — ${lapTime(d.lapTime * 1000)}`;
    case 'RTMT': return `${esc(nm.vehicleIdx)}${d.reason == null ? '' : ` (reason ${d.reason})`}`;
    case 'PENA': return `${esc(nm.vehicleIdx)}: ${esc(nm.penaltyType)} — ${esc(nm.infringementType)}${d.time && d.time !== 255 ? ` (${d.time}s)` : ''}, lap ${d.lapNum}${nm.otherVehicleIdx ? ` vs ${esc(nm.otherVehicleIdx)}` : ''}`;
    case 'SPTP': return `${esc(nm.vehicleIdx)} ${n(d.speed, 1)} kph${d.isOverallFastestInSession ? ' (session fastest)' : ''}`;
    case 'OVTK': return `${esc(nm.overtakingVehicleIdx)} passed ${esc(nm.beingOvertakenVehicleIdx)}`;
    case 'COLL': return `${esc(nm.vehicle1Idx)} × ${esc(nm.vehicle2Idx)} ${d.severity == null ? '' : ` (severity ${['low', 'medium', 'high'][d.severity] ?? d.severity})`}`;
    case 'SCAR': return `${['none', 'SC', 'VSC', 'formation'][d.safetyCarType]} ${['deployed', 'returning', 'returned', 'resume race'][d.eventType]}`;
    case 'STLG': return `${d.numLights} lights`;
    default: return Object.keys(nm).length ? esc(Object.values(nm).join(', ')) : d && Object.keys(d).length ? esc(JSON.stringify(d)) : '';
  }
}

export function events(snap) {
  const rows = [...snap.events].reverse().map((e) => `<tr><td class="r muted">${n(e.sessionTime, 1)}s</td><td>${esc(e.name)}</td><td>${describe(e)}</td></tr>`).join('');
  return `<div class="grid">
    ${panel('Race control & events', `<div class="scroll"><table><thead><tr><th class="r">Session t</th><th>Event</th><th>Detail</th></tr></thead><tbody>${rows || '<tr><td colspan="3" class="muted">No events yet.</td></tr>'}</tbody></table></div>`, 'wide')}
    ${panel('Buttons held now', snap.buttons.length ? esc(snap.buttons.join(', ')) : '<span class="muted">none</span>')}
  </div>`;
}

// ---------------------------------------------------------------- packets

export function packets(snap, rawId, raw) {
  const rows = snap.packets.map((p) => `<tr class="click" data-raw="${p.id}" tabindex="0" aria-label="Show raw ${esc(p.name)}">
    <td class="r">${p.id}</td><td>${esc(p.name)}</td><td class="r">${p.count}</td><td class="r">${n(p.rate, 1)}</td>
    <td class="r ${p.size && p.size !== p.specSize ? 'bad' : ''}">${p.size || '–'}</td><td class="r muted">${p.specSize}</td>
    <td class="r muted">${p.ageSec == null ? 'never' : `${n(p.ageSec, 1)}s ago`}</td></tr>`).join('');
  const m = snap.meta;
  return `<div class="grid">
    ${panel('Packets', `<table><thead><tr><th class="r">ID</th><th>Type</th><th class="r">Count</th><th class="r">Hz</th><th class="r">Size</th><th class="r">Spec</th><th class="r">Last</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="muted">Click a packet to see its full decoded contents.</p>`)}
    ${panel('Link', kv({ listening: `${m.listen.ip}:${m.listen.udpPort}`, recording: m.listen.recording, gameVersion: m.gameVersion, sessionUID: m.sessionUID,
      totalPackets: m.totalPackets, sources: m.sources, wrongFormats: m.wrongFormats, decodeErrors: m.errorCount, recentErrors: m.recentErrors.map((e) => e.msg) }))}
    ${rawId != null ? panel(`Raw: packet ${rawId}`, `<pre class="json">${esc(JSON.stringify(raw, null, 1))}</pre>`, 'wide') : ''}
  </div>`;
}

// ---------------------------------------------------------------- logs (dev)

export function logs(entries, filter) {
  const rows = entries
    .filter((e) => (!filter.level || e.level === filter.level) && (!filter.module || e.module === filter.module))
    .slice(-500).reverse()
    .map((e) => `<tr class="log-${e.level}"><td class="muted">${new Date(e.t * 1000).toLocaleTimeString()}</td><td>${e.level}</td><td>${esc(e.module)}</td>
      <td>${esc(e.msg)} ${e.data ? `<span class="muted">${esc(JSON.stringify(e.data))}</span>` : ''}${e.exc ? `<pre class="json">${esc(e.exc)}</pre>` : ''}</td></tr>`).join('');
  const modules = [...new Set(entries.map((e) => e.module))];
  const opt = (v, cur) => `<option ${v === cur ? 'selected' : ''}>${v}</option>`;
  return `<div class="toolbar">
      <label class="muted" for="logLevel">Level</label><select id="logLevel"><option value="">all</option>${['ERROR', 'WARNING', 'INFO', 'DEBUG', 'TRACE'].map((l) => opt(l, filter.level)).join('')}</select>
      <label class="muted" for="logModule">Module</label><select id="logModule"><option value="">all</option>${modules.map((m) => opt(m, filter.module)).join('')}</select>
      <button class="btn" id="logExportTxt">Export .txt</button><button class="btn" id="logExportJson">Export .json</button>
    </div>
    ${panel('Server log (dev)', `<div class="scroll"><table><tbody>${rows || '<tr><td class="muted">No log entries.</td></tr>'}</tbody></table></div>`)}`;
}
