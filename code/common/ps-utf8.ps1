# code/common/ps-utf8.ps1 —— PowerShell 侧的编码补丁（一次加载，当前会话生效）
#
# ⚠ 本文件必须存成 **UTF-8 带 BOM**：PowerShell 5.1 对**没有 BOM** 的脚本按 ANSI(GBK)
#   解析，中文注释会被解成乱码，可能直接把语法搞坏（实测报 "意外的标记 }"）。
#   用编辑器/工具改完这个文件 **BOM 会丢**（实测 write/edit 都会丢），改完再跑一次 check，
#   失败就补回来：
#     & $PY -c "import sys;sys.path.insert(0,r'<ws>\code\common');import textio as T;p=r'<ws>\code\common\ps-utf8.ps1';T.write_text(p,T.read_text(p),bom=True)"
#   `& $PY code\common\textio.py check` 会断言这一条（audit 的 R4 也会报）。
#
# 为什么需要它
# ------------
# DSH 的 shell 是 **Windows PowerShell 5.1**（`$PSVersionTable.PSEdition = Desktop`），
# 而 5.1 里 `Get-Content` / `Import-Csv` / `Out-File` 的默认编码是 **ANSI = 本机代码页
# 936 = GBK**，工作区的文件却几乎都是 **UTF-8**。于是：
#
#     Get-Content out.json -Raw | ConvertFrom-Json      # ← 默认按 GBK 解 UTF-8 字节
#
# 日文字段名会变成「鎸亣鍚」这类乱码，`ConvertFrom-Json` 直接报「传入的对象无效」，
# 变量为 $null，按字段名取的属性全 $null，判断条件**全部为真**。
# 2026-10-08 就是这样把 `output/cmp4` 里 39 个产出全删了。
#
# 怎么加载（实测：DSH 沙箱里脚本文件根本跑不了）
# ---------------------------------------------
# DSH 的 shell 是受限令牌：`-ExecutionPolicy` 试过 Restricted / AllSigned / RemoteSigned
# **都拦**（"is not digitally signed"），连 `Unrestricted` 都报
# "AuthorizationManager check failed"，**只有 Bypass 能跑脚本文件**；沙箱里的 shell 也
# **不加载 `$PROFILE`**（profile 已装好并实测：新会话里 `$PSDefaultParameterValues` 仍为空）。
# 所以：
#
#   # ① DSH 会话里：读内容再执行（唯一可行，已验证）
#   iex ([IO.File]::ReadAllText("$WS\code\common\ps-utf8.ps1", [Text.Encoding]::UTF8))
#
#   # ② DSH 会话里临时放开（只影响当前进程）
#   Set-ExecutionPolicy -Scope Process Bypass -Force; . "$WS\code\common\ps-utf8.ps1"
#
#   # ③ 你自己的 PowerShell 窗口：profile 已装（~\Documents\WindowsPowerShell\
#   #    Microsoft.PowerShell_profile.ps1，UTF-8 带 BOM，内容就是 ① 那条 + Test-Path 守卫），
#   #    开新窗口自动生效 —— 沙箱外的令牌不受上面那套限制。
#
# DSH 会话里 ad-hoc 跑 python（不 import textio 的一次性命令）加 `-X utf8`：
#   & $PY -X utf8 -c "print('日本語 ♪')"
#
# 它补的是 **Get-Content 的默认编码**：DSH 已经把 `[Console]::OutputEncoding` 和
# `$OutputEncoding` 设成 UTF-8，但这两个都不管 `Get-Content` 读文件。
#
# ⚠ 即便如此，**判断 / 筛选 / 删除的确认仍应交给 Python**：
#     & $PY "$WS\code\common\textio.py" read data\x.json --keys 振假名,词
#     & $PY "$WS\code\common\textio.py" audit --strict
# PowerShell 只负责启动和显示；真要删，先打印「将删 N 个」清单再动手。

$PSDefaultParameterValues['Get-Content:Encoding']   = 'utf8'
$PSDefaultParameterValues['Set-Content:Encoding']   = 'utf8'   # 5.1 下 utf8 = 带 BOM
$PSDefaultParameterValues['Add-Content:Encoding']   = 'utf8'
$PSDefaultParameterValues['Out-File:Encoding']      = 'utf8'
$PSDefaultParameterValues['Import-Csv:Encoding']    = 'utf8'
$PSDefaultParameterValues['Export-Csv:Encoding']    = 'utf8'
$PSDefaultParameterValues['Select-String:Encoding'] = 'utf8'

# 管道交给原生命令（python / ffmpeg …）时的编码；BOM 一律不要
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom

# 任何 ad-hoc 的 python 调用（连 `python -c` 也算）也就此变成 UTF-8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

# 安全读 JSON：等价于 Get-Content -Encoding utf8 | ConvertFrom-Json，但不用记参数
function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
}

Write-Verbose 'ps-utf8.ps1 已加载：Get-Content/Import-Csv/Out-File 默认 utf8，python 默认 UTF-8'
