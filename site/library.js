/* ===================================================================
   The Library view
   -------------------------------------------------------------------
   The same curriculum as the list, drawn as a bookcase: one rack per
   phase, one painted spine per lesson. The geometry is not decoration
   for its own sake — each dimension is read off the lesson:

     spine WIDTH   ← word count. A thick book is a long lesson.
     spine HEIGHT  ← deterministic jitter from the lesson path, so the
                     shelf looks hand-shelved rather than extruded, and
                     looks the SAME on every visit.
     lying FLAT    ← the phase capstone. The finished work rests on the
                     pile at the end of its shelf.
     RIBBON        ← you have marked the lesson done (localStorage).
     BLANK volume  ← nothing written yet, so it is not a link either.

   Colour, lettering, spine banding and the little foot ornament are all
   hash-picked per lesson from fixed sets, which is what buys the
   "someone painted these one at a time" look without 169 hand-drawn
   assets. Swap PIGMENTS for real scanned washes and nothing else in
   this file has to change.

   Rendering is deferred until the reader actually asks for this view —
   169 filtered spines is real work, and most visits never switch.

   Exposes window.BELibrary.mount(host).
=================================================================== */
(function () {
  'use strict';

  /* ── Pigments ───────────────────────────────────────────────────
     Nineteen washes that all sit on the same warm paper the rest of the
     site is printed on. `deep` is the same pigment concentrated: it does
     the edge-pooling and the banding, which is how a real wash darkens
     where the brush stopped. `tx` is chosen per pigment for contrast, not
     computed, so nothing ends up as grey-on-grey. */
  var PIGMENTS = [
    { bg: '#c2603c', deep: '#7d3418', tx: '#fbf3e4' },
    { bg: '#9e4029', deep: '#5f2213', tx: '#fbf3e4' },
    { bg: '#b0572c', deep: '#6d3013', tx: '#fbf3e4' },
    { bg: '#d79a3c', deep: '#8a5a12', tx: '#2b2118' },
    { bg: '#c8a52f', deep: '#7d6410', tx: '#2b2118' },
    { bg: '#ddc37a', deep: '#9a7c33', tx: '#3a2c18' },
    { bg: '#7f8a45', deep: '#47501f', tx: '#f7f4e6' },
    { bg: '#9fae84', deep: '#5c6b42', tx: '#25291a' },
    { bg: '#5d7a4c', deep: '#2f4523', tx: '#f4f2e4' },
    { bg: '#4a7e79', deep: '#20443f', tx: '#f2f3ec' },
    { bg: '#7093b0', deep: '#33556f', tx: '#f6f5ee' },
    { bg: '#a8c2d4', deep: '#4f7690', tx: '#1f2a33' },
    { bg: '#3f5578', deep: '#1d2a41', tx: '#eef1f5' },
    { bg: '#5a6472', deep: '#2c333d', tx: '#f0efe9' },
    { bg: '#7b556e', deep: '#402438', tx: '#f6eff2' },
    { bg: '#c98a86', deep: '#7e453f', tx: '#2c1d1c' },
    { bg: '#e6dcc0', deep: '#a39265', tx: '#332a1c' },
    { bg: '#d3c3a0', deep: '#8d7a4d', tx: '#2f2718' },
    { bg: '#3a3531', deep: '#141210', tx: '#ece5d4' }
  ];

  var LETTERING = ['st-display', 'st-caps', 'st-mono', 'st-heavy'];

  /* Foot ornaments. Small enough that they read as a painted flourish
     rather than an icon, which is exactly their job. */
  var ORNAMENTS = [
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><path d="M6 1.5 7.3 4.6 10.5 4.9 8.1 7 8.8 10.2 6 8.5 3.2 10.2 3.9 7 1.5 4.9 4.7 4.6z"/></svg>',
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><path d="M6 10.5c0-4 1.5-6.5 4.5-8.5-4 0-6.5 2-6.5 5.5"/><path d="M6 10.5C6 7 4.5 5 1.8 3.6"/></svg>',
    '<svg viewBox="0 0 12 12" fill="currentColor"><path d="M6 10.3 2.2 6.6a2.3 2.3 0 0 1 3.3-3.2L6 3.9l.5-.5a2.3 2.3 0 0 1 3.3 3.2z"/></svg>',
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1"><path d="M6 1.4 10.4 6 6 10.6 1.6 6z"/></svg>',
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><path d="M1 4.4c1.2-1.3 2.3-1.3 3.5 0s2.3 1.3 3.5 0 2.3-1.3 3 0"/><path d="M1 8c1.2-1.3 2.3-1.3 3.5 0s2.3 1.3 3.5 0 2.3-1.3 3 0"/></svg>',
    '<svg viewBox="0 0 12 12" fill="currentColor"><circle cx="6" cy="2.4" r="1.3"/><circle cx="6" cy="6" r="1.3"/><circle cx="6" cy="9.6" r="1.3"/></svg>',
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><circle cx="6" cy="6" r="2.4"/><path d="M6 .8v1.4M6 9.8v1.4M.8 6h1.4M9.8 6h1.4M2.3 2.3l1 1M8.7 8.7l1 1M9.7 2.3l-1 1M3.3 8.7l-1 1"/></svg>',
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><circle cx="6" cy="3.4" r="2.1"/><path d="M6 5.5v5.2M6 8.2h2M6 9.8h1.6"/></svg>',
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><path d="M2 9.6 10 2.4M10 2.4H6.4M10 2.4v3.6"/></svg>',
    '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1"><rect x="2.2" y="2.2" width="7.6" height="7.6" rx="0.6"/><path d="M4.6 6h2.8"/></svg>'
  ];

  /* ── Deterministic randomness ──────────────────────────────────
     Every visual choice is a pure function of the lesson's own path, so a
     book looks identical on every load and on every device. FNV-1a plus a
     salt gives us as many independent-looking streams as we need from one
     string. */
  function rnd(str, salt) {
    var h = (2166136261 ^ salt) >>> 0;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    h ^= h >>> 15;
    h = Math.imul(h, 2246822507);
    h ^= h >>> 13;
    return (h >>> 0) / 4294967296;
  }
  function pick(arr, str, salt) { return arr[Math.floor(rnd(str, salt) * arr.length) % arr.length]; }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function formatNum(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
  function toRoman(n) {
    var map = [[10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
    if (n === 0) return '0';
    var out = '';
    for (var i = 0; i < map.length; i++) while (n >= map[i][0]) { out += map[i][1]; n -= map[i][0]; }
    return out;
  }

  /* A spine carries the title, not the subtitle. Almost every lesson here
     is "Main Title: the longer explanatory half", and it is the first half
     that belongs on a spine — the rest is what the hover card is for. */
  function spineTitle(name) {
    // "Capstone: A Mini Relational Engine on a B-Tree" — here it is the half
    // AFTER the colon that names the book. Everywhere else it is the half
    // before it.
    var s = /^capstone\s*:/i.test(name)
      ? name.slice(name.indexOf(':') + 1).trim()
      : name.split(':')[0].trim();
    if (s.length > 30) s = s.split(/\s[&—–-]\s/)[0].trim();
    if (s.length > 30) s = s.replace(/,.*$/, '').trim();
    return s || name;
  }

  function lessonPath(l) {
    var m = l.url ? l.url.match(/(phases\/[^/]+\/[^/]+)\/?$/) : null;
    return m ? m[1] : '';
  }

  /* ── Building one book ─────────────────────────────────────────── */

  var WORDS_MIN = 475, WORDS_MAX = 7800;

  function buildBook(l, phase, index, prevPigment) {
    var path = lessonPath(l) || (phase.id + '-' + l.name);
    var flat = l.type === 'Capstone' || /^capstone\b/i.test(l.name);

    // Thickness off the word count, on a square-root curve so the middle of
    // the range spreads out instead of bunching.
    var w = l.words || 1600;
    var t = (Math.sqrt(Math.min(Math.max(w, WORDS_MIN), WORDS_MAX)) - Math.sqrt(WORDS_MIN)) /
            (Math.sqrt(WORDS_MAX) - Math.sqrt(WORDS_MIN));
    var width = Math.round(17 + t * 20);                    // 17 … 37px
    var height = Math.round(68 + rnd(path, 3) * 41);        // 68 … 109px

    // No two neighbours in the same wash.
    var pi = Math.floor(rnd(path, 7) * PIGMENTS.length);
    if (PIGMENTS[pi] === prevPigment) pi = (pi + 1 + Math.floor(rnd(path, 8) * 4)) % PIGMENTS.length;
    var pig = PIGMENTS[pi];

    var dir = rnd(path, 11) < 0.76 ? 'up' : 'down';
    var letter = pick(LETTERING, path, 13);
    var dress = Math.floor(rnd(path, 17) * 5);
    var blank = l.status !== 'complete' && !l.url;   // nothing written yet
    var orn = blank ? '' : (rnd(path, 19) < 0.55 ? pick(ORNAMENTS, path, 23) : '');
    var ornTop = rnd(path, 29) < 0.3 ? '1' : '0';

    var done = l.status === 'complete';
    var userDone = window.BEProgress && path && window.BEProgress.isLessonComplete(path);
    var href = done && path ? 'lesson.html?path=' + path : (l.url || '');
    var ghost = blank;

    var bands = '';
    if (dress === 1) bands = '<span class="band head"></span><span class="band foot"></span>';
    else if (dress === 2) bands = '<span class="band panel"></span>';
    else if (dress === 3) bands = '<span class="band rule" style="top:12%"></span><span class="band rule" style="top:15%"></span><span class="band rule" style="bottom:12%"></span><span class="band rule" style="bottom:15%"></span>';
    else if (dress === 4) bands = '<span class="band block-foot"></span>';

    var title = spineTitle(l.name);
    var style =
      '--w:' + width + 'px;--h:' + height + 'px;' +
      '--fw:' + height + 'px;--fh:' + width + 'px;' +
      '--bg:' + pig.bg + ';--deep:' + pig.deep + ';--tx:' + pig.tx + ';' +
      '--panel:' + (dress === 2 ? '#efe6cf' : pig.bg) + ';--panel-ink:#2f2718;' +
      '--fs:7px;';

    // The last upright book on a shelf leans into the gap, the way the last
    // book on a real shelf always does.
    var html = '<a class="book' + (flat ? ' flat' : '') + (ghost ? ' ghost' : '') + '"' +
      (ghost ? '' : ' href="' + escapeHtml(href) + '"') +
      (href && !(done && path) ? ' target="_blank" rel="noopener"' : '') +
      ' style="' + style + '"' +
      ' data-dir="' + dir + '"' +
      ' data-panel="' + (dress === 2 ? '1' : '0') + '"' +
      ' data-orn="' + (orn ? '1' : '0') + '"' +
      ' data-orn-top="' + ornTop + '"' +
      ' data-name="' + escapeHtml(l.name) + '"' +
      ' data-words="' + (l.words || 0) + '"' +
      (ghost ? ' tabindex="0" role="note"' : '') +
      ' aria-label="' + escapeHtml(l.name) + ' — phase ' + phase.id + ', lesson ' + (index + 1) + '">' +
      '<span class="paint" aria-hidden="true"></span>' +
      bands +
      '<span class="title ' + letter + '"><span>' + escapeHtml(title) + '</span></span>' +
      (orn ? '<span class="orn" aria-hidden="true">' + orn + '</span>' : '') +
      (userDone ? '<span class="ribbon" aria-hidden="true"></span>' : '') +
      '</a>';

    return { html: html, flat: flat, pigment: pig, width: flat ? height : width, height: height };
  }

  /* ── Building the racks ────────────────────────────────────────── */

  var GAP = 2;              // between two books
  var STRIP_PAD = 14;       // the bit of plank past the last book
  var PILE_GAP = 8;         // between the uprights and the capstone pile
  var PLANK_MIN = 190;      // a plank still has to carry its label

  function render(host) {
    if (!host || typeof PHASES === 'undefined') return;

    var avail = host.clientWidth || 1136;
    host.setAttribute('data-w', avail);

    var out = '';
    for (var i = 0; i < PHASES.length; i++) out += buildRack(PHASES[i], avail);

    host.innerHTML = out;
    fitTitles(host);
  }

  /* Fill shelves left to right, starting a new one when the next book would
     hang off the end. */
  function chunk(items, rowMax) {
    var rows = [], row = [], rowW = 0;
    for (var k = 0; k < items.length; k++) {
      var w = items[k].width + (row.length ? GAP : 0);
      if (row.length && rowW + w > rowMax) { rows.push({ items: row, w: rowW }); row = []; rowW = 0; w = items[k].width; }
      row.push(items[k]);
      rowW += w;
    }
    if (row.length) rows.push({ items: row, w: rowW });
    return rows;
  }

  function buildRack(p, avail) {
    var books = [], pile = [], prev = null, lean = -1;

    // Which upright book leans: the last one, since that is where the gap is.
    for (var j = p.lessons.length - 1; j >= 0; j--) {
      var isFlat = p.lessons[j].type === 'Capstone' || /^capstone\b/i.test(p.lessons[j].name);
      if (!isFlat) { lean = j; break; }
    }

    for (var j = 0; j < p.lessons.length; j++) {
      var b = buildBook(p.lessons[j], p, j, prev);
      prev = b.pigment;
      if (b.flat) { pile.push(b); continue; }
      if (j === lean) {
        var deg = (2.5 + rnd(p.name + j, 31) * 4).toFixed(1);
        b.html = b.html.replace('style="', 'style="--rot:' + deg + 'deg;');
      }
      books.push(b);
    }

    // The capstone pile rides along as one more item, so it lands on the
    // same row as the last books rather than starting a shelf of its own.
    var pileWidth = 0;
    for (var k = 0; k < pile.length; k++) pileWidth = Math.max(pileWidth, pile[k].width);
    var items = books.slice();
    if (pile.length) items.push({ pileHtml: pile.map(function (x) { return x.html; }).join(''), width: pileWidth + PILE_GAP });

    // Greedy fill first: how many planks does this phase actually need?
    var rowMax = Math.max(avail - STRIP_PAD, 200);
    var rows = chunk(items, rowMax);

    // Then spread the books evenly over that many planks. Greedy alone leaves
    // the last shelf holding one lonely book; balancing keeps every shelf in
    // the phase looking equally stocked, without adding a plank.
    if (rows.length > 1) {
      var total = 0, widest = 0;
      for (var k = 0; k < items.length; k++) {
        total += items[k].width + (k ? GAP : 0);
        if (items[k].width > widest) widest = items[k].width;
      }
      var target = Math.max(total / rows.length, widest);
      for (var slack = 0; slack <= 48; slack += 8) {
        var balanced = chunk(items, Math.min(rowMax, target + slack));
        if (balanced.length === rows.length) { rows = balanced; break; }
      }
    }

    // Every plank in one phase is cut to the same length, so a two-shelf
    // phase reads as one bookcase rather than two unrelated boards.
    var plank = PLANK_MIN;
    for (var r = 0; r < rows.length; r++) plank = Math.max(plank, rows[r].w + STRIP_PAD);

    var out = '<section class="rack" aria-label="Phase ' + p.id + ': ' + escapeHtml(p.name) + '">';
    for (var r = 0; r < rows.length; r++) {
      var strip = '';
      for (var k = 0; k < rows[r].items.length; k++) {
        var it = rows[r].items[k];
        strip += it.pileHtml ? '<div class="pile">' + it.pileHtml + '</div>' : it.html;
      }
      // The label goes on the last plank, directly under the books it names.
      var last = r === rows.length - 1;
      out += '<div class="shelf-row" style="width:' + Math.round(plank) + 'px">' +
        '<div class="rack-strip">' + strip + '</div>' +
        '<div class="shelf">' + (last
          ? '<span class="shelf-plate">' +
              '<span class="plate-num">' + toRoman(p.id) + '</span>' +
              escapeHtml(p.name) +
              '<span class="plate-count">' + p.lessons.length + '</span>' +
            '</span>'
          : '') + '</div>' +
      '</div>';
    }
    return out + '</section>';
  }

  /* Step the lettering down until every title actually fits its spine, then
     trim the handful that still cannot. Done in batched read/write passes so
     169 books cost a handful of layouts, not 169. */
  function fitTitles(host) {
    var sizes = [7, 6.5, 6, 5.5, 5];
    var books = Array.prototype.slice.call(host.querySelectorAll('.book'));
    var live = books;

    for (var s = 0; s < sizes.length; s++) {
      var overflowing = [];
      for (var i = 0; i < live.length; i++) {
        var t = live[i].querySelector('.title');
        var inner = t.firstElementChild;
        // Vertical writing-mode: wrapped columns grow along the box's inline
        // axis, which is its width on screen. Measure the text span itself —
        // a centred flex box does not report overflow spilling past both
        // of its edges.
        if (inner.offsetWidth > t.clientWidth + 1 || inner.offsetHeight > t.clientHeight + 1) overflowing.push(live[i]);
      }
      if (!overflowing.length) return;
      if (s === sizes.length - 1) {
        for (var k = 0; k < overflowing.length; k++) {
          var box = overflowing[k].querySelector('.title');
          var el = box.firstElementChild;
          var txt = el.textContent;
          while (txt.length > 6) {
            txt = txt.slice(0, -2);
            el.textContent = txt + '…';
            if (el.offsetWidth <= box.clientWidth + 1 && el.offsetHeight <= box.clientHeight + 1) break;
          }
        }
        return;
      }
      for (var k = 0; k < overflowing.length; k++) overflowing[k].style.setProperty('--fs', sizes[s + 1] + 'px');
      live = overflowing;
    }
  }

  /* ── The hover card ────────────────────────────────────────────── */

  function wireCard(host) {
    var card = document.getElementById('libraryCard');
    if (!card) {
      card = document.createElement('div');
      card.className = 'library-card';
      card.id = 'libraryCard';
      card.setAttribute('role', 'tooltip');
      card.setAttribute('aria-hidden', 'true');
      document.body.appendChild(card);
    }
    var open = null;

    function show(book) {
      open = book;
      var words = Number(book.getAttribute('data-words')) || 0;

      // The spine carries the short title and the plank says which phase it
      // is, so all the card owes you is the full name and how much reading
      // it is.
      var name = book.getAttribute('data-name');
      // Short titles look better on one line; only the long ones wrap.
      card.classList.toggle('wrap', name.length > 34);

      card.innerHTML =
        '<div class="card-name">' + escapeHtml(name) + '</div>' +
        '<div class="card-meta">' + (book.classList.contains('ghost')
          ? 'Not written yet'
          : (words ? formatNum(words) + ' words' : 'Read the chapter')) + '</div>';

      card.classList.add('show');
      card.setAttribute('aria-hidden', 'false');

      var r = book.getBoundingClientRect();
      var cw = card.offsetWidth, ch = card.offsetHeight;
      var left = Math.min(Math.max(8, r.left + r.width / 2 - cw / 2), window.innerWidth - cw - 8);
      var top = r.top - ch - 14;
      if (top < 8) top = Math.min(r.bottom + 14, window.innerHeight - ch - 8);
      card.style.left = left + 'px';
      card.style.top = top + 'px';
    }

    function hide() {
      open = null;
      card.classList.remove('show');
      card.setAttribute('aria-hidden', 'true');
    }

    host.addEventListener('pointerover', function (e) {
      var book = e.target.closest ? e.target.closest('.book') : null;
      if (book && book !== open) show(book);
    });
    host.addEventListener('pointerout', function (e) {
      var book = e.target.closest ? e.target.closest('.book') : null;
      if (book && !book.contains(e.relatedTarget)) hide();
    });
    host.addEventListener('focusin', function (e) {
      var book = e.target.closest ? e.target.closest('.book') : null;
      if (book) show(book);
    });
    host.addEventListener('focusout', hide);
    window.addEventListener('scroll', function () { if (open) hide(); }, { passive: true });
  }

  /* The brush. feTurbulence pushes every edge of a painted spine off its
     straight line by a few pixels, which is the whole difference between a
     CSS rectangle and something that looks laid down with water. Injected
     once, on first mount, so a page that never opens this view never pays
     for it. */
  function ensureFilter() {
    if (document.getElementById('wcEdge')) return;
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'wc-defs');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.innerHTML =
      '<filter id="wcEdge" x="-12%" y="-12%" width="124%" height="124%" color-interpolation-filters="sRGB">' +
        '<feTurbulence type="fractalNoise" baseFrequency="0.07 0.18" numOctaves="4" seed="11" result="noise"/>' +
        '<feDisplacementMap in="SourceGraphic" in2="noise" scale="2.4" xChannelSelector="R" yChannelSelector="G"/>' +
      '</filter>';
    document.body.appendChild(svg);
  }

  var mounted = null;

  window.BELibrary = {
    /* Draw the shelves into `host`. Safe to call again — a second call just
       re-chunks the rows, which is what the width watcher below wants. */
    mount: function (host) {
      if (!host) return;
      ensureFilter();
      document.documentElement.setAttribute('data-paint', 'on');
      render(host);
      if (mounted !== host) {
        wireCard(host);
        mounted = host;
      }
    },

    /* Re-chunk only when the shelves would actually fall differently — not on
       every pixel of a window drag. */
    reflow: function (host) {
      if (!host || !host.firstChild) return;
      if (Math.abs(host.clientWidth - Number(host.getAttribute('data-w'))) > 24) render(host);
    }
  };
})();
