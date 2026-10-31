const form = document.querySelector('#form');
const input = document.querySelector('#files');
const drop = document.querySelector('#drop');
const queue = document.querySelector('#queue');
const results = document.querySelector('#results');
const button = document.querySelector('#convert');
const deviceStatus = document.querySelector('#device-status');
const deviceHint = document.querySelector('#device-hint');
const deviceChoice = document.querySelector('#device-choice');
const deviceSelect = document.querySelector('#device-select');
const ejectButton = document.querySelector('#device-eject');
let files = [];
let analyses = [];
let stage = 'select';
let ejecting = false;
let lastEjected = false;
let ejectMessage = '';

function draw() {
  queue.innerHTML = '';
  files.forEach((file, index) => {
    const row = document.createElement('div');
    row.className = 'file-row';
    const name = document.createElement('span');
    name.textContent = file.name;
    const size = document.createElement('small');
    size.textContent = (file.size / 1024 / 1024).toFixed(1) + ' MB';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '×';
    remove.setAttribute('aria-label', 'Quitar ' + file.name);
    remove.onclick = () => { files.splice(index, 1); resetPreview(); draw(); };
    row.append(name, size, remove);
    queue.append(row);
  });
  button.disabled = !files.length;
  button.firstChild.textContent = !files.length ? 'Revisar archivos' : (files.length === 1 ? 'Revisar archivo' : 'Revisar ' + files.length + ' archivos');
}

function add(list) {
  let changed = false;
  for (const file of list) {
    if (file.name.toLowerCase().endsWith('.pdf') && !files.some(x => x.name === file.name && x.size === file.size)) { files.push(file); changed = true; }
  }
  if (changed) resetPreview();
  draw();
}

function resetPreview() {
  analyses = [];
  stage = 'select';
  document.querySelector('#preview').hidden = true;
}

drop.onclick = () => input.click();
drop.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } };
input.onchange = () => { add(input.files); input.value = ''; };
for (const event of ['dragenter', 'dragover']) drop.addEventListener(event, e => { e.preventDefault(); drop.classList.add('dragging'); });
for (const event of ['dragleave', 'drop']) drop.addEventListener(event, e => { e.preventDefault(); drop.classList.remove('dragging'); });
drop.addEventListener('drop', e => add(e.dataTransfer.files));

async function refreshDevices() {
  if (ejecting) return;
  try {
    const response = await fetch('/devices', { cache: 'no-store' });
    if (!response.ok) throw new Error('No se pudo consultar el dispositivo.');
    const { devices } = await response.json();
    const previous = deviceSelect.value;
    deviceSelect.innerHTML = '';
    for (const device of devices) {
      const option = document.createElement('option');
      option.value = device.id;
      option.textContent = device.label + ' (' + device.path + ')';
      deviceSelect.append(option);
    }
    if (devices.some(device => device.id === previous)) deviceSelect.value = previous;
    deviceChoice.hidden = !devices.length;
    ejectButton.disabled = !devices.length;
    if (devices.length) lastEjected = false;
    deviceStatus.textContent = devices.length ? (devices.length === 1 ? 'Kobo conectado' : devices.length + ' Kobo conectados') : (lastEjected ? 'Kobo expulsado con seguridad' : 'Kobo no conectado');
    deviceHint.textContent = ejectMessage || (devices.length ? 'Puedes enviar el libro al terminar de convertir.' : (lastEjected ? 'Ya puedes desconectarlo.' : 'Conecta el lector por USB y toca «Conectar» en su pantalla.'));
    document.querySelectorAll('.send-kobo').forEach(send => { if (!send.dataset.sent) send.disabled = !devices.length; });
  } catch {
    deviceStatus.textContent = 'No se pudo comprobar el Kobo';
    deviceHint.textContent = 'Pulsa Actualizar para intentarlo de nuevo.';
    deviceChoice.hidden = true;
    ejectButton.disabled = true;
    document.querySelectorAll('.send-kobo').forEach(send => { send.disabled = true; });
  }
}

document.querySelector('#device-refresh').onclick = () => { ejectMessage = ''; refreshDevices(); };
ejectButton.onclick = async () => {
  const device = deviceSelect.value;
  if (!device || ejecting) return;
  ejecting = true;
  ejectButton.disabled = true;
  ejectButton.textContent = 'Expulsando…';
  deviceHint.textContent = 'Espera a que Windows termine de expulsar el lector.';
  try {
    const response = await fetch('/eject-kobo', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'No se pudo expulsar el Kobo.');
    lastEjected = true;
    ejectMessage = '';
  } catch (error) {
    lastEjected = false;
    ejectMessage = error.message;
  } finally {
    ejecting = false;
    ejectButton.textContent = 'Expulsar Kobo';
    await refreshDevices();
  }
};
refreshDevices();
setInterval(refreshDevices, 8000);

async function sendToKobo(result, send, feedback) {
  send.disabled = true;
  send.textContent = 'Copiando…';
  feedback.textContent = '';
  try {
    const response = await fetch('/send-to-kobo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: result.job, filename: result.filename, device: deviceSelect.value })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo copiar el libro.');
    send.textContent = 'Enviado';
    send.dataset.sent = 'true';
    feedback.textContent = 'Guardado en ' + data.path + '. Expulsa el Kobo de forma segura antes de desconectarlo.';
  } catch (error) {
    send.textContent = 'Enviar al Kobo';
    send.disabled = !deviceSelect.value;
    feedback.textContent = error.message;
    feedback.classList.add('error');
  }
}

function showResult(row, result) {
  row.className = 'result-row';
  row.textContent = '';
  const label = document.createElement('span');
  label.textContent = result.filename + ' · ' + result.pages + (result.pages === 1 ? ' página' : ' páginas') + (result.ocr_pages ? ' · OCR en ' + result.ocr_pages : '') + ' · validado con ' + result.validation;
  const link = document.createElement('a');
  link.href = result.download;
  link.textContent = result.filename.endsWith('.kepub.epub') ? 'Descargar KEPUB' : 'Descargar EPUB';
  row.append(label, link);
  if (result.epub_download) {
    const epub = document.createElement('a');
    epub.href = result.epub_download;
    epub.textContent = 'Descargar EPUB';
    row.append(epub);
  }
  const send = document.createElement('button');
  send.type = 'button';
  send.className = 'send-kobo';
  send.textContent = 'Enviar al Kobo';
  send.disabled = !deviceSelect.value;
  const feedback = document.createElement('small');
  feedback.className = 'send-feedback';
  send.onclick = () => sendToKobo(result, send, feedback);
  row.append(send, feedback);
}

function previewCard(item) {
  const card = document.createElement('div');
  card.className = 'preview-card';
  const title = document.createElement('h3');
  title.textContent = item.filename;
  const details = document.createElement('div');
  details.className = 'diagnostics';
  details.textContent = item.pages + ' páginas · ' + item.scanned_pages + ' escaneadas · ' + item.possible_columns + ' con posibles columnas · ' + item.tables + ' tablas · ' + item.image_blocks + ' imágenes';
  card.append(title, details);
  const sample = document.createElement('details');
  sample.open = true;
  const summary = document.createElement('summary');
  summary.textContent = 'Texto de muestra · primeras ' + item.samples.length + ' páginas';
  sample.append(summary);
  item.samples.forEach(page => {
    const label = document.createElement('label');
    label.textContent = 'Página ' + page.page + (page.scanned ? ' · muestra OCR' : '');
    const textarea = document.createElement('textarea');
    textarea.value = page.text;
    textarea.dataset.original = page.text;
    textarea.dataset.page = page.page;
    label.append(textarea);
    sample.append(label);
  });
  card.append(sample);
  const chapter = document.createElement('details');
  const chapterSummary = document.createElement('summary');
  chapterSummary.textContent = 'Nombres de secciones (' + item.sections.length + ')';
  chapter.append(chapterSummary);
  item.sections.forEach(section => {
    const label = document.createElement('label');
    label.textContent = 'Desde página ' + section.page;
    const field = document.createElement('input');
    field.value = section.title;
    field.dataset.original = section.title;
    field.dataset.section = section.page;
    label.append(field);
    chapter.append(label);
  });
  card.append(chapter);
  item.card = card;
  return card;
}

async function loadHistory() {
  try {
    const { jobs } = await (await fetch('/history')).json();
    const list = document.querySelector('#history-list');
    list.textContent = jobs.length ? '' : 'Aún no hay conversiones recientes.';
    jobs.forEach(job => {
      const row = document.createElement('div');
      row.className = 'history-item';
      row.textContent = (job.title || job.source) + ' · ' + ({done: 'Listo', cancelled: 'Cancelado', error: 'Error'}[job.status] || job.status);
      if (job.download) {
        const link = document.createElement('a');
        link.href = job.download;
        link.textContent = 'Descargar';
        row.append(link);
      }
      list.append(row);
    });
  } catch { /* History remains optional when unavailable. */ }
}
loadHistory();

async function monitorJob(job, row) {
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 700));
    try {
      const response = await fetch('/jobs/' + job, { cache: 'no-store' });
      if (!response.ok) throw new Error('No se pudo consultar el progreso.');
      const state = await response.json();
      row.querySelector('progress').value = state.progress;
      row.querySelector('.job-stage').textContent = state.stage + ' · ' + state.progress + '%';
      if (state.status === 'running') continue;
      if (state.status === 'done') showResult(row, state);
      else { row.className = 'result-row error'; row.textContent = state.error || state.stage; }
      loadHistory();
      return;
    } catch (error) {
      row.className = 'result-row error'; row.textContent = error.message;
      return;
    }
  }
}

form.onsubmit = async event => {
  event.preventDefault();
  if (stage === 'select') {
    if (!files.length) return;
    stage = 'busy'; button.disabled = true; button.textContent = 'Analizando…';
    analyses = [];
    const list = document.querySelector('#preview-list'); list.textContent = '';
    for (const file of files) {
      const data = new FormData(); data.set('file', file);
      try {
        const response = await fetch('/analyze', { method: 'POST', body: data });
        const item = await response.json();
        if (!response.ok) throw new Error(item.error || 'No se pudo analizar.');
        analyses.push(item); list.append(previewCard(item));
      } catch (error) { const row = document.createElement('p'); row.className = 'error'; row.textContent = file.name + ': ' + error.message; list.append(row); }
    }
    document.querySelector('#preview').hidden = false;
    stage = 'preview'; button.disabled = !analyses.length; button.textContent = 'Iniciar conversión';
    document.querySelector('#preview').scrollIntoView({ behavior: 'smooth' });
    return;
  }
  if (stage !== 'preview') return;
  stage = 'busy'; button.disabled = true; button.textContent = 'Iniciando…';
  results.textContent = '';
  const data = new FormData(form);
  const options = { format: data.get('format'), translation: data.get('translation'), title: data.get('title'), author: data.get('author'),
    cover: data.has('cover'), chapters: data.has('chapters'), images: data.has('images'), ocr: data.has('ocr') };
  for (const item of analyses) {
    const overrides = { pages: {}, sections: {} };
    item.card.querySelectorAll('textarea[data-page]').forEach(field => { if (field.value !== field.dataset.original) overrides.pages[field.dataset.page] = field.value; });
    item.card.querySelectorAll('input[data-section]').forEach(field => { if (field.value !== field.dataset.original) overrides.sections[field.dataset.section] = field.value; });
    const row = document.createElement('div'); row.className = 'job-row'; results.append(row);
    try {
      const response = await fetch('/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: item.token, filename: item.filename, options, overrides }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'No se pudo iniciar.');
      const name = document.createElement('span'); name.textContent = item.filename;
      const meter = document.createElement('progress'); meter.max = 100; meter.value = 0;
      const phase = document.createElement('small'); phase.className = 'job-stage'; phase.textContent = 'Preparando';
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancelar';
      cancel.onclick = async () => { cancel.disabled = true; await fetch('/jobs/' + result.job + '/cancel', { method: 'POST' }); };
      row.append(name, meter, phase, cancel);
      monitorJob(result.job, row);
    } catch (error) { row.className = 'result-row error'; row.textContent = item.filename + ': ' + error.message; }
  }
  files = []; resetPreview(); draw();
};

if (!window.KEPUB_READY) {
  const option = document.querySelector('#format option[value="kepub"]');
  option.textContent = 'KEPUB · instala kepubify primero';
  option.disabled = true;
  document.querySelector('#format').value = 'epub';
}
