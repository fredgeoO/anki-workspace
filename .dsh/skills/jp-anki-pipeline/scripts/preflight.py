# -*- coding: utf-8 -*-
r"""每集流水线的开工前体检（只读，不改任何东西）。

放在 ``<工作区>/.dsh/skills/jp-anki-pipeline/scripts/`` 下，用工作区自带的 Python 跑::

    & $PY "$WS\.dsh\skills\jp-anki-pipeline\scripts\preflight.py"
    & $PY "$WS\.dsh\skills\jp-anki-pipeline\scripts\preflight.py" --tag "动画::平家物语::第02集"
    & $PY "$WS\.dsh\skills\jp-anki-pipeline\scripts\preflight.py" --cards 157

检查五件事：

  1. AnkiConnect 是否在跑（阶段 1-5 全靠它）
  2. 待清理卡（``tag:待标记``）张数
  3. 本集标签的卡：总张数 / ``AINote`` 为空张数 / 其中判弃张数
     —— **``split`` 的查询是 ``tag:<集标签> AINote:``，不含 is:suspended、也不排除判弃卡**，
     所以"split 会取走多少张"= AINote 为空的张数，可能比真正该生成的多。
     这里直接把两个数字和建议的 ``--batches`` 都算出来。
  4. 阶段二/阶段四工作目录里的**孤儿产出**（manifest 没引用的 ``input_/output_NN.json``）
     —— 换集时上一集的残留会顶替本集同批号的真产出。
  5. 阶段四 ``mine_candidates.json`` 是否比 ``gen_mine/manifest.json`` 新
     —— ``split`` 到 ``write`` 之间这份候选池必须保持不动。

退出码：0 = 可继续；1 = AnkiConnect 连不上（其余检查仍已打印）。
"""
import argparse
import json
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_common():
    """从本脚本往上找 <工作区>/code/common（工作区路径的唯一来源是那里的 paths.py）。"""
    d = _HERE
    for _ in range(8):
        cand = os.path.join(d, 'code', 'common')
        if os.path.isfile(os.path.join(cand, 'paths.py')):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    raise SystemExit('找不到 code/common/paths.py —— 本脚本应放在 '
                     '<工作区>/.dsh/skills/jp-anki-pipeline/scripts/ 下')


sys.path.insert(0, _find_common())
import anki_api as AK        # noqa: E402  唯一的 Anki 访问点
import paths as WSP          # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
sys.path.insert(0, WSP.EXECUTION)
import pipeline as PL        # noqa: E402  只为复用 CFG，import 无副作用

GEN2 = os.path.join(WSP.DATA_PIPELINE, 'gen')   # 阶段二工作目录
GEN4 = os.path.join(WSP.DATA_VOCAB, 'gen_mine')  # 阶段四工作目录
BATCH_RE = re.compile(r'^(?:input|output)_\d+\.json$')
ANKI_TIMEOUT = 20            # 体检要快：连不上就别让它吊着


def count(query):
    return len(AK.find_notes(query))


def suggest(n, per_batch):
    return int(math.ceil(n / float(per_batch))) if n else 0


def orphans(workdir, label):
    """返回 manifest 没引用的批次文件（换集残留）。"""
    man = os.path.join(workdir, 'manifest.json')
    if not os.path.isfile(man):
        return None
    try:
        manifest = json.load(open(man, encoding='utf-8'))
    except Exception as exc:
        print('  [!] %s 的 manifest.json 读不了：%s' % (label, exc))
        return None
    ref = set()
    for b in manifest:
        for k in ('input', 'output'):
            if b.get(k):
                ref.add(b[k])
    have = sorted(f for f in os.listdir(workdir) if BATCH_RE.match(f))
    return manifest, sorted(set(have) - ref)


def main():
    ap = argparse.ArgumentParser(description='流水线开工前体检（只读）')
    ap.add_argument('--tag', help='本集标签，如 动画::平家物语::第02集')
    ap.add_argument('--cards', type=int,
                    help='直接给本集待生成张数（跳过连库统计，纯离线算批次）')
    ap.add_argument('--per-batch', type=int, default=14,
                    help='每批张数，默认 14（阶段二）')
    ap.add_argument('--offline', action='store_true',
                    help='完全不连 Anki，只做 4/5 两项离线检查（Anki 没开时也能跑）')
    ap.add_argument('--list-tags', action='store_true',
                    help='展开全部已有的 动画:: 标签（默认只报数量）')
    a = ap.parse_args()

    pending_tag = PL.CFG['pending_tag']
    drop_tag = PL.CFG['drop_tag']
    deck = PL.CFG['deck']
    problems = []

    # ── 1. AnkiConnect ──────────────────────────────────────────────────────
    print('== 1. AnkiConnect ==')
    live = False
    if a.offline:
        print('  （--offline：跳过 AnkiConnect 检查）')
    else:
        # 体检只要快：单独给 20s 超时（模块默认 300s）
        client = AK.Client(timeout=ANKI_TIMEOUT)
        info = client.health()
        live = info['ok']
        if live:
            print('  [OK] %s 在跑（version=%s）' % (client.url, info['version']))
        else:
            print('  [X] %s' % (info['error'] or '连不上 %s' % client.url))
            print('      → 先启动 Anki。阶段 1-5 全部经 AnkiConnect，不给它开着跑不了。')
            problems.append('AnkiConnect 不可用')

    # ── 2. 待清理卡 ─────────────────────────────────────────────────────────
    print('== 2. 待清理（阶段 1）==')
    if live:
        n_pending = count('tag:%s' % pending_tag)
        n_dropped = count('tag:%s' % drop_tag)
        print('  tag:%s = %d 张；tag:%s = %d 张' % (pending_tag, n_pending, drop_tag, n_dropped))
        if n_pending:
            print('      → & $PY "$EXE\\pipeline.py" triage --query "tag:%s"' % pending_tag)
        else:
            print('      没有待清理的卡（本集大概是走字幕层筛选 filter_subtitle.py，跳过阶段 1）')
    else:
        print('  (跳过：AnkiConnect 不可用)')

    # ── 3. 本集标签 ─────────────────────────────────────────────────────────
    print('== 3. 本集标签 ==')
    if live:
        tags = [t for t in (AK.tags() or []) if t.startswith('动画::')]
        if tags:
            if a.list_tags:
                print('  已有的 动画:: 标签（--tag 必须与其中之一逐字一致）：')
                for t in sorted(tags):
                    print('      %s' % t)
            else:
                print('  已有 %d 个 动画:: 标签（--list-tags 展开；--tag 必须与其中之一逐字一致）'
                      % len(tags))
        else:
            print('  没有 动画:: 开头的标签（ABS 导入的卡还没打集标签？）')

    source_n = a.cards
    if a.tag:
        if live:
            base = 'tag:%s' % a.tag
            total = count(base)
            empty = count('%s AINote:' % base)
            dropped = count('%s tag:%s' % (base, drop_tag))
            keep = count('%s AINote: -tag:%s' % (base, drop_tag))
            print('  tag:%s → 共 %d 张。' % (a.tag, total))
            if empty:
                print('    split 实际会取走（tag + AINote 为空）: %d 张 → --batches %d'
                      % (empty, suggest(empty, a.per_batch)))
            else:
                print('    split 会取走: 0 张（没有 AINote 为空的卡）')
            print('    其中带着判弃标签的: %d 张' % dropped)
            if keep:
                print('    摘掉判弃卡后应生成: %d 张 → --batches %d'
                      % (keep, suggest(keep, a.per_batch)))
            if dropped:
                print('  [WARN] split 的查询是 "tag:<集标签> AINote:"，**不含 is:suspended、'
                      '也不排除判弃卡**。')
                print('         这 %d 张刚被判弃、集标签还在、AINote 还空着的卡会被一起拿去生成。' % dropped)
                print('         要么在浏览器里搜 "tag:%s tag:%s" 把它们移除集标签，' % (a.tag, drop_tag))
                print('         要么干脆改走字幕层筛选（filter_subtitle.py）让阶段 1 无事可做。')
                problems.append('本集有 %d 张判弃卡会被 split 一起取走' % dropped)
            if total == 0:
                problems.append('tag:%s 匹配不到任何卡（--tag 写错了？）' % a.tag)
                print('      → 用 --list-tags 看库里已有的 动画:: 标签，逐字抄一个过来')
            elif empty == 0:
                print('  [i] 本集没有 AINote 为空的卡 —— 阶段二已经做完了；'
                      '直接进阶段 3/4/5（activate.py plan / mine.py scan / mine_audio.py plan）。')
            if a.cards is None:
                source_n = keep if dropped else empty
            else:
                print('  （--cards %d 已给出，批次建议按它算）' % a.cards)
        else:
            print('  (跳过：AnkiConnect 不可用)')
    elif live:
        print('  （没给 --tag，跳过。开工时请带上本集标签）')

    if source_n:
        print('  阶段二批次建议：%d 张 ÷ %d ≈ --batches %d'
              % (source_n, a.per_batch, suggest(source_n, a.per_batch)))

    # ── 4. 孤儿产出 ─────────────────────────────────────────────────────────
    print('== 4. 孤儿产出（换集残留）==')
    for workdir, label in ((GEN2, '阶段二 data/pipeline/gen'),
                           (GEN4, '阶段四 data/vocab/gen_mine')):
        got = orphans(workdir, label)
        if got is None:
            print('  %s：还没有 manifest.json（本集还没 split）' % label)
            continue
        manifest, extra = got
        print('  %s：manifest %d 批；目录里 %s' % (
            label, len(manifest),
            ('干净' if not extra else '多出 %s' % extra)))
        if extra:
            print('     [WARN] 这些文件不属于本集，会在同批号时顶替真产出 → 删掉它们')
            problems.append('%s 有孤儿 %s' % (label, extra))

    # ── 5. 阶段四候选池是否被动过 ────────────────────────────────────────────
    print('== 5. 阶段四候选池 ==')
    cand = os.path.join(WSP.DATA_VOCAB, 'mine_candidates.json')
    man4 = os.path.join(GEN4, 'manifest.json')
    if not os.path.isfile(cand):
        print('  还没有 mine_candidates.json（本集还没 mine.py scan）')
    elif not os.path.isfile(man4):
        print('  mine_candidates.json 在（%s），还没有 gen_mine/manifest.json' % cand)
    elif os.path.getmtime(cand) > os.path.getmtime(man4) + 1:
        print('  [WARN] mine_candidates.json 比 gen_mine/manifest.json 新。')
        print('         split 到 write 之间这份候选池必须保持不动，否则校验按它核对产出会错位。')
        print('         若刚重跑过 scan，请重跑 split 并让子代理重做。')
        problems.append('mine_candidates.json 比 gen_mine 产出新')
    else:
        print('  [OK] mine_candidates.json 未被改动（split 之后保持不动）')

    # ── 小结 ────────────────────────────────────────────────────────────────
    print('== 小结 ==')
    if problems:
        for p in problems:
            print('  [!] %s' % p)
    else:
        print('  没有发现阻塞项，可以开工。')
    print('  下一步见 .dsh/skills/jp-anki-pipeline/SKILL.md 第二节（阶段 0-5）。')

    return 0 if (live or a.offline) else 1


if __name__ == '__main__':
    sys.exit(main())
