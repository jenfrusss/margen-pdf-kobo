const form = document.querySelector('#form');
const input = document.querySelector('#files');
const drop = document.querySelector('#drop');
const queue = document.querySelector('#queue');
const button = document.querySelector('#convert');
const deviceStatus = document.querySelector('#device-status');
const deviceHint = document.querySelector('#device-hint');
const deviceChoice = document.querySelector('#device-choice');
const deviceSelect = document.querySelector('#device-select');
let files = [];

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
    remove.onclick = () => { files.splice(index, 1); draw(); };
    row.append(name, size, remove);
    queue.append(row);
  });
  button.disabled = !files.length;
  button.firstChild.textContent = files.length === 1 ? 'Convertir archivo ' : 'Convertir ' + files.length + ' archivos ';
}

function add(list) {
  for (const file of list) {
    if (file.name.toLowerCase().endsWith('.pdf') && !files.some(x => x.name === file.name && x.size === file.size)) files.push(file);
  }
  draw();
}

drop.onclick = () => input.click();
drop.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } };
input.onchange = () => { add(input.files); input.value = ''; };
for (const event of ['dragenter', 'dragover']) drop.addEventListener(event, e => { e.preventDefault(); drop.classList.add('dragging'); });
for (const event of ['dragleave', 'drop']) drop.addEventListener(event, e => { e.preventDefault(); drop.classList.remove('dragging'); });
drop.addEventListener('drop', e => add(e.dataTransfer.files));

async function refreshDevices() {
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
    deviceStatus.textContent = devices.length ? (devices.length === 1 ? 'Kobo conectado' : devices.length + ' Kobo conectados') : 'Kobo no conectado';
    deviceHint.textContent = devices.length ? 'Puedes enviar el libro al terminar de convertir.' : 'Conecta el lector por USB y toca «Conectar» en su pantalla.';
    document.querySelectorAll('.send-kobo').forEach(send => { if (!send.dataset.sent) send.disabled = !devices.length; });
  } catch {
    deviceStatus.textContent = 'No se pudo comprobar el Kobo';
    deviceHint.textContent = 'Pulsa Actualizar para intentarlo de nuevo.';
    deviceChoice.hidden = true;
    document.querySelectorAll('.send-kobo').forEach(send => { send.disabled = true; });
  }
}

document.querySelector('#device-refresh').onclick = refreshDevices;
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

form.onsubmit = async event => {
  event.preventDefault();
  if (!files.length) return;
  button.disabled = true;
  button.innerHTML = 'Convirtiendo…';
  queue.innerHTML = '';
  for (const file of files) {
    const row = document.createElement('div');
    row.className = 'result-row';
    row.textContent = 'Procesando ' + file.name + '…';
    queue.append(row);
    const data = new FormData(form);
    data.set('file', file);
    try {
      const response = await fetch('/convert', { method: 'POST', body: data });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'No se pudo convertir.');
      row.textContent = '';
      const label = document.createElement('span');
      label.textContent = result.filename + ' · ' + result.pages + ' páginas';
      const link = document.createElement('a');
      link.href = result.download;
      link.textContent = 'Descargar';
      const send = document.createElement('button');
      send.type = 'button';
      send.className = 'send-kobo';
      send.textContent = 'Enviar al Kobo';
      send.disabled = !deviceSelect.value;
      const feedback = document.createElement('small');
      feedback.className = 'send-feedback';
      send.onclick = () => sendToKobo(result, send, feedback);
      row.append(label, link, send, feedback);
    } catch (error) {
      row.classList.add('error');
      row.textContent = file.name + ': ' + error.message;
    }
  }
  files = [];
  button.innerHTML = 'Convertir archivos <span>↗</span>';
  button.disabled = true;
};

if (!window.KEPUB_READY) {
  const option = document.querySelector('#format option[value="kepub"]');
  option.textContent = 'KEPUB · instala kepubify primero';
  option.disabled = true;
  document.querySelector('#format').value = 'epub';
}
