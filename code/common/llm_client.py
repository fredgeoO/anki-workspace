# -*- coding: utf-8 -*-
"""本地模型客户端（OpenAI Responses API 直连）与 JSON 抢救（issue #5）。

从 ``execution/today_new.py`` 上提：这组代码只做 HTTP + JSON，**不碰 Anki、不读卡片、
不决定讲什么**，两个 execution 脚本（today_new / core6000_example）都要用。留在业务
脚本里会让 core6000_example 为了一个 ``llm_chat`` 去 import 整个讲义流水线。

口径（2026-10 从 /chat/completions 切到 /responses）：

* 端点/模型/key 的查找链与 ``local-llm`` 技能一致：``<workspace>/.dsh/local-llm.json``
  → ``~/.dsh/local-llm.json``。
* 默认沿用端点当时在服务的模型（配置文件写 ``pin_active: true`` 才对齐）。
* ``usage_row`` 把两种协议的 usage 压成同一口径（Responses 没有缓存/思考明细，恒 0）。

**不要在这里加业务判断**。改讲义口径去 today_new，改教学规范去 lesson_local_prompt.md。
"""
import json
import os
import random        # 重试退避的抖动（issue #5 上提时漏了：原先蹭的是 today_new 那份 import）
import re
import sys
import time
import urllib.error
import urllib.request

import paths as WSP
import textio  # noqa: E402  UTF-8 stdio 唯一入口（common）
from jp_text import as_int

# ============================================================================
# 端点 / 模型 / key 的默认值
# ============================================================================
LLM_DEFAULT_BASE = 'http://127.0.0.1:8080/v1'
# OpenAI Responses API 路由（2026-10 从 /chat/completions 切过来）
LLM_RESPONSES_PATH = '/responses'
LLM_DEFAULT_MODEL = 'qwen3.8-27b'
LLM_CONFIG_FILE = os.path.join(WSP.ROOT, '.dsh', 'local-llm.json')
# 全局（机器级）正本配置；工作区那份若存在则覆盖它
LLM_GLOBAL_CONFIG_FILE = os.path.join(
    os.environ.get('DSH_HOME') or os.path.join(os.path.expanduser('~'), '.dsh'),
    'local-llm.json')
LLM_KEY_ENV = ['DSH_LOCAL_LLM_API_KEY', 'LOCAL_LLM_API_KEY']
LLM_TIMEOUT = 1800          # 单次请求上限（秒）；27B Q4 逐张卡通常 10–60s
LLM_HTTP_RETRIES = 3        # 连接/5xx/429 的重试次数（指数退避）
LLM_MAX_TOKENS = 4096       # 单次回复上限；超了会被截断，截断算失败并重试
LLM_TEMPERATURE = 0.3
LLM_TOP_P = 0.9

# ============================================================================
# 本地模型客户端（OpenAI Responses API：/v1/responses）
# ============================================================================
class LLMError(RuntimeError):
    pass


def llm_pin_enabled(file_cfg, cli_model=None, cli_profile=None):
    """这次要不要把 model 对齐到端点**当前在服务**的那个（卡片任务：沿用当时在用的模型）。

    与全局技能 `local_llm.pin_active` 同一套口径：**配置文件里写了 `pin_active` 才算数**
    （正本 `~/.dsh/local-llm.json` 已写 true → 开；没写就不对齐，保持原行为）
    + 环境变量 `DSH_LOCAL_LLM_PIN=0` 关掉；显式给了 `--model` / `$env:DSH_LOCAL_LLM_MODEL`
    也不对齐（那是人在明确指定）。**显式 `--profile` / `$env:DSH_LOCAL_LLM_PROFILE` 同样不
    对齐**：面板/工具点了档位，用户要的就是那一档的 model/base_url；继续 pin 会把
    选择覆盖成端点当前模型——「选模型不生效」就是这么来的（2026-11-14 修复）。
    本脚本不 import 技能模块，所以这里复刻判定，**改口径要两边一起改**。
    """
    env = os.environ.get('DSH_LOCAL_LLM_PIN')
    if env is not None and env.strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    if cli_model or os.environ.get('DSH_LOCAL_LLM_MODEL'):
        return False
    if cli_profile:
        return False
    try:
        return bool(file_cfg.get('pin_active', False))
    except (TypeError, ValueError):
        return False


def llm_active_model(base_url, api_key='', timeout=20):
    """端点当前实际在服务的模型 id（只读，不切换）。

    取 llama.cpp 兼容的 `/props` → `model_alias`。**不用 `/v1/models` 的 `loaded` 标记兜底**：
    路由器上那个标记会滞后（实测 NInfer 在服务时仍把上一个 Strata 档位标成 loaded），
    拿它改 model 等于把请求发到 A 进程却写着 B 模型（必 400）。拿不到返回 None。
    """
    try:
        req = urllib.request.Request(base_url.rsplit('/v1', 1)[0] + '/props',
                                     headers=llm_headers({'api_key': api_key}))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (json.loads(resp.read().decode('utf-8')) or {}).get('model_alias')
    except Exception:
        return None


def llm_window_for(base_url, model, api_key='', timeout=20):
    """某个模型 id 在端点上的窗口（/v1/models 里查；拿不到返回 None）。"""
    try:
        cfg = {'base_url': base_url, 'api_key': api_key}
        for m in (llm_list_models(cfg, timeout) or {}).get('data') or []:
            if m.get('id') == model:
                return int(m.get('context_window') or m.get('max_model_len')
                           or m.get('context_length') or 0) or None
    except Exception:
        pass
    return None


def load_llm_config(args):
    """api key / base_url / model 的来源与优先级，见文件头。

    配置文件读两份：全局 `~/.dsh/local-llm.json`（机器级正本）打底，
    工作区 `.dsh/local-llm.json` 若存在则覆盖（临时特例才需要）。

    **卡片类任务的口径：沿用端点当时在用的本地模型，不切换**（配置文件里
    `pin_active: true`，没写这一项就不对齐）。profile 名只是「我以为在用谁」，服务换了它不会自己跟着换；
    这里发请求前问一次 `/props`，把 model 对齐到事实。显式 `--model` / `_MODEL` 时以显式为准。

    **人点名的档位**（显式 `--profile` / `$env:DSH_LOCAL_LLM_PROFILE`）同样**关 pin**：
    面板/工具选了某个 profile，用户要的就是那个 profile 的 model/base_url；若继续对齐
    `/props`，端点在跑谁就用谁——「选模型不生效」就是这么来的（2026-11-14 修复）。
    **只有什么都不指定**时才是「沿用端点当前在用的模型」。
    """
    file_cfg = {}
    for path in (LLM_GLOBAL_CONFIG_FILE, LLM_CONFIG_FILE):
        if not os.path.exists(path):
            continue
        try:
            # utf-8-sig：PowerShell 的 Set-Content -Encoding utf8 会写 BOM
            with open(path, encoding='utf-8-sig') as fh:
                file_cfg.update(json.load(fh) or {})
        except (OSError, json.JSONDecodeError) as e:
            print('警告：读不出 %s（%s），忽略它。' % (path, e), file=sys.stderr)

    # 人显式指定的档位先记下来（pick / pin 都拿它当「以显式为准」的依据）
    cli_profile = getattr(args, 'profile', None) or os.environ.get('DSH_LOCAL_LLM_PROFILE')

    def pick(cli, envs, key, default):
        if cli:
            return cli
        for name in envs:
            if os.environ.get(name):
                return os.environ[name]
        if file_cfg.get(key):
            return file_cfg[key]
        return default

    # profile 与全局技能 local-llm.py 对齐：DSH_LOCAL_LLM_PROFILE / 文件里的 "profile"
    profs = file_cfg.get('profiles')
    prof_name = (cli_profile or (file_cfg.get('profile') if isinstance(profs, dict) else ''))
    # 人点名的档位（面板下拉 / --profile / DSH_LOCAL_LLM_PROFILE）必须真的存在于 profiles：
    # 拼错的名字绝不静默滑回「顶层默认 + pin」——那正是「选了档位却没任何效果」的来源之一。
    if cli_profile and not (isinstance(profs, dict) and isinstance(profs.get(cli_profile), dict)):
        known = sorted((profs or {}).keys()) if isinstance(profs, dict) else []
        raise LLMError('没有名为 %r 的本地模型档位（local-llm.json profiles：%s）。'
                       '请核对名字，或先在配置里加这一档。'
                       % (cli_profile, '、'.join(known) or '（无）'))
    if prof_name and isinstance(profs, dict) and isinstance(profs.get(prof_name), dict):
        file_cfg.update({k: v for k, v in profs[prof_name].items()
                         if not str(k).startswith('_')})

    declared = pick(getattr(args, 'model', None), ['DSH_LOCAL_LLM_MODEL'],
                    'model', LLM_DEFAULT_MODEL)
    # 空档位（如 ninfer: {}）= 声明「跟随端点当前在用的模型」，profile 本身没写 model。
    # 上面已对显式档位关 pin；这种档位没有可钉的 id，退回 /props 对齐（与旧版行为一致）。
    empty_profile = bool(cli_profile) and prof_name and isinstance(profs, dict) \
        and not (profs.get(prof_name) or {}).get('model')
    cfg = {
        'base_url': pick(getattr(args, 'base_url', None), ['DSH_LOCAL_LLM_BASE_URL'],
                         'base_url', LLM_DEFAULT_BASE).rstrip('/'),
        'model': declared,
        'api_key': pick(getattr(args, 'api_key', None), LLM_KEY_ENV, 'api_key', ''),
        'declared_model': declared,
        'profile': prof_name or '',
    }
    if llm_pin_enabled(file_cfg, getattr(args, 'model', None), cli_profile) or empty_profile:
        alias = llm_active_model(cfg['base_url'], cfg['api_key'])
        if alias and alias != declared:
            why = ('档位 %s 没写 model' % prof_name) if (empty_profile and prof_name) \
                else '配置里写的是 %s，profile=%s' % (declared, prof_name or '（顶层默认）')
            print('📌 沿用端点当前在用的模型：%s（%s）——不切换' % (alias, why), file=sys.stderr)
            cfg['model'] = alias
            window = llm_window_for(cfg['base_url'], alias, cfg['api_key'])
            if window:
                # 账本里记下端点实读窗口，避免拿 profile 里的旧窗口做判断
                cfg['endpoint_ctx'] = window
        elif not alias:
            print('提示：没探到端点当前在服务的模型（/props 拿不到），按配置里的 %s 跑。'
                  % declared, file=sys.stderr)
    return cfg


def llm_headers(cfg):
    headers = {'Content-Type': 'application/json'}
    if cfg.get('api_key'):
        headers['Authorization'] = 'Bearer ' + cfg['api_key']
    return headers


def _http_json(url, payload, headers, timeout):
    """POST 一个 JSON、拿一个 JSON 回来。"""
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def llm_list_models(cfg, timeout=20):
    req = urllib.request.Request(cfg['base_url'] + '/models', headers=llm_headers(cfg))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def read_llm_file_config():
    """配置文件原样合并（全局正本打底 + 工作区覆盖），**不套 profile**。

    给「列模型/profiles」这类只读展示用：load_llm_config 会把选中 profile 盖到
    顶层上，展示层要的是没盖之前的样子。读不到返回 {}。
    """
    file_cfg = {}
    for path in (LLM_GLOBAL_CONFIG_FILE, LLM_CONFIG_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding='utf-8-sig') as fh:
                file_cfg.update(json.load(fh) or {})
        except (OSError, json.JSONDecodeError):
            pass
    return file_cfg


def llm_list_profiles(file_cfg=None):
    """`~/.dsh/local-llm.json` 里 profiles 的清单（只读展示，不联网）。

    返回 [{name, model, base_url, context_window}]；顶层默认档位排在最前
    （name=''，即「不指定 profile」）。
    """
    cfg = file_cfg if isinstance(file_cfg, dict) else read_llm_file_config()
    rows = []
    profs = cfg.get('profiles')
    names = list(profs.keys()) if isinstance(profs, dict) else []
    if cfg.get('model') or cfg.get('base_url'):
        names.insert(0, '')
    for name in names:
        src = profs[name] if (name and isinstance(profs, dict)) else cfg
        if not isinstance(src, dict):
            continue
        rows.append({
            'name': name,
            'model': src.get('model') or '',
            'base_url': src.get('base_url') or '',
            'context_window': as_int(src.get('context_window') or src.get('n_ctx') or 0),
        })
    return rows


def split_llm_messages(messages):
    """chat 形状的 messages → (instructions, input)。

    Responses 没有 role=system 的位置：规范折进 `instructions`，其余消息进 `input`。
    """
    instructions, items = [], []
    for msg in messages or []:
        role = str(msg.get('role') or 'user')
        content = msg.get('content')
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = '\n'.join(str(p.get('text') or '') for p in content if isinstance(p, dict))
        else:
            text = '' if content is None else str(content)
        if role in ('system', 'developer'):
            if text:
                instructions.append(text)
            continue
        items.append({'role': role, 'content': text})
    return '\n\n'.join(instructions), items


def _responses_finish_reason(data):
    """Responses 的 status/incomplete_details → chat 风格的 finish_reason。"""
    status = data.get('status')
    if status == 'incomplete':
        reason = (data.get('incomplete_details') or {}).get('reason')
        return 'length' if reason == 'max_output_tokens' else (reason or 'incomplete')
    if status == 'failed':
        err = data.get('error') or {}
        return 'error:%s' % (err.get('message') or err.get('code') or 'failed')
    if status == 'completed':
        return 'stop'
    return status


def _responses_texts(data):
    """Responses 的 `output[]` → (正文, 思考链)。"""
    content, reasoning = [], []
    for item in data.get('output') or []:
        if not isinstance(item, dict):
            continue
        kind = item.get('type')
        if kind == 'reasoning':
            for part in item.get('content') or []:
                if isinstance(part, dict) and part.get('text'):
                    reasoning.append(str(part['text']))
            if not reasoning:
                for part in item.get('summary') or []:
                    if isinstance(part, dict) and part.get('text'):
                        reasoning.append(str(part['text']))
        elif kind == 'message':
            for part in item.get('content') or []:
                if isinstance(part, dict) and part.get('text'):
                    content.append(str(part['text']))
    return ''.join(content), ''.join(reasoning)


def build_llm_body(cfg, messages, json_mode=True, stream=False):
    """Responses API 的请求体（规范 → instructions，卡数据 → input）。

    ⚠️ NInfer 实测的硬差别（弄错就是 400）：
      * 输出上限叫 `max_output_tokens`（`max_tokens` 不认）；
      * **没有结构化输出**：`text.format` 只接受 `{"type":"text"}`，`json_object` 回
        400 `structured_outputs_not_supported`。所以 `json_mode` 只为签名兼容，
        JSON 形状靠提示词 + `extract_json` 的解析/重试；
      * 没有 `messages`：system 折进 `instructions`，其余进 `input`；
      * 思考开关是 **`reasoning.effort`**（`none` 关），不是 llama.cpp 的
        `chat_template_kwargs`（NInfer 回 400），也不是顶层 `reasoning_effort`。
    """
    instructions, items = split_llm_messages(messages)
    body = {
        'model': cfg['model'],
        'input': items,
        'temperature': LLM_TEMPERATURE,
        'top_p': LLM_TOP_P,
        'max_output_tokens': LLM_MAX_TOKENS,
        'stream': stream,
        # 本地推理最省 token 的一刀：关掉思考链（NInfer：effort=none）。
        'reasoning': {'effort': 'none'},
    }
    if instructions:
        body['instructions'] = instructions
    return body


def llm_chat(cfg, messages, json_mode=True, timeout=None, stream=True, quiet=False, label=''):
    """直连本地模型，返回 (content, usage, meta)。

    默认走流式：27B Q4 逐张卡就要几十秒，流式能拿到**首字延迟**、并避免
    长时间没有数据导致的读超时；思考链（`response.reasoning_text.delta`）一并收着
    （本脚本已把思考关掉，所以通常为空）。
    """
    url = cfg['base_url'] + LLM_RESPONSES_PATH
    timeout = timeout or LLM_TIMEOUT
    last = ''
    for attempt in range(1, LLM_HTTP_RETRIES + 1):
        t0 = time.time()
        try:
            if stream:
                return _llm_stream(cfg, url, messages, json_mode, timeout, quiet, label, t0)
            data = _http_json(url, build_llm_body(cfg, messages, json_mode, False),
                              llm_headers(cfg), timeout)
            if data.get('status') == 'failed' or data.get('error'):
                err = data.get('error') or {}
                raise LLMError('端点返回失败：%s'
                               % (err.get('message') or err.get('code') or data.get('status')))
            return _pack_response(data, time.time() - t0)
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', 'replace')[:400]
            except Exception:
                pass
            if e.code in (400, 401, 403, 404):
                raise LLMError('端点返回 HTTP %s：%s\n'
                               '（401/403 → api key 不对；404 → base_url 或模型名不对'
                               '（本脚本打的是 <base_url>/responses）；'
                               '400 看 code：context_length_exceeded → 超窗；'
                               'structured_outputs_not_supported → 不要再发 text.format；'
                               'chat_template_option_not_supported / unknown_parameter → 思考走 reasoning.effort）'
                               % (e.code, body))
            last = 'HTTP %s %s' % (e.code, body)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = '%s: %s' % (type(e).__name__, e)
        except json.JSONDecodeError as e:
            last = '端点返回的不是合法 JSON：%s' % e
        if attempt < LLM_HTTP_RETRIES:
            wait = min(30, 2 ** attempt) + random.random()
            print('    端点失败（%s），%.1fs 后重试 %d/%d'
                  % (last, wait, attempt, LLM_HTTP_RETRIES - 1), file=sys.stderr)
            time.sleep(wait)
    raise LLMError('端点连续 %d 次失败：%s' % (LLM_HTTP_RETRIES, last))


def _pack_response(data, elapsed):
    """Responses 的 `output[]` → (正文, usage, meta)。思考链单独收，不当答案。"""
    content, reasoning = _responses_texts(data)
    usage = data.get('usage') or {}
    meta = {
        'elapsed': elapsed,
        'finish_reason': _responses_finish_reason(data),
        'reasoning_chars': len(reasoning),
        'timings': data.get('timings') or {},
    }
    return content, usage, meta


def _llm_stream(cfg, url, messages, json_mode, timeout, quiet, label, t0):
    """手写 SSE 解析（标准库就够，不用 openai SDK）。

    Responses 的流是**命名事件**：正文在 `response.output_text.delta`（内容在 `delta` 字段），
    结束事件是 `response.completed`（usage 在里面），**没有 `[DONE]`**。
    """
    payload = build_llm_body(cfg, messages, json_mode, True)
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                 headers=llm_headers(cfg))
    content, reasoning, usage, finish = [], [], {}, None
    t_first = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').strip()
            if not line or not line.startswith('data:'):
                continue          # `event:` 行跳过：事件名在 data 的 type 里也有
            data = line[5:].strip()
            if data == '[DONE]':
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            etype = obj.get('type') or ''
            if etype == 'response.output_text.delta':
                piece = obj.get('delta')
                if piece:
                    if t_first is None:
                        t_first = time.time() - t0
                        if not quiet:
                            print('    %s首字 %.1fs' % (label, t_first), file=sys.stderr)
                    content.append(piece)
            elif etype == 'response.reasoning_text.delta':
                if obj.get('delta'):
                    reasoning.append(obj['delta'])
            elif etype in ('response.completed', 'response.incomplete', 'response.failed'):
                final = obj.get('response') or {}
                if final.get('usage'):
                    usage = final['usage']
                finish = _responses_finish_reason(final)
                if not content:                       # 兜底：没有 delta 时从整段取
                    text, think = _responses_texts(final)
                    if text:
                        content.append(text)
                    if think and not reasoning:
                        reasoning.append(think)
            elif etype in ('error', 'response.error'):
                finish = 'error'
                print('    %s⚠️ 流里报错：%s' % (label, obj.get('message') or obj), file=sys.stderr)
    meta = {'elapsed': time.time() - t0, 'finish_reason': finish,
            'reasoning_chars': sum(len(x) for x in reasoning),
            'first_token': t_first, 'timings': {}}
    return ''.join(content), usage, meta


def usage_row(usage):
    """把端点给的 usage 压成统一口径（协议不同字段名不同）。

    Responses 只给 `input_tokens`/`output_tokens`/`total_tokens`：**没有**缓存与思考明细，
    所以账本里 `cached_tokens` / `reasoning_tokens` 恒为 0（拿不到，不是没发生）。
    """
    def first(*values):
        for v in values:
            if v is not None:
                return v
        return None

    cached = first(((usage.get('prompt_tokens_details') or {}).get('cached_tokens')),
                   ((usage.get('input_tokens_details') or {}).get('cached_tokens')),
                   usage.get('cache_read_input_tokens'))
    reasoning = first(((usage.get('completion_tokens_details') or {}).get('reasoning_tokens')),
                      ((usage.get('output_tokens_details') or {}).get('reasoning_tokens')),
                      usage.get('reasoning_tokens'))
    return {
        'prompt_tokens': as_int(first(usage.get('prompt_tokens'), usage.get('input_tokens'))),
        'completion_tokens': as_int(first(usage.get('completion_tokens'),
                                          usage.get('output_tokens'))),
        'cached_tokens': as_int(cached),
        'reasoning_tokens': as_int(reasoning),
        'total_tokens': as_int(usage.get('total_tokens')),
    }

# ============================================================================
# JSON 抢救
# ============================================================================
FENCE = re.compile(r'```(?:json)?\s*(.*?)```', re.S)


def extract_json(raw):
    """从模型输出里抠出一个 JSON 对象。返回 (obj, 说明) 或 (None, 原因)。"""
    if not raw or not raw.strip():
        return None, '回复是空的'
    text = raw.strip()
    m = FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text), ''
    except json.JSONDecodeError:
        pass
    # 去掉可能的前后开场白，取最外层的 { ... }
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        for candidate in (text[start:end + 1],
                          re.sub(r',\s*([\]}])', r'\1', text[start:end + 1])):
            try:
                return json.loads(candidate), '（剥掉了 JSON 之外的内容）'
            except json.JSONDecodeError:
                continue
    return None, '回复里没有合法 JSON（前 200 字：%s）' % text[:200].replace('\n', ' ')


# ============================================================================
# 自检：python code\common\llm_client.py
# ============================================================================
def _selfcheck():
    """离线自检：只验纯函数（不连端点）。"""
    bad = []

    def ck(name, cond, detail=''):
        print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                           '' if cond else '  ← %s' % detail))
        if not cond:
            bad.append(name)

    obj, why = extract_json('```json\n{"a": 1}\n```')
    ck('extract_json 去围栏', obj == {'a': 1} and not why, repr((obj, why)))
    obj, why = extract_json('前言 {"a": [1,]} 后记')
    ck('extract_json 剥开场白 + 尾逗号', obj == {'a': [1]} and why, repr((obj, why)))
    obj, why = extract_json('没有 JSON')
    ck('extract_json 无 JSON 时返回原因', obj is None and why, repr(why))
    row = usage_row({'input_tokens': 3, 'output_tokens': 4, 'total_tokens': 7})
    ck('usage_row 认 Responses 字段',
       row['prompt_tokens'] == 3 and row['completion_tokens'] == 4 and row['total_tokens'] == 7,
       repr(row))

    # 档位选择 vs pin（2026-11-14「选模型不生效」的回归口径）：
    # 显式 --model / --profile 都关 pin；什么都不指定才对齐端点。
    pinned = {'pin_active': True}
    ck('pin 默认开（无显式档位）', llm_pin_enabled(pinned) is True)
    ck('显式 --model 关 pin', llm_pin_enabled(pinned, cli_model='m') is False)
    ck('显式 --profile 关 pin', llm_pin_enabled(pinned, cli_profile='strata') is False)
    ck('pin_active 没写就不对齐', llm_pin_enabled({}) is False)
    return bad


def main():
    bad = _selfcheck()
    if bad:
        print('结论：%d 项失败' % len(bad), file=sys.stderr)
        return 1
    print('结论：llm_client 口径自检通过（端点/模型/key 查找链只有一份）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
