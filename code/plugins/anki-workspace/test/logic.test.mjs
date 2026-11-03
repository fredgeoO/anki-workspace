import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildAddExampleCalls,
  buildCoverArgs,
  buildTodayNewArgs,
  crumbsFor,
  extractJson,
  isInside,
  monthKey,
  monthlyReportRelPath,
  normalizeRelPath,
  parseAnkiCheck,
  parseDoctor,
  sortAndCapEntries,
  tail,
  toRelPath,
} from '../lib/core.js'

const DOCTOR_SAMPLE = `
小结
  ✓ 通过 6 项
  · 提示 8 项（可以继续干活）
  ✗ 阻塞 0 项（必须先修）
结论：✓ 可开工（有 8 条提示，注意上面的内容）。
`

test('parseDoctor maps exit codes and counts to the 0/2/1 contract', () => {
  const hint = parseDoctor(DOCTOR_SAMPLE, 2)
  assert.equal(hint.status, 'hint')
  assert.equal(hint.label, '提示')
  assert.equal(hint.passed, 6)
  assert.equal(hint.hints, 8)
  assert.equal(hint.blocking, 0)
  assert.match(hint.summary, /可开工/)

  assert.equal(parseDoctor('✓ 通过 9 项\n· 提示 0 项\n✗ 阻塞 0 项', 0).status, 'green')
  assert.equal(parseDoctor('✓ 通过 4 项\n· 提示 0 项\n✗ 阻塞 2 项', 1).status, 'blocked')
  assert.equal(parseDoctor('', null).status, 'error')
})

test('parseAnkiCheck reads version, deck, note type and media counts', () => {
  const parsed = parseAnkiCheck(`
AnkiConnect   http://127.0.0.1:8765
  版本        6
  牌组        25 个
  笔记类型    6 个
  媒体文件    79980 个
`)
  assert.deepEqual(parsed, { version: '6', decks: 25, noteTypes: 6, media: 79980 })
  assert.deepEqual(parseAnkiCheck('offline'), { version: null, decks: null, noteTypes: null, media: null })
})

test('monthly report key and path use the configured calendar month', () => {
  const at = new Date('2026-11-03T12:00:00Z')
  assert.equal(monthKey(at, 'Asia/Shanghai'), '2026-11')
  assert.equal(monthKey(at, 'UTC'), '2026-11')
  assert.equal(monthKey(new Date('2026-10-31T20:00:00Z'), 'UTC'), '2026-10')
  assert.equal(monthKey(new Date('2026-10-31T20:00:00Z'), 'Asia/Shanghai'), '2026-11')
  assert.equal(monthlyReportRelPath('2026-11'), 'output/reports/ankir/monthly-2026-11.json')
})

test('core6000 chain is gen -> tts -> apply and only commits when asked', () => {
  const dry = buildAddExampleCalls(['--words', '徹夜'], false)
  assert.deepEqual(dry.map((call) => call.name), ['gen', 'tts', 'apply'])
  assert.equal(dry[0].argv.join(' '), 'code/cli.py core6000 gen --words 徹夜')
  assert.equal(dry[2].argv.includes('--commit'), false)

  const commit = buildAddExampleCalls(['--note-ids', '123'], true)
  assert.equal(commit[2].argv.includes('--commit'), true)
  assert.equal(commit[0].argv.includes('--commit'), false)
  assert.equal(commit[1].argv.includes('--commit'), false)
})

test('today-new is dry by default, asks for JSON and only writes with commit', () => {
  const dry = buildTodayNewArgs({ input: 'a.srt', n: 12, season: true })
  assert.deepEqual(dry.argv, ['code/cli.py', 'today-new', 'a.srt', '--json', '--n', '12', '--season'])
  assert.equal(dry.commit, false)

  const commit = buildTodayNewArgs({ input: 'a.srt', commit: true })
  assert.equal(commit.argv.includes('--commit'), true)
  assert.equal(commit.argv.includes('--json'), true)
  assert.equal(commit.commit, true)
  const fast = buildTodayNewArgs({ input: 'a.srt', noSenseCheck: true, noSenseRepair: true })
  assert.equal(fast.argv.includes('--no-sense-check'), true)
  assert.equal(fast.argv.includes('--no-sense-repair'), true)
  assert.deepEqual(buildTodayNewArgs({}), { error: '需要 input（字幕文件或作品目录）' })
})

test('vocab cover resolves relative paths and always asks for JSON', () => {
  const root = 'C:/work/anki-workspace'
  const built = buildCoverArgs(root, { paths: ['subtitles/a.srt'], top: 20 })
  assert.equal(built.argv[0], 'code/cli.py')
  assert.equal(built.argv[1], 'vocab')
  assert.equal(built.argv[2], 'cover')
  assert.equal(built.argv[3], 'C:\\work\\anki-workspace\\subtitles\\a.srt')
  assert.equal(built.argv.includes('--json'), true)
  assert.equal(built.argv.includes('--top'), true)

  const text = buildCoverArgs(root, { text: '日本語の文章' })
  assert.equal(text.argv.includes('--text'), true)
  assert.equal(text.argv.includes('--json'), true)
  assert.deepEqual(buildCoverArgs(root, {}), { error: '需要 text 或至少一个 paths 条目' })
})

test('extractJson skips the dispatcher banner and trailing warnings', () => {
  const mixed = '→ code\\analysis\\vocab_cover\\cover_cli.py\n{"cover": {"deck": 0.9}, "oov": []}\nR: some warning\n'
  assert.deepEqual(extractJson(mixed), { cover: { deck: 0.9 }, oov: [] })
  assert.equal(extractJson('no json here'), null)
  assert.deepEqual(extractJson('{"a": 1}'), { a: 1 })

  // A workspace path in the banner may itself contain braces.
  const tricky = '→ code\\tools\\today_new_words.py "subtitles\\{作品}\\第01集.srt"\n{"ok": true}\n'
  assert.deepEqual(extractJson(tricky), { ok: true })
})

test('tail keeps short text and clips long text to the end', () => {
  assert.equal(tail('abc', 10), 'abc')
  const clipped = tail('0123456789', 4)
  assert.match(clipped, /前文省略/)
  assert.ok(clipped.endsWith('6789'))
})

test('picker paths normalise to forward slashes and stay under the root', () => {
  assert.equal(normalizeRelPath(''), '')
  assert.equal(normalizeRelPath('./subtitles//a.srt'), 'subtitles/a.srt')
  assert.equal(normalizeRelPath('subtitles\\作品\\第01集.srt'), 'subtitles/作品/第01集.srt')
  assert.equal(normalizeRelPath('../../etc/passwd'), 'etc/passwd')
  assert.equal(normalizeRelPath('a/b/../c'), 'a/c')

  const root = 'C:/work/anki-workspace'
  assert.equal(isInside(root, 'C:/work/anki-workspace/subtitles'), true)
  assert.equal(isInside(root, 'C:/work/anki-workspace'), true)
  assert.equal(isInside(root, 'C:/work/other'), false)
  assert.equal(isInside(root, 'C:/work/anki-workspace/../outside'), false)
  assert.equal(toRelPath(root, 'C:/work/anki-workspace/subtitles/a.srt'), 'subtitles/a.srt')
  assert.equal(toRelPath(root, root), '')
})

test('picker lists directories first and caps oversized folders', () => {
  const sorted = sortAndCapEntries([
    { name: 'b.srt', kind: 'file' },
    { name: 'subtitles', kind: 'dir' },
    { name: 'a.srt', kind: 'file' },
    { name: '作品', kind: 'dir' },
  ])
  assert.deepEqual(sorted.entries.map((entry) => entry.name), ['subtitles', '作品', 'a.srt', 'b.srt'])
  assert.equal(sorted.truncated, false)

  const many = Array.from({ length: 9 }, (_, index) => ({ name: `f${index}.txt`, kind: 'file' }))
  const capped = sortAndCapEntries(many, 5)
  assert.equal(capped.entries.length, 5)
  assert.equal(capped.total, 9)
  assert.equal(capped.truncated, true)
})

test('picker crumbs walk from the workspace root to the current folder', () => {
  assert.deepEqual(crumbsFor('', 'anki-workspace'), [{ name: 'anki-workspace', path: '' }])
  assert.deepEqual(crumbsFor('subtitles/作品', 'anki-workspace'), [
    { name: 'anki-workspace', path: '' },
    { name: 'subtitles', path: 'subtitles' },
    { name: '作品', path: 'subtitles/作品' },
  ])
})
