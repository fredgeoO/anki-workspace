// 离线冒烟：把 client.js 的源码直接当文本检查——确认新文案与按钮逻辑都在文件里。
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../client.js', import.meta.url), 'utf8')

test('fresh client code is on disk (what a browser reload would fetch)', () => {
  assert.ok(src.includes("currentWord.none"), '提示文案键存在')
  assert.ok(src.includes('焦点被这个面板抢走不影响取词'), '新中文文案（刷新后应看到）')
  assert.ok(src.includes("if (!value.found) throw new Error(t('currentWord.none'))"), 'found=false 必须报错不静默')
  assert.ok(src.includes('.catch(() => {})'), 'onClick 返回的 promise 必须被接住（否则红条不出现、错误弹控制台）')
  assert.ok(src.includes("'panel.stale'"), 'unknown method 的人话提示存在')
})
