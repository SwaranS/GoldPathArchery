(() => {
  'use strict';
  const root = document.getElementById('scorer');
  const data = JSON.parse(document.getElementById('scoring-data').textContent);
  const $ = id => document.getElementById(id);
  let pending = null, busy = false, lastEntry = -Infinity;
  const position = $('position');
  const shots = new Map(data.shots.map(s => [s.position, s]));
  const state = message => { $('save-state').textContent = message; };
  const stage = () => data.stages[data.slots[Number(position.value)].stage];
  const symbolPoints = (s, symbol) => symbol === 'M' ? 0 : s.rules.zones.find(z => z.symbol === symbol).points;
  function entry() {
    if (!position) return;
    const s = stage(), slot = data.slots[Number(position.value)];
    $('stage-label').textContent = `Stage ${slot.stage + 1} · ${s.distance_m} m · ${s.diameter_cm} cm · ${s.rules_name}`;
    $('keypad').replaceChildren(); $('override').replaceChildren(new Option('Use tap suggestion', ''));
    for (const symbol of ['M', ...s.rules.zones.map(z => z.symbol)]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = symbol;
      button.style.minWidth = '48px'; button.style.minHeight = '48px';
      button.addEventListener('click', () => saveShot({method: 'manual', symbol}));
      $('keypad').append(button); $('override').add(new Option(symbol, symbol));
    }
    $('spot').replaceChildren(...s.geometry.spots.map((_, i) => new Option(`Spot ${i + 1}`, i)));
    const old = shots.get(Number(position.value));
    for (const option of $('physical-arrow').options) {
      const unavailable = option.dataset.active === 'false' && option.value !== String(old?.arrow_id || '');
      option.disabled = unavailable; option.hidden = unavailable;
    }
    $('physical-arrow').value = old?.arrow_id || '';
    $('reason').value = '';
    $('plot-x').value = old?.x ?? 0; $('plot-y').value = old?.y ?? 0;
    $('spot').value = old?.spot ?? 0;
    const repeats = [...shots].filter(([p, shot]) => p !== Number(position.value) && data.slots[p].stage === slot.stage && data.slots[p].end === slot.end && shot.spot !== null && shot.spot !== undefined);
    $('spot-warning').textContent = s.geometry.spots.length > 1 && repeats.length ? `Spots already used in this end: ${repeats.map(([, shot]) => shot.spot + 1).join(', ')}. Check repeated spot use against your event rules.` : '';
    draw();
  }
  function draw() {
    if (!position) return;
    const s = stage(), svg = $('target'), ns = 'http://www.w3.org/2000/svg';
    svg.replaceChildren();
    const circle = (x, y, r, color, stroke = '#555') => {
      const el = document.createElementNS(ns, 'circle');
      for (const [k, v] of Object.entries({cx:x, cy:y, r, fill:color, stroke, 'stroke-width':0.003})) el.setAttribute(k, v);
      svg.append(el);
    };
    for (const [x, y, radius] of s.geometry.spots) {
      const boundaries = [...new Set([...s.geometry.rings, ...s.rules.zones.map(z => z.radius)])].sort((a,b)=>b-a);
      for (const r of boundaries) {
        circle(x, y, r * radius, r <= .2 ? '#f4d03f' : r <= .4 ? '#e74c3c' : r <= .6 ? '#3498db' : r <= .8 ? '#222' : '#fff');
      }
    }
    for (const [p, shot] of shots) {
      if (data.slots[p].stage === data.slots[Number(position.value)].stage && data.slots[p].end === data.slots[Number(position.value)].end && shot.x !== null && shot.x !== undefined) circle(shot.x, shot.y, .012, '#2ecc71', '#000');
    }
  }
  function render() {
    if (shots.size) {
      if ($('equipment-selection')) $('equipment-selection').hidden = true;
      if ($('equipment-lock')) $('equipment-lock').textContent = 'Equipment locked. A different setup requires a new scoring session.';
    }
    const values = [...shots.values()], total = values.reduce((a, s) => a + s.points, 0);
    const max = data.slots.reduce((a, slot) => a + Math.max(...data.stages[slot.stage].rules.zones.map(z => z.points)), 0);
    $('live').textContent = `${total}/${max} · ${values.length}/${data.slots.length} arrows · Average ${values.length ? (total/values.length).toFixed(2) : '—'} · 10: ${values.filter(s=>s.points===10).length} · X: ${values.filter(s=>s.is_x).length} · 9: ${values.filter(s=>s.points===9).length}`;
    const groups = new Map();
    for (const slot of data.slots) {
      const key = `${slot.stage + 1} / ${slot.end}`;
      if (!groups.has(key)) groups.set(key, {slots:[], stage:data.stages[slot.stage]});
      groups.get(key).slots.push(slot);
      if (position) position.options[slot.position].textContent = `Stage ${slot.stage + 1}, end ${slot.end}, arrow ${slot.arrow}: ${shots.get(slot.position)?.symbol || '·'}`;
    }
    $('ends').replaceChildren(); let running = 0;
    for (const [key, group] of groups) {
      const sum = group.slots.reduce((a,s)=>a+(shots.get(s.position)?.points||0),0); running += sum;
      const row = document.createElement('tr');
      for (const value of [key, `${group.stage.distance_m} m`, group.slots.map(s=>shots.get(s.position)?.symbol||'·').join(' '),sum,running]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      $('ends').append(row);
    }
    const distribution = {};
    for (const shot of values) distribution[shot.symbol] = (distribution[shot.symbol]||0)+1;
    $('distribution').textContent = Object.entries(distribution).map(([k,v])=>`${k}: ${v}`).join(' · ');
    $('shot-detail').replaceChildren(...[...shots].sort((a,b)=>a[0]-b[0]).map(([p,s])=> {
      const li = document.createElement('li');
      li.textContent = `Shot ${p+1}: ${s.symbol}${s.arrow_snapshot?.identifier ? ' · '+s.arrow_snapshot.identifier : ''}${s.x !== null && s.x !== undefined ? ` · impact (${s.x.toFixed(3)}, ${s.y.toFixed(3)}), spot ${s.spot+1}` : ''}`;
      return li;
    }));
    draw();
  }
  async function send() {
    if (busy || !pending) return;
    busy = true; state('Saving…'); $('retry').hidden = true;
    root.querySelectorAll('button, select, input').forEach(el => { el.disabled = true; });
    try {
      const response = await fetch(root.dataset.saveUrl, {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':root.querySelector('[name=csrfmiddlewaretoken]').value}, body:JSON.stringify(pending)});
      let result;
      try { result = await response.json(); } catch { throw new Error('Save not confirmed. Check sign-in and retry.'); }
      if (!response.ok) {
        state(result.error || 'Save rejected. Reload and review.');
        if (response.status === 400 || response.status === 404) pending = null;
        else if (response.status === 409) { state(`${result.error} Your pending entry has not been saved.`); }
        return;
      }
      data.version = result.version;
      if (pending.action !== 'shot') { pending = null; location.reload(); return; }
      const saved = pending, s = data.stages[data.slots[saved.position].stage];
      let symbol = saved.symbol;
      if (!symbol) {
        const [cx,cy,r] = s.geometry.spots[saved.spot];
        const distance = Math.hypot(saved.x-cx, saved.y-cy)/r;
        symbol = s.rules.zones.find(z=>distance<=z.radius+1e-12)?.symbol||'M';
      }
      shots.set(saved.position, {symbol, points:symbolPoints(s,symbol), is_x:!!s.rules.zones.find(z=>z.symbol===symbol)?.x,
        x:saved.method==='tap'?saved.x:null, y:saved.method==='tap'?saved.y:null, spot:saved.spot,
        arrow_id:saved.arrow, arrow_snapshot:{identifier:$('physical-arrow').selectedOptions[0].textContent === 'Unidentified' ? '' : $('physical-arrow').selectedOptions[0].textContent}});
      pending = null; state('Saved to server');
      position.value = data.slots.find(slot=>!shots.has(slot.position))?.position ?? saved.position;
      entry(); render();
    } catch (error) { state(`Unsaved — ${error.message} Keep this page open and retry.`); }
    finally {
      busy = false; $('retry').hidden = !pending;
      root.querySelectorAll('button, select, input').forEach(el => { el.disabled = false; });
    }
  }
  function queue(payload) {
    if (busy || pending) { state('Finish saving or retry the pending change first.'); return; }
    pending = {...payload, version:data.version, key:crypto.randomUUID()}; send();
  }
  function saveShot(values) {
    // Ignore the second event of a touch double tap, even on a fast connection.
    if (performance.now() - lastEntry < 400) return;
    lastEntry = performance.now();
    queue({action:'shot', position:Number(position.value), reason:$('reason').value, arrow:$('physical-arrow').value || null, ...values});
  }
  $('retry').addEventListener('click', send);
  window.addEventListener('beforeunload', event => { if (pending) { event.preventDefault(); event.returnValue = ''; } });
  for (const button of root.querySelectorAll('[data-action]')) button.addEventListener('click', () => {
    const action = button.dataset.action;
    if (['delete','restore','invalidate'].includes(action) && !confirm(`${action} this session?`)) return;
    queue({action, confirmed:true});
  });
  if (position) {
    position.value = data.next_position; position.addEventListener('change', entry);
    $('method').addEventListener('change', () => {
      $('plot').hidden = $('method').value !== 'tap'; $('keypad').hidden = $('method').value !== 'manual';
    });
    const plotSave = () => saveShot({method:'tap', x:Number($('plot-x').value), y:Number($('plot-y').value), spot:Number($('spot').value), symbol:$('override').value});
    $('save-plot').addEventListener('click', plotSave);
    $('target').addEventListener('click', event => {
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform($('target').getScreenCTM().inverse());
      $('plot-x').value = point.x.toFixed(6); $('plot-y').value = point.y.toFixed(6); plotSave();
    });
    entry(); render();
  }
})();
