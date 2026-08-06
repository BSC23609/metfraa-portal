// ============================================================================
// Admin Charts — 5 bar charts for project/site breakdowns + summary tile.
//
//   1. Toolbox Talks         — vertical bars per project
//   2. Inductions            — vertical bars per project
//   3. EHS Audit             — grouped bars (unsafe acts + conditions) per project
//   4. Incidents/Accidents   — stacked bars (Major/Minor/Near Miss/Unspecified) per project
//   5. Permit Records        — vertical bars per site
//   6. Summary tile          — period totals at-a-glance
//
// View modes (page sizes):
//   1x1 -> 1 chart per page, 6 pages
//   2x1 -> 2 charts per page, 3 pages
//   2x2 -> 4 charts per page, 2 pages
//   3x2 -> all 6 on one page (default)
//
// Always-hidden: projects with "test" in the name (case-insensitive). The
// server filters them out before sending data.
// ============================================================================

let lastData = null;

// View mode state — persisted in localStorage
const VIEW_MODES = {
  '1x1': { perPage: 1, cols: 1 },
  '2x1': { perPage: 2, cols: 2 },
  '2x2': { perPage: 4, cols: 2 },
  '3x2': { perPage: 6, cols: 3 },
};
let viewMode = localStorage.getItem('chartsViewMode') || '3x2';
if (!VIEW_MODES[viewMode]) viewMode = '3x2';
let viewPage = 0;

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

  if (!me.isAdmin) {
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
      ${me.picture ? `<img src="${me.picture}" alt="">` : ''}
      <div>
        <div class="app-header__user-name">${escapeHtml(me.name)}</div>
        <div class="app-header__user-email">${escapeHtml(me.email)}</div>
      </div>
    </div>`;

  // Default range: this month
  applyPreset('this-month');

  // Event handlers
  document.getElementById('apply-range').addEventListener('click', () => loadCharts());
  document.getElementById('refresh-btn').addEventListener('click', () => loadCharts(true));
  document.getElementById('filter-project').addEventListener('change', () => loadCharts());

  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('preset-btn--active'));
      btn.classList.add('preset-btn--active');
      applyPreset(btn.dataset.preset);
      loadCharts();
    });
  });

  // View mode buttons — switch grid layout + reset to page 0
  document.querySelectorAll('.view-mode-btn').forEach(btn => {
    if (btn.dataset.view === viewMode) {
      btn.classList.add('view-mode-btn--active');
    } else {
      btn.classList.remove('view-mode-btn--active');
    }
    btn.addEventListener('click', () => {
      viewMode = btn.dataset.view;
      viewPage = 0;
      localStorage.setItem('chartsViewMode', viewMode);
      document.querySelectorAll('.view-mode-btn').forEach(b => b.classList.remove('view-mode-btn--active'));
      btn.classList.add('view-mode-btn--active');
      if (lastData) renderPage();
    });
  });

  // Pagination arrows
  document.getElementById('pager-prev').addEventListener('click', () => {
    if (viewPage > 0) { viewPage--; renderPage(); }
  });
  document.getElementById('pager-next').addEventListener('click', () => {
    const totalPages = Math.ceil(6 / VIEW_MODES[viewMode].perPage);
    if (viewPage < totalPages - 1) { viewPage++; renderPage(); }
  });

  await loadCharts();
})();

// Compute date range for each preset and set the input values
function applyPreset(preset) {
  const today = new Date();
  let start = new Date(today);
  let end = new Date(today);

  switch (preset) {
    case 'today':
      // start = end = today
      break;
    case 'yesterday':
      start.setDate(today.getDate() - 1);
      end.setDate(today.getDate() - 1);
      break;
    case 'this-week':
      // Week starts on Monday in India; getDay() returns 0=Sun..6=Sat
      const dayOfWeek = today.getDay();
      const daysToMon = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
      start.setDate(today.getDate() - daysToMon);
      break;
    case 'this-month':
      start.setDate(1);
      break;
    case 'this-year':
      start = new Date(today.getFullYear(), 0, 1);
      break;
    default:
      start.setDate(today.getDate() - 29);
  }

  document.getElementById('filter-start').value = formatYmd(start);
  document.getElementById('filter-end').value = formatYmd(end);
}

async function loadCharts(forceFresh = false) {
  const mount = document.getElementById('charts-mount');
  mount.innerHTML = '<div class="loading">Loading charts…</div>';

  const startDate = document.getElementById('filter-start').value;
  const endDate = document.getElementById('filter-end').value;
  if (!startDate || !endDate) {
    mount.innerHTML = '<div class="empty-state"><div class="empty-state__title">Pick a date range</div></div>';
    return;
  }
  if (startDate > endDate) {
    mount.innerHTML = '<div class="empty-state"><div class="empty-state__title">Invalid range</div><div class="empty-state__hint">Start date must be on or before end date.</div></div>';
    return;
  }

  if (forceFresh) {
    try { await fetch('/ehs/api/admin/charts/cache-clear', { method: 'POST' }); } catch {}
  }

  try {
    const params = new URLSearchParams({ startDate, endDate });
    const projectFilter = document.getElementById('filter-project').value;
    if (projectFilter) params.set('project', projectFilter);
    const data = await fetch(`/ehs/api/admin/charts?${params}`).then(r => {
      if (!r.ok) return r.json().then(j => Promise.reject(new Error(j.error || `HTTP ${r.status}`)));
      return r.json();
    });
    lastData = data;
    render(data);
  } catch (err) {
    mount.innerHTML = `<div class="empty-state">
      <span class="empty-state__icon">⚠️</span>
      <div class="empty-state__title">Failed to load</div>
      <div class="empty-state__hint">${escapeHtml(err.message)}</div>
    </div>`;
  }
}

function render(data) {
  const filterLabel = data.projectFilter ? ` · Filtered by: ${data.projectFilter}` : '';
  document.getElementById('range-subtitle').textContent =
    `${formatDateLong(data.range.startDate)} → ${formatDateLong(data.range.endDate)}${filterLabel}`;

  // Populate project filter dropdown (preserve current selection)
  const projectSelect = document.getElementById('filter-project');
  const currentSelection = projectSelect.value;
  const allProjects = data.availableProjects || [];
  projectSelect.innerHTML = '<option value="">All projects</option>' +
    allProjects
      .filter(p => p.active)
      .map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`)
      .join('') +
    (allProjects.some(p => !p.active)
      ? '<optgroup label="Deactivated">' +
        allProjects.filter(p => !p.active)
          .map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('') +
        '</optgroup>'
      : '');
  projectSelect.value = currentSelection || data.projectFilter || '';

  // Reset to first page when new data loads
  viewPage = 0;
  renderPage();
}

// Compose the 6 tile HTML strings — exposed so renderPage can build the current
// view-mode slice.
function buildAllTiles(data) {
  const totals = {
    tbt: sumCount(data.toolbox),
    induction: sumCount(data.induction),
    unsafeActs: (data.ehsAudit || []).reduce((s, d) => s + d.unsafeActs, 0),
    unsafeConditions: (data.ehsAudit || []).reduce((s, d) => s + d.unsafeConditions, 0),
    incidents: (data.incident || []).reduce((s, d) => s + d.total, 0),
    permits: sumCount(data.permitRecord),
  };

  return [
    chartSection({
      id: 'toolbox',
      title: 'Toolbox Talks',
      subtitle: 'TBTs per project',
      data: data.toolbox,
      total: totals.tbt,
    }),
    chartSection({
      id: 'induction',
      title: 'Inductions',
      subtitle: 'Inductions per project',
      data: data.induction,
      total: totals.induction,
    }),
    ehsAuditChartSection(data.ehsAudit),
    incidentChartSection(data.incident),
    chartSection({
      id: 'permit',
      title: 'Permit Records',
      subtitle: 'Permits per site',
      data: data.permitRecord,
      total: totals.permits,
      labelHeader: 'Site',
    }),
    summaryTile(totals, data),
  ];
}

// Render the currently-visible page slice based on viewMode + viewPage.
// Called when: new data loads, view mode changes, page changes.
function renderPage() {
  if (!lastData) return;
  const tiles = buildAllTiles(lastData);
  const perPage = VIEW_MODES[viewMode].perPage;
  const totalPages = Math.ceil(tiles.length / perPage);
  if (viewPage >= totalPages) viewPage = 0;

  const start = viewPage * perPage;
  const end = Math.min(start + perPage, tiles.length);
  const visible = tiles.slice(start, end);

  document.getElementById('charts-mount').innerHTML = `
    <div class="charts-grid" data-view="${viewMode}">
      ${visible.join('')}
    </div>
  `;

  // Update pager UI
  const pager = document.getElementById('view-pager');
  const status = document.getElementById('pager-status');
  if (totalPages > 1) {
    pager.style.display = '';
    status.textContent = `Page ${viewPage + 1} of ${totalPages}`;
    document.getElementById('pager-prev').disabled = viewPage === 0;
    document.getElementById('pager-next').disabled = viewPage === totalPages - 1;
  } else {
    pager.style.display = 'none';
  }
}

// ----------------------------------------------------------------------------
// Summary tile (6th slot) — at-a-glance totals
// ----------------------------------------------------------------------------

function summaryTile(t, data) {
  const projectCount = (data.availableProjects || []).filter(p => p.active).length;
  return `
    <section class="dash-section chart-section summary-tile">
      <div class="dash-section__head">
        <div>
          <h3>Summary</h3>
          <div class="chart-subtitle">Period totals across all forms</div>
        </div>
      </div>
      <div class="summary-grid">
        <div class="summary-cell summary-cell--blue">
          <div class="summary-cell__num">${t.tbt}</div>
          <div class="summary-cell__label">Toolbox Talks</div>
        </div>
        <div class="summary-cell summary-cell--blue">
          <div class="summary-cell__num">${t.induction}</div>
          <div class="summary-cell__label">Inductions</div>
        </div>
        <div class="summary-cell summary-cell--amber">
          <div class="summary-cell__num">${t.unsafeActs}</div>
          <div class="summary-cell__label">Unsafe Acts</div>
        </div>
        <div class="summary-cell summary-cell--red">
          <div class="summary-cell__num">${t.unsafeConditions}</div>
          <div class="summary-cell__label">Unsafe Conditions</div>
        </div>
        <div class="summary-cell summary-cell--red">
          <div class="summary-cell__num">${t.incidents}</div>
          <div class="summary-cell__label">Incidents</div>
        </div>
        <div class="summary-cell summary-cell--blue">
          <div class="summary-cell__num">${t.permits}</div>
          <div class="summary-cell__label">Permits</div>
        </div>
      </div>
      <div class="summary-footer">
        ${projectCount} active project${projectCount === 1 ? '' : 's'} tracked
      </div>
    </section>
  `;
}

// ----------------------------------------------------------------------------
// Single-metric chart (TBT, Induction, Permit) — vertical bars
// ----------------------------------------------------------------------------

function chartSection({ id, title, subtitle, data, total, labelHeader }) {
  const labelText = labelHeader || 'Project';
  if (!data || data.length === 0) {
    return emptySection(id, title, subtitle);
  }

  const maxVal = Math.max(1, ...data.map(d => d.count));
  const ySteps = niceMax(maxVal);

  // Chart dimensions — fixed viewBox, scales responsively
  const VB_W = 1000;
  const VB_H = 320;
  const M_TOP = 24;
  const M_BOTTOM = 100;   // room for rotated project labels
  const M_LEFT = 56;
  const M_RIGHT = 16;
  const PLOT_W = VB_W - M_LEFT - M_RIGHT;
  const PLOT_H = VB_H - M_TOP - M_BOTTOM;

  const barSlotW = PLOT_W / data.length;
  const barW = Math.min(48, Math.max(8, barSlotW * 0.6));

  // Y-axis lines + labels
  const yLines = [];
  for (let t = 0; t <= 4; t++) {
    const val = Math.round((ySteps / 4) * t);
    const y = M_TOP + PLOT_H - (val / ySteps) * PLOT_H;
    yLines.push(`<line x1="${M_LEFT}" y1="${y}" x2="${VB_W - M_RIGHT}" y2="${y}" stroke="#E5E5E5" stroke-width="1"/>`);
    yLines.push(`<text x="${M_LEFT - 8}" y="${y + 6}" text-anchor="end" font-size="20" fill="#999">${val}</text>`);
  }

  // Bars
  const bars = data.map((d, i) => {
    const cx = M_LEFT + i * barSlotW + barSlotW / 2;
    const barX = cx - barW / 2;
    const barH = (d.count / ySteps) * PLOT_H;
    const barY = M_TOP + PLOT_H - barH;

    const totalLabel = `<text x="${cx.toFixed(2)}" y="${(barY - 8).toFixed(2)}" text-anchor="middle" font-size="22" fill="#2A2A2A" font-weight="700">${d.count}</text>`;

    // Rotated project label — truncate aggressively for grid tiles
    const labelY = M_TOP + PLOT_H + 22;
    const truncatedLabel = truncateLabel(d.label, 14);
    const xLabel = `<text x="${cx.toFixed(2)}" y="${labelY}" text-anchor="end" font-size="20" fill="#2A2A2A" transform="rotate(-40 ${cx.toFixed(2)} ${labelY})">${escapeHtml(truncatedLabel)}</text>`;

    return `<g>
      <rect x="${barX.toFixed(2)}" y="${barY.toFixed(2)}" width="${barW.toFixed(2)}" height="${barH.toFixed(2)}" fill="#005B96" rx="2">
        <title>${escapeHtml(d.label)}: ${d.count}</title>
      </rect>
      ${totalLabel}
      ${xLabel}
    </g>`;
  }).join('');

  return `
    <section class="dash-section chart-section" id="chart-${id}">
      <div class="dash-section__head">
        <div>
          <h3>${escapeHtml(title)}</h3>
          <div class="chart-subtitle">${escapeHtml(subtitle)} · Total: <strong>${total}</strong></div>
        </div>
      </div>
      <div class="chart-wrap chart-wrap--tall">
        <svg viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="xMidYMid meet" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
          ${yLines.join('')}
          ${bars}
        </svg>
      </div>
    </section>
  `;
}

// ----------------------------------------------------------------------------
// EHS Audit chart — grouped bars (unsafe acts vs unsafe conditions)
// ----------------------------------------------------------------------------

function ehsAuditChartSection(data) {
  const title = 'EHS Audit';
  const subtitle = 'Unsafe Acts vs Unsafe Conditions per project';

  if (!data || data.length === 0) {
    return emptySection('ehs-audit', title, subtitle);
  }

  const maxVal = Math.max(1, ...data.flatMap(d => [d.unsafeActs, d.unsafeConditions]));
  const ySteps = niceMax(maxVal);

  const VB_W = 1000, VB_H = 360;
  const M_TOP = 24, M_BOTTOM = 110, M_LEFT = 56, M_RIGHT = 16;
  const PLOT_W = VB_W - M_LEFT - M_RIGHT;
  const PLOT_H = VB_H - M_TOP - M_BOTTOM;

  const groupSlotW = PLOT_W / data.length;
  const barW = Math.min(28, Math.max(4, groupSlotW * 0.35));
  const innerGap = 2;

  const yLines = [];
  for (let t = 0; t <= 4; t++) {
    const val = Math.round((ySteps / 4) * t);
    const y = M_TOP + PLOT_H - (val / ySteps) * PLOT_H;
    yLines.push(`<line x1="${M_LEFT}" y1="${y}" x2="${VB_W - M_RIGHT}" y2="${y}" stroke="#E5E5E5" stroke-width="1"/>`);
    yLines.push(`<text x="${M_LEFT - 8}" y="${y + 6}" text-anchor="end" font-size="20" fill="#999">${val}</text>`);
  }

  const bars = data.map((d, i) => {
    const cx = M_LEFT + i * groupSlotW + groupSlotW / 2;
    const leftBarX = cx - barW - innerGap / 2;
    const rightBarX = cx + innerGap / 2;

    const actsH = (d.unsafeActs / ySteps) * PLOT_H;
    const condH = (d.unsafeConditions / ySteps) * PLOT_H;
    const actsY = M_TOP + PLOT_H - actsH;
    const condY = M_TOP + PLOT_H - condH;

    const actsLabel = d.unsafeActs > 0
      ? `<text x="${(leftBarX + barW / 2).toFixed(2)}" y="${(actsY - 8).toFixed(2)}" text-anchor="middle" font-size="18" fill="#C77A00" font-weight="700">${d.unsafeActs}</text>` : '';
    const condLabel = d.unsafeConditions > 0
      ? `<text x="${(rightBarX + barW / 2).toFixed(2)}" y="${(condY - 8).toFixed(2)}" text-anchor="middle" font-size="18" fill="#C0392B" font-weight="700">${d.unsafeConditions}</text>` : '';

    const labelY = M_TOP + PLOT_H + 22;
    const truncatedLabel = truncateLabel(d.project, 14);
    const xLabel = `<text x="${cx.toFixed(2)}" y="${labelY}" text-anchor="end" font-size="20" fill="#2A2A2A" transform="rotate(-40 ${cx.toFixed(2)} ${labelY})">${escapeHtml(truncatedLabel)}</text>`;

    return `<g>
      <rect x="${leftBarX.toFixed(2)}" y="${actsY.toFixed(2)}" width="${barW.toFixed(2)}" height="${actsH.toFixed(2)}" fill="#C77A00" rx="2">
        <title>${escapeHtml(d.project)}: ${d.unsafeActs} unsafe acts</title>
      </rect>
      <rect x="${rightBarX.toFixed(2)}" y="${condY.toFixed(2)}" width="${barW.toFixed(2)}" height="${condH.toFixed(2)}" fill="#C0392B" rx="2">
        <title>${escapeHtml(d.project)}: ${d.unsafeConditions} unsafe conditions</title>
      </rect>
      ${actsLabel}
      ${condLabel}
      ${xLabel}
    </g>`;
  }).join('');

  const totalActs = data.reduce((s, d) => s + d.unsafeActs, 0);
  const totalCond = data.reduce((s, d) => s + d.unsafeConditions, 0);

  return `
    <section class="dash-section chart-section" id="chart-ehs-audit">
      <div class="dash-section__head">
        <div>
          <h3>${title}</h3>
          <div class="chart-subtitle">${subtitle} · Total: <strong>${totalActs}</strong> unsafe acts, <strong>${totalCond}</strong> unsafe conditions</div>
        </div>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#C77A00"></span>Unsafe Acts</span>
          <span class="legend-item"><span class="legend-dot" style="background:#C0392B"></span>Unsafe Conditions</span>
        </div>
      </div>
      <div class="chart-wrap chart-wrap--xtall">
        <svg viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="xMidYMid meet" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
          ${yLines.join('')}
          ${bars}
        </svg>
      </div>
    </section>
  `;
}

// ----------------------------------------------------------------------------
// Incident chart — stacked bars (Major / Minor / Near Miss / Unspecified)
// ----------------------------------------------------------------------------

function incidentChartSection(data) {
  const title = 'Incidents / Accidents';
  const subtitle = 'Incident counts by accident type per project/site';

  if (!data || data.length === 0) {
    return emptySection('incident', title, subtitle);
  }

  const maxVal = Math.max(1, ...data.map(d => d.total));
  const ySteps = niceMax(maxVal);

  const VB_W = 1000, VB_H = 360;
  const M_TOP = 24, M_BOTTOM = 110, M_LEFT = 56, M_RIGHT = 16;
  const PLOT_W = VB_W - M_LEFT - M_RIGHT;
  const PLOT_H = VB_H - M_TOP - M_BOTTOM;

  const slotW = PLOT_W / data.length;
  const barW = Math.min(48, Math.max(8, slotW * 0.6));

  const yLines = [];
  for (let t = 0; t <= 4; t++) {
    const val = Math.round((ySteps / 4) * t);
    const y = M_TOP + PLOT_H - (val / ySteps) * PLOT_H;
    yLines.push(`<line x1="${M_LEFT}" y1="${y}" x2="${VB_W - M_RIGHT}" y2="${y}" stroke="#E5E5E5" stroke-width="1"/>`);
    yLines.push(`<text x="${M_LEFT - 8}" y="${y + 6}" text-anchor="end" font-size="20" fill="#999">${val}</text>`);
  }

  const bars = data.map((d, i) => {
    const cx = M_LEFT + i * slotW + slotW / 2;
    const barX = cx - barW / 2;

    // Stack: bottom to top — Major, Minor, Near Miss, Unspecified
    let yCursor = M_TOP + PLOT_H;
    const segments = [];

    const drawSeg = (count, color, label) => {
      if (count <= 0) return;
      const segH = (count / ySteps) * PLOT_H;
      yCursor -= segH;
      segments.push(`<rect x="${barX.toFixed(2)}" y="${yCursor.toFixed(2)}" width="${barW.toFixed(2)}" height="${segH.toFixed(2)}" fill="${color}">
        <title>${escapeHtml(d.project)} - ${label}: ${count}</title>
      </rect>`);
    };

    drawSeg(d.major, '#C0392B', 'Major');
    drawSeg(d.minor, '#C77A00', 'Minor');
    drawSeg(d.nearMiss, '#F2B93B', 'Near Miss');
    drawSeg(d.unspecified, '#9AA0A6', 'Unspecified');

    const totalLabel = `<text x="${cx.toFixed(2)}" y="${(yCursor - 8).toFixed(2)}" text-anchor="middle" font-size="22" fill="#2A2A2A" font-weight="700">${d.total}</text>`;

    const labelY = M_TOP + PLOT_H + 22;
    const truncatedLabel = truncateLabel(d.project, 14);
    const xLabel = `<text x="${cx.toFixed(2)}" y="${labelY}" text-anchor="end" font-size="20" fill="#2A2A2A" transform="rotate(-40 ${cx.toFixed(2)} ${labelY})">${escapeHtml(truncatedLabel)}</text>`;

    return `<g>${segments.join('')}${totalLabel}${xLabel}</g>`;
  }).join('');

  const totals = data.reduce((acc, d) => {
    acc.major += d.major;
    acc.minor += d.minor;
    acc.nearMiss += d.nearMiss;
    acc.unspecified += d.unspecified;
    return acc;
  }, { major: 0, minor: 0, nearMiss: 0, unspecified: 0 });

  return `
    <section class="dash-section chart-section" id="chart-incident">
      <div class="dash-section__head">
        <div>
          <h3>${title}</h3>
          <div class="chart-subtitle">${subtitle} · Total: <strong>${totals.major}</strong> Major, <strong>${totals.minor}</strong> Minor, <strong>${totals.nearMiss}</strong> Near Miss${totals.unspecified > 0 ? `, <strong>${totals.unspecified}</strong> Unspecified` : ''}</div>
        </div>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#C0392B"></span>Major</span>
          <span class="legend-item"><span class="legend-dot" style="background:#C77A00"></span>Minor</span>
          <span class="legend-item"><span class="legend-dot" style="background:#F2B93B"></span>Near Miss</span>
          ${totals.unspecified > 0 ? `<span class="legend-item"><span class="legend-dot" style="background:#9AA0A6"></span>Unspecified</span>` : ''}
        </div>
      </div>
      <div class="chart-wrap chart-wrap--xtall">
        <svg viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="xMidYMid meet" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
          ${yLines.join('')}
          ${bars}
        </svg>
      </div>
    </section>
  `;
}

function emptySection(id, title, subtitle) {
  return `
    <section class="dash-section chart-section" id="chart-${id}">
      <div class="dash-section__head">
        <div>
          <h3>${escapeHtml(title)}</h3>
          <div class="chart-subtitle">${escapeHtml(subtitle)}</div>
        </div>
      </div>
      <div class="empty-chart">
        <span>📊</span>
        <div>No data for the selected date range</div>
      </div>
    </section>
  `;
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function sumCount(arr) {
  return (arr || []).reduce((s, x) => s + (x.count || 0), 0);
}

function niceMax(v) {
  if (v <= 5) return 5;
  if (v <= 10) return 10;
  if (v <= 20) return 20;
  if (v <= 50) return 50;
  if (v <= 100) return 100;
  if (v <= 200) return 200;
  if (v <= 500) return 500;
  return Math.ceil(v / 100) * 100;
}

function truncateLabel(s, n) {
  s = String(s ?? '');
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function formatYmd(d) {
  // Format in IST so today's date matches what the user expects
  const offset = 5.5 * 60;
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function formatDateLong(s) {
  if (!s) return '—';
  const d = new Date(`${s}T00:00:00`);
  if (isNaN(d)) return s;
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}
