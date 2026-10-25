"""One-shot: decode live deck options protobuf to JSON-ish dict for the JP configs.

Field numbers were reverse-mapped against the legacy JSON schema
(data/snapshots/ankisnap/c.anki2, col.conf['dconf'][id]).
"""
import gzip
import json
import sqlite3
import struct

DB = r"%APPDATA%\Anki2\账户 1\collection.anki2"
uri = "file:" + DB.replace("\\", "/") + "?immutable=1"
con = sqlite3.connect(uri, uri=True)
cur = con.cursor()

FIELD = {
    1: "new_delays_secs", 2: "learn_steps_secs", 4: "easy_days",
    6: "fsrs_params",
    7: "fsrs_health_min_reviews", 8: "fsrs_health_min_revlogs_secs",
    9: "new_per_day", 10: "rev_per_day", 11: "initial_ease", 12: "easy_bonus",
    13: "hard_factor", 14: "new_interval", 15: "interval_mult",
    16: "max_interval", 17: "new_order", 18: "new_gather_priority",
    19: "new_sort_order", 20: "new_mix", 21: "new_per_day_min",
    22: "lapse_mult", 23: "review_order", 24: "max_taken_secs",
    25: "autoplay", 26: "replay_question", 27: "bury_new", 28: "bury_reviews",
    29: "interday_learning_mix", 30: "bury_interday", 31: "timer",
    32: "stop_timer_on_answer", 34: "leech_fails", 35: "leech_action",
    37: "desired_retention", 38: "ignore_revlogs_before", 39: "ignore_before_date",
    40: "sm2_retention", 41: "easy_days_percent", 42: "wait_for_audio",
    43: "seconds_to_show_question", 44: "seconds_to_show_answer_enabled",
    45: "seconds_to_show_question_enabled", 46: "ignore_revlogs_before_date",
    47: "answer_action", 48: "question_action", 49: "new_per_day_minimum",
    50: "fsrs_short_term",
}


def varint(b, i):
    r = 0
    s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        if not (x & 0x80):
            return r, i
        s += 7


def parse(b):
    out = {}
    i = 0
    while i < len(b):
        try:
            key, i = varint(b, i)
        except IndexError:
            break
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = varint(b, i)
            out.setdefault(f, []).append(v)
        elif wt == 1:
            if i + 8 > len(b):
                break
            out.setdefault(f, []).append(struct.unpack("<d", b[i:i + 8])[0])
            i += 8
        elif wt == 2:
            n, i = varint(b, i)
            out.setdefault(f, []).append(b[i:i + n])
            i += n
        elif wt == 5:
            if i + 4 > len(b):
                break
            out.setdefault(f, []).append(struct.unpack("<f", b[i:i + 4])[0])
            i += 4
        else:
            break
    return out


def floats(payload):
    import struct as _s
    return list(_s.unpack("<%df" % (len(payload) // 4), payload[:len(payload) // 4 * 4]))


def raw_field(fields, num):
    v = fields.get(num)
    if not v:
        return None
    return v[0]


live_names = {}
for did, name in cur.execute("select id, name from decks"):
    if isinstance(name, bytes):
        try:
            name = name.decode("utf-8")
        except Exception:
            name = name.decode("utf-8", "replace")
    live_names[did] = name


def norm(s):
    return s.replace("\x1f", "::")


rows = []
for cid, cname, blob in cur.execute("select id, name, config from deck_config"):
    if isinstance(blob, bytes) and blob[:2] == b"\x1f\x8b":
        raw = gzip.decompress(blob)
    else:
        raw = blob
    f = parse(raw)
    d = {}
    for num, label in FIELD.items():
        if num in f:
            d[label] = f[num][0] if len(f[num]) == 1 else f[num]
    for k in ("new_delays_secs", "learn_steps_secs"):
        v = d.get(k)
        if isinstance(v, bytes):
            vals = []
            sub = parse(v)
            for n in sorted(sub):
                vals += [x / 100.0 if k == "new_delays_secs" else x for x in sub[n]]
            d[k] = vals
    for k in ("easy_days", "fsrs_params"):
        v = d.get(k)
        if isinstance(v, bytes):
            n = len(v)
            if k == "easy_days" and n % 4 == 0 and n <= 28:
                d[k] = floats(v)
            elif k == "fsrs_params" and n % 4 == 0 and n >= 68:
                d[k] = floats(v)
            else:
                try:
                    sub = parse(v)
                    vals = []
                    for nn in sorted(sub):
                        vals += sub[nn]
                    d[k] = vals
                except Exception:
                    d[k] = f"<{len(v)}B unparsed>"
    if isinstance(d.get("ignore_revlogs_before_date"), bytes):
        d["ignore_revlogs_before_date"] = d["ignore_revlogs_before_date"].decode()
    if isinstance(d.get("fsrs_params"), list):
        d["fsrs_params_n"] = len(d["fsrs_params"])
    rows.append((cid, cname, d))

print("=== deck_configs ===")
for cid, cname, d in rows:
    print(f"\n--- cid={cid} name={cname!r}")
    for k in sorted(d):
        print(f"    {k} = {d[k]}")

# map deck -> cid using kind field of decks (field 1 = config_id) or snapshot
print("\n=== deck -> config map (live) ===")
for did, name, kind in cur.execute("select id, name, kind from decks"):
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    cid = None
    if isinstance(kind, bytes) and kind[:2] == b"\x1f\x8b":
        try:
            kind = gzip.decompress(kind)
        except Exception:
            pass
    if isinstance(kind, bytes):
        kf = parse(kind)
        if 1 in kf:
            cid = kf[1][0]
    print(f"  {did}\t{name.replace(chr(31), '::')}\t-> cid={cid}")

print("\n=== config_id distribution ===")
import collections
import os
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
c = collections.Counter()
for did, name, kind in cur.execute("select id, name, kind from decks"):
    if isinstance(kind, bytes) and kind[:2] == b"\x1f\x8b":
        try:
            kind = gzip.decompress(kind)
        except Exception:
            pass
    cid = None
    if isinstance(kind, bytes):
        kf = parse(kind)
        cid = kf.get(1, [None])[0]
    c[cid] += 1
print(c)
con.close()
