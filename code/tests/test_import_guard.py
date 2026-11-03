# -*- coding: utf-8 -*-
"""回归测试：execution 脚本互相 import 只允许「真流程依赖」（issue #5）。

挡三件事：
1. **新增跨脚本借用**：`import <同级脚本> as Y` 之后取 `Y.attr`，属性必须在白名单里；
   不在就失败 —— 纯文本/假名/文件名这类通用件的家在 `code/common/`，不在隔壁脚本里。
2. **白名单悄悄变宽**：ALLOWED 的键与属性集合逐项比对，多一个键、多一个属性都算回归。
3. **同名不同义**：汉字/假名正则有两套口径（含不含 CJK 扩展 A），两边正本都在 `common/`，
   execution 里不许再手写这两类字符区间。

白名单两类（issue #5 非目标：不追求 execution 之间零 import）：

* **流程依赖**：生成循环、排位置、序号、Jiten 排名口径、已知词判据 —— 都要查库或跑模型。
* **同族模块**：一个能力的「巨石 + 已抽出的纯渲染层」是一对（core6000_example /
  core6000_text·text2·jisho·gates·render，today_new / lesson_check / lesson_text /
  lesson_paths / lesson_render）。巨石 import 自己抽出去的那层
  是为了保住模块级名字（测试与探针脚本仍用 `CE.ruby_word`），不是隔壁借工具。

纯离线：只 parse `code/execution/*.py`，不 import 任何脚本、不连 Anki。
跑法：& $PY code\\tests\\test_import_guard.py
"""
import ast
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
_EXEC = os.path.join(_CODE, 'execution')
sys.path.insert(0, os.path.join(_CODE, 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（common）

#: 允许的流程依赖：(借方文件, 被借脚本) -> 属性集合。多一个就算回归。
ALLOWED = {
    # 生成循环 / 提示词：走模型与落盘，是流程本身
    ("cards.py", "pipeline"): {"gen_loop"},
    ("immersionkit.py", "reposition"): {"reposition"},
    # 已知词判据 / Jiten 排名口径：要查库或读词表，留在执行层
    ("immersionkit.py", "mine"): {"JITEN_NO_RANK", "jiten_rank", "load_jiten_index",
                                  "next_index"},
    ("proper.py", "mine"): {"build_index", "extract_residuals", "hit_inflection",
                            "known_lookups", "next_index"},
    ("reposition.py", "mine"): {"JITEN_NO_RANK"},
    # pipeline 的流程件：读 Anki 或读模型预算，不是纯文本（issue #5 已明确不搬）
    # build_grammar / rebuild_known_index 直连 Anki 与 CFG；
    # fit_groups 的签名要 (cfg, LLM) 并调 LLM.budget/estimate_tokens。
    ("mine.py", "pipeline"): {"build_grammar", "fit_groups", "rebuild_known_index"},
    ("immersionkit.py", "pipeline"): {"rebuild_known_index"},
    ("proper.py", "pipeline"): {"fit_groups"},
}

#: 同族模块：巨石 import 自己抽出去的纯渲染/判定层，保住模块级名字不变。
#: 只认这些配对；别的脚本想走这条路进来要先说明理由。
#: core6000_* 五件是一对（Issue #4「按能力切分」）：巨石 import 自己抽出的
#: text2 / jisho / gates / render 只为保住模块级名字，测试与探针仍用 CE.flatten；
#: lesson_render / lesson_paths 是 today_new 抽出的渲染层与落盘层（同族）。
SAME_FAMILY = {
    ("core6000_example.py", "core6000_text"),
    ("core6000_example.py", "core6000_text2"),
    ("core6000_example.py", "core6000_jisho"),
    ("core6000_example.py", "core6000_gates"),
    ("core6000_example.py", "core6000_render"),
    ("core6000_gates.py", "core6000_text2"),
    ("core6000_gates.py", "core6000_jisho"),
    ("core6000_jisho.py", "core6000_text2"),
    ("core6000_render.py", "core6000_text"),
    ("core6000_render.py", "core6000_text2"),
    ("lesson_check.py", "lesson_text"),
    ("lesson_render.py", "lesson_check"),
    ("lesson_render.py", "lesson_paths"),
    ("lesson_render.py", "lesson_text"),
    ("today_new.py", "lesson_check"),
    ("today_new.py", "lesson_text"),
    ("today_new.py", "lesson_paths"),
    ("today_new.py", "lesson_render"),
}

#: 已有正本的同名/近名正则：execution 里再手写这套字符区间就是第二份口径。
#: KANJI 有两套**都合法**的口径（含不含 CJK 扩展 A），所以窄口径只卡 ruby_text 那份；
#: 假名集在 jp_text / ruby_text 各有一份完全相同的定义，正本收在 jp_text。
DUP_PATTERNS = (
    (r'\[\u4e00-\\u9fff\]', '汉字正则（不含扩展 A）的正本是 common/ruby_text.py::KANJI'),
    (r'\[\u3040-\\u309f\\u30a0-\\u30ff\]', '假名集的正本是 common/jp_text.py::KANA'),
)

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def scripts():
    return {f for f in os.listdir(_EXEC) if f.endswith('.py')}


def edges_for(fname, siblings):
    """解析一个脚本，返回 {(被借脚本, 属性): [行号…]}。

    认两种写法：`import <同级> as Y`（收 `Y.attr`）与 `from <同级> import a, b`（收绑定名）。
    函数体内的 import 也算 —— proper 借 mine_audio 就是在 cmd_audio 里，耦合一样成立。
    """
    path = os.path.join(_EXEC, fname)
    with open(path, encoding='utf-8') as fh:
        tree = ast.parse(fh.read(), filename=path)
    # alias -> (模块名, from-import 的原名或 None)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name in siblings:
                    aliases[al.asname or al.name] = (al.name, None)
        elif isinstance(node, ast.ImportFrom) and node.module in siblings:
            for al in node.names:
                aliases[al.asname or al.name] = (node.module, al.name)
    hits = {}

    def add(mod, attr, lineno):
        hits.setdefault((mod, attr), []).append(lineno)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            got = aliases.get(node.value.id)
            if got and got[1] is None:                 # `import X as Y` → Y.attr
                add(got[0], node.attr, node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module in siblings:
            for al in node.names:                      # `from X import a` 本身就是借 a
                add(node.module, al.name, node.lineno)
    return hits


def collect_edges():
    sib = {f[:-3] for f in scripts()}
    out = {}
    for fname in sorted(scripts()):
        for (mod, attr), lines in edges_for(fname, sib).items():
            out.setdefault((fname, mod), {}).setdefault(attr, []).extend(lines)
    return out


def test_no_new_borrowing():
    print('— execution → execution 借用（白名单外即失败）—')
    edges = collect_edges()
    extra, over = [], []
    for (fname, mod), attrs in sorted(edges.items()):
        key = (fname, mod)
        if key in SAME_FAMILY:
            continue                                # 巨石 import 自己抽出的那层
        if key not in ALLOWED:
            extra.append('%s → %s: %s' % (fname, mod, ', '.join(sorted(attrs))))
            continue
        outside = sorted(set(attrs) - ALLOWED[key])
        if outside:
            over.append('%s → %s: %s' % (fname, mod, ', '.join(outside)))
    check('没有白名单外的跨脚本借用', not extra, '; '.join(extra))
    check('借用的属性都在白名单内', not over, '; '.join(over))


def test_allowlist_not_widened():
    print('— 白名单本身（新增键/属性都要先改这里并说明理由）—')
    edges = collect_edges()
    live = {k for k in ALLOWED if k in edges} | SAME_FAMILY
    missing = sorted(set(ALLOWED) - live)
    check('白名单没有空转的条目', not missing,
          '这些依赖已经不存在的：' + '; '.join('%s → %s' % k for k in missing))


def test_no_duplicate_regex():
    print('— 同名不同义的正则不许在 execution 里再造一份 —')
    hits = []
    for fname in sorted(scripts()):
        path = os.path.join(_EXEC, fname)
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        for ln, line in enumerate(src.splitlines(), 1):
            if 'jp_text' in line or 'ruby_text' in line:
                continue                        # 注释里提正本名字不算
            for pat, why in DUP_PATTERNS:
                if re.search(pat.replace('\\u', '\\\\u'), line):
                    hits.append('%s:%d %s' % (fname, ln, why))
    check('没有重复的汉字/假名字符区间', not hits, '; '.join(hits[:6]))


def main():
    test_no_new_borrowing()
    print()
    test_allowlist_not_widened()
    print()
    test_no_duplicate_regex()
    print()
    if FAIL:
        print('结论：%d 项失败（execution 的跨脚本借用要收进 common/）' % len(FAIL))
        return 1
    print('结论：execution 之间只剩白名单里的流程依赖')
    return 0


if __name__ == '__main__':
    sys.exit(main())
