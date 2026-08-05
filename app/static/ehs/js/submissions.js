// ============================================================================
// Submissions page — fetches the user's submissions (or all, for admins),
// renders the table, handles filters, and shows PDF preview in a modal.
// ============================================================================

const FORM_ICONS = {
  toolbox: '🛠️', induction: '👷', 'ehs-audit': '🔍', incident: '⚠️', 'hse-meeting': '👥',
  'portable-grinding-machine': '⚙️', 'gas-welding-set': '🔥', 'aerial-boomlift': '🏗️',
  'air-compressor': '💨', 'arc-welding-machine': '⚡', 'cutting-machine': '✂️',
  'first-aid-box': '🏥', generator: '🔋', ladder: '🪜', 'mdb-panel': '🔌',
  'mobile-scaffolding': '🪟', 'scaffolding-cuplock': '🏗️', truck: '🚚',
  'labour-camp': '🏠', 'mobile-crane': '🏗️',
};

let me = null;
let lastResponse = null;

(async function init() {
  // Pull current user info first
  try {
    me = await fetch('/ehs/api/me').then(r => {
      if (!r.ok) throw new Error('Not authenticated');
      return r.json();
    });
  } catch {
    location.href = '/auth/login';
    return;
  }

  document.getElementById('user-pill').innerHTML = `
    <div class="app-header__user">
      ${me.picture ? `<img src="${me.picture}" alt="">` : ''}
      <div>
        <div class="app-header__user-name">${escapeHtml(me.name)}</div>
        <div class="app-header__user-email">${escapeHtml(me.email)}</div>
      </div>
    </div>
  `;

  // Set up event listeners
  document.getElementById('apply-filters').addEventListener('click', loadSubmissions);
  document.getElementById('clear-filters').addEventListener('click', () => {
    document.getElementById('filter-form').value = '';
    document.getElementById('filter-status').value = '';
    document.getElementById('filter-start').value = '';
    document.getElementById('filter-end').value = '';
    if (document.getElementById('filter-submitter')) {
      document.getElementById('filter-submitter').value = '';
    }
    // Update URL to remove ?status=...
    history.replaceState(null, '', '/ehs/submissions');
    loadSubmissions();
  });
  document.getElementById('refresh-btn').addEventListener('click', () => loadSubmissions(true));

  // PDF modal close handlers
  document.getElementById('pdf-modal-close').addEventListener('click', closePdfModal);
  document.getElementById('pdf-close-btn').addEventListener('click', closePdfModal);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closePdfModal();
  });

  // Read initial filters from URL query string (e.g., /ehs/submissions?status=pending)
  const params = new URLSearchParams(location.search);
  if (params.get('status')) {
    document.getElementById('filter-status').value = params.get('status').toLowerCase();
  }
  if (params.get('formId')) {
    // Wait until the form dropdown is populated by the first response, then re-apply
    // (handled in renderResults below)
  }

  await loadSubmissions();
})();

async function loadSubmissions(forceFresh = false) {
  const list = document.getElementById('submissions-list');
  list.innerHTML = '<div class="loading">Loading submissions…</div>';

  const params = new URLSearchParams();
  const formId = document.getElementById('filter-form').value;
  const status = document.getElementById('filter-status').value;
  const startDate = document.getElementById('filter-start').value;
  const endDate = document.getElementById('filter-end').value;
  const submitterEl = document.getElementById('filter-submitter');
  const submitter = submitterEl ? submitterEl.value : '';

  if (formId) params.set('formId', formId);
  if (status) params.set('status', status);
  if (startDate) params.set('startDate', startDate);
  if (endDate) params.set('endDate', endDate);
  if (submitter) params.set('submitter', submitter);

  if (forceFresh) {
    // Tell server to drop its cache
    try { await fetch('/ehs/api/submissions/cache-clear', { method: 'POST' }); } catch {}
  }

  try {
    const data = await fetch(`/ehs/api/submissions?${params.toString()}`).then(r => {
      if (!r.ok) throw new Error('Failed to load');
      return r.json();
    });
    lastResponse = data;
    renderResults(data);
  } catch (err) {
    list.innerHTML = `<div class="empty-state">
      <span class="empty-state__icon">⚠️</span>
      <div class="empty-state__title">Failed to load submissions</div>
      <div class="empty-state__hint">${escapeHtml(err.message)}</div>
    </div>`;
  }
}

function renderResults(data) {
  // Update page heading based on admin status
  const isAdmin = !!data.isAdmin;
  document.getElementById('page-title').textContent = isAdmin ? 'All Submissions' : 'My Submissions';
  document.getElementById('page-subtitle').textContent = isAdmin
    ? 'Submissions from all users. Filter by form type, date or submitter.'
    : 'Forms you have submitted. Click any row to view the report.';

  // Populate the form-type filter dropdown
  const formSel = document.getElementById('filter-form');
  if (formSel.options.length <= 1 && data.forms?.length) {
    for (const f of data.forms) {
      const opt = document.createElement('option');
      opt.value = f.id;
      opt.textContent = `${f.title} (${f.code})`;
      formSel.appendChild(opt);
    }
  }

  // Show submitter filter only for admins
  const submWrap = document.getElementById('filter-submitter-wrap');
  if (isAdmin) {
    submWrap.style.display = '';
    const submSel = document.getElementById('filter-submitter');
    const currentVal = submSel.value;
    submSel.innerHTML = '<option value="">All users</option>' +
      data.submitters.map(s => `<option value="${escapeAttr(s.email)}">${escapeHtml(s.name)} — ${escapeHtml(s.email)}</option>`).join('');
    submSel.value = currentVal;
  }

  // Render status counts bar
  const countsBar = document.getElementById('status-counts-bar');
  const counts = data.statusCounts || { all: 0, pending: 0, approved: 0, rejected: 0 };
  if (counts.all > 0) {
    countsBar.innerHTML = `
      <div class="status-counts">
        <div class="status-count" data-status=""><span class="num">${counts.all}</span><span class="label">Total</span></div>
        ${counts.pending > 0 ? `<div class="status-count status-count--pending" data-status="pending"><span class="num">${counts.pending}</span><span class="label">⏳ Pending</span></div>` : ''}
        ${counts.approved > 0 ? `<div class="status-count status-count--approved" data-status="approved"><span class="num">${counts.approved}</span><span class="label">✓ Approved</span></div>` : ''}
        ${counts.rejected > 0 ? `<div class="status-count status-count--rejected" data-status="rejected"><span class="num">${counts.rejected}</span><span class="label">✕ Rejected</span></div>` : ''}
      </div>`;
    // Make the chips clickable to switch the status filter
    countsBar.querySelectorAll('.status-count').forEach(chip => {
      chip.addEventListener('click', () => {
        document.getElementById('filter-status').value = chip.dataset.status;
        loadSubmissions();
      });
    });
  } else {
    countsBar.innerHTML = '';
  }

  // Render table
  const list = document.getElementById('submissions-list');
  if (!data.rows.length) {
    list.innerHTML = `<div class="empty-state">
      <span class="empty-state__icon">📭</span>
      <div class="empty-state__title">No submissions yet</div>
      <div class="empty-state__hint">${isAdmin ? 'No submissions match the current filters.' : "You haven't submitted any forms yet."}</div>
      <a href="/ehs/" class="btn-submit">Submit your first form →</a>
    </div>`;
    return;
  }

  const countText = data.truncated
    ? `Showing first ${data.rows.length} of ${data.total}+ submissions`
    : `${data.total} submission${data.total === 1 ? '' : 's'}`;

  const tableHtml = `
    <div class="results-count">${countText}</div>
    <div class="subs-table-wrap">
      <table class="subs-table">
        <thead>
          <tr>
            <th>Form</th>
            <th>Identifier</th>
            ${isAdmin ? '<th>Submitted By</th>' : ''}
            <th>Submitted At</th>
            <th>Status</th>
            <th style="text-align:right;">Actions</th>
          </tr>
        </thead>
        <tbody>
          ${data.rows.map(r => rowHtml(r, isAdmin)).join('')}
        </tbody>
      </table>
    </div>
  `;
  list.innerHTML = tableHtml;

  // Wire up View buttons
  list.querySelectorAll('[data-view-pdf]').forEach(btn => {
    btn.addEventListener('click', () => {
      const { formId, submissionId } = btn.dataset;
      const row = data.rows.find(r => r.formId === formId && r.submissionId === submissionId);
      if (row) openPdfModal(row);
    });
  });
}

function rowHtml(r, isAdmin) {
  const icon = FORM_ICONS[r.formId] || '📄';
  const status = (r.status || 'Approved').trim();
  const statusKey = status.toLowerCase(); // approved, rejected, pending
  const isApproved = statusKey === 'approved';
  const isRejected = statusKey === 'rejected';

  const statusPill = `<span class="status-pill status-pill--${statusKey}">${escapeHtml(status)}</span>`;

  // Build the meta line under the status pill (reviewer + reject reason)
  let statusMeta = '';
  if (r.reviewerName) {
    statusMeta += `<div style="font-size:11px;color:#777;margin-top:4px;">by ${escapeHtml(r.reviewerName)}</div>`;
  }
  if (isRejected && r.rejectReason) {
    statusMeta += `<div style="font-size:11px;color:#C0392B;margin-top:3px;font-style:italic;" title="${escapeAttr(r.rejectReason)}">"${escapeHtml(truncate(r.rejectReason, 40))}"</div>`;
  }

  // Actions depend on status
  let actionsHtml;
  if (isApproved) {
    actionsHtml = `
      <button type="button" class="btn-action btn-action--primary"
              data-view-pdf data-form-id="${escapeAttr(r.formId)}" data-submission-id="${escapeAttr(r.submissionId)}">
        👁 View
      </button>
      <a class="btn-action" download
         href="/ehs/api/pdf/${encodeURIComponent(r.formId)}/${encodeURIComponent(r.submissionId)}">
        ⬇
      </a>`;
  } else if (isRejected) {
    actionsHtml = `<span style="color:#C0392B;font-size:12px;font-weight:600;">No PDF (rejected)</span>`;
  } else {
    actionsHtml = `<span style="color:#8C6A00;font-size:12px;font-weight:600;">Awaiting approval</span>`;
  }

  return `
    <tr>
      <td>
        <div class="cell-form">
          <span class="cell-form__icon">${icon}</span>
          <div>
            <div>${escapeHtml(r.formTitle)}</div>
            <div style="margin-top:3px;"><span class="cell-form__code">${escapeHtml(r.formCode)}</span></div>
          </div>
        </div>
      </td>
      <td class="cell-key">
        ${r.keyLabel ? `<div class="cell-key__label">${escapeHtml(r.keyLabel)}</div>` : ''}
        <div>${escapeHtml(r.keyValue || '—')}</div>
        <div style="font-size:10px;color:#999;margin-top:2px;">${escapeHtml(r.submissionId)}</div>
      </td>
      ${isAdmin ? `<td class="cell-submitter">
        <div class="cell-submitter__name">${escapeHtml(r.submittedByName || '—')}</div>
        <div class="cell-submitter__email">${escapeHtml(r.submittedByEmail || '')}</div>
      </td>` : ''}
      <td class="cell-date">${escapeHtml(formatDate(r.submittedAt))}</td>
      <td>
        ${statusPill}
        ${statusMeta}
      </td>
      <td>
        <div class="cell-actions">
          ${actionsHtml}
        </div>
      </td>
    </tr>
  `;
}

function openPdfModal(row) {
  document.getElementById('pdf-modal-code').textContent = row.formCode;
  document.getElementById('pdf-modal-title').textContent = row.formTitle;
  document.getElementById('pdf-modal-meta').textContent =
    `${row.submittedByName || ''} · ${formatDate(row.submittedAt)} · ID: ${row.submissionId}`;

  const inlineUrl = `/ehs/api/pdf/${encodeURIComponent(row.formId)}/${encodeURIComponent(row.submissionId)}?inline=1`;
  const downloadUrl = `/ehs/api/pdf/${encodeURIComponent(row.formId)}/${encodeURIComponent(row.submissionId)}`;

  document.getElementById('pdf-iframe').src = inlineUrl;
  document.getElementById('pdf-download').href = downloadUrl;

  document.getElementById('pdf-modal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function closePdfModal() {
  document.getElementById('pdf-modal').style.display = 'none';
  document.getElementById('pdf-iframe').src = 'about:blank';
  document.body.style.overflow = '';
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function formatDate(s) {
  if (!s) return '—';
  let str = String(s);
  // Detect ISO UTC format (has T separator and ends with Z) and convert to IST display
  if (/^\d{4}-\d{2}-\d{2}T/.test(str)) {
    const d = new Date(str);
    if (!isNaN(d)) {
      return d.toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true,
      });
    }
  }
  // Already-IST string ("YYYY-MM-DD HH:MM:SS") — display as-is
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})[\sT](\d{2}):(\d{2})/);
  if (!m) return s;
  const [, yyyy, mm, dd, hh, min] = m;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  let h = parseInt(hh, 10);
  const ampm = h >= 12 ? 'pm' : 'am';
  h = h % 12 || 12;
  return `${dd} ${months[parseInt(mm, 10) - 1]} ${yyyy}, ${String(h).padStart(2, '0')}:${min} ${ampm}`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}
function escapeAttr(s) {
  return escapeHtml(s);
}
function truncate(s, n) {
  s = String(s ?? '');
  return s.length > n ? s.slice(0, n) + '…' : s;
}
