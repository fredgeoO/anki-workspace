#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""jimaku_dl.py —— 从 jimaku.cc 按作品+集数下载字幕（默认只要 Netflix 日文字幕）。

用法：
  python jimaku_dl.py --query "Seitokai ni mo Ana wa Aru" --episode 5 --dest "subtitles\\Seitokai ni mo Ana wa Aru!"
  python jimaku_dl.py --entry 12682 --episode 5 --list

退出码：
  0  成功（已下载，或目标文件已存在）
  2  该集在 jimaku 上没有任何字幕文件（尚未入库）
  3  该集有字幕，但没有 Netflix 版本（stdout 列出可用替代，等用户决定）
  4  没有 Netflix 版本且 --any 也未指定 / 未找到条目 —— 需要向用户询问
  1  参数或网络错误

API key 查找顺序：--api-key → $env:DSH_JIMAKU_API_KEY。不要把 key 写进代码或文档。
鉴权是裸 key：Authorization: <key>（加 "Bearer " 前缀会 401）。
"""
import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

# 文本 I/O 唯一入口（AGENTS §3.2）：import 这一下就把 stdio 接管成 UTF-8。
# 本脚本在 <工作区>/.dsh/skills/jimaku-subtitle/scripts/，工作区根 = 上四级。
_WS = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
import textio  # noqa: E402,F401  UTF-8 stdio（幂等）

BASE = 'https://jimaku.cc'
UA = 'anki-workspace-jimaku-fetch/1.0'


def log(msg):
    print(msg, file=sys.stderr)


def api_get(url, key, binary=False):
    req = urllib.request.Request(url, headers={
        'Authorization': key,
        'User-Agent': UA,
        'Accept': 'application/octet-stream' if binary else 'application/json',
    })
    resp = urllib.request.urlopen(req, timeout=60)
    data = resp.read()
    if binary:
        return data
    return json.loads(data.decode('utf-8'))


def norm(s):
    s = unicodedata.normalize('NFKC', s).lower()
    return re.sub(r'[\s!！。.、・·:：;；「」『』“”"\'()（）\[\]【】\-_~〜~]+', '', s)


def find_entry(query, key, entry_id=None):
    if entry_id:
        try:
            return api_get(f'{BASE}/api/entries/{entry_id}', key)
        except urllib.error.HTTPError as e:
            log(f'entry {entry_id} 不存在（HTTP {e.code}）')
            return None
    results = api_get(f'{BASE}/api/entries/search?query={urllib.parse.quote(query)}', key)
    if not results:
        return None
    if len(results) == 1:
        return results[0]
    nq = norm(query)
    for e in results:
        for field in ('name', 'english_name', 'japanese_name'):
            v = e.get(field) or ''
            if norm(v) and (nq in norm(v) or norm(v) in nq):
                return e
    log('多个候选条目（用 --entry <id> 指定）：')
    for e in results:
        log(f"  id={e['id']}  {e.get('name')}  /  {e.get('english_name') or ''}")
    return results[0]


NETFLIX = re.compile(r'netflix', re.I)
JAPANESE = re.compile(r'\u3040-\u309f\u30a0-\u30ff')


def classify(files, episode):
    """返回 (netflix_hits, others)。episode=None 时不过滤集数。"""
    ep_pat = None
    if episode is not None:
        ep = int(episode)
        ep_pat = re.compile(
            rf'(?:S\d{{2}}E{ep:02d}|S\dE{ep}(?!\d)|第\s*0?{ep}\s*[话話話]|(?<![\d-])[-\s _]?{ep:02d}(?![\d])|(?<![\d.\-])[-\s _]{ep}(?![\d]))'
        )
    netflix, others = [], []
    for f in files:
        name = f['name']
        if not name.lower().endswith(('.srt', '.ass', '.vtt')):
            continue
        if ep_pat and not ep_pat.search(name):
            continue
        if NETFLIX.search(name):
            netflix.append(f)
        else:
            others.append(f)
    return netflix, others


def main():
    ap = argparse.ArgumentParser(description='Download Netflix subtitles from jimaku.cc')
    ap.add_argument('--query', help='作品名（罗马字/日文/英文均可，模糊搜索）')
    ap.add_argument('--entry', type=int, help='jimaku entry id（与 --query 二选一）')
    ap.add_argument('--episode', type=int, help='集数（TV 条目必填）')
    ap.add_argument('--dest', required=True, help='保存目录（工作区内）')
    ap.add_argument('--lang', default='ja', help='只保留文件名含该语言标记或含日文字形的文件（默认 ja）')
    ap.add_argument('--any', action='store_true', help='没有 Netflix 版时下载任意日语字幕替代')
    ap.add_argument('--list', action='store_true', help='只列该集可用文件，不下载')
    ap.add_argument('--api-key', help='jimaku API key（默认读 $env:DSH_JIMAKU_API_KEY）')
    args = ap.parse_args()

    key = args.api_key or os.environ.get('DSH_JIMAKU_API_KEY')
    if not key:
        log('缺少 API key：设 DSH_JIMAKU_API_KEY 环境变量或 --api-key')
        return 1
    if not args.query and not args.entry:
        log('需要 --query 或 --entry')
        return 1

    entry = find_entry(args.query or '', key, args.entry)
    if not entry:
        log(f'jimaku 上找不到条目：{args.query!r}')
        return 4
    eid = entry['id']
    log(f"entry {eid}: {entry.get('name')} / {entry.get('english_name') or ''} "
        f"(japanese: {entry.get('japanese_name') or ''})")

    url = f'{BASE}/api/entries/{eid}/files'
    if args.episode is not None and not entry.get('flags', {}).get('movie'):
        url += f'?episode={args.episode}'
    try:
        files = api_get(url, key)
    except Exception as e:
        log(f'files ERR {e}')
        files = []
    # episode 过滤是 best-effort，兜底再拉全量自己匹配
    if not files and args.episode is not None:
        try:
            files_all = api_get(f'{BASE}/api/entries/{eid}/files', key)
        except Exception as e:
            log(f'files ERR {e}')
            return 1
        netflix, others = classify(files_all, args.episode)
    else:
        netflix, others = classify(files, args.episode)

    # 语言过滤：Netflix ja[cc] 或文件名含日文
    def keep(f):
        n = f['name'].lower()
        if args.lang and args.lang != 'any' and f'.{args.lang}' in n.replace('[', '.').replace(']', ''):
            return True
        return bool(JAPANESE.search(f['name']))

    netflix = [f for f in netflix if keep(f)]
    others = [f for f in others if keep(f)]

    if args.list:
        print(json.dumps({'entry': eid, 'netflix': netflix, 'others': others},
                         ensure_ascii=False, indent=1))
        return 0 if (netflix or others) else 2

    if not netflix and not others:
        log(f'第 {args.episode} 集在 jimaku 上还没有任何字幕文件（entry {eid}）。')
        return 2

    dest = __import__('pathlib').Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    picked = netflix
    if not picked:
        if not args.any:
            log(f'第 {args.episode} 集没有 Netflix 字幕。可用替代：')
            for f in others:
                log(f"  {f['name']}  ({f['size']} bytes)")
            log('需要替代请带 --any 重跑，或向用户确认要哪一种。')
            return 3
        picked = others

    saved, skipped = 0, 0
    for f in picked:
        out = dest / f['name']
        if out.exists() and out.stat().st_size == f['size']:
            log(f'skip（已存在）: {out.name}')
            skipped += 1
            continue
        data = api_get(f['url'], key, binary=True)
        out.write_bytes(data)
        ok = 'OK' if len(data) == f['size'] else f"大小不符（{len(data)} != {f['size']}）"
        log(f'saved: {out.name}  {len(data)} bytes  {ok}')
        saved += 1
    print(json.dumps({'entry': eid, 'saved': saved, 'skipped': skipped,
                      'source': 'netflix' if netflix else 'fallback'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
