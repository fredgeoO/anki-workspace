// Offline render smoke test for the panel's structured result views.
//
// The Client half is a ModuleLoader script, not an ES module, so this test
// installs a capturing `window.__ModuleLoader__` first, then imports the file
// and calls the result components with a tiny React stub. It catches the
// class of bug a browser would hit immediately (undefined field, bad child,
// missing hook) without needing a browser or a DOM.

import assert from 'node:assert/strict'
import test from 'node:test'

let captured = null
globalThis.window = {
  __ModuleLoader__: {
    load(spec) {
      captured = spec
    },
  },
}
await import(new URL('../client.js', import.meta.url).href)

function element(type, props, ...children) {
  const normalized = children.length === 0
    ? undefined
    : children.length === 1 ? children[0] : children
  if (typeof type === 'function') {
    const next = Object.assign({}, props || {})
    if (normalized !== undefined) next.children = normalized
    return type(next)
  }
  return { type, props: props || {}, children: normalized }
}

const React = {
  createElement: element,
  Fragment: 'Fragment',
  useState(initial) {
    return [typeof initial === 'function' ? initial() : initial, () => {}]
  },
  useEffect() {},
  useRef(value) {
    return { current: value === undefined ? null : value }
  },
  useCallback(fn) {
    return fn
  },
  useMemo(factory) {
    return factory()
  },
}

const components = captured.factory((name) => {
  assert.equal(name, 'react')
  return React
}).__components

function textOf(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join(' ')
  return textOf(node.children)
}

function nodesOf(node, out = []) {
  if (node == null || typeof node !== 'object') return out
  if (Array.isArray(node)) {
    for (const child of node) nodesOf(child, out)
    return out
  }
  out.push(node)
  nodesOf(node.children, out)
  return out
}

const t = (key) => key

const todayValue = {
  ok: true,
  exitCode: 0,
  result: {
    schema: 1,
    tool: 'today-new',
    source: 'subtitles/作品/第01集.srt',
    generated_at: '2026-11-03T20:00:00',
    commit: false,
    dry_run: true,
    window: { episodes: 1, season: false, labels: ['第01集'] },
    counts: { candidates: 203, picked: 10, notes: 11, ranked_by: 'llm' },
    ranking: { by: 'llm', calls: 1, secs: 2.3, cached: false },
    formula: { mu: 0.3, lam: 0.3 },
    plan: { old: 47, keep: 1, remove: 46, add: 10 },
    picked: [{
      word: 'お客様',
      reading: 'おきゃくさま',
      pos: '名词',
      level: '素材生词',
      jiten: 1901,
      occurrences: 16,
      episodes: 1,
      score: 3.87,
      why: '剧情核心',
      notes: [1, 2],
      first: { text: '愛すべきお客様に最高の笑顔を' },
      sense_repaired: true,
    }],
    pending: [{ word: 'だけ', reading: 'だけ', occurrences: 4 }],
    dropped: [{ word: '払う', noteId: 1, reason: '已不是新卡' }],
    dropped_sense: [{
      word: '頭', card_meaning: '首领', sense_gloss: '头', why: '义项对不上',
    }],
    sense_repaired: [
      { word: '顔', ok: true, why: '已补例句' },
      { word: '手', ok: false, why: '修不好' },
    ],
    skipped: { no_rank: 0, no_notes: 194, reading: 3, phrases: 0, unranked: 2 },
    write: { committed: false, verified: null, removed: 0, added: 0, tagged: 0 },
    artifacts: null,
  },
}

const coverValue = {
  ok: true,
  result: {
    schema: 1,
    tool: 'vocab-cover',
    label: 'subtitles/作品/第01集.srt',
    generated_at: '2026-11-03T20:00:00',
    chars: 1234,
    tokens: 456,
    types: 123,
    cover_all: {
      core: 0.5, corejlpt: 0.55, deck: 0.82, known: 0.71, mature: 0.5,
      understood_lenient: 0.94, understood: 0.9, oov: 0.1, proper: 0.01,
    },
    cover_vocab: {
      core: 0.6, corejlpt: 0.65, deck: 0.88, known: 0.78, mature: 0.55,
      understood_lenient: 0.96, understood: 0.92, oov: 0.12, proper: 0.02,
    },
    cover_learnable: {
      core: 0.7, corejlpt: 0.75, deck: 0.9, known: 0.8, mature: 0.6,
      understood_lenient: 0.97, understood: 0.93, oov: 0.15, proper: 0.03,
    },
    comprehension: { by_understood: 0.94, by_understood_listening: 0.91 },
    sentences: { sentences: 40, full: 0.7, lenient_l: 0.9 },
    reach: {
      core6000: { seen: 40, deck_total: 5894, seen_ratio: 0.0068, new_to_me: 3 },
      jlpt: { seen: 12, deck_total: 10529, seen_ratio: 0.0011, new_to_me: 1 },
      deck: { seen: 52, deck_total: 21124, seen_ratio: 0.0025 },
    },
    oov: [['放課後', 3], ['屋上', 1]],
    untackled: [['銀河', 'core', 2]],
    summary: {
      chars: 1234, tokens: 456, types: 123, deck: 0.82, known: 0.71,
      mature: 0.5, understood: 0.94, strict: 0.9, comprehension: 0.94,
      sentence_full: 0.7, sentence_lenient: 0.9, oov_types: 2,
      untackled_types: 1, deck_total: 21124, deck_seen: 52,
    },
    screen: {
      candidates: 2,
      ranked_by: 'llm',
      words: [{
        word: '放課後', reading: 'ほうかご', pos: '名詞', occurrences: 3,
        why: '日常对话高频', first: '放課後の屋上で',
      }],
    },
  },
}

const reportValue = {
  ok: true,
  skipped: true,
  reason: '本月报告已生成（每月一次；force=true 可重建）',
  month: '2026-11',
  reportPath: 'output/reports/ankir/monthly-2026-11.json',
  bytes: 501,
  mtime: '2026-11-03T11:38:32.000Z',
  report: {
    total_cards: 42377,
    total_notes: 39849,
    total_decks: 25,
    total_reviews: 57669,
    new_cards: 35150,
    learning_cards: 0,
    review_cards: 7227,
    suspended_cards: 12,
    buried_cards: 0,
    mature_cards: 5929,
    young_cards: 1298,
    mature_percent: 82.04,
    first_review: '2026-06-09',
    last_review: '2026-11-03',
    days_studied: 148,
    avg_reviews_per_day: 389.7,
    retention_rate: 82.3,
    total_time_hours: 325.2,
    current_streak: 148,
    longest_streak: 148,
  },
}

test('today-new result renders words, status, plan and audit sections', () => {
  const tree = components.TodayNewResult({ t, value: todayValue })
  const text = textOf(tree)
  assert.match(text, /お客様/)
  assert.match(text, /おきゃくさま/)
  assert.match(text, /result\.dryRun/)
  assert.match(text, /result\.plan\.title/)
  assert.match(text, /result\.sense\.failed/)
  assert.match(text, /修不好/)
  assert.match(text, /已不是新卡/)
  assert.match(text, /result\.skip\.noNotes/)
})

test('today-new result handles a committed run and a failed run', () => {
  const committed = JSON.parse(JSON.stringify(todayValue))
  committed.result.commit = true
  committed.result.dry_run = false
  committed.result.write = { committed: true, verified: true, removed: 46, added: 10, tagged: 10 }
  committed.result.artifacts = { picked_json: 'data/daily_new/x/picked.json', report_md: 'output/daily/x.md' }
  const committedText = textOf(components.TodayNewResult({ t, value: committed }))
  assert.match(committedText, /result\.committed/)
  assert.match(committedText, /picked\.json/)

  const failed = { ok: false, exitCode: 2, error: '没有可选的词', result: { ok: false, error: '没有可选的词', picked: [] } }
  const failedText = textOf(components.TodayNewResult({ t, value: failed }))
  assert.match(failedText, /没有可选的词/)
  assert.match(failedText, /result\.failed/)
})

test('vocab cover result renders hero metrics, table, oov and screen words', () => {
  const tree = components.CoverResult({ t, value: coverValue })
  const text = textOf(tree)
  assert.match(text, /cover\.understood/)
  assert.match(text, /cover\.row\.core/)
  assert.match(text, /cover\.oov\.title/)
  assert.match(text, /放課後/)
  assert.match(text, /cover\.screen\.title/)
  assert.match(text, /94\.0%/)

  const list = { ok: true, result: [coverValue.result, coverValue.result] }
  assert.ok(textOf(components.CoverResult({ t, value: list })).length > 0)
})

test('report result renders monthly JSON as KPIs, maturity and composition', () => {
  const text = textOf(components.ReportResult({ t, value: reportValue }))
  assert.match(text, /report\.retention/)
  assert.match(text, /82\.3%/)
  assert.match(text, /82\.0%/)
  assert.match(text, /42[,.]377/)
  assert.match(text, /report\.maturity/)
  assert.match(text, /report\.composition/)
  assert.match(text, /report\.raw/)
  assert.match(text, /2026-11-03/)
  assert.match(text, /monthly-2026-11\.json/)
})

test('report result shows the empty and parse-error states', () => {
  const empty = textOf(components.ReportResult({ t, value: { exists: false, report: null } }))
  assert.match(empty, /report\.empty/)

  const broken = textOf(components.ReportResult({
    t,
    value: { exists: true, report: null, parseError: '坏 JSON' },
  }))
  assert.match(broken, /report\.failed/)
  assert.match(broken, /坏 JSON/)
})

test('tab bar and compact status pills render their labels', () => {
  const tabs = textOf(components.TabBar({ t, active: 'study-report', onChange: () => {} }))
  assert.match(tabs, /tabs\.addExample/)
  assert.match(tabs, /tabs\.todayNew/)
  assert.match(tabs, /tabs\.cover/)
  assert.match(tabs, /tabs\.report/)
  assert.match(tabs, /tabs\.cardFix/)
  // 卡片修正 tab 是宽按钮（wide），其余不是。
  const wide = nodesOf(components.TabBar({ t, active: 'study-report', onChange: () => {} }))
    .filter((node) => node.props && typeof node.props.className === 'string' && node.props.className.includes('anki-tab-wide'))
  assert.equal(wide.length, 1)

  const corner = textOf(components.StatusCorner({
    t,
    anki: { online: true, version: 6, decks: 25, noteTypes: 15, media: 100, latencyMs: 874 },
    doctor: { status: 'hint', passed: 6, hints: 8, blocking: 0, summary: '可开工' },
    busy: '',
    updated: '2026-11-03T12:00:00.000Z',
    onAction: () => {},
  }))
  assert.match(corner, /status\.online/)
  assert.match(corner, /status\.hint/)
})

test('panel rehydrates cached tab results after a sidebar remount', () => {
  const cache = components.PANEL_CACHE
  cache.snapshot = {
    anki: { online: true, version: 6, decks: 25, noteTypes: 15, media: 100, latencyMs: 874 },
    doctor: { status: 'hint', passed: 6, hints: 8, blocking: 0, summary: '可开工' },
    monthlyReport: { exists: false, path: 'output/reports/ankir/monthly-2026-11.json' },
    refreshedAt: '2026-11-03T12:00:00.000Z',
  }
  cache.results = { 'today-new': todayValue }
  cache.activeTab = 'today-new'

  const text = textOf(components.AnkiPanel({ t }))
  assert.match(text, /お客様/)
  assert.match(text, /result\.plan\.title/)
})

test('add-example is rendered as a tab panel, not a standalone card', () => {
  const cache = components.PANEL_CACHE
  cache.snapshot = {
    anki: { online: true, version: 6, decks: 25, noteTypes: 15, media: 100, latencyMs: 874 },
    doctor: { status: 'hint', passed: 6, hints: 8, blocking: 0, summary: '可开工' },
    monthlyReport: { exists: false, path: 'output/reports/ankir/monthly-2026-11.json' },
    refreshedAt: '2026-11-03T12:00:00.000Z',
  }
  cache.results = {}
  cache.reportSnapshot = null
  cache.activeTab = 'add-example'

  const tree = components.AnkiPanel({ t })
  const nodes = nodesOf(tree)
  const panels = nodes.filter((node) => node.props && node.props.role === 'tabpanel')
  assert.deepEqual(panels.map((node) => node.props.id), [
    'anki-panel-add-example',
    'anki-panel-today-new',
    'anki-panel-vocab-cover',
    'anki-panel-study-report',
    'anki-panel-card-fix',
  ])

  const addPanel = panels[0]
  assert.equal(addPanel.props.hidden, false)
  assert.equal(panels[1].props.hidden, true)
  assert.match(textOf(addPanel), /card\.addExample\.desc/)
  assert.match(textOf(addPanel), /card\.addExample\.run/)
  // The tab label carries the title, so a tabbed card must not repeat the h3.
  assert.equal(nodesOf(addPanel).filter((node) => node.type === 'h3').length, 0)
  // No card outside the tab group any more.
  assert.equal(nodes.filter((node) => node.props && node.props.className === 'anki-solo').length, 0)
})

const wordAudioPlanValue = {
  ok: true,
  phase: 'plan',
  word: 'キャンプ場',
  exitCode: 0,
  candidates: [
    { word: 'キャンプ場', reading: 'きゃんぷじょう', noteId: 1792712150771, wordAudio: null, wordAudioEmpty: true, sentenceAudio: 'ik_drama_x.mp3', sentenceAudioEmpty: false, action: '生成 词TTS' },
    { word: 'キャンプ場', reading: 'きゃんぷじょう', noteId: 1792712150772, wordAudio: 'mine-キャンプ場-fd034fb0.mp3', wordAudioEmpty: false, sentenceAudio: null, sentenceAudioEmpty: true, action: '保留' },
  ],
  output: '',
  note: '2 张候选卡；选一张后点「生成/更新」真写。',
}

const wordAudioApplyValue = {
  ok: true,
  phase: 'apply',
  word: 'キャンプ場',
  commit: true,
  noteIds: ['1792712150771'],
  verified: true,
  output: '回读校验 1 张：Word Audio 1 / Sentence Audio 1 非空\n★ 全部通过',
  note: '已真写：合成 TTS、上传媒体、写 Word Audio 字段并回读。',
}

test('word-audio card renders plan candidates with audio status tags', () => {
  const tree = components.WordAudioCard({
    t,
    call: () => {},
    busy: '',
    result: wordAudioPlanValue,
    tabbed: true,
  })
  const text = textOf(tree)
  assert.match(text, /キャンプ場/)
  assert.match(text, /きゃんぷじょう/)
  assert.match(text, /wordAudio\.empty/)
  assert.match(text, /mine-キャンプ場-fd034fb0\.mp3/)
  assert.match(text, /card\.wordAudio\.apply/)
})

test('word-audio card renders apply result with verified badge', () => {
  const tree = components.WordAudioCard({
    t,
    call: () => {},
    busy: '',
    result: wordAudioApplyValue,
    tabbed: true,
  })
  const text = textOf(tree)
  assert.match(text, /result\.committed/)
  assert.match(text, /noteIds/)
  assert.match(text, /回读校验通过/)
})

test('word-audio card shows empty state when no candidates found', () => {
  const emptyPlan = { ...wordAudioPlanValue, candidates: [], note: '没有匹配到任何卡片。' }
  const tree = components.WordAudioCard({
    t,
    call: () => {},
    busy: '',
    result: emptyPlan,
    tabbed: true,
  })
  const text = textOf(tree)
  assert.match(text, /wordAudio\.none/)
})

const cardFixLookupValue = {
  ok: true,
  noteIds: ['1792712150771', '1792712150772'],
  cards: [
    { noteId: 1792712150771, sentence: '愛すべきお客様に最高の笑顔を', word: 'お客様', source: '第01集', hasAinote: true, hasHtml: false, ainote: '讲解…', html: '' },
    { noteId: 1792712150772, sentence: '屋上で待っている', word: '屋上', source: '第02集', hasAinote: false, hasHtml: true, ainote: '', html: '<ruby>屋上<rt>おくじょう</rt></ruby>' },
  ],
  output: '',
}

const cardFixHtmlValue = {
  ok: true,
  field: 'html',
  commit: true,
  noteIds: ['1792712150771'],
  exitCode: 0,
  verified: true,
  cards: [{ noteId: 1792712150771, sentence: '愛すべきお客様に最高の笑顔を', value: '<ruby>お客様<rt>おきゃくさま</rt></ruby>' }],
  output: 'gen --only html：1 张完成\n★ 全部通过',
  note: '默认真写：cards.py gen --commit 已写入选中字段并回读（另一字段不动）。',
}

const cardFixAinoteValue = {
  ok: true,
  field: 'ainote',
  commit: false,
  noteIds: ['1792712150771'],
  exitCode: 0,
  cards: [{ noteId: 1792712150771, sentence: '愛すべきお客様に最高の笑顔を', value: '① お客様＝客人…' }],
  output: 'gen --only ainote：1 张完成（演练）',
  note: '演练：未写库。',
}

test('field-fix card renders selected candidate, sentence and HTML button', () => {
  const tree = components.FieldFixCard({
    t,
    call: () => {},
    busy: '',
    lookupValue: cardFixLookupValue,
    htmlValue: null,
  })
  const text = textOf(tree)
  assert.match(text, /card\.fix\.lookup/)
  assert.match(text, /card\.fix\.cards/)
  assert.match(text, /愛すべきお客様に最高の笑顔を/)
  assert.match(text, /card\.fix\.has/)
  assert.match(text, /card\.fix\.empty/)
  assert.match(text, /card\.fix\.htmlBtn/)
  // select 存在且默认第 0 张；placeholder 是输入框属性，不在文本里。
  const inputs = nodesOf(tree).filter((node) => node.type === 'input')
  assert.ok(inputs.some((node) => node.props.placeholder === 'card.fix.wordInput'))
  const selects = nodesOf(tree).filter((node) => node.type === 'select')
  assert.equal(selects.length, 1)
  assert.equal(selects[0].props.value, '0')
})

test('field-fix card renders both regenerate buttons together', () => {
  const tree = components.FieldFixCard({
    t,
    call: () => {},
    busy: '',
    lookupValue: cardFixLookupValue,
    htmlValue: null,
    ainoteValue: null,
  })
  const text = textOf(tree)
  assert.match(text, /card\.fix\.htmlBtn/)
  assert.match(text, /card\.fix\.ainoteBtn/)
})

test('field-fix card renders AINote button result with its own value', () => {
  const tree = components.FieldFixCard({
    t,
    call: () => {},
    busy: '',
    lookupValue: cardFixLookupValue,
    htmlValue: null,
    ainoteValue: cardFixAinoteValue,
  })
  const text = textOf(tree)
  assert.match(text, /card\.fix\.ainoteBtn/)
  assert.match(text, /① お客様＝客人…/)
  assert.match(text, /result\.dryRun/)
  assert.match(text, /gen --only ainote/)
})

test('field-fix card shows generated result with per-card value and output details', () => {
  const tree = components.FieldFixCard({
    t,
    call: () => {},
    busy: '',
    lookupValue: cardFixLookupValue,
    htmlValue: cardFixHtmlValue,
  })
  const text = textOf(tree)
  assert.match(text, /card\.fix\.generated/)
  assert.match(text, /<ruby>お客様<rt>/)
  assert.match(text, /1792712150771/)
  assert.match(text, /result\.committed/)
  assert.match(text, /gen --only html/)
  // output 折叠区标题走 locale。
  assert.match(text, /card\.fix\.output/)
})

test('field-fix card shows card.fix.none for an empty lookup', () => {
  const tree = components.FieldFixCard({
    t,
    call: () => {},
    busy: '',
    lookupValue: { ok: true, cards: [], noteIds: [] },
    htmlValue: null,
  })
  assert.match(textOf(tree), /card\.fix\.none/)
})

test('card-fix panel uses one word input, target checkboxes and one regenerate button', () => {
  const tree = components.CardFixCard({
    t,
    call: () => {},
    busy: '',
    results: {},
  })
  assert.equal(tree.props.className, 'anki-card')
  const text = textOf(tree)
  assert.match(text, /card\.fix\.title/)
  assert.match(text, /card\.fix\.desc/)
  assert.match(text, /card\.fix\.audio/)
  assert.match(text, /Sentence HTML/)
  assert.match(text, /AINote/)
  assert.match(text, /card\.fix\.run/)

  const nodes = nodesOf(tree)
  // 共用一个单词输入：只有一个非 checkbox 的 input。
  const textInputs = nodes.filter((node) => node.type === 'input' && node.props.type !== 'checkbox')
  assert.equal(textInputs.length, 1)
  assert.equal(textInputs[0].props.placeholder, 'card.fix.wordInput')
  assert.equal(textInputs[0].props.title, 'card.fix.wordTip')

  // 音频 / HTML / AINote + 真写 都是 checkbox（「覆盖已有音频」只在勾了音频时出现，
  // 三个目标默认都不勾，所以这里至少 4 个）。
  const checks = nodes.filter((node) => node.type === 'input' && node.props.type === 'checkbox')
  assert.ok(checks.length >= 4)

  // mouseover tooltip 挂在输入框、目标 checkbox 和按钮上。
  const titles = nodes
    .filter((node) => node.props && typeof node.props.title === 'string')
    .map((node) => node.props.title)
  assert.ok(titles.includes('card.fix.audioTip'))
  assert.ok(titles.includes('card.fix.htmlTip'))
  assert.ok(titles.includes('card.fix.ainoteTip'))
  assert.ok(titles.includes('card.fix.runTip'))
  assert.ok(titles.includes('card.fix.commitTip'))
})

test('card-fix target checkboxes start unticked so nothing regenerates by default', () => {
  // 用户 2026-11-13 定：音频 / Sentence HTML / AINote 三个目标默认都不勾，
  // 必须先勾要重做的字段，「重新生成」才可用（避免一点就把整张卡重做）。
  const tree = components.CardFixCard({ t, call: () => {}, busy: '', results: {} })
  const nodes = nodesOf(tree)
  const inputByTitle = (title) => nodes.find(
    (node) => node.type === 'input' && node.props && node.props.title === title,
  )
  for (const tip of ['card.fix.audioTip', 'card.fix.htmlTip', 'card.fix.ainoteTip']) {
    const input = inputByTitle(tip)
    assert.ok(input, `${tip} checkbox exists`)
    assert.equal(input.props.checked, false, `${tip} 默认不勾`)
  }
  // 一个目标都没勾 → hasTarget 为 false，按钮禁用（无目标提示只在填了单词后显示）。
  const run = nodes.find((node) => node.type === 'button' && node.props.title === 'card.fix.runTip')
  assert.equal(run.props.disabled, true)
})

test('card-fix panel renders audio and field generation results', () => {
  const tree = components.CardFixCard({
    t,
    call: () => {},
    busy: '',
    results: {
      'word-audio-apply': wordAudioApplyValue,
      'card-fix-ainote': cardFixAinoteValue,
    },
  })
  const text = textOf(tree)
  assert.match(text, /① お客様＝客人…/)
  assert.match(text, /result\.committed/)
})
