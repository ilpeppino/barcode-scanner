// Handles the dashboard page: manual entry + recent scans table

const f = document.getElementById('f');
const code = document.getElementById('code');
const token = document.getElementById('token');
const msg = document.getElementById('msg');
const tbody = document.querySelector('#t tbody');

async function refresh() {
  const r = await fetch('/recent');
  const data = await r.json();
  tbody.innerHTML = data.map(x => `<tr><td>${x.when}</td><td>${x.code}</td></tr>`).join('');
}
setInterval(refresh, 1500);
refresh();

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = { code: code.value.trim(), token: token.value.trim() };
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
  code.value = '';
  code.focus();
  refresh();
});
