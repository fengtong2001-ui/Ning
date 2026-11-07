#!/usr/bin/env python3
"""值班简报 · 最小可用版

用法:
  brief.py clients/xxx.json [--hours 24] [--out out/xxx.md]

客户配置 (clients/xxx.json):
{
  "name": "客户名",
  "hours": 24,
  "sources": [
    {"type": "rss", "name": "Hacker News", "url": "https://hnrss.org/frontpage",
     "keywords": ["anthropic", "openai"]},          # 关键词可省，省了就不过滤
    {"type": "watch", "name": "某商品价", "url": "https://...",
     "regex": "\\$([0-9.]+)", "label": "美元"}
  ]
}
"""
import sys, os, json, re, html, time, argparse
import datetime as dt
from email.utils import parsedate_to_datetime

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def strip_tags(s: str) -> str:
    s = re.sub(r"<img[^>]*>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_dt(txt: str):
    txt = (txt or "").strip()
    if not txt:
        return None
    try:
        d = parsedate_to_datetime(txt)
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = dt.datetime.strptime(txt, fmt)
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        except Exception:
            continue
    return None


def fetch(url: str, timeout=25, retries=3) -> str:
    """抓网页。hnrss 这类源会偶发 SSL EOF，必须重试，否则整个源算失败。"""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA,
                                           "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                             timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def fetch_rss(url: str):
    txt = fetch(url)
    blocks = re.findall(r"<item>(.*?)</item>", txt, re.S) or \
             re.findall(r"<entry>(.*?)</entry>", txt, re.S)
    out = []
    for b in blocks:
        def grab(*pats):
            for p in pats:
                m = re.search(p, b, re.S)
                if m:
                    return m.group(1)
            return ""
        title = strip_tags(re.sub(r"<!\[CDATA\[|\]\]>", "", grab(r"<title[^>]*>(.*?)</title>")))
        link = (grab(r'<link[^>]*href="([^"]+)"', r"<link>(.*?)</link>") or "").strip()
        when = parse_dt(strip_tags(grab(r"<pubDate>(.*?)</pubDate>", r"<updated>(.*?)</updated>",
                                        r"<published>(.*?)</published>")))
        desc = strip_tags(re.sub(r"<!\[CDATA\[|\]\]>", "",
                                 grab(r"<description>(.*?)</description>",
                                      r"<summary[^>]*>(.*?)</summary>",
                                      r"<content[^>]*>(.*?)</content>")))
        out.append({"title": title, "link": link, "when": when, "desc": desc})
    return out


def check_watch(src: dict, state: dict):
    txt = fetch(src["url"])
    pat = src.get("regex")
    if not pat:
        return None, "no regex"
    m = re.search(pat, txt, re.S)
    if not m:
        return None, "regex 没匹配上（页面结构可能变了）"
    val = m.group(1) if m.groups() else m.group(0)
    key = src["url"] + "|" + pat
    old = state.get(key)
    state[key] = {"value": val, "at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if old is None:
        return {"value": val, "old": None, "changed": True, "label": src.get("label", "")}, None
    return {"value": val, "old": old.get("value"), "changed": old.get("value") != val,
            "label": src.get("label", "")}, None


def kw_hit(item, keywords):
    """词边界匹配——不然 'ai' 会命中 'air traffic' 这种。"""
    if not keywords:
        return True
    blob = (item["title"] + " " + item["desc"]).lower()
    for k in keywords:
        k = k.lower().strip()
        if not k:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", blob):
            return True
    return False


def build(cfg: dict, hours: int):
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=hours)
    state = {}
    if os.path.exists(STATE_PATH):
        try:
            state = json.load(open(STATE_PATH))
        except Exception:
            state = {}

    sections, errors = [], []
    seen_links = set()
    for src in cfg.get("sources", []):
        name = src.get("name") or src.get("url")
        try:
            if src.get("type") == "watch":
                res, err = check_watch(src, state)
                if err:
                    errors.append(f"{name}: {err}")
                else:
                    sections.append({"name": name, "kind": "watch", "data": res})
            else:
                items = fetch_rss(src["url"])
                keep = []
                for it in items:
                    if it["when"] and it["when"] < cutoff:
                        continue
                    if not kw_hit(it, src.get("keywords")):
                        continue
                    keep.append(it)
                keep.sort(key=lambda x: x["when"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                          reverse=True)
                uniq = []
                for it in keep:
                    key = (it["link"] or it["title"]).rstrip("/").lower()
                    if key in seen_links:
                        continue
                    seen_links.add(key)
                    uniq.append(it)
                sections.append({"name": name, "kind": "rss", "data": uniq[:src.get("limit", 8)],
                                 "total": len(uniq)})
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__} {str(e)[:80]}")

    try:
        json.dump(state, open(STATE_PATH, "w"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    return sections, errors


def render(cfg, sections, errors, hours):
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    L = [f"# {cfg.get('name','值班简报')} · 简报", "",
         f"{now:%Y-%m-%d %H:%M}（近 {hours} 小时）", ""]
    for s in sections:
        L.append(f"## {s['name']}")
        if s["kind"] == "watch":
            d = s["data"]
            if d["changed"]:
                head = f"变了：{d['value']}{d['label']}"
                if d["old"]:
                    head += f"（上次 {d['old']}{d['label']}）"
                L.append(head)
            else:
                L.append(f"没变：{d['value']}{d['label']}")
        else:
            if not s["data"]:
                L.append("这段时间没动静。")
            for it in s["data"]:
                when = it["when"].astimezone().strftime("%m-%d %H:%M") if it["when"] else ""
                line = f"- {it['title']}"
                if when:
                    line += f"  _（{when}）_"
                L.append(line)
                if it["link"]:
                    L.append(f"  {it['link']}")
        L.append("")
    if errors:
        L.append("## 没抓到的")
        for e in errors:
            L.append(f"- {e}")
    return "\n".join(L).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client")
    ap.add_argument("--hours", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    cfg = json.load(open(a.client))
    hours = a.hours or cfg.get("hours", 24)
    sections, errors = build(cfg, hours)
    md = render(cfg, sections, errors, hours)

    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                                f"{cfg.get('slug', os.path.basename(a.client).replace('.json',''))}-"
                                f"{dt.datetime.now():%Y%m%d-%H%M}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(md)
    print(md)
    print(f"\n--- 已写入 {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
