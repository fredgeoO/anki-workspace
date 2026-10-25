# -*- coding: utf-8 -*-
"""单张笔记生成 AINote + Sentence HTML（复用 pipeline 的本地模型流程）。

用法：python code/oneshot/gen_single_note.py <noteId>

流程与批量版一致，只是范围只有一张卡、产出落在独立目录
`data/pipeline/gen_oneshot/<noteId>/output_01.json`（文件名匹配 ruby_engine
repair 的 `output_*.json` 口径），不碰 `data/pipeline/gen` 的批量工作区：

  1) AnkiConnect 取 Sentence / Word / Source；
  2) pipeline.gen_loop（本地模型 + 逐张重问，per_request=1）；
  3) 合格记录写 output_01.json，下一步跑
     python code/common/ruby_engine.py repair --gen <该目录> --write。

退出码：0 = 生成合格；2 = 本地模型没做出来（问题打到 stdout，交强模型收尾）。
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, 'code', 'common'),
           os.path.join(_ROOT, 'code', 'execution')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import anki_api as AK      # noqa: E402
import local_llm as LLM    # noqa: E402
import textio  # noqa: E402,F401  UTF-8 stdio 唯一入口（import 即生效）
import pipeline as P       # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('note_id', type=int)
    a = ap.parse_args()
    nid = a.note_id

    m = AK.notes_map([nid])
    if not m:
        raise SystemExit('找不到笔记 %d' % nid)
    f = AK.field_values(m[nid])
    card = {'noteId': nid, 'sentence': f.get('Sentence', ''),
            'word': f.get('Word', ''), 'source': f.get('Source', '')}
    if not card['sentence'].strip():
        raise SystemExit('这张卡没有 Sentence，无从生成')

    outdir = os.path.join(_ROOT, 'data', 'pipeline', 'gen_oneshot', str(nid))
    os.makedirs(outdir, exist_ok=True)
    json.dump([card], open(os.path.join(outdir, 'input.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    cfg = LLM.load_config()
    print('本地模型：%s @ %s' % (cfg['model'], cfg['base_url']))
    ns = argparse.Namespace(per_request=1, retries=1)
    done, bad, stat = P.gen_loop(ns, cfg, LLM, [card], 1, tag='')
    print('请求 %d 次，prompt %d + completion %d tokens' % stat)

    if nid not in done:
        print('LOCAL_FAILED', json.dumps(
            {k: v for k, v in bad.items()}, ensure_ascii=False))
        return 2

    rec = done[nid]
    out_path = os.path.join(outdir, 'output_01.json')
    json.dump([rec], open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已写出 %s' % os.path.relpath(out_path, _ROOT))
    print('下一步：python code/common/ruby_engine.py repair --gen "%s" --write' % outdir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
