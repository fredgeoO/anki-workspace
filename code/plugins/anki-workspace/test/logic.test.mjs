import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildAddExampleCalls,
  buildCardFixArgv,
  buildCoverArgs,
  buildSeasonNewArgs,
  buildTodayNewArgs,
  cardLookupCards,
  crumbsFor,
  extractJson,
  isInside,
  monthKey,
  monthlyReportRelPath,
  mergeLlm,
  normalizeLlmModels,
  normalizeNoteIds,
  normalizeRelPath,
  parseAnkiCheck,
  parseDoctor,
  parseWordAudioCandidates,
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

test('core6000 chain is gen -> tts -> apply and commits unless explicitly told not to', () => {
  // 默认真写（用户 2026-11-09 定的规矩）：省略 / true 都带 --commit，只有显式 false 才演练。
  const def = buildAddExampleCalls(['--words', '徹夜'])
  assert.deepEqual(def.map((call) => call.name), ['gen', 'tts', 'apply'])
  assert.equal(def[0].argv.join(' '), 'code/cli.py core6000 gen --words 徹夜')
  assert.equal(def[2].argv.includes('--commit'), true)

  const dry = buildAddExampleCalls(['--words', '徹夜'], false)
  assert.equal(dry[2].argv.includes('--commit'), false)

  const commit = buildAddExampleCalls(['--note-ids', '123'], true)
  assert.equal(commit[2].argv.includes('--commit'), true)
  assert.equal(commit[0].argv.includes('--commit'), false)
  assert.equal(commit[1].argv.includes('--commit'), false)
})

test('today-new commits by default and only dry-runs when explicitly told not to', () => {
  // 默认真写（用户 2026-11-10 定的规矩）：省略 / true 都带 --commit，只有显式 false 才演练。
  const def = buildTodayNewArgs({ input: 'a.srt', n: 12, season: true })
  assert.deepEqual(def.argv, ['code/cli.py', 'today-new', 'a.srt', '--json', '--n', '12', '--season', '--commit'])
  assert.equal(def.commit, true)

  const dry = buildTodayNewArgs({ input: 'a.srt', commit: false })
  assert.equal(dry.argv.includes('--commit'), false)
  assert.equal(dry.argv.includes('--json'), true)
  assert.equal(dry.commit, false)
  const fast = buildTodayNewArgs({ input: 'a.srt', noSenseCheck: true, noSenseRepair: true })
  assert.equal(fast.argv.includes('--no-sense-check'), true)
  assert.equal(fast.argv.includes('--no-sense-repair'), true)
  assert.deepEqual(buildTodayNewArgs({}), { error: '需要 input（字幕文件或作品目录）' })
})

test('season-new is read-only by default and only writes the season tag on request', () => {
  const dry = buildSeasonNewArgs({ input: 'subtitles/Yuru Camp' })
  assert.deepEqual(dry.argv, ['code/cli.py', 'season-new', 'subtitles/Yuru Camp', '--json'])
  assert.equal(dry.commit, false)

  const full = buildSeasonNewArgs({
    input: ' subtitles/X ',
    jitenMax: 12000, workJitenMax: 24000, workMinCount: 3,
    minWords: 550, maxWords: 800, includeNames: true,
    tag: '本季生词::X', commit: true,
  })
  assert.deepEqual(full.argv, [
    'code/cli.py', 'season-new', 'subtitles/X', '--json',
    '--jiten-max', '12000', '--work-jiten-max', '24000', '--work-min-count', '3',
    '--min-words', '550', '--max-words', '800', '--include-names',
    '--tag', '本季生词::X', '--commit',
  ])
  assert.equal(full.commit, true)

  assert.deepEqual(buildSeasonNewArgs({}), { error: '需要 input（一季的字幕目录）' })
  // 非整数 / 负数不落进 argv（0 是合法值）。
  const bad = buildSeasonNewArgs({ input: 'x', jitenMax: -1, maxWords: 1.5 })
  assert.equal(bad.argv.includes('--jiten-max'), false)
  assert.equal(bad.argv.includes('--max-words'), false)
})

test('local model choice injects --model / --profile and defaults stay clean', () => {
  // 默认：不注入任何模型旗标（跟随 local-llm.json + pin_active）。
  const plain = buildTodayNewArgs({ input: 'a.srt' })
  assert.equal(plain.argv.includes('--model'), false)
  assert.equal(plain.argv.includes('--profile'), false)

  // profile：换档位走 --profile（推荐口径）。
  const prof = buildTodayNewArgs({ input: 'a.srt', llmProfile: 'strata' })
  assert.equal(prof.argv.includes('--profile'), true)
  const pIdx = prof.argv.indexOf('--profile')
  assert.equal(prof.argv[pIdx + 1], 'strata')
  assert.equal(prof.argv.includes('--model'), false)

  // model：钉住模型 id。
  const model = buildTodayNewArgs({ input: 'a.srt', llmModel: 'qwen3.8-flash-next-iq3_s_abl' })
  const mIdx = model.argv.indexOf('--model')
  assert.ok(mIdx > 0)
  assert.equal(model.argv[mIdx + 1], 'qwen3.8-flash-next-iq3_s_abl')

  // 'default' 别名与空白值都视为不指定。
  const alias = buildTodayNewArgs({ input: 'a.srt', llmProfile: ' default ', llmModel: '  ' })
  assert.equal(alias.argv.includes('--profile'), false)
  assert.equal(alias.argv.includes('--model'), false)

  // core6000：gen 带旗标，tts/apply 不跑模型所以不带。
  const chain = buildAddExampleCalls(['--words', '徹夜'], true, { llmProfile: 'ninfer', llmModel: 'x' })
  assert.equal(chain[0].argv.includes('--profile'), true)
  assert.equal(chain[0].argv.includes('--model'), true)
  assert.equal(chain[1].argv.includes('--model'), false)
  assert.equal(chain[2].argv.includes('--model'), false)

  // mergeLlm：单次覆盖 Config 默认；空值不覆盖。
  assert.deepEqual(mergeLlm({ llmProfile: 'strata' }, { llmModel: 'a' }), { model: 'a', profile: 'strata' })
  assert.deepEqual(mergeLlm({ llmProfile: 'strata' }, {}), { model: '', profile: 'strata' })
})

test('jisho pick/list flags go to gen only, never to tts or apply', () => {
  const has = (argv, flag) => argv.includes(flag)
  const valAfter = (argv, flag) => {
    const i = argv.indexOf(flag)
    return i === -1 ? null : argv[i + 1]
  }

  // opts {jishoPick:2}：只有 gen 的 argv 含 --jisho-pick 2，tts/apply 不含。
  const picked = buildAddExampleCalls(['--words', '徹夜'], true, {}, { jishoPick: 2 })
  assert.equal(has(picked[0].argv, '--jisho-pick'), true)
  assert.equal(valAfter(picked[0].argv, '--jisho-pick'), '2')
  assert.equal(has(picked[1].argv, '--jisho-pick'), false)
  assert.equal(has(picked[2].argv, '--jisho-pick'), false)
  assert.equal(has(picked[1].argv, '--list-jisho'), false)
  assert.equal(has(picked[2].argv, '--list-jisho'), false)

  // opts {listJisho:true}：只有 gen 的 argv 含 --list-jisho。
  const listed = buildAddExampleCalls(['--words', '徹夜'], true, {}, { listJisho: true })
  assert.equal(has(listed[0].argv, '--list-jisho'), true)
  assert.equal(has(listed[1].argv, '--list-jisho'), false)
  assert.equal(has(listed[2].argv, '--list-jisho'), false)
  assert.equal(has(listed[1].argv, '--jisho-pick'), false)
  assert.equal(has(listed[2].argv, '--jisho-pick'), false)

  // 都不传（opts 省略 / 空）：三条 argv 与现状完全一致。
  const plain = buildAddExampleCalls(['--words', '徹夜'])
  for (const call of plain) {
    assert.equal(has(call.argv, '--jisho-pick'), false)
    assert.equal(has(call.argv, '--list-jisho'), false)
    assert.equal(has(call.argv, '--jisho-max-len'), false)
  }
  assert.equal(plain[0].argv.join(' '), 'code/cli.py core6000 gen --words 徹夜')
  assert.equal(plain[1].argv.join(' '), 'code/cli.py core6000 tts --words 徹夜')
  assert.equal(plain[2].argv.join(' '), 'code/cli.py core6000 apply --words 徹夜 --commit')

  // opts {jishoMaxLen:20}：只有 gen 的 argv 含 --jisho-max-len 20，tts/apply 不含。
  const maxed = buildAddExampleCalls(['--words', '徹夜'], true, {}, { jishoMaxLen: 20 })
  assert.equal(has(maxed[0].argv, '--jisho-max-len'), true)
  assert.equal(valAfter(maxed[0].argv, '--jisho-max-len'), '20')
  assert.equal(has(maxed[1].argv, '--jisho-max-len'), false)
  assert.equal(has(maxed[2].argv, '--jisho-max-len'), false)
  assert.equal(has(maxed[1].argv, '--jisho-pick'), false)
  assert.equal(has(maxed[2].argv, '--jisho-pick'), false)

  // 非正整数的 jishoMaxLen（0 / 负数 / 小数 / 字符串）一律不注入。
  for (const bad of [0, -1, 1.5, '20']) {
    const c = buildAddExampleCalls(['--words', '徹夜'], true, {}, { jishoMaxLen: bad })
    assert.equal(has(c[0].argv, '--jisho-max-len'), false, `jishoMaxLen=${JSON.stringify(bad)} 不该注入`)
  }
})

test('normalizeLlmModels keeps display fields and drops junk', () => {
  const value = normalizeLlmModels({
    endpoint: { base_url: 'http://127.0.0.1:8080/v1', active_model: 'm-active' },
    models: [{ id: 'm-a', context_window: 131072 }, { id: '' }, null],
    profiles: [{ name: '', model: 'top', base_url: 'u', context_window: 0 }, { name: 'strata', model: 's' }],
    error: null,
  })
  assert.equal(value.ok, true)
  assert.equal(value.baseUrl, 'http://127.0.0.1:8080/v1')
  assert.equal(value.activeModel, 'm-active')
  assert.deepEqual(value.models, [{ id: 'm-a', contextWindow: 131072 }])
  assert.deepEqual(value.profiles[0], { name: '', model: 'top', baseUrl: 'u', contextWindow: null })
  assert.equal(value.endpointError, null)
  assert.equal(normalizeLlmModels(null).ok, false)
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

test('normalizeNoteIds handles commas, spaces, full-width commas, dupes and junk', () => {
  // 逗号 / 空格 / 中文逗号混合分隔，去重且保持出现顺序。
  assert.deepEqual(normalizeNoteIds('123,456'), [123, 456])
  assert.deepEqual(normalizeNoteIds('123 456  789'), [123, 456, 789])
  assert.deepEqual(normalizeNoteIds('123，456，123'), [123, 456])
  assert.deepEqual(normalizeNoteIds(' 123 , 456 '), [123, 456])
  // 非法值（非数字 / 负数 / 0）直接丢弃；全非法或空 → 空数组。
  assert.deepEqual(normalizeNoteIds('123,abc,-5,0,456'), [123, 456])
  assert.deepEqual(normalizeNoteIds('abc,, '), [])
  assert.deepEqual(normalizeNoteIds(''), [])
  assert.deepEqual(normalizeNoteIds(undefined), [])
  // 数组入参（工具传 noteIds 数组）也能吃。
  assert.deepEqual(normalizeNoteIds([123, '456', 123]), [123, 456])
})

test('buildCardFixArgv: html → cards.py, ainote → note_regen.py (①② 同一套讲解)', () => {
  // commit=true：带 --overwrite 与 --commit（默认真写口径）。
  const write = buildCardFixArgv([123, 456], 'html', true, 'temp/cardfix_html_1.json')
  assert.deepEqual(write, [
    'code/execution/cards.py', 'gen', '--note-id', '123,456',
    '--only', 'html', '--out', 'temp/cardfix_html_1.json',
    '--overwrite', '--commit',
  ])
  // AINote 不再走 cards.py 的 LOCAL_INSTRUCTION，而是「增加例句」同一套
  // core6000 提示词 + ①② 渲染（note_regen.py）。commit=false（演练）：只去掉
  // --commit；--overwrite 必须保留，否则已有内容的卡会被直接跳过、演练没结果。
  const dry = buildCardFixArgv([123], 'ainote', false, 'temp/cardfix_ainote_2.json')
  assert.equal(dry.includes('--commit'), false)
  assert.equal(dry.includes('--overwrite'), true)
  assert.deepEqual(dry, [
    'code/execution/note_regen.py', 'gen', '--note-id', '123',
    '--out', 'temp/cardfix_ainote_2.json',
    '--overwrite',
  ])
  // 真写：同一个入口 + --commit，不再带 cards.py 的 --only。
  const ainoteWrite = buildCardFixArgv([123], 'ainote', true, 'temp/cardfix_ainote_3.json')
  assert.equal(ainoteWrite.includes('code/execution/note_regen.py'), true)
  assert.equal(ainoteWrite.includes('--only'), false)
  assert.equal(ainoteWrite.includes('--commit'), true)
})

test('cardLookupCards keeps every writable card of the word, not just the example deck', () => {
  // 2026-11-13 的真实场景：張る 同时挂在例句卡（Basic）和词汇卡（Japanese Vocabulary）上。
  // 旧实现把查询限定在例句 deck，词汇卡被藏起来 → 候选只剩一张 → 面板按
  // 「只有一张卡」直接真写，改到了用户没在看的那张卡。
  const rows = [
    {
      noteId: 1621392101953,
      modelName: 'Japanese Vocabulary',
      tags: ['jp-core::4k'],
      fields: {
        Word: '張る',
        Sentence: '疲れて肩が張っています。',
        'Sentence HTML': '<ruby>肩<rt>かた</rt></ruby>',
        AINote: '<p>讲解</p>',
        Meaning: '拉紧',
      },
      cards: [{ cardId: 1621392102018, deckName: '0-日本语学习::0-词汇::1-高频日语单词 6000' }],
    },
    {
      noteId: 1792114947226,
      modelName: 'Basic',
      tags: ['动画::来自新世界'],
      fields: {
        Word: '張る',
        Sentence: 'ここから茅輪の郷まで 電線を引っ張るのは 無理な話だよ',
        'Sentence HTML': '',
        AINote: '',
      },
      cards: [
        { cardId: 1792114947226, deckName: '0-日本语学习::2-例句' },
        { cardId: 1792114947227, deckName: '0-日本语学习::2-例句::默认' },
      ],
    },
  ]
  const cards = cardLookupCards(rows, '張る')
  // 例句 deck 优先，其余按牌组名；两张卡都在，面板才有的选。
  assert.deepEqual(cards.map((c) => c.noteId), [1792114947226, 1621392101953])
  assert.equal(cards[0].isExample, true)
  assert.equal(cards[1].isExample, false)
  assert.equal(cards[1].deckName, '0-日本语学习::0-词汇::1-高频日语单词 6000')
  assert.equal(cards[1].modelName, 'Japanese Vocabulary')
  assert.equal(cards[1].hasAinote, true)
  // 同一张卡在多个子牌组里：牌组名去重后顿号连接，不能漏掉。
  assert.equal(cards[0].deckName, '0-日本语学习::2-例句、0-日本语学习::2-例句::默认')
  assert.equal(cards[0].hasAinote, false)
  assert.equal(cards[0].hasHtml, false)
  // 原文（未截断）交给调用方 clip。
  assert.equal(cards[1].ainote, '<p>讲解</p>')
})

test('cardLookupCards includes mined-vocabulary cards (素材生词) for the same word', () => {
  // 用户 2026-11-13 追加：除例句卡外，三个词汇卡组都要能改——尤其
  // `0-素材生词`（mine.py 建的卡，同样是 Japanese Vocabulary 笔记类型）。
  const rows = [
    {
      noteId: 1790891591425,
      modelName: 'Japanese Vocabulary',
      fields: {
        Word: 'ゴンドラ',
        Sentence: 'ゴンドラはゆっくりと上がっていく。',
        'Sentence HTML': '<ruby>…</ruby>',
        AINote: '<p>讲解</p>',
      },
      cards: [{ cardId: 1790891591500, deckName: '0-日本语学习::0-词汇::0-素材生词' }],
    },
    {
      noteId: 1792114947226,
      modelName: 'Basic',
      fields: {
        Word: 'ゴンドラ',
        Sentence: 'ここから茅輪の郷まで 電線を引っ張るのは 無理な話だよ',
        'Sentence HTML': '',
        AINote: '',
      },
      cards: [{ cardId: 1792114947226, deckName: '0-日本语学习::2-例句' }],
    },
  ]
  const cards = cardLookupCards(rows, 'ゴンドラ')
  assert.deepEqual(cards.map((c) => c.noteId), [1792114947226, 1790891591425])
  const mined = cards[1]
  assert.equal(mined.deckName, '0-日本语学习::0-词汇::0-素材生词')
  assert.equal(mined.modelName, 'Japanese Vocabulary')
  assert.equal(mined.isExample, false)
  assert.equal(mined.hasAinote, true)
  assert.equal(mined.hasHtml, true)
})

test('cardLookupCards drops cards that cannot be regenerated or are not the exact word', () => {
  const template = {
    modelName: 'Basic',
    cards: [{ deckName: '0-日本语学习::2-例句' }],
    fields: { Word: '張る', Sentence: '句子', 'Sentence HTML': '', AINote: '' },
  }
  const rows = [
    { ...template, noteId: 1 },
    // 字段搜索会命中「包含该词」的卡：必须按 Word 精确相等过滤。
    { ...template, noteId: 2, fields: { ...template.fields, Word: '張る予定' } },
    // 没有 Sentence 就没有骨架，cards.py 没法重新生成。
    { ...template, noteId: 3, fields: { ...template.fields, Sentence: '   ' } },
    // 缺 AINote 字段的笔记类型不能写入（不能凭空调出新字段）。
    { ...template, noteId: 4, fields: { Word: '張る', Sentence: '句子', 'Sentence HTML': '' } },
    // 没有牌组信息（--cards 失败 / 卡片在牌组外）也保留，只是没有 deckName。
    { ...template, noteId: 5, cards: [] },
  ]
  assert.deepEqual(cardLookupCards(rows, '張る').map((c) => c.noteId), [1, 5])
  assert.equal(cardLookupCards(rows, '張る')[1].deckName, '')
  // noteId 回读路径（word 为空）：不过滤词形，但三个字段仍要齐备。
  assert.deepEqual(cardLookupCards(rows, '').map((c) => c.noteId), [1, 2, 5])
  assert.deepEqual(cardLookupCards(null, '張る'), [])
  assert.deepEqual(cardLookupCards([null, 'junk'], '張る'), [])
})

test('parseWordAudioCandidates reads mine_audio.py plan table rows', () => {
  // Byte-for-byte output of mine_audio.py cmd_plan's `%-10s %-8s %-26s %-26s %s`
  // rows (Python pads by code point, JS padEnd by UTF-16 unit — so hard-code).
  const sample = [
    '范围："ゴンドラ" deck:"0-日本语学习::0-词汇::0-素材生词"',
    '新牌组 3 张   媒体库 80017 个文件',
    '',
    '词          读音       Word Audio                 Sentence Audio             这次怎么办',
    '-'.repeat(100),
    'ゴンドラ       ごんどら     （空）                       [sound:asbp_a_01.sr_2.mp3] 不动',
    '漕ぐ         こぐ       （空）                       [sound:asbp_a_01.sr_2.mp3] 不动',
    'ゴンドラ       ごんどら     [sound:mine-ゴンドラ-f4.mp3]   （空）                        生成 词TTS+句',
    '',
    'Sentence Audio：保留已有 2 张 / 需生成 1 张（原声 0、TTS 兜底 1）',
    'Word Audio   ：保留已有 2 张 / 需生成 1 张（TTS ja-JP-NanamiNeural）',
  ].join('\n')
  const rows = parseWordAudioCandidates(sample, 'ゴンドラ')
  // Every table row is kept (including the 漕ぐ row) so callers can align
  // rows 1:1 with find's noteIds before filtering.
  assert.equal(rows.length, 3)
  assert.deepEqual(
    rows.map((r) => [r.word, r.reading, r.wordAudioEmpty, r.sentenceAudioEmpty]),
    [
      ['ゴンドラ', 'ごんどら', true, false],
      ['漕ぐ', 'こぐ', true, false],
      ['ゴンドラ', 'ごんどら', false, true],
    ],
  )
  assert.equal(rows[2].wordAudio, 'mine-ゴンドラ-f4.mp3')
  assert.equal(rows[2].action, '生成 词TTS+句')
  // Rows for unrelated words are still parsed (alignment with find's noteIds);
  // header / separator / summary lines never leak in as candidates.
  assert.equal(parseWordAudioCandidates(sample, 'ケンカ').length, 3)
})
