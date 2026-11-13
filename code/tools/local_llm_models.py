# -*- coding: utf-8 -*-
"""列出本地模型端点上的可选档位（只读，给插件面板/Agent 用）。

输出 JSON：
  { "ok": true,
    "endpoint": {"base_url", "active_model"},     # /props 当前在服务的模型
    "models": [{"id","context_window"}...],        # /v1/models（端点在线才有）
    "profiles": [{"name","model","base_url","context_window"}...] }  # local-llm.json profiles

不写 Anki、不改配置。用法：
  python code/cli.py local-llm-models            # 默认端点（配置文件那份 base_url）
  python code/cli.py local-llm-models --base-url http://127.0.0.1:8081/v1
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))

import paths as WSP          # noqa: E402  工作区路径（也保证 common/ 在 path 上）
import textio                # noqa: E402,F401  UTF-8 stdio
import llm_client as LC      # noqa: E402


def collect(base_url=None, timeout=20):
    file_cfg = LC.read_llm_file_config()
    base = (base_url or file_cfg.get('base_url') or LC.LLM_DEFAULT_BASE).rstrip('/')
    api_key = ''
    for env in LC.LLM_KEY_ENV:
        if os.environ.get(env):
            api_key = os.environ[env]
            break
    if not api_key:
        api_key = file_cfg.get('api_key') or ''

    endpoint = {'base_url': base, 'active_model': LC.llm_active_model(base, api_key, timeout)}
    models = []
    err = None
    try:
        data = LC.llm_list_models({'base_url': base, 'api_key': api_key}, timeout)
        for m in (data.get('data') or []):
            mid = m.get('id')
            if not mid:
                continue
            models.append({'id': mid,
                           'context_window': LC.llm_window_for(base, mid, api_key, timeout)})
    except Exception as exc:  # 端点没开就退回只列 profiles
        err = '%s: %s' % (type(exc).__name__, exc)

    return {'ok': True, 'endpoint': endpoint, 'models': models,
            'profiles': LC.llm_list_profiles(file_cfg), 'error': err}


def main():
    ap = argparse.ArgumentParser(description='列出本地模型端点的档位与 profiles（只读 JSON）')
    ap.add_argument('--base-url', default=None, help='端点 base_url（默认取 local-llm.json）')
    ap.add_argument('--timeout', type=float, default=20.0)
    args = ap.parse_args()
    print(json.dumps(collect(args.base_url, args.timeout), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
