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

export function buildAddExampleCalls(selector, commit) {
  const extra = Array.isArray(selector) ? selector.slice() : []
  const base = ['code/cli.py', 'core6000']
  return [
    { name: 'gen', argv: [...base, 'gen', ...extra], timeoutMs: 30 * 60_000 },
    { name: 'tts', argv: [...base, 'tts', ...extra], timeoutMs: 15 * 60_000 },
    {
      name: 'apply',
      argv: [...base, 'apply', ...extra, ...(commit === true ? ['--commit'] : [])],
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
  if (args.season === true) argv.push('--season')
  if (args.noLlmRank === true) argv.push('--no-llm-rank')
  if (args.noSenseCheck === true) argv.push('--no-sense-check')
  if (args.noSenseRepair === true) argv.push('--no-sense-repair')
  if (args.commit === true) argv.push('--commit')
  return { argv, commit: args.commit === true }
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
      '约定：会写库的工具默认演练，只有显式 commit=true 才真写；不替用户做学习决策。',
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
    const commit = args?.commit === true
    const calls = buildAddExampleCalls(selector, commit)
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
        ? 'commit=true：apply 已追加 --commit 真写；结果里 writtenAnki 表示三步全部成功。'
        : '演练：apply 未加 --commit，没有写 Anki。',
    }
  }

  async function todayNew(args, agent, signal) {
    const built = buildTodayNewArgs(args)
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
      note: built.commit ? 'commit=true：已真写「今天学习生词」标签。' : '演练：未加 --commit，没有改标签。',
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

  return {
    config: { pythonPath, configuredRoot, timeZone, refreshMs },
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
    todayNew,
    vocabCover,
    studyReport,
    reportData,
    browse,
    monthlyReportInfo,
    readMonthlyReport,
  }
}

export { isAbsolute }
