import os, re, json, urllib.request, html

HERE = os.path.dirname(os.path.abspath(__file__))
TDIR = os.path.join(HERE, "texts")
os.makedirs(TDIR, exist_ok=True)
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Accept-Language": "ja,en;q=0.8",
}


def get(url, referer=None):
    h = dict(UA)
    if referer:
        h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def strip_html(s):
    s = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", s)
    s = re.sub(r"(?s)<rt>.*?</rt>", "", s)
    s = re.sub(r"(?s)<rp>.*?</rp>", "", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


# A: NHK Easy (list worked, article 401 -> retry with referer)
try:
    js = json.loads(get("https://www3.nhk.or.jp/news/easy/news-list.json").decode("utf-8"))
    day = sorted(js[0].keys())[-1]
    art = js[0][day][0]
    nid = art["news_id"]
    url = f"https://www3.nhk.or.jp/news/easy/{nid}/{nid}.html"
    body = strip_html(get(url, referer="https://www3.nhk.or.jp/news/easy/").decode("utf-8"))
    with open(os.path.join(TDIR, "NHK_Easy.txt"), "w", encoding="utf-8") as f:
        f.write(art.get("title", "") + " " + body)
    print("NHK_Easy ok:", art.get("title"), len(body))
except Exception as e:
    # alternative: NHK news easy via www3 top page listing
    print("NHK_Easy fail:", e)

# B: wikipedia real prose
try:
    url = "https://ja.wikipedia.org/wiki/%E6%97%A5%E6%9C%AC"
    raw = get(url).decode("utf-8")
    m = re.search(r'(?s)<div class="mw-parser-output">(.*?)(?:<div class="mw-heading|<h2)', raw)
    seg = m.group(1) if m else raw
    body = strip_html(seg)
    body = re.sub(r"\[\d+\]", "", body)
    with open(os.path.join(TDIR, "Wikipedia.txt"), "w", encoding="utf-8") as f:
        f.write(body[:6000])
    print("Wikipedia ok:", len(body))
except Exception as e:
    print("Wikipedia fail:", e)

# C: aozora, two works (children's story + modern literature)
works = {
    "Aozora_gongitsune": "https://www.aozora.gr.jp/cards/000121/files/628_14895.html",
    "Aozora_melos": "https://www.aozora.gr.jp/cards/000035/files/1567_14913.html",
}
for name, url in works.items():
    try:
        s = get(url).decode("cp932", errors="replace")
        body = strip_html(s)
        body = re.sub(r"^.*?-------------------------------------------------------", "", body, flags=re.S)
        body = re.sub(r"-------------------------------------------------------.*$", "", body, flags=re.S)
        with open(os.path.join(TDIR, name + ".txt"), "w", encoding="utf-8") as f:
            f.write(body.strip())
        print(name, "ok:", len(body))
    except Exception as e:
        print(name, "fail:", e)
