// Approvals list — show pending submissions, click to review

const FORM_ICONS = {
  toolbox: '🛠️', induction: '👷', 'ehs-audit': '🔍', incident: '⚠️', 'hse-meeting': '👥',
  'permit-record': '📋',
  'portable-grinding-machine': '⚙️', 'gas-welding-set': '🔥', 'aerial-boomlift': '🏗️',
  'air-compressor': '💨', 'arc-welding-machine': '⚡', 'cutting-machine': '✂️',
  'first-aid-box': '🏥', generator: '🔋', ladder: '🪜', 'mdb-panel': '🔌',
  'mobile-scaffolding': '🪟', 'scaffolding-cuplock': '🏗️', truck: '🚚',
  'labour-camp': '🏠', 'mobile-crane': '🏗️',
};

(async function init() {
  let me;
  try {
    me = await fetch('/ehs/api/me').then(r => {
      if (!r.ok) throw new Error('Not authenticated');
      return r.json();
    });
  } catch {
    location.href = '/auth/login';
    return;
  }

  if (!me.isApprover) {
    document.querySelector('main').innerHTML = `
      <div class="empty-state">
        <span class="empty-state__icon">🔒</span>
        <div class="empty-state__title">Not authorised</div>
        <div class="empty-state__hint">Only Varadharaj, Nirmal Kumar, or admins can view pending approvals.</div>
        <a href="/ehs/" class="btn-submit">Back to dashboard</a>
      </div>`;
    return;
  }

  document.getElementById('user-pill').innerHTML = `
    <div class="app-header__user">
      ${me.picture ? `<img src="${me.picture}" alt="">` : ''}
      <div>
        <div class="app-header__user-name">${escapeHtml(me.name)}</div>
        <div class="app-header__user-email">${escapeHtml(me.email)}</div>
      </div>
    </div>`;

  document.getElementById('refresh-btn').addEventListener('click', load);
  await load();
})();

async function load() {
  const list = document.getElementById('approvals-list');
  list.innerHTML = '<div class="loading">Loading pending submissions…</div>';
  try {
    const data = await fetch('/ehs/api/approvals').then(r => {
      if (!r.ok) throw new Error('Failed to load');
      return r.json();
    });
    render(data);
  } catch (err) {
    list.innerHTML = `<div class="empty-state">
      <span class="empty-state__icon">⚠️</span>
      <div class="empty-state__title">Failed to load</div>
      <div class="empty-state__hint">${escapeHtml(err.message)}</div>
    </div>`;
  }
}

function render(data) {
  const list = document.getElementById('approvals-list');
  if (!data.rows.length) {
    list.innerHTML = `<div class="empty-state">
      <span class="empty-state__icon">✅</span>
      <div class="empty-state__title">All caught up!</div>
      <div class="empty-state__hint">No submissions are waiting for approval right now.</div>
    </div>`;
    return;
  }

  list.innerHTML = `
    <div class="results-count">${data.count} pending submission${data.count === 1 ? '' : 's'}</div>
    <div class="subs-table-wrap">
      <table class="subs-table">
        <thead>
          <tr>
            <th>Form</th>
            <th>Identifier</th>
            <th>Submitted By</th>
            <th>Submitted At</th>
            <th style="text-align:right;">Action</th>
          </tr>
        </thead>
        <tbody>
          ${data.rows.map(r => rowHtml(r)).join('')}
        </tbody>
      </table>
    </div>`;
}

function rowHtml(r) {
  const icon = FORM_ICONS[r.formId] || '📄';
  return `
    <tr style="cursor:pointer;" onclick="location.href='/ehs/approvals/${encodeURIComponent(r.formId)}/${encodeURIComponent(r.submissionId)}'">
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
        <div>${escapeHtml(r.keyValue || '—')}</div>
        <div style="font-size:10px;color:#999;margin-top:2px;">${escapeHtml(r.submissionId)}</div>
      </td>
      <td class="cell-submitter">
        <div class="cell-submitter__name">${escapeHtml(r.submittedByName || '—')}</div>
        <div class="cell-submitter__email">${escapeHtml(r.submittedByEmail || '')}</div>
      </td>
      <td class="cell-date">${escapeHtml(formatDate(r.submittedAt))}</td>
      <td>
        <div class="cell-actions">
          <a class="btn-action btn-action--primary" href="/ehs/approvals/${encodeURIComponent(r.formId)}/${encodeURIComponent(r.submissionId)}">Review →</a>
        </div>
      </td>
    </tr>`;
}

function formatDate(s) {
  if (!s) return '—';
  let str = String(s);
  // Detect ISO format (has T separator) and convert to IST display
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
  // Master log timestamps are already IST in the format "YYYY-MM-DD HH:MM:SS"
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
