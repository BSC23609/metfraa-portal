// ============================================================================
// Admin Settings — Project management (CRUD)
// ============================================================================

let projects = [];
let editingId = null;

(async function init() {
  let user;
  try {
    user = await fetch('/ehs/api/me').then(r => {
      if (!r.ok) throw new Error('Not authenticated');
      return r.json();
    });
  } catch {
    location.href = '/auth/login';
    return;
  }

  if (!user.isAdmin) {
    document.querySelector('main').innerHTML = `
      <div class="empty-state">
        <span class="empty-state__icon">🔒</span>
        <div class="empty-state__title">Admin only</div>
        <div class="empty-state__hint">This page is restricted to admin users.</div>
        <a href="/ehs/" class="btn-submit">Back to dashboard</a>
      </div>`;
    return;
  }

  document.getElementById('user-pill').innerHTML = `
    <div class="app-header__user">
      ${user.picture ? `<img src="${user.picture}" alt="">` : ''}
      <div>
        <div class="app-header__user-name">${escapeHtml(user.name)}</div>
        <div class="app-header__user-email">${escapeHtml(user.email)}</div>
      </div>
    </div>`;

  // Wire up modal close handlers
  document.querySelectorAll('[data-modal-close]').forEach(el => {
    el.addEventListener('click', closeModal);
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  document.getElementById('add-btn').addEventListener('click', () => openAddModal());
  document.getElementById('modal-save').addEventListener('click', saveProject);

  await loadProjects();
})();

async function loadProjects() {
  const mount = document.getElementById('settings-mount');
  mount.innerHTML = '<div class="loading">Loading projects…</div>';
  try {
    projects = await fetch('/ehs/api/admin/projects').then(r => {
      if (!r.ok) return r.json().then(j => Promise.reject(new Error(j.error || `HTTP ${r.status}`)));
      return r.json();
    });
    render();
  } catch (err) {
    mount.innerHTML = `<div class="empty-state">
      <div class="empty-state__title">Failed to load</div>
      <div class="empty-state__hint">${escapeHtml(err.message)}</div>
    </div>`;
  }
}

function render() {
  const mount = document.getElementById('settings-mount');
  const active = projects.filter(p => p.active);
  const inactive = projects.filter(p => !p.active);

  mount.innerHTML = `
    <div class="settings-grid">
      <section class="settings-section">
        <div class="settings-section__head">
          <h3>Active Projects</h3>
          <span class="settings-count">${active.length}</span>
        </div>
        ${active.length === 0
          ? `<div class="empty-section">No active projects — click "Add Project" to create one.</div>`
          : `<div class="settings-list">${active.map(projectCard).join('')}</div>`
        }
      </section>

      <section class="settings-section">
        <div class="settings-section__head">
          <h3>Deactivated</h3>
          <span class="settings-count">${inactive.length}</span>
        </div>
        ${inactive.length === 0
          ? `<div class="empty-section" style="opacity:0.7;">No deactivated projects.</div>`
          : `<div class="settings-list">${inactive.map(projectCard).join('')}</div>`
        }
      </section>
    </div>
  `;

  // Wire up edit + delete buttons
  mount.querySelectorAll('[data-edit]').forEach(btn => {
    btn.addEventListener('click', () => openEditModal(btn.dataset.edit));
  });
  mount.querySelectorAll('[data-toggle]').forEach(btn => {
    btn.addEventListener('click', () => toggleActive(btn.dataset.toggle));
  });
  mount.querySelectorAll('[data-delete]').forEach(btn => {
    btn.addEventListener('click', () => deleteProject(btn.dataset.delete));
  });
}

function projectCard(p) {
  const aliasCount = (p.aliases || []).length;
  return `
    <div class="project-card ${p.active ? '' : 'project-card--inactive'}">
      <div class="project-card__main">
        <div class="project-card__name">${escapeHtml(p.name)}</div>
        <div class="project-card__meta">
          ${aliasCount > 0 ? `<span class="badge-mini">${aliasCount} alias${aliasCount === 1 ? '' : 'es'}</span>` : ''}
          ${p.aliases && p.aliases.length > 0
            ? `<span class="project-card__aliases">${p.aliases.map(a => escapeHtml(a)).join(' • ')}</span>`
            : '<span class="project-card__meta-empty">no aliases</span>'
          }
        </div>
      </div>
      <div class="project-card__actions">
        <button type="button" class="btn-action" data-edit="${escapeAttr(p.id)}">Edit</button>
        <button type="button" class="btn-action" data-toggle="${escapeAttr(p.id)}">
          ${p.active ? 'Deactivate' : 'Reactivate'}
        </button>
        <button type="button" class="btn-action btn-action--danger" data-delete="${escapeAttr(p.id)}">Delete</button>
      </div>
    </div>
  `;
}

// ----------------------------------------------------------------------------
// Modal handling
// ----------------------------------------------------------------------------

function openAddModal() {
  editingId = null;
  document.getElementById('modal-title').textContent = 'Add Project';
  document.getElementById('proj-name').value = '';
  document.getElementById('proj-aliases').value = '';
  document.getElementById('proj-active').checked = true;
  document.getElementById('proj-active').parentElement.parentElement.style.display = 'none'; // hide active toggle on add
  document.getElementById('modal-error').style.display = 'none';
  document.getElementById('project-modal').style.display = 'flex';
  setTimeout(() => document.getElementById('proj-name').focus(), 100);
}

function openEditModal(id) {
  const p = projects.find(x => x.id === id);
  if (!p) return;
  editingId = id;
  document.getElementById('modal-title').textContent = 'Edit Project';
  document.getElementById('proj-name').value = p.name;
  document.getElementById('proj-aliases').value = (p.aliases || []).join('\n');
  document.getElementById('proj-active').checked = !!p.active;
  document.getElementById('proj-active').parentElement.parentElement.style.display = '';
  document.getElementById('modal-error').style.display = 'none';
  document.getElementById('project-modal').style.display = 'flex';
  setTimeout(() => document.getElementById('proj-name').focus(), 100);
}

function closeModal() {
  document.getElementById('project-modal').style.display = 'none';
  editingId = null;
}

async function saveProject() {
  const name = document.getElementById('proj-name').value.trim();
  const aliasesText = document.getElementById('proj-aliases').value;
  const active = document.getElementById('proj-active').checked;
  const aliases = aliasesText.split('\n').map(a => a.trim()).filter(Boolean);

  if (!name) {
    showModalError('Project name is required');
    return;
  }

  const saveBtn = document.getElementById('modal-save');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';

  try {
    if (editingId) {
      await fetchOrThrow(`/ehs/api/admin/projects/${encodeURIComponent(editingId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, aliases, active }),
      });
    } else {
      await fetchOrThrow('/ehs/api/admin/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, aliases }),
      });
    }
    closeModal();
    await loadProjects();
  } catch (err) {
    showModalError(err.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save';
  }
}

async function toggleActive(id) {
  const p = projects.find(x => x.id === id);
  if (!p) return;
  try {
    await fetchOrThrow(`/ehs/api/admin/projects/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: !p.active }),
    });
    await loadProjects();
  } catch (err) {
    alert(err.message);
  }
}

async function deleteProject(id) {
  const p = projects.find(x => x.id === id);
  if (!p) return;
  if (!confirm(`Permanently delete "${p.name}"?\n\nThis only removes the project from the dropdown — historical submissions in the master logs are unaffected, but they will appear under "Other / Legacy" on charts unless you keep this project (deactivated) with its aliases configured.`)) return;
  try {
    await fetchOrThrow(`/ehs/api/admin/projects/${encodeURIComponent(id)}`, { method: 'DELETE' });
    await loadProjects();
  } catch (err) {
    alert(err.message);
  }
}

function showModalError(msg) {
  const el = document.getElementById('modal-error');
  el.textContent = msg;
  el.style.display = 'block';
}

async function fetchOrThrow(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || `HTTP ${r.status}`);
  }
  return r.json().catch(() => ({}));
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}
function escapeAttr(s) { return escapeHtml(s); }
