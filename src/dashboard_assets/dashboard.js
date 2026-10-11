// Results dashboard behaviour. Inlined into every page by src/dashboard.py.
// No network access: previews read data embedded in the page at build time, and file
// contents are only ever written as text (textContent), never interpreted as HTML or script.
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

  // ---- Sidebar: highlight the link for the section in view (set on arrival, on hash change and while scrolling).
  const here = location.pathname.split('/').pop() || 'index.html';
  const sideLinks = [...document.querySelectorAll('.sn')];
  const pageLinks = sideLinks
    .map(a => { const [file, id] = a.getAttribute('href').split('#'); return { a, file, el: id ? document.getElementById(id) : null }; })
    .filter(l => l.file === here);
  const setActive = link => sideLinks.forEach(a => {
    const on = Boolean(link) && a === link.a;
    a.classList.toggle('on', on);
    if (on) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
  });
  const inView = () => {
    const sections = pageLinks.filter(l => l.el);
    const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
    const line = atBottom ? window.innerHeight : 140;  // a section is "current" once its top passes this line
    const passed = sections.filter(l => l.el.getBoundingClientRect().top <= line);
    if (!passed.length) return pageLinks.find(l => !l.el);
    // Side-by-side sections share a top edge; among those, prefer the one the visitor clicked.
    const top = passed[passed.length - 1].el.getBoundingClientRect().top;
    const level = passed.filter(l => Math.abs(l.el.getBoundingClientRect().top - top) < 2);
    return level.find(l => '#' + l.el.id === location.hash) || level[level.length - 1];
  };
  if (pageLinks.length) {
    let ticking = false, locked = null, unlock = null;
    const update = () => { setActive(locked || inView()); ticking = false; };
    // While a same-page link scrolls smoothly, keep it highlighted instead of the sections it passes.
    const release = () => { locked = null; update(); };
    pageLinks.forEach(l => l.a.addEventListener('click', e => {
      if (!l.el) {  // the page's own top link: glide to the top instead of reloading the page
        e.preventDefault();
        history.pushState(null, '', l.a.getAttribute('href'));
        window.scrollTo({ top: 0 });  // smooth via CSS scroll-behavior unless reduced motion is set
      }
      locked = l;
      setActive(l);
      clearTimeout(unlock);
      unlock = setTimeout(release, 1200);  // fallback where 'scrollend' is not supported
    }));
    window.addEventListener('scrollend', () => { if (locked) { clearTimeout(unlock); release(); } });
    // Arriving from another page at #section: the browser scrolls there (smoothly), so hold that link meanwhile.
    const arrived = pageLinks.find(l => l.el && '#' + l.el.id === location.hash);
    if (arrived) { locked = arrived; unlock = setTimeout(release, 1500); }
    window.addEventListener('scroll', () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    window.addEventListener('hashchange', update);
    window.addEventListener('load', update);
    update();
  }

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

  // ---- Files page: category chips plus free-text filter.
  const search = document.getElementById('file-filter');
  const chips = [...document.querySelectorAll('.filter[data-tag]')];
  if (search || chips.length) {
    let tag = 'all';
    const apply = () => {
      const term = search ? search.value.trim().toLowerCase() : '';
      let total = 0;
      document.querySelectorAll('.group').forEach(group => {
        let shown = 0;
        group.querySelectorAll('[data-search]').forEach(el => {
          const hit = (tag === 'all' || el.dataset.tags.split(' ').includes(tag)) && (!term || el.dataset.search.includes(term));
          el.hidden = !hit;
          shown += hit ? 1 : 0;
        });
        group.hidden = shown === 0;
        total += shown;
      });
      document.getElementById('no-match').hidden = total > 0;
    };
    chips.forEach(chip => chip.addEventListener('click', () => {
      tag = chip.dataset.tag;
      chips.forEach(c => c.setAttribute('aria-pressed', String(c === chip)));
      apply();
    }));
    if (search) search.addEventListener('input', apply);
  }

  // ---- Files page: a pathless server root (python -m http.server --directory outputs) cannot
  // reach notebooks/, data/ or reports/; say so instead of leaving silent 404s.
  const served = document.getElementById('served-note');
  if (served && location.protocol.startsWith('http') && !location.pathname.includes('/outputs/dashboard/')) served.hidden = false;

  // ---- Files page: previews embedded at build time, shown in a modal dialog.
  const dataEl = document.getElementById('preview-data');
  const dialog = document.getElementById('preview');
  if (!dataEl || !dialog) return;
  const previews = JSON.parse(dataEl.textContent);
  const body = dialog.querySelector('.db');
  const download = dialog.querySelector('a.dl');
  let opener = null;
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const msg = text => body.appendChild(el('div', text, 'msg'));

  const render = p => {
    if (p.kind === 'table') {
      if (!p.rows.length) return msg('This table has a header but no rows.');
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
    } else if (p.kind === 'text') {
      body.appendChild(el('pre', p.text));
    } else if (p.kind === 'image') {
      const img = el('img'); img.src = p.href; img.alt = p.name; body.appendChild(img);
    } else if (p.kind === 'pdf') {
      const frame = el('iframe'); frame.src = p.href; frame.title = 'PDF preview: ' + p.name; body.appendChild(frame);
    } else if (p.kind === 'notebook') {
      p.cells.forEach(c => {
        const cell = el('div', undefined, 'nb-cell nb-' + c.type);
        cell.appendChild(el('div', c.type === 'code' ? 'In [' + (c.count ?? ' ') + ']' : 'Markdown', 'nb-k'));
        cell.appendChild(el('pre', c.source));
        (c.outputs || []).forEach(o => {
          const out = el('div', undefined, 'nb-cell nb-out');
          out.appendChild(el('div', 'Output', 'nb-k'));
          out.appendChild(el('pre', o));
          cell.appendChild(out);
        });
        body.appendChild(cell);
      });
    } else {
      msg(p.reason || 'Preview is not available for this file type. Use Download to get the file.');
    }
  };

  const show = name => {
    const p = previews[name];
    opener = document.activeElement;
    dialog.querySelector('h2').textContent = p.name;
    dialog.querySelector('small').textContent = [p.type, p.size, p.note].filter(Boolean).join(' · ');
    download.setAttribute('href', p.href);
    download.setAttribute('download', p.name);
    body.replaceChildren();
    render(p);
    body.scrollTop = 0;
    dialog.showModal();
    dialog.querySelector('.dclose').focus();
  };
  const close = () => dialog.close();
  dialog.addEventListener('close', () => {
    body.replaceChildren();  // stop PDFs / large tables holding memory
    if (opener && document.contains(opener)) opener.focus();
  });
  // Keep Tab inside the dialog (showModal makes the page inert; this also wraps at the ends).
  dialog.addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const items = [...dialog.querySelectorAll('button, a[href], iframe, [tabindex]:not([tabindex="-1"])')];
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  document.querySelectorAll('[data-preview]').forEach(b => b.addEventListener('click', () => show(b.dataset.preview)));
  dialog.querySelectorAll('.dclose, .dcancel').forEach(b => b.addEventListener('click', close));
  dialog.addEventListener('click', e => { if (e.target === dialog) close(); });  // backdrop click
})();
