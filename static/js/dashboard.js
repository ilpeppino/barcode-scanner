// Handles the dashboard page: manual entry + recent scans table

window.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('f');
  const codeInput = document.getElementById('code');
  const tokenInput = document.getElementById('token');
  const messageEl = document.getElementById('msg');
  const tbody = document.querySelector('#t tbody');
  const tasklistSelect = document.getElementById('tasklist-select');
  const activeListTitle = document.getElementById('active-list-title');

  async function refreshRecent() {
    if (!tbody) return;
    try {
      const res = await fetch('/recent');
      const data = await res.json();
      tbody.innerHTML = data.map(x => `<tr><td>${x.when}</td><td>${x.code}</td></tr>`).join('');
    } catch (err) {
      console.error('Failed to refresh recent scans', err);
    }
  }

  async function loadTasklists() {
    if (!tasklistSelect) return;
    try {
      const res = await fetch('/tasklists');
      const data = await res.json();
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

  async function switchTasklist() {
    if (!tasklistSelect) return;
    const tasklist_id = tasklistSelect.value;
    try {
      const res = await fetch('/tasklists/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tasklist_id })
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.message || 'Failed to switch list');
      }
      if (activeListTitle) {
        const sel = tasklistSelect.options[tasklistSelect.selectedIndex];
        activeListTitle.textContent = data.title || (sel ? sel.textContent : '');
      }
      if (messageEl) {
        messageEl.textContent = `Switched to list: ${activeListTitle ? activeListTitle.textContent : ''}`;
        messageEl.className = 'ok';
      }
    } catch (err) {
      console.error('Unable to switch task list', err);
      if (messageEl) {
        messageEl.textContent = err.message || 'Unable to switch list';
        messageEl.className = 'err';
      }
      loadTasklists();
    }
  }

  async function submitScan(e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (!codeInput || !tokenInput || !messageEl) return;

    const payload = { code: codeInput.value.trim(), token: tokenInput.value.trim() };
    if (!payload.code) {
      messageEl.textContent = 'Please scan or type a code first.';
      messageEl.className = 'err';
      return;
    }

    try {
      const res = await fetch('/scan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Ingest-Token': tokenInput.value.trim()
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      messageEl.textContent = data.message || JSON.stringify(data);
      messageEl.className = res.ok ? 'ok' : 'err';
      if (!res.ok) return;
      codeInput.value = '';
      codeInput.focus();
      refreshRecent();
    } catch (err) {
      console.error('Failed to submit scan', err);
      messageEl.textContent = err.message || 'Unable to submit scan';
      messageEl.className = 'err';
    }
  }

  // Initial data fetches.
  refreshRecent();
  setInterval(refreshRecent, 1500);

  if (tasklistSelect) {
    loadTasklists();
    tasklistSelect.addEventListener('change', switchTasklist);
  }

  if (form) {
    form.addEventListener('submit', submitScan);
  }
});
