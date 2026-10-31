/**
 * GST Copilot Frontend Application
 * Vanilla JS client interfacing directly with FastAPI endpoints:
 * - /ready
 * - /ask and /ask/stream
 * - /feedback
 * - /reconcile (JSON and CSV)
 * - /check-invoice
 *
 * Strict requirements:
 * - No emojis: crisp SVGs only
 * - Strict HTML escaping for untrusted data
 * - Privacy: Invoices processed in-memory
 */

// ==========================================
// 1. Utilities & Security
// ==========================================

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatRupees(amount) {
  const num = parseFloat(amount || 0);
  if (isNaN(num)) return '0.00';
  return num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// SVG Icons helper (Zero emojis)
const ICONS = {
  check: `<svg class="rule-icon success" viewBox="0 0 16 16" fill="currentColor"><path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/></svg>`,
  cross: `<svg class="rule-icon error" viewBox="0 0 16 16" fill="currentColor"><path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.75.75 0 111.06 1.06L9.06 8l3.22 3.22a.75.75 0 11-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 01-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 010-1.06z"/></svg>`,
  chevronDown: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><path d="M4 6l4 4 4-4" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  external: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" style="width:13px;height:13px;vertical-align:text-bottom;"><path d="M11 3h2v2M8 8l5-5M13 8v5a1 1 0 01-1 1H3a1 1 0 01-1-1V4a1 1 0 011-1h5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};

// ==========================================
// 1b. Cursor Movement & Motion Graphics Engine
// ==========================================

function initCursorAndMotion() {
  const dot = document.getElementById('custom-cursor-dot');
  const ring = document.getElementById('custom-cursor-ring');
  const glow = document.getElementById('cursor-glow');

  if (!dot || !ring) return;

  // Disable custom cursor on touch devices
  if (window.matchMedia('(pointer: coarse)').matches) {
    dot.style.display = 'none';
    ring.style.display = 'none';
    if (glow) glow.style.display = 'none';
    return;
  }

  let mouseX = window.innerWidth / 2;
  let mouseY = window.innerHeight / 2;
  let ringX = mouseX;
  let ringY = mouseY;
  let isVisible = false;

  window.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;

    if (!isVisible) {
      isVisible = true;
      dot.style.opacity = '1';
      ring.style.opacity = '1';
      if (glow) glow.style.opacity = '1';
    }

    // Instant dot movement
    dot.style.transform = `translate3d(${mouseX}px, ${mouseY}px, 0) translate3d(-50%, -50%, 0)`;

    // Global ambient cursor glow
    document.documentElement.style.setProperty('--mouse-x', `${mouseX}px`);
    document.documentElement.style.setProperty('--mouse-y', `${mouseY}px`);
  });

  document.addEventListener('mouseleave', () => {
    isVisible = false;
    dot.style.opacity = '0';
    ring.style.opacity = '0';
    if (glow) glow.style.opacity = '0';
  });

  // Smooth lerp loop for follower ring
  function animateRing() {
    ringX += (mouseX - ringX) * 0.18;
    ringY += (mouseY - ringY) * 0.18;

    ring.style.transform = `translate3d(${ringX.toFixed(2)}px, ${ringY.toFixed(2)}px, 0) translate3d(-50%, -50%, 0)`;

    requestAnimationFrame(animateRing);
  }
  requestAnimationFrame(animateRing);

  // Dynamic hover reaction over interactive elements
  const hoverSelector =
    'button, a, input, textarea, select, .chip-btn, .summary-card, .citation-chip, .nav-tab, .dropzone, .source-card, .inspect-inv-btn, .theme-toggle-btn';

  document.addEventListener('mouseover', (e) => {
    if (e.target.closest(hoverSelector)) {
      ring.classList.add('cursor-hover');
    }
  });

  document.addEventListener('mouseout', (e) => {
    if (e.target.closest(hoverSelector)) {
      ring.classList.remove('cursor-hover');
    }
  });

  document.addEventListener('mousedown', () => ring.classList.add('cursor-down'));
  document.addEventListener('mouseup', () => ring.classList.remove('cursor-down'));

  // Card surface spotlight
  document.querySelectorAll('.panel-card, .summary-card').forEach((card) => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.setProperty('--card-mouse-x', `${x}px`);
      card.style.setProperty('--card-mouse-y', `${y}px`);
    });
  });
}

// ==========================================
// 1c. Light Theme & Theme Switcher
// ==========================================

function initTheme() {
  const toggleBtn = document.getElementById('theme-toggle');
  const sunIcon = toggleBtn?.querySelector('.sun-icon');
  const moonIcon = toggleBtn?.querySelector('.moon-icon');
  const themeLabel = document.getElementById('theme-label');

  // Enforce light theme by default
  const savedTheme = localStorage.getItem('gst_theme') || 'light';
  applyTheme(savedTheme);

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      localStorage.setItem('gst_theme', next);
    });
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark') {
      sunIcon?.classList.add('hidden');
      moonIcon?.classList.remove('hidden');
      if (themeLabel) themeLabel.textContent = 'Dark';
    } else {
      sunIcon?.classList.remove('hidden');
      moonIcon?.classList.add('hidden');
      if (themeLabel) themeLabel.textContent = 'Light';
    }
  }
}

// Initialize motion and theme on script load
initCursorAndMotion();
initTheme();

// ==========================================
// 2. State & Slide-Over Drawer
// ==========================================

const state = {
  currentAskId: null,
  currentPassages: [],
  passagesMap: new Map(),
  reconcileData: null,
  booksFile: null,
  twobFile: null,
};

function openDrawer(title, tag, bodyHtml) {
  document.getElementById('drawer-title').textContent = title;
  const tagEl = document.getElementById('drawer-tag');
  tagEl.textContent = tag || 'INSPECTION';
  document.getElementById('drawer-body').innerHTML = bodyHtml;
  const drawer = document.getElementById('detail-drawer');
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
}

function closeDrawer() {
  const drawer = document.getElementById('detail-drawer');
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
}

document.getElementById('drawer-close').addEventListener('click', closeDrawer);
document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeDrawer();
});

// ==========================================
// 3. Navigation & Header Status
// ==========================================

document.querySelectorAll('.nav-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach((t) => {
      t.classList.remove('active');
      t.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.tab-pane').forEach((p) => p.classList.remove('active'));

    tab.classList.add('active');
    tab.setAttribute('aria-selected', 'true');
    const target = tab.getAttribute('data-tab');
    const pane = document.getElementById(target);
    if (pane) pane.classList.add('active');
  });
});

async function checkSystemStatus() {
  const dot = document.getElementById('status-dot');
  const label = document.getElementById('status-label');
  const corpusMeta = document.getElementById('corpus-metadata');

  try {
    const res = await fetch('/ready');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.status === 'ready') {
      dot.className = 'status-dot status-ready';
      label.textContent = 'System Ready';
    } else {
      dot.className = 'status-dot status-degraded';
      label.textContent = 'Degraded / Warming Up';
    }
    if (data.corpus_date) {
      corpusMeta.textContent = `Corpus Date: ${data.corpus_date} • CGST Act (as of 30-09-2020) • CGST Rules (as of 24-09-2021)`;
    }
  } catch (err) {
    dot.className = 'status-dot status-error';
    label.textContent = 'Service Disconnected';
  }
}

// Initial status check & repeat every 30s
checkSystemStatus();
setInterval(checkSystemStatus, 30000);

// ==========================================
// 4. Tab 1: Ask Law (RAG & SSE Streaming)
// ==========================================

// Suggestion chips
document.querySelectorAll('.prompt-suggestions .chip-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const query = btn.getAttribute('data-query');
    const textarea = document.getElementById('ask-input');
    textarea.value = query;
    textarea.focus();
  });
});

// Markdown formatter with interactive citation chips
function renderAnswerMarkdown(text, citedRefs = []) {
  if (!text) return '';
  const citedSet = new Set(citedRefs);

  // Split into lines for basic block formatting
  const lines = text.split('\n');
  const rendered = [];
  let inList = false;

  for (let line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (inList) {
        rendered.push('</ul>');
        inList = false;
      }
      continue;
    }

    // Numbered or bullet list
    const isBullet = /^[*-]\s+/.test(trimmed);
    const isNumbered = /^\d+\.\s+/.test(trimmed);

    let content = trimmed;
    if (isBullet) content = trimmed.replace(/^[*-]\s+/, '');
    if (isNumbered) content = trimmed.replace(/^\d+\.\s+/, '');

    // Format bold, code, and escape
    content = escapeHtml(content)
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');

    // Replace citations like [CGST-ACT-2017#81] with clickable chips
    content = content.replace(/\[([A-Za-z0-9._\/\-]+#\d+)\]/g, (match, ref) => {
      const isCited = citedSet.has(ref) || citedSet.size === 0;
      return `<button type="button" class="citation-chip ${isCited ? 'chip-active' : ''}" data-ref="${escapeHtml(ref)}" title="Click to view statutory passage">[${escapeHtml(ref)}]</button>`;
    });

    if (isBullet || isNumbered) {
      if (!inList) {
        rendered.push('<ul class="answer-list">');
        inList = true;
      }
      rendered.push(`<li>${content}</li>`);
    } else {
      if (inList) {
        rendered.push('</ul>');
        inList = false;
      }
      rendered.push(`<p class="answer-paragraph">${content}</p>`);
    }
  }

  if (inList) rendered.push('</ul>');
  return rendered.join('');
}

function showPassageModal(ref) {
  const passage = state.passagesMap.get(ref);
  if (!passage) {
    openDrawer(
      ref,
      'STATUTE',
      `<p class="passage-empty">No full text loaded for reference <code>${escapeHtml(ref)}</code>.</p>`
    );
    return;
  }

  const scoreInfo = [];
  if (passage.rerank_score !== null && passage.rerank_score !== undefined) {
    scoreInfo.push(`Rerank Score: <strong>${passage.rerank_score.toFixed(3)}</strong>`);
  }
  if (passage.vector_rank !== null && passage.vector_rank !== undefined) {
    scoreInfo.push(`Vector Rank: #${passage.vector_rank}`);
  }
  if (passage.keyword_rank !== null && passage.keyword_rank !== undefined) {
    scoreInfo.push(`Keyword Rank: #${passage.keyword_rank}`);
  }

  const html = `
    <div class="drawer-statute">
      <div class="drawer-statute-header">
        <div>
          <h4 class="statute-title">${escapeHtml(passage.title || passage.doc_id)}</h4>
          <span class="statute-sec">${escapeHtml(passage.section || passage.ref)}</span>
        </div>
        ${
          passage.source_url
            ? `<a href="${escapeHtml(passage.source_url)}" target="_blank" rel="noopener noreferrer" class="statute-link">Official Text ${ICONS.external}</a>`
            : ''
        }
      </div>
      <div class="drawer-statute-ranks">
        ${scoreInfo.map((s) => `<span class="badge badge-gray">${s}</span>`).join(' ')}
      </div>
      <div class="statute-quote-box">
        <pre class="statute-body">${escapeHtml(passage.text)}</pre>
      </div>
    </div>
  `;
  openDrawer(passage.ref, 'STATUTORY PASSAGE', html);
}

// Global click handler for citation chips
document.addEventListener('click', (e) => {
  const chip = e.target.closest('.citation-chip');
  if (chip) {
    const ref = chip.getAttribute('data-ref');
    if (ref) showPassageModal(ref);
  }
});

function renderSourcesList(passages, citedRefs = []) {
  const listEl = document.getElementById('sources-list');
  if (!passages || passages.length === 0) {
    listEl.innerHTML = '<p class="text-muted">No relevant statutory chunks retrieved.</p>';
    return;
  }

  const citedSet = new Set(citedRefs);
  listEl.innerHTML = passages
    .map((p, idx) => {
      const isCited = citedSet.has(p.ref);
      return `
        <div class="source-card ${isCited ? 'source-cited' : ''}" data-ref="${escapeHtml(p.ref)}">
          <div class="source-card-top">
            <span class="source-ref">${escapeHtml(p.ref)}</span>
            <span class="badge ${isCited ? 'badge-success' : 'badge-gray'}">
              ${isCited ? 'Cited in Answer' : 'Retrieved Context'}
            </span>
          </div>
          <div class="source-title">${escapeHtml(p.title || p.doc_id)} ${p.section ? '• ' + escapeHtml(p.section) : ''}</div>
          <div class="source-snippet">${escapeHtml(p.text.slice(0, 150))}...</div>
          <button type="button" class="btn btn-secondary btn-sm source-inspect-btn" data-ref="${escapeHtml(p.ref)}">
            Inspect Full Section
          </button>
        </div>
      `;
    })
    .join('');

  listEl.querySelectorAll('.source-inspect-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const ref = btn.getAttribute('data-ref');
      showPassageModal(ref);
    });
  });
}

function renderTimings(timings) {
  const container = document.getElementById('ask-timings');
  if (!timings || Object.keys(timings).length === 0) {
    container.classList.add('hidden');
    return;
  }
  const rows = Object.entries(timings)
    .map(
      ([k, v]) => `
      <tr>
        <td><code>${escapeHtml(k)}</code></td>
        <td class="font-mono text-right">${typeof v === 'number' ? v.toFixed(1) : v} ms</td>
      </tr>
    `
    )
    .join('');

  container.innerHTML = `
    <table class="timings-table">
      <thead><tr><th>Pipeline Stage</th><th class="text-right">Latency</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

document.getElementById('toggle-timings-btn').addEventListener('click', () => {
  const timingsEl = document.getElementById('ask-timings');
  timingsEl.classList.toggle('hidden');
});

// Submit Ask Query
const askForm = document.getElementById('ask-form');
const askInput = document.getElementById('ask-input');
const askAsOf = document.getElementById('ask-as-of');
const askSubmitBtn = document.getElementById('ask-submit');
const askResultContainer = document.getElementById('ask-result-container');
const askErrorEl = document.getElementById('ask-error');
const askAnswerEl = document.getElementById('ask-answer-text');
const askCursor = document.getElementById('ask-stream-cursor');
const askRefusalAlert = document.getElementById('ask-refusal-alert');
const askDisclaimer = document.getElementById('ask-disclaimer');
const askModelMeta = document.getElementById('ask-model-meta');
const feedbackStatus = document.getElementById('feedback-status');

askForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = askInput.value.trim();
  if (!question || question.length < 3) return;

  const asOf = askAsOf.value || null;

  // Reset UI
  askErrorEl.classList.add('hidden');
  askErrorEl.textContent = '';
  askResultContainer.classList.remove('hidden');
  askRefusalAlert.classList.add('hidden');
  askAnswerEl.innerHTML = '';
  askCursor.classList.remove('hidden');
  askDisclaimer.textContent = '';
  askModelMeta.textContent = '';
  feedbackStatus.textContent = '';
  document.getElementById('ask-timings').classList.add('hidden');
  askSubmitBtn.disabled = true;

  state.currentAskId = null;
  state.currentPassages = [];
  state.passagesMap.clear();

  let accumulatedText = '';
  let citedList = [];

  try {
    const response = await fetch('/ask/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, as_of: asOf }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: Failed to connect to retrieval pipeline.`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE lines split
      const parts = buffer.split('\n\n');
      buffer = parts.pop(); // incomplete message

      for (const part of parts) {
        if (!part.trim()) continue;
        const lines = part.split('\n');
        let eventType = 'message';
        let dataStr = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim();
          else if (line.startsWith('data: ')) dataStr = line.slice(6).trim();
        }

        if (!dataStr) continue;

        try {
          const data = JSON.parse(dataStr);

          if (eventType === 'passages') {
            state.currentPassages = data.passages || [];
            state.passagesMap.clear();
            for (const p of state.currentPassages) {
              state.passagesMap.set(p.ref, p);
            }
            renderSourcesList(state.currentPassages, []);
          } else if (eventType === 'token') {
            accumulatedText += data.text || '';
            askAnswerEl.innerHTML = renderAnswerMarkdown(accumulatedText, citedList);
          } else if (eventType === 'done') {
            state.currentAskId = data.ask_id;
            citedList = data.cited || [];
            accumulatedText = data.answer || accumulatedText;
            askAnswerEl.innerHTML = renderAnswerMarkdown(accumulatedText, citedList);
            renderSourcesList(state.currentPassages, citedList);

            if (data.refused) {
              askRefusalAlert.classList.remove('hidden');
            }

            if (data.model || data.prompt_version) {
              askModelMeta.textContent = `${data.model || 'Local Model'} • Prompt: ${data.prompt_version || 'standard'}`;
            }

            renderTimings(data.timings_ms);
            askDisclaimer.textContent = data.disclaimer || 'Information, not tax advice.';
          } else if (eventType === 'error') {
            throw new Error(data.detail || 'Language model inference error.');
          }
        } catch (jsonErr) {
          console.warn('SSE parse error:', jsonErr, dataStr);
        }
      }
    }
  } catch (err) {
    // Fallback to non-streaming POST /ask if stream fails
    console.warn('Streaming encountered error, attempting non-streaming /ask fallback:', err);
    try {
      const fallbackRes = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, as_of: asOf }),
      });
      if (!fallbackRes.ok) throw new Error(`HTTP ${fallbackRes.status}`);
      const data = await fallbackRes.json();

      state.currentAskId = data.ask_id;
      state.currentPassages = data.passages || [];
      state.passagesMap.clear();
      for (const p of state.currentPassages) {
        state.passagesMap.set(p.ref, p);
      }

      accumulatedText = data.answer || '';
      citedList = (data.passages || []).filter((p) => p.cited).map((p) => p.ref);

      askAnswerEl.innerHTML = renderAnswerMarkdown(accumulatedText, citedList);
      renderSourcesList(state.currentPassages, citedList);

      if (data.refused) askRefusalAlert.classList.remove('hidden');
      if (data.model || data.prompt_version) {
        askModelMeta.textContent = `${data.model || 'Local Model'} • Prompt: ${data.prompt_version || 'standard'}`;
      }
      renderTimings(data.timings_ms);
      askDisclaimer.textContent = data.disclaimer || 'Information, not tax advice.';
    } catch (fbErr) {
      askErrorEl.textContent = `Error: ${err.message || 'Unable to process question'}`;
      askErrorEl.classList.remove('hidden');
    }
  } finally {
    askCursor.classList.add('hidden');
    askSubmitBtn.disabled = false;
  }
});

// Feedback handlers
async function sendFeedback(rating) {
  if (!state.currentAskId) {
    feedbackStatus.textContent = 'Feedback requires a stored ask_id.';
    return;
  }
  try {
    const res = await fetch('/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ask_id: state.currentAskId, rating }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    feedbackStatus.textContent = 'Thank you for your feedback.';
  } catch (err) {
    feedbackStatus.textContent = 'Failed to submit feedback.';
  }
}

document.getElementById('feedback-up').addEventListener('click', () => sendFeedback(1));
document.getElementById('feedback-down').addEventListener('click', () => sendFeedback(-1));

// ==========================================
// 5. Tab 2: Reconcile ITC
// ==========================================

const dzBooks = document.getElementById('dz-books');
const dzTwob = document.getElementById('dz-twob');
const inputBooks = document.getElementById('input-books');
const inputTwob = document.getElementById('input-twob');
const fileLabelBooks = document.getElementById('file-label-books');
const fileLabelTwob = document.getElementById('file-label-twob');
const reconForm = document.getElementById('reconcile-form');
const reconErrorEl = document.getElementById('recon-error');
const reconResultsContainer = document.getElementById('recon-results-container');
const btnDownloadCsv = document.getElementById('download-recon-csv');

// Wire dropzone click
dzBooks.addEventListener('click', () => inputBooks.click());
dzTwob.addEventListener('click', () => inputTwob.click());

// Drag and drop events
[dzBooks, dzTwob].forEach((zone) => {
  ['dragenter', 'dragover'].forEach((evt) => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach((evt) => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
    });
  });
});

dzBooks.addEventListener('drop', (e) => {
  if (e.dataTransfer.files.length) {
    handleFileSelection(e.dataTransfer.files[0], 'books');
  }
});

dzTwob.addEventListener('drop', (e) => {
  if (e.dataTransfer.files.length) {
    handleFileSelection(e.dataTransfer.files[0], 'twob');
  }
});

inputBooks.addEventListener('change', () => {
  if (inputBooks.files.length) handleFileSelection(inputBooks.files[0], 'books');
});

inputTwob.addEventListener('change', () => {
  if (inputTwob.files.length) handleFileSelection(inputTwob.files[0], 'twob');
});

function handleFileSelection(file, target) {
  const sizeKb = (file.size / 1024).toFixed(1);
  if (target === 'books') {
    state.booksFile = file;
    fileLabelBooks.textContent = `${file.name} (${sizeKb} KB)`;
    dzBooks.classList.add('file-selected');
  } else {
    state.twobFile = file;
    fileLabelTwob.textContent = `${file.name} (${sizeKb} KB)`;
    dzTwob.classList.add('file-selected');
  }
}

// Built-in synthetic sample CSVs for one-click demo
const DEMO_BOOKS_CSV = `row_id,supplier_gstin,supplier_name,invoice_no,invoice_date,taxable_value,igst,cgst,sgst,books_period
R0001,29WFQCA3362Q6ZT,Kaveri Industries,E20/26-27/0001,2026-04-30,57893.87,0.00,1447.35,1447.34,2026-04
R0002,29RYQCK3654T4ZE,Nilgiri Agencies,Z22/26-27/0002,2026-04-29,134760.98,0.00,18866.54,18866.53,2026-04
R0003,29VRNCY5146O8ZK,Nilgiri Industries,L05/26-27/0003,2026-04-03,292202.18,0.00,26298.20,26298.19,2026-04
R0004,29ZHGCQ8073L1ZL,Coral Distributors,A23/26-27/0004,2026-04-13,266642.71,0.00,37329.98,37329.98,2026-04
R0005,29ZHGCQ8073L1ZL,Coral Distributors,A23/26-27/0005,2026-04-06,57988.34,0.00,3479.30,3479.30,2026-04
R0006,33SUGCL1596R2Z6,Lotus Agencies,S04/26-27/0006,2026-04-19,19487.72,2338.53,0.00,0.00,2026-04
R0007,29WFQCA3362Q6ZT,Kaveri Industries,E20/26-27/0007,2026-04-22,99095.91,0.00,13873.43,13873.42,2026-04
R0008,33SUGCL1596R2Z6,Lotus Agencies,S04/26-27/0008,2026-04-01,369199.52,44303.94,0.00,0.00,2026-04
R0009,29ZHGCQ8073L1ZL,Coral Distributors,A23/26-27/0009,2026-04-17,436989.29,0.00,10924.73,10924.73,2026-04
R0010,33SUGCL1596R2Z6,Lotus Agencies,S04/26-27/0010,2026-04-27,292124.58,35054.95,0.00,0.00,2026-04
R0011,29PUMCB3122C4ZD,Coral Traders,O16/26-27/0012,2026-04-09,162423.25,0.00,14618.10,14618.09,2026-04`;

const DEMO_TWOB_CSV = `row_id,supplier_gstin,trade_name,invoice_no,invoice_date,taxable_value,igst,cgst,sgst,return_period,itc_available
B0001,29WFQCA3362Q6ZT,Kaveri Industries,E20/26-27/0001,2026-04-30,57893.87,0.00,1447.35,1447.34,2026-04,Y
B0002,29VRNCY5146O8ZK,Nilgiri Industries,L05/26-27/0003,2026-04-03,292202.18,0.00,26298.20,26298.19,2026-04,Y
B0003,29ZHGCQ8073L1ZL,Coral Distributors,A23/26-27/0004,2026-04-13,239978.44,0.00,33596.98,33596.98,2026-04,Y
B0004,29ZHGCQ8073L1ZL,Coral Distributors,A23/26-27/0005,2026-04-06,57988.34,0.00,3479.30,3479.30,2026-05,Y
B0005,33SUGCL1596R2Z6,Lotus Agencies,S04/26-27/0006,2026-04-19,19487.72,2338.53,0.00,0.00,2026-04,Y
B0006,29WFQCA3362Q6ZT,Kaveri Industries,E20/26-27/0007,2026-04-22,99095.91,0.00,13873.43,13873.42,2026-04,Y
B0007,33SUGCL1596R2Z6,Lotus Agencies,S04/26-27/0008,2026-04-01,369199.92,44303.94,0.00,0.00,2026-04,Y
B0008,29ZHGCQ8073L1ZL,Coral Distributors,A23/26-27/0009,2026-04-17,436989.29,0.00,10924.73,10924.73,2026-04,Y
B0009,33SUGCL1596R2Z6,Lotus Agencies,S04/26-27/0010,2026-04-27,292124.58,35054.95,0.00,0.00,2026-04,Y
B0010,29UBCCR1542L1ZL,Indus Industries,Q00/26-27/0011,2026-04-10,170003.48,0.00,10200.21,10200.21,2026-04,Y
B0011,29PUMCB3122C4ZD,Coral Traders,O16 26-27 000012,2026-04-09,162423.25,0.00,14618.10,14618.09,2026-04,Y`;

document.getElementById('load-sample-recon').addEventListener('click', () => {
  const blobBooks = new Blob([DEMO_BOOKS_CSV], { type: 'text/csv' });
  const blobTwob = new Blob([DEMO_TWOB_CSV], { type: 'text/csv' });

  const fileB = new File([blobBooks], 'sample_purchase_register.csv', { type: 'text/csv' });
  const fileG = new File([blobTwob], 'sample_gstr2b.csv', { type: 'text/csv' });

  handleFileSelection(fileB, 'books');
  handleFileSelection(fileG, 'twob');
});

// Run reconciliation
reconForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!state.booksFile || !state.twobFile) {
    reconErrorEl.textContent = 'Please select both Purchase Register and GSTR-2B CSV files.';
    reconErrorEl.classList.remove('hidden');
    return;
  }

  reconErrorEl.classList.add('hidden');
  const tolerance = document.getElementById('recon-tolerance').value || '1.00';
  const submitBtn = document.getElementById('recon-submit');
  submitBtn.disabled = true;

  const formData = new FormData();
  formData.append('purchase_register', state.booksFile);
  formData.append('gstr2b', state.twobFile);

  try {
    const res = await fetch(`/reconcile?format=json&tolerance=${encodeURIComponent(tolerance)}`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Server returned HTTP ${res.status}`);
    }

    const data = await res.json();
    state.reconcileData = data;
    renderReconciliation(data);
    btnDownloadCsv.classList.remove('hidden');
    reconResultsContainer.classList.remove('hidden');
  } catch (err) {
    reconErrorEl.textContent = `Reconciliation error: ${err.message}`;
    reconErrorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
  }
});

// Download CSV results
btnDownloadCsv.addEventListener('click', async () => {
  if (!state.booksFile || !state.twobFile) return;
  const tolerance = document.getElementById('recon-tolerance').value || '1.00';
  const formData = new FormData();
  formData.append('purchase_register', state.booksFile);
  formData.append('gstr2b', state.twobFile);

  try {
    const res = await fetch(`/reconcile?format=csv&tolerance=${encodeURIComponent(tolerance)}`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'reconciliation.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  } catch (err) {
    alert('Failed to download reconciliation CSV.');
  }
});

function renderReconciliation(data) {
  // 1. Summary Cards (10 labels)
  const summaryEl = document.getElementById('summary-cards');
  const filterSelect = document.getElementById('recon-filter-label');

  // Reset dropdown
  filterSelect.innerHTML = '<option value="">All Categories</option>';

  const labels = Object.keys(data.summary || {});
  summaryEl.innerHTML = labels
    .map((label) => {
      const count = data.summary[label] || 0;
      const taxAmount = data.tax_by_label[label] || '0.00';
      const exp = (data.explanations && data.explanations[label]) || {};
      const title = exp.title || label.replace(/_/g, ' ').toUpperCase();

      // Populate filter dropdown
      const opt = document.createElement('option');
      opt.value = label;
      opt.textContent = `${title} (${count})`;
      filterSelect.appendChild(opt);

      return `
        <div class="summary-card" data-label="${escapeHtml(label)}">
          <div class="summary-card-top">
            <span class="summary-label">${escapeHtml(title)}</span>
            <span class="badge ${label === 'matched' ? 'badge-success' : 'badge-warning'}">${count}</span>
          </div>
          <div class="summary-tax">&#8377; ${formatRupees(taxAmount)}</div>
          <div class="summary-sub">${escapeHtml(exp.action || 'Deterministic match')}</div>
        </div>
      `;
    })
    .join('');

  // 2. Draft GSTR-3B Table 4
  renderTable4(data.draft_3b);

  // 3. Detailed Invoices Table
  renderInvoicesTable(data.results || [], data.explanations || {});
}

function renderTable4(draft3b) {
  const tbody = document.getElementById('table4-body');
  if (!draft3b) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No draft generated</td></tr>';
    return;
  }

  const rows = [
    { key: 'a5_all_other_itc', data: draft3b.a5_all_other_itc },
    { key: 'b1_permanent_reversals', data: draft3b.b1_permanent_reversals },
    { key: 'b2_temporary_reversals', data: draft3b.b2_temporary_reversals },
    { key: 'c_net_itc', data: draft3b.c_net_itc, highlight: true },
    { key: 'd1_reclaimed', data: draft3b.d1_reclaimed },
    { key: 'd2_ineligible', data: draft3b.d2_ineligible },
  ];

  tbody.innerHTML = rows
    .map(({ data, highlight }) => {
      if (!data) return '';
      const tax = data.tax || {};
      const refsId = `refs-${data.row_key.replace(/[^a-zA-Z0-9]/g, '_')}`;
      const refsList = (data.invoice_refs || []).map((r) => escapeHtml(r)).join(', ');

      return `
        <tr class="${highlight ? 'table4-net-row' : ''}">
          <td>
            <strong>${escapeHtml(data.row_key)}</strong> - ${escapeHtml(data.description)}
            ${
              data.invoice_refs && data.invoice_refs.length > 0
                ? `<br><button type="button" class="text-link refs-toggle" data-target="${refsId}">View ${data.invoice_count} invoice refs ${ICONS.chevronDown}</button>
                   <div id="${refsId}" class="invoice-refs-collapsible hidden font-mono">${refsList}</div>`
                : ''
            }
          </td>
          <td class="font-mono text-right">&#8377; ${formatRupees(tax.igst)}</td>
          <td class="font-mono text-right">&#8377; ${formatRupees(tax.cgst)}</td>
          <td class="font-mono text-right">&#8377; ${formatRupees(tax.sgst)}</td>
          <td class="font-mono text-right font-bold">&#8377; ${formatRupees(tax.total)}</td>
          <td class="text-center">${data.invoice_count}</td>
        </tr>
      `;
    })
    .join('');

  tbody.querySelectorAll('.refs-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const targetEl = document.getElementById(targetId);
      if (targetEl) targetEl.classList.toggle('hidden');
    });
  });
}

function renderInvoicesTable(results, explanations) {
  const tbody = document.getElementById('invoices-table-body');
  const searchInput = document.getElementById('recon-search');
  const filterSelect = document.getElementById('recon-filter-label');

  function filterAndDisplay() {
    const q = searchInput.value.toLowerCase().trim();
    const selectedLabel = filterSelect.value;

    const filtered = results.filter((inv) => {
      const matchSearch =
        !q ||
        inv.supplier_gstin.toLowerCase().includes(q) ||
        inv.invoice_no.toLowerCase().includes(q);
      const matchLabel = !selectedLabel || inv.label === selectedLabel;
      return matchSearch && matchLabel;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No invoices found matching criteria</td></tr>';
      return;
    }

    tbody.innerHTML = filtered
      .slice(0, 100) // render top 100 for responsive responsiveness
      .map((inv, idx) => {
        const exp = explanations[inv.label] || {};
        const diffsStr = Object.entries(inv.details || {})
          .map(([k, v]) => `${k}: ${v}`)
          .join(', ');

        return `
          <tr>
            <td>
              <span class="badge ${inv.label === 'matched' ? 'badge-success' : 'badge-warning'}">
                ${escapeHtml(exp.title || inv.label)}
              </span>
            </td>
            <td class="font-mono">${escapeHtml(inv.supplier_gstin)}</td>
            <td class="font-mono">${escapeHtml(inv.invoice_no)}</td>
            <td class="font-mono text-right">&#8377; ${formatRupees(inv.total_tax)}</td>
            <td class="text-muted text-sm">${escapeHtml(diffsStr || 'No variance')}</td>
            <td>
              <button type="button" class="btn btn-secondary btn-sm inspect-inv-btn" data-index="${idx}">
                Inspect
              </button>
            </td>
          </tr>
        `;
      })
      .join('');

    tbody.querySelectorAll('.inspect-inv-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.getAttribute('data-index'), 10);
        showInvoiceExplanation(filtered[idx], explanations);
      });
    });
  }

  searchInput.addEventListener('input', filterAndDisplay);
  filterSelect.addEventListener('change', filterAndDisplay);
  filterAndDisplay();
}

function showInvoiceExplanation(inv, explanations) {
  const exp = explanations[inv.label] || {};
  const diffsHtml = Object.entries(inv.details || {})
    .map(
      ([k, v]) => `
      <div class="diff-row">
        <span class="diff-key">${escapeHtml(k)}:</span>
        <span class="diff-val">${escapeHtml(v)}</span>
      </div>
    `
    )
    .join('');

  const html = `
    <div class="drawer-explanation">
      <div class="explanation-hero">
        <span class="badge ${inv.label === 'matched' ? 'badge-success' : 'badge-warning'}">${escapeHtml(exp.title || inv.label)}</span>
        <h4 class="hero-title">Invoice ${escapeHtml(inv.invoice_no)}</h4>
        <span class="hero-subtitle">Supplier: ${escapeHtml(inv.supplier_gstin)}</span>
      </div>

      <div class="exp-block">
        <h5 class="exp-heading">Compliance Explanation</h5>
        <p class="exp-text">${escapeHtml(exp.explanation || 'No rule details available.')}</p>
      </div>

      <div class="exp-block">
        <h5 class="exp-heading">Required Taxpayer Action</h5>
        <div class="action-box">${escapeHtml(exp.action || 'Claim credit in current period.')}</div>
      </div>

      <div class="exp-grid-meta">
        <div>
          <span class="meta-label">GSTR-3B Table 4 Row</span>
          <span class="meta-value font-mono">${escapeHtml(exp.gstr3b_row || '4(A)(5)')}</span>
        </div>
        <div>
          <span class="meta-label">Statutory Citation</span>
          <span class="meta-value">${escapeHtml(exp.citation || 'Section 16(2)')}</span>
        </div>
      </div>

      ${
        diffsHtml
          ? `
        <div class="exp-block">
          <h5 class="exp-heading">Calculated Variances</h5>
          <div class="diffs-container">${diffsHtml}</div>
        </div>
      `
          : ''
      }
    </div>
  `;

  openDrawer(inv.invoice_no, 'RECONCILIATION AUDIT', html);
}

// ==========================================
// 6. Tab 3: Check Invoice
// ==========================================

const invForm = document.getElementById('check-invoice-form');
const invSupplierGstin = document.getElementById('inv-supplier-gstin');
const invInvoiceNo = document.getElementById('inv-invoice-no');
const invInvoiceDate = document.getElementById('inv-invoice-date');
const invPos = document.getElementById('inv-pos');
const invTaxableVal = document.getElementById('inv-taxable-val');
const invCgst = document.getElementById('inv-cgst');
const invSgst = document.getElementById('inv-sgst');
const invIgst = document.getElementById('inv-igst');
const invTotal = document.getElementById('inv-total');

const checkResultsContainer = document.getElementById('check-invoice-results');
const checkStatusBanner = document.getElementById('check-status-banner');
const checkRulesList = document.getElementById('check-rules-list');
const checkDisclaimer = document.getElementById('check-disclaimer');
const checkErrorEl = document.getElementById('check-invoice-error');

// Valid Sample button
document.getElementById('btn-load-valid-inv').addEventListener('click', () => {
  invSupplierGstin.value = '27AAPFU0939F1ZV';
  invInvoiceNo.value = 'INV-2024-001';
  invInvoiceDate.value = '2024-10-15';
  invPos.value = '27';
  invTaxableVal.value = '100000.00';
  invCgst.value = '9000.00';
  invSgst.value = '9000.00';
  invIgst.value = '0.00';
  invTotal.value = '118000.00';
});

// Invalid Sample button (Wrong check character + arithmetic mismatch)
document.getElementById('btn-load-invalid-inv').addEventListener('click', () => {
  invSupplierGstin.value = '27AAPFU0939F1ZA'; // Invalid check digit
  invInvoiceNo.value = 'INV-2024-002';
  invInvoiceDate.value = '2024-10-15';
  invPos.value = '27';
  invTaxableVal.value = '100000.00';
  invCgst.value = '9000.00';
  invSgst.value = '9000.00';
  invIgst.value = '0.00';
  invTotal.value = '115000.00'; // Arithmetic mismatch: 100k + 18k != 115k
});

invForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  checkErrorEl.classList.add('hidden');
  const submitBtn = document.getElementById('inv-submit');
  submitBtn.disabled = true;

  const payload = {
    supplier_gstin: invSupplierGstin.value.trim(),
    invoice_no: invInvoiceNo.value.trim(),
    invoice_date: invInvoiceDate.value,
    place_of_supply: invPos.value.trim(),
    taxable_value: parseFloat(invTaxableVal.value || 0),
    cgst: parseFloat(invCgst.value || 0),
    sgst: parseFloat(invSgst.value || 0),
    igst: parseFloat(invIgst.value || 0),
    invoice_total: parseFloat(invTotal.value || 0),
  };

  try {
    const res = await fetch('/check-invoice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(
        (err.detail && (typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail))) ||
          `HTTP ${res.status}`
      );
    }

    const data = await res.json();
    renderInvoiceChecks(data);
    checkResultsContainer.classList.remove('hidden');
  } catch (err) {
    checkErrorEl.textContent = `Validation call error: ${err.message}`;
    checkErrorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
  }
});

function renderInvoiceChecks(data) {
  // 1. Status banner (SVG icons, no emojis)
  if (data.ok) {
    checkStatusBanner.className = 'status-banner banner-success';
    checkStatusBanner.innerHTML = `
      <div class="banner-title-group">
        ${ICONS.check}
        <h4 class="banner-heading">All Invoice Validations Passed</h4>
      </div>
      <p class="banner-desc">Invoice conforms to GSTIN checksum requirements and mathematical totals.</p>
    `;
  } else {
    checkStatusBanner.className = 'status-banner banner-error';
    checkStatusBanner.innerHTML = `
      <div class="banner-title-group">
        ${ICONS.cross}
        <h4 class="banner-heading">Invoice Validation Discrepancies</h4>
      </div>
      <p class="banner-desc">One or more statutory invoice rules failed verification. Review details below.</p>
    `;
  }

  // 2. Rules list
  checkRulesList.innerHTML = (data.checks || [])
    .map((c) => {
      const icon = c.ok ? ICONS.check : ICONS.cross;
      const statusClass = c.ok ? 'rule-passed' : 'rule-failed';

      return `
        <div class="rule-item ${statusClass}">
          <div class="rule-icon-box">${icon}</div>
          <div class="rule-details">
            <div class="rule-header">
              <span class="rule-name">${escapeHtml(c.rule.replace(/_/g, ' ').toUpperCase())}</span>
              ${
                !c.verified
                  ? `<span class="badge badge-warning" title="Rule logic marked unverified against CBIC law">Unverified Rule</span>`
                  : ''
              }
            </div>
            <div class="rule-msg">${escapeHtml(c.message)}</div>
          </div>
        </div>
      `;
    })
    .join('');

  // 3. Disclaimer
  checkDisclaimer.textContent = data.disclaimer || 'Format and arithmetic checks only, not tax advice.';
}
