// Locale wiring test for the Client half.
//
// Regression guard for the "every label shows its raw key" bug: the panel's
// copy comes from the Client locale service, whose `locale` service is
// provided only after an async bootstrap. This test drives `apply` with a
// minimal context and proves that
//   1. both dictionaries reach `locale.register`, and the sidebar label and
//      panel translate instead of echoing keys; and
//   2. a locale service that appears after `apply` is still adopted.

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

const React = {
  createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
  Fragment: 'Fragment',
  useState: (initial) => [initial, () => {}],
  useEffect() {},
  useRef: (value) => ({ current: value === undefined ? null : value }),
  useCallback: (fn) => fn,
  useMemo: (factory) => factory(),
}

await import(new URL('../client.js', import.meta.url).href)
const module = captured.factory(() => React)

function fakeLocale() {
  const registered = []
  const dicts = {}
  return {
    registered,
    register(ns, lang, dict) {
      registered.push([ns, lang])
      dicts[lang] = dict
      return () => {}
    },
    bind() {
      return (key) => dicts.zh?.[key] ?? dicts.en?.[key] ?? key
    },
  }
}

function fakeContext(locale) {
  const slots = []
  const ctx = {
    get(name) {
      if (name === 'locale') return locale
      if (name === 'slots') return ctx.slots
      return undefined
    },
    effect(fn) {
      return fn()
    },
    slots: {
      inject(_owner, callback) {
        callback()
      },
      register(options, component) {
        slots.push({ options, component })
        return () => {}
      },
    },
  }
  return { ctx, slots }
}

test('apply registers both dictionaries and translates panel copy', () => {
  const locale = fakeLocale()
  const { ctx, slots } = fakeContext(locale)
  module.apply(ctx)

  assert.deepEqual(locale.registered.sort(), [
    ['anki-workspace', 'en'],
    ['anki-workspace', 'zh'],
  ])

  const sidebar = slots.find((entry) => entry.options.name === 'sidebar.panellist')
  assert.ok(sidebar, 'sidebar entry registered')
  assert.equal(sidebar.options.label(), 'Anki 工作区')

  const main = slots.find((entry) => entry.options.name === 'main')
  assert.equal(main.options.key, 'anki-workspace')
  // The panel component receives the bound translate function.
  const tree = main.component({})
  assert.equal(tree.props.t('panel.title'), 'Anki 工作区')
})

test('a locale service that appears after apply is adopted', () => {
  const late = fakeLocale()
  const pending = []
  const { ctx, slots } = fakeContext(undefined)
  ctx.inject = (deps, callback) => {
    assert.deepEqual(deps, ['locale'])
    pending.push(callback)
  }
  module.apply(ctx)
  assert.equal(pending.length, 1, 'falls back to a dynamic injection')

  pending[0]({ get: (name) => (name === 'locale' ? late : undefined) })
  assert.deepEqual(late.registered.sort(), [
    ['anki-workspace', 'en'],
    ['anki-workspace', 'zh'],
  ])

  const sidebar = slots.find((entry) => entry.options.name === 'sidebar.panellist')
  assert.equal(sidebar.options.label(), 'Anki 工作区')
})

test('card-fix tab labels translate in both languages', () => {
  const locale = fakeLocale()
  const { ctx, slots } = fakeContext(locale)
  module.apply(ctx)

  const main = slots.find((entry) => entry.options.name === 'main')
  const tree = main.component({})
  const t = tree.props.t

  // Chinese translations for the renamed tab and its placeholder card.
  assert.equal(t('tabs.cardFix'), '卡片修正')
  assert.equal(t('card.wordAudio.title'), '单词配音（Word Audio）')
  assert.equal(t('card.fix.title'), '按单词重新生成')
  assert.equal(t('card.wordAudio.plan'), '查候选卡')
  assert.equal(t('card.wordAudio.apply'), '生成 / 更新')
  assert.equal(t('wordAudio.candidates'), '候选卡片')
  assert.equal(t('wordAudio.empty'), '空')
  assert.equal(t('wordAudio.has'), '已有音频')
  // 阶段 2：Sentence HTML 重新生成按钮与候选区文案。
  assert.equal(t('card.fix.htmlBtn'), '重新生成 Sentence HTML')
  assert.equal(t('card.fix.lookup'), '查卡片')
  assert.equal(t('card.fix.wordInput'), '单词名（词典形）')
  assert.equal(t('card.fix.none'), '没找到 Word 等于这个单词、且带 Sentence / AINote / Sentence HTML 的卡')
  assert.equal(t('card.fix.commit'), '真写库（--commit，默认勾选）')
  // 阶段 3：AINote 重新生成按钮与 output 折叠区标题。
  assert.equal(t('card.fix.ainoteBtn'), '重新生成 AINote')
  assert.equal(t('card.fix.output'), '脚本原始输出')
  // 统一输入 + checkbox + 单按钮 + tooltip。
  assert.equal(t('card.fix.run'), '重新生成')
  assert.equal(t('card.fix.audio'), '音频')
  assert.equal(t('card.fix.force'), '覆盖已有音频')
  assert.match(t('card.fix.wordTip'), /一个输入框/)
  assert.match(t('card.fix.audioTip'), /Word Audio/)
  assert.match(t('card.fix.htmlTip'), /Sentence HTML/)
  assert.match(t('card.fix.ainoteTip'), /AINote/)
  assert.match(t('card.fix.commitTip'), /真写库/)
  assert.match(t('card.fix.runTip'), /只有一张/)
})
