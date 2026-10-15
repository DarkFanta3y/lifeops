// 照搬 dsh-context fileActivity.ts：文件图标映射、路径显示与按文件聚合（截止到所选步骤）。
const DIR_BUCKETS = [
  [['test', 'tests', '__tests__', 'spec', 'specs', 'e2e'], '🧪', 'files.glyph.tests'],
  [['doc', 'docs', 'documentation'], '📚', 'files.glyph.docs'],
  [['node_modules', 'vendor', 'third_party', 'third-party', 'packages'], '📦', 'files.glyph.deps'],
  [['dist', 'build', 'out', 'target', 'release', 'debug', 'coverage', 'artifacts'], '🏗️', 'files.glyph.build'],
  [['scripts', 'tools', 'bin'], '🛠️', 'files.glyph.scripts'],
  [['config', 'configs', 'settings', '.config'], '⚙️', 'files.glyph.config'],
  [['assets', 'static', 'public', 'images', 'fonts', 'icons', 'media'], '🎨', 'files.glyph.assets'],
]

const LOCK_NAMES = ['package-lock.json', 'pnpm-lock.yaml', 'npm-shrinkwrap.json']
const MAKE_NAMES = ['makefile', 'justfile', 'cmakelists.txt']
const TEST_NAME = /(^|[^a-z0-9])test([^a-z0-9]|$)|\.test\./

const CODE_LANGS = [
  [['tsx'], 'TSX', '#3178c6', 'files.glyph.lang.ts'],
  [['ts'], 'TS', '#3178c6', 'files.glyph.lang.ts'],
  [['js', 'jsx', 'mjs', 'cjs'], 'JS', '#f7df1e', 'files.glyph.lang.js'],
  [['py', 'pyi', 'pyw'], 'PY', '#3572a5', 'files.glyph.python'],
  [['ipynb'], 'NB', '#da5b0b', 'files.glyph.notebook'],
  [['go'], 'GO', '#00add8', 'files.glyph.lang.go'],
  [['rs'], 'RS', '#dea584', 'files.glyph.lang.rust'],
  [['java'], 'JV', '#b07219', 'files.glyph.lang.java'],
  [['kt', 'kts'], 'KT', '#a97bff', 'files.glyph.lang.kotlin'],
  [['rb'], 'RB', '#701516', 'files.glyph.lang.ruby'],
  [['php'], 'PHP', '#4f5d95', 'files.glyph.lang.php'],
  [['c', 'h'], 'C', '#555555', 'files.glyph.lang.c'],
  [['cpp', 'cc', 'cxx', 'hpp'], 'C++', '#f34b7d', 'files.glyph.lang.cpp'],
  [['cs'], 'C#', '#178600', 'files.glyph.lang.csharp'],
  [['scala'], 'SC', '#c22d40', 'files.glyph.lang.scala'],
  [['lua'], 'LUA', '#000080', 'files.glyph.lang.lua'],
  [['dart'], 'DA', '#00b4ab', 'files.glyph.lang.dart'],
  [['swift'], 'SW', '#f05138', 'files.glyph.lang.swift'],
  [['vue'], 'VUE', '#41b883', 'files.glyph.lang.vue'],
  [['svelte'], 'SV', '#ff3e00', 'files.glyph.lang.svelte'],
  [['sh', 'bash', 'zsh', 'fish', 'ps1'], 'SH', '#89e051', 'files.glyph.shell'],
  [['html', 'htm', 'xhtml'], 'HT', '#e34c26', 'files.glyph.lang.html'],
  [['css', 'scss', 'sass', 'less', 'styl'], 'CSS', '#563d7c', 'files.glyph.style'],
  [['sql'], 'SQL', '#e38c00', 'files.glyph.database'],
]

function badgeTextColor(hex) {
  const n = parseInt(hex.slice(1), 16)
  const luminance = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255
  return luminance < 0.6 ? '#ffffff' : '#1f2328'
}

const EXT_BUCKETS = [
  [['yaml', 'yml', 'toml', 'ini', 'conf', 'cfg', 'properties', 'env'], '⚙️', 'files.glyph.config'],
  [['json', 'jsonc', 'json5', 'jsonl', 'ndjson', 'xml'], '🧾', 'files.glyph.data'],
  [['md', 'mdx', 'markdown', 'rst', 'adoc', 'org'], '📝', 'files.glyph.markdown'],
  [['log'], '📜', 'files.glyph.log'],
  [['csv', 'tsv', 'xls', 'xlsx', 'ods'], '📊', 'files.glyph.sheet'],
  [['pdf', 'doc', 'docx', 'odt', 'rtf'], '📕', 'files.glyph.document'],
  [['zip', 'gz', 'tgz', 'tar', 'bz2', 'xz', '7z', 'rar', 'jar'], '🗜️', 'files.glyph.archive'],
  [['ttf', 'otf', 'woff', 'woff2', 'eot'], '🔤', 'files.glyph.font'],
  [['mp4', 'mov', 'mkv', 'webm', 'mp3', 'wav', 'flac', 'ogg'], '🎬', 'files.glyph.media'],
]

function dirGlyph(base) {
  if (base === '' || base === '.') return { glyph: '🏠', tip: 'files.glyph.root' }
  const name = base.toLowerCase()
  for (const [names, glyph, tip] of DIR_BUCKETS) {
    if (names.includes(name)) return { glyph, tip }
  }
  if (name.startsWith('.')) return { glyph: '🗄️', tip: 'files.glyph.hidden' }
  return { glyph: '📁', tip: 'files.form.dir' }
}

function fileGlyph(base) {
  const name = base.toLowerCase()
  const dot = name.lastIndexOf('.')
  // A dot at position 0 is a dotfile, not an extension — `.env` below reads by name.
  const ext = dot > 0 ? name.slice(dot + 1) : ''
  if (name.endsWith('.lock') || LOCK_NAMES.includes(name)) return { glyph: '🔒', tip: 'files.glyph.lock' }
  if (TEST_NAME.test(name)) return { glyph: '🧪', tip: 'files.glyph.tests' }
  if (name === 'dockerfile' || name.startsWith('dockerfile.')) return { glyph: '🐳', tip: 'files.glyph.docker' }
  if (MAKE_NAMES.includes(name)) return { glyph: '🛠️', tip: 'files.glyph.scripts' }
  if (name === '.gitignore' || name === '.gitattributes') return { glyph: '🚫', tip: 'files.glyph.ignore' }
  if (name === 'license' || name.startsWith('license.') || name === 'copying') return { glyph: '⚖️', tip: 'files.glyph.license' }
  if (name === '.env' || name.startsWith('.env.')) return { glyph: '⚙️', tip: 'files.glyph.config' }
  if (ext !== '') {
    for (const [exts, label, color, tip] of CODE_LANGS) {
      if (exts.includes(ext)) return { glyph: label, tip, color, text: badgeTextColor(color) }
    }
    for (const [exts, glyph, tip] of EXT_BUCKETS) {
      if (exts.includes(ext)) return { glyph, tip }
    }
  }
  return { glyph: '📄', tip: 'files.form.text' }
}

export function glyphOf(path, form) {
  if (form === 'image') return { glyph: '🖼', tip: 'files.form.image' }
  const trimmed = path.endsWith('/') ? path.slice(0, -1) : path
  const base = trimmed.slice(trimmed.lastIndexOf('/') + 1)
  return form === 'dir' ? dirGlyph(base) : fileGlyph(base)
}

const DRIVE_PATH = /^[a-zA-Z]:[\\/]/

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg|bmp|ico|avif)$/i;

export function formOf(path) {
  if (IMAGE_EXT.test(path)) return 'image';
  if (path.endsWith('/')) return 'dir';
  return 'text';
}

function bareOf(remainder) {
  const bare = remainder.replace(/^(?:\.\/)+/, '');
  return bare !== '' ? bare : remainder;
}

export function displayPathOf(path, workspace) {
  const root = workspace && workspace.length > 1 ? workspace.replace(/\/+$/, '') : undefined;
  if (root) {
    if (path === root || path === root + '/') return './';
    if (path.startsWith(root + '/')) return bareOf(path.slice(root.length + 1));
  }
  if (path.startsWith('/') || DRIVE_PATH.test(path)) return path;
  return bareOf(path);
}

// before：只统计时间不晚于该时刻的操作（跟随趋势图选中的步骤）；null 表示全部。
export function aggregateOps(ops, before = null) {
  const totals = { read: { files: 0, ops: 0 }, write: { files: 0, ops: 0 }, search: { files: 0, ops: 0 }, added: 0, removed: 0 };
  const byPath = new Map();
  for (const op of ops) {
    if (before !== null && (op.time ?? 0) > before) continue;
    totals[op.kind].ops++;
    let entry = byPath.get(op.path);
    if (!entry) {
      entry = { path: op.path, form: op.pattern ? 'text' : formOf(op.path), reads: 0, writes: 0, searches: 0,
        added: 0, removed: 0, errs: 0, ops: [], ...(op.pattern ? { pattern: true } : {}) };
      byPath.set(op.path, entry);
    }
    if (op.kind === 'read') entry.reads++; else if (op.kind === 'write') entry.writes++; else entry.searches++;
    entry.added += op.added;
    entry.removed += op.removed;
    if (op.err) entry.errs++;
    entry.ops.push(op);
  }
  const entries = [...byPath.values()];
  for (const e of entries) {
    e.ops.sort((a, b) => b.seq - a.seq);
    if (e.reads > 0) totals.read.files++;
    if (e.writes > 0) totals.write.files++;
    if (e.searches > 0) totals.search.files++;
    totals.added += e.added;
    totals.removed += e.removed;
  }
  entries.sort((a, b) => b.ops[0].seq - a.ops[0].seq);
  return { entries, totals };
}
