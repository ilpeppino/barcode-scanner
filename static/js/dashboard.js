// Handles the dashboard page: manual entry + recent scans table

const f = document.getElementById('f');
const code = document.getElementById('code');
const token = document.getElementById('token');
const msg = document.getElementById('msg');
const tbody = document.querySelector('#t tbody');
const scannerDot = document.getElementById('scanner-dot');
const scannerText = document.getElementById('scanner-status-text');
const tasklistSelect = document.getElementById('tasklist-select');
const activeListTitle = document.getElementById('active-list-title');
const rawRefreshMs = document.body && document.body.dataset ? Number(document.body.dataset.scannerRefreshMs) : NaN;
const scannerRefreshMs = (!Number.isFinite(rawRefreshMs) || rawRefreshMs <= 0) ? 5000 : rawRefreshMs;
const scannerInterval = Math.max(1000, scannerRefreshMs);

async function refresh() {
  const r = await fetch('/recent');
  const data = await r.json();
  tbody.innerHTML = data.map(x => `<tr><td>${x.when}</td><td>${x.code}</td></tr>`).join('');
}
setInterval(refresh, 1500);
refresh();
if (scannerDot) {
  refreshScanner();
  setInterval(refreshScanner, scannerInterval);
}
if (tasklistSelect) {
  loadTasklists();
  tasklistSelect.addEventListener('change', onTasklistChange);
}

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = { code: code.value.trim(), token: token.value.trim() };
  if (!payload.code) {
    msg.textContent = 'Please scan or type a code first.';
    msg.className = 'err';
    return;
  }
  const r = await fetch('/scan', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Ingest-Token': token.value.trim()
    },
    body: JSON.stringify(payload)
  });
  const j = await r.json();
  msg.textContent = j.message || JSON.stringify(j);
  msg.className = r.ok ? 'ok' : 'err';
  if (!r.ok) return;
  code.value = '';
  code.focus();
  refresh();
});

async function refreshScanner() {
  if (!scannerDot) return;
  try {
    const r = await fetch('/scanner-status');
    const j = await r.json();
    scannerDot.classList.remove('connected', 'disconnected');
    if (j.connected) {
      scannerDot.classList.add('connected');
      scannerDot.title = 'Scanner connected';
      if (scannerText) scannerText.textContent = 'Scanner connected';
    } else {
      scannerDot.classList.add('disconnected');
      scannerDot.title = 'Scanner not detected';
      if (scannerText) scannerText.textContent = 'Scanner not detected';
    }
  } catch (err) {
    scannerDot.classList.remove('connected');
    scannerDot.classList.add('disconnected');
    scannerDot.title = 'Scanner status unavailable';
    if (scannerText) scannerText.textContent = 'Scanner status unavailable';
  }
}

async function loadTasklists() {
  try {
    const r = await fetch('/tasklists');
    const data = await r.json();
    if (!Array.isArray(data.items)) return;
    tasklistSelect.innerHTML = '';
    for (const item of data.items) {
      const opt = document.createElement('option');
      opt.value = item.id;
      opt.textContent = item.title;
      if (item.id === data.selected) opt.selected = true;
      tasklistSelect.appendChild(opt);
    }
    if (activeListTitle) {
      const sel = tasklistSelect.options[tasklistSelect.selectedIndex];
      if (sel) activeListTitle.textContent = sel.textContent;
    }
  } catch (err) {
    console.error('Failed to load tasklists', err);
  }
}

async function onTasklistChange() {
  const tasklist_id = tasklistSelect.value;
  try {
    const r = await fetch('/tasklists/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tasklist_id })
    });
    const data = await r.json();
    if (!r.ok || !data.ok) {
      throw new Error(data.message || 'Failed to switch list');
    }
    if (activeListTitle) activeListTitle.textContent = data.title || tasklistSelect.options[tasklistSelect.selectedIndex].textContent;
    msg.textContent = `Switched to list: ${activeListTitle.textContent}`;
    msg.className = 'ok';
  } catch (err) {
    console.error(err);
    msg.textContent = err.message || 'Unable to switch list';
    msg.className = 'err';
    loadTasklists();
  }
}
