# -*- coding: utf-8 -*-
"""只读：打印指定 note 的某个字段（默认 AINote）里坏箭头/箭头附近的片段。

用于人工验收——Anki 浏览器开着旧卡片时界面不刷新，别靠肉眼看。

用法::

    python code/oneshot/show_note_field.py --note 1621392136383
    python code/oneshot/show_note_field.py --note 1621392136383 --field "Sentence Translation"
"""
import argparse
import json
import os
import re
import sys
import urllib.request
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）


ANKI_URL = 'http://127.0.0.1:8765'
ARROW = '\u2192'


def invoke(action, **params):
    payload = json.dumps({'action': action, 'version': 6, 'params': params}).encode('utf-8')
    req = urllib.request.Request(ANKI_URL, payload, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as fh:
        res = json.loads(fh.read().decode('utf-8'))
    if res.get('error'):
        raise RuntimeError('%s: %s' % (action, res['error']))
    return res['result']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--note', type=int, required=True)
    ap.add_argument('--field', default='AINote')
    ap.add_argument('--context', type=int, default=90)
    args = ap.parse_args()

    info = invoke('notesInfo', notes=[args.note])[0]
    fields = info.get('fields', {})
    print('note %s  model=%s' % (args.note, info.get('modelName')))
    print('tags:', info.get('tags'))
    if args.field not in fields:
        print('可用字段:', list(fields))
        return
    val = fields[args.field].get('value', '') or ''
    print('字段 %s 长度 %d' % (args.field, len(val)))
    print('残留 ightarrow/\\rightarrow/to 次数: %d'
          % len(re.findall(r'ightarrow|\\+rightarrow|\\+Rightarrow|\\+to(?![A-Za-z])', val)))
    print('→ (U+2192) 个数: %d' % val.count(ARROW))

    pats = [('→', re.compile(re.escape(ARROW))),
            ('LaTeX $…$', re.compile(r'\$[^$\n]{1,40}\$')),
            ('ightarrow', re.compile(r'ightarrow'))]
    for label, rx in pats:
        ms = list(rx.finditer(val))
        if not ms:
            continue
        print('\n-- %s: %d 处' % (label, len(ms)))
        for m in ms[:6]:
            a = max(0, m.start() - args.context)
            b = min(len(val), m.end() + args.context)
            print('  …%s…' % val[a:b].replace('\n', '⏎'))


if __name__ == '__main__':
    main()
