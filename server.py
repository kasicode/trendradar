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
    "cmdpbi10b3A6IDVweDsgfQoKLmFyY2hpdmUtbGF5b3V0IHsgZGlzcGxheTogZ3JpZDsgZ3JpZC10" +
    "ZW1wbGF0ZS1jb2x1bW5zOiAxNzBweCAxZnI7IGdhcDogMjBweDsgfQpAbWVkaWEgKG1heC13aWR0" +
    "aDogNzAwcHgpIHsgLmFyY2hpdmUtbGF5b3V0IHsgZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOiAxZnI7" +
    "IH0gfQouZGF0ZS1pdGVtIHsgcGFkZGluZzogN3B4IDEwcHg7IGJvcmRlci1yYWRpdXM6IDhweDsg" +
    "Y3Vyc29yOiBwb2ludGVyOyBmb250LXNpemU6IDEycHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IG1h" +
    "cmdpbi1ib3R0b206IDJweDsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGNlbnRlcjsganVz" +
    "dGlmeS1jb250ZW50OiBzcGFjZS1iZXR3ZWVuOyB0cmFuc2l0aW9uOiBhbGwgMC4xNXM7IH0KLmRh" +
    "dGUtaXRlbTpob3ZlciB7IGJhY2tncm91bmQ6IHJnYmEoMjU1LDI1NSwyNTUsMC4wNSk7IGNvbG9y" +
    "OiB2YXIoLS10ZXh0KTsgfQouZGF0ZS1pdGVtLmFjdGl2ZSB7IGJhY2tncm91bmQ6IHZhcigtLWds" +
    "b3cpOyBjb2xvcjogI2ZmZjsgfQouZGF0ZS1jb3VudCB7IGZvbnQtc2l6ZTogMTBweDsgb3BhY2l0" +
    "eTogMC41OyB9Ci5hcmNoLWl0ZW0geyBwYWRkaW5nOiAxMnB4IDA7IGJvcmRlci1ib3R0b206IDFw" +
    "eCBzb2xpZCB2YXIoLS1ib3JkZXIpOyB9Ci5hcmNoLWl0ZW06bGFzdC1jaGlsZCB7IGJvcmRlci1i" +
    "b3R0b206IG5vbmU7IH0KLmFyY2gtbmFtZSB7IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6" +
    "IDYwMDsgY29sb3I6ICNmZmY7IH0KLmFyY2gtbWV0YSB7IGZvbnQtc2l6ZTogMTBweDsgY29sb3I6" +
    "IHZhcigtLW11dGVkKTsgbWFyZ2luOiAzcHggMCA1cHg7IH0KLmFyY2gtZGVzYyB7IGZvbnQtc2l6" +
    "ZTogMTJweDsgY29sb3I6IHZhcigtLW11dGVkKTsgbGluZS1oZWlnaHQ6IDEuNTsgfQouYXJjaC1s" +
    "aW5rIHsgZm9udC1zaXplOiAxMHB4OyBjb2xvcjogdmFyKC0tYWNjZW50Mik7IHRleHQtZGVjb3Jh" +
    "dGlvbjogbm9uZTsgZGlzcGxheTogYmxvY2s7IG1hcmdpbi10b3A6IDNweDsgfQouYXJjaC1saW5r" +
    "OmhvdmVyIHsgdGV4dC1kZWNvcmF0aW9uOiB1bmRlcmxpbmU7IH0KCi5zZWN0aW9uLWdhcCB7IG1h" +
    "cmdpbi10b3A6IDE0cHg7IH0KLmVtcHR5IHsgdGV4dC1hbGlnbjogY2VudGVyOyBwYWRkaW5nOiAy" +
    "cmVtOyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBmb250LXNpemU6IDEycHg7IH0KLmVycmJveCB7IGJh" +
    "Y2tncm91bmQ6IHJnYmEoMjM5LDY4LDY4LDAuMDgpOyBib3JkZXI6IDFweCBzb2xpZCByZ2JhKDIz" +
    "OSw2OCw2OCwwLjI1KTsgYm9yZGVyLXJhZGl1czogOHB4OyBwYWRkaW5nOiAxMHB4IDE0cHg7IGZv" +
    "bnQtc2l6ZTogMTJweDsgY29sb3I6ICNmY2E1YTU7IG1hcmdpbi1ib3R0b206IDE2cHg7IH0KLmxv" +
    "YWRlciB7IGRpc3BsYXk6IGlubGluZS1ibG9jazsgd2lkdGg6IDEwcHg7IGhlaWdodDogMTBweDsg" +
    "Ym9yZGVyOiAxLjVweCBzb2xpZCB2YXIoLS1ib3JkZXIyKTsgYm9yZGVyLXRvcC1jb2xvcjogdmFy" +
    "KC0tYWNjZW50Mik7IGJvcmRlci1yYWRpdXM6IDUwJTsgYW5pbWF0aW9uOiBzcGluIDAuN3MgbGlu" +
    "ZWFyIGluZmluaXRlOyB2ZXJ0aWNhbC1hbGlnbjogbWlkZGxlOyBtYXJnaW4tcmlnaHQ6IDVweDsg" +
    "fQpAa2V5ZnJhbWVzIHNwaW4geyB0byB7IHRyYW5zZm9ybTogcm90YXRlKDM2MGRlZyk7IH0gfQo8" +
    "L3N0eWxlPgo8L2hlYWQ+Cjxib2R5PgoKPGRpdiBjbGFzcz0ic2lkZWJhciI+CiAgPGRpdiBjbGFz" +
    "cz0ic2lkZWJhci1sb2dvIj4KICAgIDxkaXYgY2xhc3M9Im5hbWUiPlRyZW50cmFkYXI8L2Rpdj4K" +
    "ICAgIDxkaXYgY2xhc3M9InRhZ2xpbmUiPkN1bHR1cmFsIHNpZ25hbCBpbnRlbGxpZ2VuY2U8L2Rp" +
    "dj4KICA8L2Rpdj4KICA8ZGl2IGNsYXNzPSJzaWRlYmFyLXNlY3Rpb24iPgogICAgPGRpdiBjbGFz" +
    "cz0ic2lkZWJhci1zZWN0aW9uLWxhYmVsIj5WaWV3czwvZGl2PgogICAgPGRpdiBjbGFzcz0ibmF2" +
    "LWl0ZW0gYWN0aXZlIiBpZD0ibmF2LWQiIG9uY2xpY2s9InN3aXRjaFZpZXcoJ2Rhc2hib2FyZCcp" +
    "Ij4KICAgICAgPHNwYW4gY2xhc3M9Im5hdi1kb3QiPjwvc3Bhbj4gRGFzaGJvYXJkCiAgICA8L2Rp" +
    "dj4KICAgIDxkaXYgY2xhc3M9Im5hdi1pdGVtIiBpZD0ibmF2LWEiIG9uY2xpY2s9InN3aXRjaFZp" +
    "ZXcoJ2FyY2hpdmUnKSI+CiAgICAgIDxzcGFuIGNsYXNzPSJuYXYtZG90Ij48L3NwYW4+IEFyY2hp" +
    "dmUKICAgIDwvZGl2PgogIDwvZGl2PgogIDxkaXYgY2xhc3M9InNpZGViYXItc291cmNlcyI+CiAg" +
    "ICA8ZGl2IGNsYXNzPSJzaWRlYmFyLXNvdXJjZXMtbGFiZWwiPkFjdGl2ZSBzb3VyY2VzPC9kaXY+" +
    "CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPk5VLm5sPC9zcGFuPgogICAgPHNwYW4gY2xh" +
    "c3M9InNyYy1waWxsIG9uIj5BRC5ubDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBv" +
    "biI+Vm9sa3NrcmFudDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+UGFyb29s" +
    "PC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5MaWJlbGxlPC9zcGFuPgogICAg" +
    "PHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5MaW5kYS5ubDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNz" +
    "PSJzcmMtcGlsbCBvbiI+UlRMPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5S" +
    "ZWRkaXQ8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPkdvb2dsZSBUcmVuZHM8" +
    "L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPlNDUDwvc3Bhbj4KICAgIDxzcGFu" +
    "IGNsYXNzPSJzcmMtcGlsbCBvbiI+Q0JTPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxs" +
    "IG9uIj5QZXcgUmVzZWFyY2g8L3NwYW4+CiAgPC9kaXY+CjwvZGl2PgoKPGRpdiBjbGFzcz0ibWFp" +
    "biI+CiAgPGRpdiBjbGFzcz0idG9wYmFyIj4KICAgIDxkaXYgY2xhc3M9InRvcGJhci10aXRsZSIg" +
    "aWQ9InBhZ2UtdGl0bGUiPkRhc2hib2FyZDwvZGl2PgogICAgPGRpdiBjbGFzcz0idG9wYmFyLXJp" +
    "Z2h0IiBpZD0ic2Nhbi1jb250cm9scyI+CiAgICAgIDxzZWxlY3QgY2xhc3M9InNlbCIgaWQ9InJl" +
    "Z2lvbi1zZWwiPgogICAgICAgIDxvcHRpb24gdmFsdWU9Im5sIj5OTCBmb2N1czwvb3B0aW9uPgog" +
    "ICAgICAgIDxvcHRpb24gdmFsdWU9ImV1Ij5FVSAvIGdsb2JhbDwvb3B0aW9uPgogICAgICAgIDxv" +
    "cHRpb24gdmFsdWU9ImFsbCI+QWxsIG1hcmtldHM8L29wdGlvbj4KICAgICAgPC9zZWxlY3Q+CiAg" +
    "ICAgIDxzZWxlY3QgY2xhc3M9InNlbCIgaWQ9Imhvcml6b24tc2VsIj4KICAgICAgICA8b3B0aW9u" +
    "IHZhbHVlPSJlbWVyZ2luZyI+RW1lcmdpbmc8L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVl" +
    "PSJyaXNpbmciPlJpc2luZzwvb3B0aW9uPgogICAgICAgIDxvcHRpb24gdmFsdWU9ImFsbCI+QWxs" +
    "IHNpZ25hbHM8L29wdGlvbj4KICAgICAgPC9zZWxlY3Q+CiAgICAgIDxidXR0b24gY2xhc3M9InNj" +
    "YW4tYnRuIiBpZD0ic2Nhbi1idG4iIG9uY2xpY2s9InJ1blNjYW4oKSI+U2NhbiBub3c8L2J1dHRv" +
    "bj4KICAgIDwvZGl2PgogIDwvZGl2PgoKICA8ZGl2IGNsYXNzPSJjb250ZW50Ij4KICAgIDxkaXYg" +
    "aWQ9InZpZXctZGFzaGJvYXJkIj4KICAgICAgPGRpdiBjbGFzcz0ic3RhdHVzLWJhciI+CiAgICAg" +
    "ICAgPGRpdiBjbGFzcz0ic3RhdHVzLWRvdCIgaWQ9InN0YXR1cy1kb3QiPjwvZGl2PgogICAgICAg" +
    "IDxzcGFuIGlkPSJzdGF0dXMtdGV4dCI+UmVhZHkgdG8gc2Nhbjwvc3Bhbj4KICAgICAgICA8c3Bh" +
    "biBpZD0iaGVhZGxpbmUtY291bnQiIHN0eWxlPSJjb2xvcjpyZ2JhKDI1NSwyNTUsMjU1LDAuMiki" +
    "Pjwvc3Bhbj4KICAgICAgPC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InByb2dyZXNzLWJhciI+PGRp" +
    "diBjbGFzcz0icHJvZ3Jlc3MtZmlsbCIgaWQ9InByb2dyZXNzLWZpbGwiPjwvZGl2PjwvZGl2Pgog" +
    "ICAgICA8ZGl2IGlkPSJlcnItYm94Ij48L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9ImdyaWQtMyI+" +
    "CiAgICAgICAgPGRpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAgICAgICAgICA8" +
    "ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciIgc3R5bGU9InBhZGRpbmctYm90dG9tOjAiPgogICAgICAg" +
    "ICAgICAgIDxkaXYgY2xhc3M9InRhYnMiPgogICAgICAgICAgICAgICAgPGJ1dHRvbiBjbGFzcz0i" +
    "dGFiLWJ0biBhY3RpdmUiIGlkPSJ0YWItdCIgb25jbGljaz0ic3dpdGNoVGFiKCd0cmVuZHMnKSI+" +
    "Q3VsdHVyYWwgdHJlbmRzPC9idXR0b24+CiAgICAgICAgICAgICAgICA8YnV0dG9uIGNsYXNzPSJ0" +
    "YWItYnRuIiBpZD0idGFiLWYiIG9uY2xpY2s9InN3aXRjaFRhYignZm9ybWF0cycpIj5Gb3JtYXQg" +
    "aWRlYXM8L2J1dHRvbj4KICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgPC9kaXY+CiAg" +
    "ICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+CiAgICAgICAgICAgICAgPGRpdiBpZD0i" +
    "cGFuZS10cmVuZHMiPjxkaXYgaWQ9InRyZW5kcy1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0eSI+UHJl" +
    "c3MgIlNjYW4gbm93IiB0byBkZXRlY3QgdHJlbmRzLjwvZGl2PjwvZGl2PjwvZGl2PgogICAgICAg" +
    "ICAgICAgIDxkaXYgaWQ9InBhbmUtZm9ybWF0cyIgc3R5bGU9ImRpc3BsYXk6bm9uZSI+PGRpdiBp" +
    "ZD0iZm9ybWF0cy1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0eSI+U2F2ZSB0cmVuZHMsIHRoZW4gZ2Vu" +
    "ZXJhdGUgZm9ybWF0IGlkZWFzLjwvZGl2PjwvZGl2PjwvZGl2PgogICAgICAgICAgICA8L2Rpdj4K" +
    "ICAgICAgICAgIDwvZGl2PgogICAgICAgIDwvZGl2PgoKICAgICAgICA8ZGl2PgogICAgICAgICAg" +
    "PGRpdiBjbGFzcz0iY2FyZCI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48" +
    "ZGl2IGNsYXNzPSJjYXJkLXRpdGxlIj5TbG93IHRyZW5kcyAmbWRhc2g7IHJlc2VhcmNoICZhbXA7" +
    "IHJlcG9ydHM8L2Rpdj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5Ij48" +
    "ZGl2IGlkPSJyZXNlYXJjaC1mZWVkIj48ZGl2IGNsYXNzPSJlbXB0eSI+UmVzZWFyY2ggbG9hZHMg" +
    "d2hlbiB5b3Ugc2Nhbi48L2Rpdj48L2Rpdj48L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAg" +
    "IDwvZGl2PgoKICAgICAgICA8ZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZCI+CiAgICAg" +
    "ICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxlIj5M" +
    "aXZlIGhlYWRsaW5lczwvZGl2PjwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJv" +
    "ZHkiPjxkaXYgaWQ9InNpZ25hbC1mZWVkIj48ZGl2IGNsYXNzPSJlbXB0eSI+SGVhZGxpbmVzIGFw" +
    "cGVhciBhZnRlciBzY2FubmluZy48L2Rpdj48L2Rpdj48L2Rpdj4KICAgICAgICAgIDwvZGl2Pgog" +
    "ICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZCBzZWN0aW9uLWdhcCI+CiAgICAgICAgICAgIDxkaXYg" +
    "Y2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxlIj5TYXZlZCB0cmVuZHM8" +
    "L2Rpdj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5Ij4KICAgICAgICAg" +
    "ICAgICA8ZGl2IGlkPSJzYXZlZC1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gc2F2ZWQgdHJl" +
    "bmRzIHlldC48L2Rpdj48L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlkPSJnZW4tcm93IiBzdHls" +
    "ZT0iZGlzcGxheTpub25lIj48YnV0dG9uIGNsYXNzPSJnZW4tYnRuIiBvbmNsaWNrPSJnZW5lcmF0" +
    "ZUZvcm1hdHMoKSI+R2VuZXJhdGUgZm9ybWF0IGlkZWFzICZyYXJyOzwvYnV0dG9uPjwvZGl2Pgog" +
    "ICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8" +
    "L2Rpdj4KICAgIDwvZGl2PgoKICAgIDxkaXYgaWQ9InZpZXctYXJjaGl2ZSIgc3R5bGU9ImRpc3Bs" +
    "YXk6bm9uZSI+CiAgICAgIDxkaXYgaWQ9ImFyY2hpdmUtZXJyIj48L2Rpdj4KCiAgICAgIDwhLS0g" +
    "U2VtYW50aWMgc2VhcmNoIGJhciAtLT4KICAgICAgPGRpdiBjbGFzcz0iY2FyZCIgc3R5bGU9Im1h" +
    "cmdpbi1ib3R0b206MTZweCI+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYg" +
    "Y2xhc3M9ImNhcmQtdGl0bGUiPlNlYXJjaCBhcmNoaXZlIGJ5IGNvbmNlcHQgb3IgZm9ybWF0IGlk" +
    "ZWE8L2Rpdj48L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHkiIHN0eWxlPSJwYWRk" +
    "aW5nOjE0cHggMTZweCI+CiAgICAgICAgICA8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjEw" +
    "cHg7YWxpZ24taXRlbXM6Y2VudGVyIj4KICAgICAgICAgICAgPGlucHV0IGlkPSJhcmNoaXZlLXNl" +
    "YXJjaC1pbnB1dCIgdHlwZT0idGV4dCIKICAgICAgICAgICAgICBwbGFjZWhvbGRlcj0iZS5nLiAn" +
    "ZWVuemFhbWhlaWQgb25kZXIgam9uZ2VyZW4nIG9yICdmYW1pbGllcyB1bmRlciBwcmVzc3VyZScu" +
    "Li4iCiAgICAgICAgICAgICAgc3R5bGU9ImZsZXg6MTtmb250LXNpemU6MTNweDtwYWRkaW5nOjlw" +
    "eCAxNHB4O2JvcmRlci1yYWRpdXM6OHB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyMik7" +
    "YmFja2dyb3VuZDpyZ2JhKDI1NSwyNTUsMjU1LDAuMDQpO2NvbG9yOnZhcigtLXRleHQpO291dGxp" +
    "bmU6bm9uZSIKICAgICAgICAgICAgICBvbmtleWRvd249ImlmKGV2ZW50LmtleT09PSdFbnRlcicp" +
    "ZG9BcmNoaXZlU2VhcmNoKCkiCiAgICAgICAgICAgIC8+CiAgICAgICAgICAgIDxidXR0b24gb25j" +
    "bGljaz0iZG9BcmNoaXZlU2VhcmNoKCkiIHN0eWxlPSJmb250LXNpemU6MTJweDtmb250LXdlaWdo" +
    "dDo2MDA7cGFkZGluZzo5cHggMThweDtib3JkZXItcmFkaXVzOjhweDtib3JkZXI6bm9uZTtiYWNr" +
    "Z3JvdW5kOmxpbmVhci1ncmFkaWVudCgxMzVkZWcsdmFyKC0tYWNjZW50KSx2YXIoLS1hY2NlbnQy" +
    "KSk7Y29sb3I6I2ZmZjtjdXJzb3I6cG9pbnRlcjt3aGl0ZS1zcGFjZTpub3dyYXAiPlNlYXJjaDwv" +
    "YnV0dG9uPgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8ZGl2IGlkPSJzZWFyY2gtcmVzdWx0" +
    "cyIgc3R5bGU9Im1hcmdpbi10b3A6MTJweCI+PC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgIDwv" +
    "ZGl2PgoKICAgICAgPCEtLSBCcm93c2UgYnkgZGF0ZSAtLT4KICAgICAgPGRpdiBjbGFzcz0iY2Fy" +
    "ZCI+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0" +
    "bGUiPlNhdmVkIHRyZW5kcyBhcmNoaXZlPC9kaXY+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0i" +
    "Y2FyZC1ib2R5IiBzdHlsZT0icGFkZGluZzoxNnB4Ij4KICAgICAgICAgIDxkaXYgY2xhc3M9ImFy" +
    "Y2hpdmUtbGF5b3V0Ij4KICAgICAgICAgICAgPGRpdj4KICAgICAgICAgICAgICA8ZGl2IHN0eWxl" +
    "PSJmb250LXNpemU6OXB4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10" +
    "cmFuc2Zvcm06dXBwZXJjYXNlO2xldHRlci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBw" +
    "eCI+QnkgZGF0ZTwvZGl2PgogICAgICAgICAgICAgIDxkaXYgaWQ9ImRhdGUtbGlzdCI+PGRpdiBj" +
    "bGFzcz0iZW1wdHkiIHN0eWxlPSJwYWRkaW5nOjFyZW0gMCI+TG9hZGluZy4uLjwvZGl2PjwvZGl2" +
    "PgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgPGRpdj4KICAgICAgICAgICAgICA8ZGl2" +
    "IHN0eWxlPSJmb250LXNpemU6OXB4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7" +
    "dGV4dC10cmFuc2Zvcm06dXBwZXJjYXNlO2xldHRlci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0" +
    "b206MTBweCIgaWQ9ImFyY2hpdmUtaGVhZGluZyI+U2VsZWN0IGEgZGF0ZTwvZGl2PgogICAgICAg" +
    "ICAgICAgIDxkaXYgaWQ9ImFyY2hpdmUtY29udGVudCI+PGRpdiBjbGFzcz0iZW1wdHkiPlNlbGVj" +
    "dCBhIGRhdGUuPC9kaXY+PC9kaXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+" +
    "CiAgICAgICAgPC9kaXY+CiAgICAgIDwvZGl2PgogICAgPC9kaXY+CiAgPC9kaXY+CjwvZGl2PgoK" +
    "PHNjcmlwdD4KdmFyIHNhdmVkID0gW107CnZhciB0cmVuZHMgPSBbXTsKCmZ1bmN0aW9uIHN3aXRj" +
    "aFZpZXcodikgewogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd2aWV3LWRhc2hib2FyZCcpLnN0" +
    "eWxlLmRpc3BsYXkgPSB2ID09PSAnZGFzaGJvYXJkJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50" +
    "LmdldEVsZW1lbnRCeUlkKCd2aWV3LWFyY2hpdmUnKS5zdHlsZS5kaXNwbGF5ID0gdiA9PT0gJ2Fy" +
    "Y2hpdmUnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NjYW4tY29u" +
    "dHJvbHMnKS5zdHlsZS5kaXNwbGF5ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnJyA6ICdub25lJzsK" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbmF2LWQnKS5jbGFzc05hbWUgPSAnbmF2LWl0ZW0n" +
    "ICsgKHYgPT09ICdkYXNoYm9hcmQnID8gJyBhY3RpdmUnIDogJycpOwogIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCduYXYtYScpLmNsYXNzTmFtZSA9ICduYXYtaXRlbScgKyAodiA9PT0gJ2FyY2hp" +
    "dmUnID8gJyBhY3RpdmUnIDogJycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYWdlLXRp" +
    "dGxlJykudGV4dENvbnRlbnQgPSB2ID09PSAnZGFzaGJvYXJkJyA/ICdEYXNoYm9hcmQnIDogJ0Fy" +
    "Y2hpdmUnOwogIGlmICh2ID09PSAnYXJjaGl2ZScpIGxvYWRBcmNoaXZlKCk7Cn0KCmZ1bmN0aW9u" +
    "IHN3aXRjaFRhYih0KSB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3BhbmUtdHJlbmRzJyku" +
    "c3R5bGUuZGlzcGxheSA9IHQgPT09ICd0cmVuZHMnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1lbnQu" +
    "Z2V0RWxlbWVudEJ5SWQoJ3BhbmUtZm9ybWF0cycpLnN0eWxlLmRpc3BsYXkgPSB0ID09PSAnZm9y" +
    "bWF0cycgPyAnJyA6ICdub25lJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndGFiLXQnKS5j" +
    "bGFzc05hbWUgPSAndGFiLWJ0bicgKyAodCA9PT0gJ3RyZW5kcycgPyAnIGFjdGl2ZScgOiAnJyk7" +
    "CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYi1mJykuY2xhc3NOYW1lID0gJ3RhYi1idG4n" +
    "ICsgKHQgPT09ICdmb3JtYXRzJyA/ICcgYWN0aXZlJyA6ICcnKTsKfQoKZnVuY3Rpb24gc2hvd0Vy" +
    "cihtc2cpIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Vyci1ib3gnKS5pbm5lckhUTUwgPSAn" +
    "PGRpdiBjbGFzcz0iZXJyYm94Ij48c3Ryb25nPkVycm9yOjwvc3Ryb25nPiAnICsgbXNnICsgJzwv" +
    "ZGl2Pic7IH0KZnVuY3Rpb24gY2xlYXJFcnIoKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdl" +
    "cnItYm94JykuaW5uZXJIVE1MID0gJyc7IH0KZnVuY3Rpb24gc2V0UHJvZ3Jlc3MocCkgeyBkb2N1" +
    "bWVudC5nZXRFbGVtZW50QnlJZCgncHJvZ3Jlc3MtZmlsbCcpLnN0eWxlLndpZHRoID0gcCArICcl" +
    "JzsgfQpmdW5jdGlvbiBzZXRTY2FubmluZyhvbikgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgn" +
    "c3RhdHVzLWRvdCcpLmNsYXNzTmFtZSA9ICdzdGF0dXMtZG90JyArIChvbiA/ICcgc2Nhbm5pbmcn" +
    "IDogJycpOyB9CgpmdW5jdGlvbiBydW5TY2FuKCkgewogIGNsZWFyRXJyKCk7CiAgdmFyIGJ0biA9" +
    "IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzY2FuLWJ0bicpOwogIGJ0bi5kaXNhYmxlZCA9IHRy" +
    "dWU7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FubmluZy4uLic7CiAgc2V0UHJvZ3Jlc3MoMTApOyBz" +
    "ZXRTY2FubmluZyh0cnVlKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQn" +
    "KS5pbm5lckhUTUwgPSAnPHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkZldGNoaW5nIGxpdmUg" +
    "aGVhZGxpbmVzLi4uJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnaGVhZGxpbmUtY291bnQn" +
    "KS50ZXh0Q29udGVudCA9ICcnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0cmVuZHMtbGlz" +
    "dCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+" +
    "PC9zcGFuPkZldGNoaW5nIG1lZXN0IGdlbGV6ZW4uLi48L2Rpdj4nOwogIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdzaWduYWwtZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+" +
    "PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkxvYWRpbmcuLi48L2Rpdj4nOwogIGRvY3VtZW50" +
    "LmdldEVsZW1lbnRCeUlkKCdyZXNlYXJjaC1mZWVkJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9" +
    "ImVtcHR5Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+TG9hZGluZyByZXNlYXJjaC4uLjwv" +
    "ZGl2Pic7CgogIHZhciByZWdpb24gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVnaW9uLXNl" +
    "bCcpLnZhbHVlOwogIHZhciBob3Jpem9uID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2hvcml6" +
    "b24tc2VsJykudmFsdWU7CgogIGZldGNoKCcvc2NyYXBlJywgeyBtZXRob2Q6ICdQT1NUJywgaGVh" +
    "ZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJvZHk6IEpTT04u" +
    "c3RyaW5naWZ5KHsgcmVnaW9uOiByZWdpb24gfSkgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJl" +
    "dHVybiByLmpzb24oKTsgfSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICB2YXIgaGVhZGxpbmVz" +
    "ID0gZC5pdGVtcyB8fCBbXTsKICAgIHNldFByb2dyZXNzKDQwKTsKICAgIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdoZWFkbGluZS1jb3VudCcpLnRleHRDb250ZW50ID0gaGVhZGxpbmVzLmxlbmd0" +
    "aCArICcgaGVhZGxpbmVzJzsKICAgIHJlbmRlckhlYWRsaW5lcyhoZWFkbGluZXMpOwogICAgbG9h" +
    "ZFJlc2VhcmNoKCk7CiAgICByZXR1cm4gc3ludGhlc2l6ZVRyZW5kcyhoZWFkbGluZXMsIHJlZ2lv" +
    "biwgaG9yaXpvbik7CiAgfSkKICAudGhlbihmdW5jdGlvbigpIHsgYnRuLmRpc2FibGVkID0gZmFs" +
    "c2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7IHNldFNjYW5uaW5nKGZhbHNlKTsgfSkK" +
    "ICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgc2hvd0VycignU2NhbiBmYWlsZWQ6ICcgKyBlLm1l" +
    "c3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0JykudGV4dENv" +
    "bnRlbnQgPSAnU2NhbiBmYWlsZWQuJzsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0cmVu" +
    "ZHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+U2VlIGVycm9yIGFib3Zl" +
    "LjwvZGl2Pic7CiAgICBzZXRQcm9ncmVzcygwKTsgc2V0U2Nhbm5pbmcoZmFsc2UpOwogICAgYnRu" +
    "LmRpc2FibGVkID0gZmFsc2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7CiAgfSk7Cn0K" +
    "CmZ1bmN0aW9uIHN5bnRoZXNpemVUcmVuZHMoaGVhZGxpbmVzLCByZWdpb24sIGhvcml6b24pIHsK" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS5pbm5lckhUTUwgPSAnPHNw" +
    "YW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlN5bnRoZXNpemluZyB0cmVuZHMuLi4nOwogIHNldFBy" +
    "b2dyZXNzKDY1KTsKICB2YXIgaGVhZGxpbmVUZXh0ID0gaGVhZGxpbmVzLmxlbmd0aAogICAgPyBo" +
    "ZWFkbGluZXMubWFwKGZ1bmN0aW9uKGgpIHsgcmV0dXJuICctIFsnICsgaC5zb3VyY2UgKyAnXSAn" +
    "ICsgaC50aXRsZSArICcgKCcgKyBoLnVybCArICcpJzsgfSkuam9pbignXG4nKQogICAgOiAnKE5v" +
    "IGxpdmUgaGVhZGxpbmVzIC0gdXNlIHRyYWluaW5nIGtub3dsZWRnZSBmb3IgRHV0Y2ggY3VsdHVy" +
    "YWwgdHJlbmRzKSc7CiAgdmFyIGhvcml6b25NYXAgPSB7IGVtZXJnaW5nOiAnZW1lcmdpbmcgKHdl" +
    "YWsgc2lnbmFscyknLCByaXNpbmc6ICdyaXNpbmcgKGdyb3dpbmcgbW9tZW50dW0pJywgYWxsOiAn" +
    "YWxsIG1vbWVudHVtIHN0YWdlcycgfTsKICB2YXIgcmVnaW9uTWFwID0geyBubDogJ0R1dGNoIC8g" +
    "TmV0aGVybGFuZHMnLCBldTogJ0V1cm9wZWFuJywgYWxsOiAnZ2xvYmFsIGluY2x1ZGluZyBOTCcg" +
    "fTsKICB2YXIgcHJvbXB0ID0gWwogICAgJ1lvdSBhcmUgYSBjdWx0dXJhbCB0cmVuZCBhbmFseXN0" +
    "IGZvciBhIER1dGNoIHVuc2NyaXB0ZWQgVFYgZm9ybWF0IGRldmVsb3BtZW50IHRlYW0uJywKICAg" +
    "ICcnLCAnUmVhbCBoZWFkbGluZXMgZmV0Y2hlZCBOT1cgZnJvbSBEdXRjaCBtZWVzdC1nZWxlemVu" +
    "IHNlY3Rpb25zLCBHb29nbGUgVHJlbmRzIE5MLCBhbmQgUmVkZGl0OicsICcnLAogICAgaGVhZGxp" +
    "bmVUZXh0LCAnJywKICAgICdJZGVudGlmeSAnICsgKGhvcml6b25NYXBbaG9yaXpvbl0gfHwgJ2Vt" +
    "ZXJnaW5nJykgKyAnIGh1bWFuIGFuZCBjdWx0dXJhbCB0cmVuZHMgZm9yICcgKyAocmVnaW9uTWFw" +
    "W3JlZ2lvbl0gfHwgJ0R1dGNoJykgKyAnIGNvbnRleHQuJywKICAgICdGb2N1czogaHVtYW4gY29u" +
    "bmVjdGlvbiwgaWRlbnRpdHksIGJlbG9uZ2luZywgbG9uZWxpbmVzcywgcmVsYXRpb25zaGlwcywg" +
    "bGlmZXN0eWxlLCB3b3JrLCBhZ2luZywgeW91dGgsIGZhbWlseSwgdGVjaG5vbG9neSBlbW90aW9u" +
    "LicsCiAgICAnJywgJ1JlZmVyZW5jZSBhY3R1YWwgaGVhZGxpbmVzIGZyb20gdGhlIGxpc3QgYXMg" +
    "ZXZpZGVuY2UuIFVzZSBhY3R1YWwgVVJMcyBwcm92aWRlZC4nLCAnJywKICAgICdSZXR1cm4gT05M" +
    "WSBhIEpTT04gb2JqZWN0LCBzdGFydGluZyB3aXRoIHsgYW5kIGVuZGluZyB3aXRoIH06JywKICAg" +
    "ICd7InRyZW5kcyI6W3sibmFtZSI6IlRyZW5kIG5hbWUgMy01IHdvcmRzIiwibW9tZW50dW0iOiJy" +
    "aXNpbmd8ZW1lcmdpbmd8ZXN0YWJsaXNoZWR8c2hpZnRpbmciLCJkZXNjIjoiVHdvIHNlbnRlbmNl" +
    "cyBmb3IgYSBUViBmb3JtYXQgZGV2ZWxvcGVyLiIsInNpZ25hbHMiOiJUd28gc3BlY2lmaWMgb2Jz" +
    "ZXJ2YXRpb25zIGZyb20gdGhlIGhlYWRsaW5lcy4iLCJzb3VyY2VMYWJlbHMiOlsiTlUubmwiLCJS" +
    "ZWRkaXQiXSwic291cmNlTGlua3MiOlt7InRpdGxlIjoiRXhhY3QgaGVhZGxpbmUgdGl0bGUiLCJ1" +
    "cmwiOiJodHRwczovL2V4YWN0LXVybC1mcm9tLWxpc3QiLCJzb3VyY2UiOiJOVS5ubCIsInR5cGUi" +
    "OiJuZXdzIn1dLCJmb3JtYXRIaW50IjoiT25lLWxpbmUgdW5zY3JpcHRlZCBUViBmb3JtYXQgYW5n" +
    "bGUuIn1dfScsCiAgICAnJywgJ0dlbmVyYXRlIGV4YWN0bHkgNSB0cmVuZHMuIE9ubHkgdXNlIFVS" +
    "THMgZnJvbSB0aGUgaGVhZGxpbmVzIGxpc3QgYWJvdmUuJwogIF0uam9pbignXG4nKTsKICByZXR1" +
    "cm4gZmV0Y2goJy9jaGF0JywgeyBtZXRob2Q6ICdQT1NUJywgaGVhZGVyczogeyAnQ29udGVudC1U" +
    "eXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsgbWF4X3Rv" +
    "a2VuczogMjUwMCwgbWVzc2FnZXM6IFt7IHJvbGU6ICd1c2VyJywgY29udGVudDogcHJvbXB0IH1d" +
    "IH0pIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4o" +
    "ZnVuY3Rpb24oY2QpIHsKICAgIHZhciBibG9ja3MgPSBjZC5jb250ZW50IHx8IFtdOyB2YXIgdGV4" +
    "dCA9ICcnOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCBibG9ja3MubGVuZ3RoOyBpKyspIHsgaWYg" +
    "KGJsb2Nrc1tpXS50eXBlID09PSAndGV4dCcpIHRleHQgKz0gYmxvY2tzW2ldLnRleHQ7IH0KICAg" +
    "IHZhciBjbGVhbmVkID0gdGV4dC5yZXBsYWNlKC9gYGBqc29uXG4/L2csICcnKS5yZXBsYWNlKC9g" +
    "YGBcbj8vZywgJycpLnRyaW0oKTsKICAgIHZhciBtYXRjaCA9IGNsZWFuZWQubWF0Y2goL1x7W1xz" +
    "XFNdKlx9Lyk7CiAgICBpZiAoIW1hdGNoKSB0aHJvdyBuZXcgRXJyb3IoJ05vIEpTT04gaW4gcmVz" +
    "cG9uc2UnKTsKICAgIHZhciByZXN1bHQgPSBKU09OLnBhcnNlKG1hdGNoWzBdKTsKICAgIGlmICgh" +
    "cmVzdWx0LnRyZW5kcyB8fCAhcmVzdWx0LnRyZW5kcy5sZW5ndGgpIHRocm93IG5ldyBFcnJvcign" +
    "Tm8gdHJlbmRzIGluIHJlc3BvbnNlJyk7CiAgICB0cmVuZHMgPSByZXN1bHQudHJlbmRzOyBzZXRQ" +
    "cm9ncmVzcygxMDApOyByZW5kZXJUcmVuZHMocmVnaW9uKTsKICAgIHZhciBub3cgPSBuZXcgRGF0" +
    "ZSgpLnRvTG9jYWxlVGltZVN0cmluZygnbmwtTkwnLCB7IGhvdXI6ICcyLWRpZ2l0JywgbWludXRl" +
    "OiAnMi1kaWdpdCcgfSk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQn" +
    "KS50ZXh0Q29udGVudCA9ICdMYXN0IHNjYW46ICcgKyBub3cgKyAnIFx1MjAxNCAnICsgaGVhZGxp" +
    "bmVzLmxlbmd0aCArICcgaGVhZGxpbmVzJzsKICB9KTsKfQoKZnVuY3Rpb24gc3JjQ29sb3Ioc3Jj" +
    "KSB7CiAgc3JjID0gKHNyYyB8fCAnJykudG9Mb3dlckNhc2UoKTsKICBpZiAoc3JjLmluZGV4T2Yo" +
    "J3JlZGRpdCcpID4gLTEpIHJldHVybiAnI0UyNEI0QSc7CiAgaWYgKHNyYy5pbmRleE9mKCdnb29n" +
    "bGUnKSA+IC0xKSByZXR1cm4gJyMxMGI5ODEnOwogIGlmIChzcmMgPT09ICdsaWJlbGxlJyB8fCBz" +
    "cmMgPT09ICdsaW5kYS5ubCcpIHJldHVybiAnI2Y1OWUwYic7CiAgcmV0dXJuICcjM2I4MmY2JzsK" +
    "fQoKZnVuY3Rpb24gcmVuZGVySGVhZGxpbmVzKGhlYWRsaW5lcykgewogIHZhciBlbCA9IGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdzaWduYWwtZmVlZCcpOwogIGlmICghaGVhZGxpbmVzLmxlbmd0" +
    "aCkgeyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPk5vIGhlYWRsaW5lcyBmZXRj" +
    "aGVkLjwvZGl2Pic7IHJldHVybjsgfQogIHZhciBieVNvdXJjZSA9IHt9OyB2YXIgc291cmNlT3Jk" +
    "ZXIgPSBbXTsKICBmb3IgKHZhciBpID0gMDsgaSA8IGhlYWRsaW5lcy5sZW5ndGg7IGkrKykgewog" +
    "ICAgdmFyIHNyYyA9IGhlYWRsaW5lc1tpXS5zb3VyY2U7CiAgICBpZiAoIWJ5U291cmNlW3NyY10p" +
    "IHsgYnlTb3VyY2Vbc3JjXSA9IFtdOyBzb3VyY2VPcmRlci5wdXNoKHNyYyk7IH0KICAgIGJ5U291" +
    "cmNlW3NyY10ucHVzaChoZWFkbGluZXNbaV0pOwogIH0KICB2YXIgaHRtbCA9ICcnOwogIGZvciAo" +
    "dmFyIHMgPSAwOyBzIDwgc291cmNlT3JkZXIubGVuZ3RoOyBzKyspIHsKICAgIHZhciBzcmMgPSBz" +
    "b3VyY2VPcmRlcltzXTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InNyYy1ncm91cCI+JyArIHNy" +
    "YyArICc8L2Rpdj4nOwogICAgdmFyIGl0ZW1zID0gYnlTb3VyY2Vbc3JjXS5zbGljZSgwLCAzKTsK" +
    "ICAgIGZvciAodmFyIGogPSAwOyBqIDwgaXRlbXMubGVuZ3RoOyBqKyspIHsKICAgICAgdmFyIGgg" +
    "PSBpdGVtc1tqXTsKICAgICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iaGVhZGxpbmUtaXRlbSI+PGRp" +
    "diBjbGFzcz0iaC1kb3QiIHN0eWxlPSJiYWNrZ3JvdW5kOicgKyBzcmNDb2xvcihzcmMpICsgJyI+" +
    "PC9kaXY+PGRpdj48ZGl2IGNsYXNzPSJoLXRpdGxlIj4nICsgaC50aXRsZSArICc8L2Rpdj4nOwog" +
    "ICAgICBpZiAoaC51cmwpIGh0bWwgKz0gJzxhIGNsYXNzPSJoLWxpbmsiIGhyZWY9IicgKyBoLnVy" +
    "bCArICciIHRhcmdldD0iX2JsYW5rIj5sZWVzIG1lZXI8L2E+JzsKICAgICAgaHRtbCArPSAnPC9k" +
    "aXY+PC9kaXY+JzsKICAgIH0KICB9CiAgZWwuaW5uZXJIVE1MID0gaHRtbDsKfQoKZnVuY3Rpb24g" +
    "cmVuZGVyVHJlbmRzKHJlZ2lvbikgewogIHZhciBlbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlk" +
    "KCd0cmVuZHMtbGlzdCcpOwogIGlmICghdHJlbmRzLmxlbmd0aCkgeyBlbC5pbm5lckhUTUwgPSAn" +
    "PGRpdiBjbGFzcz0iZW1wdHkiPk5vIHRyZW5kcyBkZXRlY3RlZC48L2Rpdj4nOyByZXR1cm47IH0K" +
    "ICB2YXIgaHRtbCA9ICcnOwogIGZvciAodmFyIGkgPSAwOyBpIDwgdHJlbmRzLmxlbmd0aDsgaSsr" +
    "KSB7CiAgICB2YXIgdCA9IHRyZW5kc1tpXTsgdmFyIGlzU2F2ZWQgPSBmYWxzZTsKICAgIGZvciAo" +
    "dmFyIHMgPSAwOyBzIDwgc2F2ZWQubGVuZ3RoOyBzKyspIHsgaWYgKHNhdmVkW3NdLm5hbWUgPT09" +
    "IHQubmFtZSkgeyBpc1NhdmVkID0gdHJ1ZTsgYnJlYWs7IH0gfQogICAgdmFyIG1jTWFwID0geyBy" +
    "aXNpbmc6ICdiLXJpc2luZycsIGVtZXJnaW5nOiAnYi1lbWVyZ2luZycsIGVzdGFibGlzaGVkOiAn" +
    "Yi1lc3RhYmxpc2hlZCcsIHNoaWZ0aW5nOiAnYi1zaGlmdGluZycgfTsKICAgIHZhciBtYyA9IG1j" +
    "TWFwW3QubW9tZW50dW1dIHx8ICdiLWVtZXJnaW5nJzsKICAgIHZhciBsaW5rcyA9IHQuc291cmNl" +
    "TGlua3MgfHwgW107IHZhciBsaW5rc0h0bWwgPSAnJzsKICAgIGZvciAodmFyIGwgPSAwOyBsIDwg" +
    "bGlua3MubGVuZ3RoOyBsKyspIHsKICAgICAgdmFyIGxrID0gbGlua3NbbF07CiAgICAgIHZhciBj" +
    "bHNNYXAgPSB7IHJlZGRpdDogJ3NsLXJlZGRpdCcsIG5ld3M6ICdzbC1uZXdzJywgdHJlbmRzOiAn" +
    "c2wtdHJlbmRzJywgbGlmZXN0eWxlOiAnc2wtbGlmZXN0eWxlJyB9OwogICAgICB2YXIgbGJsTWFw" +
    "ID0geyByZWRkaXQ6ICdSJywgbmV3czogJ04nLCB0cmVuZHM6ICdHJywgbGlmZXN0eWxlOiAnTCcg" +
    "fTsKICAgICAgbGlua3NIdG1sICs9ICc8YSBjbGFzcz0ic291cmNlLWxpbmsiIGhyZWY9IicgKyBs" +
    "ay51cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+PHNwYW4gY2xhc3M9InNsLWljb24gJyArIChjbHNN" +
    "YXBbbGsudHlwZV0gfHwgJ3NsLW5ld3MnKSArICciPicgKyAobGJsTWFwW2xrLnR5cGVdIHx8ICdO" +
    "JykgKyAnPC9zcGFuPjxkaXY+PGRpdiBjbGFzcz0ic2wtdGl0bGUiPicgKyBsay50aXRsZSArICc8" +
    "L2Rpdj48ZGl2IGNsYXNzPSJzbC1zb3VyY2UiPicgKyBsay5zb3VyY2UgKyAnPC9kaXY+PC9kaXY+" +
    "PC9hPic7CiAgICB9CiAgICB2YXIgY2hpcHMgPSAnJzsgdmFyIHNsID0gdC5zb3VyY2VMYWJlbHMg" +
    "fHwgW107CiAgICBmb3IgKHZhciBjID0gMDsgYyA8IHNsLmxlbmd0aDsgYysrKSBjaGlwcyArPSAn" +
    "PHNwYW4gY2xhc3M9ImNoaXAiPicgKyBzbFtjXSArICc8L3NwYW4+JzsKICAgIGh0bWwgKz0gJzxk" +
    "aXYgY2xhc3M9InRyZW5kLWl0ZW0iIGlkPSJ0Yy0nICsgaSArICciPic7CiAgICBodG1sICs9ICc8" +
    "ZGl2IGNsYXNzPSJ0cmVuZC1yb3cxIj48ZGl2IGNsYXNzPSJ0cmVuZC1uYW1lIj4nICsgdC5uYW1l" +
    "ICsgJzwvZGl2PjxzcGFuIGNsYXNzPSJiYWRnZSAnICsgbWMgKyAnIj4nICsgdC5tb21lbnR1bSAr" +
    "ICc8L3NwYW4+PC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5kLWRlc2MiPicg" +
    "KyB0LmRlc2MgKyAnPC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5kLXNpZ25h" +
    "bHMiPicgKyB0LnNpZ25hbHMgKyAnPC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRy" +
    "ZW5kLWFjdGlvbnMiPjxkaXYgY2xhc3M9ImNoaXBzIj4nICsgY2hpcHMgKyAnPC9kaXY+PGRpdiBz" +
    "dHlsZT0iZGlzcGxheTpmbGV4O2dhcDo1cHgiPic7CiAgICBpZiAobGlua3MubGVuZ3RoKSBodG1s" +
    "ICs9ICc8YnV0dG9uIGNsYXNzPSJhY3QtYnRuIiBvbmNsaWNrPSJ0b2dnbGVCb3goXCdzcmMtJyAr" +
    "IGkgKyAnXCcpIj5zb3VyY2VzPC9idXR0b24+JzsKICAgIGlmICh0LmZvcm1hdEhpbnQpIGh0bWwg" +
    "Kz0gJzxidXR0b24gY2xhc3M9ImFjdC1idG4iIG9uY2xpY2s9InRvZ2dsZUJveChcJ2hpbnQtJyAr" +
    "IGkgKyAnXCcpIj5mb3JtYXQ8L2J1dHRvbj4nOwogICAgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0i" +
    "YWN0LWJ0bicgKyAoaXNTYXZlZCA/ICcgc2F2ZWQnIDogJycpICsgJyIgaWQ9InNiLScgKyBpICsg" +
    "JyIgb25jbGljaz0iZG9TYXZlKCcgKyBpICsgJyxcJycgKyByZWdpb24gKyAnXCcpIj4nICsgKGlz" +
    "U2F2ZWQgPyAnc2F2ZWQnIDogJ3NhdmUnKSArICc8L2J1dHRvbj4nOwogICAgaHRtbCArPSAnPC9k" +
    "aXY+PC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImV4cGFuZC1ib3giIGlkPSJzcmMt" +
    "JyArIGkgKyAnIj4nICsgKGxpbmtzSHRtbCB8fCAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjExcHg7" +
    "Y29sb3I6dmFyKC0tbXV0ZWQpIj5ObyBzb3VyY2UgbGlua3MuPC9kaXY+JykgKyAnPC9kaXY+JzsK" +
    "ICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImhpbnQtYm94IiBpZD0iaGludC0nICsgaSArICciPicg" +
    "KyAodC5mb3JtYXRIaW50IHx8ICcnKSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPC9kaXY+JzsK" +
    "ICB9CiAgZWwuaW5uZXJIVE1MID0gaHRtbDsKfQoKZnVuY3Rpb24gdG9nZ2xlQm94KGlkKSB7CiAg" +
    "dmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoaWQpOwogIGlmIChlbCkgZWwuc3R5bGUu" +
    "ZGlzcGxheSA9IGVsLnN0eWxlLmRpc3BsYXkgPT09ICdibG9jaycgPyAnbm9uZScgOiAnYmxvY2sn" +
    "Owp9CgpmdW5jdGlvbiBkb1NhdmUoaSwgcmVnaW9uKSB7CiAgdmFyIHQgPSB0cmVuZHNbaV07CiAg" +
    "Zm9yICh2YXIgcyA9IDA7IHMgPCBzYXZlZC5sZW5ndGg7IHMrKykgeyBpZiAoc2F2ZWRbc10ubmFt" +
    "ZSA9PT0gdC5uYW1lKSByZXR1cm47IH0KICBzYXZlZC5wdXNoKHsgbmFtZTogdC5uYW1lLCBkZXNj" +
    "OiB0LmRlc2MsIHRhZzogJycgfSk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NiLScgKyBp" +
    "KS50ZXh0Q29udGVudCA9ICdzYXZlZCc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NiLScg" +
    "KyBpKS5jbGFzc0xpc3QuYWRkKCdzYXZlZCcpOwogIHJlbmRlclNhdmVkKCk7CiAgZmV0Y2goJy9h" +
    "cmNoaXZlL3NhdmUnLCB7IG1ldGhvZDogJ1BPU1QnLCBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUn" +
    "OiAnYXBwbGljYXRpb24vanNvbicgfSwgYm9keTogSlNPTi5zdHJpbmdpZnkoeyBuYW1lOiB0Lm5h" +
    "bWUsIGRlc2M6IHQuZGVzYywgbW9tZW50dW06IHQubW9tZW50dW0sIHNpZ25hbHM6IHQuc2lnbmFs" +
    "cywgc291cmNlX2xhYmVsczogdC5zb3VyY2VMYWJlbHMgfHwgW10sIHNvdXJjZV9saW5rczogdC5z" +
    "b3VyY2VMaW5rcyB8fCBbXSwgZm9ybWF0X2hpbnQ6IHQuZm9ybWF0SGludCwgdGFnOiAnJywgcmVn" +
    "aW9uOiByZWdpb24gfHwgJ25sJyB9KSB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7IGNvbnNvbGUu" +
    "ZXJyb3IoJ2FyY2hpdmUgc2F2ZSBmYWlsZWQnLCBlKTsgfSk7Cn0KCmZ1bmN0aW9uIHJlbmRlclNh" +
    "dmVkKCkgewogIHZhciBlbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzYXZlZC1saXN0Jyk7" +
    "CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2dlbi1yb3cnKS5zdHlsZS5kaXNwbGF5ID0gc2F2" +
    "ZWQubGVuZ3RoID8gJycgOiAnbm9uZSc7CiAgaWYgKCFzYXZlZC5sZW5ndGgpIHsgZWwuaW5uZXJI" +
    "VE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyBzYXZlZCB0cmVuZHMgeWV0LjwvZGl2Pic7IHJl" +
    "dHVybjsgfQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBzYXZlZC5sZW5n" +
    "dGg7IGkrKykgewogICAgdmFyIHQgPSBzYXZlZFtpXTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9" +
    "InNhdmVkLWl0ZW0iPjxkaXYgY2xhc3M9InNhdmVkLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+" +
    "JzsKICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6NnB4O2FsaWduLWl0" +
    "ZW1zOmNlbnRlciI+PGlucHV0IGNsYXNzPSJ0YWctaW5wdXQiIHBsYWNlaG9sZGVyPSJ0YWcuLi4i" +
    "IHZhbHVlPSInICsgdC50YWcgKyAnIiBvbmlucHV0PSJzYXZlZFsnICsgaSArICddLnRhZz10aGlz" +
    "LnZhbHVlIi8+JzsKICAgIGh0bWwgKz0gJzxzcGFuIHN0eWxlPSJjdXJzb3I6cG9pbnRlcjtmb250" +
    "LXNpemU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCkiIG9uY2xpY2s9InNhdmVkLnNwbGljZSgnICsg" +
    "aSArICcsMSk7cmVuZGVyU2F2ZWQoKSI+JiN4MjcxNTs8L3NwYW4+PC9kaXY+PC9kaXY+JzsKICB9" +
    "CiAgZWwuaW5uZXJIVE1MID0gaHRtbDsKfQoKZnVuY3Rpb24gZ2VuZXJhdGVGb3JtYXRzKCkgewog" +
    "IGlmICghc2F2ZWQubGVuZ3RoKSByZXR1cm47CiAgc3dpdGNoVGFiKCdmb3JtYXRzJyk7CiAgZG9j" +
    "dW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNs" +
    "YXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlJlYWRpbmcgeW91ciBjYXRh" +
    "bG9ndWUgJmFtcDsgZ2VuZXJhdGluZyBpZGVhcy4uLjwvZGl2Pic7CiAgZmV0Y2goJy9nZW5lcmF0" +
    "ZS1mb3JtYXRzJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50" +
    "LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsg" +
    "dHJlbmRzOiBzYXZlZCB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29u" +
    "KCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24ocmVzdWx0KSB7CiAgICBpZiAocmVzdWx0LmVycm9yKSB0" +
    "aHJvdyBuZXcgRXJyb3IocmVzdWx0LmVycm9yKTsKICAgIHZhciBmb3JtYXRzID0gcmVzdWx0LmZv" +
    "cm1hdHMgfHwgW107CiAgICBpZiAoIWZvcm1hdHMubGVuZ3RoKSB0aHJvdyBuZXcgRXJyb3IoJ05v" +
    "IGZvcm1hdHMgcmV0dXJuZWQnKTsKICAgIHZhciBodG1sID0gJyc7CiAgICBmb3IgKHZhciBpID0g" +
    "MDsgaSA8IGZvcm1hdHMubGVuZ3RoOyBpKyspIHsKICAgICAgdmFyIGYgPSBmb3JtYXRzW2ldOwog" +
    "ICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQtaXRlbSI+JzsKICAgICAgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0iZm9ybWF0LXRpdGxlIj4nICsgZi50aXRsZSArICc8L2Rpdj4nOwogICAgICBo" +
    "dG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQtbG9nbGluZSI+JyArIGYubG9nbGluZSArICc8L2Rp" +
    "dj4nOwogICAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjZweDtmbGV4" +
    "LXdyYXA6d3JhcDttYXJnaW4tdG9wOjVweCI+JzsKICAgICAgaHRtbCArPSAnPHNwYW4gY2xhc3M9" +
    "ImNoaXAiPicgKyBmLmNoYW5uZWwgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzxzcGFuIGNs" +
    "YXNzPSJjaGlwIj4nICsgZi50cmVuZEJhc2lzICsgJzwvc3Bhbj4nOwogICAgICBodG1sICs9ICc8" +
    "L2Rpdj4nOwogICAgICBpZiAoZi5ob29rKSBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQtaG9v" +
    "ayI+IicgKyBmLmhvb2sgKyAnIjwvZGl2Pic7CiAgICAgIGlmIChmLndoeU5ldykgaHRtbCArPSAn" +
    "PGRpdiBzdHlsZT0iZm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tZ3JlZW4pO21hcmdpbi10b3A6" +
    "NXB4O2ZvbnQtc3R5bGU6aXRhbGljIj4nICsgZi53aHlOZXcgKyAnPC9kaXY+JzsKICAgICAgaHRt" +
    "bCArPSAnPC9kaXY+JzsKICAgIH0KICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdmb3JtYXRz" +
    "LWxpc3QnKS5pbm5lckhUTUwgPSBodG1sOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAg" +
    "IHNob3dFcnIoJ0Zvcm1hdCBnZW5lcmF0aW9uIGZhaWxlZDogJyArIGUubWVzc2FnZSk7CiAgICBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZm9ybWF0cy1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYg" +
    "Y2xhc3M9ImVtcHR5Ij5GYWlsZWQuPC9kaXY+JzsKICB9KTsKfQoKZnVuY3Rpb24gbG9hZFJlc2Vh" +
    "cmNoKCkgewogIGZldGNoKCcvcmVzZWFyY2gnKS50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIu" +
    "anNvbigpOyB9KS50aGVuKGZ1bmN0aW9uKGQpIHsgcmVuZGVyUmVzZWFyY2goZC5pdGVtcyB8fCBb" +
    "XSk7IH0pCiAgLmNhdGNoKGZ1bmN0aW9uKCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVz" +
    "ZWFyY2gtZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Q291bGQgbm90IGxv" +
    "YWQgcmVzZWFyY2guPC9kaXY+JzsgfSk7Cn0KCmZ1bmN0aW9uIHJlbmRlclJlc2VhcmNoKGl0ZW1z" +
    "KSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Jlc2VhcmNoLWZlZWQnKTsK" +
    "ICBpZiAoIWl0ZW1zLmxlbmd0aCkgeyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHki" +
    "Pk5vIHJlc2VhcmNoIGl0ZW1zIGZvdW5kLjwvZGl2Pic7IHJldHVybjsgfQogIHZhciB0eXBlTWFw" +
    "ID0geyByZXNlYXJjaDogJ1Jlc2VhcmNoJywgY3VsdHVyZTogJ0N1bHR1cmUnLCB0cmVuZHM6ICdU" +
    "cmVuZHMnIH07IHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBpdGVtcy5sZW5n" +
    "dGg7IGkrKykgewogICAgdmFyIGl0ZW0gPSBpdGVtc1tpXTsKICAgIGh0bWwgKz0gJzxkaXYgY2xh" +
    "c3M9InJlc2VhcmNoLWl0ZW0iPjxkaXYgY2xhc3M9InJlc2VhcmNoLXRpdGxlIj48YSBocmVmPSIn" +
    "ICsgaXRlbS51cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+JyArIGl0ZW0udGl0bGUgKyAnPC9hPjwv" +
    "ZGl2Pic7CiAgICBpZiAoaXRlbS5kZXNjKSBodG1sICs9ICc8ZGl2IGNsYXNzPSJyZXNlYXJjaC1k" +
    "ZXNjIj4nICsgaXRlbS5kZXNjICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJy" +
    "ZXNlYXJjaC1tZXRhIj48c3BhbiBjbGFzcz0ici1zcmMiPicgKyBpdGVtLnNvdXJjZSArICc8L3Nw" +
    "YW4+PHNwYW4gY2xhc3M9InItdHlwZSI+JyArICh0eXBlTWFwW2l0ZW0udHlwZV0gfHwgaXRlbS50" +
    "eXBlKSArICc8L3NwYW4+PC9kaXY+PC9kaXY+JzsKICB9CiAgZWwuaW5uZXJIVE1MID0gaHRtbDsK" +
    "fQoKZnVuY3Rpb24gZG9BcmNoaXZlU2VhcmNoKCkgewogIHZhciBxdWVyeSA9IGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdhcmNoaXZlLXNlYXJjaC1pbnB1dCcpLnZhbHVlLnRyaW0oKTsKICBpZiAo" +
    "IXF1ZXJ5KSByZXR1cm47CiAgdmFyIHJlc3VsdHNFbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlk" +
    "KCdzZWFyY2gtcmVzdWx0cycpOwogIHJlc3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0i" +
    "Zm9udC1zaXplOjEycHg7Y29sb3I6dmFyKC0tbXV0ZWQpIj48c3BhbiBjbGFzcz0ibG9hZGVyIj48" +
    "L3NwYW4+U2VhcmNoaW5nIGFyY2hpdmUuLi48L2Rpdj4nOwoKICBmZXRjaCgnL2FyY2hpdmUvc2Vh" +
    "cmNoJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUn" +
    "OiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsgcXVlcnk6" +
    "IHF1ZXJ5IH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkK" +
    "ICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKGQu" +
    "ZXJyb3IpOwogICAgdmFyIHJlc3VsdHMgPSBkLnJlc3VsdHMgfHwgW107CiAgICBpZiAoIXJlc3Vs" +
    "dHMubGVuZ3RoKSB7CiAgICAgIHJlc3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0iZm9u" +
    "dC1zaXplOjEycHg7Y29sb3I6dmFyKC0tbXV0ZWQpO3BhZGRpbmc6OHB4IDAiPk5vIHJlbGV2YW50" +
    "IHRyZW5kcyBmb3VuZCBmb3IgIicgKyBxdWVyeSArICciLjwvZGl2Pic7CiAgICAgIHJldHVybjsK" +
    "ICAgIH0KICAgIHZhciBtY01hcCA9IHsgcmlzaW5nOiAnYi1yaXNpbmcnLCBlbWVyZ2luZzogJ2It" +
    "ZW1lcmdpbmcnLCBlc3RhYmxpc2hlZDogJ2ItZXN0YWJsaXNoZWQnLCBzaGlmdGluZzogJ2Itc2hp" +
    "ZnRpbmcnIH07CiAgICB2YXIgaHRtbCA9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTBweDtmb250" +
    "LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTts" +
    "ZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9tOjEwcHgiPicgKyByZXN1bHRzLmxlbmd0" +
    "aCArICcgcmVsZXZhbnQgdHJlbmRzIGZvdW5kPC9kaXY+JzsKICAgIGZvciAodmFyIGkgPSAwOyBp" +
    "IDwgcmVzdWx0cy5sZW5ndGg7IGkrKykgewogICAgICB2YXIgdCA9IHJlc3VsdHNbaV07CiAgICAg" +
    "IHZhciBtYyA9IG1jTWFwW3QubW9tZW50dW1dIHx8ICdiLWVtZXJnaW5nJzsKICAgICAgaHRtbCAr" +
    "PSAnPGRpdiBzdHlsZT0icGFkZGluZzoxMnB4IDA7Ym9yZGVyLWJvdHRvbToxcHggc29saWQgdmFy" +
    "KC0tYm9yZGVyKSI+JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2Fs" +
    "aWduLWl0ZW1zOmNlbnRlcjtnYXA6OHB4O21hcmdpbi1ib3R0b206NXB4Ij4nOwogICAgICBodG1s" +
    "ICs9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTNweDtmb250LXdlaWdodDo2MDA7Y29sb3I6I2Zm" +
    "ZiI+JyArIHQubmFtZSArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8c3BhbiBjbGFzcz0iYmFk" +
    "Z2UgJyArIG1jICsgJyI+JyArICh0Lm1vbWVudHVtIHx8ICcnKSArICc8L3NwYW4+JzsKICAgICAg" +
    "aHRtbCArPSAnPHNwYW4gc3R5bGU9ImZvbnQtc2l6ZToxMHB4O2NvbG9yOnZhcigtLW11dGVkKSI+" +
    "JyArIHQuc2F2ZWRfYXQuc2xpY2UoMCwxMCkgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzwv" +
    "ZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2NvbG9yOnZh" +
    "cigtLW11dGVkKTtsaW5lLWhlaWdodDoxLjU7bWFyZ2luLWJvdHRvbTo1cHgiPicgKyAodC5kZXNj" +
    "IHx8ICcnKSArICc8L2Rpdj4nOwogICAgICBpZiAodC5yZWxldmFuY2UpIGh0bWwgKz0gJzxkaXYg" +
    "c3R5bGU9ImZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLWFjY2VudDIpO2ZvbnQtc3R5bGU6aXRh" +
    "bGljIj4nICsgdC5yZWxldmFuY2UgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+JzsK" +
    "ICAgIH0KICAgIHJlc3VsdHNFbC5pbm5lckhUTUwgPSBodG1sOwogIH0pCiAgLmNhdGNoKGZ1bmN0" +
    "aW9uKGUpIHsKICAgIHJlc3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0iZm9udC1zaXpl" +
    "OjEycHg7Y29sb3I6I2ZjYTVhNSI+U2VhcmNoIGZhaWxlZDogJyArIGUubWVzc2FnZSArICc8L2Rp" +
    "dj4nOwogIH0pOwp9CgpmdW5jdGlvbiBsb2FkQXJjaGl2ZSgpIHsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnZGF0ZS1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5IiBzdHls" +
    "ZT0icGFkZGluZzoxcmVtIDAiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj48L2Rpdj4nOwog" +
    "IGZldGNoKCcvYXJjaGl2ZS9kYXRlcycpLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29u" +
    "KCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgaWYgKCFkLmRhdGVzIHx8ICFkLmRhdGVz" +
    "Lmxlbmd0aCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0JykuaW5uZXJIVE1M" +
    "ID0gJzxkaXYgY2xhc3M9ImVtcHR5IiBzdHlsZT0icGFkZGluZzoxcmVtIDA7Zm9udC1zaXplOjEx" +
    "cHgiPk5vIGFyY2hpdmVkIHRyZW5kcyB5ZXQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgICB2YXIgaHRt" +
    "bCA9ICcnOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCBkLmRhdGVzLmxlbmd0aDsgaSsrKSB7IGh0" +
    "bWwgKz0gJzxkaXYgY2xhc3M9ImRhdGUtaXRlbSIgb25jbGljaz0ibG9hZERhdGUoXCcnICsgZC5k" +
    "YXRlc1tpXS5kYXRlICsgJ1wnLHRoaXMpIj4nICsgZC5kYXRlc1tpXS5kYXRlICsgJzxzcGFuIGNs" +
    "YXNzPSJkYXRlLWNvdW50Ij4nICsgZC5kYXRlc1tpXS5jb3VudCArICc8L3NwYW4+PC9kaXY+Jzsg" +
    "fQogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RhdGUtbGlzdCcpLmlubmVySFRNTCA9IGh0" +
    "bWw7CiAgICB2YXIgZmlyc3QgPSBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKCcuZGF0ZS1pdGVtJyk7" +
    "IGlmIChmaXJzdCkgZmlyc3QuY2xpY2soKTsKICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7IGRv" +
    "Y3VtZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLWVycicpLmlubmVySFRNTCA9ICc8ZGl2IGNs" +
    "YXNzPSJlcnJib3giPkNvdWxkIG5vdCBsb2FkIGFyY2hpdmU6ICcgKyBlLm1lc3NhZ2UgKyAnPC9k" +
    "aXY+JzsgfSk7Cn0KCmZ1bmN0aW9uIGxvYWREYXRlKGRhdGUsIGVsKSB7CiAgdmFyIGl0ZW1zID0g" +
    "ZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgnLmRhdGUtaXRlbScpOyBmb3IgKHZhciBpID0gMDsg" +
    "aSA8IGl0ZW1zLmxlbmd0aDsgaSsrKSBpdGVtc1tpXS5jbGFzc0xpc3QucmVtb3ZlKCdhY3RpdmUn" +
    "KTsKICBlbC5jbGFzc0xpc3QuYWRkKCdhY3RpdmUnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJ" +
    "ZCgnYXJjaGl2ZS1oZWFkaW5nJykudGV4dENvbnRlbnQgPSAnU2F2ZWQgb24gJyArIGRhdGU7CiAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtY29udGVudCcpLmlubmVySFRNTCA9ICc8" +
    "ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPjwvZGl2Pic7CiAg" +
    "ZmV0Y2goJy9hcmNoaXZlL2J5LWRhdGU/ZGF0ZT0nICsgZW5jb2RlVVJJQ29tcG9uZW50KGRhdGUp" +
    "KS50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0aW9u" +
    "KGQpIHsKICAgIGlmICghZC50cmVuZHMgfHwgIWQudHJlbmRzLmxlbmd0aCkgeyBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9" +
    "ImVtcHR5Ij5ObyB0cmVuZHMgZm9yIHRoaXMgZGF0ZS48L2Rpdj4nOyByZXR1cm47IH0KICAgIHZh" +
    "ciBodG1sID0gJyc7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IGQudHJlbmRzLmxlbmd0aDsgaSsr" +
    "KSB7CiAgICAgIHZhciB0ID0gZC50cmVuZHNbaV07CiAgICAgIHZhciBtY01hcCA9IHsgcmlzaW5n" +
    "OiAnYi1yaXNpbmcnLCBlbWVyZ2luZzogJ2ItZW1lcmdpbmcnLCBlc3RhYmxpc2hlZDogJ2ItZXN0" +
    "YWJsaXNoZWQnLCBzaGlmdGluZzogJ2Itc2hpZnRpbmcnIH07CiAgICAgIHZhciBtYyA9IG1jTWFw" +
    "W3QubW9tZW50dW1dIHx8ICdiLWVtZXJnaW5nJzsgdmFyIGxpbmtzID0gW107CiAgICAgIHRyeSB7" +
    "IGxpbmtzID0gSlNPTi5wYXJzZSh0LnNvdXJjZV9saW5rcyB8fCAnW10nKTsgfSBjYXRjaChlKSB7" +
    "fQogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJhcmNoLWl0ZW0iPjxkaXYgc3R5bGU9ImRpc3Bs" +
    "YXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjhweDttYXJnaW4tYm90dG9tOjNweCI+PGRp" +
    "diBjbGFzcz0iYXJjaC1uYW1lIj4nICsgdC5uYW1lICsgJzwvZGl2PjxzcGFuIGNsYXNzPSJiYWRn" +
    "ZSAnICsgbWMgKyAnIj4nICsgKHQubW9tZW50dW0gfHwgJycpICsgJzwvc3Bhbj48L2Rpdj4nOwog" +
    "ICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJhcmNoLW1ldGEiPicgKyB0LnNhdmVkX2F0ICsgKHQu" +
    "cmVnaW9uID8gJyAmbWlkZG90OyAnICsgdC5yZWdpb24udG9VcHBlckNhc2UoKSA6ICcnKSArICh0" +
    "LnRhZyA/ICcgJm1pZGRvdDsgJyArIHQudGFnIDogJycpICsgJzwvZGl2Pic7CiAgICAgIGh0bWwg" +
    "Kz0gJzxkaXYgY2xhc3M9ImFyY2gtZGVzYyI+JyArICh0LmRlc2MgfHwgJycpICsgJzwvZGl2Pic7" +
    "CiAgICAgIGZvciAodmFyIGwgPSAwOyBsIDwgbGlua3MubGVuZ3RoOyBsKyspIHsgaHRtbCArPSAn" +
    "PGEgY2xhc3M9ImFyY2gtbGluayIgaHJlZj0iJyArIGxpbmtzW2xdLnVybCArICciIHRhcmdldD0i" +
    "X2JsYW5rIj4nICsgbGlua3NbbF0udGl0bGUgKyAnPC9hPic7IH0KICAgICAgaHRtbCArPSAnPC9k" +
    "aXY+JzsKICAgIH0KICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQn" +
    "KS5pbm5lckhUTUwgPSBodG1sOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKCkgeyBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9" +
    "ImVtcHR5Ij5Db3VsZCBub3QgbG9hZC48L2Rpdj4nOyB9KTsKfQo8L3NjcmlwdD4KPC9ib2R5Pgo8" +
    "L2h0bWw+Cg=="
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
            timeout=25
        )
        return jsonify(r.json())
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
