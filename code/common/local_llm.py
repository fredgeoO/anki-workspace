# -*- coding: utf-8 -*-
"""本地模型客户端的**转发层**（实现唯一正本在全局技能里）。

2026-10-25 收口：`~/.dsh/skills/local-llm/scripts/local_llm.py` 是唯一实现，
本文件只负责把它加载进来，让 `import local_llm` 的老调用方（cards / pipeline /
local_filter / mine / immersionkit…）一行都不用改。

* **不要在这里加逻辑**。改行为去改技能里那份，本文件保持「零实现」。
* 端点/模型/窗口配置走技能的查找链：`<workspace>/.dsh/local-llm.json`（若存在）
  → `~/.dsh/local-llm.json`（机器级正本）。本工作区的工作区级配置已删除。
* 技能装到别处（或 `$DSH_HOME` 不标准）时，用 `$env:LOCAL_LLM_MODULE` 指向正本。
"""
import importlib.util
import os
import sys

_SKILL_SCRIPTS = os.path.join(
    os.environ.get('DSH_HOME') or os.path.join(os.path.expanduser('~'), '.dsh'),
    'skills', 'local-llm', 'scripts')
_IMPL_PATH = os.environ.get('LOCAL_LLM_MODULE') or os.path.join(_SKILL_SCRIPTS, 'local_llm.py')

if not os.path.isfile(_IMPL_PATH):
    raise ImportError(
        '找不到本地模型客户端正本：%s\n'
        '  全局技能 local-llm 没装？装法见 ~/.dsh/skills/local-llm/SKILL.md；\n'
        '  或设 $env:LOCAL_LLM_MODULE 指向 local_llm.py。' % _IMPL_PATH)

_SPEC = importlib.util.spec_from_file_location('local_llm_skill', _IMPL_PATH)
_IMPL = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _IMPL
_SPEC.loader.exec_module(_IMPL)

# 让 `import local_llm` 直接拿到正本模块（而不是这层壳），同时把名字铺进本模块，
# 以防导入机制在某些路径上返回壳对象。两条路都指向同一个实现。
for _name, _value in vars(_IMPL).items():
    if not _name.startswith('__'):
        globals()[_name] = _value
sys.modules[__name__] = _IMPL
