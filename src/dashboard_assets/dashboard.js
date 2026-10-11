// Results dashboard behaviour. Inlined into every page by src/dashboard.py.
// No network access: previews read data embedded in the page at build time.
(() => {
  const root = document.documentElement;

  // ---- Theme toggle: OS setting until the viewer chooses; choice kept in localStorage.
  const toggle = document.getElementById('theme-toggle');
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const effective = () => root.dataset.theme || (mq.matches ? 'dark' : 'light');
  const paint = () => {
    const dark = effective() === 'dark';
    toggle.setAttribute('aria-pressed', String(dark));
    toggle.dataset.mode = dark ? 'dark' : 'light';
    toggle.querySelector('.tlabel').textContent = dark ? 'Dark' : 'Light';
  };
  toggle.addEventListener('click', () => {
    const next = effective() === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('ns-theme', next); } catch (e) { /* storage blocked: theme lasts for this page only */ }
    paint();
  });
  if (mq.addEventListener) mq.addEventListener('change', paint);
  paint();

  // ---- Sortable tables: numbers sort numerically (cells may carry data-v), text alphabetically.
  const cellValue = (row, i) => {
    const cell = row.cells[i];
    const raw = cell.dataset.v !== undefined ? cell.dataset.v : cell.textContent.trim();
    const num = Number(raw);
    return raw !== '' && !Number.isNaN(num) ? num : raw.toLowerCase();
  };
  const compare = (a, b) => {
    if (typeof a === typeof b) return a < b ? -1 : a > b ? 1 : 0;
    return typeof a === 'number' ? -1 : 1;
  };
  document.querySelectorAll('table.sortable').forEach(table => {
    const heads = [...table.tHead.rows[0].cells];
    heads.forEach((th, i) => {
      const button = th.querySelector('button.sort');
      if (!button) return;
      button.addEventListener('click', () => {
        const asc = th.getAttribute('aria-sort') !== 'ascending';
        heads.forEach(h => h.removeAttribute('aria-sort'));
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        const body = table.tBodies[0];
        [...body.rows]
          .sort((r1, r2) => compare(cellValue(r1, i), cellValue(r2, i)) * (asc ? 1 : -1))
          .forEach(r => body.appendChild(r));
      });
    });
  });

  // ---- Vegetation review queue: filter rows by review priority.
  const priority = document.getElementById('priority-filter');
  if (priority) {
    priority.addEventListener('change', () => {
      let shown = 0;
      document.querySelectorAll('#queue tbody tr').forEach(r => {
        r.hidden = Boolean(priority.value) && r.dataset.priority !== priority.value;
        shown += r.hidden ? 0 : 1;
      });
      document.getElementById('queue-count').textContent = shown;
    });
  }

  // ---- Files page: filter by name or description.
  const filter = document.getElementById('file-filter');
  if (filter) {
    filter.addEventListener('input', () => {
      const term = filter.value.trim().toLowerCase();
      let total = 0;
      document.querySelectorAll('.group').forEach(group => {
        let shown = 0;
        group.querySelectorAll('[data-search]').forEach(el => {
          const hit = !term || el.dataset.search.includes(term);
          el.hidden = !hit;
          shown += hit ? 1 : 0;
        });
        group.hidden = shown === 0;
        total += shown;
      });
      document.getElementById('no-match').hidden = total > 0;
    });
  }

  // ---- Files page: previews embedded at build time, shown in a modal dialog.
  const dataEl = document.getElementById('preview-data');
  const dialog = document.getElementById('preview');
  if (dataEl && dialog) {
    const previews = JSON.parse(dataEl.textContent);
    const body = dialog.querySelector('.db');
    const el = (tag, text) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; return e; };
    const show = name => {
      const p = previews[name];
      dialog.querySelector('h2').textContent = name;
      dialog.querySelector('small').textContent = p.note || '';
      dialog.querySelector('a.btn').setAttribute('href', p.href);
      body.replaceChildren();
      if (p.kind === 'table') {
        const table = el('table'), head = el('tr'), tbody = el('tbody');
        p.header.forEach(h => { const th = el('th', h); th.scope = 'col'; th.title = h; head.appendChild(th); });
        table.appendChild(el('thead')).appendChild(head);
        p.rows.forEach(row => {
          const tr = el('tr');
          row.forEach(v => { const td = el('td', v); td.title = v; tr.appendChild(td); });
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        body.appendChild(table);
      } else {
        body.appendChild(el('pre', p.text));
      }
      dialog.showModal();
    };
    document.querySelectorAll('[data-preview]').forEach(b => b.addEventListener('click', () => show(b.dataset.preview)));
    dialog.querySelector('.close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
  }
})();
