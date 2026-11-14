// Host-side operations for the anki-workspace bundle.
//
// Every capability is implemented once here. The agent tools and the Web
// panel's JSON-RPC route both call these functions, so the two surfaces can
// never drift apart. Nothing in this file talks to Anki directly: the
// workspace's own `cli.py` / `anki_api.py` entry points remain the only path
// to the collection, exactly as AGENTS.md requires.

import { access, readFile, readdir, stat } from 'node:fs/promises'
import {
  basename,
  join,
  relative as relativePath,
  resolve as resolvePath,
  isAbsolute,
  sep,
} from 'node:path'

export const MONTHLY_REPORT_DIR = 'output/reports/ankir'

const DEFAULT_TIMEOUT_MS = 120_000
const MAX_CAPTURE_BYTES = 8 * 1024 * 1024
/** Do not inline a monthly report larger than this into the panel payload. */
const MAX_REPORT_BYTES = 2 * 1024 * 1024

/** Directory listing cap for the panel's path picker (read-only preview). */
export const MAX_BROWSE_ENTRIES = 500

/** 例句 deck：流水线主战场（见 `docs/anki-library.md`）。 */
export const DECK_EXAMPLE = '0-日本语学习::2-例句'

/** 素材生词 deck，与 `jp_decks.DECK_MINED` 保持一致。 */
export const DECK_MINED = '0-日本语学习::0-词汇::0-素材生词'

/** 卡片修正要读写的三个字段：cards.py 拿 Sentence 当骨架写 AINote / Sentence HTML。 */
export const CARD_FIX_FIELDS = ['Sentence', 'AINote', 'Sentence HTML']

/** 「获取当前单词」按钮读的字段：面板两个单词输入框都填 Word。 */
export const CURRENT_WORD_FIELD = 'Word'

/**
 * AnkiConnect `guiCurrentCard` 的原始返回 → 面板用的精简形状（纯函数，可离线测）。
 * null / 不在复习模式 → found:false；否则取 fields.Word.value（退化时取 Transliteration）。
 */
export function currentWordFromGuiCard(raw) {
  if (raw === null || raw === undefined || typeof raw !== 'object') {
    return { found: false, word: '', deckName: '' }
  }
  const fieldText = (name) => {
    const value = raw?.fields?.[name]
    if (value == null) return ''
    return String(typeof value === 'object' ? (value.value ?? '') : value).trim()
  }
  let word = fieldText(CURRENT_WORD_FIELD)
  if (word === '') word = fieldText('Transliteration')
  return {
    found: true,
    word,
    deckName: String(raw?.deckName ?? '').trim(),
    template: String(raw?.template ?? '').trim(),
  }
}

/**
 * `anki_api.py gui-current-word --json` 的返回 → 面板形状。
 *
 * CLI 打的是**扁平**结构（found/word/deckName/template，没有 raw 键）；
 * 只有担心版本漂移时才需要回退到原始 guiCurrentCard 形状（fields.Word…）。
 * 曾经这里只读 `parsed.raw`，于是 CLI 明明有词也永远被当成「没有当前卡」。
 */
export function currentWordFromCli(parsed) {
  if (parsed === null || parsed === undefined || typeof parsed !== 'object') {
    return { found: false, word: '', deckName: '', template: '' }
  }
  if (typeof parsed.found === 'boolean') {
    return {
      found: parsed.found,
      word: String(parsed.word ?? '').trim(),
      deckName: String(parsed.deckName ?? '').trim(),
      template: String(parsed.template ?? '').trim(),
    }
  }
  // 兼容：万一某版 CLI 改成包一层 raw（或直接透传 guiCurrentCard）。
  return currentWordFromGuiCard(parsed.raw ?? parsed)
}

export function tail(text, max = 6000) {
  const s = String(text ?? '')
  if (s.length <= max) return s
  return '…(前文省略)\n' + s.slice(s.length - max)
}

/**
 * Parse a JSON payload that may be preceded by the workspace dispatcher's
 * `→ script` banner (cli.py prints it on stdout). Returns null when no JSON
 * object/array can be recovered.
 */
export function extractJson(text) {
  const raw = String(text ?? '').trim()
  if (raw === '') return null
  try {
    return JSON.parse(raw)
  } catch {
    // Fall through to the embedded-payload scan.
  }
  // Try every `{`/`[` start, not just the first: the dispatcher banner can
  // contain braces when a workspace path is named like `{作品}`.
  const starts = []
  for (let i = 0; i < raw.length; i += 1) {
    if (raw[i] === '{' || raw[i] === '[') starts.push(i)
  }
  const lastBrace = Math.max(raw.lastIndexOf('}'), raw.lastIndexOf(']'))
  for (const start of starts) {
    if (lastBrace <= start) continue
    try {
      return JSON.parse(raw.slice(start, lastBrace + 1))
    } catch {
      // Try the next candidate start.
    }
  }
  return null
}

export function parseAnkiCheck(text) {
  const out = { version: null, decks: null, noteTypes: null, media: null }
  const grab = (re) => {
    const m = re.exec(String(text ?? ''))
    return m === null ? null : m[1]
  }
  const version = grab(/版本\s+([^\s\r\n]+)/)
  const decks = grab(/牌组\s+(\d+)\s*个/)
  const noteTypes = grab(/笔记类型\s+(\d+)\s*个/)
  const media = grab(/媒体文件\s+(\d+)\s*个/)
  if (version !== null) out.version = version
  if (decks !== null) out.decks = Number(decks)
  if (noteTypes !== null) out.noteTypes = Number(noteTypes)
  if (media !== null) out.media = Number(media)
  return out
}

/**
 * Parse the human-readable output of `mine_audio.py plan` into a list of
 * candidate cards for the Word Audio tab. Each data row in the script's table
 * has the shape:
 *
 *   <word>  <reading>  <wordAudioRef or empty marker>  <sentenceAudioRef>  <action>
 *
 * The word form is the first token; the reading is the second (katakana /
 * hiragana only); the two audio references are either `[sound:file.mp3]`
 * strings or an empty placeholder the script prints for a blank field. The
 * last column is the action ("不动" / "生成 词TTS+句"). Only rows below the
 * table's '-' separator count, so header/summary lines never leak in. Every
 * row is kept — including rows for other words whose sentences merely mention
 * the queried word — so callers can align rows 1:1 with the noteIds from
 * `anki_api.py find` and filter afterwards. The `word` argument is unused;
 * rows are not filtered by it.
 */
export function parseWordAudioCandidates(text, word) {
  void word // kept for call-site compatibility; rows are no longer filtered by it
  const body = String(text ?? '')
  const lines = body.split(/\r?\n/)
  const out = []
  const soundRe = /\[sound:([^\]]+)\]/
  // mine_audio.py pads columns with `%-Ns`, which counts code points — CJK
  // cells (ゴンドラ / 「已有」) therefore leave only one space before the next
  // column. Split on runs of >=1 space instead; audio refs never contain
  // spaces and the action column is re-joined below.
  const splitCells = (s) => s.split(/\s+/).filter(Boolean)
  // mine_audio.py prints `print('-' * 100)` right after the header; treat only
  // that exact line as the table separator so summary lines like
  // "需要新生成并上传的媒体文件：0 个" can never be parsed as rows.
  const SEPARATOR = '-'.repeat(100)
  const emptyMarkers = new Set(['', '（空）', '(空)', '-', '—', '无'])
  let seenSeparator = false
  for (const line of lines) {
    if (line.trim() === SEPARATOR) {
      seenSeparator = true
      continue
    }
    if (!seenSeparator) continue
    const trimmed = line.trim()
    // A blank line closes the table body (mine_audio.py prints one before the
    // summary lines), so "Sentence Audio：…" summaries never leak in.
    if (trimmed === '') break
    // A data row has at least the four padded columns plus an action token.
    const cells = splitCells(trimmed)
    if (cells.length < 5) continue
    // The action column itself contains a space ("生成 词TTS+句"), so anything
    // beyond the first four columns belongs to it.
    const [w, reading, wordAudioRaw, sentenceAudioRaw] = cells
    const action = cells.slice(4).join(' ')
    // The reading column is always kana; anything else (e.g. the summary line
    // "Word Audio   ：…") means this isn't a data row.
    if (!/^[\u3041-\u30ffー〜]+$/.test(reading)) continue
    const wordAudio = soundRe.exec(wordAudioRaw)?.[1] ?? ''
    const sentenceAudio = soundRe.exec(sentenceAudioRaw)?.[1] ?? ''
    const wordEmpty = wordAudioRaw === '' || emptyMarkers.has(wordAudioRaw)
    const sentenceEmpty = sentenceAudioRaw === '' || emptyMarkers.has(sentenceAudioRaw)
    out.push({
      word: w,
      reading: reading || null,
      wordAudio: wordAudio || null,
      wordAudioEmpty: wordEmpty,
      sentenceAudio: sentenceAudio || null,
      sentenceAudioEmpty: sentenceEmpty,
      action: action || null,
    })
  }
  return out
}

/**
 * Parse the human-readable output of `core6000_example.py gen --list-jisho`
 * into a list of Jisho candidate sentences for the Add-example tab. Each
 * candidate row in the script's output has the shape:
 *
 *   <word>（<noteId>）的 Jisho 候选 N 条（gen --jisho-pick N 按这个编号挑）：
 *     - 1. [41字 ｜ Jreibun] 句子原文…
 *     - 2. [12字 ｜ Tatoeba] ⚠️ 振假名不合格 另一句…
 *
 * The word header line carries the noteId and the candidate count; each
 * candidate line is prefixed by `- <index>. [<len>字 ｜ <source>]` (plus an
 * optional ruby-warning flag) followed by the sentence text. We return one
 * object per candidate so the panel can render a pickable list and hand the
 * chosen index back to `addExample` as `jishoPick`. Header / summary lines
 * (the dispatcher banner, the `--list-jisho 结束` footer, api-key warnings)
 * are never parsed as candidates.
 */
export function parseJishoCandidates(text) {
  const body = String(text ?? '')
  const lines = body.split(/\r?\n/)
  const out = []
  // Word header: "適当（1621392074520）的 Jisho 候选 1 条（…）："
  const headerRe = /^(.+?)（(\d+)）的\s*Jisho\s*候选\s*(\d+)\s*条/
  // Candidate line: "- 1. [41字 ｜ Jreibun] 句子…" or with "⚠️ 振假名不合格"
  const candRe = /^\s*-\s*(\d+)\.\s*\[(\d+)字\s*[｜|]\s*([^\]]*)\]\s*(.*)$/
  let currentWord = null
  let currentNoteId = null
  for (const line of lines) {
    const header = headerRe.exec(line)
    if (header !== null) {
      currentWord = header[1].trim()
      currentNoteId = Number(header[2])
      continue
    }
    if (currentWord === null) continue
    const m = candRe.exec(line)
    if (m === null) continue
    const rest = m[4].trim()
    const rubyWarn = /振假名不合格/.test(rest)
    const jp = rest.replace(/⚠️\s*振假名不合格\s*/, '').trim()
    out.push({
      index: Number(m[1]),
      word: currentWord,
      noteId: currentNoteId,
      len: Number(m[2]),
      source: m[3].trim(),
      rubyOk: !rubyWarn,
      jp,
    })
  }
  return out
}

export function parseDoctor(text, exitCode) {
  const body = String(text ?? '')
  const num = (re) => {
    const m = re.exec(body)
    return m === null ? 0 : Number(m[1])
  }
  const passed = num(/✓\s*通过\s*(\d+)\s*项/)
  const hints = num(/·\s*提示\s*(\d+)\s*项/)
  const blocking = num(/✗\s*阻塞\s*(\d+)\s*项/)
  const summaryMatch = /结论：([^\r\n]+)/.exec(body)
  let status
  if (blocking > 0) status = 'blocked'
  else if (exitCode === 1) status = 'blocked'
  else if (exitCode === 0) status = 'green'
  else if (exitCode === 2) status = 'hint'
  else status = 'error'
  const label = status === 'green' ? '全绿'
    : status === 'hint' ? '提示'
      : status === 'blocked' ? '阻塞'
        : '未知'
  return {
    status,
    label,
    exitCode: Number.isInteger(exitCode) ? exitCode : null,
    passed,
    hints,
    blocking,
    summary: summaryMatch === null ? '' : summaryMatch[1].trim(),
  }
}

export function monthKey(date = new Date(), timeZone = 'Asia/Shanghai') {
  let parts
  try {
    parts = new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
    }).formatToParts(date)
  } catch {
    parts = new Intl.DateTimeFormat('en-CA', {
      year: 'numeric',
      month: '2-digit',
    }).formatToParts(date)
  }
  const pick = (type) => {
    const found = parts.find((p) => p.type === type)
    return found === undefined ? '' : found.value
  }
  return `${pick('year')}-${pick('month')}`
}

export function monthlyReportRelPath(month) {
  return `${MONTHLY_REPORT_DIR}/monthly-${month}.json`
}

/**
 * Normalise a workspace-relative path for the picker: forward slashes, no
 * `.`/empty segments, and `..` clamped at the workspace root. The result is
 * what the panel sends back to `today-new` / `vocab cover`.
 */
export function normalizeRelPath(value) {
  const raw = typeof value === 'string' ? value.trim() : ''
  if (raw === '') return ''
  const parts = []
  for (const part of raw.replace(/\\/g, '/').split('/')) {
    if (part === '' || part === '.') continue
    if (part === '..') {
      parts.pop()
      continue
    }
    parts.push(part)
  }
  return parts.join('/')
}

/** True when `target` is `root` itself or lives underneath it. */
export function isInside(root, target) {
  const rel = relativePath(resolvePath(root), resolvePath(target))
  if (rel === '') return true
  return !rel.startsWith('..') && !isAbsolute(rel)
}

/** Turn an absolute path back into the picker's forward-slash relative form. */
export function toRelPath(root, target) {
  const rel = relativePath(resolvePath(root), resolvePath(target))
  if (rel === '') return ''
  return rel.split(sep).join('/')
}

/**
 * Directories first, then files, both in Japanese-friendly name order, with a
 * hard entry cap so a huge folder cannot stream thousands of rows into the
 * panel.
 */
export function sortAndCapEntries(entries, limit = MAX_BROWSE_ENTRIES) {
  const collator = new Intl.Collator('ja', { numeric: true, sensitivity: 'base' })
  const sorted = entries.slice().sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1
    return collator.compare(a.name, b.name)
  })
  const truncated = sorted.length > limit
  return {
    entries: truncated ? sorted.slice(0, limit) : sorted,
    total: sorted.length,
    truncated,
  }
}

/** Split a relative path into the crumb trail the picker renders. */
export function crumbsFor(rel, rootLabel) {
  const trail = [{ name: rootLabel, path: '' }]
  if (rel === '') return trail
  let current = ''
  for (const part of rel.split('/')) {
    current = current === '' ? part : `${current}/${part}`
    trail.push({ name: part, path: current })
  }
  return trail
}

/**
 * Read one directory of the workspace for the panel's path picker. Read-only:
 * listings never escape the workspace root, and the picker only ever returns
 * paths that `today-new` / `vocab cover` accept (relative to that root).
 */
export async function listWorkspaceDirectory(root, arg) {
  const absRoot = resolvePath(root)
  const requested = typeof arg === 'string' ? arg.trim() : ''
  const target = requested === ''
    ? absRoot
    : isAbsolute(requested)
      ? resolvePath(requested)
      : resolvePath(absRoot, normalizeRelPath(requested))
  if (!isInside(absRoot, target)) {
    return { ok: false, root: absRoot, error: `只能在 anki-workspace 内选择：${requested}` }
  }
  let dirents
  try {
    const info = await stat(target)
    if (!info.isDirectory()) return { ok: false, root: absRoot, error: `不是目录：${requested}` }
    dirents = await readdir(target, { withFileTypes: true })
  } catch (error) {
    return { ok: false, root: absRoot, error: `读取目录失败：${String(error?.message ?? error)}` }
  }
  const entries = []
  for (const dirent of dirents) {
    let kind = dirent.isDirectory() ? 'dir' : dirent.isFile() ? 'file' : null
    if (kind === null && dirent.isSymbolicLink()) {
      try {
        const info = await stat(join(target, dirent.name))
        kind = info.isDirectory() ? 'dir' : info.isFile() ? 'file' : null
      } catch {
        kind = null
      }
    }
    if (kind === null) continue
    const dot = dirent.name.lastIndexOf('.')
    entries.push({
      name: dirent.name,
      path: toRelPath(absRoot, join(target, dirent.name)),
      kind,
      ext: kind === 'file' && dot > 0 ? dirent.name.slice(dot).toLowerCase() : '',
      hidden: dirent.name.startsWith('.'),
    })
  }
  const rel = toRelPath(absRoot, target)
  const sorted = sortAndCapEntries(entries)
  return {
    ok: true,
    root: absRoot,
    path: rel,
    parent: rel === '' ? null : rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '',
    crumbs: crumbsFor(rel, basename(absRoot) || 'anki-workspace'),
    entries: sorted.entries,
    total: sorted.total,
    truncated: sorted.truncated,
  }
}

/**
 * 本地模型档位选择（面板下拉 / 工具参数 → CLI 旗标）。
 *
 * 语义与 code/common/llm_client.py 的查找链一致：
 *  - `llmModel`   → `--model <id>`：显式钉住端点上的某个模型 id。Python 侧看到
 *                   显式 model 会**关掉 pin**（不再对齐 /props 当前在服务的模型）——
 *                   这正是「人明确指定」的口径。
 *  - `llmProfile` → `--profile <name>`：用 local-llm.json 里 profiles 的那一档；
 *                   脚本 help 推荐换档位走这个（端点/窗口一起切）。
 *                   **同样关 pin**（2026-11-14 修复）：点了档位就用该档的 model，
 *                   不再被「端点当前在服务的模型」覆盖——旧行为下选 profile 毫无效果。
 * 两者都给时 Python 侧 model 覆盖 profile 的 model，pin 关闭。空值 = 不注入，
 * 维持现状（profile 默认 + pin_active）。
 */
export function normalizeLlmChoice(args) {
  const clean = (v) => (typeof v === 'string' ? v.trim() : '')
  const model = clean(args?.llmModel)
  let profile = clean(args?.llmProfile)
  // 面板的「默认档位」传空串；也接受显式的 'default' 别名。
  if (profile.toLowerCase() === 'default') profile = ''
  return { model, profile }
}

/** 单次调用（override）盖在 Config 默认之上；空值不覆盖。 */
export function mergeLlm(base, override) {
  const b = normalizeLlmChoice(base)
  const o = normalizeLlmChoice(override)
  return { model: o.model || b.model, profile: o.profile || b.profile }
}

/**
 * llmModels() 的原始 JSON → 面板/工具用的形状。Python 侧 local_llm_models.py
 * 已经把 api_key 挡在门外，这里只搬运展示字段；解析失败返回 error。
 */
export function normalizeLlmModels(raw) {
  if (!raw || typeof raw !== 'object') return { ok: false, error: '模型清单输出里没有可解析的 JSON' }
  const models = Array.isArray(raw.models)
    ? raw.models
      .filter((m) => m && typeof m.id === 'string' && m.id !== '')
      .map((m) => ({ id: m.id, contextWindow: Number.isFinite(m.context_window) ? m.context_window : null }))
    : []
  const profiles = Array.isArray(raw.profiles)
    ? raw.profiles.map((p) => ({
      name: typeof p?.name === 'string' ? p.name : '',
      model: typeof p?.model === 'string' ? p.model : '',
      baseUrl: typeof p?.base_url === 'string' ? p.base_url : '',
      contextWindow: Number.isFinite(p?.context_window) && p.context_window > 0 ? p.context_window : null,
    }))
    : []
  return {
    ok: true,
    baseUrl: raw?.endpoint?.base_url ?? '',
    activeModel: raw?.endpoint?.active_model ?? null,
    models,
    profiles,
    endpointError: typeof raw.error === 'string' ? raw.error : null,
  }
}

export function buildAddExampleCalls(selector, commit, llmArgs, opts = {}) {
  const extra = Array.isArray(selector) ? selector.slice() : []
  // 本地模型覆盖：core6000 的 gen/tts/apply 都挂了 add_llm_args，三步统一追加。
  const llm = normalizeLlmChoice(llmArgs)
  const modelFlags = []
  if (llm.model !== '') modelFlags.push('--model', llm.model)
  if (llm.profile !== '') modelFlags.push('--profile', llm.profile)
  // Jisho 选句旗标**只属于 gen**（tts/apply 的 argparse 没有这些参数，塞进去会报错）：
  // --jisho-pick N 用第 N 条候选（1 起，编号与 --list-jisho 一致），--list-jisho 只列候选清单，
  // --jisho-max-len N 只保留去空白后 ≤N 字的候选（仍受 6 字下限约束）。
  const genJishoFlags = []
  if (Number.isInteger(opts.jishoPick) && opts.jishoPick > 0) genJishoFlags.push('--jisho-pick', String(opts.jishoPick))
  if (opts.listJisho === true) genJishoFlags.push('--list-jisho')
  if (Number.isInteger(opts.jishoMaxLen) && opts.jishoMaxLen > 0) genJishoFlags.push('--jisho-max-len', String(opts.jishoMaxLen))
  const base = ['code/cli.py', 'core6000']
  // 默认真写（commit !== false）：用户 2026-11-09 定的规矩「不再演练，直接写入」。
  // 只有显式 commit === false 才退回演练（apply 不加 --commit）。
  const write = commit !== false
  return [
    { name: 'gen', argv: [...base, 'gen', ...extra, ...modelFlags, ...genJishoFlags], timeoutMs: 30 * 60_000 },
    { name: 'tts', argv: [...base, 'tts', ...extra], timeoutMs: 15 * 60_000 },
    {
      name: 'apply',
      argv: [...base, 'apply', ...extra, ...(write ? ['--commit'] : [])],
      timeoutMs: 15 * 60_000,
    },
  ]
}

export function buildTodayNewArgs(args) {
  const input = typeof args?.input === 'string' ? args.input.trim() : ''
  if (input === '') return { error: '需要 input（字幕文件或作品目录）' }
  // --json 让 Python 把结果写成结构化 JSON；人读日志走 stderr，面板再用它渲染。
  const argv = ['code/cli.py', 'today-new', input, '--json']
  if (Number.isInteger(args.n) && args.n > 0) argv.push('--n', String(args.n))
  // 本地模型覆盖（面板/工具点名的档位）：直接走脚本自己的 --model / --profile。
  const llm = normalizeLlmChoice(args)
  if (llm.model !== '') argv.push('--model', llm.model)
  if (llm.profile !== '') argv.push('--profile', llm.profile)
  if (args.season === true) argv.push('--season')
  if (args.noLlmRank === true) argv.push('--no-llm-rank')
  if (args.noSenseCheck === true) argv.push('--no-sense-check')
  if (args.noSenseRepair === true) argv.push('--no-sense-repair')
  // 默认真写（commit !== false）：用户 2026-11-10 定的规矩「默认直接 commit，点名演练才演练」。
  // 只有显式 commit === false 才退回演练（不加 --commit）。
  const write = args?.commit !== false
  if (write) argv.push('--commit')
  return { argv, commit: write }
}

export function buildSeasonNewArgs(args) {
  const input = typeof args?.input === 'string' ? args.input.trim() : ''
  if (input === '') return { error: '需要 input（一季的字幕目录）' }
  const argv = ['code/cli.py', 'season-new', input, '--json']
  const num = (v) => Number.isInteger(v) && v >= 0
  if (num(args.jitenMax)) argv.push('--jiten-max', String(args.jitenMax))
  if (num(args.workJitenMin)) argv.push('--work-jiten-min', String(args.workJitenMin))
  if (num(args.workJitenMax)) argv.push('--work-jiten-max', String(args.workJitenMax))
  if (num(args.workMinCount)) argv.push('--work-min-count', String(args.workMinCount))
  if (num(args.minWords)) argv.push('--min-words', String(args.minWords))
  if (num(args.maxWords)) argv.push('--max-words', String(args.maxWords))
  if (args.includeNames === true) argv.push('--include-names')
  if (typeof args.tag === 'string' && args.tag.trim() !== '') argv.push('--tag', args.tag.trim())
  // 默认只出清单（不写库）；只有显式 commit === true 才打季标签。
  const write = args?.commit === true
  if (write) argv.push('--commit')
  return { argv, commit: write }
}

export function buildCoverArgs(root, args) {
  const text = typeof args?.text === 'string' ? args.text : ''
  const paths = Array.isArray(args?.paths)
    ? args.paths.filter((p) => typeof p === 'string' && p.trim() !== '')
    : []
  if (text.trim() === '' && paths.length === 0) {
    return { error: '需要 text 或至少一个 paths 条目' }
  }
  const argv = ['code/cli.py', 'vocab', 'cover']
  if (text.trim() !== '') argv.push('--text', text)
  for (const p of paths) argv.push(isAbsolute(p) ? p : resolvePath(root, p))
  argv.push('--json')
  if (Number.isInteger(args.top) && args.top > 0) argv.push('--top', String(args.top))
  if (args.screen === true) argv.push('--screen')
  return { argv }
}

/**
 * 解析用户输入的 noteId 串：逗号 / 空格 / 中文逗号分隔，去重并保持出现顺序。
 * 非法值（非数字、非正整数）直接丢弃；全空返回空数组，由调用方决定报错文案。
 */
export function normalizeNoteIds(value) {
  const raw = Array.isArray(value) ? value.join(',') : String(value ?? '')
  const out = []
  for (const part of raw.replace(/，/g, ',').split(/[,\s]+/)) {
    const token = part.trim()
    if (token === '') continue
    if (!/^\d+$/.test(token)) continue
    const n = Number(token)
    if (!Number.isSafeInteger(n) || n <= 0) continue
    if (!out.includes(n)) out.push(n)
  }
  return out
}

/**
 * 卡片修正（阶段 2/3）的固定命令。两个字段各走**同一套讲解逻辑**下最合适的入口：
 * - `field='ainote'` → `note_regen.py`：按卡上现有的 ①/② 两句，套用「增加例句」
 *   的 core6000 提示词 + `render_ainote`（① 句 + ② 句），只写 AINote；
 * - `field='html'`   → `cards.py gen --only html`：沿用 ruby_engine 确定性重渲染。
 * `--out` 落一份 JSON 供面板读回。**无论演练还是真写都加 `--overwrite`**：这个动作的
 * 语义就是重做已存在的字段，不加会在演练时被「已有内容跳过」直接跳过、面板拿不到结果。
 */
export function buildCardFixArgv(ids, field, commit, outPath) {
  const argv = field === 'ainote'
    ? ['code/execution/note_regen.py', 'gen', '--note-id', ids.join(','),
      '--out', outPath, '--overwrite']
    : ['code/execution/cards.py', 'gen', '--note-id', ids.join(','),
      '--only', 'html', '--out', outPath, '--overwrite']
  if (commit === true) argv.push('--commit')
  return argv
}

/**
 * 卡片修正 · 候选整理（纯函数）：`anki_api.py notes --json --cards` 的 rows →
 * 面板可直接渲染的候选卡，`noteIds` 与 `cards` 一一对应。
 *
 * 2026-11-13 的 bug：按单词查卡时只查例句 deck。可一个词常常同时挂在
 * 例句卡和词汇卡上（張る＝例句卡「電線を引っ張る」＋ 词汇卡「肩が張る」），
 * 限定 deck 后词汇卡被藏了起来，候选只剩一张，面板就按「只有一张卡」
 * 的规则直接真写，改到了用户没在看的那张卡。所以查询**不限定 deck**，
 * 命中多张时全部交给面板，让用户选。
 *
 * 保留条件（机械判断，不猜）：
 *  - `Word` 字段与输入**精确相等**（Anki 的字段搜索会命中包含该词的卡）；
 *  - `Sentence` 非空，且 `AINote` / `Sentence HTML` 两个字段都存在——这三个
 *    字段正是 cards.py gen 要读写的东西，缺字段的笔记类型不能拿来做重新生成。
 * 排序：例句 deck 优先（面板的原始用途），再按牌组名、noteId，保证稳定。
 */
export function cardLookupCards(rows, word) {
  const want = String(word ?? '').trim()
  const out = []
  for (const row of Array.isArray(rows) ? rows : []) {
    if (row == null) continue
    const f = row.fields ?? {}
    const cardWord = String(f.Word ?? '').trim()
    if (want !== '' && cardWord !== want) continue
    if (String(f.Sentence ?? '').trim() === '') continue
    if (!CARD_FIX_FIELDS.every((name) => Object.prototype.hasOwnProperty.call(f, name))) continue
    const decks = []
    for (const card of Array.isArray(row.cards) ? row.cards : []) {
      const deck = String(card?.deckName ?? '').trim()
      if (deck !== '' && !decks.includes(deck)) decks.push(deck)
    }
    const ainote = String(f.AINote ?? '')
    const html = String(f['Sentence HTML'] ?? '')
    out.push({
      noteId: Number(row.noteId),
      word: cardWord,
      sentence: String(f.Sentence ?? ''),
      modelName: String(row.modelName ?? ''),
      deckName: decks.join('、'),
      isExample: decks.includes(DECK_EXAMPLE),
      hasAinote: ainote.trim() !== '',
      hasHtml: html.trim() !== '',
      ainote,
      html,
    })
  }
  const byDeck = (a, b) => (a.deckName < b.deckName ? -1 : (a.deckName > b.deckName ? 1 : 0))
  out.sort((a, b) => (Number(b.isExample) - Number(a.isExample))
    || byDeck(a, b)
    || a.noteId - b.noteId)
  return out
}

function readCollected(reader) {
  if (reader === undefined || reader === null) return { text: '', lossy: false }
  try {
    const read = reader.readFrom(0)
    return { text: String(read.text ?? ''), lossy: read.lossy === true }
  } catch {
    return { text: '', lossy: true }
  }
}

function combineOutput(stdout, stderr) {
  const a = String(stdout ?? '')
  const b = String(stderr ?? '')
  if (a === '') return b
  if (b === '') return a
  return `${a}\n${b}`
}

export function createRuntime(ctx, config = {}) {
  const pythonPath = typeof config.pythonPath === 'string' && config.pythonPath.trim() !== ''
    ? config.pythonPath.trim()
    : 'python'
  const configuredRoot = typeof config.workspaceRoot === 'string' && config.workspaceRoot.trim() !== ''
    ? config.workspaceRoot.trim()
    : ''
  const timeZone = typeof config.timeZone === 'string' && config.timeZone.trim() !== ''
    ? config.timeZone.trim()
    : 'Asia/Shanghai'
  const refreshMs = Number.isFinite(config.refreshMinutes) && config.refreshMinutes > 0
    ? Math.round(config.refreshMinutes * 60_000)
    : 10 * 60_000
  // 默认本地模型档位（Config 兜底）；单次调用参数 llmModel/llmProfile 覆盖它。
  const defaultLlm = normalizeLlmChoice({ llmModel: config.llmModel, llmProfile: config.llmProfile })

  let cache = null
  let refreshing = null
  let lastRefresh = 0
  let resolvedPython = null

  async function isWorkspace(dir) {
    if (typeof dir !== 'string' || dir === '') return false
    try {
      await access(join(dir, 'code', 'cli.py'))
      await access(join(dir, 'code', 'common', 'anki_api.py'))
      return true
    } catch {
      return false
    }
  }

  async function resolveRoot(agent) {
    if (configuredRoot !== '') {
      if (await isWorkspace(configuredRoot)) return configuredRoot
      throw new Error(`配置的 workspaceRoot 不是 anki-workspace：${configuredRoot}`)
    }
    const wd = ctx.get('workingDirectory')
    if (wd !== undefined && agent !== undefined) {
      try {
        const dir = await wd.ensure(agent)
        if (await isWorkspace(dir)) return dir
      } catch {
        // Fall through to the process/default candidates.
      }
    }
    const agents = ctx.get('agents')
    if (wd !== undefined && agents !== undefined) {
      const candidates = []
      try {
        const current = agents.currentInitiator()
        if (current !== undefined) candidates.push(current)
      } catch {
        // Optional service; ignore.
      }
      try {
        for (const candidate of agents.roots()) {
          if (!candidates.includes(candidate)) candidates.push(candidate)
        }
      } catch {
        // Optional service; ignore.
      }
      for (const candidate of candidates) {
        try {
          const dir = await wd.ensure(candidate)
          if (await isWorkspace(dir)) return dir
        } catch {
          // Try the next live agent.
        }
      }
    }
    if (wd !== undefined && typeof wd.defaultDirectory === 'string' && await isWorkspace(wd.defaultDirectory)) {
      return wd.defaultDirectory
    }
    if (await isWorkspace(process.cwd())) return process.cwd()
    const tried = [wd?.defaultDirectory, process.cwd()].filter(Boolean)
    throw new Error(`找不到 anki-workspace（已找：${tried.join('、') || '无'}）；请在插件 config.workspaceRoot 指定工作区根目录`)
  }

  async function pythonExe(env) {
    if (resolvedPython !== null) return resolvedPython
    try {
      resolvedPython = await ctx.subprocess.resolveExecutable(pythonPath, env)
    } catch {
      resolvedPython = pythonPath
    }
    return resolvedPython
  }

  async function run(root, argv, opts = {}) {
    const startedAt = Date.now()
    const env = {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    }
    // 兜底档位（Config llmModel/llmProfile）：走 llm_client.py 的 env 查找链，
    // 对所有子命令生效；单次调用注入的 --model/--profile 旗标优先级更高。
    const llm = normalizeLlmChoice(opts.llm)
    if (llm.model !== '') env.DSH_LOCAL_LLM_MODEL = llm.model
    if (llm.profile !== '') env.DSH_LOCAL_LLM_PROFILE = llm.profile
    const timeoutMs = Number.isFinite(opts.timeoutMs) && opts.timeoutMs > 0
      ? opts.timeoutMs
      : DEFAULT_TIMEOUT_MS
    const timeoutSignal = AbortSignal.timeout(timeoutMs)
    const signal = opts.signal === undefined
      ? timeoutSignal
      : AbortSignal.any([opts.signal, timeoutSignal])
    const exe = await pythonExe(env)
    let handle
    try {
      handle = ctx.subprocess.spawn({
        argv: [exe, ...argv],
        cwd: root,
        stdio: {
          stdin: 'ignore',
          stdout: { maxBytes: MAX_CAPTURE_BYTES },
          stderr: { maxBytes: MAX_CAPTURE_BYTES },
        },
        graceMs: 3000,
        signal,
        env,
      })
    } catch (error) {
      return {
        exitCode: null,
        signal: null,
        stdout: '',
        stderr: String(error?.message ?? error),
        durationMs: Date.now() - startedAt,
        timedOut: timeoutSignal.aborted,
        spawnError: true,
      }
    }
    let outcome
    try {
      outcome = await handle.done
    } catch (error) {
      outcome = { exitCode: null, signal: null }
      const message = String(error?.message ?? error)
      if (message !== '') {
        const stderr = readCollected(handle.collected?.stderr)
        return {
          exitCode: null,
          signal: null,
          stdout: readCollected(handle.collected?.stdout).text,
          stderr: `${stderr.text}\n${message}`.trim(),
          durationMs: Date.now() - startedAt,
          timedOut: timeoutSignal.aborted,
          spawnError: true,
        }
      }
    }
    const stdout = readCollected(handle.collected?.stdout)
    const stderr = readCollected(handle.collected?.stderr)
    return {
      exitCode: outcome.exitCode,
      signal: outcome.signal,
      stdout: stdout.text,
      stderr: stderr.text,
      durationMs: Date.now() - startedAt,
      timedOut: timeoutSignal.aborted,
      lossy: stdout.lossy || stderr.lossy,
    }
  }

  function annotateRun(result) {
    return {
      exitCode: result.exitCode,
      signal: result.signal,
      timedOut: result.timedOut,
      durationMs: result.durationMs,
      output: tail(combineOutput(result.stdout, result.stderr), 8000),
      truncated: result.lossy === true,
    }
  }

  async function statusAt(root, signal) {
    const checkedAt = new Date().toISOString()
    const r = await run(root, ['code/common/anki_api.py', 'check'], {
      timeoutMs: 30_000,
      signal,
    })
    const parsed = parseAnkiCheck(combineOutput(r.stdout, r.stderr))
    const online = r.exitCode === 0
    const output = tail(combineOutput(r.stdout, r.stderr), 1500)
    return {
      online,
      version: parsed.version,
      decks: parsed.decks,
      noteTypes: parsed.noteTypes,
      media: parsed.media,
      latencyMs: r.durationMs,
      checkedAt,
      exitCode: r.exitCode,
      timedOut: r.timedOut,
      output,
      error: online ? null : (output || 'AnkiConnect 不可达'),
    }
  }

  async function doctorAt(root, signal, tag) {
    const checkedAt = new Date().toISOString()
    const argv = ['code/cli.py', 'doctor']
    if (typeof tag === 'string' && tag.trim() !== '') argv.push('--tag', tag.trim())
    const r = await run(root, argv, { timeoutMs: 240_000, signal })
    const text = combineOutput(r.stdout, r.stderr)
    const parsed = parseDoctor(text, r.exitCode)
    return {
      ...parsed,
      checkedAt,
      tag: typeof tag === 'string' && tag.trim() !== '' ? tag.trim() : null,
      durationMs: r.durationMs,
      timedOut: r.timedOut,
      output: tail(text, 8000),
    }
  }

  async function monthlyReportInfo(root) {
    const month = monthKey(new Date(), timeZone)
    const path = monthlyReportRelPath(month)
    try {
      const st = await stat(join(root, path))
      return {
        month,
        path,
        exists: true,
        bytes: st.size,
        mtime: st.mtime.toISOString(),
      }
    } catch {
      return { month, path, exists: false, bytes: null, mtime: null }
    }
  }

  /**
   * Read the monthly report JSON without regenerating it. This is the single
   * source the panel renders: the same file `r report --json --out` writes.
   * A missing file is a normal "not generated yet" answer, not an error.
   */
  async function readMonthlyReport(root, monthArg) {
    const month = typeof monthArg === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/.test(monthArg)
      ? monthArg
      : monthKey(new Date(), timeZone)
    const reportPath = monthlyReportRelPath(month)
    const absPath = join(root, reportPath)
    let st
    try {
      st = await stat(absPath)
    } catch {
      return {
        ok: true,
        month,
        reportPath,
        exists: false,
        bytes: null,
        mtime: null,
        report: null,
        parseError: null,
        tooLarge: false,
      }
    }
    const base = {
      month,
      reportPath,
      exists: true,
      bytes: st.size,
      mtime: st.mtime.toISOString(),
    }
    if (st.size > MAX_REPORT_BYTES) {
      return {
        ...base,
        ok: false,
        report: null,
        parseError: `报告 JSON 太大（${st.size} 字节），面板不内联显示`,
        tooLarge: true,
      }
    }
    try {
      const text = await readFile(absPath, 'utf8')
      try {
        return {
          ...base,
          ok: true,
          report: JSON.parse(text),
          parseError: null,
          tooLarge: false,
        }
      } catch (error) {
        return {
          ...base,
          ok: false,
          report: null,
          parseError: `报告 JSON 解析失败：${String(error?.message ?? error)}`,
          tooLarge: false,
        }
      }
    } catch (error) {
      return {
        ...base,
        ok: false,
        report: null,
        parseError: `读取报告失败：${String(error?.message ?? error)}`,
        tooLarge: false,
      }
    }
  }

  async function refreshAll() {
    if (refreshing !== null) return refreshing
    refreshing = (async () => {
      const at = new Date().toISOString()
      try {
        const root = await resolveRoot(undefined)
        const [anki, doctor] = await Promise.all([
          statusAt(root, undefined),
          doctorAt(root, undefined, undefined),
        ])
        const monthlyReport = await monthlyReportInfo(root)
        cache = { root, anki, doctor, monthlyReport, refreshedAt: at, error: null }
      } catch (error) {
        const message = String(error?.message ?? error)
        cache = {
          root: null,
          anki: {
            online: false,
            version: null,
            decks: null,
            noteTypes: null,
            media: null,
            latencyMs: 0,
            checkedAt: at,
            exitCode: null,
            timedOut: false,
            output: message,
            error: message,
          },
          doctor: {
            status: 'error',
            label: '未知',
            exitCode: null,
            passed: 0,
            hints: 0,
            blocking: 0,
            summary: message,
            checkedAt: at,
            tag: null,
            durationMs: 0,
            timedOut: false,
            output: message,
          },
          monthlyReport: null,
          refreshedAt: at,
          error: message,
        }
      }
      lastRefresh = Date.now()
      return cache
    })().finally(() => {
      refreshing = null
    })
    return refreshing
  }

  function refreshInBackground() {
    void refreshAll().catch(() => {})
  }

  function refreshIfStale(minAgeMs = 60_000) {
    if (Date.now() - lastRefresh >= minAgeMs) refreshInBackground()
  }

  async function statusNow(agent, signal) {
    const root = await resolveRoot(agent)
    const anki = await statusAt(root, signal)
    if (cache !== null) {
      cache = { ...cache, root, anki, refreshedAt: new Date().toISOString() }
    }
    return { ...anki, root }
  }

  async function doctorNow(tag, agent, signal) {
    const root = await resolveRoot(agent)
    const doctor = await doctorAt(root, signal, tag)
    if (cache !== null) {
      cache = { ...cache, root, doctor, refreshedAt: new Date().toISOString() }
    }
    return { ...doctor, root }
  }

  async function snapshot() {
    if (cache === null) await refreshAll()
    return {
      ...(cache ?? {}),
      refreshing: refreshing !== null,
      refreshIntervalMs: refreshMs,
    }
  }

  function contextText() {
    if ((cache === null || cache.error !== null) && Date.now() - lastRefresh > 20_000) {
      refreshInBackground()
    }
    if (cache === null) {
      return [
        '<anki-workspace>',
        '状态：首次检测中，稍后可调用 anki_status / anki_doctor 获取实时结果。',
        '工具：anki_status、anki_doctor、anki_add_example、anki_today_new、anki_vocab_cover、anki_study_report。',
        '</anki-workspace>',
      ].join('\n')
    }
    const anki = cache.anki
    const doctor = cache.doctor
    const ankiLine = anki?.online === true
      ? `在线（v${anki.version ?? '?'}，${anki.decks ?? '?'} 个牌组，${anki.latencyMs} ms）`
      : `离线${anki?.error ? `：${String(anki.error).split(/\r?\n/)[0].slice(0, 120)}` : ''}`
    const doctorLine = doctor === null || doctor === undefined
      ? '未检测'
      : `${doctor.label}（exit ${doctor.exitCode ?? '?'}；通过 ${doctor.passed} / 提示 ${doctor.hints} / 阻塞 ${doctor.blocking}）${doctor.summary ? `；${doctor.summary}` : ''}`
    const lines = [
      '<anki-workspace>',
      `根目录：${cache.root ?? '(未找到)'}`,
      `AnkiConnect：${ankiLine}`,
      `doctor：${doctorLine}`,
      `检测时间：${cache.refreshedAt ?? '?'}`,
      '工具：anki_status、anki_doctor、anki_add_example、anki_today_new、anki_vocab_cover、anki_study_report。',
      ...(defaultLlm.model || defaultLlm.profile
        ? [`本地模型默认：${defaultLlm.profile ? `profile=${defaultLlm.profile}` : ''}${defaultLlm.profile && defaultLlm.model ? ' + ' : ''}${defaultLlm.model ? `model=${defaultLlm.model}` : ''}（写库类工具可单次用 llmModel/llmProfile 覆盖）`]
        : []),
      '约定：写库动作默认直接真写（commit 省略=true），只有显式 commit=false 才演练；不替用户做学习决策。',
      '</anki-workspace>',
    ]
    return lines.join('\n')
  }

  async function addExample(args, agent, signal) {
    const words = typeof args?.words === 'string' ? args.words.trim() : ''
    const noteIds = typeof args?.noteIds === 'string' ? args.noteIds.trim() : ''
    if (words === '' && noteIds === '') {
      return { ok: false, commit: false, root: null, error: '需要 words 或 noteIds 至少一个选择器' }
    }
    const root = await resolveRoot(agent)
    const selector = []
    if (words !== '') selector.push('--words', words)
    if (noteIds !== '') selector.push('--note-ids', noteIds)
    if (Number.isInteger(args?.limit) && args.limit > 0) selector.push('--limit', String(args.limit))
    // 默认真写；只有显式 commit === false 才演练（apply 不加 --commit）。
    const commit = args?.commit !== false
    // 单次档位选择覆盖 Config 默认；再合并出传给 run() 的兜底 env。
    const llm = mergeLlm(defaultLlm, normalizeLlmChoice(args))
    // Jisho 选句旗标只透传给 gen（见 buildAddExampleCalls）：jishoPick 正整数才注入，
    // listJisho 严格 === true 才注入，jishoMaxLen 正整数才注入；tts/apply 的 argv 绝不出现这些参数。
    const jishoOpts = {}
    if (Number.isInteger(args?.jishoPick) && args.jishoPick > 0) jishoOpts.jishoPick = args.jishoPick
    if (args?.listJisho === true) jishoOpts.listJisho = true
    if (Number.isInteger(args?.jishoMaxLen) && args.jishoMaxLen > 0) jishoOpts.jishoMaxLen = args.jishoMaxLen
    const calls = buildAddExampleCalls(selector, commit, llm, jishoOpts)
    const steps = []
    for (const call of calls) {
      const r = await run(root, call.argv, { timeoutMs: call.timeoutMs, signal })
      steps.push({
        name: call.name,
        ...annotateRun(r),
      })
      if (r.exitCode !== 0) break
    }
    const applyStep = steps.find((s) => s.name === 'apply')
    const ok = steps.length === calls.length && steps.every((s) => s.exitCode === 0)
    return {
      ok,
      root,
      commit,
      writtenAnki: commit && ok && applyStep !== undefined && applyStep.exitCode === 0,
      steps,
      note: commit
        ? '默认真写：apply 已追加 --commit；结果里 writtenAnki 表示三步全部成功。'
        : '演练（commit=false）：apply 未加 --commit，没有写 Anki。',
    }
  }

  /**
   * Read-only Jisho candidate listing for the Add-example tab. Runs
   * `core6000 gen --list-jisho` (no model call, no Anki write) and parses the
   * human-readable candidate list into structured rows so the panel can show a
   * pickable sentence list. The chosen index is handed back to `addExample` as
   * `jishoPick`, which pins that exact Jisho candidate through gen → tts → apply.
   */
  async function jishoList(args, agent, signal) {
    const words = typeof args?.words === 'string' ? args.words.trim() : ''
    if (words === '') {
      return { ok: false, error: '需要 words（词形，逗号/空格分隔）' }
    }
    const root = await resolveRoot(agent)
    const selector = ['--words', words]
    if (Number.isInteger(args?.limit) && args.limit > 0) selector.push('--limit', String(args.limit))
    // --list-jisho only belongs on gen; buildAddExampleCalls puts it there and
    // strips it from tts/apply. We run just the gen step here (it exits before
    // any model call when --list-jisho is set).
    const llm = mergeLlm(defaultLlm, normalizeLlmChoice(args))
    const calls = buildAddExampleCalls(selector, true, llm, { listJisho: true })
    const r = await run(root, calls[0].argv, { timeoutMs: calls[0].timeoutMs, signal })
    const out = tail(combineOutput(r.stdout, r.stderr), 8000)
    const candidates = parseJishoCandidates(out)
    return {
      ok: r.exitCode === 0,
      root,
      words,
      exitCode: r.exitCode,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      candidates,
      output: out,
      note: candidates.length === 0
        ? '没有列出任何 Jisho 候选（该词可能已有第二句，或 Jisho 无可用例句）。'
        : `${candidates.length} 条 Jisho 候选；选一条后点「生成 / 更新」，会按这条句子覆写卡片资料。`,
    }
  }

  async function todayNew(args, agent, signal) {
    // 单次档位选择覆盖 Config 默认（buildTodayNewArgs 负责注入 --model/--profile）。
    const merged = mergeLlm(defaultLlm, args)
    const built = buildTodayNewArgs({ ...args, llmModel: merged.model, llmProfile: merged.profile })
    if (built.error !== undefined) return { ok: false, error: built.error }
    const root = await resolveRoot(agent)
    const r = await run(root, built.argv, { timeoutMs: 30 * 60_000, signal })
    // today-new --json 的 stdout 是结果 JSON（前面可能有一行 cli.py 派发 banner）。
    const parsed = extractJson(r.stdout)
    let parseError = null
    if (parsed === null) {
      parseError = r.exitCode === 0 ? '输出里没有可解析的 JSON' : null
    }
    const ok = r.exitCode === 0 && parsed !== null && parsed.ok !== false
    return {
      ok,
      root,
      commit: built.commit,
      exitCode: r.exitCode,
      signal: r.signal,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      truncated: r.lossy === true,
      result: parsed,
      parseError,
      // 人读日志都在 stderr；解析成功时只把日志留作诊断，不让它盖住结构化结果。
      output: tail(parsed === null
        ? combineOutput(r.stdout, r.stderr)
        : r.stderr, 12_000),
      note: built.commit ? '默认真写（commit 省略=true）：已真写「今天学习生词」标签。' : '演练（commit=false）：未加 --commit，没有改标签。',
    }
  }

  async function seasonNew(args, agent, signal) {
    const built = buildSeasonNewArgs(args)
    if (built.error !== undefined) return { ok: false, error: built.error }
    const root = await resolveRoot(agent)
    const r = await run(root, built.argv, { timeoutMs: 30 * 60_000, signal })
    const parsed = extractJson(r.stdout)
    let parseError = null
    if (parsed === null) {
      parseError = r.exitCode === 0 ? '输出里没有可解析的 JSON' : null
    }
    const ok = r.exitCode === 0 && parsed !== null && parsed.ok !== false
    return {
      ok,
      root,
      commit: built.commit,
      exitCode: r.exitCode,
      signal: r.signal,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      truncated: r.lossy === true,
      result: parsed,
      parseError,
      output: tail(parsed === null
        ? combineOutput(r.stdout, r.stderr)
        : r.stderr, 12_000),
      note: built.commit
        ? '已按每季口径提取并真写季标签（写后回读）。'
        : '默认真写关闭：只出清单，没有改标签（勾选「写入季标签」才写库）。',
    }
  }

  async function vocabCover(args, agent, signal) {
    if (args?.text === undefined && args?.paths === undefined) {
      return { ok: false, error: '需要 text 或 paths' }
    }
    const root = await resolveRoot(agent)
    const built = buildCoverArgs(root, args)
    if (built.error !== undefined) return { ok: false, error: built.error }
    const r = await run(root, built.argv, { timeoutMs: 15 * 60_000, signal })
    const out = String(r.stdout ?? '')
    let parsed = null
    let parseError = null
    if (r.exitCode === 0) {
      parsed = extractJson(out)
      if (parsed === null) parseError = '输出里没有可解析的 JSON'
    }
    return {
      ok: r.exitCode === 0,
      root,
      exitCode: r.exitCode,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      result: parsed,
      parseError,
      output: parsed !== null ? '' : tail(combineOutput(r.stdout, r.stderr), 12_000),
    }
  }

  async function studyReport(args, agent, signal) {
    const root = await resolveRoot(agent)
    const month = monthKey(new Date(), timeZone)
    const relPath = monthlyReportRelPath(month)
    const absPath = join(root, relPath)
    const force = args?.force === true
    if (!force) {
      const info = await monthlyReportInfo(root)
      if (info.exists) {
        const loaded = await readMonthlyReport(root, month)
        return {
          ok: loaded.ok,
          skipped: true,
          reason: '本月报告已生成（每月一次；force=true 可重建）',
          month,
          reportPath: relPath,
          mtime: info.mtime,
          bytes: info.bytes,
          reportBytes: info.bytes,
          reportMtime: info.mtime,
          report: loaded.report,
          parseError: loaded.parseError,
          tooLarge: loaded.tooLarge === true,
        }
      }
    }
    const r = await run(root, ['code/cli.py', 'r', 'report', '--json', '--out', absPath], {
      timeoutMs: 20 * 60_000,
      signal,
    })
    const loaded = await readMonthlyReport(root, month)
    if (r.exitCode === 0) {
      const info = await monthlyReportInfo(root)
      cache = cache === null ? cache : { ...cache, monthlyReport: info }
    }
    return {
      ok: r.exitCode === 0 && loaded.exists && loaded.ok,
      skipped: false,
      forced: force,
      root,
      month,
      reportPath: relPath,
      reportBytes: loaded.bytes,
      reportMtime: loaded.mtime,
      exitCode: r.exitCode,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      report: loaded.report,
      parseError: loaded.parseError,
      tooLarge: loaded.tooLarge === true,
      output: tail(combineOutput(r.stdout, r.stderr), 8000),
    }
  }

  async function reportData(month, agent) {
    const root = await resolveRoot(agent)
    return { ...(await readMonthlyReport(root, month)), root }
  }

  async function browse(args, agent) {
    const root = await resolveRoot(agent)
    return listWorkspaceDirectory(root, args?.path)
  }

  /**
   * 「获取当前单词」按钮（只读）：经工作区唯一入口 `anki_api.py` 调 AnkiConnect
   * `guiCurrentCard`，取当前复习卡的 Word 字段。不在复习模式返回 found:false；
   * 卡片没有 Word 字段时退回 Transliteration（读音）。Host 不直连 8765。
   */
  async function currentWord(agent, signal) {
    const root = await resolveRoot(agent)
    const r = await run(root, ['code/common/anki_api.py', 'gui-current-word', '--json'],
      { timeoutMs: 10_000, signal })
    if (r.exitCode !== 0) {
      return { ok: false, root, error: tail(combineOutput(r.stdout, r.stderr), 500) || `exit ${r.exitCode}` }
    }
    const parsed = extractJson(r.stdout)
    if (!parsed || typeof parsed !== 'object') {
      return { ok: false, root, error: 'guiCurrentCard 输出里没有可解析的 JSON' }
    }
    const value = currentWordFromCli(parsed)
    return { ...value, ok: true, root, durationMs: r.durationMs }
  }

  /**
   * Read-only list of local-model choices for the panel's model dropdown and
   * the Agent: endpoint models (/v1/models + active /props) plus the profiles
   * declared in local-llm.json. Never includes the api_key — the Python side
   * (`cli.py local-llm-models`) keeps it out of its JSON.
   */
  async function llmModels(agent) {
    const root = await resolveRoot(agent)
    const r = await run(root, ['code/cli.py', 'local-llm-models'], { timeoutMs: 45_000 })
    if (r.exitCode !== 0) {
      return { ok: false, error: tail(combineOutput(r.stdout, r.stderr), 2000) || `exit ${r.exitCode}` }
    }
    const value = normalizeLlmModels(extractJson(r.stdout))
    return { ...value, root, defaultModel: defaultLlm.model, defaultProfile: defaultLlm.profile }
  }

  /**
   * Word Audio (阶段 5 · 生词配音) for a single named word.
   *
   * Two phases:
   *  - phase "plan" (default): run `mine_audio.py plan --query '"Word" deck:<素材生词>'`
   *    to discover every card that carries this word, and in parallel
   *    `anki_api.py find '"Word" deck:<素材生词>' --json` to get the ordered list of
   *    noteIds. The i-th candidate in the plan table corresponds to the
   *    i-th noteId from the find command. We attach each noteId to its
   *    candidate so the panel can let the user pick which one to update.
   *  - phase "apply": the caller passes back either `noteIds` (real Anki
   *    note IDs, used by the agent tool) or `candidateIndices` (indices into
   *    the most recent plan's candidates array, used by the Web panel). We
   *    resolve them to noteIds and run
   *    `mine_audio.py apply --query "nid:<id>" [--commit] [--force]`.
   *    This is the only path that writes to Anki, and it goes through the
   *    workspace's own entry point exactly like every other capability.
   *
   * We never talk to Anki directly here — `mine_audio.py` owns the read/write
   * gate, the backup, and the post-write verify.
   */
  // DECK_MINED / DECK_EXAMPLE 提到模块作用域（导出，供 `cardLookupCards` 判断
  // 例句卡排序）。素材生词 plan 仍然限定在这个 deck：不带 deck 的引号搜索会
  // 连例句卡一起命中；apply 阶段的 `nid:` 查询不需要限定。

  // Per-word cache so the apply phase can resolve candidateIndices without
  // re-running the plan. Keyed by the trimmed word form.
  const wordAudioPlanCache = {}

  /**
   * 卡片修正 · 读取（只读）：按**单词名**找到能重新生成字段的卡，或按 noteId 直接回读。
   *
   * 面板的主输入是单词名（`Word` 字段）：`Word:"…"` 在**整个收藏**里查，再由
   * `cardLookupCards` 按 Word 字段**精确相等** + 三个字段齐备过滤。以前这里把
   * 查询限定在例句 deck，同词的词汇卡（「張る」→ 词汇卡「肩が張る」）被藏起来，
   * 候选只剩例句卡一张，面板就按「只有一张卡」直接真写，改到了错的卡。
   * 现在命中多张时全部返回（带牌组 / 笔记类型），由面板让用户选。
   * 走 `code/common/anki_api.py notes --query/--ids --json --cards`，Host 不直连 AnkiConnect。
   */
  async function cardLookup(args, agent, signal) {
    const word = typeof args?.word === 'string' ? args.word.trim() : ''
    const ids = normalizeNoteIds(args?.ids ?? args?.noteIds)
    if (word === '' && ids.length === 0) {
      return { ok: false, error: '需要 word（单词名）或 noteId' }
    }
    if (word.includes('"')) {
      return { ok: false, error: 'word 不能包含引号（"）' }
    }
    const root = await resolveRoot(agent)
    // 注意：`anki_api.py notes --fields` 会按空白再切一次，
    // `Sentence HTML` 这种带空格的字段名会被切成 `Sentence` + `HTML`。
    // 这里不传 --fields，拿全字段再按名字取。`--cards` 只读牌组名（只读，供
    // 面板区分例句卡 / 词汇卡），不写任何东西。
    const base = ['code/common/anki_api.py', 'notes', '--json', '--cards']
    const argv = word !== ''
      ? [...base, '--query', `Word:"${word}"`, '--limit', '50']
      : [...base, '--ids', ids.join(',')]
    const r = await run(root, argv, { timeoutMs: 60_000, signal })
    const out = tail(combineOutput(r.stdout, r.stderr), 8000)
    const parsed = extractJson(r.stdout)
    const clip = (s) => {
      const v = String(s ?? '')
      return v.length > 4000 ? `${v.slice(0, 4000)}…` : v
    }
    const cards = cardLookupCards(parsed, word).map((card) => ({
      ...card,
      ainote: clip(card.ainote),
      html: clip(card.html),
    }))
    const decksOf = () => [...new Set(cards.map((c) => c.deckName).filter(Boolean))]
    let note = ''
    if (word !== '') {
      if (cards.length === 0) {
        note = `全库里没有 Word 字段等于「${word}」、且带 Sentence / AINote / Sentence HTML 的卡。`
      } else if (cards.length > 1) {
        note = `「${word}」命中 ${cards.length} 张卡（${decksOf().join('、')}），勾选要改的那张再点「重新生成」。`
      }
    }
    return {
      ok: r.exitCode === 0,
      root,
      word: word || null,
      noteIds: cards.map((c) => c.noteId),
      cards,
      exitCode: r.exitCode,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      output: out,
      note,
    }
  }

  /**
   * 卡片修正 · 生成/写库：按卡上 Sentence 重新生成选中字段（html | ainote）。
   * - html：`cards.py gen --only html`（ruby_engine 确定性重渲染）；
   * - ainote：`note_regen.py gen`（与「增加例句」同一份 core6000 提示词 /
   *   `render_ainote`，把卡上 ①/② 两句写成 ①② 讲解），只写 AINote。
   * Host 不直连 AnkiConnect、不新增提示词。默认真写（commit !== false）；
   * commit=false 演练（只去掉 --commit）。
   */
  async function cardFix(args, agent, signal) {
    const field = args?.field
    if (field !== 'html' && field !== 'ainote') {
      return { ok: false, error: "field 必须是 'html' 或 'ainote'" }
    }
    const ids = normalizeNoteIds(args?.noteIds ?? args?.ids)
    if (ids.length === 0) {
      return { ok: false, field, error: '需要 noteId' }
    }
    // 默认真写（用户口径同其它写库工具）：只有显式 commit === false 才演练。
    const commit = args?.commit !== false
    const root = await resolveRoot(agent)
    const outRel = `temp/cardfix_${field}_${Date.now()}.json`
    const argv = buildCardFixArgv(ids, field, commit, outRel)
    // opts.llm = args：单次 llmModel/llmProfile 覆盖 Config 默认（run() 注入 env）。
    const r = await run(root, argv, { timeoutMs: 20 * 60_000, signal, llm: mergeLlm(defaultLlm, args) })
    const out = tail(combineOutput(r.stdout, r.stderr), 8000)
    // 读回 --out 的 JSON（形状 [{noteId, sentence, AINote, SentenceHTML}]）；
    // 读回失败不整体失败：cards 给空数组，保留 output 供诊断。
    let cards = []
    try {
      const text = await readFile(join(root, outRel), 'utf8')
      const parsed = extractJson(text)
      if (Array.isArray(parsed)) {
        for (const row of parsed) {
          const value = String(row?.[field === 'html' ? 'SentenceHTML' : 'AINote'] ?? '')
          cards.push({
            noteId: Number(row?.noteId),
            sentence: String(row?.sentence ?? ''),
            value,
          })
        }
      }
    } catch {
      cards = []
    }
    return {
      ok: r.exitCode === 0,
      root,
      field,
      commit,
      noteIds: ids,
      outPath: outRel,
      exitCode: r.exitCode,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      cards,
      verified: commit && r.exitCode === 0 && cards.length > 0
        && cards.every((c) => String(c.value ?? '').trim() !== ''),
      output: out,
      note: commit
        ? (r.exitCode === 0
          ? (field === 'ainote'
            ? '默认真写：note_regen.py 已按卡上 ①② 两句重写 AINote 并回读（其它字段不动）。'
            : '默认真写：cards.py gen --commit 已写入 Sentence HTML 并回读（AINote 不动）。')
          : '真写失败，看 output 定位（未通过的卡不会写）。')
        : '演练（commit=false）：未加 --commit，没有写 Anki。',
    }
  }

  async function wordAudio(args, agent, signal) {
    const word = typeof args?.word === 'string' ? args.word.trim() : ''
    if (word === '') {
      return { ok: false, error: '需要 word（单词名）' }
    }
    // Guard against breaking out of the quoted term with a stray quote.
    if (word.includes('"')) {
      return { ok: false, error: 'word 不能包含引号（"）' }
    }
    const phase = args?.phase === 'apply' ? 'apply' : 'plan'
    const commit = args?.commit !== false
    const root = await resolveRoot(agent)

    if (phase === 'plan') {
      // Anki's `note:` prefix means "has a note" — searching the word form is
      // a bare quoted term, scoped to the mined-vocabulary deck so example
      // cards don't pollute the candidate list.
      const query = `"${word}" deck:"${DECK_MINED}"`
      // Run both commands in parallel: the human-readable table from
      // mine_audio.py and the machine-readable noteId list from anki_api.py.
      const [r, rFind] = await Promise.all([
        run(
          root,
          ['code/execution/mine_audio.py', 'plan', '--query', query],
          { timeoutMs: 60_000, signal },
        ),
        run(
          root,
          ['code/common/anki_api.py', 'find', query, '--json'],
          { timeoutMs: 30_000, signal },
        ),
      ])
      const out = tail(combineOutput(r.stdout, r.stderr), 8000)
      // mine_audio.py's table lists every note its query hit — including notes
      // for *other* words that merely contain the queried word (ゴンドラ also
      // pulls in 漕ぐ/ケンカ cards whose sentences mention it). The find
      // command below returns those same notes in gather() order, so we align
      // them by noteId and keep only rows whose Word field equals the query.
      let noteIds = []
      if (rFind.exitCode === 0) {
        const parsed = extractJson(rFind.stdout)
        if (Array.isArray(parsed)) {
          noteIds = parsed.map(Number).filter((n) => Number.isFinite(n) && n > 0)
        } else if (parsed && Array.isArray(parsed.ids)) {
          noteIds = parsed.ids.map(Number).filter((n) => Number.isFinite(n) && n > 0)
        }
      }
      const allRows = parseWordAudioCandidates(out, word)
      const candidates = []
      for (let i = 0; i < allRows.length; i += 1) {
        const noteId = noteIds[i] != null ? noteIds[i] : null
        if (noteId == null || allRows[i].word === word) {
          allRows[i].noteId = noteId
          candidates.push(allRows[i])
        }
      }

      // Cache for the apply phase (candidateIndices resolution).
      wordAudioPlanCache[word] = candidates

      return {
        ok: r.exitCode === 0,
        root,
        phase: 'plan',
        word,
        exitCode: r.exitCode,
        timedOut: r.timedOut,
        durationMs: r.durationMs,
        candidates,
        output: out,
        note: candidates.length === 0
          ? '没有匹配到任何卡片，或该词的 Word Audio 字段都已有音频。'
          : `${candidates.length} 张候选卡；选一张后点「生成/更新」真写。`,
      }
    }

    // phase === 'apply'
    let ids = []
    if (Array.isArray(args?.noteIds) && args.noteIds.length > 0) {
      // Agent tool path: real noteIds passed directly.
      ids = args.noteIds
        .filter((id) => Number.isInteger(id) && id > 0)
        .map(String)
    } else if (Array.isArray(args?.candidateIndices) && args.candidateIndices.length > 0) {
      // Web panel path: indices into the cached plan's candidates.
      const cached = wordAudioPlanCache[word]
      if (!cached || cached.length === 0) {
        return {
          ok: false,
          phase: 'apply',
          error: '没有该词的 plan 缓存；请先点「查候选卡」。',
        }
      }
      for (const idx of args.candidateIndices) {
        if (Number.isInteger(idx) && idx >= 0 && idx < cached.length) {
          const nid = cached[idx].noteId
          if (nid != null) ids.push(String(nid))
        }
      }
      if (ids.length === 0) {
        return {
          ok: false,
          phase: 'apply',
          error: '所选候选卡都没有 noteId（plan 时 anki_api.py find 失败）。请重新「查候选卡」。',
        }
      }
    } else {
      return { ok: false, phase: 'apply', error: '需要 noteIds 或 candidateIndices（至少一个）' }
    }

    // Deduplicate while preserving order.
    ids = [...new Set(ids)]
    // nid:a or nid:b is valid Anki query syntax for multiple notes.
    const query = ids.map((id) => `nid:${id}`).join(' or ')
    const argv = ['code/execution/mine_audio.py', 'apply', '--query', query]
    if (commit) argv.push('--commit')
    if (args?.force === true) argv.push('--force')
    const r = await run(root, argv, { timeoutMs: 5 * 60_000, signal })
    const out = tail(combineOutput(r.stdout, r.stderr), 8000)
    const verified = /全部通过|回读校验/.test(out) && /非空/.test(out)
    return {
      ok: r.exitCode === 0,
      root,
      phase: 'apply',
      word,
      commit,
      force: args?.force === true,
      noteIds: ids,
      exitCode: r.exitCode,
      timedOut: r.timedOut,
      durationMs: r.durationMs,
      verified,
      output: out,
      note: commit
        ? (r.exitCode === 0
          ? '已真写：合成 TTS、上传媒体、写 Word Audio 字段并回读。'
          : '真写失败，看下方输出定位。')
        : '演练（commit=false）：未加 --commit，没有写 Anki。',
    }
  }

  return {
    config: { pythonPath, configuredRoot, timeZone, refreshMs },
    llmDefaults: defaultLlm,
    resolveRoot,
    statusAt,
    doctorAt,
    statusNow,
    doctorNow,
    refreshAll,
    refreshInBackground,
    refreshIfStale,
    snapshot,
    contextText,
    addExample,
    jishoList,
    todayNew,
    seasonNew,
    vocabCover,
    studyReport,
    reportData,
    browse,
    currentWord,
    llmModels,
    wordAudio,
    cardLookup,
    cardFix,
    monthlyReportInfo,
    readMonthlyReport,
  }
}

export { isAbsolute }
