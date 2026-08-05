// Dashboard — renders a tile per form, grouped by category. Shows
// approvals badge if the user is an approver/admin.

(async function init() {
  const [me, forms] = await Promise.all([
    fetch('/ehs/api/me').then(r => r.json()),
    fetch('/ehs/api/forms').then(r => r.json()),
  ]);

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
  if (me.isAdmin) {
    document.getElementById('admin-link').style.display = '';
    document.getElementById('charts-link').style.display = '';
    document.getElementById('settings-link').style.display = '';
  }
  if (me.isApprover) {
    document.getElementById('approvals-link').style.display = '';
    // Fetch pending count and update badge
    fetch('/ehs/api/approvals')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        const badge = document.getElementById('approvals-badge');
        if (data.count > 0) {
          badge.textContent = String(data.count);
          badge.style.display = '';
        }
        // Also show a status strip on the page
        if (data.count > 0) {
          document.getElementById('status-strip').innerHTML = `
            <div class="status-strip status-strip--warn">
              <span>⏳ <strong>${data.count}</strong> submission${data.count === 1 ? '' : 's'} waiting for your approval.</span>
              <a href="/ehs/approvals" class="btn-action btn-action--primary">Review now →</a>
            </div>`;
        }
      })
      .catch(() => {});
  }

  // Fetch this user's own pending count (separate from approver count)
  fetch('/ehs/api/my-pending-count')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      const link = document.getElementById('my-pending-link');
      const badge = document.getElementById('my-pending-badge');
      if (data.count > 0) {
        link.style.display = '';
        badge.textContent = String(data.count);
      }
    })
    .catch(() => {});

  // Group forms
  const general = forms.filter(f => f.category === 'general');
  const equipment = forms.filter(f => f.category === 'equipment');

  document.getElementById('general-count').textContent = `${general.length} forms`;
  document.getElementById('equipment-count').textContent = `${equipment.length} forms`;

  document.getElementById('general-grid').innerHTML = general.map(tileHtml).join('');
  document.getElementById('equipment-grid').innerHTML = equipment.map(tileHtml).join('');
})();

function tileHtml(f) {
  return `
    <a class="tile" href="/ehs/form/${f.id}">
      <div class="tile__icon">${f.icon}</div>
      <div class="tile__code">${f.code}</div>
      <h4 class="tile__title">${escapeHtml(f.title)}</h4>
      <div class="tile__cta">Open form</div>
    </a>
  `;
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}
