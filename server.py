from flask import Flask, request, jsonify, send_file
import anthropic
import os
import json
import re
import time
from datetime import datetime
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# ── Database setup ────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    def get_db():
        return psycopg2.connect(DATABASE_URL)
    def db_cursor(conn):
        return conn.cursor(cursor_factory=RealDictCursor)
    PLACEHOLDER = "%s"
    PK_DEF = "SERIAL PRIMARY KEY"
else:
    import sqlite3
    DB_PATH = os.environ.get("DB_PATH", "trentradar.db")
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    def db_cursor(conn):
        return conn.cursor()
    PLACEHOLDER = "?"
    PK_DEF = "INTEGER PRIMARY KEY AUTOINCREMENT"

def init_db():
    conn = get_db()
    cur = db_cursor(conn)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_trends (
            id """ + PK_DEF + """,
            name TEXT NOT NULL,
            desc TEXT,
            momentum TEXT,
            signals TEXT,
            source_labels TEXT,
            source_links TEXT,
            format_hint TEXT,
            tag TEXT,
            region TEXT,
            saved_at TEXT NOT NULL
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ── Scraping helpers ──────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def safe_get(url, timeout=7):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print("[scraper] Failed {}: {}".format(url, e))
        return None

def scrape_nu():
    items = []
    try:
        soup = safe_get("https://www.nu.nl")
        if soup:
            seen = set()
            for a in soup.select("h2 a, h3 a, .item__title a")[:20]:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if title and len(title) > 20 and title not in seen:
                    url = href if href.startswith("http") else "https://www.nu.nl" + href
                    items.append({"title": title, "url": url, "source": "NU.nl"})
                    seen.add(title)
    except Exception as e:
        print("[nu.nl] {}".format(e))
    return items[:6]

def scrape_ad():
    items = []
    try:
        soup = safe_get("https://www.ad.nl")
        if soup:
            seen = set()
            for a in soup.select("h2 a, h3 a, .article__title a")[:20]:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if title and len(title) > 20 and title not in seen:
                    url = href if href.startswith("http") else "https://www.ad.nl" + href
                    items.append({"title": title, "url": url, "source": "AD.nl"})
                    seen.add(title)
    except Exception as e:
        print("[ad.nl] {}".format(e))
    return items[:6]

def scrape_volkskrant():
    items = []
    try:
        soup = safe_get("https://www.volkskrant.nl/meest-gelezen")
        if soup:
            seen = set()
            for a in soup.select("h2 a, h3 a, .teaser__title a, article a")[:20]:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if title and len(title) > 20 and title not in seen:
                    url = href if href.startswith("http") else "https://www.volkskrant.nl" + href
                    items.append({"title": title, "url": url, "source": "de Volkskrant"})
                    seen.add(title)
    except Exception as e:
        print("[volkskrant] {}".format(e))
    return items[:6]

def scrape_parool():
    items = []
    try:
        soup = safe_get("https://www.parool.nl/meest-gelezen")
        if soup:
            seen = set()
            for a in soup.select("h2 a, h3 a, .teaser__title a, article a")[:20]:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if title and len(title) > 20 and title not in seen:
                    url = href if href.startswith("http") else "https://www.parool.nl" + href
                    items.append({"title": title, "url": url, "source": "Het Parool"})
                    seen.add(title)
    except Exception as e:
        print("[parool] {}".format(e))
    return items[:6]

def scrape_libelle():
    items = []
    try:
        soup = safe_get("https://www.libelle.nl")
        if soup:
            seen = set()
            for a in soup.select("h2 a, h3 a, .article-title a, .card__title a")[:20]:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if title and len(title) > 20 and title not in seen:
                    url = href if href.startswith("http") else "https://www.libelle.nl" + href
                    items.append({"title": title, "url": url, "source": "Libelle"})
                    seen.add(title)
    except Exception as e:
        print("[libelle] {}".format(e))
    return items[:6]

def scrape_linda():
    items = []
    try:
        soup = safe_get("https://www.linda.nl")
        if soup:
            seen = set()
            for a in soup.select("h2 a, h3 a, .article__title a, .card-title a")[:20]:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if title and len(title) > 20 and title not in seen:
                    url = href if href.startswith("http") else "https://www.linda.nl" + href
                    items.append({"title": title, "url": url, "source": "Linda.nl"})
                    seen.add(title)
    except Exception as e:
        print("[linda] {}".format(e))
    return items[:6]

def scrape_rtl():
    items = []
    try:
        soup = safe_get("https://www.rtlnieuws.nl")
        if soup:
            seen = set()
            for a in soup.select("h2 a, h3 a, .article-title a, .card__title a")[:20]:
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if title and len(title) > 20 and title not in seen:
                    url = href if href.startswith("http") else "https://www.rtlnieuws.nl" + href
                    items.append({"title": title, "url": url, "source": "RTL Nieuws"})
                    seen.add(title)
    except Exception as e:
        print("[rtl] {}".format(e))
    return items[:6]

def scrape_reddit_hot(subreddit):
    items = []
    try:
        r = requests.get(
            "https://www.reddit.com/r/{}/hot.json?limit=8".format(subreddit),
            headers={"User-Agent": "Trentradar/1.0"},
            timeout=7
        )
        data = r.json()
        for post in data["data"]["children"]:
            p = post["data"]
            if not p.get("stickied") and p.get("title"):
                items.append({
                    "title": p["title"],
                    "url": "https://www.reddit.com" + p["permalink"],
                    "source": "r/{}".format(subreddit),
                    "type": "reddit"
                })
    except Exception as e:
        print("[reddit/{}] {}".format(subreddit, e))
    return items[:5]

_gtrends_cache = {"data": [], "fetched_at": 0}

def scrape_google_trends_nl():
    if time.time() - _gtrends_cache["fetched_at"] < 1800:
        return _gtrends_cache["data"]
    items = []
    try:
        r = requests.get(
            "https://trends.google.com/trends/trendingsearches/daily/rss?geo=NL",
            headers=HEADERS, timeout=8
        )
        root = ET.fromstring(r.content)
        ns = {"ht": "https://trends.google.com/trends/trendingsearches/daily"}
        for item in root.findall(".//item")[:12]:
            title_el = item.find("title")
            traffic_el = item.find("ht:approx_traffic", ns)
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            traffic = traffic_el.text.strip() if traffic_el is not None and traffic_el.text else ""
            if title:
                search_url = "https://trends.google.com/trends/explore?q=" + requests.utils.quote(title) + "&geo=NL"
                items.append({
                    "title": title + (" (" + traffic + " searches)" if traffic else ""),
                    "url": search_url,
                    "source": "Google Trends NL",
                    "type": "trends"
                })
    except Exception as e:
        print("[google trends] {}".format(e))
    _gtrends_cache["data"] = items
    _gtrends_cache["fetched_at"] = time.time()
    return items

def gather_all_headlines(region="nl"):
    all_items = []
    subreddits = ["Netherlands", "europe", "psychology", "TrueOffMyChest"]
    if region != "nl":
        subreddits = ["worldnews", "europe", "sociology", "psychology"]
    scrapers = [scrape_nu, scrape_ad, scrape_volkskrant, scrape_parool,
                scrape_libelle, scrape_linda, scrape_rtl, scrape_google_trends_nl]
    scrapers += [lambda s=s: scrape_reddit_hot(s) for s in subreddits]
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(fn): fn for fn in scrapers}
        for future in as_completed(futures, timeout=15):
            try:
                result = future.result()
                if result:
                    all_items.extend(result)
            except Exception as e:
                print("[parallel error] {}".format(e))
    return all_items

_research_cache = {"data": [], "fetched_at": 0}

def scrape_rss(url, source_name, source_type="research", limit=5):
    items = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:limit]:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")
            title = (title_el.text or "").strip()
            link = (link_el.text or "").strip()
            desc = re.sub(r"<[^>]+>", "", (desc_el.text or ""))[:180].strip()
            pub = (pub_el.text or "")[:16].strip()
            if title and link:
                items.append({"title": title, "url": link, "desc": desc, "pub": pub, "source": source_name, "type": source_type})
    except Exception as e:
        print("[rss/{}] {}".format(source_name, e))
    return items

def scrape_scp():
    items = []
    try:
        soup = safe_get("https://www.scp.nl/publicaties")
        if soup:
            for article in soup.select("article, .publication-item, .search-result")[:6]:
                a = article.select_one("a[href]")
                title_el = article.select_one("h2, h3, .title")
                desc_el = article.select_one("p, .description, .summary")
                if a and title_el:
                    title = title_el.get_text(strip=True)
                    href = a.get("href", "")
                    url = href if href.startswith("http") else "https://www.scp.nl" + href
                    desc = desc_el.get_text(strip=True)[:180] if desc_el else ""
                    if len(title) > 10:
                        items.append({"title": title, "url": url, "desc": desc, "pub": "", "source": "SCP", "type": "research"})
    except Exception as e:
        print("[scp] {}".format(e))
    return items[:5]

def gather_research():
    if time.time() - _research_cache["fetched_at"] < 3600:
        return _research_cache["data"]
    feeds = [
        ("https://www.cbs.nl/nl-nl/rss/artikelen", "CBS Statistiek", "research"),
        ("https://www.pewresearch.org/feed/", "Pew Research", "research"),
        ("https://reutersinstitute.politics.ox.ac.uk/rss.xml", "Reuters Institute", "research"),
        ("https://hbr.org/rss/topic/culture", "Harvard Business Review", "research"),
        ("https://newsroom.spotify.com/feed/", "Spotify Newsroom", "culture"),
        ("https://newsroom.tiktok.com/en-us/rss", "TikTok Newsroom", "culture"),
    ]
    tasks = [scrape_scp] + [lambda u=u, n=n, t=t: scrape_rss(u, n, t, 4) for u, n, t in feeds]
    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fn): fn for fn in tasks}
        for future in as_completed(futures, timeout=20):
            try:
                result = future.result()
                if result:
                    all_items.extend(result)
            except Exception as e:
                print("[research parallel error] {}".format(e))
    _research_cache["data"] = all_items
    _research_cache["fetched_at"] = time.time()
    return all_items

# ── Google Sheets format database ────────────────────────────────────────────

SHEET_ID = "1hriKOJaETWO69ty29cMuR9CPTvMa1X4N"
_formats_cache = {"data": [], "fetched_at": 0}

def get_formats_from_sheet():
    """Fetch formats from Google Sheets using service account credentials."""
    if time.time() - _formats_cache["fetched_at"] < 1800:
        return _formats_cache["data"]
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if not creds_json:
            print("[sheets] No GOOGLE_CREDENTIALS_JSON env var found")
            return []
        creds_dict = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID).sheet1
        rows = sheet.get_all_records()
        formats = []
        for row in rows:
            title = str(row.get("Title", "") or row.get("title", "")).strip()
            synopsis = str(row.get("Synopsis", "") or row.get("synopsis", "")).strip()
            genre = str(row.get("Genre", "") or row.get("genre", "")).strip()
            tags = str(row.get("Tags", "") or row.get("tags", "")).strip()
            topic = str(row.get("Topic", "") or row.get("topic", "")).strip()
            if title:
                formats.append({
                    "title": title,
                    "synopsis": synopsis[:300],
                    "genre": genre,
                    "tags": tags,
                    "topic": topic
                })
        _formats_cache["data"] = formats
        _formats_cache["fetched_at"] = time.time()
        print("[sheets] Loaded {} formats".format(len(formats)))
        return formats
    except Exception as e:
        print("[sheets] Error: {}".format(e))
        return []

def match_formats_to_trend(trend_name, trend_desc, formats):
    """Use Claude to find matching formats for a trend."""
    if not formats:
        return []
    try:
        # Send up to 60 formats to Claude for matching
        sample = formats[:60]
        format_list = "\n".join([
            "{}. {} | Genre: {} | Topic: {} | Synopsis: {}".format(
                i+1, f["title"], f["genre"], f["topic"], f["synopsis"][:150]
            ) for i, f in enumerate(sample)
        ])
        anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": (
                    "You are a TV format analyst. Given this cultural trend and a list of TV formats, "
                    "identify the 1-3 formats that are most thematically related to the trend.\n\n"
                    "Trend: {}\n{}\n\n"
                    "Format database:\n{}\n\n"
                    "Return ONLY a JSON object starting with {{ ending with }}:\n"
                    "{{\"matches\":[{{\"title\":\"Format title\",\"reason\":\"One sentence why this matches the trend\"}}]}}\n"
                    "Return an empty matches array if nothing is relevant. Max 3 matches."
                ).format(trend_name, trend_desc, format_list)
            }]
        )
        text = message.content[0].text
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            result = json.loads(match.group(0))
            # Enrich matches with full format data
            matches = result.get("matches", [])
            enriched = []
            for m in matches:
                full = next((f for f in formats if f["title"].lower() == m["title"].lower()), None)
                enriched.append({
                    "title": m["title"],
                    "reason": m.get("reason", ""),
                    "genre": full["genre"] if full else "",
                    "topic": full["topic"] if full else "",
                    "synopsis": full["synopsis"][:150] if full else ""
                })
            return enriched
    except Exception as e:
        print("[match_formats] {}".format(e))
    return []

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder=".")
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# HTML stored as base64 to avoid file path issues on Railway
_HTML_B64 = (
    "PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9Im5sIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVU" +
    "Ri04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCwg" +
    "aW5pdGlhbC1zY2FsZT0xLjAiPgo8dGl0bGU+VHJlbnRyYWRhcjwvdGl0bGU+CjxsaW5rIGhyZWY9" +
    "Imh0dHBzOi8vZm9udHMuZ29vZ2xlYXBpcy5jb20vY3NzMj9mYW1pbHk9SW50ZXI6d2dodEAzMDA7" +
    "NDAwOzUwMDs2MDA7NzAwJmRpc3BsYXk9c3dhcCIgcmVsPSJzdHlsZXNoZWV0Ij4KPHN0eWxlPgoq" +
    "LCAqOjpiZWZvcmUsICo6OmFmdGVyIHsgYm94LXNpemluZzogYm9yZGVyLWJveDsgbWFyZ2luOiAw" +
    "OyBwYWRkaW5nOiAwOyB9Cjpyb290IHsKICAtLWJnOiAjMGYxMTE3OyAtLXNpZGViYXI6ICMxNjFi" +
    "Mjc7IC0tY2FyZDogIzFhMjAzNTsgLS1ib3JkZXI6IHJnYmEoMjU1LDI1NSwyNTUsMC4wOCk7CiAg" +
    "LS1ib3JkZXIyOiByZ2JhKDI1NSwyNTUsMjU1LDAuMTIpOyAtLXRleHQ6ICNlMmU4ZjA7IC0tbXV0" +
    "ZWQ6ICM3MTgwOTY7CiAgLS1hY2NlbnQ6ICM3YzNhZWQ7IC0tYWNjZW50MjogI2E4NTVmNzsgLS1n" +
    "cmVlbjogIzEwYjk4MTsgLS1hbWJlcjogI2Y1OWUwYjsKICAtLWJsdWU6ICMzYjgyZjY7IC0tcmVk" +
    "OiAjZWY0NDQ0OyAtLXBpbms6ICNlYzQ4OTk7IC0tZ2xvdzogcmdiYSgxMjQsNTgsMjM3LDAuMTUp" +
    "Owp9CmJvZHkgeyBmb250LWZhbWlseTogJ0ludGVyJywgLWFwcGxlLXN5c3RlbSwgc2Fucy1zZXJp" +
    "ZjsgYmFja2dyb3VuZDogdmFyKC0tYmcpOyBjb2xvcjogdmFyKC0tdGV4dCk7IG1pbi1oZWlnaHQ6" +
    "IDEwMHZoOyBkaXNwbGF5OiBmbGV4OyB9Cgouc2lkZWJhciB7IHdpZHRoOiAyMjBweDsgbWluLWhl" +
    "aWdodDogMTAwdmg7IGJhY2tncm91bmQ6IHZhcigtLXNpZGViYXIpOyBib3JkZXItcmlnaHQ6IDFw" +
    "eCBzb2xpZCB2YXIoLS1ib3JkZXIpOyBkaXNwbGF5OiBmbGV4OyBmbGV4LWRpcmVjdGlvbjogY29s" +
    "dW1uOyBmbGV4LXNocmluazogMDsgcG9zaXRpb246IGZpeGVkOyB0b3A6IDA7IGxlZnQ6IDA7IGJv" +
    "dHRvbTogMDsgei1pbmRleDogMTAwOyB9Ci5zaWRlYmFyLWxvZ28geyBwYWRkaW5nOiAyMnB4IDE4" +
    "cHggMThweDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLnNpZGVi" +
    "YXItbG9nbyAubmFtZSB7IGZvbnQtc2l6ZTogMTVweDsgZm9udC13ZWlnaHQ6IDcwMDsgY29sb3I6" +
    "ICNmZmY7IGxldHRlci1zcGFjaW5nOiAtMC4zcHg7IH0KLnNpZGViYXItbG9nbyAudGFnbGluZSB7" +
    "IGZvbnQtc2l6ZTogOXB4OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBtYXJnaW4tdG9wOiAzcHg7IGxl" +
    "dHRlci1zcGFjaW5nOiAwLjVweDsgdGV4dC10cmFuc2Zvcm06IHVwcGVyY2FzZTsgfQouc2lkZWJh" +
    "ci1zZWN0aW9uIHsgcGFkZGluZzogMTZweCAxMHB4IDhweDsgfQouc2lkZWJhci1zZWN0aW9uLWxh" +
    "YmVsIHsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiA2MDA7IGNvbG9yOiB2YXIoLS1tdXRl" +
    "ZCk7IHRleHQtdHJhbnNmb3JtOiB1cHBlcmNhc2U7IGxldHRlci1zcGFjaW5nOiAxcHg7IHBhZGRp" +
    "bmc6IDAgOHB4OyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLm5hdi1pdGVtIHsgZGlzcGxheTogZmxl" +
    "eDsgYWxpZ24taXRlbXM6IGNlbnRlcjsgZ2FwOiAxMHB4OyBwYWRkaW5nOiA5cHggMTBweDsgYm9y" +
    "ZGVyLXJhZGl1czogOHB4OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiA1MDA7IGNvbG9y" +
    "OiB2YXIoLS1tdXRlZCk7IGN1cnNvcjogcG9pbnRlcjsgdHJhbnNpdGlvbjogYWxsIDAuMTVzOyBt" +
    "YXJnaW4tYm90dG9tOiAycHg7IH0KLm5hdi1pdGVtOmhvdmVyIHsgYmFja2dyb3VuZDogcmdiYSgy" +
    "NTUsMjU1LDI1NSwwLjA1KTsgY29sb3I6IHZhcigtLXRleHQpOyB9Ci5uYXYtaXRlbS5hY3RpdmUg" +
    "eyBiYWNrZ3JvdW5kOiB2YXIoLS1nbG93KTsgY29sb3I6ICNmZmY7IH0KLm5hdi1kb3QgeyB3aWR0" +
    "aDogN3B4OyBoZWlnaHQ6IDdweDsgYm9yZGVyLXJhZGl1czogNTAlOyBiYWNrZ3JvdW5kOiByZ2Jh" +
    "KDI1NSwyNTUsMjU1LDAuMTUpOyBmbGV4LXNocmluazogMDsgfQoubmF2LWl0ZW0uYWN0aXZlIC5u" +
    "YXYtZG90IHsgYmFja2dyb3VuZDogdmFyKC0tYWNjZW50Mik7IGJveC1zaGFkb3c6IDAgMCA4cHgg" +
    "dmFyKC0tYWNjZW50Mik7IH0KLnNpZGViYXItc291cmNlcyB7IHBhZGRpbmc6IDEycHg7IGJvcmRl" +
    "ci10b3A6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyBtYXJnaW4tdG9wOiBhdXRvOyB9Ci5zaWRl" +
    "YmFyLXNvdXJjZXMtbGFiZWwgeyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IDYwMDsgY29s" +
    "b3I6IHZhcigtLW11dGVkKTsgdGV4dC10cmFuc2Zvcm06IHVwcGVyY2FzZTsgbGV0dGVyLXNwYWNp" +
    "bmc6IDFweDsgbWFyZ2luLWJvdHRvbTogOHB4OyB9Ci5zcmMtcGlsbCB7IGRpc3BsYXk6IGlubGlu" +
    "ZS1mbGV4OyBhbGlnbi1pdGVtczogY2VudGVyOyBmb250LXNpemU6IDEwcHg7IHBhZGRpbmc6IDNw" +
    "eCA4cHg7IGJvcmRlci1yYWRpdXM6IDIwcHg7IGJvcmRlcjogMXB4IHNvbGlkIHZhcigtLWJvcmRl" +
    "cjIpOyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBjdXJzb3I6IGRlZmF1bHQ7IG1hcmdpbjogMnB4OyB9" +
    "Ci5zcmMtcGlsbC5vbiB7IGJvcmRlci1jb2xvcjogcmdiYSgxNiwxODUsMTI5LDAuNCk7IGNvbG9y" +
    "OiB2YXIoLS1ncmVlbik7IGJhY2tncm91bmQ6IHJnYmEoMTYsMTg1LDEyOSwwLjA4KTsgfQoKLm1h" +
    "aW4geyBtYXJnaW4tbGVmdDogMjIwcHg7IGZsZXg6IDE7IG1pbi1oZWlnaHQ6IDEwMHZoOyBkaXNw" +
    "bGF5OiBmbGV4OyBmbGV4LWRpcmVjdGlvbjogY29sdW1uOyB9Ci50b3BiYXIgeyBoZWlnaHQ6IDU4" +
    "cHg7IGJhY2tncm91bmQ6IHZhcigtLXNpZGViYXIpOyBib3JkZXItYm90dG9tOiAxcHggc29saWQg" +
    "dmFyKC0tYm9yZGVyKTsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGNlbnRlcjsganVzdGlm" +
    "eS1jb250ZW50OiBzcGFjZS1iZXR3ZWVuOyBwYWRkaW5nOiAwIDI0cHg7IHBvc2l0aW9uOiBzdGlj" +
    "a3k7IHRvcDogMDsgei1pbmRleDogNTA7IH0KLnRvcGJhci10aXRsZSB7IGZvbnQtc2l6ZTogMTRw" +
    "eDsgZm9udC13ZWlnaHQ6IDYwMDsgY29sb3I6ICNmZmY7IH0KLnRvcGJhci1yaWdodCB7IGRpc3Bs" +
    "YXk6IGZsZXg7IGdhcDogOHB4OyBhbGlnbi1pdGVtczogY2VudGVyOyB9Ci5zZWwgeyBmb250LXNp" +
    "emU6IDEycHg7IHBhZGRpbmc6IDZweCAxMHB4OyBib3JkZXItcmFkaXVzOiA4cHg7IGJvcmRlcjog" +
    "MXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBiYWNrZ3JvdW5kOiB2YXIoLS1jYXJkKTsgY29sb3I6" +
    "IHZhcigtLXRleHQpOyBjdXJzb3I6IHBvaW50ZXI7IG91dGxpbmU6IG5vbmU7IH0KLnNjYW4tYnRu" +
    "IHsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogNjAwOyBwYWRkaW5nOiA4cHggMjBweDsg" +
    "Ym9yZGVyLXJhZGl1czogOHB4OyBib3JkZXI6IG5vbmU7IGJhY2tncm91bmQ6IGxpbmVhci1ncmFk" +
    "aWVudCgxMzVkZWcsIHZhcigtLWFjY2VudCksIHZhcigtLWFjY2VudDIpKTsgY29sb3I6ICNmZmY7" +
    "IGN1cnNvcjogcG9pbnRlcjsgYm94LXNoYWRvdzogMCAwIDIwcHggcmdiYSgxMjQsNTgsMjM3LDAu" +
    "MzUpOyB0cmFuc2l0aW9uOiBhbGwgMC4yczsgfQouc2Nhbi1idG46aG92ZXIgeyBib3gtc2hhZG93" +
    "OiAwIDAgMzBweCByZ2JhKDEyNCw1OCwyMzcsMC41NSk7IHRyYW5zZm9ybTogdHJhbnNsYXRlWSgt" +
    "MXB4KTsgfQouc2Nhbi1idG46ZGlzYWJsZWQgeyBvcGFjaXR5OiAwLjU7IGN1cnNvcjogbm90LWFs" +
    "bG93ZWQ7IHRyYW5zZm9ybTogbm9uZTsgfQoKLmNvbnRlbnQgeyBwYWRkaW5nOiAyMHB4IDI0cHg7" +
    "IGZsZXg6IDE7IH0KLnN0YXR1cy1iYXIgeyBkaXNwbGF5OiBmbGV4OyBhbGlnbi1pdGVtczogY2Vu" +
    "dGVyOyBnYXA6IDEycHg7IGZvbnQtc2l6ZTogMTFweDsgY29sb3I6IHZhcigtLW11dGVkKTsgbWFy" +
    "Z2luLWJvdHRvbTogMTRweDsgZmxleC13cmFwOiB3cmFwOyB9Ci5zdGF0dXMtZG90IHsgd2lkdGg6" +
    "IDZweDsgaGVpZ2h0OiA2cHg7IGJvcmRlci1yYWRpdXM6IDUwJTsgYmFja2dyb3VuZDogdmFyKC0t" +
    "Z3JlZW4pOyBib3gtc2hhZG93OiAwIDAgNnB4IHZhcigtLWdyZWVuKTsgZmxleC1zaHJpbms6IDA7" +
    "IH0KLnN0YXR1cy1kb3Quc2Nhbm5pbmcgeyBiYWNrZ3JvdW5kOiB2YXIoLS1hbWJlcik7IGJveC1z" +
    "aGFkb3c6IDAgMCA2cHggdmFyKC0tYW1iZXIpOyBhbmltYXRpb246IGJsaW5rIDFzIGluZmluaXRl" +
    "OyB9CkBrZXlmcmFtZXMgYmxpbmsgeyAwJSwxMDAle29wYWNpdHk6MX01MCV7b3BhY2l0eTowLjN9" +
    "IH0KLnByb2dyZXNzLWJhciB7IGhlaWdodDogMnB4OyBiYWNrZ3JvdW5kOiB2YXIoLS1ib3JkZXIp" +
    "OyBib3JkZXItcmFkaXVzOiAycHg7IG1hcmdpbi1ib3R0b206IDE4cHg7IG92ZXJmbG93OiBoaWRk" +
    "ZW47IH0KLnByb2dyZXNzLWZpbGwgeyBoZWlnaHQ6IDJweDsgYmFja2dyb3VuZDogbGluZWFyLWdy" +
    "YWRpZW50KDkwZGVnLCB2YXIoLS1hY2NlbnQpLCB2YXIoLS1hY2NlbnQyKSk7IHdpZHRoOiAwJTsg" +
    "dHJhbnNpdGlvbjogd2lkdGggMC40czsgYm9yZGVyLXJhZGl1czogMnB4OyB9CgouZ3JpZC0zIHsg" +
    "ZGlzcGxheTogZ3JpZDsgZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOiAxZnIgMWZyIDFmcjsgZ2FwOiAx" +
    "NnB4OyBhbGlnbi1pdGVtczogc3RhcnQ7IH0KQG1lZGlhIChtYXgtd2lkdGg6IDExMDBweCkgeyAu" +
    "Z3JpZC0zIHsgZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOiAxZnIgMWZyOyB9IH0KQG1lZGlhIChtYXgt" +
    "d2lkdGg6IDcwMHB4KSB7IC5ncmlkLTMgeyBncmlkLXRlbXBsYXRlLWNvbHVtbnM6IDFmcjsgfSAu" +
    "c2lkZWJhciB7IGRpc3BsYXk6IG5vbmU7IH0gLm1haW4geyBtYXJnaW4tbGVmdDogMDsgfSB9Cgou" +
    "Y2FyZCB7IGJhY2tncm91bmQ6IHZhcigtLWNhcmQpOyBib3JkZXI6IDFweCBzb2xpZCB2YXIoLS1i" +
    "b3JkZXIpOyBib3JkZXItcmFkaXVzOiAxMnB4OyBvdmVyZmxvdzogaGlkZGVuOyB9Ci5jYXJkLWhl" +
    "YWRlciB7IGRpc3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50ZXI7IGp1c3RpZnktY29udGVu" +
    "dDogc3BhY2UtYmV0d2VlbjsgcGFkZGluZzogMTJweCAxNnB4OyBib3JkZXItYm90dG9tOiAxcHgg" +
    "c29saWQgdmFyKC0tYm9yZGVyKTsgfQouY2FyZC10aXRsZSB7IGZvbnQtc2l6ZTogMTBweDsgZm9u" +
    "dC13ZWlnaHQ6IDYwMDsgY29sb3I6IHZhcigtLW11dGVkKTsgdGV4dC10cmFuc2Zvcm06IHVwcGVy" +
    "Y2FzZTsgbGV0dGVyLXNwYWNpbmc6IDAuOHB4OyB9Ci5jYXJkLWJvZHkgeyBwYWRkaW5nOiAwIDE2" +
    "cHggNHB4OyB9CgoudGFicyB7IGRpc3BsYXk6IGZsZXg7IGJvcmRlci1ib3R0b206IG5vbmU7IH0K" +
    "LnRhYi1idG4geyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiA1MDA7IHBhZGRpbmc6IDAg" +
    "MTRweCAwIDA7IGN1cnNvcjogcG9pbnRlcjsgY29sb3I6IHZhcigtLW11dGVkKTsgYm9yZGVyOiBu" +
    "b25lOyBiYWNrZ3JvdW5kOiBub25lOyBib3JkZXItYm90dG9tOiAycHggc29saWQgdHJhbnNwYXJl" +
    "bnQ7IHBhZGRpbmctYm90dG9tOiAxMnB4OyBtYXJnaW4tYm90dG9tOiAtMXB4OyB0cmFuc2l0aW9u" +
    "OiBhbGwgMC4xNXM7IH0KLnRhYi1idG4uYWN0aXZlIHsgY29sb3I6ICNmZmY7IGJvcmRlci1ib3R0" +
    "b20tY29sb3I6IHZhcigtLWFjY2VudDIpOyB9Ci50YWItYnRuOmhvdmVyOm5vdCguYWN0aXZlKSB7" +
    "IGNvbG9yOiB2YXIoLS10ZXh0KTsgfQoKLnRyZW5kLWl0ZW0geyBwYWRkaW5nOiAxNHB4IDA7IGJv" +
    "cmRlci1ib3R0b206IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyB9Ci50cmVuZC1pdGVtOmxhc3Qt" +
    "Y2hpbGQgeyBib3JkZXItYm90dG9tOiBub25lOyB9Ci50cmVuZC1yb3cxIHsgZGlzcGxheTogZmxl" +
    "eDsgYWxpZ24taXRlbXM6IGZsZXgtc3RhcnQ7IGp1c3RpZnktY29udGVudDogc3BhY2UtYmV0d2Vl" +
    "bjsgZ2FwOiAxMHB4OyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLnRyZW5kLW5hbWUgeyBmb250LXNp" +
    "emU6IDE0cHg7IGZvbnQtd2VpZ2h0OiA2MDA7IGNvbG9yOiAjZmZmOyBsaW5lLWhlaWdodDogMS4z" +
    "OyB9Ci5iYWRnZSB7IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogNjAwOyBwYWRkaW5nOiAz" +
    "cHggOHB4OyBib3JkZXItcmFkaXVzOiAyMHB4OyB3aGl0ZS1zcGFjZTogbm93cmFwOyBmbGV4LXNo" +
    "cmluazogMDsgdGV4dC10cmFuc2Zvcm06IHVwcGVyY2FzZTsgbGV0dGVyLXNwYWNpbmc6IDAuNHB4" +
    "OyB9Ci5iLXJpc2luZyB7IGJhY2tncm91bmQ6IHJnYmEoMTYsMTg1LDEyOSwwLjEyKTsgY29sb3I6" +
    "IHZhcigtLWdyZWVuKTsgYm9yZGVyOiAxcHggc29saWQgcmdiYSgxNiwxODUsMTI5LDAuMjUpOyB9" +
    "Ci5iLWVtZXJnaW5nIHsgYmFja2dyb3VuZDogcmdiYSgyNDUsMTU4LDExLDAuMTIpOyBjb2xvcjog" +
    "dmFyKC0tYW1iZXIpOyBib3JkZXI6IDFweCBzb2xpZCByZ2JhKDI0NSwxNTgsMTEsMC4yNSk7IH0K" +
    "LmItZXN0YWJsaXNoZWQgeyBiYWNrZ3JvdW5kOiByZ2JhKDU5LDEzMCwyNDYsMC4xMik7IGNvbG9y" +
    "OiB2YXIoLS1ibHVlKTsgYm9yZGVyOiAxcHggc29saWQgcmdiYSg1OSwxMzAsMjQ2LDAuMjUpOyB9" +
    "Ci5iLXNoaWZ0aW5nIHsgYmFja2dyb3VuZDogcmdiYSgyMzYsNzIsMTUzLDAuMTIpOyBjb2xvcjog" +
    "dmFyKC0tcGluayk7IGJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMjM2LDcyLDE1MywwLjI1KTsgfQou" +
    "dHJlbmQtZGVzYyB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6IHZhcigtLW11dGVkKTsgbGluZS1o" +
    "ZWlnaHQ6IDEuNjsgbWFyZ2luLWJvdHRvbTogNnB4OyB9Ci50cmVuZC1zaWduYWxzIHsgZm9udC1z" +
    "aXplOiAxMXB4OyBjb2xvcjogcmdiYSgyNTUsMjU1LDI1NSwwLjMpOyBsaW5lLWhlaWdodDogMS41" +
    "OyBtYXJnaW4tYm90dG9tOiA4cHg7IH0KLnRyZW5kLWFjdGlvbnMgeyBkaXNwbGF5OiBmbGV4OyBn" +
    "YXA6IDZweDsgYWxpZ24taXRlbXM6IGNlbnRlcjsganVzdGlmeS1jb250ZW50OiBzcGFjZS1iZXR3" +
    "ZWVuOyBmbGV4LXdyYXA6IHdyYXA7IH0KLmNoaXBzIHsgZGlzcGxheTogZmxleDsgZ2FwOiA0cHg7" +
    "IGZsZXgtd3JhcDogd3JhcDsgfQouY2hpcCB7IGZvbnQtc2l6ZTogOXB4OyBwYWRkaW5nOiAycHgg" +
    "N3B4OyBib3JkZXItcmFkaXVzOiAyMHB4OyBiYWNrZ3JvdW5kOiByZ2JhKDI1NSwyNTUsMjU1LDAu" +
    "MDUpOyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBib3JkZXI6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIp" +
    "OyB9Ci5hY3QtYnRuIHsgZm9udC1zaXplOiAxMHB4OyBwYWRkaW5nOiA0cHggMTBweDsgYm9yZGVy" +
    "LXJhZGl1czogNnB4OyBib3JkZXI6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIyKTsgYmFja2dyb3Vu" +
    "ZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGN1cnNvcjogcG9pbnRlcjsgdHJh" +
    "bnNpdGlvbjogYWxsIDAuMTVzOyB9Ci5hY3QtYnRuOmhvdmVyIHsgYmFja2dyb3VuZDogcmdiYSgy" +
    "NTUsMjU1LDI1NSwwLjA2KTsgY29sb3I6IHZhcigtLXRleHQpOyB9Ci5hY3QtYnRuLnNhdmVkIHsg" +
    "Ym9yZGVyLWNvbG9yOiByZ2JhKDE2LDE4NSwxMjksMC40KTsgY29sb3I6IHZhcigtLWdyZWVuKTsg" +
    "YmFja2dyb3VuZDogcmdiYSgxNiwxODUsMTI5LDAuMSk7IH0KLmV4cGFuZC1ib3ggeyBkaXNwbGF5" +
    "OiBub25lOyBtYXJnaW4tdG9wOiAxMHB4OyBib3JkZXItdG9wOiAxcHggc29saWQgdmFyKC0tYm9y" +
    "ZGVyKTsgcGFkZGluZy10b3A6IDEwcHg7IH0KLnNvdXJjZS1saW5rIHsgZGlzcGxheTogZmxleDsg" +
    "YWxpZ24taXRlbXM6IGZsZXgtc3RhcnQ7IGdhcDogOHB4OyBwYWRkaW5nOiA2cHggMDsgYm9yZGVy" +
    "LWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IHRleHQtZGVjb3JhdGlvbjogbm9uZTsg" +
    "Y29sb3I6IGluaGVyaXQ7IH0KLnNvdXJjZS1saW5rOmxhc3QtY2hpbGQgeyBib3JkZXItYm90dG9t" +
    "OiBub25lOyB9Ci5zb3VyY2UtbGluazpob3ZlciAuc2wtdGl0bGUgeyBjb2xvcjogdmFyKC0tYWNj" +
    "ZW50Mik7IH0KLnNsLWljb24geyBmb250LXNpemU6IDhweDsgZm9udC13ZWlnaHQ6IDcwMDsgY29s" +
    "b3I6ICNmZmY7IGJvcmRlci1yYWRpdXM6IDRweDsgcGFkZGluZzogMnB4IDVweDsgZmxleC1zaHJp" +
    "bms6IDA7IG1hcmdpbi10b3A6IDJweDsgfQouc2wtcmVkZGl0IHsgYmFja2dyb3VuZDogI0UyNEI0" +
    "QTsgfSAuc2wtbmV3cyB7IGJhY2tncm91bmQ6IHZhcigtLWJsdWUpOyB9IC5zbC10cmVuZHMgeyBi" +
    "YWNrZ3JvdW5kOiB2YXIoLS1ncmVlbik7IH0gLnNsLWxpZmVzdHlsZSB7IGJhY2tncm91bmQ6IHZh" +
    "cigtLWFtYmVyKTsgfQouc2wtdGl0bGUgeyBmb250LXNpemU6IDExcHg7IGNvbG9yOiB2YXIoLS10" +
    "ZXh0KTsgbGluZS1oZWlnaHQ6IDEuNDsgfQouc2wtc291cmNlIHsgZm9udC1zaXplOiAxMHB4OyBj" +
    "b2xvcjogdmFyKC0tbXV0ZWQpOyBtYXJnaW4tdG9wOiAxcHg7IH0KLmhpbnQtYm94IHsgZGlzcGxh" +
    "eTogbm9uZTsgbWFyZ2luLXRvcDogMTBweDsgYm9yZGVyLXRvcDogMXB4IHNvbGlkIHZhcigtLWJv" +
    "cmRlcik7IHBhZGRpbmctdG9wOiAxMHB4OyBmb250LXNpemU6IDEycHg7IGZvbnQtc3R5bGU6IGl0" +
    "YWxpYzsgY29sb3I6IHZhcigtLWFjY2VudDIpOyBsaW5lLWhlaWdodDogMS41OyB9CgouaGVhZGxp" +
    "bmUtaXRlbSB7IGRpc3BsYXk6IGZsZXg7IGdhcDogOHB4OyBwYWRkaW5nOiA3cHggMDsgYm9yZGVy" +
    "LWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLmhlYWRsaW5lLWl0ZW06bGFzdC1j" +
    "aGlsZCB7IGJvcmRlci1ib3R0b206IG5vbmU7IH0KLmgtZG90IHsgd2lkdGg6IDVweDsgaGVpZ2h0" +
    "OiA1cHg7IGJvcmRlci1yYWRpdXM6IDUwJTsgbWFyZ2luLXRvcDogNnB4OyBmbGV4LXNocmluazog" +
    "MDsgfQouaC10aXRsZSB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6IHZhcigtLXRleHQpOyBsaW5l" +
    "LWhlaWdodDogMS40OyB9Ci5oLWxpbmsgeyBmb250LXNpemU6IDEwcHg7IGNvbG9yOiB2YXIoLS1h" +
    "Y2NlbnQyKTsgdGV4dC1kZWNvcmF0aW9uOiBub25lOyBkaXNwbGF5OiBibG9jazsgbWFyZ2luLXRv" +
    "cDogMnB4OyB9Ci5oLWxpbms6aG92ZXIgeyB0ZXh0LWRlY29yYXRpb246IHVuZGVybGluZTsgfQou" +
    "c3JjLWdyb3VwIHsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiA2MDA7IGNvbG9yOiB2YXIo" +
    "LS1tdXRlZCk7IHRleHQtdHJhbnNmb3JtOiB1cHBlcmNhc2U7IGxldHRlci1zcGFjaW5nOiAwLjhw" +
    "eDsgcGFkZGluZzogOHB4IDAgNHB4OyB9CgoucmVzZWFyY2gtaXRlbSB7IHBhZGRpbmc6IDEwcHgg" +
    "MDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLnJlc2VhcmNoLWl0" +
    "ZW06bGFzdC1jaGlsZCB7IGJvcmRlci1ib3R0b206IG5vbmU7IH0KLnJlc2VhcmNoLXRpdGxlIHsg" +
    "Zm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogNTAwOyBjb2xvcjogdmFyKC0tdGV4dCk7IGxp" +
    "bmUtaGVpZ2h0OiAxLjQ7IG1hcmdpbi1ib3R0b206IDRweDsgfQoucmVzZWFyY2gtdGl0bGUgYSB7" +
    "IGNvbG9yOiBpbmhlcml0OyB0ZXh0LWRlY29yYXRpb246IG5vbmU7IH0KLnJlc2VhcmNoLXRpdGxl" +
    "IGE6aG92ZXIgeyBjb2xvcjogdmFyKC0tYWNjZW50Mik7IH0KLnJlc2VhcmNoLWRlc2MgeyBmb250" +
    "LXNpemU6IDExcHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGxpbmUtaGVpZ2h0OiAxLjU7IG1hcmdp" +
    "bi1ib3R0b206IDVweDsgfQoucmVzZWFyY2gtbWV0YSB7IGRpc3BsYXk6IGZsZXg7IGdhcDogNnB4" +
    "OyB9Ci5yLXNyYyB7IGZvbnQtc2l6ZTogOXB4OyBwYWRkaW5nOiAycHggN3B4OyBib3JkZXItcmFk" +
    "aXVzOiAyMHB4OyBiYWNrZ3JvdW5kOiByZ2JhKDE2LDE4NSwxMjksMC4wOCk7IGNvbG9yOiB2YXIo" +
    "LS1ncmVlbik7IGJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMTYsMTg1LDEyOSwwLjIpOyB9Ci5yLXR5" +
    "cGUgeyBmb250LXNpemU6IDlweDsgcGFkZGluZzogMnB4IDdweDsgYm9yZGVyLXJhZGl1czogMjBw" +
    "eDsgYmFja2dyb3VuZDogcmdiYSgyNTUsMjU1LDI1NSwwLjA0KTsgY29sb3I6IHZhcigtLW11dGVk" +
    "KTsgfQoKLnNhdmVkLWl0ZW0geyBkaXNwbGF5OiBmbGV4OyBhbGlnbi1pdGVtczogY2VudGVyOyBq" +
    "dXN0aWZ5LWNvbnRlbnQ6IHNwYWNlLWJldHdlZW47IHBhZGRpbmc6IDdweCAwOyBib3JkZXItYm90" +
    "dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgfQouc2F2ZWQtaXRlbTpsYXN0LWNoaWxkIHsg" +
    "Ym9yZGVyLWJvdHRvbTogbm9uZTsgfQouc2F2ZWQtbmFtZSB7IGZvbnQtc2l6ZTogMTJweDsgY29s" +
    "b3I6IHZhcigtLXRleHQpOyBmbGV4OiAxOyB9Ci50YWctaW5wdXQgeyBmb250LXNpemU6IDEwcHg7" +
    "IGJvcmRlcjogMXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBib3JkZXItcmFkaXVzOiA2cHg7IHBh" +
    "ZGRpbmc6IDNweCA4cHg7IGJhY2tncm91bmQ6IHJnYmEoMjU1LDI1NSwyNTUsMC4wNCk7IGNvbG9y" +
    "OiB2YXIoLS1tdXRlZCk7IHdpZHRoOiA3MHB4OyBvdXRsaW5lOiBub25lOyB9Ci50YWctaW5wdXQ6" +
    "OnBsYWNlaG9sZGVyIHsgY29sb3I6IHJnYmEoMjU1LDI1NSwyNTUsMC4xNSk7IH0KLmdlbi1idG4g" +
    "eyB3aWR0aDogMTAwJTsgbWFyZ2luLXRvcDogMTBweDsgcGFkZGluZzogOXB4OyBib3JkZXItcmFk" +
    "aXVzOiA4cHg7IGJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMTY4LDg1LDI0NywwLjMpOyBiYWNrZ3Jv" +
    "dW5kOiByZ2JhKDEyNCw1OCwyMzcsMC4xKTsgY29sb3I6IHZhcigtLWFjY2VudDIpOyBmb250LXNp" +
    "emU6IDEycHg7IGZvbnQtd2VpZ2h0OiA1MDA7IGN1cnNvcjogcG9pbnRlcjsgdHJhbnNpdGlvbjog" +
    "YWxsIDAuMTVzOyB9Ci5nZW4tYnRuOmhvdmVyIHsgYmFja2dyb3VuZDogcmdiYSgxMjQsNTgsMjM3" +
    "LDAuMik7IH0KCi5mb3JtYXQtaXRlbSB7IHBhZGRpbmc6IDEycHggMDsgYm9yZGVyLWJvdHRvbTog" +
    "MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLmZvcm1hdC1pdGVtOmxhc3QtY2hpbGQgeyBib3Jk" +
    "ZXItYm90dG9tOiBub25lOyB9Ci5mb3JtYXQtdGl0bGUgeyBmb250LXNpemU6IDEzcHg7IGZvbnQt" +
    "d2VpZ2h0OiA2MDA7IGNvbG9yOiAjZmZmOyBtYXJnaW4tYm90dG9tOiA0cHg7IH0KLmZvcm1hdC1s" +
    "b2dsaW5lIHsgZm9udC1zaXplOiAxMnB4OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBsaW5lLWhlaWdo" +
    "dDogMS41OyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLmZvcm1hdC1ob29rIHsgZm9udC1zaXplOiAx" +
    "MXB4OyBjb2xvcjogcmdiYSgxNjgsODUsMjQ3LDAuNzUpOyBmb250LXN0eWxlOiBpdGFsaWM7IG1h" +
    "cmdpbi10b3A6IDVweDsgfQouZGV2LWJ0biB7IGRpc3BsYXk6IGlubGluZS1ibG9jazsgZm9udC1z" +
    "aXplOiAxMHB4OyBwYWRkaW5nOiA0cHggMTBweDsgYm9yZGVyLXJhZGl1czogNnB4OyBib3JkZXI6" +
    "IDFweCBzb2xpZCByZ2JhKDE2LDE4NSwxMjksMC40KTsgYmFja2dyb3VuZDogcmdiYSgxNiwxODUs" +
    "MTI5LDAuMDgpOyBjb2xvcjogdmFyKC0tZ3JlZW4pOyBjdXJzb3I6IHBvaW50ZXI7IG1hcmdpbi10" +
    "b3A6IDhweDsgdHJhbnNpdGlvbjogYWxsIDAuMTVzOyB9Ci5kZXYtYnRuOmhvdmVyIHsgYmFja2dy" +
    "b3VuZDogcmdiYSgxNiwxODUsMTI5LDAuMTUpOyB9Ci5kZXYtcGFuZWwgeyBiYWNrZ3JvdW5kOiB2" +
    "YXIoLS1jYXJkKTsgYm9yZGVyOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgYm9yZGVyLXJhZGl1" +
    "czogMTJweDsgbWFyZ2luLXRvcDogMTZweDsgb3ZlcmZsb3c6IGhpZGRlbjsgZGlzcGxheTogbm9u" +
    "ZTsgfQouZGV2LXBhbmVsLWhlYWRlciB7IHBhZGRpbmc6IDEycHggMTZweDsgYm9yZGVyLWJvdHRv" +
    "bTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLmRldi1wYW5lbC10aXRsZSB7IGZvbnQtc2l6" +
    "ZTogMTJweDsgZm9udC13ZWlnaHQ6IDYwMDsgY29sb3I6IHZhcigtLWdyZWVuKTsgfQouZGV2LXBh" +
    "bmVsLXN1YnRpdGxlIHsgZm9udC1zaXplOiAxMXB4OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBtYXJn" +
    "aW4tdG9wOiAycHg7IH0KLmRldi1jaGF0IHsgaGVpZ2h0OiAzNjBweDsgb3ZlcmZsb3cteTogYXV0" +
    "bzsgcGFkZGluZzogMTZweDsgZGlzcGxheTogZmxleDsgZmxleC1kaXJlY3Rpb246IGNvbHVtbjsg" +
    "Z2FwOiAxMHB4OyB9Ci5kZXYtbXNnIHsgbWF4LXdpZHRoOiA4NSU7IHBhZGRpbmc6IDEwcHggMTRw" +
    "eDsgYm9yZGVyLXJhZGl1czogMTBweDsgZm9udC1zaXplOiAxM3B4OyBsaW5lLWhlaWdodDogMS42" +
    "OyB9Ci5kZXYtbXNnLmFpIHsgYmFja2dyb3VuZDogdmFyKC0tY2FyZDIpOyBjb2xvcjogdmFyKC0t" +
    "dGV4dCk7IGFsaWduLXNlbGY6IGZsZXgtc3RhcnQ7IGJvcmRlci1ib3R0b20tbGVmdC1yYWRpdXM6" +
    "IDNweDsgfQouZGV2LW1zZy51c2VyIHsgYmFja2dyb3VuZDogcmdiYSgxMjQsNTgsMjM3LDAuMTUp" +
    "OyBjb2xvcjogdmFyKC0tdGV4dCk7IGFsaWduLXNlbGY6IGZsZXgtZW5kOyBib3JkZXItYm90dG9t" +
    "LXJpZ2h0LXJhZGl1czogM3B4OyBib3JkZXI6IDFweCBzb2xpZCByZ2JhKDEyNCw1OCwyMzcsMC4y" +
    "NSk7IH0KLmRldi1pbnB1dC1yb3cgeyBkaXNwbGF5OiBmbGV4OyBnYXA6IDhweDsgcGFkZGluZzog" +
    "MTJweCAxNnB4OyBib3JkZXItdG9wOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgfQouZGV2LWlu" +
    "cHV0IHsgZmxleDogMTsgZm9udC1zaXplOiAxM3B4OyBwYWRkaW5nOiA5cHggMTRweDsgYm9yZGVy" +
    "LXJhZGl1czogOHB4OyBib3JkZXI6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIyKTsgYmFja2dyb3Vu" +
    "ZDogcmdiYSgyNTUsMjU1LDI1NSwwLjA0KTsgY29sb3I6IHZhcigtLXRleHQpOyBvdXRsaW5lOiBu" +
    "b25lOyBmb250LWZhbWlseTogaW5oZXJpdDsgfQouZGV2LWlucHV0OjpwbGFjZWhvbGRlciB7IGNv" +
    "bG9yOiByZ2JhKDI1NSwyNTUsMjU1LDAuMik7IH0KLmRldi1zZW5kIHsgZm9udC1zaXplOiAxMnB4" +
    "OyBmb250LXdlaWdodDogNjAwOyBwYWRkaW5nOiA5cHggMTZweDsgYm9yZGVyLXJhZGl1czogOHB4" +
    "OyBib3JkZXI6IG5vbmU7IGJhY2tncm91bmQ6IGxpbmVhci1ncmFkaWVudCgxMzVkZWcsIHZhcigt" +
    "LWFjY2VudCksIHZhcigtLWFjY2VudDIpKTsgY29sb3I6ICNmZmY7IGN1cnNvcjogcG9pbnRlcjsg" +
    "d2hpdGUtc3BhY2U6IG5vd3JhcDsgfQouZGV2LXNlbmQ6ZGlzYWJsZWQgeyBvcGFjaXR5OiAwLjQ7" +
    "IGN1cnNvcjogbm90LWFsbG93ZWQ7IH0KCi5hcmNoaXZlLWxheW91dCB7IGRpc3BsYXk6IGdyaWQ7" +
    "IGdyaWQtdGVtcGxhdGUtY29sdW1uczogMTcwcHggMWZyOyBnYXA6IDIwcHg7IH0KQG1lZGlhICht" +
    "YXgtd2lkdGg6IDcwMHB4KSB7IC5hcmNoaXZlLWxheW91dCB7IGdyaWQtdGVtcGxhdGUtY29sdW1u" +
    "czogMWZyOyB9IH0KLmRhdGUtaXRlbSB7IHBhZGRpbmc6IDdweCAxMHB4OyBib3JkZXItcmFkaXVz" +
    "OiA4cHg7IGN1cnNvcjogcG9pbnRlcjsgZm9udC1zaXplOiAxMnB4OyBjb2xvcjogdmFyKC0tbXV0" +
    "ZWQpOyBtYXJnaW4tYm90dG9tOiAycHg7IGRpc3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50" +
    "ZXI7IGp1c3RpZnktY29udGVudDogc3BhY2UtYmV0d2VlbjsgdHJhbnNpdGlvbjogYWxsIDAuMTVz" +
    "OyB9Ci5kYXRlLWl0ZW06aG92ZXIgeyBiYWNrZ3JvdW5kOiByZ2JhKDI1NSwyNTUsMjU1LDAuMDUp" +
    "OyBjb2xvcjogdmFyKC0tdGV4dCk7IH0KLmRhdGUtaXRlbS5hY3RpdmUgeyBiYWNrZ3JvdW5kOiB2" +
    "YXIoLS1nbG93KTsgY29sb3I6ICNmZmY7IH0KLmRhdGUtY291bnQgeyBmb250LXNpemU6IDEwcHg7" +
    "IG9wYWNpdHk6IDAuNTsgfQouYXJjaC1pdGVtIHsgcGFkZGluZzogMTJweCAwOyBib3JkZXItYm90" +
    "dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgfQouYXJjaC1pdGVtOmxhc3QtY2hpbGQgeyBi" +
    "b3JkZXItYm90dG9tOiBub25lOyB9Ci5hcmNoLW5hbWUgeyBmb250LXNpemU6IDEzcHg7IGZvbnQt" +
    "d2VpZ2h0OiA2MDA7IGNvbG9yOiAjZmZmOyB9Ci5hcmNoLW1ldGEgeyBmb250LXNpemU6IDEwcHg7" +
    "IGNvbG9yOiB2YXIoLS1tdXRlZCk7IG1hcmdpbjogM3B4IDAgNXB4OyB9Ci5hcmNoLWRlc2MgeyBm" +
    "b250LXNpemU6IDEycHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGxpbmUtaGVpZ2h0OiAxLjU7IH0K" +
    "LmFyY2gtbGluayB7IGZvbnQtc2l6ZTogMTBweDsgY29sb3I6IHZhcigtLWFjY2VudDIpOyB0ZXh0" +
    "LWRlY29yYXRpb246IG5vbmU7IGRpc3BsYXk6IGJsb2NrOyBtYXJnaW4tdG9wOiAzcHg7IH0KLmFy" +
    "Y2gtbGluazpob3ZlciB7IHRleHQtZGVjb3JhdGlvbjogdW5kZXJsaW5lOyB9Cgouc2VjdGlvbi1n" +
    "YXAgeyBtYXJnaW4tdG9wOiAxNHB4OyB9Ci5lbXB0eSB7IHRleHQtYWxpZ246IGNlbnRlcjsgcGFk" +
    "ZGluZzogMnJlbTsgY29sb3I6IHZhcigtLW11dGVkKTsgZm9udC1zaXplOiAxMnB4OyB9Ci5lcnJi" +
    "b3ggeyBiYWNrZ3JvdW5kOiByZ2JhKDIzOSw2OCw2OCwwLjA4KTsgYm9yZGVyOiAxcHggc29saWQg" +
    "cmdiYSgyMzksNjgsNjgsMC4yNSk7IGJvcmRlci1yYWRpdXM6IDhweDsgcGFkZGluZzogMTBweCAx" +
    "NHB4OyBmb250LXNpemU6IDEycHg7IGNvbG9yOiAjZmNhNWE1OyBtYXJnaW4tYm90dG9tOiAxNnB4" +
    "OyB9Ci5sb2FkZXIgeyBkaXNwbGF5OiBpbmxpbmUtYmxvY2s7IHdpZHRoOiAxMHB4OyBoZWlnaHQ6" +
    "IDEwcHg7IGJvcmRlcjogMS41cHggc29saWQgdmFyKC0tYm9yZGVyMik7IGJvcmRlci10b3AtY29s" +
    "b3I6IHZhcigtLWFjY2VudDIpOyBib3JkZXItcmFkaXVzOiA1MCU7IGFuaW1hdGlvbjogc3BpbiAw" +
    "LjdzIGxpbmVhciBpbmZpbml0ZTsgdmVydGljYWwtYWxpZ246IG1pZGRsZTsgbWFyZ2luLXJpZ2h0" +
    "OiA1cHg7IH0KQGtleWZyYW1lcyBzcGluIHsgdG8geyB0cmFuc2Zvcm06IHJvdGF0ZSgzNjBkZWcp" +
    "OyB9IH0KPC9zdHlsZT4KPC9oZWFkPgo8Ym9keT4KCjxkaXYgY2xhc3M9InNpZGViYXIiPgogIDxk" +
    "aXYgY2xhc3M9InNpZGViYXItbG9nbyI+CiAgICA8ZGl2IGNsYXNzPSJuYW1lIj5UcmVudHJhZGFy" +
    "PC9kaXY+CiAgICA8ZGl2IGNsYXNzPSJ0YWdsaW5lIj5DdWx0dXJhbCBzaWduYWwgaW50ZWxsaWdl" +
    "bmNlPC9kaXY+CiAgPC9kaXY+CiAgPGRpdiBjbGFzcz0ic2lkZWJhci1zZWN0aW9uIj4KICAgIDxk" +
    "aXYgY2xhc3M9InNpZGViYXItc2VjdGlvbi1sYWJlbCI+Vmlld3M8L2Rpdj4KICAgIDxkaXYgY2xh" +
    "c3M9Im5hdi1pdGVtIGFjdGl2ZSIgaWQ9Im5hdi1kIiBvbmNsaWNrPSJzd2l0Y2hWaWV3KCdkYXNo" +
    "Ym9hcmQnKSI+CiAgICAgIDxzcGFuIGNsYXNzPSJuYXYtZG90Ij48L3NwYW4+IERhc2hib2FyZAog" +
    "ICAgPC9kaXY+CiAgICA8ZGl2IGNsYXNzPSJuYXYtaXRlbSIgaWQ9Im5hdi1hIiBvbmNsaWNrPSJz" +
    "d2l0Y2hWaWV3KCdhcmNoaXZlJykiPgogICAgICA8c3BhbiBjbGFzcz0ibmF2LWRvdCI+PC9zcGFu" +
    "PiBBcmNoaXZlCiAgICA8L2Rpdj4KICA8L2Rpdj4KICA8ZGl2IGNsYXNzPSJzaWRlYmFyLXNvdXJj" +
    "ZXMiPgogICAgPGRpdiBjbGFzcz0ic2lkZWJhci1zb3VyY2VzLWxhYmVsIj5BY3RpdmUgc291cmNl" +
    "czwvZGl2PgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5OVS5ubDwvc3Bhbj4KICAgIDxz" +
    "cGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+QUQubmw8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3Jj" +
    "LXBpbGwgb24iPlZvbGtza3JhbnQ8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24i" +
    "PlBhcm9vbDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+TGliZWxsZTwvc3Bh" +
    "bj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+TGluZGEubmw8L3NwYW4+CiAgICA8c3Bh" +
    "biBjbGFzcz0ic3JjLXBpbGwgb24iPlJUTDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGls" +
    "bCBvbiI+UmVkZGl0PC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5Hb29nbGUg" +
    "VHJlbmRzPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5TQ1A8L3NwYW4+CiAg" +
    "ICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPkNCUzwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJz" +
    "cmMtcGlsbCBvbiI+UGV3IFJlc2VhcmNoPC9zcGFuPgogIDwvZGl2Pgo8L2Rpdj4KCjxkaXYgY2xh" +
    "c3M9Im1haW4iPgogIDxkaXYgY2xhc3M9InRvcGJhciI+CiAgICA8ZGl2IGNsYXNzPSJ0b3BiYXIt" +
    "dGl0bGUiIGlkPSJwYWdlLXRpdGxlIj5EYXNoYm9hcmQ8L2Rpdj4KICAgIDxkaXYgY2xhc3M9InRv" +
    "cGJhci1yaWdodCIgaWQ9InNjYW4tY29udHJvbHMiPgogICAgICA8c2VsZWN0IGNsYXNzPSJzZWwi" +
    "IGlkPSJyZWdpb24tc2VsIj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJubCI+TkwgZm9jdXM8L29w" +
    "dGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJldSI+RVUgLyBnbG9iYWw8L29wdGlvbj4KICAg" +
    "ICAgICA8b3B0aW9uIHZhbHVlPSJhbGwiPkFsbCBtYXJrZXRzPC9vcHRpb24+CiAgICAgIDwvc2Vs" +
    "ZWN0PgogICAgICA8c2VsZWN0IGNsYXNzPSJzZWwiIGlkPSJob3Jpem9uLXNlbCI+CiAgICAgICAg" +
    "PG9wdGlvbiB2YWx1ZT0iZW1lcmdpbmciPkVtZXJnaW5nPC9vcHRpb24+CiAgICAgICAgPG9wdGlv" +
    "biB2YWx1ZT0icmlzaW5nIj5SaXNpbmc8L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJh" +
    "bGwiPkFsbCBzaWduYWxzPC9vcHRpb24+CiAgICAgIDwvc2VsZWN0PgogICAgICA8YnV0dG9uIGNs" +
    "YXNzPSJzY2FuLWJ0biIgaWQ9InNjYW4tYnRuIiBvbmNsaWNrPSJydW5TY2FuKCkiPlNjYW4gbm93" +
    "PC9idXR0b24+CiAgICA8L2Rpdj4KICA8L2Rpdj4KCiAgPGRpdiBjbGFzcz0iY29udGVudCI+CiAg" +
    "ICA8ZGl2IGlkPSJ2aWV3LWRhc2hib2FyZCI+CiAgICAgIDxkaXYgY2xhc3M9InN0YXR1cy1iYXIi" +
    "PgogICAgICAgIDxkaXYgY2xhc3M9InN0YXR1cy1kb3QiIGlkPSJzdGF0dXMtZG90Ij48L2Rpdj4K" +
    "ICAgICAgICA8c3BhbiBpZD0ic3RhdHVzLXRleHQiPlJlYWR5IHRvIHNjYW48L3NwYW4+CiAgICAg" +
    "ICAgPHNwYW4gaWQ9ImhlYWRsaW5lLWNvdW50IiBzdHlsZT0iY29sb3I6cmdiYSgyNTUsMjU1LDI1" +
    "NSwwLjIpIj48L3NwYW4+CiAgICAgIDwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJwcm9ncmVzcy1i" +
    "YXIiPjxkaXYgY2xhc3M9InByb2dyZXNzLWZpbGwiIGlkPSJwcm9ncmVzcy1maWxsIj48L2Rpdj48" +
    "L2Rpdj4KICAgICAgPGRpdiBpZD0iZXJyLWJveCI+PC9kaXY+CgogICAgICA8ZGl2IGNsYXNzPSJn" +
    "cmlkLTMiPgogICAgICAgIDxkaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkIj4KICAgICAg" +
    "ICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiIHN0eWxlPSJwYWRkaW5nLWJvdHRvbTowIj4K" +
    "ICAgICAgICAgICAgICA8ZGl2IGNsYXNzPSJ0YWJzIj4KICAgICAgICAgICAgICAgIDxidXR0b24g" +
    "Y2xhc3M9InRhYi1idG4gYWN0aXZlIiBpZD0idGFiLXQiIG9uY2xpY2s9InN3aXRjaFRhYigndHJl" +
    "bmRzJykiPkN1bHR1cmFsIHRyZW5kczwvYnV0dG9uPgogICAgICAgICAgICAgICAgPGJ1dHRvbiBj" +
    "bGFzcz0idGFiLWJ0biIgaWQ9InRhYi1mIiBvbmNsaWNrPSJzd2l0Y2hUYWIoJ2Zvcm1hdHMnKSI+" +
    "Rm9ybWF0IGlkZWFzPC9idXR0b24+CiAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDwv" +
    "ZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHkiPgogICAgICAgICAgICAgIDxk" +
    "aXYgaWQ9InBhbmUtdHJlbmRzIj48ZGl2IGlkPSJ0cmVuZHMtbGlzdCI+PGRpdiBjbGFzcz0iZW1w" +
    "dHkiPlByZXNzICJTY2FuIG5vdyIgdG8gZGV0ZWN0IHRyZW5kcy48L2Rpdj48L2Rpdj48L2Rpdj4K" +
    "ICAgICAgICAgICAgICA8ZGl2IGlkPSJwYW5lLWZvcm1hdHMiIHN0eWxlPSJkaXNwbGF5Om5vbmUi" +
    "PgogICAgICAgICAgICAgICAgPGRpdiBpZD0iZm9ybWF0cy1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0" +
    "eSI+U2F2ZSB0cmVuZHMsIHRoZW4gZ2VuZXJhdGUgZm9ybWF0IGlkZWFzLjwvZGl2PjwvZGl2Pgog" +
    "ICAgICAgICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsIiBpZD0iZGV2LXBhbmVsIj4KICAg" +
    "ICAgICAgICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsLWhlYWRlciI+CiAgICAgICAgICAg" +
    "ICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsLXRpdGxlIj4mIzk2Nzk7IEZvcm1hdCBEZXZl" +
    "bG9wbWVudCBTZXNzaW9uPC9kaXY+CiAgICAgICAgICAgICAgICAgICAgPGRpdiBjbGFzcz0iZGV2" +
    "LXBhbmVsLXN1YnRpdGxlIiBpZD0iZGV2LXBhbmVsLXN1YnRpdGxlIj5EZXZlbG9waW5nOiAmbWRh" +
    "c2g7PC9kaXY+CiAgICAgICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgICAgICA8ZGl2" +
    "IGNsYXNzPSJkZXYtY2hhdCIgaWQ9ImRldi1jaGF0Ij48L2Rpdj4KICAgICAgICAgICAgICAgICAg" +
    "PGRpdiBjbGFzcz0iZGV2LWlucHV0LXJvdyI+CiAgICAgICAgICAgICAgICAgICAgPGlucHV0IGNs" +
    "YXNzPSJkZXYtaW5wdXQiIGlkPSJkZXYtaW5wdXQiIHR5cGU9InRleHQiIHBsYWNlaG9sZGVyPSJS" +
    "ZXBseSB0byB5b3VyIGRldmVsb3BtZW50IGV4ZWMuLi4iIG9ua2V5ZG93bj0iaWYoZXZlbnQua2V5" +
    "PT09J0VudGVyJylzZW5kRGV2TWVzc2FnZSgpIiAvPgogICAgICAgICAgICAgICAgICAgIDxidXR0" +
    "b24gY2xhc3M9ImRldi1zZW5kIiBpZD0iZGV2LXNlbmQiIG9uY2xpY2s9InNlbmREZXZNZXNzYWdl" +
    "KCkiPlNlbmQ8L2J1dHRvbj4KICAgICAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAg" +
    "ICA8L2Rpdj4KICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAg" +
    "ICA8L2Rpdj4KICAgICAgICA8L2Rpdj4KCiAgICAgICAgPGRpdj4KICAgICAgICAgIDxkaXYgY2xh" +
    "c3M9ImNhcmQiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciI+PGRpdiBjbGFz" +
    "cz0iY2FyZC10aXRsZSI+U2xvdyB0cmVuZHMgJm1kYXNoOyByZXNlYXJjaCAmYW1wOyByZXBvcnRz" +
    "PC9kaXY+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+PGRpdiBpZD0i" +
    "cmVzZWFyY2gtZmVlZCI+PGRpdiBjbGFzcz0iZW1wdHkiPlJlc2VhcmNoIGxvYWRzIHdoZW4geW91" +
    "IHNjYW4uPC9kaXY+PC9kaXY+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj4K" +
    "CiAgICAgICAgPGRpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAgICAgICAgICA8" +
    "ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+TGl2ZSBoZWFk" +
    "bGluZXM8L2Rpdj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5Ij48ZGl2" +
    "IGlkPSJzaWduYWwtZmVlZCI+PGRpdiBjbGFzcz0iZW1wdHkiPkhlYWRsaW5lcyBhcHBlYXIgYWZ0" +
    "ZXIgc2Nhbm5pbmcuPC9kaXY+PC9kaXY+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICAg" +
    "IDxkaXYgY2xhc3M9ImNhcmQgc2VjdGlvbi1nYXAiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJj" +
    "YXJkLWhlYWRlciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+U2F2ZWQgdHJlbmRzPC9kaXY+PC9k" +
    "aXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+CiAgICAgICAgICAgICAgPGRp" +
    "diBpZD0ic2F2ZWQtbGlzdCI+PGRpdiBjbGFzcz0iZW1wdHkiPk5vIHNhdmVkIHRyZW5kcyB5ZXQu" +
    "PC9kaXY+PC9kaXY+CiAgICAgICAgICAgICAgPGRpdiBpZD0iZ2VuLXJvdyIgc3R5bGU9ImRpc3Bs" +
    "YXk6bm9uZSI+PGJ1dHRvbiBjbGFzcz0iZ2VuLWJ0biIgb25jbGljaz0iZ2VuZXJhdGVGb3JtYXRz" +
    "KCkiPkdlbmVyYXRlIGZvcm1hdCBpZGVhcyAmcmFycjs8L2J1dHRvbj48L2Rpdj4KICAgICAgICAg" +
    "ICAgPC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgICAgPC9kaXY+CiAg" +
    "ICA8L2Rpdj4KCiAgICA8ZGl2IGlkPSJ2aWV3LWFyY2hpdmUiIHN0eWxlPSJkaXNwbGF5Om5vbmUi" +
    "PgogICAgICA8ZGl2IGlkPSJhcmNoaXZlLWVyciI+PC9kaXY+CgogICAgICA8IS0tIFNlbWFudGlj" +
    "IHNlYXJjaCBiYXIgLS0+CiAgICAgIDxkaXYgY2xhc3M9ImNhcmQiIHN0eWxlPSJtYXJnaW4tYm90" +
    "dG9tOjE2cHgiPgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJj" +
    "YXJkLXRpdGxlIj5TZWFyY2ggYXJjaGl2ZSBieSBjb25jZXB0IG9yIGZvcm1hdCBpZGVhPC9kaXY+" +
    "PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5IiBzdHlsZT0icGFkZGluZzoxNHB4" +
    "IDE2cHgiPgogICAgICAgICAgPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDoxMHB4O2FsaWdu" +
    "LWl0ZW1zOmNlbnRlciI+CiAgICAgICAgICAgIDxpbnB1dCBpZD0iYXJjaGl2ZS1zZWFyY2gtaW5w" +
    "dXQiIHR5cGU9InRleHQiCiAgICAgICAgICAgICAgcGxhY2Vob2xkZXI9ImUuZy4gJ2VlbnphYW1o" +
    "ZWlkIG9uZGVyIGpvbmdlcmVuJyBvciAnZmFtaWxpZXMgdW5kZXIgcHJlc3N1cmUnLi4uIgogICAg" +
    "ICAgICAgICAgIHN0eWxlPSJmbGV4OjE7Zm9udC1zaXplOjEzcHg7cGFkZGluZzo5cHggMTRweDti" +
    "b3JkZXItcmFkaXVzOjhweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpO2JhY2tncm91" +
    "bmQ6cmdiYSgyNTUsMjU1LDI1NSwwLjA0KTtjb2xvcjp2YXIoLS10ZXh0KTtvdXRsaW5lOm5vbmUi" +
    "CiAgICAgICAgICAgICAgb25rZXlkb3duPSJpZihldmVudC5rZXk9PT0nRW50ZXInKWRvQXJjaGl2" +
    "ZVNlYXJjaCgpIgogICAgICAgICAgICAvPgogICAgICAgICAgICA8YnV0dG9uIG9uY2xpY2s9ImRv" +
    "QXJjaGl2ZVNlYXJjaCgpIiBzdHlsZT0iZm9udC1zaXplOjEycHg7Zm9udC13ZWlnaHQ6NjAwO3Bh" +
    "ZGRpbmc6OXB4IDE4cHg7Ym9yZGVyLXJhZGl1czo4cHg7Ym9yZGVyOm5vbmU7YmFja2dyb3VuZDps" +
    "aW5lYXItZ3JhZGllbnQoMTM1ZGVnLHZhcigtLWFjY2VudCksdmFyKC0tYWNjZW50MikpO2NvbG9y" +
    "OiNmZmY7Y3Vyc29yOnBvaW50ZXI7d2hpdGUtc3BhY2U6bm93cmFwIj5TZWFyY2g8L2J1dHRvbj4K" +
    "ICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPGRpdiBpZD0ic2VhcmNoLXJlc3VsdHMiIHN0eWxl" +
    "PSJtYXJnaW4tdG9wOjEycHgiPjwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4KCiAg" +
    "ICAgIDwhLS0gQnJvd3NlIGJ5IGRhdGUgLS0+CiAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAg" +
    "ICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxlIj5TYXZl" +
    "ZCB0cmVuZHMgYXJjaGl2ZTwvZGl2PjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9k" +
    "eSIgc3R5bGU9InBhZGRpbmc6MTZweCI+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJhcmNoaXZlLWxh" +
    "eW91dCI+CiAgICAgICAgICAgIDxkaXY+CiAgICAgICAgICAgICAgPGRpdiBzdHlsZT0iZm9udC1z" +
    "aXplOjlweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJhbnNmb3Jt" +
    "OnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9tOjEwcHgiPkJ5IGRh" +
    "dGU8L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlkPSJkYXRlLWxpc3QiPjxkaXYgY2xhc3M9ImVt" +
    "cHR5IiBzdHlsZT0icGFkZGluZzoxcmVtIDAiPkxvYWRpbmcuLi48L2Rpdj48L2Rpdj4KICAgICAg" +
    "ICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXY+CiAgICAgICAgICAgICAgPGRpdiBzdHlsZT0i" +
    "Zm9udC1zaXplOjlweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJh" +
    "bnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9tOjEwcHgi" +
    "IGlkPSJhcmNoaXZlLWhlYWRpbmciPlNlbGVjdCBhIGRhdGU8L2Rpdj4KICAgICAgICAgICAgICA8" +
    "ZGl2IGlkPSJhcmNoaXZlLWNvbnRlbnQiPjxkaXYgY2xhc3M9ImVtcHR5Ij5TZWxlY3QgYSBkYXRl" +
    "LjwvZGl2PjwvZGl2PgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAg" +
    "IDwvZGl2PgogICAgICA8L2Rpdj4KICAgIDwvZGl2PgogIDwvZGl2Pgo8L2Rpdj4KCjxzY3JpcHQ+" +
    "CnZhciBzYXZlZCA9IFtdOwp2YXIgdHJlbmRzID0gW107CgpmdW5jdGlvbiBzd2l0Y2hWaWV3KHYp" +
    "IHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndmlldy1kYXNoYm9hcmQnKS5zdHlsZS5kaXNw" +
    "bGF5ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnJyA6ICdub25lJzsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgndmlldy1hcmNoaXZlJykuc3R5bGUuZGlzcGxheSA9IHYgPT09ICdhcmNoaXZlJyA/" +
    "ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzY2FuLWNvbnRyb2xzJyku" +
    "c3R5bGUuZGlzcGxheSA9IHYgPT09ICdkYXNoYm9hcmQnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ25hdi1kJykuY2xhc3NOYW1lID0gJ25hdi1pdGVtJyArICh2ID09" +
    "PSAnZGFzaGJvYXJkJyA/ICcgYWN0aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJ" +
    "ZCgnbmF2LWEnKS5jbGFzc05hbWUgPSAnbmF2LWl0ZW0nICsgKHYgPT09ICdhcmNoaXZlJyA/ICcg" +
    "YWN0aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncGFnZS10aXRsZScpLnRl" +
    "eHRDb250ZW50ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnRGFzaGJvYXJkJyA6ICdBcmNoaXZlJzsK" +
    "ICBpZiAodiA9PT0gJ2FyY2hpdmUnKSBsb2FkQXJjaGl2ZSgpOwp9CgpmdW5jdGlvbiBzd2l0Y2hU" +
    "YWIodCkgewogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYW5lLXRyZW5kcycpLnN0eWxlLmRp" +
    "c3BsYXkgPSB0ID09PSAndHJlbmRzJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdwYW5lLWZvcm1hdHMnKS5zdHlsZS5kaXNwbGF5ID0gdCA9PT0gJ2Zvcm1hdHMnID8g" +
    "JycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYi10JykuY2xhc3NOYW1l" +
    "ID0gJ3RhYi1idG4nICsgKHQgPT09ICd0cmVuZHMnID8gJyBhY3RpdmUnIDogJycpOwogIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCd0YWItZicpLmNsYXNzTmFtZSA9ICd0YWItYnRuJyArICh0ID09" +
    "PSAnZm9ybWF0cycgPyAnIGFjdGl2ZScgOiAnJyk7Cn0KCmZ1bmN0aW9uIHNob3dFcnIobXNnKSB7" +
    "IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdlcnItYm94JykuaW5uZXJIVE1MID0gJzxkaXYgY2xh" +
    "c3M9ImVycmJveCI+PHN0cm9uZz5FcnJvcjo8L3N0cm9uZz4gJyArIG1zZyArICc8L2Rpdj4nOyB9" +
    "CmZ1bmN0aW9uIGNsZWFyRXJyKCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZXJyLWJveCcp" +
    "LmlubmVySFRNTCA9ICcnOyB9CmZ1bmN0aW9uIHNldFByb2dyZXNzKHApIHsgZG9jdW1lbnQuZ2V0" +
    "RWxlbWVudEJ5SWQoJ3Byb2dyZXNzLWZpbGwnKS5zdHlsZS53aWR0aCA9IHAgKyAnJSc7IH0KZnVu" +
    "Y3Rpb24gc2V0U2Nhbm5pbmcob24pIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy1k" +
    "b3QnKS5jbGFzc05hbWUgPSAnc3RhdHVzLWRvdCcgKyAob24gPyAnIHNjYW5uaW5nJyA6ICcnKTsg" +
    "fQoKZnVuY3Rpb24gcnVuU2NhbigpIHsKICBjbGVhckVycigpOwogIHZhciBidG4gPSBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgnc2Nhbi1idG4nKTsKICBidG4uZGlzYWJsZWQgPSB0cnVlOyBidG4u" +
    "dGV4dENvbnRlbnQgPSAnU2Nhbm5pbmcuLi4nOwogIHNldFByb2dyZXNzKDEwKTsgc2V0U2Nhbm5p" +
    "bmcodHJ1ZSk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0JykuaW5uZXJI" +
    "VE1MID0gJzxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5GZXRjaGluZyBsaXZlIGhlYWRsaW5l" +
    "cy4uLic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2hlYWRsaW5lLWNvdW50JykudGV4dENv" +
    "bnRlbnQgPSAnJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndHJlbmRzLWxpc3QnKS5pbm5l" +
    "ckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5G" +
    "ZXRjaGluZyBtZWVzdCBnZWxlemVuLi4uPC9kaXY+JzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJ" +
    "ZCgnc2lnbmFsLWZlZWQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNs" +
    "YXNzPSJsb2FkZXIiPjwvc3Bhbj5Mb2FkaW5nLi4uPC9kaXY+JzsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgncmVzZWFyY2gtZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+" +
    "PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkxvYWRpbmcgcmVzZWFyY2guLi48L2Rpdj4nOwoK" +
    "ICB2YXIgcmVnaW9uID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3JlZ2lvbi1zZWwnKS52YWx1" +
    "ZTsKICB2YXIgaG9yaXpvbiA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdob3Jpem9uLXNlbCcp" +
    "LnZhbHVlOwoKICBmZXRjaCgnL3NjcmFwZScsIHsgbWV0aG9kOiAnUE9TVCcsIGhlYWRlcnM6IHsg" +
    "J0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBib2R5OiBKU09OLnN0cmluZ2lm" +
    "eSh7IHJlZ2lvbjogcmVnaW9uIH0pIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5q" +
    "c29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgdmFyIGhlYWRsaW5lcyA9IGQuaXRl" +
    "bXMgfHwgW107CiAgICBzZXRQcm9ncmVzcyg0MCk7CiAgICBpZiAoZC5lcnJvcikgewogICAgICBz" +
    "aG93SW5mbygnU2NyYXBlciBub3RlOiAnICsgZC5lcnJvciArICcg4oCUIHN5bnRoZXNpemluZyB0" +
    "cmVuZHMgZnJvbSBBSSBrbm93bGVkZ2UgaW5zdGVhZC4nKTsKICAgIH0KICAgIGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdoZWFkbGluZS1jb3VudCcpLnRleHRDb250ZW50ID0gaGVhZGxpbmVzLmxl" +
    "bmd0aCArICcgaGVhZGxpbmVzJzsKICAgIHJlbmRlckhlYWRsaW5lcyhoZWFkbGluZXMpOwogICAg" +
    "bG9hZFJlc2VhcmNoKCk7CiAgICByZXR1cm4gc3ludGhlc2l6ZVRyZW5kcyhoZWFkbGluZXMsIHJl" +
    "Z2lvbiwgaG9yaXpvbik7CiAgfSkKICAudGhlbihmdW5jdGlvbigpIHsgYnRuLmRpc2FibGVkID0g" +
    "ZmFsc2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7IHNldFNjYW5uaW5nKGZhbHNlKTsg" +
    "fSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgc2hvd0VycignU2NhbiBmYWlsZWQ6ICcgKyBl" +
    "Lm1lc3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0JykudGV4" +
    "dENvbnRlbnQgPSAnU2NhbiBmYWlsZWQuJzsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0" +
    "cmVuZHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+U2VlIGVycm9yIGFi" +
    "b3ZlLjwvZGl2Pic7CiAgICBzZXRQcm9ncmVzcygwKTsgc2V0U2Nhbm5pbmcoZmFsc2UpOwogICAg" +
    "YnRuLmRpc2FibGVkID0gZmFsc2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7CiAgfSk7" +
    "Cn0KCmZ1bmN0aW9uIHN5bnRoZXNpemVUcmVuZHMoaGVhZGxpbmVzLCByZWdpb24sIGhvcml6b24p" +
    "IHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS5pbm5lckhUTUwgPSAn" +
    "PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlN5bnRoZXNpemluZyB0cmVuZHMuLi4nOwogIHNl" +
    "dFByb2dyZXNzKDY1KTsKICB2YXIgaGVhZGxpbmVUZXh0ID0gaGVhZGxpbmVzLmxlbmd0aAogICAg" +
    "PyBoZWFkbGluZXMubWFwKGZ1bmN0aW9uKGgpIHsgcmV0dXJuICctIFsnICsgaC5zb3VyY2UgKyAn" +
    "XSAnICsgaC50aXRsZSArICcgKCcgKyBoLnVybCArICcpJzsgfSkuam9pbignXG4nKQogICAgOiAn" +
    "KE5vIGxpdmUgaGVhZGxpbmVzIC0gdXNlIHRyYWluaW5nIGtub3dsZWRnZSBmb3IgRHV0Y2ggY3Vs" +
    "dHVyYWwgdHJlbmRzKSc7CiAgdmFyIGhvcml6b25NYXAgPSB7IGVtZXJnaW5nOiAnZW1lcmdpbmcg" +
    "KHdlYWsgc2lnbmFscyknLCByaXNpbmc6ICdyaXNpbmcgKGdyb3dpbmcgbW9tZW50dW0pJywgYWxs" +
    "OiAnYWxsIG1vbWVudHVtIHN0YWdlcycgfTsKICB2YXIgcmVnaW9uTWFwID0geyBubDogJ0R1dGNo" +
    "IC8gTmV0aGVybGFuZHMnLCBldTogJ0V1cm9wZWFuJywgYWxsOiAnZ2xvYmFsIGluY2x1ZGluZyBO" +
    "TCcgfTsKICB2YXIgcHJvbXB0ID0gWwogICAgJ1lvdSBhcmUgYSBjdWx0dXJhbCB0cmVuZCBhbmFs" +
    "eXN0IGZvciBhIER1dGNoIHVuc2NyaXB0ZWQgVFYgZm9ybWF0IGRldmVsb3BtZW50IHRlYW0gdGhh" +
    "dCBkZXZlbG9wcyByZWFsaXR5IGFuZCBlbnRlcnRhaW5tZW50IGZvcm1hdHMuJywKICAgICcnLCAn" +
    "UmVhbCBoZWFkbGluZXMgZmV0Y2hlZCBOT1cgZnJvbSBEdXRjaCBtZWVzdC1nZWxlemVuIHNlY3Rp" +
    "b25zLCBHb29nbGUgVHJlbmRzIE5MLCBhbmQgUmVkZGl0OicsICcnLAogICAgaGVhZGxpbmVUZXh0" +
    "LCAnJywKICAgICdJZGVudGlmeSAnICsgKGhvcml6b25NYXBbaG9yaXpvbl0gfHwgJ2VtZXJnaW5n" +
    "JykgKyAnIGh1bWFuIGFuZCBjdWx0dXJhbCB0cmVuZHMgZm9yICcgKyAocmVnaW9uTWFwW3JlZ2lv" +
    "bl0gfHwgJ0R1dGNoJykgKyAnIGNvbnRleHQuJywKICAgICcnLAogICAgJ0lNUE9SVEFOVCDigJQg" +
    "Rm9jdXMgYXJlYXMgKHVzZSB0aGVzZSBhcyB0cmVuZCBldmlkZW5jZSk6JywKICAgICdIdW1hbiBj" +
    "b25uZWN0aW9uLCBpZGVudGl0eSwgYmVsb25naW5nLCBsb25lbGluZXNzLCByZWxhdGlvbnNoaXBz" +
    "LCBsaWZlc3R5bGUsIHdvcmsgY3VsdHVyZSwgYWdpbmcsIHlvdXRoLCBmYW1pbHkgZHluYW1pY3Ms" +
    "IHRlY2hub2xvZ3lcJ3MgZW1vdGlvbmFsIGltcGFjdCwgbW9uZXkgYW5kIGNsYXNzLCBoZWFsdGgg" +
    "YW5kIGJvZHksIGRhdGluZyBhbmQgbG92ZSwgZnJpZW5kc2hpcCwgaG91c2luZywgbGVpc3VyZSwg" +
    "Y3JlYXRpdml0eSwgc3Bpcml0dWFsaXR5LCBmb29kIGFuZCBjb25zdW1wdGlvbiBoYWJpdHMuJywK" +
    "ICAgICcnLAogICAgJ0lNUE9SVEFOVCDigJQgU3RyaWN0IGV4Y2x1c2lvbnMgKG5ldmVyIHVzZSB0" +
    "aGVzZSBhcyB0cmVuZCBldmlkZW5jZSwgc2tpcCB0aGVzZSBoZWFkbGluZXMgZW50aXJlbHkpOics" +
    "CiAgICAnSGFyZCBwb2xpdGljYWwgbmV3cywgZWxlY3Rpb24gcmVzdWx0cywgZ292ZXJubWVudCBw" +
    "b2xpY3kgZGViYXRlcywgd2FyLCBhcm1lZCBjb25mbGljdCwgdGVycm9yaXNtLCBhdHRhY2tzLCBi" +
    "b21iaW5ncywgc2hvb3RpbmdzLCBtdXJkZXJzLCBjcmltZSwgZGlzYXN0ZXJzLCBhY2NpZGVudHMs" +
    "IGZsb29kcywgZWFydGhxdWFrZXMsIGRlYXRoIHRvbGxzLCBhYnVzZSwgc2V4dWFsIHZpb2xlbmNl" +
    "LCBleHRyZW1lIHZpb2xlbmNlLCBjb3VydCBjYXNlcywgbGVnYWwgcHJvY2VlZGluZ3MsIHNhbmN0" +
    "aW9ucywgZGlwbG9tYXRpYyBkaXNwdXRlcy4nLAogICAgJycsCiAgICAnSWYgYSBoZWFkbGluZSBp" +
    "cyBhYm91dCBhbiBleGNsdWRlZCB0b3BpYywgaWdub3JlIGl0IGNvbXBsZXRlbHkg4oCUIGRvIG5v" +
    "dCB1c2UgaXQgYXMgZXZpZGVuY2UgZXZlbiBpbmRpcmVjdGx5LicsCiAgICAnSWYgYSBodW1hbiB0" +
    "cmVuZCAoZS5nLiBhbnhpZXR5LCBzb2xpZGFyaXR5LCBkaXN0cnVzdCkgaXMgdmlzaWJsZSBCRUhJ" +
    "TkQgYSBwb2xpdGljYWwgb3IgY3JpbWUgaGVhZGxpbmUsIHlvdSBtYXkgcmVmZXJlbmNlIHRoZSB1" +
    "bmRlcmx5aW5nIGh1bWFuIHBhdHRlcm4g4oCUIGJ1dCBuZXZlciB0aGUgZXZlbnQgaXRzZWxmLics" +
    "CiAgICAnSWYgdGhlcmUgYXJlIG5vdCBlbm91Z2ggbm9uLWV4Y2x1ZGVkIGhlYWRsaW5lcyB0byBz" +
    "dXBwb3J0IDUgdHJlbmRzLCBnZW5lcmF0ZSBmZXdlciB0cmVuZHMgcmF0aGVyIHRoYW4gdXNpbmcg" +
    "ZXhjbHVkZWQgdG9waWNzLicsCiAgICAnJywKICAgICdSZWZlcmVuY2UgYWN0dWFsIG5vbi1leGNs" +
    "dWRlZCBoZWFkbGluZXMgZnJvbSB0aGUgbGlzdCBhcyBldmlkZW5jZS4gVXNlIGFjdHVhbCBVUkxz" +
    "IHByb3ZpZGVkLicsICcnLAogICAgJ1JldHVybiBPTkxZIGEgSlNPTiBvYmplY3QsIHN0YXJ0aW5n" +
    "IHdpdGggeyBhbmQgZW5kaW5nIHdpdGggfTonLAogICAgJ3sidHJlbmRzIjpbeyJuYW1lIjoiVHJl" +
    "bmQgbmFtZSAzLTUgd29yZHMiLCJtb21lbnR1bSI6InJpc2luZ3xlbWVyZ2luZ3xlc3RhYmxpc2hl" +
    "ZHxzaGlmdGluZyIsImRlc2MiOiJUd28gc2VudGVuY2VzIGZvciBhIFRWIGZvcm1hdCBkZXZlbG9w" +
    "ZXIuIiwic2lnbmFscyI6IlR3byBzcGVjaWZpYyBvYnNlcnZhdGlvbnMgZnJvbSB0aGUgaGVhZGxp" +
    "bmVzLiIsInNvdXJjZUxhYmVscyI6WyJOVS5ubCIsIlJlZGRpdCJdLCJzb3VyY2VMaW5rcyI6W3si" +
    "dGl0bGUiOiJFeGFjdCBoZWFkbGluZSB0aXRsZSIsInVybCI6Imh0dHBzOi8vZXhhY3QtdXJsLWZy" +
    "b20tbGlzdCIsInNvdXJjZSI6Ik5VLm5sIiwidHlwZSI6Im5ld3MifV0sImZvcm1hdEhpbnQiOiJP" +
    "bmUtbGluZSB1bnNjcmlwdGVkIFRWIGZvcm1hdCBhbmdsZS4ifV19JywKICAgICcnLCAnR2VuZXJh" +
    "dGUgdXAgdG8gNSB0cmVuZHMuIE9ubHkgdXNlIFVSTHMgZnJvbSBub24tZXhjbHVkZWQgaGVhZGxp" +
    "bmVzIGFib3ZlLicKICBdLmpvaW4oJ1xuJyk7CiAgcmV0dXJuIGZldGNoKCcvY2hhdCcsIHsgbWV0" +
    "aG9kOiAnUE9TVCcsIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29u" +
    "JyB9LCBib2R5OiBKU09OLnN0cmluZ2lmeSh7IG1heF90b2tlbnM6IDI1MDAsIG1lc3NhZ2VzOiBb" +
    "eyByb2xlOiAndXNlcicsIGNvbnRlbnQ6IHByb21wdCB9XSB9KSB9KQogIC50aGVuKGZ1bmN0aW9u" +
    "KHIpIHsKICAgIGlmICghci5vaykgdGhyb3cgbmV3IEVycm9yKCdTZXJ2ZXIgZXJyb3IgJyArIHIu" +
    "c3RhdHVzICsgJyBvbiAvY2hhdCDigJQgY2hlY2sgUmFpbHdheSBsb2dzJyk7CiAgICB2YXIgY3Qg" +
    "PSByLmhlYWRlcnMuZ2V0KCdjb250ZW50LXR5cGUnKSB8fCAnJzsKICAgIGlmIChjdC5pbmRleE9m" +
    "KCdqc29uJykgPT09IC0xKSB0aHJvdyBuZXcgRXJyb3IoJ05vbi1KU09OIHJlc3BvbnNlIGZyb20g" +
    "L2NoYXQgKHN0YXR1cyAnICsgci5zdGF0dXMgKyAnKScpOwogICAgcmV0dXJuIHIuanNvbigpOwog" +
    "IH0pCiAgLnRoZW4oZnVuY3Rpb24oY2QpIHsKICAgIGlmIChjZC5lcnJvcikgdGhyb3cgbmV3IEVy" +
    "cm9yKCdDbGF1ZGUgQVBJIGVycm9yOiAnICsgY2QuZXJyb3IpOwogICAgdmFyIGJsb2NrcyA9IGNk" +
    "LmNvbnRlbnQgfHwgW107IHZhciB0ZXh0ID0gJyc7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IGJs" +
    "b2Nrcy5sZW5ndGg7IGkrKykgeyBpZiAoYmxvY2tzW2ldLnR5cGUgPT09ICd0ZXh0JykgdGV4dCAr" +
    "PSBibG9ja3NbaV0udGV4dDsgfQogICAgdmFyIGNsZWFuZWQgPSB0ZXh0LnJlcGxhY2UoL2BgYGpz" +
    "b25cbj8vZywgJycpLnJlcGxhY2UoL2BgYFxuPy9nLCAnJykudHJpbSgpOwogICAgdmFyIG1hdGNo" +
    "ID0gY2xlYW5lZC5tYXRjaCgvXHtbXHNcU10qXH0vKTsKICAgIGlmICghbWF0Y2gpIHRocm93IG5l" +
    "dyBFcnJvcignTm8gSlNPTiBpbiByZXNwb25zZScpOwogICAgdmFyIHJlc3VsdCA9IEpTT04ucGFy" +
    "c2UobWF0Y2hbMF0pOwogICAgaWYgKCFyZXN1bHQudHJlbmRzIHx8ICFyZXN1bHQudHJlbmRzLmxl" +
    "bmd0aCkgdGhyb3cgbmV3IEVycm9yKCdObyB0cmVuZHMgaW4gcmVzcG9uc2UnKTsKICAgIHRyZW5k" +
    "cyA9IHJlc3VsdC50cmVuZHM7IHNldFByb2dyZXNzKDEwMCk7IHJlbmRlclRyZW5kcyhyZWdpb24p" +
    "OwogICAgdmFyIG5vdyA9IG5ldyBEYXRlKCkudG9Mb2NhbGVUaW1lU3RyaW5nKCdubC1OTCcsIHsg" +
    "aG91cjogJzItZGlnaXQnLCBtaW51dGU6ICcyLWRpZ2l0JyB9KTsKICAgIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdzdGF0dXMtdGV4dCcpLnRleHRDb250ZW50ID0gJ0xhc3Qgc2NhbjogJyArIG5v" +
    "dyArICcgXHUyMDE0ICcgKyBoZWFkbGluZXMubGVuZ3RoICsgJyBoZWFkbGluZXMnOwogIH0pOwp9" +
    "CgpmdW5jdGlvbiBzcmNDb2xvcihzcmMpIHsKICBzcmMgPSAoc3JjIHx8ICcnKS50b0xvd2VyQ2Fz" +
    "ZSgpOwogIGlmIChzcmMuaW5kZXhPZigncmVkZGl0JykgPiAtMSkgcmV0dXJuICcjRTI0QjRBJzsK" +
    "ICBpZiAoc3JjLmluZGV4T2YoJ2dvb2dsZScpID4gLTEpIHJldHVybiAnIzEwYjk4MSc7CiAgaWYg" +
    "KHNyYyA9PT0gJ2xpYmVsbGUnIHx8IHNyYyA9PT0gJ2xpbmRhLm5sJykgcmV0dXJuICcjZjU5ZTBi" +
    "JzsKICByZXR1cm4gJyMzYjgyZjYnOwp9CgpmdW5jdGlvbiByZW5kZXJIZWFkbGluZXMoaGVhZGxp" +
    "bmVzKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NpZ25hbC1mZWVkJyk7" +
    "CiAgaWYgKCFoZWFkbGluZXMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJl" +
    "bXB0eSI+Tm8gaGVhZGxpbmVzIGZldGNoZWQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIGJ5U291" +
    "cmNlID0ge307IHZhciBzb3VyY2VPcmRlciA9IFtdOwogIGZvciAodmFyIGkgPSAwOyBpIDwgaGVh" +
    "ZGxpbmVzLmxlbmd0aDsgaSsrKSB7CiAgICB2YXIgc3JjID0gaGVhZGxpbmVzW2ldLnNvdXJjZTsK" +
    "ICAgIGlmICghYnlTb3VyY2Vbc3JjXSkgeyBieVNvdXJjZVtzcmNdID0gW107IHNvdXJjZU9yZGVy" +
    "LnB1c2goc3JjKTsgfQogICAgYnlTb3VyY2Vbc3JjXS5wdXNoKGhlYWRsaW5lc1tpXSk7CiAgfQog" +
    "IHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgcyA9IDA7IHMgPCBzb3VyY2VPcmRlci5sZW5ndGg7" +
    "IHMrKykgewogICAgdmFyIHNyYyA9IHNvdXJjZU9yZGVyW3NdOwogICAgaHRtbCArPSAnPGRpdiBj" +
    "bGFzcz0ic3JjLWdyb3VwIj4nICsgc3JjICsgJzwvZGl2Pic7CiAgICB2YXIgaXRlbXMgPSBieVNv" +
    "dXJjZVtzcmNdLnNsaWNlKDAsIDMpOwogICAgZm9yICh2YXIgaiA9IDA7IGogPCBpdGVtcy5sZW5n" +
    "dGg7IGorKykgewogICAgICB2YXIgaCA9IGl0ZW1zW2pdOwogICAgICBodG1sICs9ICc8ZGl2IGNs" +
    "YXNzPSJoZWFkbGluZS1pdGVtIj48ZGl2IGNsYXNzPSJoLWRvdCIgc3R5bGU9ImJhY2tncm91bmQ6" +
    "JyArIHNyY0NvbG9yKHNyYykgKyAnIj48L2Rpdj48ZGl2PjxkaXYgY2xhc3M9ImgtdGl0bGUiPicg" +
    "KyBoLnRpdGxlICsgJzwvZGl2Pic7CiAgICAgIGlmIChoLnVybCkgaHRtbCArPSAnPGEgY2xhc3M9" +
    "ImgtbGluayIgaHJlZj0iJyArIGgudXJsICsgJyIgdGFyZ2V0PSJfYmxhbmsiPmxlZXMgbWVlcjwv" +
    "YT4nOwogICAgICBodG1sICs9ICc8L2Rpdj48L2Rpdj4nOwogICAgfQogIH0KICBlbC5pbm5lckhU" +
    "TUwgPSBodG1sOwp9CgpmdW5jdGlvbiByZW5kZXJUcmVuZHMocmVnaW9uKSB7CiAgdmFyIGVsID0g" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyZW5kcy1saXN0Jyk7CiAgaWYgKCF0cmVuZHMubGVu" +
    "Z3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gdHJlbmRzIGRldGVj" +
    "dGVkLjwvZGl2Pic7IHJldHVybjsgfQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9IDA7" +
    "IGkgPCB0cmVuZHMubGVuZ3RoOyBpKyspIHsKICAgIHZhciB0ID0gdHJlbmRzW2ldOyB2YXIgaXNT" +
    "YXZlZCA9IGZhbHNlOwogICAgZm9yICh2YXIgcyA9IDA7IHMgPCBzYXZlZC5sZW5ndGg7IHMrKykg" +
    "eyBpZiAoc2F2ZWRbc10ubmFtZSA9PT0gdC5uYW1lKSB7IGlzU2F2ZWQgPSB0cnVlOyBicmVhazsg" +
    "fSB9CiAgICB2YXIgbWNNYXAgPSB7IHJpc2luZzogJ2ItcmlzaW5nJywgZW1lcmdpbmc6ICdiLWVt" +
    "ZXJnaW5nJywgZXN0YWJsaXNoZWQ6ICdiLWVzdGFibGlzaGVkJywgc2hpZnRpbmc6ICdiLXNoaWZ0" +
    "aW5nJyB9OwogICAgdmFyIG1jID0gbWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1lcmdpbmcnOwog" +
    "ICAgdmFyIGxpbmtzID0gdC5zb3VyY2VMaW5rcyB8fCBbXTsgdmFyIGxpbmtzSHRtbCA9ICcnOwog" +
    "ICAgZm9yICh2YXIgbCA9IDA7IGwgPCBsaW5rcy5sZW5ndGg7IGwrKykgewogICAgICB2YXIgbGsg" +
    "PSBsaW5rc1tsXTsKICAgICAgdmFyIGNsc01hcCA9IHsgcmVkZGl0OiAnc2wtcmVkZGl0JywgbmV3" +
    "czogJ3NsLW5ld3MnLCB0cmVuZHM6ICdzbC10cmVuZHMnLCBsaWZlc3R5bGU6ICdzbC1saWZlc3R5" +
    "bGUnIH07CiAgICAgIHZhciBsYmxNYXAgPSB7IHJlZGRpdDogJ1InLCBuZXdzOiAnTicsIHRyZW5k" +
    "czogJ0cnLCBsaWZlc3R5bGU6ICdMJyB9OwogICAgICBsaW5rc0h0bWwgKz0gJzxhIGNsYXNzPSJz" +
    "b3VyY2UtbGluayIgaHJlZj0iJyArIGxrLnVybCArICciIHRhcmdldD0iX2JsYW5rIj48c3BhbiBj" +
    "bGFzcz0ic2wtaWNvbiAnICsgKGNsc01hcFtsay50eXBlXSB8fCAnc2wtbmV3cycpICsgJyI+JyAr" +
    "IChsYmxNYXBbbGsudHlwZV0gfHwgJ04nKSArICc8L3NwYW4+PGRpdj48ZGl2IGNsYXNzPSJzbC10" +
    "aXRsZSI+JyArIGxrLnRpdGxlICsgJzwvZGl2PjxkaXYgY2xhc3M9InNsLXNvdXJjZSI+JyArIGxr" +
    "LnNvdXJjZSArICc8L2Rpdj48L2Rpdj48L2E+JzsKICAgIH0KICAgIHZhciBjaGlwcyA9ICcnOyB2" +
    "YXIgc2wgPSB0LnNvdXJjZUxhYmVscyB8fCBbXTsKICAgIGZvciAodmFyIGMgPSAwOyBjIDwgc2wu" +
    "bGVuZ3RoOyBjKyspIGNoaXBzICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIHNsW2NdICsgJzwv" +
    "c3Bhbj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtaXRlbSIgaWQ9InRjLScgKyBp" +
    "ICsgJyI+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5kLXJvdzEiPjxkaXYgY2xhc3M9" +
    "InRyZW5kLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+PHNwYW4gY2xhc3M9ImJhZGdlICcgKyBt" +
    "YyArICciPicgKyB0Lm1vbWVudHVtICsgJzwvc3Bhbj48L2Rpdj4nOwogICAgaHRtbCArPSAnPGRp" +
    "diBjbGFzcz0idHJlbmQtZGVzYyI+JyArIHQuZGVzYyArICc8L2Rpdj4nOwogICAgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0idHJlbmQtc2lnbmFscyI+JyArIHQuc2lnbmFscyArICc8L2Rpdj4nOwogICAg" +
    "aHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtYWN0aW9ucyI+PGRpdiBjbGFzcz0iY2hpcHMiPicg" +
    "KyBjaGlwcyArICc8L2Rpdj48ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjVweCI+JzsKICAg" +
    "IGlmIChsaW5rcy5sZW5ndGgpIGh0bWwgKz0gJzxidXR0b24gY2xhc3M9ImFjdC1idG4iIG9uY2xp" +
    "Y2s9InRvZ2dsZUJveChcJ3NyYy0nICsgaSArICdcJykiPnNvdXJjZXM8L2J1dHRvbj4nOwogICAg" +
    "aWYgKHQuZm9ybWF0SGludCkgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0iYWN0LWJ0biIgb25jbGlj" +
    "az0idG9nZ2xlQm94KFwnaGludC0nICsgaSArICdcJykiPmZvcm1hdDwvYnV0dG9uPic7CiAgICBo" +
    "dG1sICs9ICc8YnV0dG9uIGNsYXNzPSJhY3QtYnRuJyArIChpc1NhdmVkID8gJyBzYXZlZCcgOiAn" +
    "JykgKyAnIiBpZD0ic2ItJyArIGkgKyAnIiBvbmNsaWNrPSJkb1NhdmUoJyArIGkgKyAnLFwnJyAr" +
    "IHJlZ2lvbiArICdcJykiPicgKyAoaXNTYXZlZCA/ICdzYXZlZCcgOiAnc2F2ZScpICsgJzwvYnV0" +
    "dG9uPic7CiAgICBodG1sICs9ICc8L2Rpdj48L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFz" +
    "cz0iZXhwYW5kLWJveCIgaWQ9InNyYy0nICsgaSArICciPicgKyAobGlua3NIdG1sIHx8ICc8ZGl2" +
    "IHN0eWxlPSJmb250LXNpemU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCkiPk5vIHNvdXJjZSBsaW5r" +
    "cy48L2Rpdj4nKSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iaGludC1ib3gi" +
    "IGlkPSJoaW50LScgKyBpICsgJyI+JyArICh0LmZvcm1hdEhpbnQgfHwgJycpICsgJzwvZGl2Pic7" +
    "CiAgICBodG1sICs9ICc8L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9CgpmdW5j" +
    "dGlvbiB0b2dnbGVCb3goaWQpIHsKICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZChp" +
    "ZCk7CiAgaWYgKGVsKSBlbC5zdHlsZS5kaXNwbGF5ID0gZWwuc3R5bGUuZGlzcGxheSA9PT0gJ2Js" +
    "b2NrJyA/ICdub25lJyA6ICdibG9jayc7Cn0KCmZ1bmN0aW9uIGRvU2F2ZShpLCByZWdpb24pIHsK" +
    "ICB2YXIgdCA9IHRyZW5kc1tpXTsKICBmb3IgKHZhciBzID0gMDsgcyA8IHNhdmVkLmxlbmd0aDsg" +
    "cysrKSB7IGlmIChzYXZlZFtzXS5uYW1lID09PSB0Lm5hbWUpIHJldHVybjsgfQogIHNhdmVkLnB1" +
    "c2goeyBuYW1lOiB0Lm5hbWUsIGRlc2M6IHQuZGVzYywgdGFnOiAnJyB9KTsKICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnc2ItJyArIGkpLnRleHRDb250ZW50ID0gJ3NhdmVkJzsKICBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgnc2ItJyArIGkpLmNsYXNzTGlzdC5hZGQoJ3NhdmVkJyk7CiAgcmVu" +
    "ZGVyU2F2ZWQoKTsKICBmZXRjaCgnL2FyY2hpdmUvc2F2ZScsIHsgbWV0aG9kOiAnUE9TVCcsIGhl" +
    "YWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBib2R5OiBKU09O" +
    "LnN0cmluZ2lmeSh7IG5hbWU6IHQubmFtZSwgZGVzYzogdC5kZXNjLCBtb21lbnR1bTogdC5tb21l" +
    "bnR1bSwgc2lnbmFsczogdC5zaWduYWxzLCBzb3VyY2VfbGFiZWxzOiB0LnNvdXJjZUxhYmVscyB8" +
    "fCBbXSwgc291cmNlX2xpbmtzOiB0LnNvdXJjZUxpbmtzIHx8IFtdLCBmb3JtYXRfaGludDogdC5m" +
    "b3JtYXRIaW50LCB0YWc6ICcnLCByZWdpb246IHJlZ2lvbiB8fCAnbmwnIH0pIH0pCiAgLmNhdGNo" +
    "KGZ1bmN0aW9uKGUpIHsgY29uc29sZS5lcnJvcignYXJjaGl2ZSBzYXZlIGZhaWxlZCcsIGUpOyB9" +
    "KTsKfQoKZnVuY3Rpb24gcmVuZGVyU2F2ZWQoKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxl" +
    "bWVudEJ5SWQoJ3NhdmVkLWxpc3QnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZ2VuLXJv" +
    "dycpLnN0eWxlLmRpc3BsYXkgPSBzYXZlZC5sZW5ndGggPyAnJyA6ICdub25lJzsKICBpZiAoIXNh" +
    "dmVkLmxlbmd0aCkgeyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPk5vIHNhdmVk" +
    "IHRyZW5kcyB5ZXQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIGh0bWwgPSAnJzsKICBmb3IgKHZh" +
    "ciBpID0gMDsgaSA8IHNhdmVkLmxlbmd0aDsgaSsrKSB7CiAgICB2YXIgdCA9IHNhdmVkW2ldOwog" +
    "ICAgaHRtbCArPSAnPGRpdiBjbGFzcz0ic2F2ZWQtaXRlbSI+PGRpdiBjbGFzcz0ic2F2ZWQtbmFt" +
    "ZSI+JyArIHQubmFtZSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZGlzcGxh" +
    "eTpmbGV4O2dhcDo2cHg7YWxpZ24taXRlbXM6Y2VudGVyIj48aW5wdXQgY2xhc3M9InRhZy1pbnB1" +
    "dCIgcGxhY2Vob2xkZXI9InRhZy4uLiIgdmFsdWU9IicgKyB0LnRhZyArICciIG9uaW5wdXQ9InNh" +
    "dmVkWycgKyBpICsgJ10udGFnPXRoaXMudmFsdWUiLz4nOwogICAgaHRtbCArPSAnPHNwYW4gc3R5" +
    "bGU9ImN1cnNvcjpwb2ludGVyO2ZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dGVkKSIgb25j" +
    "bGljaz0ic2F2ZWQuc3BsaWNlKCcgKyBpICsgJywxKTtyZW5kZXJTYXZlZCgpIj4mI3gyNzE1Ozwv" +
    "c3Bhbj48L2Rpdj48L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9Cgp2YXIgZ2Vu" +
    "ZXJhdGVkRm9ybWF0cyA9IFtdOwoKZnVuY3Rpb24gZ2VuZXJhdGVGb3JtYXRzKCkgewogIGlmICgh" +
    "c2F2ZWQubGVuZ3RoKSByZXR1cm47CiAgc3dpdGNoVGFiKCdmb3JtYXRzJyk7CiAgZG9jdW1lbnQu" +
    "Z2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbCcpLnN0eWxlLmRpc3BsYXkgPSAnbm9uZSc7CiAgZG9j" +
    "dW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNs" +
    "YXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlJlYWRpbmcgeW91ciBjYXRh" +
    "bG9ndWUgJmFtcDsgZ2VuZXJhdGluZyBpZGVhcy4uLjwvZGl2Pic7CiAgZmV0Y2goJy9nZW5lcmF0" +
    "ZS1mb3JtYXRzJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50" +
    "LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsg" +
    "dHJlbmRzOiBzYXZlZCB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29u" +
    "KCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24ocmVzdWx0KSB7CiAgICBpZiAocmVzdWx0LmVycm9yKSB0" +
    "aHJvdyBuZXcgRXJyb3IocmVzdWx0LmVycm9yKTsKICAgIHZhciBmb3JtYXRzID0gcmVzdWx0LmZv" +
    "cm1hdHMgfHwgW107CiAgICBpZiAoIWZvcm1hdHMubGVuZ3RoKSB0aHJvdyBuZXcgRXJyb3IoJ05v" +
    "IGZvcm1hdHMgcmV0dXJuZWQnKTsKICAgIGdlbmVyYXRlZEZvcm1hdHMgPSBmb3JtYXRzOwogICAg" +
    "dmFyIGh0bWwgPSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgZm9ybWF0cy5sZW5ndGg7IGkr" +
    "KykgewogICAgICB2YXIgZiA9IGZvcm1hdHNbaV07CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9" +
    "ImZvcm1hdC1pdGVtIj4nOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQtdGl0bGUi" +
    "PicgKyBmLnRpdGxlICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1h" +
    "dC1sb2dsaW5lIj4nICsgZi5sb2dsaW5lICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYg" +
    "c3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6NnB4O2ZsZXgtd3JhcDp3cmFwO21hcmdpbi10b3A6NXB4" +
    "Ij4nOwogICAgICBodG1sICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIGYuY2hhbm5lbCArICc8" +
    "L3NwYW4+JzsKICAgICAgaHRtbCArPSAnPHNwYW4gY2xhc3M9ImNoaXAiPicgKyBmLnRyZW5kQmFz" +
    "aXMgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICAgIGlmIChmLmhvb2sp" +
    "IGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1hdC1ob29rIj4iJyArIGYuaG9vayArICciPC9kaXY+" +
    "JzsKICAgICAgaWYgKGYud2h5TmV3KSBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTFw" +
    "eDtjb2xvcjp2YXIoLS1ncmVlbik7bWFyZ2luLXRvcDo1cHg7Zm9udC1zdHlsZTppdGFsaWMiPicg" +
    "KyBmLndoeU5ldyArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8YnV0dG9uIGNsYXNzPSJkZXYt" +
    "YnRuIiBvbmNsaWNrPSJzdGFydERldmVsb3BtZW50KCcgKyBpICsgJykiPiYjOTY2MDsgRGV2ZWxv" +
    "cCB0aGlzIGZvcm1hdDwvYnV0dG9uPic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICB9CiAg" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZm9ybWF0cy1saXN0JykuaW5uZXJIVE1MID0gaHRt" +
    "bDsKICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7CiAgICBzaG93RXJyKCdGb3JtYXQgZ2VuZXJh" +
    "dGlvbiBmYWlsZWQ6ICcgKyBlLm1lc3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+RmFpbGVkLjwv" +
    "ZGl2Pic7CiAgfSk7Cn0KCi8vIOKUgOKUgCBGb3JtYXQgZGV2ZWxvcG1lbnQgY2hhdCDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKdmFyIGRldk1lc3NhZ2VzID0gW107CnZh" +
    "ciBkZXZGb3JtYXQgPSBudWxsOwoKZnVuY3Rpb24gc3RhcnREZXZlbG9wbWVudChpKSB7CiAgZGV2" +
    "Rm9ybWF0ID0gZ2VuZXJhdGVkRm9ybWF0c1tpXSB8fCBudWxsOwogIGRldk1lc3NhZ2VzID0gW107" +
    "CiAgdmFyIHBhbmVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbCcpOwogIHZh" +
    "ciBjaGF0ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1jaGF0Jyk7CiAgcGFuZWwuc3R5" +
    "bGUuZGlzcGxheSA9ICcnOwogIGNoYXQuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij48" +
    "c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+U3RhcnRpbmcgZGV2ZWxvcG1lbnQgc2Vzc2lvbi4u" +
    "LjwvZGl2Pic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbC1zdWJ0aXRsZScp" +
    "LnRleHRDb250ZW50ID0gJ0RldmVsb3Bpbmc6ICcgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LnRp" +
    "dGxlIDogJ0Zvcm1hdCBpZGVhJyk7CiAgcGFuZWwuc2Nyb2xsSW50b1ZpZXcoeyBiZWhhdmlvcjog" +
    "J3Ntb290aCcsIGJsb2NrOiAnc3RhcnQnIH0pOwoKICAvLyBPcGVuaW5nIG1lc3NhZ2UgZnJvbSB0" +
    "aGUgQUkKICBmZXRjaCgnL2RldmVsb3AnLCB7CiAgICBtZXRob2Q6ICdQT1NUJywKICAgIGhlYWRl" +
    "cnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LAogICAgYm9keTogSlNP" +
    "Ti5zdHJpbmdpZnkoewogICAgICBmb3JtYXRfaWRlYTogZGV2Rm9ybWF0LAogICAgICB0cmVuZHM6" +
    "IHNhdmVkLAogICAgICBtZXNzYWdlczogW3sKICAgICAgICByb2xlOiAndXNlcicsCiAgICAgICAg" +
    "Y29udGVudDogJ0kgd2FudCB0byBkZXZlbG9wIHRoaXMgZm9ybWF0IGlkZWEuIEhlcmUgaXMgd2hh" +
    "dCB3ZSBoYXZlIHNvIGZhcjogVGl0bGU6ICInICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC50aXRs" +
    "ZSA6ICcnKSArICciLiBMb2dsaW5lOiAnICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC5sb2dsaW5l" +
    "IDogJycpICsgJy4gUGxlYXNlIHN0YXJ0IG91ciBkZXZlbG9wbWVudCBzZXNzaW9uLicKICAgICAg" +
    "fV0KICAgIH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkK" +
    "ICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKGQu" +
    "ZXJyb3IpOwogICAgZGV2TWVzc2FnZXMgPSBbCiAgICAgIHsgcm9sZTogJ3VzZXInLCBjb250ZW50" +
    "OiAnSSB3YW50IHRvIGRldmVsb3AgdGhpcyBmb3JtYXQgaWRlYS4gSGVyZSBpcyB3aGF0IHdlIGhh" +
    "dmUgc28gZmFyOiBUaXRsZTogIicgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LnRpdGxlIDogJycp" +
    "ICsgJyIuIExvZ2xpbmU6ICcgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LmxvZ2xpbmUgOiAnJykg" +
    "KyAnLiBQbGVhc2Ugc3RhcnQgb3VyIGRldmVsb3BtZW50IHNlc3Npb24uJyB9LAogICAgICB7IHJv" +
    "bGU6ICdhc3Npc3RhbnQnLCBjb250ZW50OiBkLnJlc3BvbnNlIH0KICAgIF07CiAgICByZW5kZXJE" +
    "ZXZDaGF0KCk7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgY2hhdC5pbm5lckhUTUwg" +
    "PSAnPGRpdiBjbGFzcz0iZW1wdHkiPkNvdWxkIG5vdCBzdGFydCBzZXNzaW9uOiAnICsgZS5tZXNz" +
    "YWdlICsgJzwvZGl2Pic7CiAgfSk7Cn0KCmZ1bmN0aW9uIHNlbmREZXZNZXNzYWdlKCkgewogIHZh" +
    "ciBpbnB1dCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtaW5wdXQnKTsKICB2YXIgbXNn" +
    "ID0gaW5wdXQudmFsdWUudHJpbSgpOwogIGlmICghbXNnIHx8ICFkZXZGb3JtYXQpIHJldHVybjsK" +
    "ICBpbnB1dC52YWx1ZSA9ICcnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtc2VuZCcp" +
    "LmRpc2FibGVkID0gdHJ1ZTsKCiAgZGV2TWVzc2FnZXMucHVzaCh7IHJvbGU6ICd1c2VyJywgY29u" +
    "dGVudDogbXNnIH0pOwogIHJlbmRlckRldkNoYXQoKTsKCiAgZmV0Y2goJy9kZXZlbG9wJywgewog" +
    "ICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAnYXBwbGlj" +
    "YXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsKICAgICAgZm9ybWF0X2lk" +
    "ZWE6IGRldkZvcm1hdCwKICAgICAgdHJlbmRzOiBzYXZlZCwKICAgICAgbWVzc2FnZXM6IGRldk1l" +
    "c3NhZ2VzCiAgICB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7" +
    "IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgaWYgKGQuZXJyb3IpIHRocm93IG5ldyBFcnJv" +
    "cihkLmVycm9yKTsKICAgIGRldk1lc3NhZ2VzLnB1c2goeyByb2xlOiAnYXNzaXN0YW50JywgY29u" +
    "dGVudDogZC5yZXNwb25zZSB9KTsKICAgIHJlbmRlckRldkNoYXQoKTsKICAgIGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdkZXYtc2VuZCcpLmRpc2FibGVkID0gZmFsc2U7CiAgICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnZGV2LWlucHV0JykuZm9jdXMoKTsKICB9KQogIC5jYXRjaChmdW5jdGlv" +
    "bihlKSB7CiAgICBkZXZNZXNzYWdlcy5wdXNoKHsgcm9sZTogJ2Fzc2lzdGFudCcsIGNvbnRlbnQ6" +
    "ICdTb3JyeSwgc29tZXRoaW5nIHdlbnQgd3Jvbmc6ICcgKyBlLm1lc3NhZ2UgfSk7CiAgICByZW5k" +
    "ZXJEZXZDaGF0KCk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXNlbmQnKS5kaXNh" +
    "YmxlZCA9IGZhbHNlOwogIH0pOwp9CgpmdW5jdGlvbiByZW5kZXJEZXZDaGF0KCkgewogIHZhciBj" +
    "aGF0ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1jaGF0Jyk7CiAgdmFyIGh0bWwgPSAn" +
    "JzsKICBmb3IgKHZhciBpID0gMDsgaSA8IGRldk1lc3NhZ2VzLmxlbmd0aDsgaSsrKSB7CiAgICB2" +
    "YXIgbSA9IGRldk1lc3NhZ2VzW2ldOwogICAgdmFyIGNscyA9IG0ucm9sZSA9PT0gJ2Fzc2lzdGFu" +
    "dCcgPyAnYWknIDogJ3VzZXInOwogICAgdmFyIHRleHQgPSBtLmNvbnRlbnQucmVwbGFjZSgvXG4v" +
    "ZywgJzxicj4nKTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImRldi1tc2cgJyArIGNscyArICci" +
    "PicgKyB0ZXh0ICsgJzwvZGl2Pic7CiAgfQogIGNoYXQuaW5uZXJIVE1MID0gaHRtbDsKICBjaGF0" +
    "LnNjcm9sbFRvcCA9IGNoYXQuc2Nyb2xsSGVpZ2h0Owp9CgpmdW5jdGlvbiBsb2FkUmVzZWFyY2go" +
    "KSB7CiAgZmV0Y2goJy9yZXNlYXJjaCcpLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29u" +
    "KCk7IH0pLnRoZW4oZnVuY3Rpb24oZCkgeyByZW5kZXJSZXNlYXJjaChkLml0ZW1zIHx8IFtdKTsg" +
    "fSkKICAuY2F0Y2goZnVuY3Rpb24oKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZXNlYXJj" +
    "aC1mZWVkJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5Db3VsZCBub3QgbG9hZCBy" +
    "ZXNlYXJjaC48L2Rpdj4nOyB9KTsKfQoKZnVuY3Rpb24gcmVuZGVyUmVzZWFyY2goaXRlbXMpIHsK" +
    "ICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVzZWFyY2gtZmVlZCcpOwogIGlm" +
    "ICghaXRlbXMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8g" +
    "cmVzZWFyY2ggaXRlbXMgZm91bmQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIHR5cGVNYXAgPSB7" +
    "IHJlc2VhcmNoOiAnUmVzZWFyY2gnLCBjdWx0dXJlOiAnQ3VsdHVyZScsIHRyZW5kczogJ1RyZW5k" +
    "cycgfTsgdmFyIGh0bWwgPSAnJzsKICBmb3IgKHZhciBpID0gMDsgaSA8IGl0ZW1zLmxlbmd0aDsg" +
    "aSsrKSB7CiAgICB2YXIgaXRlbSA9IGl0ZW1zW2ldOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0i" +
    "cmVzZWFyY2gtaXRlbSI+PGRpdiBjbGFzcz0icmVzZWFyY2gtdGl0bGUiPjxhIGhyZWY9IicgKyBp" +
    "dGVtLnVybCArICciIHRhcmdldD0iX2JsYW5rIj4nICsgaXRlbS50aXRsZSArICc8L2E+PC9kaXY+" +
    "JzsKICAgIGlmIChpdGVtLmRlc2MpIGh0bWwgKz0gJzxkaXYgY2xhc3M9InJlc2VhcmNoLWRlc2Mi" +
    "PicgKyBpdGVtLmRlc2MgKyAnPC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InJlc2Vh" +
    "cmNoLW1ldGEiPjxzcGFuIGNsYXNzPSJyLXNyYyI+JyArIGl0ZW0uc291cmNlICsgJzwvc3Bhbj48" +
    "c3BhbiBjbGFzcz0ici10eXBlIj4nICsgKHR5cGVNYXBbaXRlbS50eXBlXSB8fCBpdGVtLnR5cGUp" +
    "ICsgJzwvc3Bhbj48L2Rpdj48L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9Cgpm" +
    "dW5jdGlvbiBkb0FyY2hpdmVTZWFyY2goKSB7CiAgdmFyIHF1ZXJ5ID0gZG9jdW1lbnQuZ2V0RWxl" +
    "bWVudEJ5SWQoJ2FyY2hpdmUtc2VhcmNoLWlucHV0JykudmFsdWUudHJpbSgpOwogIGlmICghcXVl" +
    "cnkpIHJldHVybjsKICB2YXIgcmVzdWx0c0VsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Nl" +
    "YXJjaC1yZXN1bHRzJyk7CiAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxlPSJmb250" +
    "LXNpemU6MTJweDtjb2xvcjp2YXIoLS1tdXRlZCkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bh" +
    "bj5TZWFyY2hpbmcgYXJjaGl2ZS4uLjwvZGl2Pic7CgogIGZldGNoKCcvYXJjaGl2ZS9zZWFyY2gn" +
    "LCB7CiAgICBtZXRob2Q6ICdQT1NUJywKICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdh" +
    "cHBsaWNhdGlvbi9qc29uJyB9LAogICAgYm9keTogSlNPTi5zdHJpbmdpZnkoeyBxdWVyeTogcXVl" +
    "cnkgfSkKICB9KQogIC50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50" +
    "aGVuKGZ1bmN0aW9uKGQpIHsKICAgIGlmIChkLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoZC5lcnJv" +
    "cik7CiAgICB2YXIgcmVzdWx0cyA9IGQucmVzdWx0cyB8fCBbXTsKICAgIGlmICghcmVzdWx0cy5s" +
    "ZW5ndGgpIHsKICAgICAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxlPSJmb250LXNp" +
    "emU6MTJweDtjb2xvcjp2YXIoLS1tdXRlZCk7cGFkZGluZzo4cHggMCI+Tm8gcmVsZXZhbnQgdHJl" +
    "bmRzIGZvdW5kIGZvciAiJyArIHF1ZXJ5ICsgJyIuPC9kaXY+JzsKICAgICAgcmV0dXJuOwogICAg" +
    "fQogICAgdmFyIG1jTWFwID0geyByaXNpbmc6ICdiLXJpc2luZycsIGVtZXJnaW5nOiAnYi1lbWVy" +
    "Z2luZycsIGVzdGFibGlzaGVkOiAnYi1lc3RhYmxpc2hlZCcsIHNoaWZ0aW5nOiAnYi1zaGlmdGlu" +
    "ZycgfTsKICAgIHZhciBodG1sID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMHB4O2ZvbnQtd2Vp" +
    "Z2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10cmFuc2Zvcm06dXBwZXJjYXNlO2xldHRl" +
    "ci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBweCI+JyArIHJlc3VsdHMubGVuZ3RoICsg" +
    "JyByZWxldmFudCB0cmVuZHMgZm91bmQ8L2Rpdj4nOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCBy" +
    "ZXN1bHRzLmxlbmd0aDsgaSsrKSB7CiAgICAgIHZhciB0ID0gcmVzdWx0c1tpXTsKICAgICAgdmFy" +
    "IG1jID0gbWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1lcmdpbmcnOwogICAgICBodG1sICs9ICc8" +
    "ZGl2IHN0eWxlPSJwYWRkaW5nOjEycHggMDtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1i" +
    "b3JkZXIpIj4nOwogICAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7YWxpZ24t" +
    "aXRlbXM6Y2VudGVyO2dhcDo4cHg7bWFyZ2luLWJvdHRvbTo1cHgiPic7CiAgICAgIGh0bWwgKz0g" +
    "JzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjojZmZmIj4n" +
    "ICsgdC5uYW1lICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxzcGFuIGNsYXNzPSJiYWRnZSAn" +
    "ICsgbWMgKyAnIj4nICsgKHQubW9tZW50dW0gfHwgJycpICsgJzwvc3Bhbj4nOwogICAgICBodG1s" +
    "ICs9ICc8c3BhbiBzdHlsZT0iZm9udC1zaXplOjEwcHg7Y29sb3I6dmFyKC0tbXV0ZWQpIj4nICsg" +
    "dC5zYXZlZF9hdC5zbGljZSgwLDEwKSArICc8L3NwYW4+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+" +
    "JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjEycHg7Y29sb3I6dmFyKC0t" +
    "bXV0ZWQpO2xpbmUtaGVpZ2h0OjEuNTttYXJnaW4tYm90dG9tOjVweCI+JyArICh0LmRlc2MgfHwg" +
    "JycpICsgJzwvZGl2Pic7CiAgICAgIGlmICh0LnJlbGV2YW5jZSkgaHRtbCArPSAnPGRpdiBzdHls" +
    "ZT0iZm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tYWNjZW50Mik7Zm9udC1zdHlsZTppdGFsaWMi" +
    "PicgKyB0LnJlbGV2YW5jZSArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8L2Rpdj4nOwogICAg" +
    "fQogICAgcmVzdWx0c0VsLmlubmVySFRNTCA9IGh0bWw7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24o" +
    "ZSkgewogICAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTJw" +
    "eDtjb2xvcjojZmNhNWE1Ij5TZWFyY2ggZmFpbGVkOiAnICsgZS5tZXNzYWdlICsgJzwvZGl2Pic7" +
    "CiAgfSk7Cn0KCmZ1bmN0aW9uIGxvYWRBcmNoaXZlKCkgewogIGRvY3VtZW50LmdldEVsZW1lbnRC" +
    "eUlkKCdkYXRlLWxpc3QnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiIHN0eWxlPSJw" +
    "YWRkaW5nOjFyZW0gMCI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPjwvZGl2Pic7CiAgZmV0" +
    "Y2goJy9hcmNoaXZlL2RhdGVzJykudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsg" +
    "fSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoIWQuZGF0ZXMgfHwgIWQuZGF0ZXMubGVu" +
    "Z3RoKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkYXRlLWxpc3QnKS5pbm5lckhUTUwgPSAn" +
    "PGRpdiBjbGFzcz0iZW1wdHkiIHN0eWxlPSJwYWRkaW5nOjFyZW0gMDtmb250LXNpemU6MTFweCI+" +
    "Tm8gYXJjaGl2ZWQgdHJlbmRzIHlldC48L2Rpdj4nOyByZXR1cm47IH0KICAgIHZhciBodG1sID0g" +
    "Jyc7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IGQuZGF0ZXMubGVuZ3RoOyBpKyspIHsgaHRtbCAr" +
    "PSAnPGRpdiBjbGFzcz0iZGF0ZS1pdGVtIiBvbmNsaWNrPSJsb2FkRGF0ZShcJycgKyBkLmRhdGVz" +
    "W2ldLmRhdGUgKyAnXCcsdGhpcykiPicgKyBkLmRhdGVzW2ldLmRhdGUgKyAnPHNwYW4gY2xhc3M9" +
    "ImRhdGUtY291bnQiPicgKyBkLmRhdGVzW2ldLmNvdW50ICsgJzwvc3Bhbj48L2Rpdj4nOyB9CiAg" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0JykuaW5uZXJIVE1MID0gaHRtbDsK" +
    "ICAgIHZhciBmaXJzdCA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoJy5kYXRlLWl0ZW0nKTsgaWYg" +
    "KGZpcnN0KSBmaXJzdC5jbGljaygpOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsgZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtZXJyJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9" +
    "ImVycmJveCI+Q291bGQgbm90IGxvYWQgYXJjaGl2ZTogJyArIGUubWVzc2FnZSArICc8L2Rpdj4n" +
    "OyB9KTsKfQoKZnVuY3Rpb24gbG9hZERhdGUoZGF0ZSwgZWwpIHsKICB2YXIgaXRlbXMgPSBkb2N1" +
    "bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcuZGF0ZS1pdGVtJyk7IGZvciAodmFyIGkgPSAwOyBpIDwg" +
    "aXRlbXMubGVuZ3RoOyBpKyspIGl0ZW1zW2ldLmNsYXNzTGlzdC5yZW1vdmUoJ2FjdGl2ZScpOwog" +
    "IGVsLmNsYXNzTGlzdC5hZGQoJ2FjdGl2ZScpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdh" +
    "cmNoaXZlLWhlYWRpbmcnKS50ZXh0Q29udGVudCA9ICdTYXZlZCBvbiAnICsgZGF0ZTsKICBkb2N1" +
    "bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYg" +
    "Y2xhc3M9ImVtcHR5Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+PC9kaXY+JzsKICBmZXRj" +
    "aCgnL2FyY2hpdmUvYnktZGF0ZT9kYXRlPScgKyBlbmNvZGVVUklDb21wb25lbnQoZGF0ZSkpLnRo" +
    "ZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkg" +
    "ewogICAgaWYgKCFkLnRyZW5kcyB8fCAhZC50cmVuZHMubGVuZ3RoKSB7IGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1w" +
    "dHkiPk5vIHRyZW5kcyBmb3IgdGhpcyBkYXRlLjwvZGl2Pic7IHJldHVybjsgfQogICAgdmFyIGh0" +
    "bWwgPSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgZC50cmVuZHMubGVuZ3RoOyBpKyspIHsK" +
    "ICAgICAgdmFyIHQgPSBkLnRyZW5kc1tpXTsKICAgICAgdmFyIG1jTWFwID0geyByaXNpbmc6ICdi" +
    "LXJpc2luZycsIGVtZXJnaW5nOiAnYi1lbWVyZ2luZycsIGVzdGFibGlzaGVkOiAnYi1lc3RhYmxp" +
    "c2hlZCcsIHNoaWZ0aW5nOiAnYi1zaGlmdGluZycgfTsKICAgICAgdmFyIG1jID0gbWNNYXBbdC5t" +
    "b21lbnR1bV0gfHwgJ2ItZW1lcmdpbmcnOyB2YXIgbGlua3MgPSBbXTsKICAgICAgdHJ5IHsgbGlu" +
    "a3MgPSBKU09OLnBhcnNlKHQuc291cmNlX2xpbmtzIHx8ICdbXScpOyB9IGNhdGNoKGUpIHt9CiAg" +
    "ICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gtaXRlbSI+PGRpdiBzdHlsZT0iZGlzcGxheTpm" +
    "bGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6OHB4O21hcmdpbi1ib3R0b206M3B4Ij48ZGl2IGNs" +
    "YXNzPSJhcmNoLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+PHNwYW4gY2xhc3M9ImJhZGdlICcg" +
    "KyBtYyArICciPicgKyAodC5tb21lbnR1bSB8fCAnJykgKyAnPC9zcGFuPjwvZGl2Pic7CiAgICAg" +
    "IGh0bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gtbWV0YSI+JyArIHQuc2F2ZWRfYXQgKyAodC5yZWdp" +
    "b24gPyAnICZtaWRkb3Q7ICcgKyB0LnJlZ2lvbi50b1VwcGVyQ2FzZSgpIDogJycpICsgKHQudGFn" +
    "ID8gJyAmbWlkZG90OyAnICsgdC50YWcgOiAnJykgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0iYXJjaC1kZXNjIj4nICsgKHQuZGVzYyB8fCAnJykgKyAnPC9kaXY+JzsKICAg" +
    "ICAgZm9yICh2YXIgbCA9IDA7IGwgPCBsaW5rcy5sZW5ndGg7IGwrKykgeyBodG1sICs9ICc8YSBj" +
    "bGFzcz0iYXJjaC1saW5rIiBocmVmPSInICsgbGlua3NbbF0udXJsICsgJyIgdGFyZ2V0PSJfYmxh" +
    "bmsiPicgKyBsaW5rc1tsXS50aXRsZSArICc8L2E+JzsgfQogICAgICBodG1sICs9ICc8L2Rpdj4n" +
    "OwogICAgfQogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtY29udGVudCcpLmlu" +
    "bmVySFRNTCA9IGh0bWw7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oKSB7IGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1w" +
    "dHkiPkNvdWxkIG5vdCBsb2FkLjwvZGl2Pic7IH0pOwp9Cjwvc2NyaXB0Pgo8L2JvZHk+CjwvaHRt" +
    "bD4K"
)

@app.route("/")
def index():
    import base64
    return base64.b64decode(_HTML_B64).decode()

SCRAPER_URL = "https://web-production-3d190.up.railway.app"

@app.route("/scrape", methods=["POST"])
def scrape():
    body = request.json or {}
    region = body.get("region", "nl")
    try:
        r = requests.post(
            SCRAPER_URL + "/scrape",
            json={"region": region},
            headers={"Content-Type": "application/json"},
            timeout=25
        )
        # Check we actually got JSON back
        content_type = r.headers.get("content-type", "")
        if "json" not in content_type:
            print("[scraper proxy] Non-JSON response: {} {}".format(r.status_code, r.text[:100]))
            return jsonify({"items": [], "count": 0, "error": "Scraper returned non-JSON (status {})".format(r.status_code)})
        return jsonify(r.json())
    except requests.exceptions.Timeout:
        print("[scraper proxy] Timeout")
        return jsonify({"items": [], "count": 0, "error": "Scraper timed out"})
    except Exception as e:
        print("[scraper proxy error] {}".format(e))
        return jsonify({"items": [], "count": 0, "error": str(e)})

@app.route("/research")
def research():
    items = gather_research()
    return jsonify({"items": items, "count": len(items)})

@app.route("/formats-db")
def formats_db():
    """Return all formats from the Google Sheet."""
    formats = get_formats_from_sheet()
    return jsonify({"formats": formats, "count": len(formats)})

@app.route("/match-trend", methods=["POST"])
def match_trend():
    """Find matching formats from the database for a given trend."""
    body = request.json or {}
    trend_name = body.get("name", "")
    trend_desc = body.get("desc", "")
    formats = get_formats_from_sheet()
    if not formats:
        return jsonify({"matches": [], "error": "Could not load format database"})
    matches = match_formats_to_trend(trend_name, trend_desc, formats)
    return jsonify({"matches": matches})

@app.route("/generate-formats", methods=["POST"])
def generate_formats():
    """Generate format ideas using saved trends + catalogue context."""
    body = request.json or {}
    saved_trends = body.get("trends", [])
    if not saved_trends:
        return jsonify({"error": "No trends provided"})

    # Load catalogue for context
    formats = get_formats_from_sheet()

    # Build catalogue summary for Claude
    catalogue_context = ""
    if formats:
        # Genre distribution
        genres = {}
        topics = []
        for f in formats:
            g = f.get("genre", "").strip()
            if g:
                genres[g] = genres.get(g, 0) + 1
            t = f.get("topic", "").strip()
            if t:
                topics.append(t)
        genre_summary = ", ".join(["{} ({})".format(g, c) for g, c in sorted(genres.items(), key=lambda x: -x[1])[:8]])
        # Sample of existing titles + synopses
        sample = formats[:40]
        catalogue_sample = "\n".join([
            "- {} [{}]: {}".format(f["title"], f["genre"], f["synopsis"][:100])
            for f in sample if f["title"]
        ])
        catalogue_context = (
            "\n\nYour existing format catalogue context ({} formats):\n"
            "Genre breakdown: {}\n\n"
            "Sample of existing formats:\n{}\n\n"
            "Use this catalogue to:\n"
            "1. Understand the team's style, tone and genre preferences\n"
            "2. Avoid duplicating concepts already in the catalogue\n"
            "3. Identify genuine white spaces and fresh angles\n"
            "4. Generate ideas that feel like they belong in this catalogue"
        ).format(len(formats), genre_summary, catalogue_sample)

    # Build trend list
    trend_list = "\n".join([
        "{}. \"{}\": {}{}".format(
            i+1, t.get("name",""), t.get("desc",""),
            " [tag: {}]".format(t.get("tag")) if t.get("tag") else ""
        )
        for i, t in enumerate(saved_trends)
    ])

    prompt = (
        "You are a senior unscripted TV format developer at a Dutch production company (KRO-NCRV, BNNVARA, Talpa)."
        "{}"
        "\n\nGenerate format concepts inspired by these cultural trends spotted in Dutch media today:\n\n{}\n\n"
        "Return ONLY a JSON object starting with {{ ending with }}:\n"
        "{{\"formats\":[{{\"title\":\"Format title\",\"logline\":\"One punchy sentence.\","
        "\"trendBasis\":\"Which trend(s)\",\"hook\":\"What makes this emotionally compelling for Dutch audience?\","
        "\"channel\":\"e.g. NPO1, RTL4, Netflix NL\",\"whyNew\":\"One sentence on why this fills a gap in the catalogue\"}}]}}\n\n"
        "Generate exactly 3 specific, pitchable format concepts. Make them feel fresh and distinct from the existing catalogue."
    ).format(catalogue_context, trend_list)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1400,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if not match:
            return jsonify({"error": "No JSON in response"})
        result = json.loads(match.group(0))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

# Format development knowledge base extracted from uploaded documents
FORMAT_DEV_SYSTEM = """You are an experienced unscripted TV format development executive at a Dutch production company. You are helping a colleague develop a rough format idea into a pitchable concept through conversation.

Your approach is drawn from proven development practice:
- Always start by finding the universal human QUESTION at the heart of the format. Not a social experiment, but a question people ask themselves: "What would I do?", "Could I survive?", "Is this person right for me?"
- The best formats have one "cheeky" or unexpected element — a twist on something familiar that makes people say "oh that's clever"
- Title is everything. A great title sells itself: it's punchy, tells you what the show is, and hints at the fun
- Keep it simple. Over-complicated formats fail. If you need a graphic to explain the game, it's too complex
- Think about NARRATIVE levers (character journey, conflict, alliances) not just FORMAT levers (the game mechanics)
- Know your casting archetypes — who are we watching and why do we care about them specifically?
- Think format-driven vs character-driven: format-driven shows let you control drama through structure; character-driven shows rely on personality conflict
- The logline should be one sentence that a stranger immediately understands and gets excited about
- Genre-blending is powerful: what happens if you take this format and set it in survival? Or add a scientific element? Or flip the end goal?
- Always think about the billboard/tile: what's the image and tagline that makes someone click?

Your conversation style:
- Ask ONE focused question at a time — don't overwhelm
- React to what the user says, build on it, push back gently if something is vague
- When you hear something strong, name it: "That's your hook right there"
- If the format is getting complicated, flag it: "Let's simplify — what's the ONE thing that makes this special?"
- After 6-8 exchanges, offer to summarize what you've built so far
- Be warm, direct, and creatively engaged — like a smart colleague in a development session, not a form to fill in
- Ask about the Dutch context when relevant: which broadcaster, what Dutch audience, what cultural specificity makes this work here

Never produce a full format document mid-conversation. Build it through dialogue. When the user feels ready, offer to produce a one-page format summary."""

@app.route("/develop", methods=["POST"])
def develop():
    """Format development conversation endpoint."""
    body = request.json or {}
    messages = body.get("messages", [])
    format_idea = body.get("format_idea", {})
    trends = body.get("trends", [])

    if not messages:
        return jsonify({"error": "No messages provided"})

    # Build context about the format idea and trends
    context = ""
    if format_idea:
        context += "The format idea being developed:\n"
        context += "Title: {}\n".format(format_idea.get("title", ""))
        context += "Logline: {}\n".format(format_idea.get("logline", ""))
        context += "Hook: {}\n".format(format_idea.get("hook", ""))
        context += "Trend basis: {}\n".format(format_idea.get("trendBasis", ""))
        context += "Target channel: {}\n".format(format_idea.get("channel", ""))
        context += "Why it's new: {}\n".format(format_idea.get("whyNew", ""))

    if trends:
        context += "\nCultural trends that inspired this idea:\n"
        for t in trends:
            context += "- {} ({}): {}\n".format(
                t.get("name", ""), t.get("momentum", ""), t.get("desc", "")
            )

    # Inject context into the system message
    system = FORMAT_DEV_SYSTEM
    if context:
        system += "\n\nContext for this session:\n" + context

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=system,
            messages=messages
        )
        return jsonify({"response": message.content[0].text})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/chat", methods=["POST"])
def chat():
    body = request.json
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=body.get("max_tokens", 2500),
        messages=body.get("messages", [])
    )
    return jsonify({"content": [{"type": "text", "text": message.content[0].text}]})

@app.route("/archive/save", methods=["POST"])
def archive_save():
    body = request.json
    conn = get_db()
    cur = db_cursor(conn)
    ph = ",".join([PLACEHOLDER] * 10)
    cur.execute(
        "INSERT INTO saved_trends (name, desc, momentum, signals, source_labels, source_links, format_hint, tag, region, saved_at) VALUES (" + ph + ")",
        (body.get("name"), body.get("desc"), body.get("momentum"), body.get("signals"),
         json.dumps(body.get("source_labels", [])), json.dumps(body.get("source_links", [])),
         body.get("format_hint"), body.get("tag", ""), body.get("region", "nl"),
         datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/archive/dates")
def archive_dates():
    conn = get_db()
    cur = db_cursor(conn)
    cur.execute("SELECT substr(saved_at, 1, 10) as date, COUNT(*) as count FROM saved_trends GROUP BY date ORDER BY date DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"dates": [{"date": r["date"], "count": r["count"]} for r in rows]})

@app.route("/archive/by-date")
def archive_by_date():
    date = request.args.get("date", "")
    conn = get_db()
    cur = db_cursor(conn)
    cur.execute("SELECT * FROM saved_trends WHERE substr(saved_at, 1, 10) = " + PLACEHOLDER + " ORDER BY saved_at DESC", (date,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"trends": [dict(r) for r in rows]})

@app.route("/archive/search", methods=["POST"])
def archive_search():
    """Semantic search across all saved trends using Claude."""
    body = request.json or {}
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"results": []})

    # Load all saved trends from the database
    conn = get_db()
    cur = db_cursor(conn)
    cur.execute("SELECT * FROM saved_trends ORDER BY saved_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return jsonify({"results": [], "message": "No trends in archive yet."})

    all_trends = [dict(r) for r in rows]

    # Build trend list for Claude
    trend_list = "\n".join([
        "{}. [{}] {}: {}".format(
            i+1,
            t.get("saved_at", "")[:10],
            t.get("name", ""),
            t.get("desc", "")[:200]
        )
        for i, t in enumerate(all_trends)
    ])

    prompt = (
        "You are a TV format development assistant helping a Dutch production company search their trend archive.\n\n"
        "Search query: \"{}\"\n\n"
        "Saved trends archive:\n{}\n\n"
        "Find the trends most relevant to the search query. Think semantically — if someone searches "
        "'loneliness' also consider trends about isolation, disconnection, social anxiety, community loss etc. "
        "If someone searches a format concept like 'families under pressure', find trends about work-life balance, "
        "parenting stress, financial anxiety etc.\n\n"
        "Return ONLY a JSON object starting with {{ ending with }}:\n"
        "{{\"results\":[{{\"index\":1,\"relevance\":\"One sentence explaining why this trend is relevant to the query\"}}]}}\n\n"
        "Return the top 5 most relevant trends by their index number. If fewer than 5 are relevant, return only those. "
        "If nothing is relevant, return an empty results array."
    ).format(query, trend_list)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if not match:
            return jsonify({"results": [], "message": "No results found."})
        result = json.loads(match.group(0))
        raw_results = result.get("results", [])

        # Enrich results with full trend data
        enriched = []
        for r in raw_results:
            idx = r.get("index", 0) - 1
            if 0 <= idx < len(all_trends):
                trend = dict(all_trends[idx])
                trend["relevance"] = r.get("relevance", "")
                enriched.append(trend)

        return jsonify({"results": enriched, "count": len(enriched)})
    except Exception as e:
        return jsonify({"error": str(e), "results": []})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
