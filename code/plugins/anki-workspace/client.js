/**
 * Client half of @local/anki-workspace.
 *
 * ModuleLoader format. Registers one sidebar panel icon and the matching main
 * panel. Data and actions go through the Host half's package route
 * (`/anki-workspace/api`); the panel never talks to Anki or the filesystem
 * directly.
 */
window.__ModuleLoader__.load({
  id: '@local/anki-workspace',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const EN = {
      'panel.title': 'Anki Workspace',
      'panel.subtitle': 'Seven workspace capabilities, live status and commit-by-default write actions.',
      'panel.loading': 'Loading status…',
      'panel.refresh': 'Refresh',
      'panel.lastUpdated': 'Updated',
      'panel.error': 'Request failed',
      'status.anki': 'AnkiConnect',
      'status.online': 'Online',
      'status.offline': 'Offline',
      'status.unknown': 'Unknown',
      'status.check': 'Check now',
      'status.doctor': 'doctor',
      'status.green': 'All green',
      'status.hint': 'Hints',
      'status.blocked': 'Blocked',
      'status.error': 'Error',
      'status.passed': 'Passed',
      'status.hints': 'Hints',
      'status.blocking': 'Blocking',
      'status.runDoctor': 'Run doctor',
      'status.details': 'Details',
      'status.close': 'Close',
      'status.checked': 'Checked',
      'status.decks': 'decks',
      'status.noteTypes': 'note types',
      'status.media': 'media',
      'status.latency': 'latency',
      'tabs.aria': 'Workspace panels',
      'tabs.addExample': 'Add example',
      'tabs.todayNew': "Today's new words",
      'tabs.cover': 'Vocabulary coverage',
      'tabs.report': 'Monthly report',
      'card.addExample.title': 'Add example sentence',
      'card.addExample.desc': 'gen → tts → apply for words you named (searched in core6000 + mined-vocab decks). New sentences come from jisho, not the model. Writes by default; uncheck to dry-run.',
      'card.addExample.words': 'Words (comma/space separated)',
      'card.addExample.noteIds': 'Note IDs (optional)',
      'card.addExample.limit': 'Limit',
      'card.addExample.run': 'Run chain',
      'card.addExample.commit': 'Write to Anki (--commit, on by default)',
      'card.addExample.listJisho': 'List Jisho candidates',
      'card.addExample.candidates': 'Jisho candidate sentences',
      'card.addExample.pickHint': 'Pick one (or none = auto-pick), then run the chain to overwrite the card.',
      'card.addExample.rubyWarn': 'ruby check failed',
      'card.addExample.none': 'No Jisho candidates listed (the word may already have a second sentence, or Jisho has no usable example).',
      'llm.label': 'Local model',
      'llm.default': 'Default (config / endpoint pin)',
      'llm.groupProfiles': 'Profiles (pin off: use this profile\'s model)',
      'llm.groupModels': 'Endpoint models',
      'llm.active': 'serving now',
      'llm.endpoint': 'Endpoint',
      'llm.loadFailed': 'Could not read the model list',
      'card.todayNew.title': "Today's new words",
      'card.todayNew.desc': 'Pick N words from one subtitle / work directory. Writes tags by default; uncheck to dry run.',
      'card.todayNew.input': 'Subtitle file or work directory',
      'card.todayNew.n': 'Count',
      'card.todayNew.season': 'Whole season',
      'card.todayNew.noLlmRank': 'Skip LLM ranking',
      'card.todayNew.fast': 'Skip sense check (fast)',
      'card.todayNew.run': 'Pick words',
      'card.todayNew.commit': 'Write tags (--commit)',
      'card.seasonNew.title': 'Season new words',
      'card.seasonNew.desc': 'Pick a whole season directory and extract 550–800 unlearned words: first Jiten ≤ 12000 common words, then 12001–24000 work words appearing ≥3 times. A list is always produced; tick "write season tag" to tag them 本季生词::<dir>.',
      'card.seasonNew.jitenMax': 'Common Jiten ≤',
      'card.seasonNew.workJitenMin': 'Work Jiten ≥',
      'card.seasonNew.workJitenMax': 'Work Jiten ≤',
      'card.seasonNew.workMinCount': 'Work min count',
      'card.seasonNew.minWords': 'Min words',
      'card.seasonNew.maxWords': 'Max words',
      'card.seasonNew.tag': 'Tag (empty = 本季生词::<dir>)',
      'card.seasonNew.includeNames': 'Keep proper names',
      'card.seasonNew.writeTag': 'Write season tag',
      'card.seasonNew.run': 'Extract season words',
      'card.seasonNew.commonLayer': 'Common',
      'card.seasonNew.workLayer': 'Work',
      'card.seasonNew.relaxed': 'Relaxed',
      'card.cover.title': 'Vocabulary coverage',
      'card.cover.desc': 'Coverage, out-of-deck new words and understandable share for a Japanese text or subtitle.',
      'card.cover.text': 'Japanese text',
      'card.cover.paths': 'Files',
      'card.cover.top': 'Top',
      'card.cover.screen': 'Screen new words',
      'card.cover.run': 'Analyze',
      'card.report.title': 'Monthly study report',
      'card.report.desc': 'Run the ankiR report once per month. Existing report is skipped unless forced.',
      'card.report.force': 'Rebuild even if this month exists',
      'card.report.run': 'Generate report',
      'card.report.exists': 'This month already has a report',
      'card.report.missing': 'No report for this month yet',
      'report.title': 'ankiR monthly report',
      'report.empty': 'No report for this month yet.',
      'report.emptyHint': 'Generate it below; this panel renders the JSON file directly.',
      'report.failed': 'Could not read the report JSON.',
      'report.retention': 'Retention',
      'report.maturity': 'Maturity',
      'report.mature': 'Mature',
      'report.young': 'Young',
      'report.totalCards': 'Cards',
      'report.totalNotes': 'Notes',
      'report.totalDecks': 'Decks',
      'report.totalReviews': 'Reviews',
      'report.daysStudied': 'Days studied',
      'report.avgReviews': 'Avg / day',
      'report.streak': 'Streak',
      'report.longest': 'Longest',
      'report.hours': 'Hours',
      'report.hourUnit': 'h',
      'report.composition': 'Card composition',
      'report.newCards': 'New',
      'report.learningCards': 'Learning',
      'report.reviewCards': 'Review',
      'report.suspended': 'Suspended',
      'report.buried': 'Buried',
      'report.range': 'Review span',
      'report.firstReview': 'First',
      'report.lastReview': 'Last',
      'report.dataThrough': 'Data through',
      'report.month': 'Month',
      'report.path': 'File',
      'report.size': 'Size',
      'report.generated': 'File time',
      'report.raw': 'Raw JSON',
      'picker.browse': 'Browse…',
      'picker.clear': 'Clear',
      'picker.cancel': 'Cancel',
      'picker.choose': 'Choose',
      'picker.chooseDir': 'Use this folder',
      'picker.up': 'Up',
      'picker.filter': 'Filter names',
      'picker.loading': 'Reading folder…',
      'picker.empty': 'This folder is empty',
      'picker.failed': 'Could not read folder',
      'picker.otherFiles': 'Show all files',
      'picker.root': 'Workspace root',
      'picker.remove': 'Remove',
      'picker.chosen': 'Selected',
      'picker.noSelection': 'Nothing selected',
      'picker.title.file': 'Choose a file',
      'picker.title.files': 'Choose files',
      'picker.title.dir': 'Choose a folder',
      'picker.title.any': 'Choose a subtitle file or folder',
      'picker.truncated': 'Too many entries — showing the first',
      'common.working': 'Working…',
      'common.noResult': 'No result yet',
      'common.dryRun': 'Write actions commit by default (--commit); untick "write" to dry run.',
      'result.dryRun': 'Dry run — nothing written',
      'result.committed': 'Written to Anki',
      'result.failed': 'Failed',
      'result.generated': 'Generated',
      'result.window': 'Window',
      'result.episodes': 'episodes',
      'result.episodesUnit': 'ep',
      'result.candidates': 'Candidates',
      'result.pickedWords': 'Words picked',
      'result.noteCount': 'Notes',
      'result.notesUnit': 'notes',
      'result.rankedBy': 'Ranking',
      'result.rank.llm': 'LLM ranking',
      'result.rank.formula': 'Formula fallback',
      'result.rank.cached': 'cache hit',
      'result.times': '×',
      'result.showAll': 'Show all',
      'result.showLess': 'Show fewer',
      'result.pending.title': 'Particles with no card yet',
      'result.plan.title': 'Tag plan',
      'result.plan.old': 'Old',
      'result.plan.keep': 'Keep',
      'result.plan.remove': 'Remove',
      'result.plan.add': 'Add',
      'result.sense.title': 'Sense check repaired',
      'result.sense.failed': 'Sense repair failed',
      'result.sense.dropped': 'Dropped by sense check',
      'result.dropped.title': 'Dropped in live re-check',
      'result.skipped.title': 'Skipped',
      'result.skip.noRank': 'no JAR rank',
      'result.skip.noNotes': 'no unlearned note',
      'result.skip.reading': 'reading mismatch',
      'result.skip.phrases': 'phrase filter',
      'result.skip.unranked': 'queued for card creation',
      'result.artifacts': 'Artifacts',
      'result.empty': 'No words returned',
      'result.repaired': 'repaired',
      'cover.understood': 'Understood (lenient)',
      'cover.strict': 'Understood (strict)',
      'cover.deck': 'In your decks',
      'cover.known': 'Learned',
      'cover.mature': 'Mature',
      'cover.coverage': 'Coverage',
      'cover.allTokens': 'all tokens',
      'cover.vocabTokens': 'vocab tokens',
      'cover.learnable': 'learnable',
      'cover.chars': 'Chars',
      'cover.tokens': 'Tokens',
      'cover.types': 'Types',
      'cover.sentences': 'Sentences',
      'cover.sentenceFull': 'Fully understood',
      'cover.sentenceLenient': '≤1 new word',
      'cover.listening': 'Listening (no subs)',
      'cover.table.title': 'Breakdown by denominator',
      'cover.table.metric': 'Metric',
      'cover.row.core': 'core6000 hit',
      'cover.row.corejlpt': 'core6000 + JLPT',
      'cover.row.deck': 'All my decks',
      'cover.row.known': 'Learned',
      'cover.row.mature': 'Mature',
      'cover.row.understood': '★ Understandable',
      'cover.row.strict': 'Strict',
      'cover.row.oov': 'Out-of-deck',
      'cover.row.proper': 'Proper nouns',
      'cover.oov.title': 'New words outside every deck',
      'cover.oov.empty': 'No out-of-deck new words.',
      'cover.oov.more': 'more',
      'cover.untackled.title': 'In decks but never studied',
      'cover.untackled.empty': 'No untackled words.',
      'cover.reach.title': 'Deck reach',
      'cover.reach.seen': 'seen',
      'cover.screen.title': 'Content-word candidates',
      'cover.screen.empty': 'Screen returned no content words.',
      'cover.screen.ranked': 'LLM ranking',
      'cover.screen.occurrences': 'by occurrences',
      'cover.textInput': 'Text input',
      'tabs.cardFix': 'Card Fix',
      'card.fix.title': 'Regenerate by word',
      'card.fix.desc': 'Type one word, first tick what to regenerate (Word Audio / Sentence HTML / AINote — all three start unticked), then click Regenerate. Field cards are looked up by the Word field across the whole collection — example cards and all three vocabulary decks (6000 / JLPT / mined) alike: a single writable card runs immediately; when several cards share the word they are all listed below (each with its deck and note type), none ticked — pick the one you mean, then click Regenerate.',
      'card.fix.wordInput': 'Word (dictionary form)',
      'card.fix.run': 'Regenerate',
      'card.fix.lookup': 'Find cards',
      'card.fix.audio': 'Word Audio',
      'card.fix.force': 'Overwrite existing audio',
      'card.fix.audioCandidates': 'Word Audio candidates',
      'card.fix.fieldCandidates': 'Candidate cards (incl. mined vocabulary)',
      'card.fix.multiHint': 'This word matches several writable cards (each row shows its deck and note type): tick the one to update, then click Regenerate. Nothing is pre-ticked so the wrong card cannot be overwritten.',
      'card.fix.pickFirst': 'Tick the card to regenerate first (nothing is pre-ticked, so another card cannot be overwritten).',
      'card.fix.noAudio': 'No mined-vocabulary card found for this word.',
      'card.fix.noFields': 'No card whose Word matches this word and that carries the Sentence / AINote / Sentence HTML fields (example cards, the 6000 / JLPT / mined-vocabulary decks were all searched).',
      'card.fix.needTarget': 'Tick what to regenerate first (Word Audio / Sentence HTML / AINote — all start unticked).',
      'card.fix.wordTip': 'One input drives two lookups: field cards by the Word field across the whole collection (example deck plus the 6000 / JLPT / mined-vocabulary decks), Word Audio cards by the word form.',
      'card.fix.audioTip': 'Regenerate Word Audio with edge-TTS ja-JP-NanamiNeural reading the Transliteration kana. Existing audio is kept unless “Overwrite existing audio” is ticked.',
      'card.fix.htmlTip': 'Regenerate Sentence HTML (ruby) from the card’s Sentence; only this field is written.',
      'card.fix.ainoteTip': 'Regenerate the AINote explanation from the card’s Sentence; only this field is written.',
      'card.fix.commitTip': 'On by default: actually write Anki. Untick to dry-run.',
      'card.fix.forceTip': 'Also regenerate Word Audio when the field already has audio.',
      'card.fix.runTip': 'Look up cards first; a single writable card in the collection regenerates immediately. When several match, tick the one you mean and click again.',
      'card.fix.pickTip': 'Include this card in the regeneration.',
      'card.fix.cards': 'Candidate cards',
      'card.fix.none': 'No card whose Word matches this word and that carries Sentence / AINote / Sentence HTML.',
      'card.fix.sentence': 'Sentence',
      'card.fix.word': 'Word',
      'card.fix.has': 'has content',
      'card.fix.empty': 'empty',
      'card.fix.commit': 'Write to Anki (--commit, on by default)',
      'card.fix.selectHint': 'Pick a card, then click regenerate.',
      'card.fix.htmlBtn': 'Regenerate Sentence HTML',
      'card.fix.ainoteBtn': 'Regenerate AINote',
      'card.fix.output': 'Raw output',
      'card.fix.generated': 'Generated result',
      'card.fix.noValue': 'No content returned.',
      'card.fix.failed': 'failed',
      'card.wordAudio.title': 'Word Audio (TTS)',
      'card.wordAudio.desc': 'Generate / fix the Word Audio for one word. The script reads the Transliteration (kana) with edge-TTS ja-JP-NanamiNeural. If several cards share the word, pick which one to update. Sentence Audio is kept when it already has the actor’s original voice.',
      'card.wordAudio.word': 'Word (dictionary form)',
      'card.wordAudio.plan': 'Find cards',
      'card.wordAudio.apply': 'Generate / update',
      'card.wordAudio.commit': 'Write to Anki (--commit, on by default)',
      'card.wordAudio.force': 'Overwrite existing audio',
      'wordAudio.candidates': 'Candidate cards',
      'wordAudio.none': 'No candidate cards found, or every card already has Word Audio.',
      'wordAudio.empty': 'empty',
      'wordAudio.has': 'has audio',
      'wordAudio.wordAudio': 'Word Audio',
      'wordAudio.sentenceAudio': 'Sentence Audio',
      'wordAudio.reading': 'reading',
      'wordAudio.action': 'action',
      'wordAudio.selectHint': 'Pick a card below, then click “Generate / update”.',
      'wordAudio.selected': 'selected',
    }

    const ZH = {
      'panel.title': 'Anki 工作区',
      'panel.subtitle': '七项常用能力：实时状态 + 默认真写的写库动作。',
      'panel.loading': '正在加载状态…',
      'panel.refresh': '刷新',
      'panel.lastUpdated': '更新于',
      'panel.error': '请求失败',
      'status.anki': 'AnkiConnect',
      'status.online': '在线',
      'status.offline': '离线',
      'status.unknown': '未知',
      'status.check': '立即检测',
      'status.doctor': 'doctor',
      'status.green': '全绿',
      'status.hint': '提示',
      'status.blocked': '阻塞',
      'status.error': '异常',
      'status.passed': '通过',
      'status.hints': '提示',
      'status.blocking': '阻塞',
      'status.runDoctor': '跑 doctor',
      'status.details': '详情',
      'status.close': '关闭',
      'status.checked': '检测于',
      'status.decks': '牌组',
      'status.noteTypes': '笔记类型',
      'status.media': '媒体',
      'status.latency': '耗时',
      'tabs.aria': '工作区面板',
      'tabs.addExample': '增加例句',
      'tabs.todayNew': '今日选词',
      'tabs.cover': '词汇覆盖率',
      'tabs.report': '每月报告',
      'card.addExample.title': '增加例句',
      'card.addExample.desc': '点名的词（core6000 ＋ 素材生词两个卡组自动查找）：gen → tts → apply。新例句取自 jisho 真实语料，不由模型造句。默认真写库，取消勾选才演练。',
      'card.addExample.words': '词形（逗号/空格分隔）',
      'card.addExample.noteIds': 'noteId（可选）',
      'card.addExample.limit': '张数上限',
      'card.addExample.run': '跑三步',
      'card.addExample.commit': '真写库（--commit，默认勾选）',
      'card.addExample.listJisho': '列 Jisho 候选',
      'card.addExample.candidates': 'Jisho 候选例句',
      'card.addExample.pickHint': '选一条（或不选 = 自动挑选），再跑三步覆写卡片资料。',
      'card.addExample.rubyWarn': '振假名不合格',
      'card.addExample.none': '没有列出任何 Jisho 候选（该词可能已有第二句，或 Jisho 无可用例句）。',
      'llm.label': '本地模型',
      'llm.default': '默认（配置 / 跟随端点）',
      'llm.groupProfiles': '档位 profile（选定即用该档 model，不再跟随端点）',
      'llm.groupModels': '端点模型',
      'llm.active': '当前在服务',
      'llm.endpoint': '端点',
      'llm.loadFailed': '读取模型清单失败',
      'card.todayNew.title': '今日选词',
      'card.todayNew.desc': '从一集字幕 / 作品目录挑 N 个词。默认真写标签，取消勾选才演练。',
      'card.todayNew.input': '字幕文件或作品目录',
      'card.todayNew.n': '数量',
      'card.todayNew.season': '扩到整季',
      'card.todayNew.noLlmRank': '跳过 LLM 精排',
      'card.todayNew.fast': '跳过义项核验（离线快跑）',
      'card.todayNew.run': '选词',
      'card.todayNew.commit': '真写标签（--commit）',
      'card.seasonNew.title': '每季生词（选目录）',
      'card.seasonNew.desc': '选一季字幕目录，按「先 Jiten ≤ 12000 通用词、再 12001–24000 且本季出现 ≥3 次的作品词」筛出 550–800 个未学词；始终出清单，勾选「写入季标签」才给这些词打 本季生词::<目录名>。',
      'card.seasonNew.jitenMax': '通用层 Jiten ≤',
      'card.seasonNew.workJitenMin': '作品层 Jiten ≥',
      'card.seasonNew.workJitenMax': '作品层 Jiten ≤',
      'card.seasonNew.workMinCount': '作品层最少出现',
      'card.seasonNew.minWords': '每季下限',
      'card.seasonNew.maxWords': '每季上限',
      'card.seasonNew.tag': '标签（空 = 本季生词::<目录名>）',
      'card.seasonNew.includeNames': '保留专有名词',
      'card.seasonNew.writeTag': '写入季标签',
      'card.seasonNew.run': '提取每季生词',
      'card.seasonNew.commonLayer': '通用层',
      'card.seasonNew.workLayer': '作品层',
      'card.seasonNew.relaxed': '放宽',
      'card.cover.title': '词汇覆盖率',
      'card.cover.desc': '一段日文或一集字幕：卡组覆盖、卡组外新词、待激活词、可懂度。',
      'card.cover.text': '日文文本',
      'card.cover.paths': '文件',
      'card.cover.top': 'Top',
      'card.cover.screen': '筛选新词',
      'card.cover.run': '分析',
      'card.report.title': '每月学习报告',
      'card.report.desc': '每月跑一次 ankiR 报告；本月已有就跳过，可强制重建。',
      'card.report.force': '本月已有也重建',
      'card.report.run': '生成报告',
      'card.report.exists': '本月已有报告',
      'card.report.missing': '本月还没有报告',
      'report.title': 'ankiR 月度报告',
      'report.empty': '本月还没有报告。',
      'report.emptyHint': '在下方生成；这个面板会直接渲染 JSON 文件。',
      'report.failed': '读取报告 JSON 失败。',
      'report.retention': '留存率',
      'report.maturity': '卡片成熟度',
      'report.mature': '成熟卡',
      'report.young': '年轻卡',
      'report.totalCards': '卡片',
      'report.totalNotes': '笔记',
      'report.totalDecks': '牌组',
      'report.totalReviews': '复习',
      'report.daysStudied': '学习天数',
      'report.avgReviews': '日均复习',
      'report.streak': '连续天数',
      'report.longest': '最长',
      'report.hours': '学习时长',
      'report.hourUnit': '小时',
      'report.composition': '卡片构成',
      'report.newCards': '新卡',
      'report.learningCards': '学习中',
      'report.reviewCards': '复习卡',
      'report.suspended': '挂起',
      'report.buried': '埋藏',
      'report.range': '复习跨度',
      'report.firstReview': '首次',
      'report.lastReview': '最近',
      'report.dataThrough': '数据截至',
      'report.month': '月份',
      'report.path': '文件',
      'report.size': '大小',
      'report.generated': '文件时间',
      'report.raw': '原始 JSON',
      'picker.browse': '浏览…',
      'picker.clear': '清除',
      'picker.cancel': '取消',
      'picker.choose': '选择',
      'picker.chooseDir': '选择此目录',
      'picker.up': '上一级',
      'picker.filter': '按名称筛选',
      'picker.loading': '正在读取目录…',
      'picker.empty': '这个目录是空的',
      'picker.failed': '目录读取失败',
      'picker.otherFiles': '显示其它文件',
      'picker.root': '工作区根目录',
      'picker.remove': '移除',
      'picker.chosen': '已选',
      'picker.noSelection': '未选择',
      'picker.title.file': '选择文件',
      'picker.title.files': '选择文件（可多选）',
      'picker.title.dir': '选择目录',
      'picker.title.any': '选择字幕文件或目录',
      'picker.truncated': '目录条目过多，仅显示前',
      'common.working': '运行中…',
      'common.noResult': '还没有结果',
      'common.dryRun': '写库动作默认真写（--commit），取消勾选「真写」才演练。',
      'result.dryRun': '演练 — 未写库',
      'result.committed': '已写入 Anki',
      'result.failed': '失败',
      'result.generated': '生成于',
      'result.window': '窗口',
      'result.episodes': '集',
      'result.episodesUnit': '集',
      'result.candidates': '候选词',
      'result.pickedWords': '入选词',
      'result.noteCount': '笔记',
      'result.notesUnit': '张笔记',
      'result.rankedBy': '排序',
      'result.rank.llm': 'LLM 精排',
      'result.rank.formula': '公式兜底',
      'result.rank.cached': '命中缓存',
      'result.times': '次',
      'result.showAll': '显示全部',
      'result.showLess': '收起',
      'result.pending.title': '高分助词/感动词（库里没卡，待建卡）',
      'result.plan.title': '标签计划',
      'result.plan.old': '旧标签',
      'result.plan.keep': '保留',
      'result.plan.remove': '摘除',
      'result.plan.add': '新增',
      'result.sense.title': '义项已修复（照常入选）',
      'result.sense.failed': '义项修复失败（维持剔除）',
      'result.sense.dropped': '义项核验被剔除',
      'result.dropped.title': '现场复核被剔除',
      'result.skipped.title': '被排除',
      'result.skip.noRank': '无 JAR 排名',
      'result.skip.noNotes': '没有未学笔记',
      'result.skip.reading': '读音对不上',
      'result.skip.phrases': '词性过滤',
      'result.skip.unranked': '待建卡清单',
      'result.artifacts': '产物',
      'result.empty': '没有返回任何词',
      'result.repaired': '已修义项',
      'cover.understood': '我实际能懂（宽口径）',
      'cover.strict': '严格口径能懂',
      'cover.deck': '落在我的卡组',
      'cover.known': '我已学（≥1 次）',
      'cover.mature': '我已成熟（≥21 天）',
      'cover.coverage': '覆盖率',
      'cover.allTokens': '含语法词',
      'cover.vocabTokens': '词汇词',
      'cover.learnable': '需背实词',
      'cover.chars': '字数',
      'cover.tokens': '词元',
      'cover.types': '词种',
      'cover.sentences': '句子',
      'cover.sentenceFull': '整句无生词',
      'cover.sentenceLenient': '≤1 个生词',
      'cover.listening': '无字幕听力折算',
      'cover.table.title': '三套分母对比',
      'cover.table.metric': '指标',
      'cover.row.core': 'core6000 命中',
      'cover.row.corejlpt': 'core6000+考级',
      'cover.row.deck': '我的全部卡组',
      'cover.row.known': '我已学',
      'cover.row.mature': '我已成熟',
      'cover.row.understood': '★我实际能懂',
      'cover.row.strict': '严格口径',
      'cover.row.oov': '卡组外新词',
      'cover.row.proper': '专有名词',
      'cover.oov.title': '卡组外新词',
      'cover.oov.empty': '没有卡组外新词。',
      'cover.oov.more': '个未列出',
      'cover.untackled.title': '卡组里有卡但没刷过',
      'cover.untackled.empty': '没有待激活词。',
      'cover.reach.title': '反向触达',
      'cover.reach.seen': '出现',
      'cover.screen.title': '内容词候选',
      'cover.screen.empty': '筛选后没有内容词。',
      'cover.screen.ranked': 'LLM 精排',
      'cover.screen.occurrences': '按出现次数',
      'cover.textInput': '文本输入',
      'tabs.cardFix': '卡片修正',
      'card.fix.title': '按单词重新生成',
      'card.fix.desc': '输入一个单词，先勾选要重新生成的内容（单词音频 / Sentence HTML / AINote，三项默认都不勾），点「重新生成」。字段卡按 Word 在整库查，例句卡与三个词汇卡组（高频 6000 / 考级 / 素材生词）都能改：只有一张可改的卡时直接生成；同词多张时全部列在下方（每张标出牌组与笔记类型）、默认不勾选，先选卡再点「重新生成」。',
      'card.fix.wordInput': '单词名（词典形）',
      'card.fix.run': '重新生成',
      'card.fix.lookup': '查卡片',
      'card.fix.audio': '音频',
      'card.fix.force': '覆盖已有音频',
      'card.fix.audioCandidates': '单词配音候选',
      'card.fix.fieldCandidates': '候选卡（含素材生词）',
      'card.fix.multiHint': '这个词命中多张可改的卡（下方每张都列了牌组与笔记类型）：勾选要改的那一张，再点「重新生成」。默认一张都不勾，避免写错卡。',
      'card.fix.pickFirst': '先勾选要重新生成的卡（默认不预选，避免覆盖到别的卡）。',
      'card.fix.noAudio': '没有找到这个单词的素材生词卡。',
      'card.fix.noFields': '没有找到 Word 等于这个单词、且带 Sentence / AINote / Sentence HTML 字段的卡（例句卡、高频 6000 / 考级 / 素材生词 都查过）。',
      'card.fix.needTarget': '先勾选要重新生成的内容（单词音频 / Sentence HTML / AINote，默认都不勾）。',
      'card.fix.wordTip': '一个输入框同时查两个地方：字段卡按 Word 字段在整库查（例句 deck + 高频 6000 / 考级 / 素材生词 三个词汇卡组），素材生词卡按词形查。',
      'card.fix.audioTip': '重新生成 Word Audio：edge-TTS ja-JP-NanamiNeural 读 Transliteration 假名。已有音频默认保留，勾选「覆盖已有音频」才重做。',
      'card.fix.htmlTip': '按卡上的 Sentence 重新渲染 Sentence HTML（振假名），只写这个字段。',
      'card.fix.ainoteTip': '按卡上的 Sentence 重新生成 AINote 讲解，只写这个字段。',
      'card.fix.commitTip': '默认勾选＝真写库；取消勾选只演练，不写 Anki。',
      'card.fix.forceTip': 'Word Audio 字段已有音频时也重新生成。',
      'card.fix.runTip': '先查卡片；整库只有一张可改的卡时直接生成，同词多张时先勾选要改的那张再点一次。',
      'card.fix.pickTip': '把这张卡纳入本次重新生成。',
      'card.fix.cards': '候选卡片',
      'card.fix.none': '没找到 Word 等于这个单词、且带 Sentence / AINote / Sentence HTML 的卡',
      'card.fix.sentence': '例句',
      'card.fix.word': '重点词',
      'card.fix.has': '有内容',
      'card.fix.empty': '空',
      'card.fix.commit': '真写库（--commit，默认勾选）',
      'card.fix.selectHint': '选一张卡，再点重新生成',
      'card.fix.htmlBtn': '重新生成 Sentence HTML',
      'card.fix.ainoteBtn': '重新生成 AINote',
      'card.fix.output': '脚本原始输出',
      'card.fix.generated': '生成结果',
      'card.fix.noValue': '没有返回内容',
      'card.fix.failed': '失败',
      'card.wordAudio.title': '单词配音（Word Audio）',
      'card.wordAudio.desc': '给一个词的素材生词卡生成 / 修 Word Audio：edge-TTS ja-JP-NanamiNeural 读 Transliteration（假名读音）。同词多张卡时，选要更新哪一张。Sentence Audio 已有演员原声则保留不动。默认真写库，取消勾选才演练。',
      'card.wordAudio.word': '单词名（词典形）',
      'card.wordAudio.plan': '查候选卡',
      'card.wordAudio.apply': '生成 / 更新',
      'card.wordAudio.commit': '真写库（--commit，默认勾选）',
      'card.wordAudio.force': '覆盖已有音频',
      'wordAudio.candidates': '候选卡片',
      'wordAudio.none': '没找到候选卡，或这些卡的 Word Audio 都已有音频。',
      'wordAudio.empty': '空',
      'wordAudio.has': '已有音频',
      'wordAudio.wordAudio': 'Word Audio',
      'wordAudio.sentenceAudio': 'Sentence Audio',
      'wordAudio.reading': '读音',
      'wordAudio.action': '动作',
      'wordAudio.selectHint': '在下方勾选要更新的卡，再点「生成 / 更新」。',
      'wordAudio.selected': '已选',
    }

    // Extensions offered by the picker for subtitle / plain-text inputs.
    const SUBTITLE_EXTS = ['.srt', '.vtt', '.ass', '.ssa', '.txt', '.md']

    // Panels 3–6 share one slot; only the active one is visible.
    const TABS = [
      { id: 'add-example', label: 'tabs.addExample' },
      { id: 'today-new', label: 'tabs.todayNew' },
      { id: 'vocab-cover', label: 'tabs.cover' },
      { id: 'study-report', label: 'tabs.report' },
      { id: 'card-fix', label: 'tabs.cardFix', wide: true },
    ]

    // The main slot unmounts this panel when another sidebar icon is selected.
    // Keep the last status, tab and tool results at module scope so clicking
    // the Anki icon again shows the same tab output instead of an empty form.
    const PANEL_CACHE = {
      snapshot: null,
      results: {},
      reportSnapshot: null,
      activeTab: 'today-new',
      // 本地模型档位：清单只读一次缓存在这里；选择跨卸载保留，空串=默认。
      llmModels: null,
      llmChoice: '',
    }
    const PANEL_LISTENERS = new Set()

    function publishResults(next) {
      PANEL_CACHE.results = next
      for (const listener of PANEL_LISTENERS) {
        try {
          listener(next)
        } catch {
          // A listener belongs to a panel that is being torn down; ignore it.
        }
      }
    }

    const CSS = `
.anki-page{height:100%;box-sizing:border-box;overflow:auto;padding:26px 30px 40px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font-family:inherit}
.anki-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:20px}
.anki-title{font-size:20px;font-weight:650;letter-spacing:.01em;line-height:1.3}
.anki-sub{margin-top:5px;font-size:12.5px;line-height:1.55;color:var(--dsw-alias-label-secondary);max-width:720px}
.anki-head-actions{display:flex;align-items:center;gap:10px;flex:none;flex-wrap:wrap;justify-content:flex-end}
.anki-updated{margin-top:6px;font-size:12px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
.anki-card{background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:12px;padding:16px 16px 14px;min-width:0}
.anki-card h3{margin:0;font-size:14px;font-weight:650;line-height:1.4}
.anki-card p{margin:5px 0 0;font-size:12.5px;line-height:1.55;color:var(--dsw-alias-label-secondary)}
.anki-card-body{margin-top:12px;display:flex;flex-direction:column;gap:8px}
.anki-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.anki-row.between{justify-content:space-between}
.anki-input,.anki-textarea{width:100%;box-sizing:border-box;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font:inherit;font-size:12.5px;padding:7px 9px;outline:none}
.anki-input:focus,.anki-textarea:focus{border-color:var(--dsw-alias-brand-primary)}
.anki-select{box-sizing:border-box;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font:inherit;font-size:12.5px;padding:7px 9px;outline:none;max-width:420px}
.anki-select:focus{border-color:var(--dsw-alias-brand-primary)}
.anki-textarea{min-height:76px;resize:vertical;line-height:1.5}
.anki-check{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--dsw-alias-label-secondary);cursor:pointer;user-select:none}
.anki-check input{accent-color:var(--dsw-alias-brand-primary)}
.anki-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);font:inherit;font-size:12.5px;font-weight:550;padding:6px 13px;cursor:pointer;white-space:nowrap}
.anki-btn:hover:not(:disabled){border-color:var(--dsw-alias-brand-primary);color:var(--dsw-alias-brand-primary)}
.anki-btn:disabled{opacity:.45;cursor:default}
.anki-badge{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:600;line-height:1.6}
.anki-badge.green{color:var(--dsw-alias-state-success-primary);border-color:var(--dsw-alias-state-success-primary)}
.anki-badge.warn{color:var(--dsw-alias-state-warn-primary);border-color:var(--dsw-alias-state-warn-primary)}
.anki-badge.error{color:var(--dsw-alias-state-error-primary);border-color:var(--dsw-alias-state-error-primary)}
.anki-badge.idle{color:var(--dsw-alias-state-idle-primary);border-color:var(--dsw-alias-border-l2)}
.anki-meta{font-size:12px;line-height:1.6;color:var(--dsw-alias-label-secondary)}
.anki-meta strong{color:var(--dsw-alias-label-primary);font-weight:600}
.anki-out{white-space:pre-wrap;word-break:break-word;max-height:240px;overflow:auto;margin:2px 0 0;padding:9px 10px;border:1px solid var(--dsw-alias-border-l1);border-radius:8px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.anki-error{font-size:12.5px;color:var(--dsw-alias-state-error-primary);white-space:pre-wrap;margin-top:10px}
.anki-foot{margin-top:18px;font-size:12px;color:var(--dsw-alias-label-secondary)}
.anki-result{display:flex;flex-direction:column;gap:10px;min-width:0}
.anki-result-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;min-width:0}
.anki-result-title{font-size:12.5px;font-weight:600;line-height:1.4;color:var(--dsw-alias-label-primary);overflow-wrap:anywhere}
.anki-result-sub{font-size:11.5px;line-height:1.5;color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
.anki-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(70px,1fr));gap:6px}
.anki-kpi{min-width:0;border:1px solid var(--dsw-alias-border-l1);border-radius:8px;background:var(--dsw-alias-bg-base);padding:6px 8px}
.anki-kpi b{display:block;font-size:15px;font-weight:650;line-height:1.2;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.anki-kpi span{display:block;margin-top:1px;font-size:10.5px;line-height:1.3;color:var(--dsw-alias-label-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.anki-metric{display:grid;grid-template-columns:minmax(72px,116px) 1fr 48px;align-items:center;gap:8px;min-width:0}
.anki-metric-label{font-size:11.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.anki-metric-value{font-size:11.5px;text-align:right;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-primary)}
.anki-bar{display:block;height:6px;border-radius:999px;background:var(--dsw-alias-bg-layer-2);overflow:hidden}
.anki-bar i{display:block;height:100%;border-radius:999px;background:var(--dsw-alias-brand-primary)}
.anki-bar.green i{background:var(--dsw-alias-state-success-primary)}
.anki-bar.warn i{background:var(--dsw-alias-state-warn-primary)}
.anki-hero{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.anki-hero strong{font-size:28px;font-weight:650;line-height:1.1;font-variant-numeric:tabular-nums;color:var(--dsw-alias-brand-primary)}
.anki-hero span{font-size:11.5px;color:var(--dsw-alias-label-secondary)}
.anki-words{display:flex;flex-direction:column;gap:6px;max-height:400px;overflow:auto;padding-right:2px}
.anki-word{min-width:0;border:1px solid var(--dsw-alias-border-l1);border-radius:9px;background:var(--dsw-alias-bg-base);padding:7px 9px}
.anki-word-head{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap;min-width:0}
.anki-word-index{flex:none;font-size:10.5px;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-tertiary)}
.anki-word-form{font-size:14px;font-weight:650;line-height:1.3;color:var(--dsw-alias-label-primary)}
.anki-word-reading{font-size:11.5px;color:var(--dsw-alias-label-secondary)}
.anki-word-meta{margin-top:3px;font-size:10.5px;line-height:1.45;color:var(--dsw-alias-label-tertiary);font-variant-numeric:tabular-nums}
.anki-word-score{display:grid;grid-template-columns:1fr 38px;align-items:center;gap:6px;margin-top:5px}
.anki-word-score-val{font-size:10.5px;text-align:right;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-secondary)}
.anki-word-why{margin-top:5px;font-size:11.5px;line-height:1.5;color:var(--dsw-alias-label-secondary)}
.anki-quote{margin-top:5px;padding-left:7px;border-left:2px solid var(--dsw-alias-border-l2);font-size:11px;line-height:1.5;color:var(--dsw-alias-label-tertiary);overflow-wrap:anywhere}
.anki-section{border-top:1px solid var(--dsw-alias-border-l1);padding-top:8px}
.anki-section h5{margin:0 0 6px;font-size:11px;font-weight:650;letter-spacing:.02em;color:var(--dsw-alias-label-secondary)}
.anki-rows{display:flex;flex-direction:column;gap:4px;min-width:0}
.anki-rowline{font-size:11.5px;line-height:1.5;color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
.anki-rowline b{font-weight:650;color:var(--dsw-alias-label-primary)}
.anki-chiplist{display:flex;flex-wrap:wrap;gap:5px;min-width:0}
.anki-tag{display:inline-flex;align-items:center;gap:3px;max-width:100%;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;padding:1px 7px;font-size:11px;line-height:1.6;color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-base)}
.anki-tag b{font-weight:650;color:var(--dsw-alias-label-primary)}
.anki-tag.dim{color:var(--dsw-alias-label-tertiary)}
.anki-cov{display:grid;grid-template-columns:minmax(92px,1fr) repeat(3,50px);gap:3px 6px;align-items:center;font-size:11px;font-variant-numeric:tabular-nums}
.anki-cov .h{font-size:10.5px;text-align:right;color:var(--dsw-alias-label-tertiary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.anki-cov .m{color:var(--dsw-alias-label-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.anki-cov .v{text-align:right;color:var(--dsw-alias-label-primary)}
.anki-cov .v.dim{color:var(--dsw-alias-label-tertiary)}
.anki-toggle{align-self:flex-start;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);font:inherit;font-size:11px;padding:2px 9px;cursor:pointer}
.anki-toggle:hover{border-color:var(--dsw-alias-brand-primary);color:var(--dsw-alias-brand-primary)}
.anki-ok{font-size:11.5px;line-height:1.5;color:var(--dsw-alias-state-success-primary)}
.anki-fail{font-size:11.5px;line-height:1.5;color:var(--dsw-alias-state-error-primary);white-space:pre-wrap}
.anki-icon{display:block}
.anki-path{display:flex;align-items:stretch;gap:6px;min-width:0}
.anki-path-box{flex:1;min-width:0;display:flex;align-items:center;gap:6px;min-height:34px;box-sizing:border-box;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;background:var(--dsw-alias-bg-base);padding:6px 9px}
.anki-path-value{font-size:12.5px;color:var(--dsw-alias-label-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.anki-path-empty{font-size:12.5px;color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.anki-chips{display:flex;flex-wrap:wrap;gap:6px;min-width:0;padding:1px 0}
.anki-chip{display:inline-flex;align-items:center;gap:4px;max-width:100%;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;padding:2px 4px 2px 9px;font-size:11.5px;color:var(--dsw-alias-label-secondary)}
.anki-chip-text{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.anki-chip-x{border:none;background:none;color:var(--dsw-alias-label-tertiary);cursor:pointer;font:inherit;font-size:13px;line-height:1;padding:0 3px}
.anki-chip-x:hover{color:var(--dsw-alias-state-error-primary)}
.anki-modal{position:fixed;inset:0;z-index:1200;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(0,0,0,.45)}
.anki-dialog{width:min(680px,100%);max-height:min(560px,100%);display:flex;flex-direction:column;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:12px;box-shadow:0 18px 48px rgba(0,0,0,.32);overflow:hidden;outline:none}
.anki-dialog-head{flex:none;display:flex;flex-direction:column;gap:8px;padding:14px 16px 10px;border-bottom:1px solid var(--dsw-alias-border-l1)}
.anki-dialog h4{margin:0;font-size:14px;font-weight:650;color:var(--dsw-alias-label-primary)}
.anki-crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:2px;font-size:12px;min-width:0}
.anki-crumb{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:none;background:none;border-radius:6px;padding:2px 4px;color:var(--dsw-alias-label-secondary);font:inherit;font-size:12px;cursor:pointer}
.anki-crumb:hover{color:var(--dsw-alias-label-primary);background:var(--dsw-alias-interactive-bg-hover)}
.anki-crumb.current{color:var(--dsw-alias-label-primary);font-weight:600}
.anki-crumb-sep{color:var(--dsw-alias-label-tertiary)}
.anki-dialog-tools{flex:none;display:flex;align-items:center;gap:8px;padding:10px 16px 0;flex-wrap:wrap}
.anki-dialog-list{flex:1;min-height:130px;overflow:auto;padding:8px 10px 12px}
.anki-entry{display:flex;align-items:center;gap:8px;width:100%;text-align:left;background:none;border:none;border-radius:8px;padding:6px 8px;cursor:pointer;color:var(--dsw-alias-label-primary);font:inherit;font-size:12.5px}
.anki-entry:hover{background:var(--dsw-alias-interactive-bg-hover)}
.anki-entry.selected{background:var(--dsw-alias-interactive-bg-active,var(--dsw-alias-interactive-bg-hover))}
.anki-entry-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.anki-entry-meta{flex:none;font-size:11px;color:var(--dsw-alias-label-tertiary)}
.anki-entry svg{flex:none;color:var(--dsw-alias-label-secondary)}
.anki-dialog-empty{padding:18px 8px;font-size:12.5px;color:var(--dsw-alias-label-secondary)}
.anki-dialog-error{padding:0 16px 8px;font-size:12.5px;color:var(--dsw-alias-state-error-primary);white-space:pre-wrap}
.anki-dialog-foot{flex:none;display:flex;align-items:center;gap:8px;padding:10px 16px;border-top:1px solid var(--dsw-alias-border-l1)}
.anki-spacer{flex:1;min-width:0}
.anki-dialog-note{font-size:12px;color:var(--dsw-alias-label-secondary);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.anki-corner{position:relative;display:flex;align-items:center;gap:6px}
.anki-pill{display:inline-flex;align-items:center;gap:6px;height:28px;box-sizing:border-box;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);font:inherit;font-size:11.5px;font-weight:550;padding:0 10px;cursor:pointer;white-space:nowrap}
.anki-pill:hover{border-color:var(--dsw-alias-brand-primary)}
.anki-pill[aria-expanded=true]{border-color:var(--dsw-alias-brand-primary);color:var(--dsw-alias-brand-primary)}
.anki-dot{width:7px;height:7px;border-radius:999px;background:var(--dsw-alias-state-idle-primary);flex:none}
.anki-dot.green{background:var(--dsw-alias-state-success-primary)}
.anki-dot.warn{background:var(--dsw-alias-state-warn-primary)}
.anki-dot.error{background:var(--dsw-alias-state-error-primary)}
.anki-pill-state{color:var(--dsw-alias-label-secondary);font-weight:500}
.anki-pop{position:absolute;z-index:80;right:0;top:calc(100% + 8px);width:min(360px,calc(100vw - 48px));box-sizing:border-box;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.28);padding:14px}
.anki-pop-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
.anki-pop h4{margin:0;font-size:13px;font-weight:650;color:var(--dsw-alias-label-primary)}
.anki-pop-detail{font-size:12px;line-height:1.55;color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
.anki-pop-foot{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:10px}
.anki-tabs{display:flex;align-items:center;gap:2px;border-bottom:1px solid var(--dsw-alias-border-l1);margin:0}
.anki-tab{border:none;border-bottom:2px solid transparent;background:none;color:var(--dsw-alias-label-secondary);font:inherit;font-size:12.5px;font-weight:550;padding:7px 12px;margin-bottom:-1px;cursor:pointer;white-space:nowrap}
.anki-tab:hover{color:var(--dsw-alias-label-primary)}
.anki-tab.active{color:var(--dsw-alias-brand-primary);border-bottom-color:var(--dsw-alias-brand-primary)}
.anki-tabpanel{padding-top:14px}
.anki-tabpanel[hidden]{display:none}
.anki-form-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px}
.anki-report{display:flex;flex-direction:column;gap:12px;min-width:0}
.anki-report-hero{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap}
.anki-report-hero .anki-hero strong{font-size:34px}
.anki-report-split{display:flex;height:9px;border-radius:999px;overflow:hidden;background:var(--dsw-alias-bg-layer-2);margin-top:6px}
.anki-report-split i{display:block;height:100%}
.anki-report-split .mature{background:var(--dsw-alias-brand-primary)}
.anki-report-split .young{background:var(--dsw-alias-state-warn-primary)}
.anki-report-legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;font-size:11.5px;color:var(--dsw-alias-label-secondary)}
.anki-report-legend span{display:inline-flex;align-items:center;gap:5px}
.anki-report-legend i{width:7px;height:7px;border-radius:999px;display:inline-block}
.anki-report-meta{font-size:11.5px;line-height:1.55;color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
.anki-report-raw{margin-top:4px}
.anki-report-raw summary{cursor:pointer;font-size:11.5px;color:var(--dsw-alias-label-secondary);user-select:none}
.anki-report-raw pre{max-height:280px}
.anki-report-empty{border:1px dashed var(--dsw-alias-border-l2);border-radius:10px;padding:18px;text-align:center;color:var(--dsw-alias-label-secondary);font-size:12.5px;line-height:1.6}
.anki-report-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:8px}
.anki-report-row{display:grid;grid-template-columns:minmax(76px,120px) 1fr 72px;gap:8px;align-items:center;font-size:11.5px}
.anki-report-row .anki-bar{height:7px}
.anki-report-row b{font-weight:650;font-variant-numeric:tabular-nums;text-align:right;color:var(--dsw-alias-label-primary)}
@media (max-width:720px){.anki-form-grid{grid-template-columns:minmax(0,1fr)}}
.anki-tab-wide{padding-left:20px;padding-right:20px}
.anki-fixgrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:16px;align-items:start}
.anki-fixgrid > .anki-card{min-width:0}
@media (max-width:980px){.anki-fixgrid{grid-template-columns:minmax(0,1fr)}}
.anki-candlist{display:flex;flex-direction:column;gap:6px;min-width:0}
.anki-cand{min-width:0;border:1px solid var(--dsw-alias-border-l1);border-radius:9px;background:var(--dsw-alias-bg-base);padding:8px 10px;display:flex;flex-direction:column;gap:5px}
.anki-cand-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}
.anki-cand-check{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--dsw-alias-label-secondary);cursor:pointer;user-select:none}
.anki-cand-check input{accent-color:var(--dsw-alias-brand-primary)}
.anki-cand-word{font-size:14px;font-weight:650;line-height:1.3;color:var(--dsw-alias-label-primary)}
.anki-cand-reading{font-size:11.5px;color:var(--dsw-alias-label-secondary)}
.anki-cand-audio{display:flex;flex-wrap:wrap;gap:6px;min-width:0}
.anki-cand-audio .anki-tag{font-size:11px}
.anki-cand-index{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;padding:0 5px;border-radius:6px;font-size:11px;font-weight:700;color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-l2)}
.anki-cand.selected{border-color:var(--dsw-alias-brand-primary);box-shadow:0 0 0 1px var(--dsw-alias-brand-primary) inset}
.anki-cand.selected .anki-cand-index{color:var(--dsw-alias-brand-primary);background:transparent}
.anki-cand-sentence{font-size:13.5px;line-height:1.55;color:var(--dsw-alias-label-primary);word-break:break-word}
.anki-fixprev{border:1px solid var(--dsw-alias-border-l1);border-radius:9px;background:var(--dsw-alias-bg-base);padding:8px 10px;display:flex;flex-direction:column;gap:6px;min-width:0}
.anki-fixprev-sentence{font-size:13px;line-height:1.6;color:var(--dsw-alias-label-primary);overflow-wrap:anywhere}
.anki-fixactions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
`

    async function rpc(method, args) {
      const response = await fetch('/anki-workspace/api', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ method, args: args || {} }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data || data.ok !== true) {
        throw new Error((data && data.error) || ('HTTP ' + response.status))
      }
      return data.value
    }

    function fmtTime(value) {
      if (!value) return '—'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return String(value)
      return date.toLocaleString()
    }

    function truncate(text, max) {
      const value = String(text == null ? '' : text)
      return value.length > max ? value.slice(0, max) + '\n…(截断)' : value
    }

    function pct(value) {
      return typeof value === 'number' && Number.isFinite(value)
        ? (value * 100).toFixed(1) + '%'
        : '?'
    }

    function coverSummary(result) {
      if (result == null) return ''
      const lines = []
      lines.push('tokens ' + (result.tokens == null ? '?' : result.tokens) +
        ' · types ' + (result.types == null ? '?' : result.types))
      for (const key of ['cover_all', 'cover_vocab', 'cover_learnable']) {
        const bucket = result[key]
        if (bucket == null) continue
        lines.push(key + ': deck ' + pct(bucket.deck) + ' · known ' + pct(bucket.known) +
          ' · oov ' + pct(bucket.oov) + ' · understood ' + pct(bucket.understood))
      }
      if (result.sentences) {
        lines.push('sentences: ' + (result.sentences.sentences == null ? '?' : result.sentences.sentences) +
          ' · full ' + pct(result.sentences.full) + ' · lenient ' + pct(result.sentences.lenient))
      }
      if (result.comprehension) {
        lines.push('comprehension: by_understood ' + pct(result.comprehension.by_understood) +
          ' · by_strict ' + pct(result.comprehension.by_strict))
      }
      if (Array.isArray(result.oov) && result.oov.length > 0) {
        lines.push('oov (' + result.oov.length + '): ' + JSON.stringify(result.oov.slice(0, 40)))
      }
      if (Array.isArray(result.untackled) && result.untackled.length > 0) {
        lines.push('untackled (' + result.untackled.length + '): ' + JSON.stringify(result.untackled.slice(0, 40)))
      }
      return lines.join('\n')
    }

    function formatValue(name, value, t) {
      const tr = typeof t === 'function' ? t : (key) => key
      if (value == null) return ''
      if (name === 'add-example') {
        const lines = [value.ok === true ? '三步完成' : '未完成', value.note || '']
        for (const step of value.steps || []) {
          lines.push('· ' + step.name + ': exit ' + (step.exitCode == null ? '?' : step.exitCode) +
            (step.timedOut ? '（超时）' : '') + ' · ' + (step.durationMs == null ? '?' : step.durationMs) + ' ms')
        }
        const last = (value.steps || []).slice(-1)[0]
        if (last && last.output) lines.push('', truncate(last.output, 4000))
        return lines.filter(Boolean).join('\n')
      }
      if (name === 'today-new') {
        return truncate([value.note || '', value.output || ''].filter(Boolean).join('\n\n'), 6000)
      }
      if (name === 'season-new') {
        const r = value.result
        if (r == null) {
          return truncate([value.note || '', value.output || ''].filter(Boolean).join('\n\n'), 6000)
        }
        const c = r.counts || {}
        const p = r.params || {}
        const m = r.meta || {}
        const lines = [
          '每季生词：' + (r.ok === false ? '失败' : '完成') +
            '（收录 ' + (c.picked == null ? '?' : c.picked) + ' 词 / 通用 ' +
            (c.common == null ? '?' : c.common) + ' + 作品 ' + (c.work == null ? '?' : c.work) + '）',
          '口径：Jiten ≤ ' + (p.jitenMax == null ? '?' : p.jitenMax) +
            '；作品层 ' + (p.workJitenMin == null ? '?' : p.workJitenMin) + '–' +
            (m.workJitenMax == null ? (p.workJitenMax == null ? '?' : p.workJitenMax) : m.workJitenMax) +
            ' 且出现 ≥ ' + (m.workMinCount == null ? (p.workMinCount == null ? '?' : p.workMinCount) : m.workMinCount),
          '模式：' + (value.commit === true ? '已写季标签' : '只出清单'),
        ]
        if (r.tag) lines.push('季标签：' + r.tag)
        if (Array.isArray(m.relaxed)) {
          for (const row of m.relaxed) lines.push('放宽：' + (row.why || ''))
        }
        if (r.artifacts) {
          lines.push('清单：' + (r.artifacts.report_md || '—'))
          lines.push('数据：' + (r.artifacts.season_json || '—'))
        }
        return truncate(lines.join('\n'), 6000)
      }
      if (name === 'vocab-cover') {
        const body = value.result == null ? (value.parseError || '') : coverSummary(value.result)
        return truncate([body, value.output || ''].filter(Boolean).join('\n\n'), 6000)
      }
      if (name === 'study-report') {
        const lines = []
        if (value.skipped) lines.push(value.reason || '本月已生成，跳过')
        lines.push('报告：' + (value.reportPath || '—'))
        if (value.reportBytes != null) lines.push('大小：' + value.reportBytes + ' 字节')
        if (value.report) lines.push('', truncate(JSON.stringify(value.report, null, 2), 5000))
        if (value.output) lines.push('', truncate(value.output, 3000))
        return lines.filter(Boolean).join('\n')
      }
      if (name === 'word-audio') {
        const lines = []
        if (value.phase === 'apply') {
          lines.push(value.ok === true ? tr('result.committed') : tr('result.failed'))
          if (value.noteIds && value.noteIds.length > 0) lines.push('noteIds: ' + value.noteIds.join(', '))
          if (value.verified) lines.push('回读校验通过')
          if (value.note) lines.push(value.note)
          if (value.output) lines.push('', truncate(value.output, 3000))
        } else if (value.phase === 'plan') {
          lines.push(value.note || '')
          if (value.output) lines.push(truncate(value.output, 3000))
        }
        return lines.filter(Boolean).join('\n')
      }
      return truncate(JSON.stringify(value, null, 2), 6000)
    }

    // ------------------------------------------------------------------
    // 结构化结果视图：today-new / vocab cover 的 JSON 都在这里变成面板
    // ------------------------------------------------------------------
    function baseName(path) {
      const value = String(path == null ? '' : path)
      const cut = Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\'))
      return cut >= 0 ? value.slice(cut + 1) : value
    }

    function numberText(value, fallback) {
      return typeof value === 'number' && Number.isFinite(value)
        ? value.toLocaleString()
        : (fallback || '—')
    }

    function ratioText(value) {
      return typeof value === 'number' && Number.isFinite(value)
        ? (value * 100).toFixed(1) + '%'
        : '—'
    }

    function barWidth(value) {
      if (typeof value !== 'number' || !Number.isFinite(value)) return '0%'
      return (Math.max(0, Math.min(1, value)) * 100).toFixed(1) + '%'
    }

    function Kpi(props) {
      return h('div', { className: 'anki-kpi', title: props.title || '' },
        h('b', null, props.value),
        h('span', null, props.label))
    }

    function MetricBar(props) {
      return h('div', { className: 'anki-metric', title: props.title || props.label },
        h('span', { className: 'anki-metric-label' }, props.label),
        h('span', { className: 'anki-bar' + (props.tone ? ' ' + props.tone : '') },
          h('i', { style: { width: barWidth(props.value) } })),
        h('span', { className: 'anki-metric-value' }, ratioText(props.value)))
    }

    function Tag(props) {
      return h('span', { className: 'anki-tag' + (props.dim ? ' dim' : ''), title: props.title || '' },
        props.label,
        props.value == null ? null : h('b', null, props.value))
    }

    function ResultHead(props) {
      return h('div', { className: 'anki-result-head' },
        h('div', { style: { minWidth: 0 } },
          h('div', { className: 'anki-result-title', title: props.title || '' }, props.title),
          props.sub ? h('div', { className: 'anki-result-sub' }, props.sub) : null),
        h(Badge, { tone: props.tone }, props.badge))
    }

    function ResultSection(props) {
      return h('div', { className: 'anki-section' },
        h('h5', null, props.title),
        props.children)
    }

    function WordRow(props) {
      const { t, word, index, maxScore } = props
      const score = Number(word.score)
      const ratio = maxScore > 0 && Number.isFinite(score) ? score / maxScore : 0
      const meta = []
      if (word.jiten != null) meta.push('JAR ' + word.jiten)
      meta.push(numberText(word.occurrences) + ' ' + t('result.times'))
      meta.push(numberText(word.episodes) + ' ' + t('result.episodesUnit'))
      if (Array.isArray(word.notes) && word.notes.length > 0) {
        meta.push(word.notes.length + ' ' + t('result.notesUnit'))
      }
      if (word.level) meta.push(word.level)
      if (word.pos) meta.push(word.pos)
      return h('div', { className: 'anki-word' },
        h('div', { className: 'anki-word-head' },
          h('span', { className: 'anki-word-index' }, String(index).padStart(2, '0')),
          h('span', { className: 'anki-word-form' }, word.word),
          word.reading ? h('span', { className: 'anki-word-reading' }, word.reading) : null,
          word.sense_repaired ? h(Badge, { tone: 'warn' }, t('result.repaired')) : null),
        h('div', { className: 'anki-word-meta' }, meta.join(' · ')),
        h('div', { className: 'anki-word-score' },
          h('span', { className: 'anki-bar' },
            h('i', { style: { width: barWidth(ratio) } })),
          h('span', { className: 'anki-word-score-val' },
            Number.isFinite(score) ? score.toFixed(2) : '—')),
        word.why ? h('div', { className: 'anki-word-why' }, word.why) : null,
        word.first && word.first.text
          ? h('div', { className: 'anki-quote' }, word.first.text)
          : null)
    }

    function TodayNewResult(props) {
      const { t, value } = props
      const r = value && value.result ? value.result : null
      const [showAll, setShowAll] = React.useState(false)
      if (r == null) return h('pre', { className: 'anki-out' }, formatValue('today-new', value))

      const counts = r.counts || {}
      const picked = Array.isArray(r.picked) ? r.picked : []
      const pending = Array.isArray(r.pending) ? r.pending : []
      const dropped = Array.isArray(r.dropped) ? r.dropped : []
      const senseDropped = Array.isArray(r.dropped_sense) ? r.dropped_sense : []
      const repaired = Array.isArray(r.sense_repaired) ? r.sense_repaired : []
      const repairOk = repaired.filter(function (row) { return row.ok === true })
      const repairFailed = repaired.filter(function (row) { return row.ok !== true })
      const rank = r.ranking || {}
      const write = r.write || {}
      const committed = write.committed === true || r.commit === true
      const failed = value.ok === false || r.ok === false ||
        (value.exitCode != null && value.exitCode !== 0)
      const rankedByLlm = rank.by === 'llm'
      const maxScore = picked.reduce(function (acc, word) {
        return Math.max(acc, Number(word.score) || 0)
      }, 0)
      const visible = showAll ? picked : picked.slice(0, 12)
      const skip = r.skipped || {}
      const skipRows = [
        ['result.skip.noRank', skip.no_rank],
        ['result.skip.noNotes', skip.no_notes],
        ['result.skip.reading', skip.reading],
        ['result.skip.phrases', skip.phrases],
        ['result.skip.unranked', skip.unranked],
      ].filter(function (row) {
        return typeof row[1] === 'number' && row[1] > 0
      })
      const parts = []
      if (r.generated_at) parts.push(t('result.generated') + ' ' + fmtTime(r.generated_at))
      if (r.window) {
        parts.push(t('result.window') + ' ' + numberText(r.window.episodes) + ' ' + t('result.episodes'))
      }
      if (rankedByLlm) {
        parts.push(t('result.rank.llm'))
        if (rank.cached === true) parts.push(t('result.rank.cached'))
        else if (rank.calls != null) parts.push(rank.calls + ' × ' + (rank.secs == null ? '?' : rank.secs) + 's')
      } else if (r.formula) {
        parts.push('μ ' + r.formula.mu + ' · λ ' + r.formula.lam)
      }
      const errorText = value.error || r.error || ''

      return h('div', { className: 'anki-result' },
        h(ResultHead, {
          title: baseName(r.source || '') || t('result.empty'),
          sub: parts.join(' · '),
          tone: failed ? 'error' : committed ? 'green' : 'warn',
          badge: failed ? t('result.failed') : committed ? t('result.committed') : t('result.dryRun'),
        }),
        failed && errorText !== '' ? h('div', { className: 'anki-fail' }, errorText) : null,
        h('div', { className: 'anki-kpis' },
          h(Kpi, { label: t('result.candidates'), value: numberText(counts.candidates) }),
          h(Kpi, { label: t('result.pickedWords'), value: numberText(picked.length) }),
          h(Kpi, { label: t('result.noteCount'), value: numberText(counts.notes) }),
          h(Kpi, {
            label: t('result.rankedBy'),
            value: rankedByLlm ? t('result.rank.llm') : t('result.rank.formula'),
          })),
        picked.length === 0
          ? h('div', { className: 'anki-result-sub' }, errorText || t('result.empty'))
          : h('div', { className: 'anki-words' }, visible.map(function (word, index) {
              return h(WordRow, {
                key: (word.word || '') + '#' + index,
                t: t,
                word: word,
                index: index + 1,
                maxScore: maxScore,
              })
            })),
        picked.length > 12
          ? h('button', {
              type: 'button',
              className: 'anki-toggle',
              onClick: function () { setShowAll(function (v) { return !v }) },
            }, showAll ? t('result.showLess') : t('result.showAll') + ' (' + picked.length + ')')
          : null,
        pending.length > 0
          ? h(ResultSection, { title: t('result.pending.title') },
              h('div', { className: 'anki-chiplist' }, pending.map(function (word, index) {
                return h(Tag, {
                  key: (word.word || '') + '#' + index,
                  label: word.word + (word.reading ? '（' + word.reading + '）' : ''),
                  value: numberText(word.occurrences) + t('result.times'),
                  title: word.first && word.first.text ? word.first.text : '',
                })
              })))
          : null,
        r.plan
          ? h(ResultSection, { title: t('result.plan.title') },
              h('div', { className: 'anki-chiplist' },
                h(Tag, { label: t('result.plan.old'), value: numberText(r.plan.old), dim: true }),
                h(Tag, { label: t('result.plan.keep'), value: numberText(r.plan.keep) }),
                h(Tag, { label: t('result.plan.remove'), value: numberText(r.plan.remove) }),
                h(Tag, { label: t('result.plan.add'), value: numberText(r.plan.add) })))
          : null,
        repairOk.length > 0
          ? h(ResultSection, { title: t('result.sense.title') },
              h('div', { className: 'anki-rows' }, repairOk.map(function (row, index) {
                return h('div', { className: 'anki-rowline', key: 'fix' + index },
                  h('b', null, row.word), '：', row.why || '')
              })))
          : null,
        repairFailed.length > 0
          ? h(ResultSection, { title: t('result.sense.failed') },
              h('div', { className: 'anki-rows' }, repairFailed.map(function (row, index) {
                return h('div', { className: 'anki-rowline', key: 'fixbad' + index },
                  h('b', null, row.word), '：', row.why || '')
              })))
          : null,
        senseDropped.length > 0
          ? h(ResultSection, { title: t('result.sense.dropped') },
              h('div', { className: 'anki-rows' }, senseDropped.slice(0, 8).map(function (row, index) {
                return h('div', { className: 'anki-rowline', key: 'sense' + index },
                  h('b', null, row.word), '：',
                  (row.card_meaning || '—') + ' → ' +
                  (row.sense_gloss || '—') +
                  (row.why ? '（' + row.why + '）' : ''))
              })))
          : null,
        dropped.length > 0
          ? h(ResultSection, { title: t('result.dropped.title') },
              h('div', { className: 'anki-rows' }, dropped.slice(0, 8).map(function (row, index) {
                return h('div', { className: 'anki-rowline', key: 'drop' + index },
                  h('b', null, row.word), '：', row.reason || '')
              })))
          : null,
        skipRows.length > 0
          ? h(ResultSection, { title: t('result.skipped.title') },
              h('div', { className: 'anki-chiplist' }, skipRows.map(function (row) {
                return h(Tag, { key: row[0], label: t(row[0]), value: numberText(row[1]), dim: true })
              })))
          : null,
        r.artifacts
          ? h(ResultSection, { title: t('result.artifacts') },
              h('div', { className: 'anki-rows' },
                h('div', { className: 'anki-rowline' }, r.artifacts.picked_json || ''),
                h('div', { className: 'anki-rowline' }, r.artifacts.report_md || '')))
          : null)
    }

    function SeasonNewResult(props) {
      const { t, value } = props
      const r = value && value.result ? value.result : null
      const [showAll, setShowAll] = React.useState(false)
      if (r == null) return h('pre', { className: 'anki-out' }, formatValue('season-new', value))

      const counts = r.counts || {}
      const params = r.params || {}
      const meta = r.meta || {}
      const picked = Array.isArray(r.picked) ? r.picked : []
      const visible = showAll ? picked : picked.slice(0, 20)
      const committed = r.commit === true
      const failed = value.ok === false || r.ok === false ||
        (value.exitCode != null && value.exitCode !== 0)
      const errorText = value.error || r.error || ''
      const parts = []
      if (r.generated_at) parts.push(t('result.generated') + ' ' + fmtTime(r.generated_at))
      if (r.window) {
        parts.push(t('result.window') + ' ' + numberText(r.window.episodes) + ' ' + t('result.episodes'))
      }
      parts.push('Jiten ≤ ' + numberText(params.jitenMax))
      if (meta.workMinCount != null) parts.push('≥ ' + meta.workMinCount + ' ' + t('result.times'))
      parts.push(numberText(params.minWords) + '–' + numberText(params.maxWords))
      if (r.tag) parts.push(r.tag)

      return h('div', { className: 'anki-result' },
        h(ResultHead, {
          title: baseName(r.source || '') || t('result.empty'),
          sub: parts.join(' · '),
          tone: failed ? 'error' : committed ? 'green' : 'warn',
          badge: failed ? t('result.failed') : committed ? t('result.committed') : t('result.dryRun'),
        }),
        failed && errorText !== '' ? h('div', { className: 'anki-fail' }, errorText) : null,
        h('div', { className: 'anki-kpis' },
          h(Kpi, { label: t('card.seasonNew.commonLayer'), value: numberText(counts.common) }),
          h(Kpi, { label: t('card.seasonNew.workLayer'), value: numberText(counts.work) }),
          h(Kpi, { label: t('result.pickedWords'), value: numberText(counts.picked) }),
          h(Kpi, { label: t('result.noteCount'), value: numberText(counts.notes) })),
        picked.length === 0
          ? h('div', { className: 'anki-result-sub' }, errorText || t('result.empty'))
          : h('div', { className: 'anki-words' }, visible.map(function (word, index) {
              const layerText = word.layer === 'work'
                ? t('card.seasonNew.workLayer')
                : t('card.seasonNew.commonLayer')
              return h('div', { className: 'anki-word', key: (word.word || '') + '#' + index },
                h('div', { className: 'anki-word-head' },
                  h('span', { className: 'anki-word-index' }, String(index + 1).padStart(2, '0')),
                  h('span', { className: 'anki-word-form' }, word.word),
                  word.reading ? h('span', { className: 'anki-word-reading' }, word.reading) : null,
                  h(Badge, { tone: word.layer === 'work' ? 'warn' : 'idle' }, layerText)),
                h('div', { className: 'anki-word-meta' },
                  ['JAR ' + numberText(word.jiten),
                   numberText(word.occurrences) + ' ' + t('result.times'),
                   numberText(word.episodes) + ' ' + t('result.episodesUnit'),
                   (word.notes ? word.notes.length : 0) + ' ' + t('result.notesUnit')].join(' · ')),
                word.first && word.first.text
                  ? h('div', { className: 'anki-quote' }, word.first.text)
                  : null)
            })),
        picked.length > 20
          ? h('button', {
              type: 'button',
              className: 'anki-toggle',
              onClick: function () { setShowAll(function (v) { return !v }) },
            }, showAll ? t('result.showLess') : t('result.showAll') + ' (' + picked.length + ')')
          : null,
        Array.isArray(meta.relaxed) && meta.relaxed.length > 0
          ? h(ResultSection, { title: t('card.seasonNew.relaxed') },
              h('div', { className: 'anki-rows' }, meta.relaxed.map(function (row, index) {
                return h('div', { className: 'anki-rowline', key: 'relax' + index }, row.why || '')
              })))
          : null,
        r.plan
          ? h(ResultSection, { title: t('result.plan.title') },
              h('div', { className: 'anki-chiplist' },
                h(Tag, { label: t('result.plan.old'), value: numberText(r.plan.old), dim: true }),
                h(Tag, { label: t('result.plan.keep'), value: numberText(r.plan.keep) }),
                h(Tag, { label: t('result.plan.remove'), value: numberText(r.plan.remove) }),
                h(Tag, { label: t('result.plan.add'), value: numberText(r.plan.add) })))
          : null,
        r.artifacts
          ? h(ResultSection, { title: t('result.artifacts') },
              h('div', { className: 'anki-rows' },
                h('div', { className: 'anki-rowline' }, r.artifacts.report_md || ''),
                h('div', { className: 'anki-rowline' }, r.artifacts.season_json || '')))
          : null)
    }

    function CoverTable(props) {
      const { t, res } = props
      const buckets = [
        ['cover.row.core', 'cover_all', 'cover_vocab', 'cover_learnable', 'core'],
        ['cover.row.corejlpt', 'cover_all', 'cover_vocab', 'cover_learnable', 'corejlpt'],
        ['cover.row.deck', 'cover_all', 'cover_vocab', 'cover_learnable', 'deck'],
        ['cover.row.known', 'cover_all', 'cover_vocab', 'cover_learnable', 'known'],
        ['cover.row.mature', 'cover_all', 'cover_vocab', 'cover_learnable', 'mature'],
        ['cover.row.understood', 'cover_all', 'cover_vocab', 'cover_learnable', 'understood_lenient'],
        ['cover.row.strict', 'cover_all', 'cover_vocab', 'cover_learnable', 'understood'],
        ['cover.row.oov', 'cover_all', 'cover_vocab', 'cover_learnable', 'oov'],
        ['cover.row.proper', 'cover_all', 'cover_vocab', 'cover_learnable', 'proper'],
      ]
      const cell = function (source, key) {
        const group = res[source] || {}
        return ratioText(group[key])
      }
      return h('div', { className: 'anki-cov' },
        h('span', { className: 'm' }, t('cover.table.metric')),
        h('span', { className: 'h' }, t('cover.allTokens')),
        h('span', { className: 'h' }, t('cover.vocabTokens')),
        h('span', { className: 'h' }, t('cover.learnable')),
        buckets.map(function (row) {
          return h(React.Fragment, { key: row[0] },
            h('span', { className: 'm' }, t(row[0])),
            h('span', { className: 'v' }, cell(row[1], row[4])),
            h('span', { className: 'v dim' }, cell(row[2], row[4])),
            h('span', { className: 'v dim' }, cell(row[3], row[4])))
        }))
    }

    function CoverOne(props) {
      const { t, res } = props
      const summary = res.summary || {}
      const comp = res.comprehension || {}
      const sent = res.sentences || {}
      const reach = res.reach || {}
      const oov = Array.isArray(res.oov) ? res.oov : []
      const untackled = Array.isArray(res.untackled) ? res.untackled : []
      const screen = res.screen || null
      const deck = summary.deck != null ? summary.deck : (res.cover_all || {}).deck
      const known = summary.known != null ? summary.known : (res.cover_all || {}).known
      const understood = summary.understood != null
        ? summary.understood
        : (res.cover_all || {}).understood_lenient
      const strict = summary.strict != null ? summary.strict : (res.cover_all || {}).understood
      const label = res.label === '--text'
        ? t('cover.textInput')
        : (baseName(res.label || '') || t('cover.textInput'))
      const parts = []
      if (res.generated_at) parts.push(t('result.generated') + ' ' + fmtTime(res.generated_at))
      if (res.tokens != null) parts.push(numberText(res.tokens) + ' ' + t('cover.tokens'))
      const screenWords = screen && Array.isArray(screen.words) ? screen.words : []

      return h('div', { className: 'anki-result' },
        h(ResultHead, {
          title: label,
          sub: parts.join(' · '),
          tone: 'green',
          badge: t('cover.coverage'),
        }),
        h('div', { className: 'anki-hero' },
          h('strong', null, ratioText(understood)),
          h('span', null, t('cover.understood'))),
        h('div', { className: 'anki-kpis' },
          h(Kpi, { label: t('cover.chars'), value: numberText(res.chars) }),
          h(Kpi, { label: t('cover.tokens'), value: numberText(res.tokens) }),
          h(Kpi, { label: t('cover.types'), value: numberText(res.types) }),
          h(Kpi, { label: t('cover.sentences'), value: numberText(sent.sentences) })),
        h('div', { className: 'anki-rows' },
          h(MetricBar, { label: t('cover.deck'), value: deck, tone: 'green' }),
          h(MetricBar, { label: t('cover.known'), value: known, tone: 'green' }),
          h(MetricBar, { label: t('cover.strict'), value: strict, tone: 'warn' })),
        h(ResultSection, { title: t('cover.table.title') },
          h(CoverTable, { t: t, res: res })),
        h('div', { className: 'anki-chiplist' },
          h(Tag, { label: t('cover.sentenceFull'), value: ratioText(sent.full) }),
          h(Tag, { label: t('cover.sentenceLenient'), value: ratioText(sent.lenient_l) }),
          h(Tag, { label: t('cover.listening'), value: ratioText(comp.by_understood_listening) })),
        Object.keys(reach).length > 0
          ? h(ResultSection, { title: t('cover.reach.title') },
              h('div', { className: 'anki-rows' }, ['core6000', 'jlpt', 'deck'].map(function (key) {
                const item = reach[key]
                if (item == null) return null
                return h('div', { className: 'anki-rowline', key: key },
                  h('b', null, key), '：',
                  numberText(item.seen) + ' / ' + numberText(item.deck_total) + ' ' +
                  t('cover.reach.seen') + '（' + ratioText(item.seen_ratio) + '）' +
                  (item.new_to_me != null ? ' · ' + t('result.skip.noNotes') + ' ' + numberText(item.new_to_me) : ''))
              })))
          : null,
        screen != null
          ? h(ResultSection, { title: t('cover.screen.title') },
              screenWords.length === 0
                ? h('div', { className: 'anki-result-sub' }, t('cover.screen.empty'))
                : h('div', { className: 'anki-words' }, screenWords.slice(0, 15).map(function (word, index) {
                    return h(WordRow, {
                      key: 'scr' + index,
                      t: t,
                      word: {
                        word: word.word,
                        reading: word.reading,
                        occurrences: word.occurrences,
                        why: word.why,
                        first: { text: word.first },
                        notes: [],
                      },
                      index: index + 1,
                      maxScore: Math.max(1, ...screenWords.map(function (row) {
                        return Number(row.occurrences) || 0
                      })),
                    })
                  })))
          : null,
        h(ResultSection, { title: t('cover.oov.title') },
          oov.length === 0
            ? h('div', { className: 'anki-result-sub' }, t('cover.oov.empty'))
            : h('div', { className: 'anki-chiplist' },
                oov.slice(0, 60).map(function (row, index) {
                  return h(Tag, {
                    key: 'oov' + index,
                    label: row[0],
                    value: numberText(row[1]) + t('result.times'),
                  })
                }).concat(oov.length > 60
                  ? [h(Tag, {
                      key: 'oov-rest',
                      label: '+' + (oov.length - 60) + ' ' + t('cover.oov.more'),
                      dim: true,
                    })]
                  : []))
        ),
        h(ResultSection, { title: t('cover.untackled.title') },
          untackled.length === 0
            ? h('div', { className: 'anki-result-sub' }, t('cover.untackled.empty'))
            : h('div', { className: 'anki-chiplist' },
                untackled.slice(0, 40).map(function (row, index) {
                  return h(Tag, {
                    key: 'unt' + index,
                    label: row[0] + (row[1] ? ' [' + String(row[1]).slice(0, 4) + ']' : ''),
                    value: numberText(row[2]) + t('result.times'),
                  })
                }).concat(untackled.length > 40
                  ? [h(Tag, {
                      key: 'unt-rest',
                      label: '+' + (untackled.length - 40) + ' ' + t('cover.oov.more'),
                      dim: true,
                    })]
                  : [])))
      )
    }

    function CoverResult(props) {
      const { t, value } = props
      const result = value && value.result ? value.result : null
      if (result == null) return h('pre', { className: 'anki-out' }, formatValue('vocab-cover', value))
      const list = Array.isArray(result) ? result : [result]
      return h('div', { className: 'anki-result' }, list.map(function (res, index) {
        return h(CoverOne, { key: 'cover' + index, t: t, res: res || {} })
      }))
    }

    function Badge(props) {
      return h('span', { className: 'anki-badge ' + (props.tone || 'idle') }, props.children)
    }

    function ResultBlock(props) {
      const { t, name, value } = props
      if (value == null) return h('div', { className: 'anki-meta' }, t('common.noResult'))
      if (name === 'today-new' && value.result) return h(TodayNewResult, { t, value })
      if (name === 'season-new' && value.result) return h(SeasonNewResult, { t, value })
      if (name === 'vocab-cover' && value.result) return h(CoverResult, { t, value })
      if (name === 'study-report') return h(ReportResult, { t, value })
      return h('pre', { className: 'anki-out' }, formatValue(name, value, t))
    }

    function StatusPill(props) {
      const { t, tone, label, state, open, onClick } = props
      return h('button', {
        type: 'button',
        className: 'anki-pill',
        'aria-haspopup': 'dialog',
        'aria-expanded': open ? 'true' : 'false',
        title: t('status.details'),
        onClick,
      },
        h('span', { className: 'anki-dot ' + tone }),
        h('span', null, label),
        state ? h('span', { className: 'anki-pill-state' }, '· ' + state) : null,
      )
    }

    function StatusCorner(props) {
      const { t, anki, doctor, busy, onAction, updated } = props
      const [open, setOpen] = React.useState(null)
      const ref = React.useRef(null)

      React.useEffect(() => {
        if (open === null) return undefined
        const onPointerDown = (event) => {
          if (ref.current !== null && !ref.current.contains(event.target)) setOpen(null)
        }
        document.addEventListener('pointerdown', onPointerDown)
        return () => document.removeEventListener('pointerdown', onPointerDown)
      }, [open])

      const toggle = (key) => setOpen((previous) => previous === key ? null : key)
      const ankiTone = anki == null ? 'idle' : (anki.online ? 'green' : 'error')
      const ankiLabel = anki == null
        ? t('status.unknown')
        : anki.online ? t('status.online') : t('status.offline')
      const doctorTone = toneForDoctor(doctor)
      const doctorLabel = labelForDoctor(t, doctor)

      const ankiParts = []
      if (anki != null && anki.online) {
        if (anki.version != null) ankiParts.push('v' + anki.version)
        if (anki.decks != null) ankiParts.push(anki.decks + ' ' + t('status.decks'))
        if (anki.noteTypes != null) ankiParts.push(anki.noteTypes + ' ' + t('status.noteTypes'))
        if (anki.media != null) ankiParts.push(anki.media + ' ' + t('status.media'))
        if (anki.latencyMs != null) ankiParts.push(anki.latencyMs + ' ms')
      } else if (anki != null) {
        ankiParts.push(t('status.offline'))
        if (anki.error) ankiParts.push(String(anki.error).split(/\r?\n/)[0])
      }
      const ankiDetail = ankiParts.length > 0 ? ankiParts.join(' · ') : t('status.unknown')

      const doctorParts = []
      if (doctor != null) {
        doctorParts.push(t('status.passed') + ' ' + doctor.passed)
        doctorParts.push(t('status.hints') + ' ' + doctor.hints)
        doctorParts.push(t('status.blocking') + ' ' + doctor.blocking)
        if (doctor.summary) doctorParts.push(doctor.summary)
      }
      const doctorDetail = doctorParts.length > 0 ? doctorParts.join(' · ') : t('status.unknown')

      const popover = open === null ? null : h('div', { className: 'anki-pop', role: 'dialog', 'aria-modal': 'false' },
        h('div', { className: 'anki-pop-head' },
          h('h4', null, open === 'anki' ? t('status.anki') : t('status.doctor')),
          h(Badge, { tone: open === 'anki' ? ankiTone : doctorTone },
            open === 'anki' ? ankiLabel : doctorLabel),
        ),
        h('div', { className: 'anki-pop-detail' }, open === 'anki' ? ankiDetail : doctorDetail),
        h('div', { className: 'anki-pop-foot' },
          h('span', { className: 'anki-meta' },
            t('status.checked') + ' ' + (updated || '—')),
          h('button', {
            type: 'button',
            className: 'anki-btn',
            disabled: busy !== '',
            onClick: () => onAction(open === 'anki' ? 'status-now' : 'doctor'),
          }, busy === (open === 'anki' ? 'status-now' : 'doctor')
            ? t('common.working')
            : (open === 'anki' ? t('status.check') : t('status.runDoctor'))),
        ),
      )

      return h('div', { className: 'anki-corner', ref },
        h(StatusPill, {
          t,
          tone: ankiTone,
          label: t('status.anki'),
          state: ankiLabel,
          open: open === 'anki',
          onClick: () => toggle('anki'),
        }),
        h(StatusPill, {
          t,
          tone: doctorTone,
          label: t('status.doctor'),
          state: doctorLabel,
          open: open === 'doctor',
          onClick: () => toggle('doctor'),
        }),
        popover,
      )
    }

    function FolderGlyph() {
      return h('svg', { width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none', 'aria-hidden': true },
        h('path', {
          d: 'M3.7 6.5a1.6 1.6 0 0 1 1.6-1.6h4.1l1.8 2h7.5a1.6 1.6 0 0 1 1.6 1.6v9a1.6 1.6 0 0 1-1.6 1.6H5.3a1.6 1.6 0 0 1-1.6-1.6z',
          stroke: 'currentColor',
          strokeWidth: 1.5,
          strokeLinejoin: 'round',
        }),
      )
    }

    function FileGlyph() {
      return h('svg', { width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none', 'aria-hidden': true },
        h('path', {
          d: 'M6.5 3.9h7l4 4v11.9a1.2 1.2 0 0 1-1.2 1.2H6.5a1.2 1.2 0 0 1-1.2-1.2V5.1a1.2 1.2 0 0 1 1.2-1.2z',
          stroke: 'currentColor',
          strokeWidth: 1.5,
          strokeLinejoin: 'round',
        }),
        h('path', { d: 'M13.4 4.2v4h4', stroke: 'currentColor', strokeWidth: 1.5, strokeLinejoin: 'round' }),
      )
    }

    function PathField(props) {
      const { t, value, values, placeholder, onBrowse, onClear, onRemove } = props
      const list = Array.isArray(values) ? values : (value ? [value] : [])
      const multiple = Array.isArray(values)
      return h('div', { className: 'anki-path' },
        h('div', { className: 'anki-path-box' },
          list.length === 0
            ? h('span', { className: 'anki-path-empty' }, placeholder)
            : multiple
              ? h('div', { className: 'anki-chips' }, list.map((path) => h('span', { className: 'anki-chip', key: path },
                h('span', { className: 'anki-chip-text', title: path }, path),
                h('button', {
                  type: 'button',
                  className: 'anki-chip-x',
                  title: t('picker.remove'),
                  onClick: () => onRemove(path),
                }, '×'),
              )))
              : h('span', { className: 'anki-path-value', title: list[0] }, list[0]),
        ),
        h('button', { type: 'button', className: 'anki-btn', onClick: onBrowse }, t('picker.browse')),
        list.length > 0 && !multiple
          ? h('button', { type: 'button', className: 'anki-btn', onClick: onClear }, t('picker.clear'))
          : null,
      )
    }

    /**
     * In-app file/folder chooser backed by the host's read-only `browse` route.
     * Native OS dialogs cannot hand a path back to the browser, so the picker
     * lists the workspace through the Host half and returns workspace-relative
     * paths that `today-new` / `vocab cover` resolve against the root.
     */
    function PathPicker(props) {
      const { t, open, mode, accept, initialPath, onPick, onClose } = props
      const [dir, setDir] = React.useState('')
      const [listing, setListing] = React.useState(null)
      const [loading, setLoading] = React.useState(false)
      const [error, setError] = React.useState(null)
      const [filter, setFilter] = React.useState('')
      const [selected, setSelected] = React.useState([])
      const [showAllFiles, setShowAllFiles] = React.useState(false)
      const dialogRef = React.useRef(null)
      const acceptSet = React.useMemo(
        () => new Set((accept || []).map((ext) => String(ext).toLowerCase())),
        [accept],
      )

      const load = React.useCallback(async (path) => {
        setLoading(true)
        setError(null)
        try {
          const value = await rpc('browse', { path: path || '' })
          if (!value || value.ok !== true) throw new Error((value && value.error) || t('picker.failed'))
          setListing(value)
          setDir(value.path)
          setFilter('')
          return value
        } catch (cause) {
          setError(String(cause && cause.message ? cause.message : cause))
          return null
        } finally {
          setLoading(false)
        }
      }, [t])

      React.useEffect(() => {
        if (!open) return
        setListing(null)
        setShowAllFiles(false)
        setSelected([])
        const start = String(initialPath || '')
        const cut = start.lastIndexOf('/')
        const base = cut >= 0 ? start.slice(cut + 1) : start
        // A previously picked file reopens its folder with that file selected.
        const dot = base.lastIndexOf('.')
        const ext = dot > 0 ? base.slice(dot).toLowerCase() : ''
        const looksLikeFile = ext !== '' && (acceptSet.size === 0 || acceptSet.has(ext))
        if (!looksLikeFile) {
          load(start)
          return
        }
        load(cut >= 0 ? start.slice(0, cut) : '').then((value) => {
          if (value !== null) setSelected([start])
        })
      }, [open, initialPath, load, acceptSet])

      React.useEffect(() => {
        if (!open) return undefined
        const onKeyDown = (event) => {
          if (event.key === 'Escape') {
            event.stopPropagation()
            onClose()
          }
        }
        window.addEventListener('keydown', onKeyDown)
        if (dialogRef.current !== null) dialogRef.current.focus()
        return () => window.removeEventListener('keydown', onKeyDown)
      }, [open, onClose])

      if (!open) return null

      const entries = listing && Array.isArray(listing.entries) ? listing.entries : []
      const needle = filter.trim().toLowerCase()
      const visible = entries.filter((entry) => {
        if (entry.hidden === true) return false
        if (needle !== '' && !entry.name.toLowerCase().includes(needle)) return false
        if (entry.kind === 'dir') return true
        if (acceptSet.size === 0 || showAllFiles) return true
        return acceptSet.has(entry.ext)
      })

      const pickEntry = (entry) => {
        if (entry.kind === 'dir') {
          if (mode !== 'files') setSelected([])
          load(entry.path)
          return
        }
        if (mode === 'files') {
          setSelected((previous) => previous.includes(entry.path)
            ? previous.filter((path) => path !== entry.path)
            : previous.concat([entry.path]))
          return
        }
        setSelected([entry.path])
      }

      const confirmFiles = () => {
        if (selected.length === 0) return
        onPick(selected)
        onClose()
      }

      const confirmDir = () => {
        onPick([dir])
        onClose()
      }

      const titleKey = mode === 'dir'
        ? 'picker.title.dir'
        : mode === 'files' ? 'picker.title.files' : mode === 'any' ? 'picker.title.any' : 'picker.title.file'

      const note = mode === 'files'
        ? (selected.length === 0
            ? t('picker.noSelection')
            : t('picker.chosen') + ' ' + selected.length)
        : selected.length === 0
          ? t('picker.noSelection')
          : selected[0]

      const crumbs = listing && Array.isArray(listing.crumbs) ? listing.crumbs : []

      return h('div', {
        className: 'anki-modal',
        onMouseDown: (event) => { if (event.target === event.currentTarget) onClose() },
      },
        h('div', {
          className: 'anki-dialog',
          role: 'dialog',
          'aria-modal': 'true',
          'aria-label': t(titleKey),
          tabIndex: -1,
          ref: dialogRef,
        },
          h('div', { className: 'anki-dialog-head' },
            h('h4', null, t(titleKey)),
            h('div', { className: 'anki-crumbs' }, crumbs.map((crumb, index) => {
              const last = index === crumbs.length - 1
              return h('span', { key: crumb.path + '#' + index, style: { display: 'inline-flex', alignItems: 'center', gap: '2px', minWidth: 0 } },
                h('button', {
                  type: 'button',
                  className: 'anki-crumb' + (last ? ' current' : ''),
                  title: crumb.path === '' ? t('picker.root') : crumb.path,
                  onClick: () => load(crumb.path),
                }, crumb.name),
                last ? null : h('span', { className: 'anki-crumb-sep' }, '›'),
              )
            })),
          ),
          h('div', { className: 'anki-dialog-tools' },
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: loading || listing === null || listing.parent === null,
              onClick: () => listing && load(listing.parent),
            }, t('picker.up')),
            h('input', {
              className: 'anki-input',
              style: { flex: '1 1 160px', width: 'auto' },
              placeholder: t('picker.filter'),
              value: filter,
              onChange: (event) => setFilter(event.target.value),
            }),
            acceptSet.size === 0
              ? null
              : h('label', { className: 'anki-check' },
                  h('input', { type: 'checkbox', checked: showAllFiles, onChange: (event) => setShowAllFiles(event.target.checked) }),
                  t('picker.otherFiles'),
                ),
          ),
          h('div', { className: 'anki-dialog-list' },
            loading
              ? h('div', { className: 'anki-dialog-empty' }, t('picker.loading'))
              : visible.length === 0
                ? h('div', { className: 'anki-dialog-empty' }, t('picker.empty'))
                : visible.map((entry) => {
                    const active = entry.kind === 'file' && selected.includes(entry.path)
                    return h('button', {
                      key: entry.path,
                      type: 'button',
                      className: 'anki-entry' + (active ? ' selected' : ''),
                      title: entry.path,
                      onClick: () => pickEntry(entry),
                    },
                      entry.kind === 'dir' ? h(FolderGlyph) : h(FileGlyph),
                      h('span', { className: 'anki-entry-name' }, entry.name),
                      h('span', { className: 'anki-entry-meta' }, entry.kind === 'dir' ? '›' : entry.ext.replace('.', '')),
                    )
                  }),
            listing !== null && listing.truncated === true
              ? h('div', { className: 'anki-dialog-empty' }, t('picker.truncated') + ' ' + listing.total)
              : null,
          ),
          error === null ? null : h('div', { className: 'anki-dialog-error' }, error),
          h('div', { className: 'anki-dialog-foot' },
            h('span', { className: 'anki-dialog-note' }, note),
            h('span', { className: 'anki-spacer' }),
            h('button', { type: 'button', className: 'anki-btn', onClick: onClose }, t('picker.cancel')),
            mode === 'dir' || mode === 'any'
              ? h('button', { type: 'button', className: 'anki-btn', disabled: loading || listing === null, onClick: confirmDir }, t('picker.chooseDir'))
              : null,
            mode === 'dir'
              ? null
              : h('button', {
                  type: 'button',
                  className: 'anki-btn',
                  disabled: selected.length === 0,
                  onClick: confirmFiles,
                }, t('picker.choose')),
          ),
        ),
      )
    }

    /**
     * 本地模型档位下拉（今日选词 / 增加例句共用）。
     * value：'' = 默认（不注入旗标，跟随 local-llm.json + pin_active）；
     *        'profile:<name>' → llmProfile；'model:<id>' → llmModel。
     * 选了 profile 或 model 都会**关掉 pin**（llm_client.py 2026-11-14 口径）：
     * 用你点名的档位，而不是端点当前在服务的模型。
     */
    function LlmModelSelect(props) {
      const { t, data, value, onChange } = props
      const choice = (kind, name) => (name === '' ? '' : `${kind}:${name}`)
      const profiles = Array.isArray(data?.profiles) ? data.profiles : []
      const models = Array.isArray(data?.models) ? data.models : []
      return h('div', { className: 'anki-row' },
        h('span', { className: 'anki-meta' }, t('llm.label')),
        h('select', {
          className: 'anki-select',
          value,
          onChange: (event) => onChange(event.target.value),
        },
          h('option', { value: '' }, t('llm.default')
            + (data?.activeModel ? `（${t('llm.active')}：${data.activeModel}）` : '')),
          profiles.length === 0 ? null : h('optgroup', { label: t('llm.groupProfiles') },
            profiles.map((p) => {
              const bits = []
              if (p.model) bits.push(p.model)
              if (p.contextWindow) bits.push(`ctx ${p.contextWindow}`)
              return h('option', { key: `p:${p.name}`, value: choice('profile', p.name) },
                `${p.name === '' ? t('llm.default') : p.name}${bits.length ? ` — ${bits.join(' · ')}` : ''}`)
            })),
          models.length === 0 ? null : h('optgroup', { label: t('llm.groupModels') },
            models.map((m) => h('option', { key: `m:${m.id}`, value: choice('model', m.id) },
              `${m.id}${m.contextWindow ? ` · ctx ${m.contextWindow}` : ''}${data?.activeModel === m.id ? `（${t('llm.active')}）` : ''}`))),
        ),
      )
    }

    function llmArgsFrom(choice) {
      const raw = String(choice || '')
      const at = raw.indexOf(':')
      if (at <= 0) return {}
      const kind = raw.slice(0, at)
      const name = raw.slice(at + 1)
      if (kind === 'profile') return { llmProfile: name }
      if (kind === 'model') return { llmModel: name }
      return {}
    }

    function AddExampleCard(props) {
      const { t, call, busy, result, tabbed, llmModels, llmChoice, setLlmChoice } = props
      const [words, setWords] = React.useState('')
      const [noteIds, setNoteIds] = React.useState('')
      const [limit, setLimit] = React.useState('')
      // 默认真写（用户 2026-11-09 定的规矩）：取消勾选才演练。
      const [commit, setCommit] = React.useState(true)
      // Jisho 候选例句选择：listJisho 拉清单，pickIndex 钉住某条来覆写卡片资料。
      const [jishoList, setJishoList] = React.useState(null)
      const [pickIndex, setPickIndex] = React.useState(null)
      const running = busy === 'add-example'
      const runningList = busy === 'add-example-list'
      const anyRunning = busy !== ''
      const doList = () => {
        if (words.trim() === '') return
        setPickIndex(null)
        call('add-example', 'jisho-list', { words: words.trim(), limit: limit.trim() === '' ? undefined : Number(limit) }, 'add-example-list').then((value) => {
          if (value != null) setJishoList(value)
        })
      }
      const submit = () => call('add-example', 'add-example', {
        words,
        noteIds,
        commit,
        limit: limit.trim() === '' ? undefined : Number(limit),
        jishoPick: pickIndex || undefined,
        ...llmArgsFrom(llmChoice),
      })
      const candidates = jishoList && Array.isArray(jishoList.candidates) ? jishoList.candidates : []
      return h('section', { className: 'anki-card' },
        tabbed ? null : h('h3', null, t('card.addExample.title')),
        h('p', null, t('card.addExample.desc')),
        h('div', { className: 'anki-card-body' },
          h('div', { className: 'anki-form-grid' },
            h('input', {
              className: 'anki-input',
              placeholder: t('card.addExample.words'),
              value: words,
              onChange: (event) => setWords(event.target.value),
              onKeyDown: (event) => { if (event.key === 'Enter') doList() },
            }),
            h('input', {
              className: 'anki-input',
              placeholder: t('card.addExample.noteIds'),
              value: noteIds,
              onChange: (event) => setNoteIds(event.target.value),
            }),
          ),
          h('div', { className: 'anki-row' },
            h('input', {
              className: 'anki-input',
              style: { width: '110px' },
              placeholder: t('card.addExample.limit'),
              value: limit,
              inputMode: 'numeric',
              onChange: (event) => setLimit(event.target.value),
            }),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: commit, onChange: (event) => setCommit(event.target.checked) }),
              t('card.addExample.commit'),
            ),
          ),
          h(LlmModelSelect, { t, data: llmModels, value: llmChoice || '', onChange: setLlmChoice }),
          // —— Jisho 候选例句选择区 ——
          h('div', { className: 'anki-section' },
            h('div', { className: 'anki-row between' },
              h('h5', null, t('card.addExample.candidates')),
              h('button', {
                type: 'button',
                className: 'anki-btn',
                disabled: anyRunning || words.trim() === '',
                onClick: doList,
              }, runningList ? t('common.working') : t('card.addExample.listJisho')),
            ),
            jishoList == null
              ? null
              : candidates.length === 0
                ? h('div', { className: 'anki-meta' }, jishoList.note || t('card.addExample.none'))
                : h('div', { className: 'anki-candlist' },
                    h('div', { className: 'anki-result-sub' }, t('card.addExample.pickHint')),
                    candidates.map(function (cand) {
                      const selected = pickIndex === cand.index
                      return h('div', {
                        className: 'anki-cand' + (selected ? ' selected' : ''),
                        key: 'jisho' + cand.index,
                        onClick: function () { setPickIndex(selected ? null : cand.index) },
                      },
                        h('div', { className: 'anki-cand-head' },
                          h('span', { className: 'anki-cand-index' }, String(cand.index)),
                          h(Tag, { label: cand.source, value: cand.len + '字' }),
                          cand.rubyOk === false ? h(Badge, { tone: 'warn' }, t('card.addExample.rubyWarn')) : null,
                          selected ? h(Badge, { tone: 'green' }, '✓') : null),
                        h('div', { className: 'anki-cand-sentence' }, cand.jp))
                    }))
          ),
          h('div', { className: 'anki-row' },
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: anyRunning || (words.trim() === '' && noteIds.trim() === ''),
              onClick: submit,
            }, running ? t('common.working') : t('card.addExample.run') + (pickIndex ? '（#' + pickIndex + '）' : '')),
          ),
          h(ResultBlock, { t, name: 'add-example', value: result }),
        ),
      )
    }

    function TodayNewCard(props) {
      const { t, call, busy, result, seasonResult, tabbed, llmModels, llmChoice, setLlmChoice } = props
      const [input, setInput] = React.useState('')
      const [picking, setPicking] = React.useState(false)
      const [n, setN] = React.useState('30')
      const [season, setSeason] = React.useState(false)
      const [noLlmRank, setNoLlmRank] = React.useState(false)
      const [fast, setFast] = React.useState(false)
      // 默认真写（用户 2026-11-10 定的规矩）：取消勾选才演练。
      const [commit, setCommit] = React.useState(true)
      // 每季生词：默认值来自 2026-11-13 的 19 部 12–13 集实测结论。
      const [jitenMax, setJitenMax] = React.useState('12000')
      const [workJitenMin, setWorkJitenMin] = React.useState('12001')
      const [workJitenMax, setWorkJitenMax] = React.useState('24000')
      const [workMinCount, setWorkMinCount] = React.useState('3')
      const [minWords, setMinWords] = React.useState('550')
      const [maxWords, setMaxWords] = React.useState('800')
      const [includeNames, setIncludeNames] = React.useState(false)
      const [writeTag, setWriteTag] = React.useState(false)
      const [tagName, setTagName] = React.useState('')
      const running = busy === 'today-new'
      const runningSeason = busy === 'season-new'
      const submit = () => call('today-new', 'today-new', {
        input,
        n: n.trim() === '' ? undefined : Number(n),
        season,
        noLlmRank,
        noSenseCheck: fast,
        noSenseRepair: fast,
        // 默认真写：勾选=true，取消勾选才显式演练（false）。
        commit,
        ...llmArgsFrom(llmChoice),
      })
      const submitSeason = () => call('season-new', 'season-new', {
        input,
        jitenMax: jitenMax.trim() === '' ? undefined : Number(jitenMax),
        workJitenMin: workJitenMin.trim() === '' ? undefined : Number(workJitenMin),
        workJitenMax: workJitenMax.trim() === '' ? undefined : Number(workJitenMax),
        workMinCount: workMinCount.trim() === '' ? undefined : Number(workMinCount),
        minWords: minWords.trim() === '' ? undefined : Number(minWords),
        maxWords: maxWords.trim() === '' ? undefined : Number(maxWords),
        includeNames,
        tag: tagName.trim(),
        // 新功能默认只出清单；勾选后才写季标签。
        commit: writeTag,
      })
      return h('section', { className: 'anki-card' },
        tabbed ? null : h('h3', null, t('card.todayNew.title')),
        h('p', null, t('card.todayNew.desc')),
        h('div', { className: 'anki-card-body' },
          h(PathField, {
            t,
            value: input,
            placeholder: t('card.todayNew.input'),
            onBrowse: () => setPicking(true),
            onClear: () => setInput(''),
          }),
          h(PathPicker, {
            t,
            open: picking,
            mode: 'any',
            accept: SUBTITLE_EXTS,
            initialPath: input,
            onPick: (paths) => setInput(paths[0] || ''),
            onClose: () => setPicking(false),
          }),
          h('div', { className: 'anki-row' },
            h('input', {
              className: 'anki-input',
              style: { width: '100px' },
              placeholder: t('card.todayNew.n'),
              value: n,
              inputMode: 'numeric',
              onChange: (event) => setN(event.target.value),
            }),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: season, onChange: (event) => setSeason(event.target.checked) }),
              t('card.todayNew.season'),
            ),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: noLlmRank, onChange: (event) => setNoLlmRank(event.target.checked) }),
              t('card.todayNew.noLlmRank'),
            ),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: fast, onChange: (event) => setFast(event.target.checked) }),
              t('card.todayNew.fast'),
            ),
          ),
          h('label', { className: 'anki-check' },
            h('input', { type: 'checkbox', checked: commit, onChange: (event) => setCommit(event.target.checked) }),
            t('card.todayNew.commit'),
          ),
          h(LlmModelSelect, { t, data: llmModels, value: llmChoice || '', onChange: setLlmChoice }),
          h('div', { className: 'anki-row' },
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: busy !== '' || input.trim() === '',
              onClick: submit,
            }, running ? t('common.working') : t('card.todayNew.run')),
          ),
          h(ResultBlock, { t, name: 'today-new', value: result }),
          h('div', { className: 'anki-section' },
            h('h5', null, t('card.seasonNew.title')),
            h('p', null, t('card.seasonNew.desc')),
            h('div', { className: 'anki-row' },
              h('input', {
                className: 'anki-input',
                style: { width: '118px' },
                placeholder: t('card.seasonNew.jitenMax'),
                value: jitenMax,
                inputMode: 'numeric',
                onChange: (event) => setJitenMax(event.target.value),
              }),
              h('input', {
                className: 'anki-input',
                style: { width: '118px' },
                placeholder: t('card.seasonNew.workJitenMax'),
                value: workJitenMax,
                inputMode: 'numeric',
                onChange: (event) => setWorkJitenMax(event.target.value),
              }),
              h('input', {
                className: 'anki-input',
                style: { width: '118px' },
                placeholder: t('card.seasonNew.workMinCount'),
                value: workMinCount,
                inputMode: 'numeric',
                onChange: (event) => setWorkMinCount(event.target.value),
              })),
            h('div', { className: 'anki-row' },
              h('input', {
                className: 'anki-input',
                style: { width: '96px' },
                placeholder: t('card.seasonNew.workJitenMin'),
                value: workJitenMin,
                inputMode: 'numeric',
                onChange: (event) => setWorkJitenMin(event.target.value),
              }),
              h('input', {
                className: 'anki-input',
                style: { width: '96px' },
                placeholder: t('card.seasonNew.minWords'),
                value: minWords,
                inputMode: 'numeric',
                onChange: (event) => setMinWords(event.target.value),
              }),
              h('input', {
                className: 'anki-input',
                style: { width: '96px' },
                placeholder: t('card.seasonNew.maxWords'),
                value: maxWords,
                inputMode: 'numeric',
                onChange: (event) => setMaxWords(event.target.value),
              })),
            h('div', { className: 'anki-row' },
              h('input', {
                className: 'anki-input',
                style: { flex: '1', minWidth: '160px' },
                placeholder: t('card.seasonNew.tag'),
                value: tagName,
                onChange: (event) => setTagName(event.target.value),
              })),
            h('div', { className: 'anki-row' },
              h('label', { className: 'anki-check' },
                h('input', { type: 'checkbox', checked: includeNames, onChange: (event) => setIncludeNames(event.target.checked) }),
                t('card.seasonNew.includeNames'),
              ),
              h('label', { className: 'anki-check' },
                h('input', { type: 'checkbox', checked: writeTag, onChange: (event) => setWriteTag(event.target.checked) }),
                t('card.seasonNew.writeTag'),
              )),
            h('div', { className: 'anki-row' },
              h('button', {
                type: 'button',
                className: 'anki-btn',
                disabled: busy !== '' || input.trim() === '',
                onClick: submitSeason,
              }, runningSeason ? t('common.working') : t('card.seasonNew.run'))),
            h(ResultBlock, { t, name: 'season-new', value: seasonResult })),
        ),
      )
    }

    function CoverCard(props) {
      const { t, call, busy, result, tabbed } = props
      const [text, setText] = React.useState('')
      const [paths, setPaths] = React.useState([])
      const [picking, setPicking] = React.useState(false)
      const [top, setTop] = React.useState('30')
      const [screen, setScreen] = React.useState(false)
      const running = busy === 'vocab-cover'
      const submit = () => call('vocab-cover', 'vocab-cover', {
        text,
        paths,
        top: top.trim() === '' ? undefined : Number(top),
        screen,
      })
      return h('section', { className: 'anki-card' },
        tabbed ? null : h('h3', null, t('card.cover.title')),
        h('p', null, t('card.cover.desc')),
        h('div', { className: 'anki-card-body' },
          h('textarea', {
            className: 'anki-textarea',
            placeholder: t('card.cover.text'),
            value: text,
            onChange: (event) => setText(event.target.value),
          }),
          h(PathField, {
            t,
            values: paths,
            placeholder: t('card.cover.paths'),
            onBrowse: () => setPicking(true),
            onRemove: (path) => setPaths((previous) => previous.filter((item) => item !== path)),
          }),
          h(PathPicker, {
            t,
            open: picking,
            mode: 'files',
            accept: SUBTITLE_EXTS,
            initialPath: paths.length > 0 && paths[0].includes('/') ? paths[0].slice(0, paths[0].lastIndexOf('/')) : '',
            onPick: (picked) => setPaths((previous) => Array.from(new Set(previous.concat(picked)))),
            onClose: () => setPicking(false),
          }),
          h('div', { className: 'anki-row' },
            h('input', {
              className: 'anki-input',
              style: { width: '100px' },
              placeholder: t('card.cover.top'),
              value: top,
              inputMode: 'numeric',
              onChange: (event) => setTop(event.target.value),
            }),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: screen, onChange: (event) => setScreen(event.target.checked) }),
              t('card.cover.screen'),
            ),
          ),
          h('div', { className: 'anki-row' },
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: busy !== '' || (text.trim() === '' && paths.length === 0),
              onClick: submit,
            }, running ? t('common.working') : t('card.cover.run')),
          ),
          h(ResultBlock, { t, name: 'vocab-cover', value: result }),
        ),
      )
    }

    function reportNumber(source, key) {
      const value = source == null ? null : source[key]
      return typeof value === 'number' && Number.isFinite(value) ? value : null
    }

    function reportRatio(value) {
      if (typeof value !== 'number' || !Number.isFinite(value)) return null
      const ratio = value > 1 ? value / 100 : value
      return Math.max(0, Math.min(1, ratio))
    }

    /**
     * Render the monthly ankiR JSON as data, not as a raw dump. The same
     * `output/reports/ankir/monthly-YYYY-MM.json` file feeds the agent tool,
     * so this view is just a read-only presentation of the Python output.
     */
    function ReportResult(props) {
      const { t, value } = props
      let report = null
      if (value != null && value.report != null && typeof value.report === 'object' && !Array.isArray(value.report)) {
        report = value.report
      } else if (value != null && typeof value === 'object' &&
        (typeof value.total_cards === 'number' || (value.stats != null && typeof value.stats === 'object'))) {
        report = value
      }
      const stats = report != null && report.stats != null && typeof report.stats === 'object'
        ? report.stats
        : report
      const error = value == null ? null : (value.parseError || value.error || null)
      const note = value != null && value.skipped === true
        ? (value.reason || t('card.report.exists'))
        : null

      if (stats == null || typeof stats !== 'object' || Array.isArray(stats)) {
        return h('div', { className: 'anki-report' },
          note == null ? null : h('div', { className: 'anki-meta' }, note),
          error == null ? null : h('div', { className: 'anki-fail' }, t('report.failed') + '：' + error),
          h('div', { className: 'anki-report-empty' },
            h('div', null, t('report.empty')),
            h('div', null, t('report.emptyHint')),
          ),
          value != null && value.reportPath != null
            ? h('div', { className: 'anki-report-meta' }, t('report.path') + '：' + value.reportPath)
            : null,
        )
      }

      const total = reportNumber(stats, 'total_cards')
      const retentionRatio = reportRatio(stats.retention_rate)
      const matureRatio = reportRatio(stats.mature_percent) != null
        ? reportRatio(stats.mature_percent)
        : (total != null && total > 0 && reportNumber(stats, 'mature_cards') != null
          ? reportNumber(stats, 'mature_cards') / total
          : null)
      const youngRatio = matureRatio == null ? null : Math.max(0, 1 - matureRatio)
      const totalReviews = reportNumber(stats, 'total_reviews')
      const daysStudied = reportNumber(stats, 'days_studied')
      const avgReviews = reportNumber(stats, 'avg_reviews_per_day')
      const currentStreak = reportNumber(stats, 'current_streak')
      const longestStreak = reportNumber(stats, 'longest_streak')
      const hours = reportNumber(stats, 'total_time_hours')
      const firstReview = stats.first_review == null ? null : String(stats.first_review)
      const lastReview = stats.last_review == null ? null : String(stats.last_review)
      const month = (value != null && value.month) || (report != null && report.month) || null

      const kpis = []
      const addKpi = (label, number, title, suffix) => {
        if (number == null) return
        kpis.push(h(Kpi, {
          key: label,
          label,
          title: title || '',
          value: numberText(number, '—') + (suffix || ''),
        }))
      }
      addKpi(t('report.totalCards'), total)
      addKpi(t('report.totalNotes'), reportNumber(stats, 'total_notes'))
      addKpi(t('report.totalDecks'), reportNumber(stats, 'total_decks'))
      addKpi(t('report.totalReviews'), totalReviews)
      addKpi(t('report.daysStudied'), daysStudied)
      addKpi(t('report.avgReviews'), avgReviews)
      addKpi(t('report.streak'), currentStreak,
        longestStreak == null ? '' : t('report.longest') + ' ' + numberText(longestStreak))
      addKpi(t('report.hours'), hours, '', t('report.hourUnit'))

      const composition = [
        { key: 'new_cards', label: 'report.newCards' },
        { key: 'review_cards', label: 'report.reviewCards' },
        { key: 'learning_cards', label: 'report.learningCards' },
        { key: 'suspended_cards', label: 'report.suspended' },
        { key: 'buried_cards', label: 'report.buried' },
      ].map((row) => {
        const count = reportNumber(stats, row.key)
        if (count == null) return null
        return h('div', { className: 'anki-report-row', key: row.key },
          h('span', { className: 'anki-metric-label' }, t(row.label)),
          h('span', { className: 'anki-bar' },
            h('i', { style: { width: barWidth(total != null && total > 0 ? count / total : 0) } })),
          h('b', null, numberText(count)),
        )
      }).filter(Boolean)

      const metaBits = []
      if (value != null && value.reportPath != null) metaBits.push(t('report.path') + '：' + value.reportPath)
      const sizeBytes = value == null ? null : (value.bytes != null ? value.bytes : value.reportBytes)
      if (sizeBytes != null) metaBits.push(t('report.size') + '：' + numberText(sizeBytes) + ' B')
      const fileTime = value == null ? null : (value.mtime != null ? value.mtime : value.reportMtime)
      if (fileTime != null) metaBits.push(t('report.generated') + '：' + fmtTime(fileTime))

      return h('div', { className: 'anki-report' },
        note == null ? null : h('div', { className: 'anki-meta' }, note),
        error == null ? null : h('div', { className: 'anki-fail' }, t('report.failed') + '：' + error),
        h('div', { className: 'anki-report-hero' },
          h('div', { className: 'anki-hero' },
            h('strong', null, ratioText(retentionRatio)),
            h('span', null, t('report.retention'))),
          h('div', { className: 'anki-report-meta' },
            t('report.dataThrough') + ' ' + (lastReview || '—') +
            (month == null ? '' : ' · ' + t('report.month') + ' ' + month)),
        ),
        kpis.length === 0 ? null : h('div', { className: 'anki-report-kpis' }, kpis),
        matureRatio == null ? null : h(ResultSection, { title: t('report.maturity') },
          h('div', { className: 'anki-report-split' },
            h('i', { className: 'mature', style: { width: barWidth(matureRatio) } }),
            h('i', { className: 'young', style: { width: barWidth(youngRatio) } }),
          ),
          h('div', { className: 'anki-report-legend' },
            h('span', null,
              h('i', { style: { background: 'var(--dsw-alias-brand-primary)' } }),
              t('report.mature') + ' ' + numberText(reportNumber(stats, 'mature_cards')) +
              (matureRatio == null ? '' : ' · ' + ratioText(matureRatio))),
            h('span', null,
              h('i', { style: { background: 'var(--dsw-alias-state-warn-primary)' } }),
              t('report.young') + ' ' + numberText(reportNumber(stats, 'young_cards')) +
              (youngRatio == null ? '' : ' · ' + ratioText(youngRatio))),
          ),
        ),
        composition.length === 0 ? null : h(ResultSection, { title: t('report.composition') },
          h('div', { className: 'anki-rows' }, composition),
        ),
        firstReview == null && lastReview == null ? null : h(ResultSection, { title: t('report.range') },
          h('div', { className: 'anki-rows' },
            h('div', { className: 'anki-rowline' },
              t('report.firstReview') + '：', h('b', null, firstReview || '—')),
            h('div', { className: 'anki-rowline' },
              t('report.lastReview') + '：', h('b', null, lastReview || '—')),
          ),
        ),
        metaBits.length === 0 ? null : h('div', { className: 'anki-report-meta' }, metaBits.join(' · ')),
        h('details', { className: 'anki-report-raw' },
          h('summary', null, t('report.raw')),
          h('pre', { className: 'anki-out' }, JSON.stringify(report, null, 2)),
        ),
      )
    }

    function ReportCard(props) {
      const { t, call, busy, result, reportSnapshot, snapshot, tabbed } = props
      const [force, setForce] = React.useState(false)
      const running = busy === 'study-report'
      const info = reportSnapshot || (snapshot && snapshot.monthlyReport) || null
      const statusText = info == null
        ? ''
        : info.exists
          ? t('card.report.exists') + ' · ' + (info.reportPath || info.path || '')
          : t('card.report.missing')

      const view = Object.assign({}, reportSnapshot || {})
      if (result != null) {
        Object.assign(view, result)
        if (view.report == null && reportSnapshot != null && reportSnapshot.report != null) {
          view.report = reportSnapshot.report
        }
      }

      return h('section', { className: 'anki-card' },
        h('div', { className: 'anki-row between' },
          tabbed ? null : h('h3', null, t('card.report.title')),
          statusText === '' ? null : h('div', { className: 'anki-meta' }, statusText),
        ),
        h('p', null, t('card.report.desc')),
        h('div', { className: 'anki-card-body' },
          h('div', { className: 'anki-row' },
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: force, onChange: (event) => setForce(event.target.checked) }),
              t('card.report.force'),
            ),
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: busy !== '',
              onClick: () => call('study-report', 'study-report', { force }),
            }, running ? t('common.working') : t('card.report.run')),
          ),
          h(ReportResult, { t, value: view }),
        ),
      )
    }

    function WordAudioCard(props) {
      const { t, call, busy, result, tabbed } = props
      const [word, setWord] = React.useState('')
      const [commit, setCommit] = React.useState(true)
      const [force, setForce] = React.useState(false)
      const [selected, setSelected] = React.useState({})
      const planValue = result && result.phase === 'plan' ? result : null
      const applyValue = result && result.phase === 'apply' ? result : null
      const candidates = planValue && Array.isArray(planValue.candidates) ? planValue.candidates : []
      const runningPlan = busy === 'word-audio-plan'
      const runningApply = busy === 'word-audio-apply'
      const anyRunning = busy !== ''

      const toggle = (index) => {
        setSelected((prev) => {
          const next = Object.assign({}, prev)
          if (next[index]) delete next[index]
          else next[index] = true
          return next
        })
      }

      const selectedCount = Object.keys(selected).length

      const doPlan = () => {
        if (word.trim() === '') return
        call('word-audio', 'word-audio', { word: word.trim(), phase: 'plan' }, 'word-audio-plan')
      }

      const doApply = () => {
        const ids = []
        for (let i = 0; i < candidates.length; i += 1) {
          if (selected[i]) ids.push(i)
        }
        if (ids.length === 0) return
        call('word-audio', 'word-audio', {
          word: word.trim(),
          phase: 'apply',
          commit,
          force,
          candidateIndices: ids,
        }, 'word-audio-apply')
      }

      return h('section', { className: 'anki-card' },
        tabbed ? null : h('h3', null, t('card.wordAudio.title')),
        h('p', null, t('card.wordAudio.desc')),
        h('div', { className: 'anki-card-body' },
          h('input', {
            className: 'anki-input',
            placeholder: t('card.wordAudio.word'),
            value: word,
            onChange: (event) => setWord(event.target.value),
            onKeyDown: (event) => { if (event.key === 'Enter') doPlan() },
          }),
          h('div', { className: 'anki-row' },
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: anyRunning || word.trim() === '',
              onClick: doPlan,
            }, runningPlan ? t('common.working') : t('card.wordAudio.plan')),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: commit, onChange: (event) => setCommit(event.target.checked) }),
              t('card.wordAudio.commit'),
            ),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: force, onChange: (event) => setForce(event.target.checked) }),
              t('card.wordAudio.force'),
            ),
          ),
          candidates.length > 0
            ? h('div', { className: 'anki-section' },
                h('h5', null, t('wordAudio.candidates') + '（' + candidates.length + '）'),
                h('div', { className: 'anki-candlist' },
                  candidates.map((cand, index) => {
                    const checked = !!selected[index]
                    return h('div', { className: 'anki-cand', key: 'cand' + index },
                      h('div', { className: 'anki-cand-head' },
                        h('label', { className: 'anki-cand-check' },
                          h('input', {
                            type: 'checkbox',
                            checked,
                            onChange: () => toggle(index),
                          }),
                          cand.reading ? h('span', { className: 'anki-cand-reading' }, cand.reading) : null),
                        h('span', { className: 'anki-cand-word' }, cand.word)),
                      h('div', { className: 'anki-cand-audio' },
                        h(Tag, {
                          label: t('wordAudio.wordAudio'),
                          value: cand.wordAudioEmpty ? t('wordAudio.empty') : (cand.wordAudio || t('wordAudio.has')),
                          dim: cand.wordAudioEmpty,
                        }),
                        h(Tag, {
                          label: t('wordAudio.sentenceAudio'),
                          value: cand.sentenceAudioEmpty ? t('wordAudio.empty') : (cand.sentenceAudio || t('wordAudio.has')),
                          dim: cand.sentenceAudioEmpty,
                        }),
                      ),
                    )
                  })),
                h('div', { className: 'anki-row', style: { marginTop: '8px' } },
                  h('button', {
                    type: 'button',
                    className: 'anki-btn',
                    disabled: anyRunning || selectedCount === 0,
                    onClick: doApply,
                  }, runningApply ? t('common.working') : t('card.wordAudio.apply') + (selectedCount > 0 ? '（' + selectedCount + '）' : '')),
                ))
            : null,
          planValue != null && candidates.length === 0
            ? h('div', { className: 'anki-meta' }, t('wordAudio.none'))
            : null,
          applyValue != null
            ? h(ResultBlock, { t, name: 'word-audio', value: applyValue })
            : null,
        ),
      )
    }

    // 卡片修正 · 生成结果视图：每张卡 noteId + 生成值；失败/演练状态一行 meta，
    // value.output（脚本原始输出）折叠在 details 里。html 与 ainote 结果复用同一组件。
    function CardFixResult(props) {
      const { t, value } = props
      if (value == null) return null
      const cards = Array.isArray(value.cards) ? value.cards : []
      const failedRun = value.ok === false || (value.exitCode != null && value.exitCode !== 0)
      const bits = []
      bits.push(failedRun ? t('card.fix.failed') : (value.commit === false ? t('result.dryRun') : t('result.committed')))
      if (Array.isArray(value.noteIds) && value.noteIds.length > 0) bits.push('noteIds: ' + value.noteIds.join(', '))
      if (value.verified) bits.push('回读校验通过')
      if (value.note) bits.push(value.note)
      const errorText = value.error || ''
      return h('div', { className: 'anki-result' },
        h('div', { className: 'anki-meta' }, bits.join(' · ')),
        failedRun && errorText !== '' ? h('div', { className: 'anki-fail' }, errorText) : null,
        cards.length === 0
          ? h('div', { className: 'anki-meta' }, t('card.fix.noValue'))
          : h(ResultSection, { title: t('card.fix.generated') },
              h('div', { className: 'anki-rows' }, cards.map(function (row, index) {
                return h('div', { className: 'anki-fixprev', key: 'fix' + index },
                  h('div', { className: 'anki-rowline' }, h('b', null, String(row.noteId))),
                  row.value
                    ? h('pre', { className: 'anki-out' }, truncate(row.value, 4000))
                    : h('div', { className: 'anki-meta' }, t('card.fix.noValue')))
              }))),
        value.output
          ? h('details', null,
              h('summary', null, t('card.fix.output')),
              h('pre', { className: 'anki-out' }, truncate(value.output, 6000)))
          : null,
      )
    }

    // 卡片修正 · 右列：按单词名查例句卡 → 选卡预览 → 按 Sentence 重新生成字段。
    // 两个按钮各管一个字段：card-fix-html（Sentence HTML）与 card-fix-ainote（AINote）。
    function FieldFixCard(props) {
      const { t, call, busy, lookupValue, htmlValue, ainoteValue } = props
      const [wordText, setWordText] = React.useState('')
      const [commit, setCommit] = React.useState(true)
      const [selectedIndex, setSelectedIndex] = React.useState(0)
      const candidates = lookupValue && Array.isArray(lookupValue.cards) ? lookupValue.cards : []
      // 候选表变化后旧下标可能越界，钳到有效范围。
      const safeIndex = candidates.length > 0
        ? Math.min(Math.max(selectedIndex, 0), candidates.length - 1)
        : 0
      const selectedCard = candidates.length > 0 ? candidates[safeIndex] : null
      const runningLookup = busy === 'card-lookup'
      const runningHtml = busy === 'card-fix-html'
      const runningAinote = busy === 'card-fix-ainote'
      const anyRunning = busy !== ''

      const doLookup = () => {
        if (wordText.trim() === '') return
        call('card-lookup', 'card-lookup', { word: wordText.trim() }, 'card-lookup')
      }

      const doHtml = () => {
        if (selectedCard == null) return
        call('card-fix-html', 'card-fix', {
          noteIds: [String(selectedCard.noteId)],
          field: 'html',
          commit,
        }, 'card-fix-html')
      }

      const doAinote = () => {
        if (selectedCard == null) return
        call('card-fix-ainote', 'card-fix', {
          noteIds: [String(selectedCard.noteId)],
          field: 'ainote',
          commit,
        }, 'card-fix-ainote')
      }

      return h('section', { className: 'anki-card' },
        h('h3', null, t('card.fix.title')),
        h('p', null, t('card.fix.desc')),
        h('div', { className: 'anki-card-body' },
          h('input', {
            className: 'anki-input',
            placeholder: t('card.fix.wordInput'),
            value: wordText,
            onChange: (event) => setWordText(event.target.value),
            onKeyDown: (event) => { if (event.key === 'Enter') doLookup() },
          }),
          h('div', { className: 'anki-row' },
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: anyRunning || wordText.trim() === '',
              onClick: doLookup,
            }, runningLookup ? t('common.working') : t('card.fix.lookup')),
            h('label', { className: 'anki-check' },
              h('input', { type: 'checkbox', checked: commit, onChange: (event) => setCommit(event.target.checked) }),
              t('card.fix.commit'),
            ),
          ),
          lookupValue != null && candidates.length === 0
            ? h('div', { className: 'anki-meta' },
                lookupValue.note || lookupValue.error || t('card.fix.none'))
            : null,
          candidates.length > 0
            ? h('div', { className: 'anki-section' },
                h('h5', null, t('card.fix.cards') + '（' + candidates.length + '）'),
                h('select', {
                  className: 'anki-select',
                  value: String(safeIndex),
                  onChange: (event) => setSelectedIndex(Number(event.target.value) || 0),
                }, candidates.map(function (cand, index) {
                  return h('option', { key: 'fix' + index, value: String(index) },
                    cand.noteId + ' · ' + (cand.word || '') + ' · ' + (cand.sentence || ''))
                })),
                selectedCard
                  ? h('div', { className: 'anki-fixprev' },
                      h('div', { className: 'anki-fixprev-sentence' },
                        t('card.fix.sentence') + '：' + (selectedCard.sentence || '')),
                      h('div', { className: 'anki-cand-audio' },
                        h(Tag, { label: t('card.fix.word'), value: selectedCard.word || t('card.fix.empty'), dim: !selectedCard.word }),
                        h(Tag, {
                          label: 'AINote',
                          value: selectedCard.hasAinote ? t('card.fix.has') : t('card.fix.empty'),
                          dim: !selectedCard.hasAinote,
                        }),
                        h(Tag, {
                          label: 'Sentence HTML',
                          value: selectedCard.hasHtml ? t('card.fix.has') : t('card.fix.empty'),
                          dim: !selectedCard.hasHtml,
                        }),
                      ),
                    )
                  : null,
                h('div', { className: 'anki-fixactions' },
                  h('button', {
                    type: 'button',
                    className: 'anki-btn',
                    disabled: anyRunning || selectedCard == null,
                    onClick: doHtml,
                  }, runningHtml ? t('common.working') : t('card.fix.htmlBtn')),
                  h('button', {
                    type: 'button',
                    className: 'anki-btn',
                    disabled: anyRunning || selectedCard == null,
                    onClick: doAinote,
                  }, runningAinote ? t('common.working') : t('card.fix.ainoteBtn')),
                  h('span', { className: 'anki-meta' }, t('card.fix.selectHint')),
                ))
            : null,
          htmlValue != null ? h(CardFixResult, { t, value: htmlValue }) : null,
          ainoteValue != null ? h(CardFixResult, { t, value: ainoteValue }) : null,
        ),
      )
    }

    // 卡片修正 tab：一个单词输入 + 目标 checkbox + 一个「重新生成」按钮。
    // 音频目标查素材生词卡，Sentence HTML / AINote 目标按 Word 在**整库**查
    // （例句卡与词汇卡都算）。同词多张时先列出全部候选：音频默认全选（同 deck
    // 同词形），字段卡默认一张不勾（避免把别的卡一起覆盖），勾选后再点同一个
    // 按钮；整库只有一张可改的卡时直接执行。
    function CardFixCard(props) {
      const { t, call, busy, results } = props
      const r = results || {}
      const [wordText, setWordText] = React.useState('')
      // 三个目标默认**都不勾**（用户 2026-11-13 定）：先想清楚要重做哪个字段，
      // 再动手；一个都没勾时「重新生成」是灰的。默认真写库仍保持 true。
      const [targets, setTargets] = React.useState({ audio: false, html: false, ainote: false })
      const [commit, setCommit] = React.useState(true)
      const [force, setForce] = React.useState(false)
      const [lookup, setLookup] = React.useState(null)
      const [audioChecked, setAudioChecked] = React.useState({})
      const [fieldChecked, setFieldChecked] = React.useState({})
      const anyRunning = busy !== ''
      const running = busy === 'word-audio-plan' || busy === 'word-audio-apply' ||
        busy === 'card-lookup' || busy === 'card-fix-html' || busy === 'card-fix-ainote'
      const hasTarget = targets.audio || targets.html || targets.ainote
      const word = wordText.trim()
      const signature = [word, targets.audio ? 'a' : '', targets.html ? 'h' : '',
        targets.ainote ? 'n' : ''].join('|')

      const toggleTarget = (name) => {
        setTargets((prev) => Object.assign({}, prev, { [name]: !prev[name] }))
        setLookup(null)
      }
      const toggleId = (setter, id) => {
        setter((prev) => {
          const next = Object.assign({}, prev)
          if (next[id]) delete next[id]
          else next[id] = true
          return next
        })
      }
      const checkAll = (rows) => {
        const out = {}
        for (const row of rows) if (row.noteId != null) out[row.noteId] = true
        return out
      }
      const idsFrom = (rows, checked) => rows
        .filter((row) => row.noteId != null && checked[row.noteId])
        .map((row) => row.noteId)

      const doLookup = async (sig, opts) => {
        const found = { key: sig, word: opts.word, audio: [], fields: [] }
        if (opts.audio) {
          const value = await call('word-audio-plan', 'word-audio',
            { word: opts.word, phase: 'plan' }, 'word-audio-plan')
          if (value && Array.isArray(value.candidates)) {
            found.audio = value.candidates.filter((c) => c.noteId != null)
          }
        }
        if (opts.html || opts.ainote) {
          const value = await call('card-lookup', 'card-lookup', { word: opts.word }, 'card-lookup')
          if (value && Array.isArray(value.cards)) found.fields = value.cards
        }
        return found
      }

      const execute = async (found, audioIds, fieldIds) => {
        if (targets.audio && audioIds.length > 0) {
          await call('word-audio-apply', 'word-audio', {
            word: found.word, phase: 'apply', noteIds: audioIds, commit, force,
          }, 'word-audio-apply')
        }
        if (targets.html && fieldIds.length > 0) {
          await call('card-fix-html', 'card-fix', {
            noteIds: fieldIds, field: 'html', commit,
          }, 'card-fix-html')
        }
        if (targets.ainote && fieldIds.length > 0) {
          await call('card-fix-ainote', 'card-fix', {
            noteIds: fieldIds, field: 'ainote', commit,
          }, 'card-fix-ainote')
        }
      }

      const doRun = async () => {
        if (word === '' || !hasTarget) return
        let found = lookup
        let audioIds
        let fieldIds
        if (found == null || found.key !== signature) {
          found = await doLookup(signature, {
            word, audio: targets.audio, html: targets.html, ainote: targets.ainote,
          })
          setLookup(found)
          // 同词命中多张字段卡时**一张都不预选**：预选全部再点一次
          // 「重新生成」会把每张都覆盖掉（2026-11-13 的 bug 就是这么写错卡的：
          // 張る 同时挂在例句卡和词汇卡上，一张候选时直接写进了例句卡）。
          // 音频候选仍全选（同一个 deck、同一个词形，行为不变）。
          const pickFields = (targets.html || targets.ainote) && found.fields.length > 1
          const allAudio = checkAll(found.audio)
          const allFields = pickFields ? {} : checkAll(found.fields)
          setAudioChecked(allAudio)
          setFieldChecked(allFields)
          audioIds = idsFrom(found.audio, allAudio)
          fieldIds = idsFrom(found.fields, allFields)
          const needsChoice = (targets.audio && audioIds.length > 1) || pickFields
          if (needsChoice) return
          await execute(found, audioIds, fieldIds)
          return
        }
        audioIds = idsFrom(found.audio, audioChecked)
        fieldIds = idsFrom(found.fields, fieldChecked)
        await execute(found, audioIds, fieldIds)
      }

      const current = lookup != null && lookup.key === signature ? lookup : null
      const audioRows = current ? current.audio : []
      const fieldRows = current ? current.fields : []
      const pickedAudio = audioRows
        .filter((row) => row.noteId != null && audioChecked[row.noteId]).length
      const pickedFields = fieldRows
        .filter((row) => row.noteId != null && fieldChecked[row.noteId]).length
      // 候选都列出来了却一张没勾：按钮置灰并提示先勾卡，不能静默什么都不做。
      const nothingPicked = current != null && pickedAudio + pickedFields === 0
      const multi = current != null && (
        (targets.audio && audioRows.length > 1) ||
        ((targets.html || targets.ainote) && fieldRows.length > 1)
      )
      const audioApply = r['word-audio-apply']
      const audioPlan = r['word-audio-plan']

      return h('section', { className: 'anki-card' },
        h('h3', null, t('card.fix.title')),
        h('p', null, t('card.fix.desc')),
        h('div', { className: 'anki-card-body' },
          h('input', {
            className: 'anki-input',
            placeholder: t('card.fix.wordInput'),
            title: t('card.fix.wordTip'),
            value: wordText,
            onChange: (event) => { setWordText(event.target.value); setLookup(null) },
            onKeyDown: (event) => { if (event.key === 'Enter') doRun() },
          }),
          h('div', { className: 'anki-fixactions' },
            h('label', { className: 'anki-check', title: t('card.fix.audioTip') },
              h('input', { type: 'checkbox', title: t('card.fix.audioTip'), checked: targets.audio, onChange: () => toggleTarget('audio') }),
              t('card.fix.audio')),
            h('label', { className: 'anki-check', title: t('card.fix.htmlTip') },
              h('input', { type: 'checkbox', title: t('card.fix.htmlTip'), checked: targets.html, onChange: () => toggleTarget('html') }),
              'Sentence HTML'),
            h('label', { className: 'anki-check', title: t('card.fix.ainoteTip') },
              h('input', { type: 'checkbox', title: t('card.fix.ainoteTip'), checked: targets.ainote, onChange: () => toggleTarget('ainote') }),
              'AINote'),
          ),
          h('div', { className: 'anki-fixactions' },
            h('button', {
              type: 'button',
              className: 'anki-btn',
              title: t('card.fix.runTip'),
              disabled: anyRunning || word === '' || !hasTarget || nothingPicked,
              onClick: doRun,
            }, running ? t('common.working') : t('card.fix.run')),
            h('label', { className: 'anki-check', title: t('card.fix.commitTip') },
              h('input', { type: 'checkbox', checked: commit, onChange: (event) => setCommit(event.target.checked) }),
              t('card.fix.commit')),
            targets.audio
              ? h('label', { className: 'anki-check', title: t('card.fix.forceTip') },
                  h('input', { type: 'checkbox', checked: force, onChange: (event) => setForce(event.target.checked) }),
                  t('card.fix.force'))
              : null,
          ),
          word === '' || hasTarget
            ? null
            : h('div', { className: 'anki-meta' }, t('card.fix.needTarget')),
          multi
            ? h('div', { className: 'anki-meta' }, t('card.fix.multiHint'))
            : null,
          nothingPicked
            ? h('div', { className: 'anki-meta' }, t('card.fix.pickFirst'))
            : null,
          current == null ? null : h('div', { className: 'anki-section' },
            targetHintRows(t, targets, current, audioRows, fieldRows),
            audioRows.length === 0 ? null : h('div', null,
              h('h5', null, t('card.fix.audioCandidates') + '（' + audioRows.length + '）'),
              h('div', { className: 'anki-candlist' }, audioRows.map((cand) => h('div', { className: 'anki-cand', key: 'a' + cand.noteId },
                h('div', { className: 'anki-cand-head' },
                  h('label', { className: 'anki-cand-check', title: t('card.fix.pickTip') },
                    h('input', {
                      type: 'checkbox',
                      checked: !!audioChecked[cand.noteId],
                      onChange: () => toggleId(setAudioChecked, cand.noteId),
                    }),
                    cand.reading ? h('span', { className: 'anki-cand-reading' }, cand.reading) : null),
                  h('span', { className: 'anki-cand-word' }, cand.word)),
                h('div', { className: 'anki-cand-audio' },
                  h(Tag, {
                    label: t('wordAudio.wordAudio'),
                    value: cand.wordAudioEmpty ? t('wordAudio.empty') : (cand.wordAudio || t('wordAudio.has')),
                    dim: cand.wordAudioEmpty,
                  }),
                  h(Tag, {
                    label: t('wordAudio.sentenceAudio'),
                    value: cand.sentenceAudioEmpty ? t('wordAudio.empty') : (cand.sentenceAudio || t('wordAudio.has')),
                    dim: cand.sentenceAudioEmpty,
                  })))))),
            fieldRows.length === 0 ? null : h('div', null,
              h('h5', null, t('card.fix.fieldCandidates') + '（' + fieldRows.length + '）'),
              h('div', { className: 'anki-candlist' }, fieldRows.map((cand) => h('div', { className: 'anki-cand', key: 'f' + cand.noteId },
                h('div', { className: 'anki-cand-head' },
                  h('label', { className: 'anki-cand-check', title: t('card.fix.pickTip') },
                    h('input', {
                      type: 'checkbox',
                      checked: !!fieldChecked[cand.noteId],
                      onChange: () => toggleId(setFieldChecked, cand.noteId),
                    }),
                    h('span', { className: 'anki-cand-reading' }, cand.word || '')),
                  h('span', { className: 'anki-cand-word' }, cand.noteId)),
                h('div', { className: 'anki-fixprev-sentence' }, cand.sentence || ''),
                // 牌组 + 笔记类型：同一个词在例句 deck 和词汇 deck 各有一张卡时，
                // 只看 noteId / 例句分不清是哪张（历史 bug 就写错了卡）。
                h('div', { className: 'anki-meta' },
                  [cand.deckName, cand.modelName].filter(Boolean).join(' · ')),
                h('div', { className: 'anki-cand-audio' },
                  h(Tag, {
                    label: 'AINote',
                    value: cand.hasAinote ? t('card.fix.has') : t('card.fix.empty'),
                    dim: !cand.hasAinote,
                  }),
                  h(Tag, {
                    label: 'Sentence HTML',
                    value: cand.hasHtml ? t('card.fix.has') : t('card.fix.empty'),
                    dim: !cand.hasHtml,
                  }))))))),
          audioApply != null ? h(ResultBlock, { t, name: 'word-audio', value: audioApply }) : null,
          audioApply == null && audioPlan != null && audioPlan.ok === false
            ? h('div', { className: 'anki-error' }, audioPlan.error || audioPlan.note || '')
            : null,
          r['card-fix-html'] != null ? h(CardFixResult, { t, value: r['card-fix-html'] }) : null,
          r['card-fix-ainote'] != null ? h(CardFixResult, { t, value: r['card-fix-ainote'] }) : null,
        ),
      )
    }

    // 候选为空时给一句目标相关的提示（不要只说「没找到」，用户不知道是哪种卡）。
    function targetHintRows(t, targets, lookup, audioRows, fieldRows) {
      const rows = []
      if (targets.audio && audioRows.length === 0) {
        rows.push(h('div', { className: 'anki-meta', key: 'no-audio' }, t('card.fix.noAudio')))
      }
      if ((targets.html || targets.ainote) && fieldRows.length === 0) {
        rows.push(h('div', { className: 'anki-meta', key: 'no-field' },
          lookup.note || t('card.fix.noFields')))
      }
      return rows
    }

    function TabBar(props) {
      const { t, active, onChange } = props
      return h('div', { className: 'anki-tabs', role: 'tablist', 'aria-label': t('tabs.aria') },
        TABS.map((tab) => h('button', {
          key: tab.id,
          type: 'button',
          role: 'tab',
          id: 'anki-tab-' + tab.id,
          'aria-selected': active === tab.id ? 'true' : 'false',
          'aria-controls': 'anki-panel-' + tab.id,
          className: 'anki-tab' + (active === tab.id ? ' active' : '') + (tab.wide === true ? ' anki-tab-wide' : ''),
          onClick: () => onChange(tab.id),
        }, t(tab.label))))
    }

    function toneForDoctor(doctor) {
      if (doctor == null) return 'idle'
      if (doctor.status === 'green') return 'green'
      if (doctor.status === 'hint') return 'warn'
      if (doctor.status === 'blocked') return 'error'
      return 'error'
    }

    function labelForDoctor(t, doctor) {
      if (doctor == null) return t('status.unknown')
      if (doctor.status === 'green') return t('status.green')
      if (doctor.status === 'hint') return t('status.hint')
      if (doctor.status === 'blocked') return t('status.blocked')
      return t('status.error')
    }

    function AnkiPanel(props) {
      const t = props.t
      const [snapshot, setSnapshot] = React.useState(PANEL_CACHE.snapshot)
      const [loading, setLoading] = React.useState(PANEL_CACHE.snapshot == null)
      const [busy, setBusy] = React.useState('')
      const [error, setError] = React.useState(null)
      const [results, setResults] = React.useState(() => Object.assign({}, PANEL_CACHE.results))
      const resultsRef = React.useRef(PANEL_CACHE.results)
      const [reportSnapshot, setReportSnapshot] = React.useState(PANEL_CACHE.reportSnapshot)
      const [activeTab, setActiveTab] = React.useState(PANEL_CACHE.activeTab)
      const [llmModels, setLlmModels] = React.useState(PANEL_CACHE.llmModels)
      const [llmChoice, setLlmChoiceState] = React.useState(PANEL_CACHE.llmChoice)

      // Mirror the view state into the module cache. The panel can be unmounted
      // at any moment by a sidebar switch, so each committed state is copied.
      React.useEffect(() => { PANEL_CACHE.snapshot = snapshot }, [snapshot])
      React.useEffect(() => {
        resultsRef.current = results
        PANEL_CACHE.results = results
      }, [results])
      React.useEffect(() => {
        const listener = (next) => {
          resultsRef.current = next
          setResults(next)
        }
        PANEL_LISTENERS.add(listener)
        return () => {
          PANEL_LISTENERS.delete(listener)
        }
      }, [])
      React.useEffect(() => { PANEL_CACHE.reportSnapshot = reportSnapshot }, [reportSnapshot])
      React.useEffect(() => { PANEL_CACHE.activeTab = activeTab }, [activeTab])
      React.useEffect(() => { PANEL_CACHE.llmChoice = llmChoice }, [llmChoice])

      const setLlmChoice = (next) => {
        PANEL_CACHE.llmChoice = next
        setLlmChoiceState(next)
      }

      // 模型清单只在面板打开时拉一次（缓存到模块级）；失败也记一次，点刷新可重试。
      React.useEffect(() => {
        if (PANEL_CACHE.llmModels != null) return
        let alive = true
        rpc('llm-models', {}).then((value) => {
          if (!alive) return
          PANEL_CACHE.llmModels = value
          setLlmModels(value)
        }).catch(() => {})
        return () => { alive = false }
      }, [])

      React.useEffect(() => {
        let alive = true
        const load = async () => {
          try {
            const value = await rpc('status', {})
            if (alive) setSnapshot(value)
          } catch (cause) {
            if (alive) setError(String(cause && cause.message ? cause.message : cause))
          } finally {
            if (alive) setLoading(false)
          }
        }
        const loadReport = async () => {
          try {
            const value = await rpc('report', {})
            if (alive) {
              PANEL_CACHE.reportSnapshot = value
              setReportSnapshot(value)
            }
          } catch {
            // The report tab renders its own empty state; a status error is enough.
          }
        }
        load()
        loadReport()
        const timer = setInterval(load, 30000)
        return () => {
          alive = false
          clearInterval(timer)
        }
      }, [])

      const call = async (name, method, args, busyKey) => {
        setBusy(busyKey || name)
        setError(null)
        try {
          const value = await rpc(method, args)
          // Write the cache before React state: a sidebar switch can unmount
          // this panel while the tool is still running, and the next open must
          // still see the finished result.
          const nextResults = Object.assign({}, resultsRef.current, { [name]: value })
          resultsRef.current = nextResults
          publishResults(nextResults)
          if (method === 'refresh') {
            setSnapshot(value)
            rpc('llm-models', {}).then((next) => {
              PANEL_CACHE.llmModels = next
              setLlmModels(next)
            }).catch(() => {})
            rpc('report', {}).then((next) => {
              PANEL_CACHE.reportSnapshot = next
              setReportSnapshot(next)
            }).catch(() => {})
          } else if (method === 'status-now') {
            setSnapshot((previous) => previous ? Object.assign({}, previous, { anki: value, refreshedAt: value.checkedAt }) : previous)
          } else if (method === 'doctor') {
            setSnapshot((previous) => previous ? Object.assign({}, previous, { doctor: value, refreshedAt: value.checkedAt }) : previous)
          } else if (method === 'study-report') {
            if (value != null) {
              PANEL_CACHE.reportSnapshot = value
              setReportSnapshot(value)
            }
            rpc('status', {}).then((next) => setSnapshot(next)).catch(() => {})
          }
          return value
        } catch (cause) {
          setError(String(cause && cause.message ? cause.message : cause))
          return null
        } finally {
          setBusy('')
        }
      }

      const anki = snapshot && snapshot.anki ? snapshot.anki : null
      const doctor = snapshot && snapshot.doctor ? snapshot.doctor : null
      const updated = snapshot && snapshot.refreshedAt ? fmtTime(snapshot.refreshedAt) : '—'

      const changeTab = (next) => {
        PANEL_CACHE.activeTab = next
        setActiveTab(next)
      }

      const panel = (id, node) => h('div', {
        className: 'anki-tabpanel',
        id: 'anki-panel-' + id,
        role: 'tabpanel',
        'aria-labelledby': 'anki-tab-' + id,
        hidden: activeTab !== id,
      }, node)

      const body = loading && snapshot == null
        ? h('div', { className: 'anki-meta' }, t('panel.loading'))
        : h('div', null,
          h(TabBar, { t, active: activeTab, onChange: changeTab }),
          panel('add-example', h(AddExampleCard, {
            t,
            call,
            busy,
            result: results['add-example'],
            tabbed: true,
            llmModels,
            llmChoice,
            setLlmChoice,
          })),
          panel('today-new', h(TodayNewCard, {
            t,
            call,
            busy,
            result: results['today-new'],
            seasonResult: results['season-new'],
            tabbed: true,
            llmModels,
            llmChoice,
            setLlmChoice,
          })),
          panel('vocab-cover', h(CoverCard, {
            t,
            call,
            busy,
            result: results['vocab-cover'],
            tabbed: true,
          })),
          panel('study-report', h(ReportCard, {
            t,
            call,
            busy,
            result: results['study-report'],
            reportSnapshot,
            snapshot,
            tabbed: true,
          })),
          panel('card-fix', h(CardFixCard, {
            t,
            call,
            busy,
            result: results['word-audio'],
            results,
            tabbed: true,
          })),
        )

      return h('div', { className: 'anki-page' },
        h('style', null, CSS),
        h('header', { className: 'anki-head' },
          h('div', null,
            h('div', { className: 'anki-title' }, t('panel.title')),
            h('div', { className: 'anki-sub' }, t('panel.subtitle')),
            h('div', { className: 'anki-updated' }, t('panel.lastUpdated') + ' ' + updated),
          ),
          h('div', { className: 'anki-head-actions' },
            h(StatusCorner, {
              t,
              anki,
              doctor,
              busy,
              updated,
              onAction: (name) => call(name, name, {}),
            }),
            h('button', {
              type: 'button',
              className: 'anki-btn',
              disabled: busy !== '',
              onClick: () => call('refresh', 'refresh', {}),
            }, busy === 'refresh' ? t('common.working') : t('panel.refresh')),
          ),
        ),
        body,
        error == null ? null : h('div', { className: 'anki-error' }, t('panel.error') + '：' + error),
        h('div', { className: 'anki-foot' }, t('common.dryRun')),
      )
    }

    function AnkiIcon(props) {
      const size = props.size || 18
      const active = props.active === true
      return h('svg', {
        className: 'anki-icon',
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        'aria-hidden': true,
        style: { color: active ? 'var(--dsw-alias-brand-primary)' : 'currentColor' },
      },
        h('rect', { x: 4.2, y: 5.4, width: 15.6, height: 13.2, rx: 2.4, fill: active ? 'currentColor' : 'none', stroke: 'currentColor', strokeWidth: 1.6, opacity: active ? 0.18 : 1 }),
        h('path', { d: 'M7.4 9.2h9.2M7.4 12.1h9.2M7.4 15h5.6', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' }),
        h('circle', { cx: 18.2, cy: 6.2, r: 2.1, fill: 'var(--dsw-alias-state-error-primary)' }),
      )
    }

    function apply(ctx) {
      // 'locale' is a hard dependency (see the returned `inject`): the locale
      // plugin provides its service only after its own async bootstrap, so an
      // opportunistic ctx.get('locale') here can still be undefined and would
      // leave every label as a raw translation key. The dynamic fallback below
      // only matters if this plugin was applied before that service appeared.
      let t = (key) => key
      let localeBound = false
      const useLocale = (locale) => {
        if (localeBound || locale === undefined) return
        localeBound = true
        ctx.effect(() => locale.register('anki-workspace', 'en', EN))
        ctx.effect(() => locale.register('anki-workspace', 'zh', ZH))
        t = locale.bind('anki-workspace')
      }

      useLocale(ctx.get('locale'))
      if (!localeBound && typeof ctx.inject === 'function') {
        ctx.inject(['locale'], (inner) => useLocale(inner.get('locale')))
      }

      const slots = ctx.get('slots')
      if (slots === undefined) return

      ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
        name: 'sidebar.panellist',
        id: 'anki-workspace',
        order: 20,
        label: () => t('panel.title'),
      }, AnkiIcon))

      ctx.slots.inject('main', () => ctx.slots.register({
        name: 'main',
        key: 'anki-workspace',
      }, (props) => h(AnkiPanel, Object.assign({}, props, { t }))))
    }

    return {
      // `locale` must be declared here, not read opportunistically in apply:
      // its service is provided after an async bootstrap, and a plain
      // ctx.get('locale') at apply time can still be undefined.
      inject: ['slots', 'locale'],
      apply,
      // 供离线渲染冒烟测试直接调用（ModuleLoader 只读 inject/apply）。
      __components: {
        AnkiPanel: AnkiPanel,
        TodayNewResult: TodayNewResult,
        SeasonNewResult: SeasonNewResult,
        CoverResult: CoverResult,
        ReportResult: ReportResult,
        StatusCorner: StatusCorner,
        TabBar: TabBar,
        WordAudioCard: WordAudioCard,
        CardFixCard: CardFixCard,
        FieldFixCard: FieldFixCard,
        CardFixResult: CardFixResult,
        LlmModelSelect: LlmModelSelect,
        PANEL_CACHE: PANEL_CACHE,
      },
    }
  },
})
