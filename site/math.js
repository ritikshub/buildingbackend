/* Math Behind Tech hub: live teasers, one per chapter, plus the "this page
 * arrived compressed" line. No dependencies. Each widget is the chapter's
 * central computation in a dozen lines, so what you type here is exactly
 * what the chapter works through by hand. */
(function () {
  function $(id) { return document.getElementById(id); }
  function row(k, v) {
    return '<div class="try-row"><div class="try-k">' + k + '</div><div class="try-v">' + v + '</div></div>';
  }
  function fmt(n) { return n.toLocaleString('en-US'); }

  /* ── Chapter 02 hook: how compressed was this very page? ────────────── */
  (function wire() {
    var el = $('wire');
    if (!el || !window.performance || !performance.getEntriesByType) return;
    var nav = performance.getEntriesByType('navigation')[0];
    if (!nav || !nav.encodedBodySize || !nav.decodedBodySize) return;
    if (nav.encodedBodySize >= nav.decodedBodySize) return; // served uncompressed (local dev)
    var pct = Math.round(100 - 100 * nav.encodedBodySize / nav.decodedBodySize);
    el.innerHTML = 'This page was <span class="live">' + fmt(nav.encodedBodySize) + ' bytes</span> on the wire and <span class="live">' +
      fmt(nav.decodedBodySize) + ' bytes</span> once unpacked, so it travelled <span class="live">' + pct + '% smaller</span>.';
  })();

  /* ── Chapter 01: RSA with public key (33, 3) and private key (33, 7) ─── */
  function modpow(b, e, m) {
    var r = 1; b %= m;
    while (e > 0) { if (e & 1) r = (r * b) % m; b = (b * b) % m; e >>= 1; }
    return r;
  }
  (function rsa() {
    var input = $('rsaIn'), out = $('rsaOut');
    if (!input || !out) return;
    function render() {
      var word = (input.value || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 10);
      if (!word) { out.innerHTML = row('Type a word', '<span class="try-muted">letters A to Z only</span>'); return; }
      var m = [], c = [], back = '';
      for (var i = 0; i < word.length; i++) {
        var v = word.charCodeAt(i) - 64;          // A = 1 … Z = 26, all below n = 33
        var cv = modpow(v, 3, 33);                 // lock: m³ mod 33
        m.push(v); c.push(cv);
        back += String.fromCharCode(modpow(cv, 7, 33) + 64);   // unlock: c⁷ mod 33
      }
      out.innerHTML =
        row(word + ' as numbers, A = 1 … Z = 26', m.join(' ')) +
        row('Locked with the public key (33, 3): m³ mod 33', '<b>' + c.join(' ') + '</b>') +
        row('Unlocked with the private key (33, 7): c⁷ mod 33', '<b>' + back + '</b>');
    }
    input.addEventListener('input', render);
    render();
  })();

  /* ── Chapter 02: Huffman code lengths for a word ───────────────────── */
  function huffmanBits(word) {
    var counts = {};
    for (var i = 0; i < word.length; i++) counts[word[i]] = (counts[word[i]] || 0) + 1;
    var nodes = Object.keys(counts).map(function (ch) { return { w: counts[ch], syms: [ch] }; });
    var len = {};
    Object.keys(counts).forEach(function (ch) { len[ch] = 0; });
    if (nodes.length === 1) len[nodes[0].syms[0]] = 1;        // a single symbol still needs one bit
    while (nodes.length > 1) {
      nodes.sort(function (a, b) { return a.w - b.w; });
      var a = nodes.shift(), b = nodes.shift();
      a.syms.concat(b.syms).forEach(function (ch) { len[ch] += 1; });   // one more bit for everything underneath
      nodes.push({ w: a.w + b.w, syms: a.syms.concat(b.syms) });
    }
    var bits = 0;
    Object.keys(counts).forEach(function (ch) { bits += counts[ch] * len[ch]; });
    return { bits: bits, symbols: Object.keys(counts).length, lengths: len };
  }
  (function huff() {
    var input = $('huffIn'), out = $('huffOut'), barA = $('barAscii'), barH = $('barHuff');
    if (!input || !out) return;
    function render() {
      var word = (input.value || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 24);
      if (!word) { out.innerHTML = row('Type a word', '<span class="try-muted">letters A to Z only</span>'); barA.style.width = barH.style.width = '0'; return; }
      var h = huffmanBits(word), ascii = word.length * 8;
      var saved = Math.round(100 - 100 * h.bits / ascii);
      var codes = Object.keys(h.lengths).sort(function (x, y) { return h.lengths[x] - h.lengths[y] || (x < y ? -1 : 1); })
        .map(function (ch) { return ch + '&thinsp;' + h.lengths[ch]; }).join(' · ');
      out.innerHTML =
        row(word.length + ' letters as ASCII, 8 bits each', ascii + ' bits') +
        row(h.symbols + ' distinct letters; bits per letter after Huffman', codes) +
        row('The whole word with Huffman', '<b>' + h.bits + ' bits</b>, ' + saved + '% smaller');
      barA.style.width = '100%';
      barH.style.width = (100 * h.bits / ascii) + '%';
    }
    input.addEventListener('input', render);
    render();
  })();

  /* ── Chapter 03: the birthday paradox ──────────────────────────────── */
  (function birthday() {
    var input = $('bdayIn'), out = $('bdayOut'), bar = $('barBday'), label = $('bdayN');
    if (!input || !out) return;
    function render() {
      var n = parseInt(input.value, 10) || 2;
      var pNone = 1;
      for (var i = 1; i < n; i++) pNone *= (365 - i) / 365;      // each newcomer avoids everyone before
      var p = 1 - pNone, pairs = n * (n - 1) / 2;
      label.textContent = n;
      out.innerHTML =
        row(n + ' people make this many pairs', fmt(pairs)) +
        row('Chance that no pair shares a birthday', (100 * pNone).toFixed(1) + '%') +
        row('Chance that at least one pair does', '<b>' + (100 * p).toFixed(1) + '%</b>');
      bar.style.width = (100 * p) + '%';
    }
    input.addEventListener('input', render);
    render();
  })();
})();
