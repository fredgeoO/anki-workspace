# -*- coding: utf-8 -*-
"""最小可用 edge-TTS 客户端（纯标准库，不依赖 edge-tts 包）。

为什么不用 edge-tts 包：本机 pip 在工作区里解包 wheel 会被沙箱拒（临时文件），
而 TTS 协议本身很简单，标准库完全够用，还少一层依赖。

协议要点（2026-10 实测）：
  1. 端点 /consumer/speech/synthesize/readaloud/edge/v1
  2. 必须带 Sec-MS-GEC 与 Sec-MS-GEC-Version，否则 403
     GEC v2（2026-10 起）= '<16位hex CS64>-<64位hex SHA256>'，算法见 gec_v2.py
  3. JWT 用固定签名（这是 Edge 浏览器扩展里的公开值）
  4. 握手后：先发 speech.config，再发 ssml，服务端回若干二进制音频帧 + 一个 text 结束帧
"""
import base64
import json
import os
import socket
import ssl
import struct
import sys
import time
import uuid
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
import gec_v2  # noqa: E402  Sec-MS-GEC v2 摘要（上游 edge-tts master 移植，纯标准库）

TRUSTED_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
HOST = 'speech.platform.bing.com'
BASE_PATH = '/consumer/speech/synthesize/readaloud/edge/v1'
# 与 edge-tts 常量保持一致（服务端会校验这个版本号）
CHROMIUM_FULL_VERSION = '143.0.3650.75'
CHROMIUM_MAJOR = CHROMIUM_FULL_VERSION.split('.')[0]
SEC_MS_GEC_VERSION = '2-%s' % CHROMIUM_FULL_VERSION


def connect_id():
    """32 位无连字符小写 hex，作为 ConnectionId 查询参数（服务端要求）。"""
    return uuid.uuid4().hex


def _gec():
    """Sec-MS-GEC v2：'<16位hex CS64>-<64位hex SHA256>'（微软 2026-10 升级，算法见 gec_v2.py）。"""
    return gec_v2.generate_sec_ms_gec_v2()


class WS:
    """最小 WebSocket 客户端（客户端掩码、支持文本/二进制/分片/关闭）。"""

    def __init__(self, timeout=30):
        self.sock = None
        self.timeout = timeout

    def connect(self):
        # 三个查询参数缺一不可：TrustedClientToken、Sec-MS-GEC、Sec-MS-GEC-Version。
        # 另外 ConnectionId 也必须带，缺它服务端直接 403（踩过）。
        path = ('%s?TrustedClientToken=%s&Sec-MS-GEC=%s&Sec-MS-GEC-Version=%s'
                '&ConnectionId=%s'
                % (BASE_PATH, TRUSTED_TOKEN, _gec(), SEC_MS_GEC_VERSION, connect_id()))
        key = base64.b64encode(os.urandom(16)).decode()
        raw = socket.create_connection((HOST, 443), timeout=self.timeout)
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=HOST)
        # Cookie: muid=… 是 edge-tts 新加的要求（DRM.headers_with_muid）
        muid = os.urandom(16).hex().upper()
        req = (
            'GET %s HTTP/1.1\r\n'
            'Host: %s\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            'Sec-WebSocket-Key: %s\r\n'
            'Sec-WebSocket-Version: 13\r\n'
            'Pragma: no-cache\r\n'
            'Cache-Control: no-cache\r\n'
            'Origin: chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold\r\n'
            'Cookie: muid=%s;\r\n'
            'Accept-Encoding: gzip, deflate, br, zstd\r\n'
            'Accept-Language: en-US,en;q=0.9\r\n'
            'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/%s.0.0.0 Safari/537.36 Edg/%s.0.0.0\r\n'
            '\r\n' % (path, HOST, key, muid, CHROMIUM_MAJOR, CHROMIUM_MAJOR)
        )
        self.sock.sendall(req.encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        head = buf.split(b'\r\n\r\n')[0].decode('utf-8', 'replace')
        status = head.split('\r\n')[0]
        if '101' not in status:
            raise RuntimeError('WebSocket 握手失败：%s' % status)
        self._rest = buf.split(b'\r\n\r\n', 1)[1]
        return status

    # ---- 帧 ----
    def _send(self, data, opcode=0x1):
        mask = os.urandom(4)
        n = len(data)
        header = bytearray([0x80 | opcode])
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack('>H', n)
        else:
            header.append(0x80 | 127)
            header += struct.pack('>Q', n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def send_text(self, s):
        self._send(s.encode('utf-8'), 0x1)

    def _read_exact(self, n):
        out = b''
        if self._rest:
            take = min(n, len(self._rest))
            out, self._rest = self._rest[:take], self._rest[take:]
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError('连接中断')
            out += chunk
        return out

    def recv(self):
        """返回 (opcode, payload)；opcode 0x1=文本 0x2=二进制 0x8=关闭。"""
        b1, b2 = self._read_exact(2)
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack('>H', self._read_exact(2))[0]
        elif n == 127:
            n = struct.unpack('>Q', self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else None
        data = self._read_exact(n) if n else b''
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return opcode, data

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


SSML_TMPL = (
    "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{lang}'>"
    "<voice name='{voice}'><prosody pitch='{pitch}' rate='{rate}' volume='{volume}'>"
    '{text}</prosody></voice></speak>'
)


def synth(text, voice='ja-JP-NanamiNeural', rate='+0%', pitch='+0Hz', volume='+0%',
          timeout=60):
    """合成一段文本，返回 mp3 字节。"""
    import html as _html
    # 文本必须做过 XML 转义，否则 & < > 会打断 SSML
    safe = _html.escape(text, quote=False)
    ws = WS(timeout)
    ws.connect()
    try:
        cfg = json.dumps({'context': {'synthesis': {
            'audio': {'metadataoptions': {'sentenceBoundaryEnabled': 'false',
                                          'wordBoundaryEnabled': 'false'},
                      'outputFormat': 'audio-24khz-48kbitrate-mono-mp3'}}},
            'requestId': uuid.uuid4().hex})
        ws.send_text('X-Timestamp:%s\r\nContent-Type:application/json; charset=utf-8\r\n'
                     'Path:speech.config\r\n\r\n%s' % (_ts(), cfg))
        ssml = SSML_TMPL.format(lang=voice.split('-')[0] + '-' + voice.split('-')[1],
                                voice=voice, pitch=pitch, rate=rate, volume=volume,
                                text=safe)
        ws.send_text('X-RequestId:%s\r\nContent-Type:application/ssml+xml\r\n'
                     'X-Timestamp:%sZ\r\nPath:ssml\r\n\r\n%s'
                     % (uuid.uuid4().hex, _ts(), ssml))
        audio = bytearray()
        while True:
            opcode, data = ws.recv()
            if opcode == 0x2:                       # 二进制：前 2 字节 big-endian 是头长度
                if len(data) < 2:
                    continue
                hlen = struct.unpack('>H', data[:2])[0]
                path = data[2:2 + hlen].decode('utf-8', 'replace')
                if 'Path:audio' in path:
                    audio += data[2 + hlen:]
            elif opcode == 0x1:
                if 'Path:turn.end' in data.decode('utf-8', 'replace'):
                    break
            elif opcode == 0x8:
                break
        return bytes(audio)
    finally:
        ws.close()


def _ts():
    import datetime as dt
    return dt.datetime.utcnow().strftime('%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)')


def list_ja_voices():
    import urllib.request
    url = ('https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/'
           'voices/list?trustedclienttoken=%s' % TRUSTED_TOKEN)
    r = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0',
                                             'Sec-MS-GEC': _gec(),
                                             'Sec-MS-GEC-Version': SEC_MS_GEC_VERSION})
    d = json.loads(urllib.request.urlopen(r, timeout=25).read().decode('utf-8'))
    return [v for v in d if v['Locale'].startswith('ja-')]


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'test_tts.mp3'
    text = sys.argv[2] if len(sys.argv) > 2 else '郵便局に戻った時に調べてみるよ'
    print('日语声音：')
    for v in list_ja_voices():
        print('   %s  %s' % (v['ShortName'], v['Gender']))
    t0 = time.time()
    data = synth(text)
    open(out, 'wb').write(data)
    print('合成 %d 字节 -> %s  (%.1fs)' % (len(data), out, time.time() - t0))
