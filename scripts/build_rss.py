import os, sys, hashlib, time, json
import feedparser, requests
from bs4 import BeautifulSoup
from email.utils import formatdate

PAGE_LINK = os.environ.get("PAGE_LINK", "").strip() or "https://www.facebook.com"
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "5"))
SOURCE_FEEDS = [u.strip() for u in os.environ.get("SOURCE_FEEDS","").split(",") if u.strip()]

# ---------- Translation helpers ----------
# ลำดับความพยายาม: DeepL API -> MyMemory (ฟรี) -> ไม่แปล (ส่งต้นฉบับ)
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "").strip()
DEEPL_ENDPOINT = "https://api-free.deepl.com/v2/translate"  # หรือ api.deepl.com ถ้ามี Pro

def translate_text_th(text):
    text = (text or "").strip()
    if not text:
        return text
    # 1) DeepL (มีคีย์ถึงจะใช้ได้)
    if DEEPL_API_KEY:
        try:
            r = requests.post(
                DEEPL_ENDPOINT,
                data={"text": text, "target_lang": "TH"},
                headers={"Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}"},
                timeout=12,
            )
            if r.ok:
                data = r.json()
                if "translations" in data and data["translations"]:
                    return data["translations"][0]["text"]
        except Exception as e:
            print("DeepL error:", e, file=sys.stderr)
    # 2) MyMemory (ฟรี, มีลิมิต): en|th
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text, "langpair": "en|th"},
            timeout=12,
        )
        if r.ok:
            data = r.json()
            cand = data.get("responseData", {}).get("translatedText") or ""
            if cand:
                return cand
    except Exception as e:
        print("MyMemory error:", e, file=sys.stderr)
    # 3) fallback: ส่งต้นฉบับ
    return text

# ---------- Image helpers ----------
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

def is_image_url(url):
    if not url:
        return False
    u = url.lower()
    if any(u.endswith(ext) for ext in IMG_EXTS):
        return True
    # ลอง HEAD เช็ก Content-Type
    try:
        h = requests.head(url, allow_redirects=True, timeout=8)
        ctype = h.headers.get("Content-Type","").lower()
        return ctype.startswith("image/")
    except Exception:
        return False

def extract_image_from_entry(entry):
    # 1) media:content / media:thumbnail (ถ้ามี)
    media = getattr(entry, "media_content", []) or []
    for m in media:
        u = m.get("url")
        if is_image_url(u):
            return u
    thumbs = getattr(entry, "media_thumbnail", []) or []
    for m in thumbs:
        u = m.get("url")
        if is_image_url(u):
            return u
    # 2) enclosure links
    for l in getattr(entry, "links", []) or []:
        if l.get("rel") == "enclosure":
            u = l.get("href")
            if is_image_url(u):
                return u
    # 3) ดึงจาก summary (img แรก)
    html = getattr(entry, "summary", "") or ""
    if html:
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        if img and img.get("src") and is_image_url(img["src"]):
            return img["src"]
    return None

# ---------- RSS helpers ----------
def clean_html_summary(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script","style"]):
        t.extract()
    text = " ".join(soup.get_text(" ").split())
    return text[:400]

def normalize_pubdate(entry):
    # เก็บเวลาแบบต้นฉบับ (ไม่แปลงโซน)
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

def pull_items():
    items = []
    for feed_url in SOURCE_FEEDS:
        try:
            d = feedparser.parse(feed_url)
            for e in d.entries[:7]:  # ดึงมาหน่อยเผื่อกรองซ้ำ
                title = (getattr(e, "title", "") or "").strip()
                link = (getattr(e, "link", "") or "").strip()
                if not title or not link:
                    continue
                summary_raw = getattr(e, "summary", "") or ""
                pubdate = normalize_pubdate(e)
                guid = make_guid(link, pubdate)
                image_url = extract_image_from_entry(e)

                # แปลไทย (หัวข้อ + สรุป)
                title_th = translate_text_th(title)
                summary_th = translate_text_th(clean_html_summary(summary_raw))

                items.append({
                    "title": title_th or title,
                    "link": link,
                    "summary": summary_th,
                    "pubdate": pubdate,
                    "guid": guid,
                    "image": image_url
                })
        except Exception as ex:
            print("ERR feed:", feed_url, ex, file=sys.stderr)
            continue

    # ตัดซ้ำด้วย GUID และจำกัดจำนวน
    seen, uniq = set(), []
    for it in items:
        if it["guid"] in seen:
            continue
        seen.add(it["guid"])
        uniq.append(it)
    return uniq[:MAX_ITEMS]

def build_rss(items):
    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8" ?>\n<rss version="2.0">\n  <channel>\n')
    parts.append(f'    <title>ข่าวไว</title>\n    <link>{PAGE_LINK}</link>\n')
    parts.append('    <description>ข่าวอัปเดตเร็ว ทันเหตุการณ์ รายชั่วโมง (แปลไทย+ภาพ)</description>\n')
    parts.append('    <language>th-TH</language>\n\n')

    for it in items:
        parts.append("    <item>\n")
        parts.append(f"      <title>{escape(it['title'])}</title>\n")
        parts.append(f"      <link>{escape(it['link'])}</link>\n")
        if it["summary"]:
            parts.append(f"      <description>{escape(it['summary'])}</description>\n")
        parts.append(f"      <pubDate>{escape(it['pubdate'])}</pubDate>\n")
        parts.append(f"      <guid isPermaLink=\"false\">{it['guid']}</guid>\n")
        if it["image"]:
            # enclosure สำหรับภาพ
            # เดา content-type แบบง่าย ถ้า HEAD บอก image/* จะผ่าน
            # ถ้าไม่รู้ กำหนดเป็น image/jpeg ให้ dlvr.it ใช้ภาพได้
            ctype = "image/jpeg"
            try:
                h = requests.head(it["image"], allow_redirects=True, timeout=8)
                ct = h.headers.get("Content-Type","").lower()
                if ct.startswith("image/"):
                    ctype = ct
            except Exception:
                pass
            parts.append(f'      <enclosure url="{escape(it["image"])}" type="{ctype}"/>\n')
        parts.append("    </item>\n\n")

    parts.append("  </channel>\n</rss>\n")
    return "".join(parts)

def main():
    items = pull_items()
    xml = build_rss(items)
    with open("rss.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"Wrote {len(items)} items to rss.xml with images+thai")
    # พิมพ์รายการคร่าวๆ เพื่อ debug log
    for i, it in enumerate(items, 1):
        print(i, it["title"][:80], "|", it["image"] or "-")

if __name__ == "__main__":
    main()
