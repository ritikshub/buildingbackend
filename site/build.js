#!/usr/bin/env node
/**
 * Build script for Building Backend website.
 * Parses README.md, ROADMAP.md, and glossary/terms.md from the repo root
 * and generates data.js with all phase/lesson/glossary data.
 *
 * Run: node site/build.js
 * Called automatically by GitHub Actions on every push.
 */

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const README_PATH = path.join(REPO_ROOT, 'README.md');
const ROADMAP_PATH = path.join(REPO_ROOT, 'ROADMAP.md');
const GLOSSARY_PATH = path.join(REPO_ROOT, 'glossary', 'terms.md');
const OUTPUT_PATH = path.join(__dirname, 'data.js');

const REPO_URL = 'https://github.com/ritikshub/buildingbackend';
const GITHUB_BASE = `${REPO_URL}/tree/main/`;
const SITE_ORIGIN = 'https://buildingbackend.vercel.app';

// GITHUB_BASE lesson url -> site path "phases/<phase>/<lesson>"
function lessonPath(url) {
  if (!url) return null;
  const m = url.match(/(phases\/[^/]+\/[^/]+)\/?$/);
  return m ? m[1] : null;
}

// ─── Parse ROADMAP.md for lesson statuses ────────────────────────────
function parseRoadmap(content) {
  const statuses = {}; // { "Phase 0": { phaseStatus, lessons: { "Dev Environment": "complete" } } }
  let currentPhase = null;
  let currentPhaseStatus = null;

  for (const line of content.split(/\r?\n/)) {
    // Match phase headers like: ## Phase 0: Foundations — ✅
    const phaseMatch = line.match(/^##\s+Phase\s+(\d+).*?—\s*(✅|🚧|⬚)/);
    if (phaseMatch) {
      const phaseId = parseInt(phaseMatch[1]);
      const statusEmoji = phaseMatch[2];
      currentPhaseStatus = statusEmoji === '✅' ? 'complete' : statusEmoji === '🚧' ? 'in-progress' : 'planned';
      currentPhase = `Phase ${phaseId}`;
      statuses[currentPhase] = { phaseStatus: currentPhaseStatus, lessons: {} };
      continue;
    }

    // Match lesson rows like: | 01 | Dev Environment | ✅ |
    if (currentPhase) {
      const lessonMatch = line.match(/^\|\s*\d+\s*\|\s*(.+?)\s*\|\s*(✅|🚧|⬚)\s*\|/);
      if (lessonMatch) {
        const lessonName = lessonMatch[1].trim();
        const statusEmoji = lessonMatch[2];
        const status = statusEmoji === '✅' ? 'complete' : statusEmoji === '🚧' ? 'in-progress' : 'planned';
        statuses[currentPhase].lessons[lessonName] = status;
      }
    }
  }

  return statuses;
}

// ─── Parse README.md for phases and lessons ──────────────────────────
function parseReadme(content, roadmapStatuses) {
  const phases = [];

  // Split into phase blocks
  // Phase 0 is in a <table> block, phases 1-14 are in <details> blocks
  // We'll parse line by line to extract phase headers and lesson tables

  const lines = content.split(/\r?\n/);
  let currentPhase = null;
  let inLessonTable = false;
  let isCapstoneTable = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Match Phase header - multiple formats supported:
    // Old: ### Phase 0: Foundations `11 lessons`
    // Old: <summary><strong>Phase 1: Networking and Protocols</strong> <code>14 lessons</code> ... <em>Description</em></summary>
    // New: ### ![](https://img.shields.io/badge/Phase_0-Setup_&_Tooling-95A5A6?style=for-the-badge) `12 lessons`
    // New: <summary><b>Phase 1 — Networking and Protocols</b> &nbsp;<code>14 lessons</code>&nbsp; <em>Description</em></summary>
    const phaseHeaderMatch =
      line.match(/###\s+Phase\s+(\d+):\s+(.+?)\s*`(\d+)\s+lessons?`/) ||
      line.match(/###\s+!\[\]\([^)]*?Phase[_\s]+(\d+)[-_]([^?)]+?)-[A-F0-9]{6}[^)]*\)\s*`(\d+)\s+lessons?`/i);
    const detailsHeaderMatch =
      line.match(/<summary><strong>Phase\s+(\d+):\s+(.+?)<\/strong>\s*<code>(\d+)\s+(?:lessons?|projects?)<\/code>.*?<em>(.*?)<\/em>/) ||
      line.match(/<summary>\s*<b>\s*(?:[^\w\s]+\s+)?Phase\s+(\d+)\s*[—\-:]\s*(.+?)<\/b>.*?<code>(\d+)\s+(?:lessons?|projects?)<\/code>.*?<em>(.*?)<\/em>/);

    if (phaseHeaderMatch) {
      const [, idStr, rawName] = phaseHeaderMatch;
      const id = parseInt(idStr);
      const name = rawName.replace(/_/g, ' ').trim();
      // Look for the description on the next line (blockquote)
      let desc = '';
      for (let j = i + 1; j < Math.min(i + 5, lines.length); j++) {
        if (lines[j].startsWith('>')) {
          desc = lines[j].replace(/^>\s*/, '').trim();
          break;
        }
      }
      const roadmapKey = `Phase ${id}`;
      const phaseStatus = roadmapStatuses[roadmapKey]?.phaseStatus || 'planned';
      currentPhase = { id, name: name.trim(), status: phaseStatus, desc, lessons: [] };
      phases.push(currentPhase);
      inLessonTable = false;
      continue;
    }

    if (detailsHeaderMatch) {
      const [, idStr, name, , desc] = detailsHeaderMatch;
      const id = parseInt(idStr);
      const roadmapKey = `Phase ${id}`;
      const phaseStatus = roadmapStatuses[roadmapKey]?.phaseStatus || 'planned';
      currentPhase = { id, name: name.trim(), status: phaseStatus, desc: desc?.trim() || '', lessons: [] };
      phases.push(currentPhase);
      inLessonTable = false;
      continue;
    }

    // Detect start of lesson table
    if (currentPhase && line.match(/^\|\s*#\s*\|\s*Lesson/)) {
      inLessonTable = true;
      isCapstoneTable = false;
      continue;
    }

    // Skip table separator
    if (inLessonTable && line.match(/^\|[\s:|-]+\|$/)) {
      continue;
    }

    // Parse lesson rows
    if (inLessonTable && currentPhase && line.startsWith('|')) {
      // | 01 | [Bits and Bytes](phases/00-foundations/01-bits-and-bytes/) | Build | Python |
      // | 02 | Text and Encoding | Build | Python |
      const cols = line.split('|').map(c => c.trim()).filter(c => c.length > 0);
      if (cols.length >= 4) {
        const lessonCol = cols[1];
        const typeRaw = cols[2];
        const langRaw = cols[3];

        // Type may be plain ("Build") or a shield image: ![Build](https://...)
        const typeBadgeMatch = typeRaw.match(/!\[([^\]]+)\]/);
        const type = typeBadgeMatch ? typeBadgeMatch[1] : typeRaw;

        // Lang may be plain ("Python, Rust") or emoji flags (🐍 🟦 🦀 🟣 ⚛️)
        const EMOJI_LANG = {
          '🐍': 'Python',
          '🟦': 'TypeScript',
          '🦀': 'Rust',
          '⚛️': 'React',
          '⚛': 'React',
        };
        let lang = langRaw;
        if (/[\uD800-\uDBFF\u2600-\u27BF\u1F300-\u1FAFF]/.test(langRaw) || /[🐍🟦🦀🟣⚛]/u.test(langRaw)) {
          const tokens = Array.from(langRaw)
            .map(ch => EMOJI_LANG[ch])
            .filter(Boolean);
          if (tokens.length) lang = [...new Set(tokens)].join(', ');
          else if (langRaw.trim() === '—' || langRaw.trim() === '-') lang = '';
        }
        if (lang === '—' || lang === '-') lang = '';

        // Check if lesson has a link (meaning it has content)
        const linkMatch = lessonCol.match(/\[(.+?)\]\((.+?)\)/);
        let lessonName, url;
        if (linkMatch) {
          lessonName = linkMatch[1];
          const relativePath = linkMatch[2];
          url = GITHUB_BASE + relativePath.replace(/^\//, '');
        } else {
          lessonName = lessonCol;
          url = null;
        }

        // Get status from roadmap
        const roadmapKey = `Phase ${currentPhase.id}`;
        const roadmapPhase = roadmapStatuses[roadmapKey];
        let status = 'planned';
        if (roadmapPhase) {
          // Try to find matching lesson by fuzzy match
          const lessonNameClean = lessonName.replace(/[-–—:]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
          for (const [rName, rStatus] of Object.entries(roadmapPhase.lessons)) {
            const rNameClean = rName.replace(/[-–—:]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
            if (rNameClean.includes(lessonNameClean) || lessonNameClean.includes(rNameClean) ||
                rNameClean.split(' ').slice(0, 3).join(' ') === lessonNameClean.split(' ').slice(0, 3).join(' ')) {
              status = rStatus;
              break;
            }
          }
        }

        // If it has a link, it's at least complete (override roadmap if needed)
        if (url && status === 'planned') {
          status = 'complete';
        }

        // Capstone tables use the middle column for prerequisite phase tokens
        // (e.g., "P11 P13 P14"), not a Build/Learn enum. Keep `type` on the
        // Build/Learn axis so CSS selectors (data-type="Build"/"Learn") stay
        // valid, and emit the prereq string in a dedicated `combines` field.
        const lessonEntry = {
          name: lessonName.trim(),
          status,
          type: isCapstoneTable ? 'Capstone' : type.trim(),
          lang: lang.trim() || '—',
          ...(isCapstoneTable && { combines: type.trim() }),
          ...(url && { url }),
        };
        currentPhase.lessons.push(lessonEntry);
      }
    }

    // End of table
    if (inLessonTable && (line.match(/<\/td>/) || line.match(/<\/details>/) || (line.trim() === '' && i + 1 < lines.length && !lines[i + 1].startsWith('|')))) {
      inLessonTable = false;
    }

    // Also detect capstone table format (# | Project | Combines | Lang)
    if (currentPhase && line.match(/^\|\s*#\s*\|\s*Project/)) {
      inLessonTable = true;
      isCapstoneTable = true;
      continue;
    }
  }

  return phases;
}

// ─── Extract lesson summary + keywords from docs/en.md ───────────────
/**
 * Single-pass read of a lesson's docs/en.md.
 *
 * Returns:
 *   summary  : first `> blockquote` line (the lesson's one-liner motto).
 *   keywords: all `### H3` heading texts joined by ' · '.
 *              H3 headings are the densest vocabulary in a lesson doc
 *              (e.g. "Scaled dot-product · Causal masking · KV cache"),
 *              so they extend search coverage without bloating data.js.
 *
 *   words   : prose word count, used to show how long a lesson is.
 *
 * Both text fields are empty strings (and words is 0) when the file is absent
 * or has no matching content, expected for planned lessons with no docs yet.
 */
function extractLessonMeta(relPath) {
  const docPath = path.join(REPO_ROOT, relPath, 'docs', 'en.md');
  const result = { summary: '', keywords: '', words: 0 };
  try {
    const lines = fs.readFileSync(docPath, 'utf8').split(/\r?\n/);
    const h3s = [];
    let inFence = false;
    for (const raw of lines) {
      const line = raw.trim();

      // Fenced code is skipped: it's read at a very different pace than prose,
      // so counting it would inflate the reading estimate.
      if (/^(```|~~~)/.test(line)) {
        inFence = !inFence;
        continue;
      }
      if (inFence) continue;

      if (!result.summary && line.startsWith('> ') && line.length > 3) {
        const s = line.slice(2).trim();
        result.summary = s.length > 180 ? s.slice(0, 177) + '…' : s;
      }
      if (line.startsWith('### ')) {
        const heading = line.slice(4).trim();
        if (heading) h3s.push(heading);
      }
      result.words += countProseWords(line);
    }
    if (h3s.length) result.keywords = h3s.join(' · ');
  } catch (_) {
    // File absent or unreadable, expected for planned lessons.
  }
  return result;
}

/**
 * Word count for a single line of markdown prose. Strips the syntax that
 * carries no reading time so the number tracks effort, not file size.
 * Fenced code blocks are excluded by the caller.
 */
function countProseWords(line) {
  const text = line
    .replace(/`[^`]*`/g, ' ')                   // inline code
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')  // links/images → keep the label
    .replace(/<[^>]+>/g, ' ')                   // raw HTML tags
    .replace(/^[#>\-*+]+\s*/, '')               // heading / quote / bullet markers
    .replace(/^\d+\.\s+/, '')                   // ordered list markers
    .replace(/[|*_~]/g, ' ');                   // table pipes, emphasis
  // A token counts only if it contains a letter or digit, which drops table
  // rules (---), stray punctuation and bare symbols.
  return text.split(/\s+/).filter(t => /[A-Za-z0-9]/.test(t)).length;
}

// ─── Parse glossary/terms.md ──────────────────────────────────────────
function parseGlossary(content) {
  const terms = [];
  let currentTerm = null;

  for (const line of content.split(/\r?\n/)) {
    // Match term headers: ### ACID or ### ABAC (Attribute-Based Access Control)
    const termMatch = line.match(/^###\s+(.+)/);
    if (termMatch) {
      if (currentTerm && currentTerm.says && currentTerm.means) {
        terms.push(currentTerm);
      }
      currentTerm = { term: termMatch[1].trim(), says: '', means: '' };
      continue;
    }

    if (!currentTerm) continue;

    // Match "What people say" line
    const saysMatch = line.match(/\*\*What people say:\*\*\s*"?(.+?)"?\s*$/);
    if (saysMatch) {
      currentTerm.says = saysMatch[1].replace(/^"/, '').replace(/"$/, '').trim();
      continue;
    }

    // Match "What it actually means" line
    const meansMatch = line.match(/\*\*What it actually means:\*\*\s*(.+)/);
    if (meansMatch) {
      currentTerm.means = meansMatch[1].trim();
      continue;
    }
  }

  // Push the last term
  if (currentTerm && currentTerm.says && currentTerm.means) {
    terms.push(currentTerm);
  }

  return terms;
}

// ─── Discover outputs/ artifacts (skills / prompts / agents) ──────────
function parseFrontmatter(text) {
  if (!text.startsWith('---')) return null;
  const end = text.indexOf('\n---', 4);
  if (end === -1) return null;
  const block = text.slice(4, end);
  const result = {};
  for (const raw of block.split(/\r?\n/)) {
    const line = raw.trimEnd();
    if (!line || line.startsWith('#') || !line.includes(':')) continue;
    const idx = line.indexOf(':');
    const key = line.slice(0, idx).trim();
    let value = line.slice(idx + 1).trim();
    if (value.startsWith('[') && value.endsWith(']')) {
      const inner = value.slice(1, -1).trim();
      result[key] = inner
        ? inner.split(',').map(s => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean)
        : [];
    } else if ((value.startsWith('"') && value.endsWith('"')) ||
               (value.startsWith("'") && value.endsWith("'"))) {
      result[key] = value.slice(1, -1);
    } else {
      result[key] = value;
    }
  }
  return result;
}

function discoverArtifacts() {
  const artifacts = [];
  const phasesDir = path.join(REPO_ROOT, 'phases');
  if (!fs.existsSync(phasesDir)) return artifacts;
  const VALID_TYPES = ['prompt', 'checklist', 'runbook'];
  for (const phaseDirName of fs.readdirSync(phasesDir).sort()) {
    const phaseMatch = phaseDirName.match(/^([0-9]{2})-([a-z0-9-]+)$/);
    if (!phaseMatch) continue;
    const phaseId = parseInt(phaseMatch[1], 10);
    const phaseDir = path.join(phasesDir, phaseDirName);
    for (const lessonDirName of fs.readdirSync(phaseDir).sort()) {
      const lessonMatch = lessonDirName.match(/^([0-9]{2})-([a-z0-9-]+)$/);
      if (!lessonMatch) continue;
      const lessonId = parseInt(lessonMatch[1], 10);
      const lessonRel = `phases/${phaseDirName}/${lessonDirName}`;
      const outputsDir = path.join(phaseDir, lessonDirName, 'outputs');
      if (fs.existsSync(outputsDir)) {
        for (const file of fs.readdirSync(outputsDir).sort()) {
          if (!file.endsWith('.md')) continue;
          const stem = file.replace(/\.md$/, '');
          const type = VALID_TYPES.find(t => stem.startsWith(`${t}-`));
          if (!type) continue;
          let meta = {};
          try {
            meta = parseFrontmatter(fs.readFileSync(path.join(outputsDir, file), 'utf8')) || {};
          } catch (_) {}
          artifacts.push({
            kind: type,
            name: (meta.name || stem).trim(),
            description: (meta.description || '').trim(),
            tags: Array.isArray(meta.tags) ? meta.tags : [],
            phase: phaseId,
            lesson: lessonId,
            lessonPath: lessonRel,
            file: `${lessonRel}/outputs/${file}`,
          });
        }
      }
      const missionPath = path.join(phaseDir, lessonDirName, 'mission.md');
      if (fs.existsSync(missionPath)) {
        let firstLine = '';
        try {
          firstLine = fs.readFileSync(missionPath, 'utf8').split(/\r?\n/)[0].replace(/^#\s+/, '').trim();
        } catch (_) {}
        artifacts.push({
          kind: 'mission',
          name: firstLine || `${lessonDirName} mission`,
          description: '',
          tags: [],
          phase: phaseId,
          lesson: lessonId,
          lessonPath: lessonRel,
          file: `${lessonRel}/mission.md`,
        });
      }
    }
  }
  return artifacts;
}

// ─── Manifest of each lesson's code/ + outputs/ files ─────────────────
// Baked into data.js so the lesson page can list, describe, and link every
// file with zero network calls, so it works offline and needs no GitHub repo.
// Shape: { "phases/<phase>/<lesson>": { code: [{name,size}], outputs: [{name,size,desc}] } }
function discoverLessonFiles() {
  const manifest = {};
  const phasesDir = path.join(REPO_ROOT, 'phases');
  if (!fs.existsSync(phasesDir)) return manifest;

  function listDir(dir, withDesc) {
    if (!fs.existsSync(dir)) return [];
    const files = [];
    for (const name of fs.readdirSync(dir).sort()) {
      if (name.startsWith('.')) continue;
      const fp = path.join(dir, name);
      let stat;
      try { stat = fs.statSync(fp); } catch (_) { continue; }
      if (!stat.isFile()) continue;
      const entry = { name, size: stat.size };
      if (withDesc) {
        let desc = '';
        try {
          const meta = parseFrontmatter(fs.readFileSync(fp, 'utf8'));
          if (meta && meta.description) desc = String(meta.description).trim();
        } catch (_) {}
        entry.desc = desc;
      }
      files.push(entry);
    }
    return files;
  }

  for (const phaseDirName of fs.readdirSync(phasesDir).sort()) {
    if (!/^\d{2}-[a-z0-9-]+$/.test(phaseDirName)) continue;
    const phaseDir = path.join(phasesDir, phaseDirName);
    try { if (!fs.statSync(phaseDir).isDirectory()) continue; } catch (_) { continue; }
    for (const lessonDirName of fs.readdirSync(phaseDir).sort()) {
      if (!/^\d{2}-[a-z0-9-]+$/.test(lessonDirName)) continue;
      const lessonRel = `phases/${phaseDirName}/${lessonDirName}`;
      const lessonDir = path.join(phaseDir, lessonDirName);
      const entry = {};
      const code = listDir(path.join(lessonDir, 'code'), false);
      const outputs = listDir(path.join(lessonDir, 'outputs'), true);
      if (code.length) entry.code = code;
      if (outputs.length) entry.outputs = outputs;
      if (entry.code || entry.outputs) manifest[lessonRel] = entry;
    }
  }
  return manifest;
}

// ─── Bundle lesson content into site/ so the deployed site is self-contained ──
// The site is deployed with `site/` as the web root (Vercel outputDirectory),
// and the repo may not be published to GitHub. So mirror every lesson's docs,
// quiz, outputs, and code under `site/content/phases/…`, and have lesson.html
// fetch it with a site-root-relative base ("content/…"). Works identically in
// local `python -m http.server site` and on Vercel, with no GitHub dependency.
// Regenerated on every build and git-ignored (see .gitignore) so it never drifts.
function copyLessonContent() {
  const srcRoot = path.join(REPO_ROOT, 'phases');
  const contentRoot = path.join(__dirname, 'content');
  const destRoot = path.join(contentRoot, 'phases');
  // Wipe first so a deleted/renamed lesson can't leave a stale copy behind.
  fs.rmSync(contentRoot, { recursive: true, force: true });
  if (!fs.existsSync(srcRoot)) return 0;

  let count = 0;
  function copyDir(src, dest) {
    fs.mkdirSync(dest, { recursive: true });
    for (const name of fs.readdirSync(src)) {
      if (name.startsWith('.')) continue; // skip .DS_Store, etc.
      const s = path.join(src, name);
      const d = path.join(dest, name);
      let stat;
      try { stat = fs.statSync(s); } catch (_) { continue; }
      if (stat.isDirectory()) copyDir(s, d);
      else { fs.copyFileSync(s, d); count++; }
    }
  }
  copyDir(srcRoot, destRoot);
  return count;
}

// ─── Main build ──────────────────────────────────────────────────────
// Write the git ref this deploy was built from, so lesson.html fetches docs
// from the right branch (PR previews render their own edits, not main).
function writeBuildMeta() {
  let ref = process.env.VERCEL_GIT_COMMIT_REF || '';
  if (!ref) {
    try {
      ref = require('child_process')
        .execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'] })
        .trim();
    } catch (e) { ref = ''; }
  }
  if (!ref || ref === 'HEAD') ref = 'main';
  const js = '// Auto-generated by build.js on each deploy. Do not edit.\n'
    + 'window.__BE_REF = ' + JSON.stringify(ref) + ';\n';
  fs.writeFileSync(path.join(__dirname, 'build-meta.js'), js, 'utf8');
  console.log('   wrote build-meta.js (ref: ' + ref + ')');
}

function build() {
  console.log('📖 Reading source files...');
  writeBuildMeta();

  const readme = fs.readFileSync(README_PATH, 'utf8');
  const roadmap = fs.readFileSync(ROADMAP_PATH, 'utf8');
  const glossary = fs.readFileSync(GLOSSARY_PATH, 'utf8');

  console.log('🔍 Parsing ROADMAP.md...');
  const roadmapStatuses = parseRoadmap(roadmap);

  console.log('🔍 Parsing README.md...');
  const phases = parseReadme(readme, roadmapStatuses);

  console.log('🔍 Parsing glossary/terms.md...');
  const glossaryTerms = parseGlossary(glossary);

  console.log('🔍 Discovering outputs + Phase 14 missions...');
  const artifacts = discoverArtifacts();

  console.log('🗂  Building per-lesson code/outputs file manifest...');
  const lessonFiles = discoverLessonFiles();

  console.log('📦 Bundling lesson content into site/content/ ...');
  const bundledFiles = copyLessonContent();

  console.log('📚 Extracting lesson summaries + keywords + word counts from docs/en.md...');
  let summarized = 0, withKeywords = 0, withWords = 0, totalWords = 0;
  for (const phase of phases) {
    for (const lesson of phase.lessons) {
      if (lesson.url) {
        const relPath = lesson.url.replace(GITHUB_BASE, '').replace(/\/+$/, '');
        const meta = extractLessonMeta(relPath);
        if (meta.summary)  { lesson.summary  = meta.summary;  summarized++;   }
        if (meta.keywords) { lesson.keywords = meta.keywords; withKeywords++; }
        if (meta.words)    { lesson.words    = meta.words;    withWords++; totalWords += meta.words; }
      }
    }
  }

  // Stats
  let totalLessons = 0;
  let completeLessons = 0;
  phases.forEach(p => {
    totalLessons += p.lessons.length;
    completeLessons += p.lessons.filter(l => l.status === 'complete').length;
  });

  // Public-facing counts advertise only what a reader can actually open today.
  // totalLessons includes roadmap rows with no lesson folder behind them (the
  // Phase 13 capstones), so it would overstate the curriculum on every page.
  const writtenLessons = phases.reduce(
    (n, p) => n + p.lessons.filter(l => lessonPath(l.url)).length, 0);
  const writtenPhases = phases.filter(
    p => p.lessons.some(l => lessonPath(l.url))).length;

  console.log(`\n📊 Stats:`);
  console.log(`   Phases: ${phases.length} (${writtenPhases} with written lessons)`);
  console.log(`   Lessons: ${totalLessons} (${writtenLessons} written)`);
  console.log(`   Complete: ${completeLessons}`);
  console.log(`   Summaries: ${summarized}, Keywords: ${withKeywords}`);
  console.log(`   Word counts: ${withWords} lessons, ${totalWords.toLocaleString()} words total`);
  console.log(`   Glossary terms: ${glossaryTerms.length}`);
  console.log(`   Artifacts: ${artifacts.length}`);
  console.log(`   Lessons with files: ${Object.keys(lessonFiles).length}`);
  console.log(`   Bundled content files: ${bundledFiles}`);

  // Generate data.js
  const output = `// Auto-generated by build.js. Do not edit manually.
// Last built: ${new Date().toISOString()}

const PHASES = ${JSON.stringify(phases, null, 2)};

const GLOSSARY = ${JSON.stringify(glossaryTerms, null, 2)};

const ARTIFACTS = ${JSON.stringify(artifacts, null, 2)};

const LESSON_FILES = ${JSON.stringify(lessonFiles, null, 2)};
`;

  fs.writeFileSync(OUTPUT_PATH, output, 'utf8');
  console.log(`\n✅ Generated ${OUTPUT_PATH}`);

  syncHeaders();
  syncCounts(writtenLessons, writtenPhases, artifacts.length);
  syncReadme(writtenLessons);
  writeSitemap(phases, glossaryTerms.length);
  writeLlms(phases, glossaryTerms.length, artifacts.length);
}

// ─── sitemap.xml from the same PHASES the site renders ───────────────────
function writeSitemap(phases, glossaryCount) {
  const today = new Date().toISOString().slice(0, 10);
  const urls = [
    { loc: '/', priority: '1.0', freq: 'weekly' },
    { loc: '/catalog.html', priority: '0.8', freq: 'weekly' },
    { loc: '/prereqs.html', priority: '0.7', freq: 'monthly' },
  ];
  if (glossaryCount > 0) urls.push({ loc: '/jargon.html', priority: '0.6', freq: 'monthly' });
  urls.push({ loc: '/about.html', priority: '0.5', freq: 'monthly' });
  for (const phase of phases) {
    for (const l of phase.lessons) {
      const p = lessonPath(l.url);
      if (p) urls.push({ loc: '/lesson.html?path=' + p, priority: '0.6', freq: 'monthly' });
    }
  }
  const body = urls.map(u =>
    `  <url>\n    <loc>${SITE_ORIGIN}${u.loc}</loc>\n` +
    `    <lastmod>${today}</lastmod>\n    <changefreq>${u.freq}</changefreq>\n` +
    `    <priority>${u.priority}</priority>\n  </url>`).join('\n');
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
  fs.writeFileSync(path.join(__dirname, 'sitemap.xml'), xml, 'utf8');
  console.log(`   wrote sitemap.xml (${urls.length} URLs)`);
}

// ─── llms.txt: a link-rich map of the curriculum for AI agents ───────────
function writeLlms(phases, glossaryCount, artifactCount) {
  // written = lessons that resolve to a real path on disk; planned = everything on the roadmap.
  let written = 0, planned = 0;
  phases.forEach(p => {
    written += p.lessons.filter(l => lessonPath(l.url)).length;
    planned += p.lessons.length;
  });
  let out = `# Building Backend\n\n`;
  out += `> A free, open-source curriculum that builds every core backend primitive by hand. ${planned} lessons across ${phases.length} phases, ${written} written so far, from raw sockets to a deployed, observable fleet. Python, standard library only.\n\n`;
  out += `Canonical site: ${SITE_ORIGIN}\n`;
  out += `Source: https://github.com/ritikshub/buildingbackend\n`;
  out += `Jargon terms: ${glossaryCount} · Reusable outputs (prompts/skills/agents): ${artifactCount}\n\n`;
  for (const phase of phases) {
    out += `## Phase ${phase.id}: ${phase.name}\n`;
    if (phase.desc) out += `${phase.desc}\n`;
    out += `\n`;
    for (const l of phase.lessons) {
      const p = lessonPath(l.url);
      if (!p) continue;
      const note = l.summary ? `: ${l.summary}` : '';
      out += `- [${l.name}](${SITE_ORIGIN}/lesson.html?path=${p})${note}\n`;
    }
    out += `\n`;
  }
  out += `## Optional\n`;
  out += `- [Catalog](${SITE_ORIGIN}/catalog.html): full searchable lesson index\n`;
  out += `- [Roadmap](${SITE_ORIGIN}/prereqs.html): prerequisite ordering across phases\n`;
  if (glossaryCount > 0) out += `- [Jargon](${SITE_ORIGIN}/jargon.html): what people say vs what it actually means, for ${glossaryCount} terms\n`;
  fs.writeFileSync(path.join(__dirname, 'llms.txt'), out, 'utf8');
  console.log(`   wrote llms.txt`);
}

// ─── Regenerate README stats block + lessons badge from source ───────────
function syncReadme(lessons) {
  const readmePath = path.join(REPO_ROOT, 'README.md');
  if (!fs.existsSync(readmePath)) return;
  let md = fs.readFileSync(readmePath, 'utf8');
  const before = md;

  // Keep the lessons badge in sync with the live count (URL value + alt text)
  md = md.replace(/badge\/lessons-\d+-/g, `badge/lessons-${lessons}-`);
  md = md.replace(/alt="\d+ lessons"/g, `alt="${lessons} lessons"`);

  // Regenerate the traffic proof block from site/stats.json
  const statsPath = path.join(__dirname, 'stats.json');
  if (fs.existsSync(statsPath)) {
    try {
      const s = JSON.parse(fs.readFileSync(statsPath, 'utf8'));
      const fmt = n => Number(n).toLocaleString('en-US');
      const block =
        '<!-- STATS:START (generated from site/stats.json by build.js, do not edit by hand) -->\n' +
        `<p align="center"><sub><b>${fmt(s.visitors30d)}</b> readers &nbsp;·&nbsp; ` +
        `<b>${fmt(s.pageViews30d)}</b> page views in the last ${s.period} &nbsp;·&nbsp; ` +
        `as of ${s.updated}</sub></p>\n` +
        '<!-- STATS:END -->';
      const statsRe = /<!-- STATS:START[\s\S]*?<!-- STATS:END -->/;
      if (statsRe.test(md)) {
        md = md.replace(statsRe, block);
      } else {
        // Self-heal: re-insert the block if the markers were removed/mangled
        md = md.replace(/\n## How this works/, `\n${block}\n\n## How this works`);
      }
    } catch (err) {
      console.warn(`⚠️  README stats sync skipped: ${err.message}`);
    }
  }

  if (md !== before) {
    fs.writeFileSync(readmePath, md, 'utf8');
    console.log('   synced README stats + lessons badge');
  }
}

// ─── Keep marketing counts in sync (single source of truth = this build) ──
// ─── Single source of truth for the site header ─────────────────────────
// The header used to be copy-pasted into all six pages, and it drifted:
// lesson.html silently lost its "About" link, and a rename left one page on
// the old logo. It is generated from this one template on every build now, so
// the pages cannot disagree. The live IST clock is appended at runtime by
// header.js — it is deliberately not in this markup.
const NAV_LINKS = [
  { key: 'contents', href: 'index.html#contents', label: 'Contents' },
  { key: 'catalog',  href: 'catalog.html',        label: 'Catalog'  },
  { key: 'roadmap',  href: 'prereqs.html',        label: 'Roadmap'  },
  { key: 'jargon',   href: 'jargon.html',         label: 'Jargon'   },
  { key: 'about',    href: 'about.html',          label: 'About'    },
];

// Which nav item is "current" per page. lesson.html maps to nothing on
// purpose: an individual lesson is not one of the five nav destinations.
const PAGE_ACTIVE = {
  'index.html': 'contents',
  'catalog.html': 'catalog',
  'prereqs.html': 'roadmap',
  'jargon.html': 'jargon',
  'about.html': 'about',
  'lesson.html': null,
};

const SEARCH_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
const THEME_ICON = '<span class="theme-icon" id="themeIcon" aria-hidden="true"><svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg><svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg></span>';

function headerHtml(page) {
  const active = PAGE_ACTIVE[page];
  const links = NAV_LINKS.map(l => {
    // On the homepage, "Contents" is a same-page anchor, not a round trip.
    const href = (page === 'index.html' && l.key === 'contents') ? '#contents' : l.href;
    const cur = l.key === active ? ' aria-current="page"' : '';
    return `        <a href="${href}"${cur}>${l.label}</a>`;
  }).join('\n');

  return `  <header class="site-header">
    <div class="header-inner">
      <a href="index.html" class="logo">
        <span class="logo-icon" aria-hidden="true"></span> BUILDING BACKEND
      </a>
      <nav class="header-nav">
${links}
      </nav>
      <button class="search-toggle" type="button" data-cmd-palette
        aria-label="Search (⌘K)" title="Search (⌘K)">
        ${SEARCH_ICON}
      </button>
      <button class="theme-toggle" id="themeToggle" aria-label="Toggle theme" type="button">
        ${THEME_ICON}
      </button>
    </div>
  </header>`;
}

function syncHeaders() {
  const headerRe = /[ \t]*<header class="site-header">[\s\S]*?<\/header>/;
  for (const page of Object.keys(PAGE_ACTIVE)) {
    const p = path.join(__dirname, page);
    if (!fs.existsSync(p)) continue;
    const before = fs.readFileSync(p, 'utf8');
    if (!headerRe.test(before)) {
      console.warn(`   ⚠️  no <header> block found in ${page} — skipped`);
      continue;
    }
    const after = before.replace(headerRe, headerHtml(page));
    if (after !== before) {
      fs.writeFileSync(p, after, 'utf8');
      console.log(`   synced header in ${page}`);
    }
  }
}

function syncCounts(lessons, phaseCount, outputs) {
  const targets = ['index.html', 'catalog.html', 'lesson.html', 'prereqs.html', 'about.html', 'cmdpalette.js'];
  for (const f of targets) {
    const p = path.join(__dirname, f);
    if (!fs.existsSync(p)) continue;
    const before = fs.readFileSync(p, 'utf8');
    const after = before
      .replace(/\b\d+( backend engineering)? lessons\b/g, `${lessons}$1 lessons`)
      .replace(/\b\d+ phases\b/g, `${phaseCount} phases`)
      .replace(/\b\d+ outputs\b/g, `${outputs} outputs`);
    if (after !== before) {
      fs.writeFileSync(p, after, 'utf8');
      console.log(`   synced counts in ${f}`);
    }
  }
}

build();
