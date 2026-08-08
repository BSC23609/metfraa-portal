// ============================================================================
// Approval review page — renders an editable form for one pending submission
// ============================================================================

// The reference app served this at /approvals/{formId}/{subId}, so it read
// fixed indexes 1 and 2. Inside the portal the path is
// /ehs/approvals/{formId}/{subId}, which shifted everything by one and made
// formId read as the literal 'approvals'. Anchor on the segment instead of
// counting from the left, so it works at any mount point.
const pathParts = location.pathname.split('/').filter(Boolean);
const _i = pathParts.indexOf('approvals');
const formId = pathParts[_i + 1];
const subId = pathParts[_i + 2];

let me = null;
let form = null;
let submission = null;

(async function init() {
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
    document.getElementById('mount').innerHTML = `<p>Not authorised.</p>`;
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

  try {
    const data = await fetch(`/ehs/api/approvals/${encodeURIComponent(formId)}/${encodeURIComponent(subId)}`).then(r => {
      if (!r.ok) return r.json().then(j => Promise.reject(new Error(j.error || `HTTP ${r.status}`)));
      return r.json();
    });
    form = data.form;
    submission = data.submission;
    render();
  } catch (err) {
    document.getElementById('mount').innerHTML = `
      <div class="empty-state">
        <span class="empty-state__icon">⚠️</span>
        <div class="empty-state__title">Could not load submission</div>
        <div class="empty-state__hint">${escapeHtml(err.message)}</div>
        <a href="/ehs/approvals" class="btn-submit">Back to list</a>
      </div>`;
  }
})();

function render() {
  const fields = submission.fields || {};
  const checklist = submission.checklist || [];

  document.getElementById('mount').innerHTML = `
    <a href="/ehs/approvals" class="form-back">← Back to pending list</a>
    <div class="review-shell">
      <div class="review-header">
        <div class="review-header__code">${escapeHtml(form.code)}</div>
        <h1 class="review-header__title">${escapeHtml(form.title)}</h1>
        <div class="review-header__meta">
          <div><strong>Submitted by:</strong> ${escapeHtml(submission.user.name)} (${escapeHtml(submission.user.email)})</div>
          <div><strong>Submitted at:</strong> ${escapeHtml(formatDate(submission.submittedAt))}</div>
          <div><strong>Submission ID:</strong> ${escapeHtml(submission.submissionId)}</div>
        </div>
        <div class="review-banner">
          ✏️ All fields below are editable. Your changes will be recorded in the audit log when you approve.
        </div>
      </div>

      <div class="review-section">
        <h3 class="review-section__title">Form Details</h3>
        <div class="review-grid" id="fields-grid"></div>
      </div>

      ${form.checklist ? `
        <div class="review-section">
          <h3 class="review-section__title">Inspection Checklist</h3>
          <div id="checklist-mount"></div>
        </div>` : ''}

      <div class="review-actions">
        <button class="btn-secondary" type="button" onclick="location.href='/ehs/approvals'">Cancel</button>
        <button class="btn-reject" type="button" id="btn-reject">✕ Reject</button>
        <button class="btn-approve" type="button" id="btn-approve">✓ Approve &amp; Generate PDF</button>
      </div>
    </div>`;

  renderFields(fields);
  if (form.checklist) renderChecklist(checklist);

  document.getElementById('btn-approve').addEventListener('click', doApprove);
  document.getElementById('btn-reject').addEventListener('click', openRejectModal);

  // Reject modal handlers
  document.getElementById('reject-cancel').addEventListener('click', closeRejectModal);
  document.getElementById('reject-modal-overlay').addEventListener('click', closeRejectModal);
  document.getElementById('reject-confirm').addEventListener('click', doReject);
}

function renderFields(values) {
  const grid = document.getElementById('fields-grid');
  grid.innerHTML = form.fields.map(f => renderField(f, values[f.key])).join('');
}

function renderField(f, value) {
  const isFull = ['textarea', 'photo'].includes(f.type);
  const wrap = (inner) => `
    <div class="${isFull ? 'review-field--full' : 'review-field'}">
      <label class="review-label">${escapeHtml(f.label)}</label>
      ${inner}
    </div>`;
  const v = value === undefined ? '' : value;

  switch (f.type) {
    case 'photo':
      return wrap(renderPhotoField(f));
    case 'textarea':
      return wrap(`<textarea class="review-input" name="${f.key}" rows="3">${escapeHtml(v)}</textarea>`);
    case 'select':
      return wrap(`<select class="review-input" name="${f.key}">
        ${(f.options || []).map(o => `<option value="${escapeHtml(o)}" ${o === v ? 'selected' : ''}>${escapeHtml(o)}</option>`).join('')}
      </select>`);
    case 'radio':
      return wrap(`<div class="review-radio-group">
        ${(f.options || []).map(o => `
          <label class="review-radio-pill">
            <input type="radio" name="${f.key}" value="${escapeHtml(o)}" ${o === v ? 'checked' : ''}>
            <span>${escapeHtml(o)}</span>
          </label>`).join('')}
      </div>`);
    case 'inspector':
    case 'text':
    case 'tel':
      return wrap(`<input class="review-input" type="${f.type === 'tel' ? 'tel' : 'text'}" name="${f.key}" value="${escapeHtml(v)}">`);
    case 'number':
      return wrap(`<input class="review-input" type="number" name="${f.key}" value="${escapeHtml(v)}">`);
    case 'date':
      return wrap(`<input class="review-input" type="date" name="${f.key}" value="${escapeHtml(v)}">`);
    case 'time':
      return wrap(`<input class="review-input" type="time" name="${f.key}" value="${escapeHtml(v)}">`);
    default:
      return wrap(`<input class="review-input" type="text" name="${f.key}" value="${escapeHtml(v)}">`);
  }
}

function renderPhotoField(f) {
  const photos = (submission.photos?.fields || {})[f.key] || [];
  if (photos.length === 0) {
    return `<div class="review-photos-empty">— no photo —</div>`;
  }
  return `<div class="review-photos">
    ${photos.map(p => photoThumbnailHtml(p)).join('')}
  </div>`;
}

function photoThumbnailHtml(p) {
  const url = `/ehs/api/approvals/${encodeURIComponent(formId)}/${encodeURIComponent(subId)}/photo/${encodeURIComponent(p.filename)}`;
  return `<a href="${url}" target="_blank" class="review-photo">
    <img src="${url}" alt="${escapeHtml(p.filename)}" loading="lazy">
  </a>`;
}

function renderChecklist(values) {
  const tbody = form.checklist.map((param, i) => {
    const item = values[i] || {};
    const photos = (submission.photos?.checklist || {})[i] || [];
    return `
      <tr>
        <td class="col-no">${i + 1}</td>
        <td>${escapeHtml(param)}</td>
        <td class="col-result">
          <div class="yn-pill-group">
            <label class="yn-pill yn-pill--yes">
              <input type="radio" name="cl-${i}" value="YES" ${item.result === 'YES' ? 'checked' : ''}> YES
            </label>
            <label class="yn-pill yn-pill--no">
              <input type="radio" name="cl-${i}" value="NO" ${item.result === 'NO' ? 'checked' : ''}> NO
            </label>
          </div>
        </td>
        <td class="col-remarks">
          <textarea class="review-input" name="cl-remarks-${i}" rows="2">${escapeHtml(item.remarks || '')}</textarea>
        </td>
        <td class="col-photo">
          ${photos.length > 0
            ? photos.map(p => photoThumbnailHtml(p)).join('')
            : '<span style="color:#999;font-size:12px;">—</span>'}
        </td>
      </tr>`;
  }).join('');

  document.getElementById('checklist-mount').innerHTML = `
    <div style="overflow-x:auto;">
      <table class="checklist-table">
        <thead>
          <tr>
            <th class="col-no">#</th>
            <th>Parameter</th>
            <th class="col-result">Result</th>
            <th class="col-remarks">Remarks</th>
            <th class="col-photo">Photo</th>
          </tr>
        </thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>`;
}

// ----------------------------------------------------------------------------
// Collect edits and submit
// ----------------------------------------------------------------------------

function collectEditedData() {
  const fields = {};
  for (const f of form.fields) {
    if (f.type === 'photo') continue;
    if (f.type === 'radio') {
      const checked = document.querySelector(`input[name="${f.key}"]:checked`);
      fields[f.key] = checked ? checked.value : '';
    } else {
      const el = document.querySelector(`[name="${f.key}"]`);
      fields[f.key] = el ? el.value : '';
    }
  }
  const checklist = (form.checklist || []).map((_, i) => {
    const result = document.querySelector(`input[name="cl-${i}"]:checked`);
    const remarks = document.querySelector(`[name="cl-remarks-${i}"]`);
    return {
      result: result ? result.value : '',
      remarks: remarks ? remarks.value : '',
    };
  });
  return { fields, checklist };
}

async function doApprove() {
  setLoader(true, 'Approving and generating PDF…');
  try {
    const body = collectEditedData();
    const resp = await fetch(`/ehs/api/approvals/${encodeURIComponent(formId)}/${encodeURIComponent(subId)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const json = await resp.json();
    if (!resp.ok) throw new Error(json.error || 'Approval failed');
    setLoader(false);
    alert(`Approved! PDF generated.${json.editsCount > 0 ? ` (${json.editsCount} edit${json.editsCount === 1 ? '' : 's'} recorded)` : ''}`);
    location.href = '/ehs/approvals';
  } catch (err) {
    setLoader(false);
    alert('Failed: ' + err.message);
  }
}

function openRejectModal() {
  document.getElementById('reject-modal').style.display = 'flex';
  document.getElementById('reject-reason').focus();
}
function closeRejectModal() {
  document.getElementById('reject-modal').style.display = 'none';
  document.getElementById('reject-reason').value = '';
}

async function doReject() {
  const reason = document.getElementById('reject-reason').value.trim();
  if (!reason) {
    alert('Please provide a rejection reason.');
    return;
  }
  closeRejectModal();
  setLoader(true, 'Rejecting submission…');
  try {
    const resp = await fetch(`/ehs/api/approvals/${encodeURIComponent(formId)}/${encodeURIComponent(subId)}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    const json = await resp.json();
    if (!resp.ok) throw new Error(json.error || 'Rejection failed');
    setLoader(false);
    alert('Submission rejected.');
    location.href = '/ehs/approvals';
  } catch (err) {
    setLoader(false);
    alert('Failed: ' + err.message);
  }
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function formatDate(s) {
  if (!s) return '—';
  let str = String(s);
  // Detect ISO format (has T separator) — old pending submissions stored ISO timestamps
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

function setLoader(on, text) {
  const l = document.getElementById('loader');
  l.classList.toggle('active', on);
  if (text) document.getElementById('loader-text').textContent = text;
}
