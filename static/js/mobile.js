// Handles the mobile scanner page: camera + BarcodeDetector + posting scans

// Camera API requires HTTPS (or localhost). Show a helpful message if missing.
if (!("mediaDevices" in navigator) || !("getUserMedia" in navigator.mediaDevices)) {
  const host = location.host;
  document.write('<p class="err">Camera API not available. On mobile, this usually means the page is not opened over HTTPS. Try: <strong>https://' + host + '/mobile</strong>.</p>');
  throw new Error('getUserMedia unavailable');
}

const tokenInput = document.getElementById('token');
const v = document.getElementById('v');
const status = document.getElementById('status');

// Remember the token so you type it once
tokenInput.value = localStorage.getItem('ingestToken') || '';
tokenInput.addEventListener('change', () => localStorage.setItem('ingestToken', tokenInput.value.trim()));

async function start() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
    v.srcObject = stream;
    await v.play();

    if (!('BarcodeDetector' in window)) {
      status.innerHTML = '<p class="err">BarcodeDetector not supported. Use Chrome or Safari.</p>';
      return;
    }

    // Formats include QR + common retail barcodes (UPC removed to avoid EAN dup)
    const det = new BarcodeDetector({ formats: ['ean_13','ean_8','code_128','code_39','qr_code','itf'] });
    const seen = new Set();

    async function tick() {
      try {
        const barcodes = await det.detect(v);
        for (const b of barcodes) {
          const code = (b.rawValue || '').trim();
          if (code && !seen.has(code)) {
            seen.add(code);
            const token = tokenInput.value.trim();
            const r = await fetch('/scan', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Ingest-Token': token
              },
              body: JSON.stringify({ code, token })
            });
            const j = await r.json();
            status.innerHTML = `<p class="${r.ok ? 'ok' : 'err'}">${j.message || JSON.stringify(j)}</p>`;
          }
        }
      } catch (e) {}
      requestAnimationFrame(tick);
    }
    tick();
  } catch (e) {
    status.innerHTML = `<p class="err">${e.message}</p>`;
  }
}
start();