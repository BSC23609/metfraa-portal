// ============================================================================
// Admin Dashboard — fetches stats and renders KPI tiles, daily activity chart,
// category breakdown (with drill-down to forms), status breakdown.
// ============================================================================

const FORM_ICONS = {
  toolbox: '🛠️', induction: '👷', 'ehs-audit': '🔍', incident: '⚠️', 'hse-meeting': '👥',
  'permit-record': '📋',
  'portable-grinding-machine': '⚙️', 'gas-welding-set': '🔥', 'aerial-boomlift': '🏗️',
  'air-compressor': '💨', 'arc-welding-machine': '⚡', 'cutting-machine': '✂️',
  'first-aid-box': '🏥', generator: '🔋', ladder: '🪜', 'mdb-panel': '🔌',
  'mobile-scaffolding': '🪟', 'scaffolding-cuplock': '🏗️', truck: '🚚',
  'labour-camp': '🏠', 'mobile-crane': '🏗️',
};

let lastData = null;
let expandedCategory = null;

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
        <div class="empty-state__hint">This dashboard is restricted to admin users.</div>
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

  // Default range: last 30 days
  const today = new Date();
  const thirtyAgo = new Date();
  thirtyAgo.setDate(today.getDate() - 29);
  document.getElementById('filter-start').value = formatYmd(thirtyAgo);
  document.getElementById('filter-end').value = formatYmd(today);

  document.getElementById('apply-range').addEventListener('click', () => loadDashboard());
  document.getElementById('refresh-btn').addEventListener('click', () => loadDashboard(true));

  // Preset buttons
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const days = parseInt(btn.dataset.days, 10);
      const end = new Date();
      const start = new Date();
      start.setDate(end.getDate() - (days - 1));
      document.getElementById('filter-start').value = formatYmd(start);
      document.getElementById('filter-end').value = formatYmd(end);
      // Visual active state
      document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('preset-btn--active'));
      btn.classList.add('preset-btn--active');
      loadDashboard();
    });
  });

  await loadDashboard();
})();

async function loadDashboard(forceFresh = false) {
  const mount = document.getElementById('dashboard-mount');
  mount.innerHTML = '<div class="loading">Loading dashboard…</div>';

  const startDate = document.getElementById('filter-start').value;
  const endDate = document.getElementById('filter-end').value;
  if (!startDate || !endDate) {
    mount.innerHTML = '<div class="empty-state"><div class="empty-state__title">Pick a date range</div></div>';
    return;
  }
  if (startDate > endDate) {
    mount.innerHTML = '<div class="empty-state"><div class="empty-state__title">Invalid range</div><div class="empty-state__hint">Start date must be before end date.</div></div>';
    return;
  }

  if (forceFresh) {
    try { await fetch('/ehs/api/admin/dashboard/cache-clear', { method: 'POST' }); } catch {}
  }

  try {
    const data = await fetch(`/ehs/api/admin/dashboard?startDate=${startDate}&endDate=${endDate}`).then(r => {
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
  document.getElementById('range-subtitle').textContent =
    `${formatDateLong(data.range.startDate)} → ${formatDateLong(data.range.endDate)}  ·  ${data.range.days} day${data.range.days === 1 ? '' : 's'}`;

  document.getElementById('dashboard-mount').innerHTML = `
    ${kpiTilesHtml(data)}
    ${dailyChartHtml(data)}
    ${statusBreakdownHtml(data)}
    ${categoryBreakdownHtml(data)}
  `;

  // Wire up category expand/collapse
  document.querySelectorAll('.cat-card').forEach(card => {
    card.addEventListener('click', () => {
      const cat = card.dataset.cat;
      expandedCategory = expandedCategory === cat ? null : cat;
      render(lastData);
    });
  });

  // Wire up date navigation arrows
  document.querySelectorAll('.chart-nav__btn').forEach(btn => {
    if (btn.disabled) return;
    btn.addEventListener('click', () => {
      const newStart = btn.dataset.start;
      const newEnd = btn.dataset.end;
      if (newStart && newEnd) {
        document.getElementById('filter-start').value = newStart;
        document.getElementById('filter-end').value = newEnd;
        // Clear preset highlight since custom navigation is now in effect
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('preset-btn--active'));
        loadDashboard();
      }
    });
  });
}

// ----------------------------------------------------------------------------
// KPI tiles (top section)
// ----------------------------------------------------------------------------

function kpiTilesHtml(data) {
  const k = data.kpi;
  return `
    <div class="kpi-grid">
      <div class="kpi-tile kpi-tile--blue">
        <div class="kpi-tile__num">${k.today}</div>
        <div class="kpi-tile__label">Today</div>
      </div>
      <div class="kpi-tile kpi-tile--blue">
        <div class="kpi-tile__num">${k.last7Days}</div>
        <div class="kpi-tile__label">Last 7 days</div>
      </div>
      <div class="kpi-tile kpi-tile--blue">
        <div class="kpi-tile__num">${k.totalInRange}</div>
        <div class="kpi-tile__label">In selected range</div>
      </div>
      <div class="kpi-tile ${k.pendingNow > 0 ? 'kpi-tile--orange' : 'kpi-tile--grey'}">
        <div class="kpi-tile__num">${k.pendingNow}</div>
        <div class="kpi-tile__label">Pending now</div>
      </div>
    </div>
  `;
}

// ----------------------------------------------------------------------------
// Daily activity chart — pure SVG, stacked bars (approved + rejected + pending)
// ----------------------------------------------------------------------------

function dailyChartHtml(data) {
  const days = data.dailyActivity;
  if (!days.length) return '';

  const maxVal = Math.max(1, ...days.map(d => d.total));
  const ySteps = niceMax(maxVal);

  // Use a single coordinate system — viewBox in pure pixels
  const VB_W = 1000;
  const VB_H = 280;
  const M_TOP = 16;
  const M_BOTTOM = 60;       // room for rotated date labels
  const M_LEFT = 44;         // room for y-axis labels
  const M_RIGHT = 16;
  const PLOT_W = VB_W - M_LEFT - M_RIGHT;
  const PLOT_H = VB_H - M_TOP - M_BOTTOM;

  const barSlotW = PLOT_W / days.length;
  const barW = Math.min(28, Math.max(4, barSlotW * 0.7));
  const barGap = barSlotW - barW;

  // ----- Y axis (gridlines + value labels) -----
  const yLines = [];
  const numYTicks = 4;
  for (let t = 0; t <= numYTicks; t++) {
    const val = Math.round((ySteps / numYTicks) * t);
    const y = M_TOP + PLOT_H - (val / ySteps) * PLOT_H;
    yLines.push(`<line x1="${M_LEFT}" y1="${y}" x2="${VB_W - M_RIGHT}" y2="${y}" stroke="#E5E5E5" stroke-width="1"/>`);
    yLines.push(`<text x="${M_LEFT - 6}" y="${y + 4}" text-anchor="end" font-size="11" fill="#999">${val}</text>`);
  }

  // ----- Bars + labels -----
  // Date labels: only show enough to fit. Compute max labels that fit at ~50px width per label.
  const maxLabels = Math.floor(PLOT_W / 70);
  const labelEveryN = Math.max(1, Math.ceil(days.length / maxLabels));

  const bars = days.map((d, i) => {
    const slotX = M_LEFT + i * barSlotW;
    const barX = slotX + barGap / 2;
    const cx = slotX + barSlotW / 2;

    const approvedH = (d.approved / ySteps) * PLOT_H;
    const rejectedH = (d.rejected / ySteps) * PLOT_H;
    const pendingH = (d.pending / ySteps) * PLOT_H;

    let yCursor = M_TOP + PLOT_H;
    const segments = [];
    if (d.approved > 0) {
      yCursor -= approvedH;
      segments.push(`<rect x="${barX.toFixed(2)}" y="${yCursor.toFixed(2)}" width="${barW.toFixed(2)}" height="${approvedH.toFixed(2)}" fill="#1F8B4C"/>`);
    }
    if (d.rejected > 0) {
      yCursor -= rejectedH;
      segments.push(`<rect x="${barX.toFixed(2)}" y="${yCursor.toFixed(2)}" width="${barW.toFixed(2)}" height="${rejectedH.toFixed(2)}" fill="#C0392B"/>`);
    }
    if (d.pending > 0) {
      yCursor -= pendingH;
      segments.push(`<rect x="${barX.toFixed(2)}" y="${yCursor.toFixed(2)}" width="${barW.toFixed(2)}" height="${pendingH.toFixed(2)}" fill="#F2B93B"/>`);
    }

    // Total label above bar
    const totalLabel = d.total > 0
      ? `<text x="${cx.toFixed(2)}" y="${(yCursor - 4).toFixed(2)}" text-anchor="middle" font-size="11" fill="#5A5A5A" font-weight="600">${d.total}</text>`
      : '';

    // Hover tooltip
    const tooltip = `<title>${d.date}: ${d.total} total (${d.approved} approved, ${d.rejected} rejected, ${d.pending} pending)</title>`;

    // Date label below — rotated 45° if many days, otherwise straight
    const showLabel = i % labelEveryN === 0 || i === days.length - 1;
    let xLabel = '';
    if (showLabel) {
      const labelY = M_TOP + PLOT_H + 14;
      if (labelEveryN > 1 || days.length > 7) {
        xLabel = `<text x="${cx.toFixed(2)}" y="${labelY}" text-anchor="end" font-size="11" fill="#666" transform="rotate(-45 ${cx.toFixed(2)} ${labelY})">${formatChartDate(d.date)}</text>`;
      } else {
        xLabel = `<text x="${cx.toFixed(2)}" y="${labelY}" text-anchor="middle" font-size="11" fill="#666">${formatChartDate(d.date)}</text>`;
      }
    }

    return `<g>${segments.join('')}${totalLabel}${tooltip}${xLabel}</g>`;
  }).join('');

  // ----- Date navigation arrows -----
  // Compute previous-window and next-window ranges (same length as current)
  const winDays = data.range.days;
  const startD = new Date(`${data.range.startDate}T00:00:00`);
  const prevStart = new Date(startD);
  prevStart.setDate(prevStart.getDate() - winDays);
  const prevEnd = new Date(prevStart);
  prevEnd.setDate(prevEnd.getDate() + winDays - 1);

  const endD = new Date(`${data.range.endDate}T00:00:00`);
  const nextStart = new Date(endD);
  nextStart.setDate(nextStart.getDate() + 1);
  const nextEnd = new Date(nextStart);
  nextEnd.setDate(nextEnd.getDate() + winDays - 1);

  // Disable "next" if next window would extend past today
  const todayStr = formatYmd(new Date());
  const nextStartStr = formatYmd(nextStart);
  const nextDisabled = nextStartStr > todayStr;

  return `
    <section class="dash-section">
      <div class="dash-section__head">
        <h3>Daily Activity</h3>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#1F8B4C"></span>Approved</span>
          <span class="legend-item"><span class="legend-dot" style="background:#C0392B"></span>Rejected</span>
          <span class="legend-item"><span class="legend-dot" style="background:#F2B93B"></span>Pending</span>
        </div>
      </div>

      <!-- Date navigation -->
      <div class="chart-nav">
        <button type="button" class="chart-nav__btn" data-shift="prev"
                data-start="${formatYmd(prevStart)}" data-end="${formatYmd(prevEnd)}"
                title="Previous ${winDays} day${winDays === 1 ? '' : 's'}">
          ← ${formatDateLong(formatYmd(prevStart))} – ${formatDateLong(formatYmd(prevEnd))}
        </button>
        <div class="chart-nav__current">
          ${formatDateLong(data.range.startDate)} – ${formatDateLong(data.range.endDate)}
        </div>
        <button type="button" class="chart-nav__btn ${nextDisabled ? 'chart-nav__btn--disabled' : ''}"
                ${nextDisabled ? 'disabled' : ''}
                data-shift="next"
                data-start="${formatYmd(nextStart)}" data-end="${formatYmd(nextEnd)}"
                title="${nextDisabled ? 'No future data available' : `Next ${winDays} day${winDays === 1 ? '' : 's'}`}">
          ${nextDisabled ? 'No future data' : formatDateLong(formatYmd(nextStart)) + ' – ' + formatDateLong(formatYmd(nextEnd))} →
        </button>
      </div>

      <div class="chart-wrap">
        <svg viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="xMidYMid meet" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
          ${yLines.join('')}
          ${bars}
        </svg>
      </div>
    </section>
  `;
}

// ----------------------------------------------------------------------------
// Status breakdown — small horizontal pills
// ----------------------------------------------------------------------------

function statusBreakdownHtml(data) {
  const b = data.breakdown;
  const tot = Math.max(1, b.total);
  const pct = (n) => Math.round((n / tot) * 100);
  return `
    <section class="dash-section">
      <div class="dash-section__head"><h3>Status Breakdown</h3></div>
      <div class="status-grid">
        <div class="status-card status-card--approved">
          <div class="status-card__num">${b.approved}</div>
          <div class="status-card__label">Approved</div>
          <div class="status-card__pct">${pct(b.approved)}%</div>
        </div>
        <div class="status-card status-card--rejected">
          <div class="status-card__num">${b.rejected}</div>
          <div class="status-card__label">Rejected</div>
          <div class="status-card__pct">${pct(b.rejected)}%</div>
        </div>
        <div class="status-card status-card--pending">
          <div class="status-card__num">${b.pending}</div>
          <div class="status-card__label">Pending</div>
          <div class="status-card__pct">${pct(b.pending)}%</div>
        </div>
        <div class="status-card status-card--total">
          <div class="status-card__num">${b.total}</div>
          <div class="status-card__label">Total</div>
          <div class="status-card__pct">100%</div>
        </div>
      </div>
    </section>
  `;
}

// ----------------------------------------------------------------------------
// Category breakdown with drill-down to individual forms
// ----------------------------------------------------------------------------

function categoryBreakdownHtml(data) {
  const cats = ['general', 'equipment'];
  const cards = cats.map(cat => {
    const c = data.byCategory[cat];
    const isExpanded = expandedCategory === cat;
    return `
      <div class="cat-card ${isExpanded ? 'cat-card--expanded' : ''}" data-cat="${cat}">
        <div class="cat-card__head">
          <div>
            <div class="cat-card__title">${escapeHtml(c.label)}</div>
            <div class="cat-card__sub">${c.total} submission${c.total === 1 ? '' : 's'}</div>
          </div>
          <div class="cat-card__chev">${isExpanded ? '▾' : '▸'}</div>
        </div>
        <div class="cat-card__bars">
          ${miniBar(c.approved, c.total, '#1F8B4C', 'Approved')}
          ${miniBar(c.rejected, c.total, '#C0392B', 'Rejected')}
          ${miniBar(c.pending, c.total, '#F2B93B', 'Pending')}
        </div>
      </div>`;
  }).join('');

  // Drill-down rows for forms in expanded category
  const drillDown = expandedCategory
    ? formsTableHtml(data.byForm.filter(f => f.category === expandedCategory))
    : '';

  return `
    <section class="dash-section">
      <div class="dash-section__head">
        <h3>By Category</h3>
        <span class="hint">click a category to see individual forms</span>
      </div>
      <div class="cat-grid">
        ${cards}
      </div>
      ${drillDown}
    </section>
  `;
}

function miniBar(value, total, color, label) {
  const pct = total === 0 ? 0 : (value / total) * 100;
  return `
    <div class="mini-bar">
      <div class="mini-bar__label">
        <span class="legend-dot" style="background:${color}"></span>
        <span>${label}</span>
        <span class="mini-bar__val">${value}</span>
      </div>
      <div class="mini-bar__track">
        <div class="mini-bar__fill" style="width:${pct.toFixed(1)}%; background:${color};"></div>
      </div>
    </div>
  `;
}

function formsTableHtml(forms) {
  // Sort by total desc
  forms.sort((a, b) => b.total - a.total);
  return `
    <div class="forms-table-wrap">
      <table class="forms-table">
        <thead>
          <tr>
            <th>Form</th>
            <th class="num">Total</th>
            <th class="num">Approved</th>
            <th class="num">Rejected</th>
            <th class="num">Pending</th>
          </tr>
        </thead>
        <tbody>
          ${forms.map(f => `
            <tr>
              <td>
                <div class="cell-form">
                  <span class="cell-form__icon">${FORM_ICONS[f.id] || '📄'}</span>
                  <div>
                    <div>${escapeHtml(f.title)}</div>
                    <div style="margin-top:3px;"><span class="cell-form__code">${escapeHtml(f.code)}</span></div>
                  </div>
                </div>
              </td>
              <td class="num"><strong>${f.total}</strong></td>
              <td class="num" style="color:#1F8B4C;">${f.approved}</td>
              <td class="num" style="color:#C0392B;">${f.rejected || ''}</td>
              <td class="num" style="color:#8C6A00;">${f.pending || ''}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function niceMax(v) {
  if (v <= 5) return 5;
  if (v <= 10) return 10;
  if (v <= 20) return 20;
  if (v <= 50) return 50;
  if (v <= 100) return 100;
  // round up to nearest 50
  return Math.ceil(v / 50) * 50;
}

function formatYmd(d) {
  return d.toISOString().slice(0, 10);
}
function formatDateLong(s) {
  if (!s) return '—';
  const d = new Date(`${s}T00:00:00`);
  if (isNaN(d)) return s;
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}
function formatChartDate(s) {
  if (!s) return '';
  const d = new Date(`${s}T00:00:00`);
  if (isNaN(d)) return s;
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}
