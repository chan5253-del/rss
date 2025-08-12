import os, sys, hashlib
from urllib.parse import urlparse
import feedparser
from bs4 import BeautifulSoup
from email.utils import formatdate

PAGE_LINK = os.environ.get("PAGE_LINK", "").strip() or "https://www.facebook.com"
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "5"))
SOURCE_FEEDS = [u.strip() for u in os.environ.get("SOURCE_FEEDS","").split(",") if u.strip()]

def clean_html_summary(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script","style"]): t.extract()
    text = " ".join(soup.get_text(" ").split())
    return text[:280]

def normalize_pubdate(entry):
    if getattr(entry, "published", None):
        return entry.published
    if getattr(entry, "updated", None):
        return entry.updated
    return formatdate(localtime=True)

def make_guid(link, pubdate):
    base = (link or "") + "|" + (pubdate or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def escape(s):
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def pull():
    items = []
    for feed_url in SOURCE_FEEDS:
        try:
            d = feedparser.parse(feed_url)
            for e in d.entries[:5]:
                title = getattr(e, "title", "").strip()
                link = getattr(e, "link", "").strip()
                if not title or not link:
                    continue
                summary = clean_html_summary(getattr(e, "summary", ""))
                pubdate = normalize_pubdate(e)
                guid = make_guid(link, pubdate)
                items.append({"title": title, "link": link, "summary": summary, "pubdate": pubdate, "guid": guid})
        except Exception as ex:
            print("ERR feed:", feed_url, ex, file=sys.stderr)
            continue
    # dedupe by guid
    seen = set()
    uniq = []
    for it in items:
        if it["guid"] in seen:
            continue
        seen.add(it["guid"])
        uniq.append(it)
    return uniq[:MAX_ITEMS]

def build_rss(items):
    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8" ?>\n<rss version="2.0">\n  <channel>\n')
    parts.append(f'    <title>ข่าวไว</title>\n    <link>{PAGE_LINK}</link>\n    <description>ข่าวอัปเดตเร็ว ทันเหตุการณ์ รายชั่วโมง</description>\n    <language>th-TH</language>\n\n')
    for it in items:
        parts.append("    <item>\n")
        parts.append(f"      <title>{escape(it['title'])}</title>\n")
        parts.append(f"      <link>{escape(it['link'])}</link>\n")
        if it["summary"]:
            parts.append(f"      <description>{escape(it['summary'])}</description>\n")
        parts.append(f"      <pubDate>{escape(it['pubdate'])}</pubDate>\n")
        parts.append(f"      <guid isPermaLink=\"false\">{it['guid']}</guid>\n")
        parts.append("    </item>\n\n")
    parts.append("  </channel>\n</rss>\n")
    return "".join(parts)

def main():
    items = pull()
    xml = build_rss(items)
    with open("rss.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"Wrote {len(items)} items to rss.xml")

if __name__ == "__main__":
    main()
