/**
 * Shared header behaviors: live GitHub star counter, live IST clock.
 * Loaded by every page that includes the .header-github component.
 */

/* ── Live Indian Standard Time ───────────────────────────────────────────
 * Always IST (UTC+5:30) regardless of where the reader is, so the time
 * shown is the project's home clock rather than the visitor's. Intl does
 * the zone conversion, so this stays correct without any offset maths.
 */
(function () {
  var ZONE = 'Asia/Kolkata';

  // Two formatters, built once: rebuilding per tick is needlessly expensive.
  var dayFmt = new Intl.DateTimeFormat('en-IN', {
    timeZone: ZONE, weekday: 'short', day: '2-digit', month: 'short',
  });
  var timeFmt = new Intl.DateTimeFormat('en-IN', {
    timeZone: ZONE, hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  });

  function mount() {
    var host = document.querySelector('.header-inner');
    if (!host || document.querySelector('.header-clock')) return null;

    var el = document.createElement('time');
    el.className = 'header-clock';
    // No aria-live: a value that changes every second would flood a screen
    // reader. The static label describes it; the digits are decorative.
    el.setAttribute('aria-label', 'Current time in India Standard Time');
    el.title = 'India Standard Time (UTC+5:30)';

    // Last child = far right of the header, after the theme toggle.
    host.appendChild(el);
    return el;
  }

  function tick(el) {
    var now = new Date();
    el.dateTime = now.toISOString();
    el.innerHTML =
      '<span class="clock-day">' + dayFmt.format(now).toUpperCase().replace(/,/g, '') + '</span>' +
      '<span class="clock-time">' + timeFmt.format(now) + '</span>' +
      '<span class="clock-zone">IST</span>';
  }

  function start() {
    var el = mount();
    if (!el) return;
    tick(el);
    // Align the first tick to the next whole second so the display doesn't
    // visibly drift, then fall into a steady 1s cadence.
    setTimeout(function () {
      tick(el);
      setInterval(function () { tick(el); }, 1000);
    }, 1000 - (Date.now() % 1000));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();

(function () {
  var REPO = 'ritikshub/buildingbackend';
  var CACHE_KEY = 'gh:stars:' + REPO;
  var CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes

  function format(n) {
    if (n >= 10000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
    return String(n);
  }

  function paint(n) {
    // The header's star badge was removed; the homepage masthead button is
    // the only remaining consumer, so this is the one selector left.
    var els = document.querySelectorAll('[data-gh-stars="' + REPO + '"]');
    for (var i = 0; i < els.length; i++) {
      els[i].textContent = format(n);
      els[i].removeAttribute('data-loading');
    }
  }

  function readCache() {
    try {
      var raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (Date.now() - parsed.t > CACHE_TTL_MS) return null;
      return parsed.n;
    } catch (e) {
      return null;
    }
  }

  function writeCache(n) {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({ n: n, t: Date.now() }));
    } catch (e) {
      // localStorage may be disabled
    }
  }

  function load() {
    var cached = readCache();
    if (cached != null) {
      paint(cached);
      return;
    }
    fetch('https://api.github.com/repos/' + REPO, {
      headers: { Accept: 'application/vnd.github+json' },
    })
      .then(function (r) {
        if (!r.ok) throw new Error('gh ' + r.status);
        return r.json();
      })
      .then(function (data) {
        var n = data.stargazers_count;
        if (typeof n !== 'number') return;
        writeCache(n);
        paint(n);
      })
      .catch(function () {
        // Leave the placeholder; the link still works.
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
