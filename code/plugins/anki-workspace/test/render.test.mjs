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
