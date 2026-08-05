// ============================================================================
// Form page — renders any form by ID, handles submission with photo uploads.
// ============================================================================

const formId = location.pathname.split('/').pop();
const photoState = {
  fields: {},     // { fieldKey: [File, File, ...] }
  checklist: {},  // { itemIndex: [File] }
};

let me = null;
let form = null;
let activeProjects = [];

(async function init() {
  try {
    const [meRes, formRes, projectsRes] = await Promise.all([
      fetch('/ehs/api/me').then(r => r.json()),
      fetch(`/ehs/api/forms/${encodeURIComponent(formId)}`).then(r => {
        if (!r.ok) throw new Error('Form not found');
        return r.json();
      }),
      fetch('/ehs/api/projects').then(r => r.ok ? r.json() : []).catch(() => []),
    ]);
    me = meRes;
    form = formRes;
    activeProjects = projectsRes;
    console.log('[form.js] loaded form:', form.id, '- projects available:', activeProjects.length);
    if (activeProjects.length === 0) {
      console.warn('[form.js] NO PROJECTS returned from /ehs/api/projects — dropdown will fall back to text input.');
    }
  } catch (err) {
    document.getElementById('form-mount').innerHTML = `<p>Form not found.</p>`;
    return;
  }

  // User pill
  document.getElementById('user-pill').innerHTML = `
    <div class="app-header__user">
      <img src="${me.picture || ''}" alt="">
      <div>
        <div class="app-header__user-name">${escapeHtml(me.name)}</div>
        <div class="app-header__user-email">${escapeHtml(me.email)}</div>
      </div>
    </div>
  `;

  renderForm();
})();

function renderForm() {
  const mount = document.getElementById('form-mount');
  mount.innerHTML = `
    <div class="form-shell">
      <div class="form-header">
        <div class="form-header__code">${escapeHtml(form.code)}</div>
        <h1 class="form-header__title">${escapeHtml(form.title)}</h1>
      </div>

      <div class="form-section">
        <h3 class="form-section__title">Form Details</h3>
        <div class="field-grid" id="fields-grid"></div>
      </div>

      ${form.checklist ? `
        <div class="form-section">
          <h3 class="form-section__title">Inspection Checklist</h3>
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
              <tbody id="checklist-body"></tbody>
            </table>
          </div>
        </div>
      ` : ''}

      <div class="form-footer">
        <button type="button" class="btn-secondary" onclick="location.href='/ehs/'">Cancel</button>
        <button type="button" class="btn-submit" id="submit-btn">Submit Form →</button>
      </div>
    </div>
  `;

  renderFields();
  if (form.checklist) renderChecklist();

  document.getElementById('submit-btn').addEventListener('click', submitForm);
}

function renderFields() {
  const grid = document.getElementById('fields-grid');
  grid.innerHTML = form.fields.map(f => renderField(f)).join('');

  // Wire up photo capture buttons
  for (const f of form.fields) {
    if (f.type === 'photo') wirePhotoField(f);
  }
}

function renderField(f) {
  // Defensive: if a project_name or site_name field still arrives as type 'text'
  // (e.g. server's forms-config.js didn't deploy or browser is showing a stale form),
  // force-render the project dropdown anyway. This guarantees the dropdown shows up
  // even if upstream config got out of sync.
  if (f.type === 'text' && (f.key === 'project_name' || f.key === 'site_name')) {
    console.warn('[form.js] field', f.key, 'arrived as text — forcing project dropdown');
    f = Object.assign({}, f, { type: 'project' });
  }
  const required = f.required ? '<span class="req">*</span>' : '';
  const isFull = ['textarea', 'photo'].includes(f.type);
  const wrap = (inner) => `
    <div class="${isFull ? 'field--full' : ''}">
      <label class="field-label">${escapeHtml(f.label)}${required}</label>
      ${inner}
    </div>
  `;

  switch (f.type) {
    case 'text':
    case 'tel':
      return wrap(`<input class="field-input" type="${f.type === 'tel' ? 'tel' : 'text'}"
                   name="${f.key}" ${f.required ? 'required' : ''}
                   ${f.pattern ? `pattern="${f.pattern}"` : ''}>`);
    case 'number':
      return wrap(`<input class="field-input" type="number" name="${f.key}"
                   ${f.required ? 'required' : ''} ${f.min ? `min="${f.min}"` : ''}>`);
    case 'date':
      return wrap(`<input class="field-input" type="date" name="${f.key}"
                   value="${f.autofill === 'today' ? todayStr() : ''}"
                   ${f.required ? 'required' : ''}>`);
    case 'time':
      return wrap(`<input class="field-input" type="time" name="${f.key}"
                   value="${f.autofill === 'now' ? nowTimeStr() : ''}"
                   ${f.required ? 'required' : ''}>`);
    case 'textarea':
      return wrap(`<textarea class="field-textarea" name="${f.key}"
                   ${f.required ? 'required' : ''}></textarea>`);
    case 'select':
      return wrap(`<select class="field-select" name="${f.key}" ${f.required ? 'required' : ''}>
        <option value="">— select —</option>
        ${f.options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('')}
      </select>`);
    case 'project':
      // Dropdown of active projects (managed by admins in Settings)
      // Falls back to a free-text field if no projects are configured yet.
      if (!activeProjects || activeProjects.length === 0) {
        return wrap(`
          <input class="field-input" type="text" name="${f.key}"
                 placeholder="Project name (no projects configured — ask admin)"
                 ${f.required ? 'required' : ''}>
        `);
      }
      return wrap(`
        <select class="field-select" name="${f.key}" ${f.required ? 'required' : ''}>
          <option value="">— select project —</option>
          ${activeProjects.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('')}
        </select>
        ${me.isAdmin ? `<div class="field-hint" style="margin-top:6px;font-size:11px;">
          <a href="/ehs/admin-settings" target="_blank" style="color:#005B96;">Manage projects →</a>
        </div>` : ''}
      `);
    case 'radio':
      return wrap(`<div class="field-radio-group">
        ${f.options.map(o => `
          <label class="field-radio-pill">
            <input type="radio" name="${f.key}" value="${escapeHtml(o)}" ${f.required ? 'required' : ''}>
            ${escapeHtml(o)}
          </label>
        `).join('')}
      </div>`);
    case 'inspector':
      // Prefilled editable textbox — defaults to logged-in user's name,
      // but can be edited (e.g., if someone fills the form on behalf of another inspector).
      return wrap(`
        <input class="field-input" type="text" name="${f.key}"
               value="${escapeHtml(me.name || '')}"
               placeholder="Inspector name">
      `);
    case 'photo':
      return wrap(`
        <div class="field-photo">
          <div class="field-photo__buttons">
            <button type="button" class="btn-photo" data-photo-trigger="${f.key}" data-mode="camera">📷 Capture</button>
            <button type="button" class="btn-photo btn-photo--secondary" data-photo-trigger="${f.key}" data-mode="library">📁 Upload</button>
          </div>
          <input type="file" accept="image/*" capture="environment"
                 id="photo-input-${f.key}-camera" style="display:none"
                 ${f.multiple ? 'multiple' : ''}>
          <input type="file" accept="image/*"
                 id="photo-input-${f.key}-library" style="display:none"
                 ${f.multiple ? 'multiple' : ''}>
          <p class="field-photo__hint">${f.multiple ? 'You can add multiple photos.' : 'One photo.'}</p>
          <div class="field-photo-preview" id="photo-preview-${f.key}"></div>
        </div>
      `);
    default:
      return wrap(`<input class="field-input" type="text" name="${f.key}">`);
  }
}

function wirePhotoField(f) {
  document.querySelectorAll(`[data-photo-trigger="${f.key}"]`).forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      document.getElementById(`photo-input-${f.key}-${mode}`).click();
    });
  });
  ['camera', 'library'].forEach(mode => {
    const input = document.getElementById(`photo-input-${f.key}-${mode}`);
    input.addEventListener('change', e => {
      const files = Array.from(e.target.files || []);
      if (!f.multiple) photoState.fields[f.key] = [];
      photoState.fields[f.key] = (photoState.fields[f.key] || []).concat(files);
      renderPhotoPreview('field', f.key, photoState.fields[f.key]);
      e.target.value = ''; // allow re-selecting same file
    });
  });
}

// Inspector field — show/hide custom input
document.addEventListener('change', (e) => {
  if (e.target.matches('select[id$="__select"]')) {
    const baseId = e.target.id.replace('__select', '');
    const custom = document.getElementById(`${baseId}__custom`);
    if (custom) custom.style.display = e.target.value === '__other__' ? '' : 'none';
  }
});

function renderChecklist() {
  const tbody = document.getElementById('checklist-body');
  tbody.innerHTML = form.checklist.map((param, i) => `
    <tr>
      <td class="col-no">${i + 1}</td>
      <td>${escapeHtml(param)}</td>
      <td class="col-result">
        <div class="yn-pill-group">
          <label class="yn-pill yn-pill--yes">
            <input type="radio" name="cl-${i}" value="YES"> YES
          </label>
          <label class="yn-pill yn-pill--no">
            <input type="radio" name="cl-${i}" value="NO"> NO
          </label>
        </div>
      </td>
      <td class="col-remarks">
        <textarea class="field-textarea field-textarea--remarks" name="cl-remarks-${i}"
                  placeholder="Remarks (optional)"></textarea>
      </td>
      <td class="col-photo">
        <button type="button" class="checklist-photo-btn" data-cl-photo="${i}">📷 Photo</button>
        <input type="file" accept="image/*" capture="environment"
               id="cl-photo-input-${i}" style="display:none;">
        <div id="cl-photo-preview-${i}"></div>
      </td>
    </tr>
  `).join('');

  // Wire up checklist photo buttons
  form.checklist.forEach((_, i) => {
    document.querySelector(`[data-cl-photo="${i}"]`).addEventListener('click', () => {
      document.getElementById(`cl-photo-input-${i}`).click();
    });
    document.getElementById(`cl-photo-input-${i}`).addEventListener('change', (e) => {
      const file = (e.target.files || [])[0];
      if (!file) return;
      photoState.checklist[i] = [file];
      renderPhotoPreview('checklist', i, [file]);
      e.target.value = '';
    });
  });
}

function renderPhotoPreview(kind, key, files) {
  const id = kind === 'field' ? `photo-preview-${key}` : `cl-photo-preview-${key}`;
  const el = document.getElementById(id);
  el.innerHTML = files.map((f, idx) => `
    <div class="${kind === 'checklist' ? 'checklist-photo-thumb' : 'field-photo-preview-item'}"
         style="background-image:url('${URL.createObjectURL(f)}');">
      <button type="button" data-remove-photo="${kind}:${key}:${idx}">×</button>
    </div>
  `).join('');
  el.querySelectorAll('[data-remove-photo]').forEach(btn => {
    btn.addEventListener('click', () => {
      const [k, key2, idx] = btn.dataset.removePhoto.split(':');
      const arr = k === 'field' ? photoState.fields[key2] : photoState.checklist[key2];
      arr.splice(parseInt(idx, 10), 1);
      renderPhotoPreview(k, key2, arr);
    });
  });
}

// ----------------------------------------------------------------------------
// Submission
// ----------------------------------------------------------------------------

async function submitForm() {
  const errors = validate();
  if (errors.length) {
    toast(`Please fix: ${errors.join(', ')}`, 'error');
    return;
  }

  setLoader(true, 'Uploading photos and saving to OneDrive…');

  // Build fields object
  const fields = {};
  for (const f of form.fields) {
    if (f.type === 'photo') continue;
    if (f.type === 'radio') {
      const checked = document.querySelector(`input[name="${f.key}"]:checked`);
      fields[f.key] = checked ? checked.value : '';
    } else {
      const el = document.querySelector(`[name="${f.key}"]`);
      fields[f.key] = el ? el.value.trim() : '';
    }
  }

  // Build checklist array
  const checklist = (form.checklist || []).map((_, i) => {
    const result = document.querySelector(`input[name="cl-${i}"]:checked`);
    const remarks = document.querySelector(`[name="cl-remarks-${i}"]`);
    return {
      result: result ? result.value : '',
      remarks: remarks ? remarks.value : '',
    };
  });

  // Build FormData
  const fd = new FormData();
  fd.append('data', JSON.stringify({ fields, checklist }));
  for (const [k, files] of Object.entries(photoState.fields)) {
    files.forEach(file => fd.append(`photo:${k}`, file, file.name));
  }
  for (const [k, files] of Object.entries(photoState.checklist)) {
    files.forEach(file => fd.append(`photo:checklist:${k}`, file, file.name));
  }

  try {
    const resp = await fetch(`/ehs/api/submit/${encodeURIComponent(formId)}`, {
      method: 'POST',
      body: fd,
    });
    const json = await resp.json();
    if (!resp.ok) throw new Error(json.error || 'Submission failed');

    setLoader(false);
    toast(
      `<strong>✓ Submitted for approval</strong><br>` +
      `ID: ${json.submissionId}<br>` +
      `Awaiting review by Varadharaj or Nirmal Kumar.<br>` +
      `<a href="/ehs/submissions" style="color:#fff;text-decoration:underline;">Track status in My Submissions →</a>`,
      'success', 9000,
    );
    setTimeout(() => location.href = '/ehs/', 4000);
  } catch (err) {
    setLoader(false);
    console.error(err);
    const msg = err.message || 'Submission failed';
    // Friendly hint for OneDrive errors
    if (/user not found|invalid_user|insufficient.*priv/i.test(msg)) {
      toast(
        `<strong>OneDrive storage error.</strong><br>` +
        `${escapeHtml(msg)}<br><br>` +
        `Your form was prepared but couldn't be saved to OneDrive. ` +
        `Open <a href="/ehs/debug/onedrive" target="_blank" style="color:#fff;text-decoration:underline;">/ehs/debug/onedrive</a> ` +
        `to see exactly what's wrong (admin only).`,
        'error', 15000,
      );
    } else {
      toast(escapeHtml(msg), 'error', 8000);
    }
  }
}

function validate() {
  const errors = [];
  for (const f of form.fields) {
    if (!f.required) continue;
    if (f.type === 'photo') {
      if (!(photoState.fields[f.key] || []).length) errors.push(f.label);
    } else if (f.type === 'radio') {
      if (!document.querySelector(`input[name="${f.key}"]:checked`)) errors.push(f.label);
    } else {
      const el = document.querySelector(`[name="${f.key}"]`);
      if (!el || !el.value.trim()) errors.push(f.label);
    }
  }
  return errors;
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function nowTimeStr() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}
function setLoader(on, text) {
  const l = document.getElementById('loader');
  l.classList.toggle('active', on);
  if (text) document.getElementById('loader-text').textContent = text;
}
function toast(msgHtml, kind = 'success', duration = 4000) {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const t = document.createElement('div');
  t.className = `toast toast--${kind}`;
  t.innerHTML = msgHtml;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), duration);
}
