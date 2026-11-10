// Host half of @local/anki-workspace.
//
// Registers six agent tools, one compact dynamic prompt context, and the
// JSON-RPC route the Web panel uses. All six operations live in
// `lib/core.js`; both callers share them.

import { createRuntime, tail } from './lib/core.js'

export const name = 'anki-workspace'
export const inject = ['tools', 'systemPrompt', 'subprocess', 'webServer']

const OUT_SCHEMA = { type: 'object', additionalProperties: true }
const API_PREFIX = '/anki-workspace'
const API_PATH = `${API_PREFIX}/api`

function textBlock(text) {
  return [{ type: 'text', text: String(text ?? '') }]
}

function firstLine(value) {
  return String(value ?? '').split(/\r?\n/)[0]
}

function pct(value) {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(1)}%`
    : '?'
}

function renderStatus(value) {
  const lines = []
  if (value?.online === true) {
    lines.push(`AnkiConnect 在线：版本 ${value.version ?? '?'}，牌组 ${value.decks ?? '?'} 个，笔记类型 ${value.noteTypes ?? '?'} 个，媒体 ${value.media ?? '?'} 个，耗时 ${value.latencyMs ?? '?'} ms。`)
  } else {
    lines.push(`AnkiConnect 离线：${firstLine(value?.error) || '不可达'}`)
  }
  lines.push(`检测时间：${value?.checkedAt ?? '?'}`)
  if (value?.output) lines.push('', value.output)
  return textBlock(lines.join('\n'))
}

function renderDoctor(value) {
  const lines = [
    `doctor 结论：${value?.label ?? '?'}（exit ${value?.exitCode ?? '?'}；通过 ${value?.passed ?? '?'} / 提示 ${value?.hints ?? '?'} / 阻塞 ${value?.blocking ?? '?'}）`,
  ]
  if (value?.summary) lines.push(value.summary)
  lines.push(`检测时间：${value?.checkedAt ?? '?'}${value?.tag ? `；preflight tag：${value.tag}` : ''}`)
  if (value?.output) lines.push('', value.output)
  return textBlock(lines.join('\n'))
}

function renderSteps(value) {
  const lines = [
    `core6000 补例句：${value?.ok === true ? '成功' : '未完成'}（${value?.commit === true ? '真写模式 commit=true' : '演练模式，未写库'}）`,
  ]
  if (value?.root) lines.push(`工作区：${value.root}`)
  for (const step of value?.steps ?? []) {
    const flags = []
    if (step.timedOut === true) flags.push('超时')
    if (step.exitCode !== 0) flags.push('失败')
    lines.push(`- ${step.name}: exit ${step.exitCode ?? '?'}${flags.length ? `（${flags.join('、')}）` : ''}，${step.durationMs ?? '?'} ms`)
  }
  const last = (value?.steps ?? []).at(-1)
  if (last?.output) lines.push('', tail(last.output, 4000))
  if (value?.note) lines.push('', value.note)
  return textBlock(lines.join('\n'))
}

function renderTodayNew(value) {
  const lines = [
    `today-new：${value?.ok === true ? '成功' : '失败'}（${value?.commit === true ? 'commit=true 真写' : '演练，未改标签'}）`,
  ]
  if (value?.root) lines.push(`工作区：${value.root}`)
  if (value?.timedOut === true) lines.push('状态：超时')
  if (value?.exitCode !== undefined) lines.push(`exit：${value.exitCode}`)
  const r = value?.result
  if (r !== null && r !== undefined) {
    const c = r.counts ?? {}
    lines.push(`来源：${r.source ?? '?'}${r.window ? `；窗口 ${r.window.episodes ?? '?'} 集` : ''}`)
    lines.push(`候选 ${c.candidates ?? '?'} 个 → 入选 ${c.picked ?? '?'} 个词 / ${c.notes ?? '?'} 张笔记；排序：${r.ranking?.by === 'llm' ? `LLM 精排（${r.ranking?.calls ?? '?'} 次调用 / ${r.ranking?.secs ?? '?'} 秒）` : '公式兜底'}`)
    const picked = Array.isArray(r.picked) ? r.picked : []
    if (picked.length > 0) {
      lines.push('入选：')
      for (const w of picked.slice(0, 30)) {
        const bits = [
          `${w.word}${w.reading ? `（${w.reading}）` : ''}`,
          `JAR ${w.jiten ?? '—'}`,
          `${w.occurrences ?? '?'} 次`,
          `分 ${Number(w.score ?? 0).toFixed(2)}`,
        ]
        if (w.why) bits.push(w.why)
        lines.push(`- ${bits.join(' · ')}`)
      }
    }
    const pending = Array.isArray(r.pending) ? r.pending : []
    if (pending.length > 0) {
      lines.push(`待建卡助词/感动词：${pending.map((w) => w.word).join('、')}`)
    }
    if (r.plan) {
      lines.push(`旧标签 ${r.plan.old ?? '?'} / 保留 ${r.plan.keep ?? '?'} / 摘除 ${r.plan.remove ?? '?'} / 新增 ${r.plan.add ?? '?'}`)
    }
    if (r.write?.committed === true) {
      lines.push(`写入：${r.write.verified === true ? '回读通过' : '回读失败'}（摘除 ${r.write.removed ?? '?'} / 新增 ${r.write.added ?? '?'} / 当前 ${r.write.tagged ?? '?'}）`)
    }
    if (r.artifacts) {
      lines.push(`产物：${r.artifacts.picked_json ?? '?'}；${r.artifacts.report_md ?? '?'}`)
    }
  }
  if (value?.parseError) lines.push('', `JSON 解析失败：${value.parseError}`)
  if (value?.note) lines.push(value.note)
  // 解析成功时结果已经在上面完整列出；human 日志只在失败/解析失败时补一段诊断。
  if (value?.output && (value?.parseError || r == null || value?.ok !== true)) {
    lines.push('', tail(value.output, 4000))
  }
  return textBlock(lines.join('\n'))
}

function renderCover(value) {
  const lines = [`vocab cover：${value?.ok === true ? '成功' : '失败'}（exit ${value?.exitCode ?? '?'}）`]
  if (value?.root) lines.push(`工作区：${value.root}`)
  if (value?.timedOut === true) lines.push('状态：超时')
  const r = value?.result
  if (r !== null && r !== undefined) {
    lines.push(`tokens：${r.tokens ?? '?'}（词汇 ${r.tokens_vocab ?? '?'} / 语法 ${r.tokens_grammar ?? '?'}）；types：${r.types ?? '?'}`)
    for (const key of ['cover_all', 'cover_vocab', 'cover_learnable']) {
      const c = r[key]
      if (c === undefined || c === null) continue
      lines.push(`${key}：deck ${pct(c.deck)} · known ${pct(c.known)} · oov ${pct(c.oov)} · understood ${pct(c.understood)}`)
    }
    if (r.sentences) {
      lines.push(`句子：${r.sentences.sentences ?? '?'} 句，full ${pct(r.sentences.full)}，lenient ${pct(r.sentences.lenient)}`)
    }
    if (r.comprehension) {
      lines.push(`可懂度：by_understood ${pct(r.comprehension.by_understood)} · by_strict ${pct(r.comprehension.by_strict)} · by_understood_listening ${pct(r.comprehension.by_understood_listening)}`)
    }
    if (Array.isArray(r.oov) && r.oov.length > 0) {
      lines.push(`卡组外新词（${r.oov.length}）：${JSON.stringify(r.oov.slice(0, 40))}`)
    } else {
      lines.push('卡组外新词：无')
    }
    if (Array.isArray(r.untackled) && r.untackled.length > 0) {
      lines.push(`待激活（${r.untackled.length}）：${JSON.stringify(r.untackled.slice(0, 40))}`)
    } else {
      lines.push('待激活：无')
    }
    lines.push('（完整 JSON 仍在工具返回值 result 中）')
  }
  if (value?.parseError) lines.push('', `JSON 解析失败：${value.parseError}`)
  if (value?.output) lines.push('', tail(value.output, 4000))
  return textBlock(lines.join('\n'))
}

function renderReport(value) {
  const lines = []
  if (value?.skipped === true) {
    lines.push(`本月学习报告已存在，跳过：${value.reportPath}`)
    if (value.mtime) lines.push(`生成时间：${value.mtime}`)
    lines.push('需要重建时传 force=true。')
    return textBlock(lines.join('\n'))
  }
  lines.push(`ankiR 学习报告：${value?.ok === true ? '已生成' : '失败'}（${value?.month ?? '?'}）`)
  if (value?.reportPath) lines.push(`报告：${value.reportPath}`)
  if (value?.reportBytes !== null && value?.reportBytes !== undefined) lines.push(`大小：${value.reportBytes} 字节`)
  if (value?.timedOut === true) lines.push('状态：超时')
  if (value?.report) {
    lines.push('', '报告数据：', JSON.stringify(value.report, null, 2).slice(0, 6000))
  }
  if (value?.output) lines.push('', tail(value.output, 4000))
  return textBlock(lines.join('\n'))
}

function makeTools(runtime) {
  const readCall = (title) => (args) => ({ card: 'generic', title, kind: 'read', rawInput: args })
  const execCall = (title) => (args) => ({ card: 'generic', title, kind: 'execute', rawInput: args })

  return [
    {
      name: 'anki_status',
      description: '检查 AnkiConnect（127.0.0.1:8765）是否在线，走 anki_api.py check，返回版本、牌组数、笔记类型数、媒体数与耗时。只读，不写库。',
      parameters: { type: 'object', additionalProperties: false, properties: {} },
      output: { schema: OUT_SCHEMA, render: (_a, v) => renderStatus(v) },
      timeoutMs: 45_000,
      isConcurrencySafe: () => true,
      presentCall: readCall('Check AnkiConnect'),
      execute: (args, exec) => runtime.statusNow(exec.agent, exec.signal),
    },
    {
      name: 'anki_doctor',
      description: '跑开工体检 doctor，返回 0=全绿 / 2=提示 / 1=阻塞 的结论、通过/提示/阻塞计数、结论行与输出尾部。只读。可选 tag 额外跑该集 preflight。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          tag: { type: 'string', description: '可选：动画::<作品>::<季>::第NN集；额外跑该集 preflight' },
        },
      },
      output: { schema: OUT_SCHEMA, render: (_a, v) => renderDoctor(v) },
      timeoutMs: 300_000,
      isConcurrencySafe: () => true,
      presentCall: readCall('Run workspace doctor'),
      execute: (args, exec) => runtime.doctorNow(args?.tag, exec.agent, exec.signal),
    },
    {
      name: 'anki_add_example',
      description: '给用户点名的词（core6000 ＋ 素材生词两个卡组自动查找）补第二条例句：固定 gen → tts → apply。新例句来自 jisho 真实语料，模型只写翻译与讲解。默认真写（apply 带 --commit，写前自动备份、写后回读）；只有显式 commit=false 才演练不写。至少给 words 或 noteIds。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          words: { type: 'string', description: '词形，逗号/空格分隔（如 "徹夜,適当"）' },
          noteIds: { type: 'string', description: '点名的 noteId，逗号分隔；与 words 二选一或并用' },
          limit: { type: 'integer', description: '最多处理几张卡' },
          commit: { type: 'boolean', description: '默认真写（省略=true）；显式 false 才演练不写库' },
        },
      },
      output: { schema: OUT_SCHEMA, render: (_a, v) => renderSteps(v) },
      timeoutMs: 60 * 60_000,
      isConcurrencySafe: () => false,
      presentCall: execCall('Add core6000 example (gen → tts → apply)'),
      execute: (args, exec) => runtime.addExample(args, exec.agent, exec.signal),
    },
    {
      name: 'anki_today_new',
      description: '从一集字幕 / 作品目录挑今天的 N 个生词（today-new）。默认只筛指定的一集；默认演练、不改标签；commit=true 才用 --commit 真写「今天学习生词」。输入是字幕/目录路径。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        required: ['input'],
        properties: {
          input: { type: 'string', description: '字幕文件或作品目录（相对路径按工作区根解析）' },
          n: { type: 'integer', description: '每天选多少个词（默认 30）' },
          season: { type: 'boolean', description: '单集时扩到同目录整季' },
          noLlmRank: { type: 'boolean', description: '关掉 LLM 精排，退回公式排序' },
          noSenseCheck: { type: 'boolean', description: '跳过义项核验（离线快跑）' },
          noSenseRepair: { type: 'boolean', description: '义项核验被剔的词不自动修卡（通常与 noSenseCheck 一起用）' },
          commit: { type: 'boolean', description: '默认 false=演练；true 才 --commit 真写标签' },
        },
      },
      output: { schema: OUT_SCHEMA, render: (_a, v) => renderTodayNew(v) },
      timeoutMs: 60 * 60_000,
      isConcurrencySafe: () => false,
      presentCall: execCall('Pick today\'s new words'),
      execute: (args, exec) => runtime.todayNew(args, exec.agent, exec.signal),
    },
    {
      name: 'anki_vocab_cover',
      description: '给任意日文文本或字幕算词汇覆盖率（vocab cover --json）：卡组覆盖、卡组外新词、待激活词、可懂度。只读，不写 Anki。text 与 paths 至少给一个。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          text: { type: 'string', description: '直接分析的日文文本' },
          paths: { type: 'array', items: { type: 'string' }, description: '字幕/文本文件路径；相对路径按工作区根解析' },
          top: { type: 'integer', description: '打印多少个新词/待学词' },
          screen: { type: 'boolean', description: '附加卡组外新词筛选（复用 today-new 的内容词闸）' },
        },
      },
      output: { schema: OUT_SCHEMA, render: (_a, v) => renderCover(v) },
      timeoutMs: 20 * 60_000,
      isConcurrencySafe: () => false,
      presentCall: readCall('Analyze vocabulary coverage'),
      execute: (args, exec) => runtime.vocabCover(args, exec.agent, exec.signal),
    },
    {
      name: 'anki_study_report',
      description: '生成当月 ankiR 学习报告（cli.py r report --json），默认每月一次：本月已有报告就跳过，force=true 重建。只读 Anki；会写 output/reports/ankir/monthly-YYYY-MM.json。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          force: { type: 'boolean', description: '本月已有报告时仍重建' },
        },
      },
      output: { schema: OUT_SCHEMA, render: (_a, v) => renderReport(v) },
      timeoutMs: 30 * 60_000,
      isConcurrencySafe: () => false,
      presentCall: readCall('Generate monthly ankiR report'),
      execute: (args, exec) => runtime.studyReport(args, exec.agent, exec.signal),
    },
  ]
}

function isLoopback(address) {
  const value = String(address ?? '')
  return value === '127.0.0.1'
    || value === '::1'
    || value === '::ffff:127.0.0.1'
    || value.startsWith('127.')
}

function trustedRequest(req) {
  if (!isLoopback(req.socket?.remoteAddress)) return false
  const host = req.headers?.host
  const origin = req.headers?.origin
  if (origin !== undefined && origin !== '') {
    try {
      if (new URL(origin).host !== host) return false
    } catch {
      return false
    }
  }
  return true
}

function sendJson(res, status, body) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

function createApiHandler(runtime) {
  return async function handle(req, res) {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    if (url.pathname !== API_PATH && url.pathname !== `${API_PATH}/`) {
      sendJson(res, 404, { ok: false, error: 'not found' })
      return
    }
    if (!trustedRequest(req)) {
      sendJson(res, 403, { ok: false, error: 'forbidden' })
      return
    }
    if (req.method === 'GET') {
      try {
        sendJson(res, 200, { ok: true, value: await runtime.snapshot() })
      } catch (error) {
        sendJson(res, 500, { ok: false, error: String(error?.message ?? error) })
      }
      return
    }
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'method not allowed' })
      return
    }
    if (!/^application\/json\b/i.test(String(req.headers?.['content-type'] ?? ''))) {
      sendJson(res, 415, { ok: false, error: 'content-type must be application/json' })
      return
    }
    let body = ''
    let bytes = 0
    for await (const chunk of req) {
      bytes += chunk.length
      if (bytes > 2_000_000) {
        sendJson(res, 413, { ok: false, error: 'request body too large' })
        return
      }
      body += chunk
    }
    let payload
    try {
      payload = JSON.parse(body === '' ? '{}' : body)
    } catch {
      sendJson(res, 400, { ok: false, error: 'invalid JSON body' })
      return
    }
    const method = payload?.method
    const args = payload?.args ?? {}
    try {
      let value
      switch (method) {
        case 'status':
          value = await runtime.snapshot()
          break
        case 'refresh':
          value = await runtime.refreshAll()
          break
        case 'status-now':
          value = await runtime.statusNow(undefined, undefined)
          break
        case 'doctor':
          value = await runtime.doctorNow(args?.tag, undefined, undefined)
          break
        case 'add-example':
          value = await runtime.addExample(args, undefined, undefined)
          break
        case 'today-new':
          value = await runtime.todayNew(args, undefined, undefined)
          break
        case 'vocab-cover':
          value = await runtime.vocabCover(args, undefined, undefined)
          break
        case 'browse':
          value = await runtime.browse(args, undefined)
          break
        case 'study-report':
          value = await runtime.studyReport(args, undefined, undefined)
          break
        case 'report':
          value = await runtime.reportData(args?.month, undefined)
          break
        default:
          sendJson(res, 404, { ok: false, error: `unknown method: ${String(method)}` })
          return
      }
      sendJson(res, 200, { ok: true, value })
    } catch (error) {
      sendJson(res, 500, { ok: false, error: String(error?.message ?? error) })
    }
  }
}

export function apply(ctx, config = {}) {
  const runtime = createRuntime(ctx, config)

  for (const definition of makeTools(runtime)) {
    ctx.effect(() => ctx.tools.register(definition))
  }

  ctx.effect(() => ctx.systemPrompt.context({
    name: 'anki-workspace',
    order: 300,
    interpolate: false,
    text: () => runtime.contextText(),
  }))

  ctx.effect(() => ctx.webServer.register({
    kind: 'prefix',
    path: API_PREFIX,
    handler: createApiHandler(runtime),
  }))

  ctx.effect(() => ctx.on('agent/created', () => {
    runtime.refreshIfStale(60_000)
  }))

  const timer = ctx.get('timer')
  if (timer !== undefined) {
    ctx.effect(() => timer.interval(() => runtime.refreshInBackground(), runtime.config.refreshMs))
  }

  runtime.refreshInBackground()
}
