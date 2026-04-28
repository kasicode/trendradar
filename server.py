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
    "Mjc7IC0tY2FyZDogIzFhMjAzNTsgLS1jYXJkMjogIzFlMjY0MDsgLS1ib3JkZXI6IHJnYmEoMjU1" +
    "LDI1NSwyNTUsMC4wOCk7CiAgLS1ib3JkZXIyOiByZ2JhKDI1NSwyNTUsMjU1LDAuMTIpOyAtLXRl" +
    "eHQ6ICNlMmU4ZjA7IC0tbXV0ZWQ6ICM3MTgwOTY7CiAgLS1hY2NlbnQ6ICM3YzNhZWQ7IC0tYWNj" +
    "ZW50MjogI2E4NTVmNzsgLS1ncmVlbjogIzEwYjk4MTsgLS1hbWJlcjogI2Y1OWUwYjsKICAtLWJs" +
    "dWU6ICMzYjgyZjY7IC0tcmVkOiAjZWY0NDQ0OyAtLXBpbms6ICNlYzQ4OTk7IC0tZ2xvdzogcmdi" +
    "YSgxMjQsNTgsMjM3LDAuMTUpOwp9CmJvZHkgeyBmb250LWZhbWlseTogJ0ludGVyJywgLWFwcGxl" +
    "LXN5c3RlbSwgc2Fucy1zZXJpZjsgYmFja2dyb3VuZDogdmFyKC0tYmcpOyBjb2xvcjogdmFyKC0t" +
    "dGV4dCk7IG1pbi1oZWlnaHQ6IDEwMHZoOyBkaXNwbGF5OiBmbGV4OyB9Cgouc2lkZWJhciB7IHdp" +
    "ZHRoOiAyMjBweDsgbWluLWhlaWdodDogMTAwdmg7IGJhY2tncm91bmQ6IHZhcigtLXNpZGViYXIp" +
    "OyBib3JkZXItcmlnaHQ6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyBkaXNwbGF5OiBmbGV4OyBm" +
    "bGV4LWRpcmVjdGlvbjogY29sdW1uOyBmbGV4LXNocmluazogMDsgcG9zaXRpb246IGZpeGVkOyB0" +
    "b3A6IDA7IGxlZnQ6IDA7IGJvdHRvbTogMDsgei1pbmRleDogMTAwOyB9Ci5zaWRlYmFyLWxvZ28g" +
    "eyBwYWRkaW5nOiAyMnB4IDE4cHggMThweDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigt" +
    "LWJvcmRlcik7IH0KLnNpZGViYXItbG9nbyAubmFtZSB7IGZvbnQtc2l6ZTogMTVweDsgZm9udC13" +
    "ZWlnaHQ6IDcwMDsgY29sb3I6ICNmZmY7IGxldHRlci1zcGFjaW5nOiAtMC4zcHg7IH0KLnNpZGVi" +
    "YXItbG9nbyAudGFnbGluZSB7IGZvbnQtc2l6ZTogOXB4OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBt" +
    "YXJnaW4tdG9wOiAzcHg7IGxldHRlci1zcGFjaW5nOiAwLjVweDsgdGV4dC10cmFuc2Zvcm06IHVw" +
    "cGVyY2FzZTsgfQouc2lkZWJhci1zZWN0aW9uIHsgcGFkZGluZzogMTZweCAxMHB4IDhweDsgfQou" +
    "c2lkZWJhci1zZWN0aW9uLWxhYmVsIHsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiA2MDA7" +
    "IGNvbG9yOiB2YXIoLS1tdXRlZCk7IHRleHQtdHJhbnNmb3JtOiB1cHBlcmNhc2U7IGxldHRlci1z" +
    "cGFjaW5nOiAxcHg7IHBhZGRpbmc6IDAgOHB4OyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLm5hdi1p" +
    "dGVtIHsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGNlbnRlcjsgZ2FwOiAxMHB4OyBwYWRk" +
    "aW5nOiA5cHggMTBweDsgYm9yZGVyLXJhZGl1czogOHB4OyBmb250LXNpemU6IDEzcHg7IGZvbnQt" +
    "d2VpZ2h0OiA1MDA7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGN1cnNvcjogcG9pbnRlcjsgdHJhbnNp" +
    "dGlvbjogYWxsIDAuMTVzOyBtYXJnaW4tYm90dG9tOiAycHg7IH0KLm5hdi1pdGVtOmhvdmVyIHsg" +
    "YmFja2dyb3VuZDogcmdiYSgyNTUsMjU1LDI1NSwwLjA1KTsgY29sb3I6IHZhcigtLXRleHQpOyB9" +
    "Ci5uYXYtaXRlbS5hY3RpdmUgeyBiYWNrZ3JvdW5kOiB2YXIoLS1nbG93KTsgY29sb3I6ICNmZmY7" +
    "IH0KLm5hdi1kb3QgeyB3aWR0aDogN3B4OyBoZWlnaHQ6IDdweDsgYm9yZGVyLXJhZGl1czogNTAl" +
    "OyBiYWNrZ3JvdW5kOiByZ2JhKDI1NSwyNTUsMjU1LDAuMTUpOyBmbGV4LXNocmluazogMDsgfQou" +
    "bmF2LWl0ZW0uYWN0aXZlIC5uYXYtZG90IHsgYmFja2dyb3VuZDogdmFyKC0tYWNjZW50Mik7IGJv" +
    "eC1zaGFkb3c6IDAgMCA4cHggdmFyKC0tYWNjZW50Mik7IH0KLnNpZGViYXItc291cmNlcyB7IHBh" +
    "ZGRpbmc6IDEycHg7IGJvcmRlci10b3A6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyBtYXJnaW4t" +
    "dG9wOiBhdXRvOyB9Ci5zaWRlYmFyLXNvdXJjZXMtbGFiZWwgeyBmb250LXNpemU6IDlweDsgZm9u" +
    "dC13ZWlnaHQ6IDYwMDsgY29sb3I6IHZhcigtLW11dGVkKTsgdGV4dC10cmFuc2Zvcm06IHVwcGVy" +
    "Y2FzZTsgbGV0dGVyLXNwYWNpbmc6IDFweDsgbWFyZ2luLWJvdHRvbTogOHB4OyB9Ci5zcmMtcGls" +
    "bCB7IGRpc3BsYXk6IGlubGluZS1mbGV4OyBhbGlnbi1pdGVtczogY2VudGVyOyBmb250LXNpemU6" +
    "IDEwcHg7IHBhZGRpbmc6IDNweCA4cHg7IGJvcmRlci1yYWRpdXM6IDIwcHg7IGJvcmRlcjogMXB4" +
    "IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBjdXJzb3I6IGRlZmF1" +
    "bHQ7IG1hcmdpbjogMnB4OyB9Ci5zcmMtcGlsbC5vbiB7IGJvcmRlci1jb2xvcjogcmdiYSgxNiwx" +
    "ODUsMTI5LDAuNCk7IGNvbG9yOiB2YXIoLS1ncmVlbik7IGJhY2tncm91bmQ6IHJnYmEoMTYsMTg1" +
    "LDEyOSwwLjA4KTsgfQoKLm1haW4geyBtYXJnaW4tbGVmdDogMjIwcHg7IGZsZXg6IDE7IG1pbi1o" +
    "ZWlnaHQ6IDEwMHZoOyBkaXNwbGF5OiBmbGV4OyBmbGV4LWRpcmVjdGlvbjogY29sdW1uOyB9Ci50" +
    "b3BiYXIgeyBoZWlnaHQ6IDU4cHg7IGJhY2tncm91bmQ6IHZhcigtLXNpZGViYXIpOyBib3JkZXIt" +
    "Ym90dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgZGlzcGxheTogZmxleDsgYWxpZ24taXRl" +
    "bXM6IGNlbnRlcjsganVzdGlmeS1jb250ZW50OiBzcGFjZS1iZXR3ZWVuOyBwYWRkaW5nOiAwIDI0" +
    "cHg7IHBvc2l0aW9uOiBzdGlja3k7IHRvcDogMDsgei1pbmRleDogNTA7IH0KLnRvcGJhci10aXRs" +
    "ZSB7IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6IDYwMDsgY29sb3I6ICNmZmY7IH0KLnRv" +
    "cGJhci1yaWdodCB7IGRpc3BsYXk6IGZsZXg7IGdhcDogOHB4OyBhbGlnbi1pdGVtczogY2VudGVy" +
    "OyB9Ci5zZWwgeyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDZweCAxMHB4OyBib3JkZXItcmFk" +
    "aXVzOiA4cHg7IGJvcmRlcjogMXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBiYWNrZ3JvdW5kOiB2" +
    "YXIoLS1jYXJkKTsgY29sb3I6IHZhcigtLXRleHQpOyBjdXJzb3I6IHBvaW50ZXI7IG91dGxpbmU6" +
    "IG5vbmU7IH0KLnNjYW4tYnRuIHsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogNjAwOyBw" +
    "YWRkaW5nOiA4cHggMjBweDsgYm9yZGVyLXJhZGl1czogOHB4OyBib3JkZXI6IG5vbmU7IGJhY2tn" +
    "cm91bmQ6IGxpbmVhci1ncmFkaWVudCgxMzVkZWcsIHZhcigtLWFjY2VudCksIHZhcigtLWFjY2Vu" +
    "dDIpKTsgY29sb3I6ICNmZmY7IGN1cnNvcjogcG9pbnRlcjsgYm94LXNoYWRvdzogMCAwIDIwcHgg" +
    "cmdiYSgxMjQsNTgsMjM3LDAuMzUpOyB0cmFuc2l0aW9uOiBhbGwgMC4yczsgfQouc2Nhbi1idG46" +
    "aG92ZXIgeyBib3gtc2hhZG93OiAwIDAgMzBweCByZ2JhKDEyNCw1OCwyMzcsMC41NSk7IHRyYW5z" +
    "Zm9ybTogdHJhbnNsYXRlWSgtMXB4KTsgfQouc2Nhbi1idG46ZGlzYWJsZWQgeyBvcGFjaXR5OiAw" +
    "LjU7IGN1cnNvcjogbm90LWFsbG93ZWQ7IHRyYW5zZm9ybTogbm9uZTsgfQoKLmNvbnRlbnQgeyBw" +
    "YWRkaW5nOiAyMHB4IDI0cHg7IGZsZXg6IDE7IH0KLnN0YXR1cy1iYXIgeyBkaXNwbGF5OiBmbGV4" +
    "OyBhbGlnbi1pdGVtczogY2VudGVyOyBnYXA6IDEycHg7IGZvbnQtc2l6ZTogMTFweDsgY29sb3I6" +
    "IHZhcigtLW11dGVkKTsgbWFyZ2luLWJvdHRvbTogMTRweDsgZmxleC13cmFwOiB3cmFwOyB9Ci5z" +
    "dGF0dXMtZG90IHsgd2lkdGg6IDZweDsgaGVpZ2h0OiA2cHg7IGJvcmRlci1yYWRpdXM6IDUwJTsg" +
    "YmFja2dyb3VuZDogdmFyKC0tZ3JlZW4pOyBib3gtc2hhZG93OiAwIDAgNnB4IHZhcigtLWdyZWVu" +
    "KTsgZmxleC1zaHJpbms6IDA7IH0KLnN0YXR1cy1kb3Quc2Nhbm5pbmcgeyBiYWNrZ3JvdW5kOiB2" +
    "YXIoLS1hbWJlcik7IGJveC1zaGFkb3c6IDAgMCA2cHggdmFyKC0tYW1iZXIpOyBhbmltYXRpb246" +
    "IGJsaW5rIDFzIGluZmluaXRlOyB9CkBrZXlmcmFtZXMgYmxpbmsgeyAwJSwxMDAle29wYWNpdHk6" +
    "MX01MCV7b3BhY2l0eTowLjN9IH0KLnByb2dyZXNzLWJhciB7IGhlaWdodDogMnB4OyBiYWNrZ3Jv" +
    "dW5kOiB2YXIoLS1ib3JkZXIpOyBib3JkZXItcmFkaXVzOiAycHg7IG1hcmdpbi1ib3R0b206IDE4" +
    "cHg7IG92ZXJmbG93OiBoaWRkZW47IH0KLnByb2dyZXNzLWZpbGwgeyBoZWlnaHQ6IDJweDsgYmFj" +
    "a2dyb3VuZDogbGluZWFyLWdyYWRpZW50KDkwZGVnLCB2YXIoLS1hY2NlbnQpLCB2YXIoLS1hY2Nl" +
    "bnQyKSk7IHdpZHRoOiAwJTsgdHJhbnNpdGlvbjogd2lkdGggMC40czsgYm9yZGVyLXJhZGl1czog" +
    "MnB4OyB9CgouZ3JpZC0zIHsgZGlzcGxheTogZ3JpZDsgZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOiAx" +
    "ZnIgMWZyIDFmcjsgZ2FwOiAxNnB4OyBhbGlnbi1pdGVtczogc3RhcnQ7IH0KQG1lZGlhIChtYXgt" +
    "d2lkdGg6IDExMDBweCkgeyAuZ3JpZC0zIHsgZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOiAxZnIgMWZy" +
    "OyB9IH0KQG1lZGlhIChtYXgtd2lkdGg6IDcwMHB4KSB7IC5ncmlkLTMgeyBncmlkLXRlbXBsYXRl" +
    "LWNvbHVtbnM6IDFmcjsgfSAuc2lkZWJhciB7IGRpc3BsYXk6IG5vbmU7IH0gLm1haW4geyBtYXJn" +
    "aW4tbGVmdDogMDsgfSB9CgouY2FyZCB7IGJhY2tncm91bmQ6IHZhcigtLWNhcmQpOyBib3JkZXI6" +
    "IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyBib3JkZXItcmFkaXVzOiAxMnB4OyBvdmVyZmxvdzog" +
    "aGlkZGVuOyB9Ci5jYXJkLWhlYWRlciB7IGRpc3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50" +
    "ZXI7IGp1c3RpZnktY29udGVudDogc3BhY2UtYmV0d2VlbjsgcGFkZGluZzogMTJweCAxNnB4OyBi" +
    "b3JkZXItYm90dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgfQouY2FyZC10aXRsZSB7IGZv" +
    "bnQtc2l6ZTogMTBweDsgZm9udC13ZWlnaHQ6IDYwMDsgY29sb3I6IHZhcigtLW11dGVkKTsgdGV4" +
    "dC10cmFuc2Zvcm06IHVwcGVyY2FzZTsgbGV0dGVyLXNwYWNpbmc6IDAuOHB4OyB9Ci5jYXJkLWJv" +
    "ZHkgeyBwYWRkaW5nOiAwIDE2cHggNHB4OyB9CgoudGFicyB7IGRpc3BsYXk6IGZsZXg7IGJvcmRl" +
    "ci1ib3R0b206IG5vbmU7IH0KLnRhYi1idG4geyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0" +
    "OiA1MDA7IHBhZGRpbmc6IDAgMTRweCAwIDA7IGN1cnNvcjogcG9pbnRlcjsgY29sb3I6IHZhcigt" +
    "LW11dGVkKTsgYm9yZGVyOiBub25lOyBiYWNrZ3JvdW5kOiBub25lOyBib3JkZXItYm90dG9tOiAy" +
    "cHggc29saWQgdHJhbnNwYXJlbnQ7IHBhZGRpbmctYm90dG9tOiAxMnB4OyBtYXJnaW4tYm90dG9t" +
    "OiAtMXB4OyB0cmFuc2l0aW9uOiBhbGwgMC4xNXM7IH0KLnRhYi1idG4uYWN0aXZlIHsgY29sb3I6" +
    "ICNmZmY7IGJvcmRlci1ib3R0b20tY29sb3I6IHZhcigtLWFjY2VudDIpOyB9Ci50YWItYnRuOmhv" +
    "dmVyOm5vdCguYWN0aXZlKSB7IGNvbG9yOiB2YXIoLS10ZXh0KTsgfQoKLnRyZW5kLWl0ZW0geyBw" +
    "YWRkaW5nOiAxNHB4IDA7IGJvcmRlci1ib3R0b206IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyB9" +
    "Ci50cmVuZC1pdGVtOmxhc3QtY2hpbGQgeyBib3JkZXItYm90dG9tOiBub25lOyB9Ci50cmVuZC1y" +
    "b3cxIHsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGZsZXgtc3RhcnQ7IGp1c3RpZnktY29u" +
    "dGVudDogc3BhY2UtYmV0d2VlbjsgZ2FwOiAxMHB4OyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLnRy" +
    "ZW5kLW5hbWUgeyBmb250LXNpemU6IDE0cHg7IGZvbnQtd2VpZ2h0OiA2MDA7IGNvbG9yOiAjZmZm" +
    "OyBsaW5lLWhlaWdodDogMS4zOyB9Ci5iYWRnZSB7IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdo" +
    "dDogNjAwOyBwYWRkaW5nOiAzcHggOHB4OyBib3JkZXItcmFkaXVzOiAyMHB4OyB3aGl0ZS1zcGFj" +
    "ZTogbm93cmFwOyBmbGV4LXNocmluazogMDsgdGV4dC10cmFuc2Zvcm06IHVwcGVyY2FzZTsgbGV0" +
    "dGVyLXNwYWNpbmc6IDAuNHB4OyB9Ci5iLXJpc2luZyB7IGJhY2tncm91bmQ6IHJnYmEoMTYsMTg1" +
    "LDEyOSwwLjEyKTsgY29sb3I6IHZhcigtLWdyZWVuKTsgYm9yZGVyOiAxcHggc29saWQgcmdiYSgx" +
    "NiwxODUsMTI5LDAuMjUpOyB9Ci5iLWVtZXJnaW5nIHsgYmFja2dyb3VuZDogcmdiYSgyNDUsMTU4" +
    "LDExLDAuMTIpOyBjb2xvcjogdmFyKC0tYW1iZXIpOyBib3JkZXI6IDFweCBzb2xpZCByZ2JhKDI0" +
    "NSwxNTgsMTEsMC4yNSk7IH0KLmItZXN0YWJsaXNoZWQgeyBiYWNrZ3JvdW5kOiByZ2JhKDU5LDEz" +
    "MCwyNDYsMC4xMik7IGNvbG9yOiB2YXIoLS1ibHVlKTsgYm9yZGVyOiAxcHggc29saWQgcmdiYSg1" +
    "OSwxMzAsMjQ2LDAuMjUpOyB9Ci5iLXNoaWZ0aW5nIHsgYmFja2dyb3VuZDogcmdiYSgyMzYsNzIs" +
    "MTUzLDAuMTIpOyBjb2xvcjogdmFyKC0tcGluayk7IGJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMjM2" +
    "LDcyLDE1MywwLjI1KTsgfQoudHJlbmQtZGVzYyB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6IHZh" +
    "cigtLW11dGVkKTsgbGluZS1oZWlnaHQ6IDEuNjsgbWFyZ2luLWJvdHRvbTogNnB4OyB9Ci50cmVu" +
    "ZC1zaWduYWxzIHsgZm9udC1zaXplOiAxMXB4OyBjb2xvcjogcmdiYSgyNTUsMjU1LDI1NSwwLjMp" +
    "OyBsaW5lLWhlaWdodDogMS41OyBtYXJnaW4tYm90dG9tOiA4cHg7IH0KLnRyZW5kLWFjdGlvbnMg" +
    "eyBkaXNwbGF5OiBmbGV4OyBnYXA6IDZweDsgYWxpZ24taXRlbXM6IGNlbnRlcjsganVzdGlmeS1j" +
    "b250ZW50OiBzcGFjZS1iZXR3ZWVuOyBmbGV4LXdyYXA6IHdyYXA7IH0KLmNoaXBzIHsgZGlzcGxh" +
    "eTogZmxleDsgZ2FwOiA0cHg7IGZsZXgtd3JhcDogd3JhcDsgfQouY2hpcCB7IGZvbnQtc2l6ZTog" +
    "OXB4OyBwYWRkaW5nOiAycHggN3B4OyBib3JkZXItcmFkaXVzOiAyMHB4OyBiYWNrZ3JvdW5kOiBy" +
    "Z2JhKDI1NSwyNTUsMjU1LDAuMDUpOyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBib3JkZXI6IDFweCBz" +
    "b2xpZCB2YXIoLS1ib3JkZXIpOyB9Ci5hY3QtYnRuIHsgZm9udC1zaXplOiAxMHB4OyBwYWRkaW5n" +
    "OiA0cHggMTBweDsgYm9yZGVyLXJhZGl1czogNnB4OyBib3JkZXI6IDFweCBzb2xpZCB2YXIoLS1i" +
    "b3JkZXIyKTsgYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGN1" +
    "cnNvcjogcG9pbnRlcjsgdHJhbnNpdGlvbjogYWxsIDAuMTVzOyB9Ci5hY3QtYnRuOmhvdmVyIHsg" +
    "YmFja2dyb3VuZDogcmdiYSgyNTUsMjU1LDI1NSwwLjA2KTsgY29sb3I6IHZhcigtLXRleHQpOyB9" +
    "Ci5hY3QtYnRuLnNhdmVkIHsgYm9yZGVyLWNvbG9yOiByZ2JhKDE2LDE4NSwxMjksMC40KTsgY29s" +
    "b3I6IHZhcigtLWdyZWVuKTsgYmFja2dyb3VuZDogcmdiYSgxNiwxODUsMTI5LDAuMSk7IH0KLmV4" +
    "cGFuZC1ib3ggeyBkaXNwbGF5OiBub25lOyBtYXJnaW4tdG9wOiAxMHB4OyBib3JkZXItdG9wOiAx" +
    "cHggc29saWQgdmFyKC0tYm9yZGVyKTsgcGFkZGluZy10b3A6IDEwcHg7IH0KLnNvdXJjZS1saW5r" +
    "IHsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGZsZXgtc3RhcnQ7IGdhcDogOHB4OyBwYWRk" +
    "aW5nOiA2cHggMDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IHRleHQt" +
    "ZGVjb3JhdGlvbjogbm9uZTsgY29sb3I6IGluaGVyaXQ7IH0KLnNvdXJjZS1saW5rOmxhc3QtY2hp" +
    "bGQgeyBib3JkZXItYm90dG9tOiBub25lOyB9Ci5zb3VyY2UtbGluazpob3ZlciAuc2wtdGl0bGUg" +
    "eyBjb2xvcjogdmFyKC0tYWNjZW50Mik7IH0KLnNsLWljb24geyBmb250LXNpemU6IDhweDsgZm9u" +
    "dC13ZWlnaHQ6IDcwMDsgY29sb3I6ICNmZmY7IGJvcmRlci1yYWRpdXM6IDRweDsgcGFkZGluZzog" +
    "MnB4IDVweDsgZmxleC1zaHJpbms6IDA7IG1hcmdpbi10b3A6IDJweDsgfQouc2wtcmVkZGl0IHsg" +
    "YmFja2dyb3VuZDogI0UyNEI0QTsgfSAuc2wtbmV3cyB7IGJhY2tncm91bmQ6IHZhcigtLWJsdWUp" +
    "OyB9IC5zbC10cmVuZHMgeyBiYWNrZ3JvdW5kOiB2YXIoLS1ncmVlbik7IH0gLnNsLWxpZmVzdHls" +
    "ZSB7IGJhY2tncm91bmQ6IHZhcigtLWFtYmVyKTsgfQouc2wtdGl0bGUgeyBmb250LXNpemU6IDEx" +
    "cHg7IGNvbG9yOiB2YXIoLS10ZXh0KTsgbGluZS1oZWlnaHQ6IDEuNDsgfQouc2wtc291cmNlIHsg" +
    "Zm9udC1zaXplOiAxMHB4OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBtYXJnaW4tdG9wOiAxcHg7IH0K" +
    "LmhpbnQtYm94IHsgZGlzcGxheTogbm9uZTsgbWFyZ2luLXRvcDogMTBweDsgYm9yZGVyLXRvcDog" +
    "MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IHBhZGRpbmctdG9wOiAxMHB4OyBmb250LXNpemU6IDEy" +
    "cHg7IGZvbnQtc3R5bGU6IGl0YWxpYzsgY29sb3I6IHZhcigtLWFjY2VudDIpOyBsaW5lLWhlaWdo" +
    "dDogMS41OyB9CgouaGVhZGxpbmUtaXRlbSB7IGRpc3BsYXk6IGZsZXg7IGdhcDogOHB4OyBwYWRk" +
    "aW5nOiA3cHggMDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLmhl" +
    "YWRsaW5lLWl0ZW06bGFzdC1jaGlsZCB7IGJvcmRlci1ib3R0b206IG5vbmU7IH0KLmgtZG90IHsg" +
    "d2lkdGg6IDVweDsgaGVpZ2h0OiA1cHg7IGJvcmRlci1yYWRpdXM6IDUwJTsgbWFyZ2luLXRvcDog" +
    "NnB4OyBmbGV4LXNocmluazogMDsgfQouaC10aXRsZSB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6" +
    "IHZhcigtLXRleHQpOyBsaW5lLWhlaWdodDogMS40OyB9Ci5oLWxpbmsgeyBmb250LXNpemU6IDEw" +
    "cHg7IGNvbG9yOiB2YXIoLS1hY2NlbnQyKTsgdGV4dC1kZWNvcmF0aW9uOiBub25lOyBkaXNwbGF5" +
    "OiBibG9jazsgbWFyZ2luLXRvcDogMnB4OyB9Ci5oLWxpbms6aG92ZXIgeyB0ZXh0LWRlY29yYXRp" +
    "b246IHVuZGVybGluZTsgfQouc3JjLWdyb3VwIHsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0" +
    "OiA2MDA7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IHRleHQtdHJhbnNmb3JtOiB1cHBlcmNhc2U7IGxl" +
    "dHRlci1zcGFjaW5nOiAwLjhweDsgcGFkZGluZzogOHB4IDAgNHB4OyB9CgoucmVzZWFyY2gtaXRl" +
    "bSB7IHBhZGRpbmc6IDEwcHggMDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRl" +
    "cik7IH0KLnJlc2VhcmNoLWl0ZW06bGFzdC1jaGlsZCB7IGJvcmRlci1ib3R0b206IG5vbmU7IH0K" +
    "LnJlc2VhcmNoLXRpdGxlIHsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogNTAwOyBjb2xv" +
    "cjogdmFyKC0tdGV4dCk7IGxpbmUtaGVpZ2h0OiAxLjQ7IG1hcmdpbi1ib3R0b206IDRweDsgfQou" +
    "cmVzZWFyY2gtdGl0bGUgYSB7IGNvbG9yOiBpbmhlcml0OyB0ZXh0LWRlY29yYXRpb246IG5vbmU7" +
    "IH0KLnJlc2VhcmNoLXRpdGxlIGE6aG92ZXIgeyBjb2xvcjogdmFyKC0tYWNjZW50Mik7IH0KLnJl" +
    "c2VhcmNoLWRlc2MgeyBmb250LXNpemU6IDExcHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGxpbmUt" +
    "aGVpZ2h0OiAxLjU7IG1hcmdpbi1ib3R0b206IDVweDsgfQoucmVzZWFyY2gtbWV0YSB7IGRpc3Bs" +
    "YXk6IGZsZXg7IGdhcDogNnB4OyB9Ci5yLXNyYyB7IGZvbnQtc2l6ZTogOXB4OyBwYWRkaW5nOiAy" +
    "cHggN3B4OyBib3JkZXItcmFkaXVzOiAyMHB4OyBiYWNrZ3JvdW5kOiByZ2JhKDE2LDE4NSwxMjks" +
    "MC4wOCk7IGNvbG9yOiB2YXIoLS1ncmVlbik7IGJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMTYsMTg1" +
    "LDEyOSwwLjIpOyB9Ci5yLXR5cGUgeyBmb250LXNpemU6IDlweDsgcGFkZGluZzogMnB4IDdweDsg" +
    "Ym9yZGVyLXJhZGl1czogMjBweDsgYmFja2dyb3VuZDogcmdiYSgyNTUsMjU1LDI1NSwwLjA0KTsg" +
    "Y29sb3I6IHZhcigtLW11dGVkKTsgfQoKLnNhdmVkLWl0ZW0geyBkaXNwbGF5OiBmbGV4OyBhbGln" +
    "bi1pdGVtczogY2VudGVyOyBqdXN0aWZ5LWNvbnRlbnQ6IHNwYWNlLWJldHdlZW47IHBhZGRpbmc6" +
    "IDdweCAwOyBib3JkZXItYm90dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgfQouc2F2ZWQt" +
    "aXRlbTpsYXN0LWNoaWxkIHsgYm9yZGVyLWJvdHRvbTogbm9uZTsgfQouc2F2ZWQtbmFtZSB7IGZv" +
    "bnQtc2l6ZTogMTJweDsgY29sb3I6IHZhcigtLXRleHQpOyBmbGV4OiAxOyB9Ci50YWctaW5wdXQg" +
    "eyBmb250LXNpemU6IDEwcHg7IGJvcmRlcjogMXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBib3Jk" +
    "ZXItcmFkaXVzOiA2cHg7IHBhZGRpbmc6IDNweCA4cHg7IGJhY2tncm91bmQ6IHJnYmEoMjU1LDI1" +
    "NSwyNTUsMC4wNCk7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IHdpZHRoOiA3MHB4OyBvdXRsaW5lOiBu" +
    "b25lOyB9Ci50YWctaW5wdXQ6OnBsYWNlaG9sZGVyIHsgY29sb3I6IHJnYmEoMjU1LDI1NSwyNTUs" +
    "MC4xNSk7IH0KLmdlbi1idG4geyB3aWR0aDogMTAwJTsgbWFyZ2luLXRvcDogMTBweDsgcGFkZGlu" +
    "ZzogOXB4OyBib3JkZXItcmFkaXVzOiA4cHg7IGJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMTY4LDg1" +
    "LDI0NywwLjMpOyBiYWNrZ3JvdW5kOiByZ2JhKDEyNCw1OCwyMzcsMC4xKTsgY29sb3I6IHZhcigt" +
    "LWFjY2VudDIpOyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiA1MDA7IGN1cnNvcjogcG9p" +
    "bnRlcjsgdHJhbnNpdGlvbjogYWxsIDAuMTVzOyB9Ci5nZW4tYnRuOmhvdmVyIHsgYmFja2dyb3Vu" +
    "ZDogcmdiYSgxMjQsNTgsMjM3LDAuMik7IH0KCi5mb3JtYXQtaXRlbSB7IHBhZGRpbmc6IDEycHgg" +
    "MDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLmZvcm1hdC1pdGVt" +
    "Omxhc3QtY2hpbGQgeyBib3JkZXItYm90dG9tOiBub25lOyB9Ci5mb3JtYXQtdGl0bGUgeyBmb250" +
    "LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiA2MDA7IGNvbG9yOiAjZmZmOyBtYXJnaW4tYm90dG9t" +
    "OiA0cHg7IH0KLmZvcm1hdC1sb2dsaW5lIHsgZm9udC1zaXplOiAxMnB4OyBjb2xvcjogdmFyKC0t" +
    "bXV0ZWQpOyBsaW5lLWhlaWdodDogMS41OyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLmZvcm1hdC1o" +
    "b29rIHsgZm9udC1zaXplOiAxMXB4OyBjb2xvcjogcmdiYSgxNjgsODUsMjQ3LDAuNzUpOyBmb250" +
    "LXN0eWxlOiBpdGFsaWM7IG1hcmdpbi10b3A6IDVweDsgfQouZGV2LWJ0biB7IGRpc3BsYXk6IGlu" +
    "bGluZS1ibG9jazsgZm9udC1zaXplOiAxMHB4OyBwYWRkaW5nOiA0cHggMTBweDsgYm9yZGVyLXJh" +
    "ZGl1czogNnB4OyBib3JkZXI6IDFweCBzb2xpZCByZ2JhKDE2LDE4NSwxMjksMC40KTsgYmFja2dy" +
    "b3VuZDogcmdiYSgxNiwxODUsMTI5LDAuMDgpOyBjb2xvcjogdmFyKC0tZ3JlZW4pOyBjdXJzb3I6" +
    "IHBvaW50ZXI7IG1hcmdpbi10b3A6IDhweDsgdHJhbnNpdGlvbjogYWxsIDAuMTVzOyB9Ci5kZXYt" +
    "YnRuOmhvdmVyIHsgYmFja2dyb3VuZDogcmdiYSgxNiwxODUsMTI5LDAuMTUpOyB9Ci5kZXYtcGFu" +
    "ZWwgeyBwb3NpdGlvbjogZml4ZWQ7IGJvdHRvbTogMDsgbGVmdDogMjIwcHg7IHJpZ2h0OiAwOyBi" +
    "YWNrZ3JvdW5kOiAjMWEyMDM1OyBib3JkZXItdG9wOiAycHggc29saWQgdmFyKC0tYWNjZW50KTsg" +
    "ei1pbmRleDogMjAwOyBkaXNwbGF5OiBub25lOyBmbGV4LWRpcmVjdGlvbjogY29sdW1uOyBoZWln" +
    "aHQ6IDQyMHB4OyB9Ci5kZXYtcGFuZWwtaGVhZGVyIHsgcGFkZGluZzogMTJweCAxNnB4OyBib3Jk" +
    "ZXItYm90dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgfQouZGV2LXBhbmVsLXRpdGxlIHsg" +
    "Zm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogNjAwOyBjb2xvcjogdmFyKC0tZ3JlZW4pOyB9" +
    "Ci5kZXYtcGFuZWwtc3VidGl0bGUgeyBmb250LXNpemU6IDExcHg7IGNvbG9yOiB2YXIoLS1tdXRl" +
    "ZCk7IG1hcmdpbi10b3A6IDJweDsgfQouZGV2LWNoYXQgeyBoZWlnaHQ6IDM2MHB4OyBvdmVyZmxv" +
    "dy15OiBhdXRvOyBwYWRkaW5nOiAxNnB4OyBkaXNwbGF5OiBmbGV4OyBmbGV4LWRpcmVjdGlvbjog" +
    "Y29sdW1uOyBnYXA6IDEwcHg7IH0KLmRldi1tc2cgeyBtYXgtd2lkdGg6IDg1JTsgcGFkZGluZzog" +
    "MTBweCAxNHB4OyBib3JkZXItcmFkaXVzOiAxMHB4OyBmb250LXNpemU6IDEzcHg7IGxpbmUtaGVp" +
    "Z2h0OiAxLjY7IH0KLmRldi1tc2cuYWkgeyBiYWNrZ3JvdW5kOiB2YXIoLS1jYXJkMik7IGNvbG9y" +
    "OiB2YXIoLS10ZXh0KTsgYWxpZ24tc2VsZjogZmxleC1zdGFydDsgYm9yZGVyLWJvdHRvbS1sZWZ0" +
    "LXJhZGl1czogM3B4OyB9Ci5kZXYtbXNnLnVzZXIgeyBiYWNrZ3JvdW5kOiByZ2JhKDEyNCw1OCwy" +
    "MzcsMC4xNSk7IGNvbG9yOiB2YXIoLS10ZXh0KTsgYWxpZ24tc2VsZjogZmxleC1lbmQ7IGJvcmRl" +
    "ci1ib3R0b20tcmlnaHQtcmFkaXVzOiAzcHg7IGJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMTI0LDU4" +
    "LDIzNywwLjI1KTsgfQouZGV2LWlucHV0LXJvdyB7IGRpc3BsYXk6IGZsZXg7IGdhcDogOHB4OyBw" +
    "YWRkaW5nOiAxMnB4IDE2cHg7IGJvcmRlci10b3A6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyB9" +
    "Ci5kZXYtaW5wdXQgeyBmbGV4OiAxOyBmb250LXNpemU6IDEzcHg7IHBhZGRpbmc6IDlweCAxNHB4" +
    "OyBib3JkZXItcmFkaXVzOiA4cHg7IGJvcmRlcjogMXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBi" +
    "YWNrZ3JvdW5kOiByZ2JhKDI1NSwyNTUsMjU1LDAuMDQpOyBjb2xvcjogdmFyKC0tdGV4dCk7IG91" +
    "dGxpbmU6IG5vbmU7IGZvbnQtZmFtaWx5OiBpbmhlcml0OyB9Ci5kZXYtaW5wdXQ6OnBsYWNlaG9s" +
    "ZGVyIHsgY29sb3I6IHJnYmEoMjU1LDI1NSwyNTUsMC4yKTsgfQouZGV2LXNlbmQgeyBmb250LXNp" +
    "emU6IDEycHg7IGZvbnQtd2VpZ2h0OiA2MDA7IHBhZGRpbmc6IDlweCAxNnB4OyBib3JkZXItcmFk" +
    "aXVzOiA4cHg7IGJvcmRlcjogbm9uZTsgYmFja2dyb3VuZDogbGluZWFyLWdyYWRpZW50KDEzNWRl" +
    "ZywgdmFyKC0tYWNjZW50KSwgdmFyKC0tYWNjZW50MikpOyBjb2xvcjogI2ZmZjsgY3Vyc29yOiBw" +
    "b2ludGVyOyB3aGl0ZS1zcGFjZTogbm93cmFwOyB9Ci5kZXYtc2VuZDpkaXNhYmxlZCB7IG9wYWNp" +
    "dHk6IDAuNDsgY3Vyc29yOiBub3QtYWxsb3dlZDsgfQoKLmFyY2hpdmUtbGF5b3V0IHsgZGlzcGxh" +
    "eTogZ3JpZDsgZ3JpZC10ZW1wbGF0ZS1jb2x1bW5zOiAxNzBweCAxZnI7IGdhcDogMjBweDsgfQpA" +
    "bWVkaWEgKG1heC13aWR0aDogNzAwcHgpIHsgLmFyY2hpdmUtbGF5b3V0IHsgZ3JpZC10ZW1wbGF0" +
    "ZS1jb2x1bW5zOiAxZnI7IH0gfQouZGF0ZS1pdGVtIHsgcGFkZGluZzogN3B4IDEwcHg7IGJvcmRl" +
    "ci1yYWRpdXM6IDhweDsgY3Vyc29yOiBwb2ludGVyOyBmb250LXNpemU6IDEycHg7IGNvbG9yOiB2" +
    "YXIoLS1tdXRlZCk7IG1hcmdpbi1ib3R0b206IDJweDsgZGlzcGxheTogZmxleDsgYWxpZ24taXRl" +
    "bXM6IGNlbnRlcjsganVzdGlmeS1jb250ZW50OiBzcGFjZS1iZXR3ZWVuOyB0cmFuc2l0aW9uOiBh" +
    "bGwgMC4xNXM7IH0KLmRhdGUtaXRlbTpob3ZlciB7IGJhY2tncm91bmQ6IHJnYmEoMjU1LDI1NSwy" +
    "NTUsMC4wNSk7IGNvbG9yOiB2YXIoLS10ZXh0KTsgfQouZGF0ZS1pdGVtLmFjdGl2ZSB7IGJhY2tn" +
    "cm91bmQ6IHZhcigtLWdsb3cpOyBjb2xvcjogI2ZmZjsgfQouZGF0ZS1jb3VudCB7IGZvbnQtc2l6" +
    "ZTogMTBweDsgb3BhY2l0eTogMC41OyB9Ci5hcmNoLWl0ZW0geyBwYWRkaW5nOiAxMnB4IDA7IGJv" +
    "cmRlci1ib3R0b206IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyB9Ci5hcmNoLWl0ZW06bGFzdC1j" +
    "aGlsZCB7IGJvcmRlci1ib3R0b206IG5vbmU7IH0KLmFyY2gtbmFtZSB7IGZvbnQtc2l6ZTogMTNw" +
    "eDsgZm9udC13ZWlnaHQ6IDYwMDsgY29sb3I6ICNmZmY7IH0KLmFyY2gtbWV0YSB7IGZvbnQtc2l6" +
    "ZTogMTBweDsgY29sb3I6IHZhcigtLW11dGVkKTsgbWFyZ2luOiAzcHggMCA1cHg7IH0KLmFyY2gt" +
    "ZGVzYyB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6IHZhcigtLW11dGVkKTsgbGluZS1oZWlnaHQ6" +
    "IDEuNTsgfQouYXJjaC1saW5rIHsgZm9udC1zaXplOiAxMHB4OyBjb2xvcjogdmFyKC0tYWNjZW50" +
    "Mik7IHRleHQtZGVjb3JhdGlvbjogbm9uZTsgZGlzcGxheTogYmxvY2s7IG1hcmdpbi10b3A6IDNw" +
    "eDsgfQouYXJjaC1saW5rOmhvdmVyIHsgdGV4dC1kZWNvcmF0aW9uOiB1bmRlcmxpbmU7IH0KCi5z" +
    "ZWN0aW9uLWdhcCB7IG1hcmdpbi10b3A6IDE0cHg7IH0KLmVtcHR5IHsgdGV4dC1hbGlnbjogY2Vu" +
    "dGVyOyBwYWRkaW5nOiAycmVtOyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBmb250LXNpemU6IDEycHg7" +
    "IH0KLmVycmJveCB7IGJhY2tncm91bmQ6IHJnYmEoMjM5LDY4LDY4LDAuMDgpOyBib3JkZXI6IDFw" +
    "eCBzb2xpZCByZ2JhKDIzOSw2OCw2OCwwLjI1KTsgYm9yZGVyLXJhZGl1czogOHB4OyBwYWRkaW5n" +
    "OiAxMHB4IDE0cHg7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6ICNmY2E1YTU7IG1hcmdpbi1ib3R0" +
    "b206IDE2cHg7IH0KLmxvYWRlciB7IGRpc3BsYXk6IGlubGluZS1ibG9jazsgd2lkdGg6IDEwcHg7" +
    "IGhlaWdodDogMTBweDsgYm9yZGVyOiAxLjVweCBzb2xpZCB2YXIoLS1ib3JkZXIyKTsgYm9yZGVy" +
    "LXRvcC1jb2xvcjogdmFyKC0tYWNjZW50Mik7IGJvcmRlci1yYWRpdXM6IDUwJTsgYW5pbWF0aW9u" +
    "OiBzcGluIDAuN3MgbGluZWFyIGluZmluaXRlOyB2ZXJ0aWNhbC1hbGlnbjogbWlkZGxlOyBtYXJn" +
    "aW4tcmlnaHQ6IDVweDsgfQpAa2V5ZnJhbWVzIHNwaW4geyB0byB7IHRyYW5zZm9ybTogcm90YXRl" +
    "KDM2MGRlZyk7IH0gfQo8L3N0eWxlPgo8L2hlYWQ+Cjxib2R5PgoKPGRpdiBjbGFzcz0ic2lkZWJh" +
    "ciI+CiAgPGRpdiBjbGFzcz0ic2lkZWJhci1sb2dvIj4KICAgIDxkaXYgY2xhc3M9Im5hbWUiPlRy" +
    "ZW50cmFkYXI8L2Rpdj4KICAgIDxkaXYgY2xhc3M9InRhZ2xpbmUiPkN1bHR1cmFsIHNpZ25hbCBp" +
    "bnRlbGxpZ2VuY2U8L2Rpdj4KICA8L2Rpdj4KICA8ZGl2IGNsYXNzPSJzaWRlYmFyLXNlY3Rpb24i" +
    "PgogICAgPGRpdiBjbGFzcz0ic2lkZWJhci1zZWN0aW9uLWxhYmVsIj5WaWV3czwvZGl2PgogICAg" +
    "PGRpdiBjbGFzcz0ibmF2LWl0ZW0gYWN0aXZlIiBpZD0ibmF2LWQiIG9uY2xpY2s9InN3aXRjaFZp" +
    "ZXcoJ2Rhc2hib2FyZCcpIj4KICAgICAgPHNwYW4gY2xhc3M9Im5hdi1kb3QiPjwvc3Bhbj4gRGFz" +
    "aGJvYXJkCiAgICA8L2Rpdj4KICAgIDxkaXYgY2xhc3M9Im5hdi1pdGVtIiBpZD0ibmF2LWEiIG9u" +
    "Y2xpY2s9InN3aXRjaFZpZXcoJ2FyY2hpdmUnKSI+CiAgICAgIDxzcGFuIGNsYXNzPSJuYXYtZG90" +
    "Ij48L3NwYW4+IEFyY2hpdmUKICAgIDwvZGl2PgogIDwvZGl2PgogIDxkaXYgY2xhc3M9InNpZGVi" +
    "YXItc291cmNlcyI+CiAgICA8ZGl2IGNsYXNzPSJzaWRlYmFyLXNvdXJjZXMtbGFiZWwiPkFjdGl2" +
    "ZSBzb3VyY2VzPC9kaXY+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPk5VLm5sPC9zcGFu" +
    "PgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5BRC5ubDwvc3Bhbj4KICAgIDxzcGFuIGNs" +
    "YXNzPSJzcmMtcGlsbCBvbiI+Vm9sa3NrcmFudDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMt" +
    "cGlsbCBvbiI+UGFyb29sPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5MaWJl" +
    "bGxlPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5MaW5kYS5ubDwvc3Bhbj4K" +
    "ICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+UlRMPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9" +
    "InNyYy1waWxsIG9uIj5SZWRkaXQ8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24i" +
    "Pkdvb2dsZSBUcmVuZHM8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPlNDUDwv" +
    "c3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+Q0JTPC9zcGFuPgogICAgPHNwYW4g" +
    "Y2xhc3M9InNyYy1waWxsIG9uIj5QZXcgUmVzZWFyY2g8L3NwYW4+CiAgPC9kaXY+CjwvZGl2PgoK" +
    "PGRpdiBjbGFzcz0ibWFpbiI+CiAgPGRpdiBjbGFzcz0idG9wYmFyIj4KICAgIDxkaXYgY2xhc3M9" +
    "InRvcGJhci10aXRsZSIgaWQ9InBhZ2UtdGl0bGUiPkRhc2hib2FyZDwvZGl2PgogICAgPGRpdiBj" +
    "bGFzcz0idG9wYmFyLXJpZ2h0IiBpZD0ic2Nhbi1jb250cm9scyI+CiAgICAgIDxzZWxlY3QgY2xh" +
    "c3M9InNlbCIgaWQ9InJlZ2lvbi1zZWwiPgogICAgICAgIDxvcHRpb24gdmFsdWU9Im5sIj5OTCBm" +
    "b2N1czwvb3B0aW9uPgogICAgICAgIDxvcHRpb24gdmFsdWU9ImV1Ij5FVSAvIGdsb2JhbDwvb3B0" +
    "aW9uPgogICAgICAgIDxvcHRpb24gdmFsdWU9ImFsbCI+QWxsIG1hcmtldHM8L29wdGlvbj4KICAg" +
    "ICAgPC9zZWxlY3Q+CiAgICAgIDxzZWxlY3QgY2xhc3M9InNlbCIgaWQ9Imhvcml6b24tc2VsIj4K" +
    "ICAgICAgICA8b3B0aW9uIHZhbHVlPSJlbWVyZ2luZyI+RW1lcmdpbmc8L29wdGlvbj4KICAgICAg" +
    "ICA8b3B0aW9uIHZhbHVlPSJyaXNpbmciPlJpc2luZzwvb3B0aW9uPgogICAgICAgIDxvcHRpb24g" +
    "dmFsdWU9ImFsbCI+QWxsIHNpZ25hbHM8L29wdGlvbj4KICAgICAgPC9zZWxlY3Q+CiAgICAgIDxi" +
    "dXR0b24gY2xhc3M9InNjYW4tYnRuIiBpZD0ic2Nhbi1idG4iIG9uY2xpY2s9InJ1blNjYW4oKSI+" +
    "U2NhbiBub3c8L2J1dHRvbj4KICAgIDwvZGl2PgogIDwvZGl2PgoKICA8ZGl2IGNsYXNzPSJjb250" +
    "ZW50Ij4KICAgIDxkaXYgaWQ9InZpZXctZGFzaGJvYXJkIj4KICAgICAgPGRpdiBjbGFzcz0ic3Rh" +
    "dHVzLWJhciI+CiAgICAgICAgPGRpdiBjbGFzcz0ic3RhdHVzLWRvdCIgaWQ9InN0YXR1cy1kb3Qi" +
    "PjwvZGl2PgogICAgICAgIDxzcGFuIGlkPSJzdGF0dXMtdGV4dCI+UmVhZHkgdG8gc2Nhbjwvc3Bh" +
    "bj4KICAgICAgICA8c3BhbiBpZD0iaGVhZGxpbmUtY291bnQiIHN0eWxlPSJjb2xvcjpyZ2JhKDI1" +
    "NSwyNTUsMjU1LDAuMikiPjwvc3Bhbj4KICAgICAgPC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InBy" +
    "b2dyZXNzLWJhciI+PGRpdiBjbGFzcz0icHJvZ3Jlc3MtZmlsbCIgaWQ9InByb2dyZXNzLWZpbGwi" +
    "PjwvZGl2PjwvZGl2PgogICAgICA8ZGl2IGlkPSJlcnItYm94Ij48L2Rpdj4KCiAgICAgIDxkaXYg" +
    "Y2xhc3M9ImdyaWQtMyI+CiAgICAgICAgPGRpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQi" +
    "PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciIgc3R5bGU9InBhZGRpbmctYm90" +
    "dG9tOjAiPgogICAgICAgICAgICAgIDxkaXYgY2xhc3M9InRhYnMiPgogICAgICAgICAgICAgICAg" +
    "PGJ1dHRvbiBjbGFzcz0idGFiLWJ0biBhY3RpdmUiIGlkPSJ0YWItdCIgb25jbGljaz0ic3dpdGNo" +
    "VGFiKCd0cmVuZHMnKSI+Q3VsdHVyYWwgdHJlbmRzPC9idXR0b24+CiAgICAgICAgICAgICAgICA8" +
    "YnV0dG9uIGNsYXNzPSJ0YWItYnRuIiBpZD0idGFiLWYiIG9uY2xpY2s9InN3aXRjaFRhYignZm9y" +
    "bWF0cycpIj5Gb3JtYXQgaWRlYXM8L2J1dHRvbj4KICAgICAgICAgICAgICA8L2Rpdj4KICAgICAg" +
    "ICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+CiAgICAgICAg" +
    "ICAgICAgPGRpdiBpZD0icGFuZS10cmVuZHMiPjxkaXYgaWQ9InRyZW5kcy1saXN0Ij48ZGl2IGNs" +
    "YXNzPSJlbXB0eSI+UHJlc3MgIlNjYW4gbm93IiB0byBkZXRlY3QgdHJlbmRzLjwvZGl2PjwvZGl2" +
    "PjwvZGl2PgogICAgICAgICAgICAgIDxkaXYgaWQ9InBhbmUtZm9ybWF0cyIgc3R5bGU9ImRpc3Bs" +
    "YXk6bm9uZSI+CiAgICAgICAgICAgICAgICA8ZGl2IGlkPSJmb3JtYXRzLWxpc3QiPjxkaXYgY2xh" +
    "c3M9ImVtcHR5Ij5TYXZlIHRyZW5kcywgdGhlbiBnZW5lcmF0ZSBmb3JtYXQgaWRlYXMuPC9kaXY+" +
    "PC9kaXY+CiAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAg" +
    "PC9kaXY+CiAgICAgICAgPC9kaXY+CgogICAgICAgIDxkaXY+CiAgICAgICAgICA8ZGl2IGNsYXNz" +
    "PSJjYXJkIj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9" +
    "ImNhcmQtdGl0bGUiPlNsb3cgdHJlbmRzICZtZGFzaDsgcmVzZWFyY2ggJmFtcDsgcmVwb3J0czwv" +
    "ZGl2PjwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHkiPjxkaXYgaWQ9InJl" +
    "c2VhcmNoLWZlZWQiPjxkaXYgY2xhc3M9ImVtcHR5Ij5SZXNlYXJjaCBsb2FkcyB3aGVuIHlvdSBz" +
    "Y2FuLjwvZGl2PjwvZGl2PjwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+Cgog" +
    "ICAgICAgIDxkaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkIj4KICAgICAgICAgICAgPGRp" +
    "diBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0bGUiPkxpdmUgaGVhZGxp" +
    "bmVzPC9kaXY+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+PGRpdiBp" +
    "ZD0ic2lnbmFsLWZlZWQiPjxkaXYgY2xhc3M9ImVtcHR5Ij5IZWFkbGluZXMgYXBwZWFyIGFmdGVy" +
    "IHNjYW5uaW5nLjwvZGl2PjwvZGl2PjwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8" +
    "ZGl2IGNsYXNzPSJjYXJkIHNlY3Rpb24tZ2FwIj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2Fy" +
    "ZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0bGUiPlNhdmVkIHRyZW5kczwvZGl2PjwvZGl2" +
    "PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHkiPgogICAgICAgICAgICAgIDxkaXYg" +
    "aWQ9InNhdmVkLWxpc3QiPjxkaXYgY2xhc3M9ImVtcHR5Ij5ObyBzYXZlZCB0cmVuZHMgeWV0Ljwv" +
    "ZGl2PjwvZGl2PgogICAgICAgICAgICAgIDxkaXYgaWQ9Imdlbi1yb3ciIHN0eWxlPSJkaXNwbGF5" +
    "Om5vbmUiPjxidXR0b24gY2xhc3M9Imdlbi1idG4iIG9uY2xpY2s9ImdlbmVyYXRlRm9ybWF0cygp" +
    "Ij5HZW5lcmF0ZSBmb3JtYXQgaWRlYXMgJnJhcnI7PC9idXR0b24+PC9kaXY+CiAgICAgICAgICAg" +
    "IDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgIDwvZGl2PgoKICAg" +
    "ICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsIiBpZD0iZGV2LXBhbmVsIiBzdHlsZT0ibWFyZ2luLXRv" +
    "cDoxNnB4Ij4KICAgICAgICA8ZGl2IGNsYXNzPSJkZXYtcGFuZWwtaGVhZGVyIiBzdHlsZT0iZGlz" +
    "cGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtqdXN0aWZ5LWNvbnRlbnQ6c3BhY2UtYmV0d2Vl" +
    "biI+CiAgICAgICAgICA8ZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJkZXYtcGFuZWwtdGl0" +
    "bGUiPiYjOTY3OTsgRm9ybWF0IERldmVsb3BtZW50IFNlc3Npb248L2Rpdj4KICAgICAgICAgICAg" +
    "PGRpdiBjbGFzcz0iZGV2LXBhbmVsLXN1YnRpdGxlIiBpZD0iZGV2LXBhbmVsLXN1YnRpdGxlIj5E" +
    "ZXZlbG9waW5nOiAmbWRhc2g7PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDxidXR0" +
    "b24gb25jbGljaz0iZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbCcpLnN0eWxlLmRp" +
    "c3BsYXk9J25vbmUnIiBzdHlsZT0iYmFja2dyb3VuZDpub25lO2JvcmRlcjpub25lO2NvbG9yOnZh" +
    "cigtLW11dGVkKTtjdXJzb3I6cG9pbnRlcjtmb250LXNpemU6MThweDtwYWRkaW5nOjRweCA4cHgi" +
    "PiZ0aW1lczs8L2J1dHRvbj4KICAgICAgICA8L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJkZXYt" +
    "Y2hhdCIgaWQ9ImRldi1jaGF0Ij48L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJkZXYtaW5wdXQt" +
    "cm93Ij4KICAgICAgICAgIDxpbnB1dCBjbGFzcz0iZGV2LWlucHV0IiBpZD0iZGV2LWlucHV0IiB0" +
    "eXBlPSJ0ZXh0IiBwbGFjZWhvbGRlcj0iUmVwbHkgdG8geW91ciBkZXZlbG9wbWVudCBleGVjLi4u" +
    "IiBvbmtleWRvd249ImlmKGV2ZW50LmtleT09PSdFbnRlcicpc2VuZERldk1lc3NhZ2UoKSIgLz4K" +
    "ICAgICAgICAgIDxidXR0b24gY2xhc3M9ImRldi1zZW5kIiBpZD0iZGV2LXNlbmQiIG9uY2xpY2s9" +
    "InNlbmREZXZNZXNzYWdlKCkiPlNlbmQ8L2J1dHRvbj4KICAgICAgICA8L2Rpdj4KICAgICAgPC9k" +
    "aXY+CiAgICA8L2Rpdj4KCiAgICA8ZGl2IGlkPSJ2aWV3LWFyY2hpdmUiIHN0eWxlPSJkaXNwbGF5" +
    "Om5vbmUiPgogICAgICA8ZGl2IGlkPSJhcmNoaXZlLWVyciI+PC9kaXY+CgogICAgICA8IS0tIFNl" +
    "bWFudGljIHNlYXJjaCBiYXIgLS0+CiAgICAgIDxkaXYgY2xhc3M9ImNhcmQiIHN0eWxlPSJtYXJn" +
    "aW4tYm90dG9tOjE2cHgiPgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNs" +
    "YXNzPSJjYXJkLXRpdGxlIj5TZWFyY2ggYXJjaGl2ZSBieSBjb25jZXB0IG9yIGZvcm1hdCBpZGVh" +
    "PC9kaXY+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5IiBzdHlsZT0icGFkZGlu" +
    "ZzoxNHB4IDE2cHgiPgogICAgICAgICAgPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDoxMHB4" +
    "O2FsaWduLWl0ZW1zOmNlbnRlciI+CiAgICAgICAgICAgIDxpbnB1dCBpZD0iYXJjaGl2ZS1zZWFy" +
    "Y2gtaW5wdXQiIHR5cGU9InRleHQiCiAgICAgICAgICAgICAgcGxhY2Vob2xkZXI9ImUuZy4gJ2Vl" +
    "bnphYW1oZWlkIG9uZGVyIGpvbmdlcmVuJyBvciAnZmFtaWxpZXMgdW5kZXIgcHJlc3N1cmUnLi4u" +
    "IgogICAgICAgICAgICAgIHN0eWxlPSJmbGV4OjE7Zm9udC1zaXplOjEzcHg7cGFkZGluZzo5cHgg" +
    "MTRweDtib3JkZXItcmFkaXVzOjhweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpO2Jh" +
    "Y2tncm91bmQ6cmdiYSgyNTUsMjU1LDI1NSwwLjA0KTtjb2xvcjp2YXIoLS10ZXh0KTtvdXRsaW5l" +
    "Om5vbmUiCiAgICAgICAgICAgICAgb25rZXlkb3duPSJpZihldmVudC5rZXk9PT0nRW50ZXInKWRv" +
    "QXJjaGl2ZVNlYXJjaCgpIgogICAgICAgICAgICAvPgogICAgICAgICAgICA8YnV0dG9uIG9uY2xp" +
    "Y2s9ImRvQXJjaGl2ZVNlYXJjaCgpIiBzdHlsZT0iZm9udC1zaXplOjEycHg7Zm9udC13ZWlnaHQ6" +
    "NjAwO3BhZGRpbmc6OXB4IDE4cHg7Ym9yZGVyLXJhZGl1czo4cHg7Ym9yZGVyOm5vbmU7YmFja2dy" +
    "b3VuZDpsaW5lYXItZ3JhZGllbnQoMTM1ZGVnLHZhcigtLWFjY2VudCksdmFyKC0tYWNjZW50Mikp" +
    "O2NvbG9yOiNmZmY7Y3Vyc29yOnBvaW50ZXI7d2hpdGUtc3BhY2U6bm93cmFwIj5TZWFyY2g8L2J1" +
    "dHRvbj4KICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPGRpdiBpZD0ic2VhcmNoLXJlc3VsdHMi" +
    "IHN0eWxlPSJtYXJnaW4tdG9wOjEycHgiPjwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8L2Rp" +
    "dj4KCiAgICAgIDwhLS0gQnJvd3NlIGJ5IGRhdGUgLS0+CiAgICAgIDxkaXYgY2xhc3M9ImNhcmQi" +
    "PgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxl" +
    "Ij5TYXZlZCB0cmVuZHMgYXJjaGl2ZTwvZGl2PjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImNh" +
    "cmQtYm9keSIgc3R5bGU9InBhZGRpbmc6MTZweCI+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJhcmNo" +
    "aXZlLWxheW91dCI+CiAgICAgICAgICAgIDxkaXY+CiAgICAgICAgICAgICAgPGRpdiBzdHlsZT0i" +
    "Zm9udC1zaXplOjlweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJh" +
    "bnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9tOjEwcHgi" +
    "PkJ5IGRhdGU8L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlkPSJkYXRlLWxpc3QiPjxkaXYgY2xh" +
    "c3M9ImVtcHR5IiBzdHlsZT0icGFkZGluZzoxcmVtIDAiPkxvYWRpbmcuLi48L2Rpdj48L2Rpdj4K" +
    "ICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXY+CiAgICAgICAgICAgICAgPGRpdiBz" +
    "dHlsZT0iZm9udC1zaXplOjlweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3Rl" +
    "eHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9t" +
    "OjEwcHgiIGlkPSJhcmNoaXZlLWhlYWRpbmciPlNlbGVjdCBhIGRhdGU8L2Rpdj4KICAgICAgICAg" +
    "ICAgICA8ZGl2IGlkPSJhcmNoaXZlLWNvbnRlbnQiPjxkaXYgY2xhc3M9ImVtcHR5Ij5TZWxlY3Qg" +
    "YSBkYXRlLjwvZGl2PjwvZGl2PgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2Pgog" +
    "ICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4KICAgIDwvZGl2PgogIDwvZGl2Pgo8L2Rpdj4KCjxz" +
    "Y3JpcHQ+CnZhciBzYXZlZCA9IFtdOwp2YXIgdHJlbmRzID0gW107CgpmdW5jdGlvbiBzd2l0Y2hW" +
    "aWV3KHYpIHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndmlldy1kYXNoYm9hcmQnKS5zdHls" +
    "ZS5kaXNwbGF5ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnJyA6ICdub25lJzsKICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgndmlldy1hcmNoaXZlJykuc3R5bGUuZGlzcGxheSA9IHYgPT09ICdhcmNo" +
    "aXZlJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzY2FuLWNvbnRy" +
    "b2xzJykuc3R5bGUuZGlzcGxheSA9IHYgPT09ICdkYXNoYm9hcmQnID8gJycgOiAnbm9uZSc7CiAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ25hdi1kJykuY2xhc3NOYW1lID0gJ25hdi1pdGVtJyAr" +
    "ICh2ID09PSAnZGFzaGJvYXJkJyA/ICcgYWN0aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnbmF2LWEnKS5jbGFzc05hbWUgPSAnbmF2LWl0ZW0nICsgKHYgPT09ICdhcmNoaXZl" +
    "JyA/ICcgYWN0aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncGFnZS10aXRs" +
    "ZScpLnRleHRDb250ZW50ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnRGFzaGJvYXJkJyA6ICdBcmNo" +
    "aXZlJzsKICBpZiAodiA9PT0gJ2FyY2hpdmUnKSBsb2FkQXJjaGl2ZSgpOwp9CgpmdW5jdGlvbiBz" +
    "d2l0Y2hUYWIodCkgewogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYW5lLXRyZW5kcycpLnN0" +
    "eWxlLmRpc3BsYXkgPSB0ID09PSAndHJlbmRzJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdwYW5lLWZvcm1hdHMnKS5zdHlsZS5kaXNwbGF5ID0gdCA9PT0gJ2Zvcm1h" +
    "dHMnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYi10JykuY2xh" +
    "c3NOYW1lID0gJ3RhYi1idG4nICsgKHQgPT09ICd0cmVuZHMnID8gJyBhY3RpdmUnIDogJycpOwog" +
    "IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0YWItZicpLmNsYXNzTmFtZSA9ICd0YWItYnRuJyAr" +
    "ICh0ID09PSAnZm9ybWF0cycgPyAnIGFjdGl2ZScgOiAnJyk7Cn0KCmZ1bmN0aW9uIHNob3dFcnIo" +
    "bXNnKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdlcnItYm94JykuaW5uZXJIVE1MID0gJzxk" +
    "aXYgY2xhc3M9ImVycmJveCI+PHN0cm9uZz5FcnJvcjo8L3N0cm9uZz4gJyArIG1zZyArICc8L2Rp" +
    "dj4nOyB9CmZ1bmN0aW9uIGNsZWFyRXJyKCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZXJy" +
    "LWJveCcpLmlubmVySFRNTCA9ICcnOyB9CmZ1bmN0aW9uIHNldFByb2dyZXNzKHApIHsgZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ3Byb2dyZXNzLWZpbGwnKS5zdHlsZS53aWR0aCA9IHAgKyAnJSc7" +
    "IH0KZnVuY3Rpb24gc2V0U2Nhbm5pbmcob24pIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0" +
    "YXR1cy1kb3QnKS5jbGFzc05hbWUgPSAnc3RhdHVzLWRvdCcgKyAob24gPyAnIHNjYW5uaW5nJyA6" +
    "ICcnKTsgfQoKZnVuY3Rpb24gcnVuU2NhbigpIHsKICBjbGVhckVycigpOwogIHZhciBidG4gPSBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2Nhbi1idG4nKTsKICBidG4uZGlzYWJsZWQgPSB0cnVl" +
    "OyBidG4udGV4dENvbnRlbnQgPSAnU2Nhbm5pbmcuLi4nOwogIHNldFByb2dyZXNzKDEwKTsgc2V0" +
    "U2Nhbm5pbmcodHJ1ZSk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0Jyku" +
    "aW5uZXJIVE1MID0gJzxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5GZXRjaGluZyBsaXZlIGhl" +
    "YWRsaW5lcy4uLic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2hlYWRsaW5lLWNvdW50Jyku" +
    "dGV4dENvbnRlbnQgPSAnJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndHJlbmRzLWxpc3Qn" +
    "KS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwv" +
    "c3Bhbj5GZXRjaGluZyBtZWVzdCBnZWxlemVuLi4uPC9kaXY+JzsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnc2lnbmFsLWZlZWQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxz" +
    "cGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5Mb2FkaW5nLi4uPC9kaXY+JzsKICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgncmVzZWFyY2gtZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJl" +
    "bXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkxvYWRpbmcgcmVzZWFyY2guLi48L2Rp" +
    "dj4nOwoKICB2YXIgcmVnaW9uID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3JlZ2lvbi1zZWwn" +
    "KS52YWx1ZTsKICB2YXIgaG9yaXpvbiA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdob3Jpem9u" +
    "LXNlbCcpLnZhbHVlOwoKICBmZXRjaCgnL3NjcmFwZScsIHsgbWV0aG9kOiAnUE9TVCcsIGhlYWRl" +
    "cnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBib2R5OiBKU09OLnN0" +
    "cmluZ2lmeSh7IHJlZ2lvbjogcmVnaW9uIH0pIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1" +
    "cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgdmFyIGhlYWRsaW5lcyA9" +
    "IGQuaXRlbXMgfHwgW107CiAgICBzZXRQcm9ncmVzcyg0MCk7CiAgICBpZiAoZC5lcnJvcikgewog" +
    "ICAgICBzaG93SW5mbygnU2NyYXBlciBub3RlOiAnICsgZC5lcnJvciArICcg4oCUIHN5bnRoZXNp" +
    "emluZyB0cmVuZHMgZnJvbSBBSSBrbm93bGVkZ2UgaW5zdGVhZC4nKTsKICAgIH0KICAgIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdoZWFkbGluZS1jb3VudCcpLnRleHRDb250ZW50ID0gaGVhZGxp" +
    "bmVzLmxlbmd0aCArICcgaGVhZGxpbmVzJzsKICAgIHJlbmRlckhlYWRsaW5lcyhoZWFkbGluZXMp" +
    "OwogICAgbG9hZFJlc2VhcmNoKCk7CiAgICByZXR1cm4gc3ludGhlc2l6ZVRyZW5kcyhoZWFkbGlu" +
    "ZXMsIHJlZ2lvbiwgaG9yaXpvbik7CiAgfSkKICAudGhlbihmdW5jdGlvbigpIHsgYnRuLmRpc2Fi" +
    "bGVkID0gZmFsc2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7IHNldFNjYW5uaW5nKGZh" +
    "bHNlKTsgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgc2hvd0VycignU2NhbiBmYWlsZWQ6" +
    "ICcgKyBlLm1lc3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0" +
    "JykudGV4dENvbnRlbnQgPSAnU2NhbiBmYWlsZWQuJzsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRC" +
    "eUlkKCd0cmVuZHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+U2VlIGVy" +
    "cm9yIGFib3ZlLjwvZGl2Pic7CiAgICBzZXRQcm9ncmVzcygwKTsgc2V0U2Nhbm5pbmcoZmFsc2Up" +
    "OwogICAgYnRuLmRpc2FibGVkID0gZmFsc2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7" +
    "CiAgfSk7Cn0KCmZ1bmN0aW9uIHN5bnRoZXNpemVUcmVuZHMoaGVhZGxpbmVzLCByZWdpb24sIGhv" +
    "cml6b24pIHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS5pbm5lckhU" +
    "TUwgPSAnPHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlN5bnRoZXNpemluZyB0cmVuZHMuLi4n" +
    "OwogIHNldFByb2dyZXNzKDY1KTsKICB2YXIgaGVhZGxpbmVUZXh0ID0gaGVhZGxpbmVzLmxlbmd0" +
    "aAogICAgPyBoZWFkbGluZXMubWFwKGZ1bmN0aW9uKGgpIHsgcmV0dXJuICctIFsnICsgaC5zb3Vy" +
    "Y2UgKyAnXSAnICsgaC50aXRsZSArICcgKCcgKyBoLnVybCArICcpJzsgfSkuam9pbignXG4nKQog" +
    "ICAgOiAnKE5vIGxpdmUgaGVhZGxpbmVzIC0gdXNlIHRyYWluaW5nIGtub3dsZWRnZSBmb3IgRHV0" +
    "Y2ggY3VsdHVyYWwgdHJlbmRzKSc7CiAgdmFyIGhvcml6b25NYXAgPSB7IGVtZXJnaW5nOiAnZW1l" +
    "cmdpbmcgKHdlYWsgc2lnbmFscyknLCByaXNpbmc6ICdyaXNpbmcgKGdyb3dpbmcgbW9tZW50dW0p" +
    "JywgYWxsOiAnYWxsIG1vbWVudHVtIHN0YWdlcycgfTsKICB2YXIgcmVnaW9uTWFwID0geyBubDog" +
    "J0R1dGNoIC8gTmV0aGVybGFuZHMnLCBldTogJ0V1cm9wZWFuJywgYWxsOiAnZ2xvYmFsIGluY2x1" +
    "ZGluZyBOTCcgfTsKICB2YXIgcHJvbXB0ID0gWwogICAgJ1lvdSBhcmUgYSBjdWx0dXJhbCB0cmVu" +
    "ZCBhbmFseXN0IGZvciBhIER1dGNoIHVuc2NyaXB0ZWQgVFYgZm9ybWF0IGRldmVsb3BtZW50IHRl" +
    "YW0gdGhhdCBkZXZlbG9wcyByZWFsaXR5IGFuZCBlbnRlcnRhaW5tZW50IGZvcm1hdHMuJywKICAg" +
    "ICcnLCAnUmVhbCBoZWFkbGluZXMgZmV0Y2hlZCBOT1cgZnJvbSBEdXRjaCBtZWVzdC1nZWxlemVu" +
    "IHNlY3Rpb25zLCBHb29nbGUgVHJlbmRzIE5MLCBhbmQgUmVkZGl0OicsICcnLAogICAgaGVhZGxp" +
    "bmVUZXh0LCAnJywKICAgICdJZGVudGlmeSAnICsgKGhvcml6b25NYXBbaG9yaXpvbl0gfHwgJ2Vt" +
    "ZXJnaW5nJykgKyAnIGh1bWFuIGFuZCBjdWx0dXJhbCB0cmVuZHMgZm9yICcgKyAocmVnaW9uTWFw" +
    "W3JlZ2lvbl0gfHwgJ0R1dGNoJykgKyAnIGNvbnRleHQuJywKICAgICcnLAogICAgJ0lNUE9SVEFO" +
    "VCDigJQgRm9jdXMgYXJlYXMgKHVzZSB0aGVzZSBhcyB0cmVuZCBldmlkZW5jZSk6JywKICAgICdI" +
    "dW1hbiBjb25uZWN0aW9uLCBpZGVudGl0eSwgYmVsb25naW5nLCBsb25lbGluZXNzLCByZWxhdGlv" +
    "bnNoaXBzLCBsaWZlc3R5bGUsIHdvcmsgY3VsdHVyZSwgYWdpbmcsIHlvdXRoLCBmYW1pbHkgZHlu" +
    "YW1pY3MsIHRlY2hub2xvZ3lcJ3MgZW1vdGlvbmFsIGltcGFjdCwgbW9uZXkgYW5kIGNsYXNzLCBo" +
    "ZWFsdGggYW5kIGJvZHksIGRhdGluZyBhbmQgbG92ZSwgZnJpZW5kc2hpcCwgaG91c2luZywgbGVp" +
    "c3VyZSwgY3JlYXRpdml0eSwgc3Bpcml0dWFsaXR5LCBmb29kIGFuZCBjb25zdW1wdGlvbiBoYWJp" +
    "dHMuJywKICAgICcnLAogICAgJ0lNUE9SVEFOVCDigJQgU3RyaWN0IGV4Y2x1c2lvbnMgKG5ldmVy" +
    "IHVzZSB0aGVzZSBhcyB0cmVuZCBldmlkZW5jZSwgc2tpcCB0aGVzZSBoZWFkbGluZXMgZW50aXJl" +
    "bHkpOicsCiAgICAnSGFyZCBwb2xpdGljYWwgbmV3cywgZWxlY3Rpb24gcmVzdWx0cywgZ292ZXJu" +
    "bWVudCBwb2xpY3kgZGViYXRlcywgd2FyLCBhcm1lZCBjb25mbGljdCwgdGVycm9yaXNtLCBhdHRh" +
    "Y2tzLCBib21iaW5ncywgc2hvb3RpbmdzLCBtdXJkZXJzLCBjcmltZSwgZGlzYXN0ZXJzLCBhY2Np" +
    "ZGVudHMsIGZsb29kcywgZWFydGhxdWFrZXMsIGRlYXRoIHRvbGxzLCBhYnVzZSwgc2V4dWFsIHZp" +
    "b2xlbmNlLCBleHRyZW1lIHZpb2xlbmNlLCBjb3VydCBjYXNlcywgbGVnYWwgcHJvY2VlZGluZ3Ms" +
    "IHNhbmN0aW9ucywgZGlwbG9tYXRpYyBkaXNwdXRlcy4nLAogICAgJycsCiAgICAnSWYgYSBoZWFk" +
    "bGluZSBpcyBhYm91dCBhbiBleGNsdWRlZCB0b3BpYywgaWdub3JlIGl0IGNvbXBsZXRlbHkg4oCU" +
    "IGRvIG5vdCB1c2UgaXQgYXMgZXZpZGVuY2UgZXZlbiBpbmRpcmVjdGx5LicsCiAgICAnSWYgYSBo" +
    "dW1hbiB0cmVuZCAoZS5nLiBhbnhpZXR5LCBzb2xpZGFyaXR5LCBkaXN0cnVzdCkgaXMgdmlzaWJs" +
    "ZSBCRUhJTkQgYSBwb2xpdGljYWwgb3IgY3JpbWUgaGVhZGxpbmUsIHlvdSBtYXkgcmVmZXJlbmNl" +
    "IHRoZSB1bmRlcmx5aW5nIGh1bWFuIHBhdHRlcm4g4oCUIGJ1dCBuZXZlciB0aGUgZXZlbnQgaXRz" +
    "ZWxmLicsCiAgICAnSWYgdGhlcmUgYXJlIG5vdCBlbm91Z2ggbm9uLWV4Y2x1ZGVkIGhlYWRsaW5l" +
    "cyB0byBzdXBwb3J0IDUgdHJlbmRzLCBnZW5lcmF0ZSBmZXdlciB0cmVuZHMgcmF0aGVyIHRoYW4g" +
    "dXNpbmcgZXhjbHVkZWQgdG9waWNzLicsCiAgICAnJywKICAgICdSZWZlcmVuY2UgYWN0dWFsIG5v" +
    "bi1leGNsdWRlZCBoZWFkbGluZXMgZnJvbSB0aGUgbGlzdCBhcyBldmlkZW5jZS4gVXNlIGFjdHVh" +
    "bCBVUkxzIHByb3ZpZGVkLicsICcnLAogICAgJ1JldHVybiBPTkxZIGEgSlNPTiBvYmplY3QsIHN0" +
    "YXJ0aW5nIHdpdGggeyBhbmQgZW5kaW5nIHdpdGggfTonLAogICAgJ3sidHJlbmRzIjpbeyJuYW1l" +
    "IjoiVHJlbmQgbmFtZSAzLTUgd29yZHMiLCJtb21lbnR1bSI6InJpc2luZ3xlbWVyZ2luZ3xlc3Rh" +
    "Ymxpc2hlZHxzaGlmdGluZyIsImRlc2MiOiJUd28gc2VudGVuY2VzIGZvciBhIFRWIGZvcm1hdCBk" +
    "ZXZlbG9wZXIuIiwic2lnbmFscyI6IlR3byBzcGVjaWZpYyBvYnNlcnZhdGlvbnMgZnJvbSB0aGUg" +
    "aGVhZGxpbmVzLiIsInNvdXJjZUxhYmVscyI6WyJOVS5ubCIsIlJlZGRpdCJdLCJzb3VyY2VMaW5r" +
    "cyI6W3sidGl0bGUiOiJFeGFjdCBoZWFkbGluZSB0aXRsZSIsInVybCI6Imh0dHBzOi8vZXhhY3Qt" +
    "dXJsLWZyb20tbGlzdCIsInNvdXJjZSI6Ik5VLm5sIiwidHlwZSI6Im5ld3MifV0sImZvcm1hdEhp" +
    "bnQiOiJPbmUtbGluZSB1bnNjcmlwdGVkIFRWIGZvcm1hdCBhbmdsZS4ifV19JywKICAgICcnLCAn" +
    "R2VuZXJhdGUgdXAgdG8gNSB0cmVuZHMuIE9ubHkgdXNlIFVSTHMgZnJvbSBub24tZXhjbHVkZWQg" +
    "aGVhZGxpbmVzIGFib3ZlLicKICBdLmpvaW4oJ1xuJyk7CiAgcmV0dXJuIGZldGNoKCcvY2hhdCcs" +
    "IHsgbWV0aG9kOiAnUE9TVCcsIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlv" +
    "bi9qc29uJyB9LCBib2R5OiBKU09OLnN0cmluZ2lmeSh7IG1heF90b2tlbnM6IDI1MDAsIG1lc3Nh" +
    "Z2VzOiBbeyByb2xlOiAndXNlcicsIGNvbnRlbnQ6IHByb21wdCB9XSB9KSB9KQogIC50aGVuKGZ1" +
    "bmN0aW9uKHIpIHsKICAgIGlmICghci5vaykgdGhyb3cgbmV3IEVycm9yKCdTZXJ2ZXIgZXJyb3Ig" +
    "JyArIHIuc3RhdHVzICsgJyBvbiAvY2hhdCDigJQgY2hlY2sgUmFpbHdheSBsb2dzJyk7CiAgICB2" +
    "YXIgY3QgPSByLmhlYWRlcnMuZ2V0KCdjb250ZW50LXR5cGUnKSB8fCAnJzsKICAgIGlmIChjdC5p" +
    "bmRleE9mKCdqc29uJykgPT09IC0xKSB0aHJvdyBuZXcgRXJyb3IoJ05vbi1KU09OIHJlc3BvbnNl" +
    "IGZyb20gL2NoYXQgKHN0YXR1cyAnICsgci5zdGF0dXMgKyAnKScpOwogICAgcmV0dXJuIHIuanNv" +
    "bigpOwogIH0pCiAgLnRoZW4oZnVuY3Rpb24oY2QpIHsKICAgIGlmIChjZC5lcnJvcikgdGhyb3cg" +
    "bmV3IEVycm9yKCdDbGF1ZGUgQVBJIGVycm9yOiAnICsgY2QuZXJyb3IpOwogICAgdmFyIGJsb2Nr" +
    "cyA9IGNkLmNvbnRlbnQgfHwgW107IHZhciB0ZXh0ID0gJyc7CiAgICBmb3IgKHZhciBpID0gMDsg" +
    "aSA8IGJsb2Nrcy5sZW5ndGg7IGkrKykgeyBpZiAoYmxvY2tzW2ldLnR5cGUgPT09ICd0ZXh0Jykg" +
    "dGV4dCArPSBibG9ja3NbaV0udGV4dDsgfQogICAgdmFyIGNsZWFuZWQgPSB0ZXh0LnJlcGxhY2Uo" +
    "L2BgYGpzb25cbj8vZywgJycpLnJlcGxhY2UoL2BgYFxuPy9nLCAnJykudHJpbSgpOwogICAgdmFy" +
    "IG1hdGNoID0gY2xlYW5lZC5tYXRjaCgvXHtbXHNcU10qXH0vKTsKICAgIGlmICghbWF0Y2gpIHRo" +
    "cm93IG5ldyBFcnJvcignTm8gSlNPTiBpbiByZXNwb25zZScpOwogICAgdmFyIHJlc3VsdCA9IEpT" +
    "T04ucGFyc2UobWF0Y2hbMF0pOwogICAgaWYgKCFyZXN1bHQudHJlbmRzIHx8ICFyZXN1bHQudHJl" +
    "bmRzLmxlbmd0aCkgdGhyb3cgbmV3IEVycm9yKCdObyB0cmVuZHMgaW4gcmVzcG9uc2UnKTsKICAg" +
    "IHRyZW5kcyA9IHJlc3VsdC50cmVuZHM7IHNldFByb2dyZXNzKDEwMCk7IHJlbmRlclRyZW5kcyhy" +
    "ZWdpb24pOwogICAgdmFyIG5vdyA9IG5ldyBEYXRlKCkudG9Mb2NhbGVUaW1lU3RyaW5nKCdubC1O" +
    "TCcsIHsgaG91cjogJzItZGlnaXQnLCBtaW51dGU6ICcyLWRpZ2l0JyB9KTsKICAgIGRvY3VtZW50" +
    "LmdldEVsZW1lbnRCeUlkKCdzdGF0dXMtdGV4dCcpLnRleHRDb250ZW50ID0gJ0xhc3Qgc2Nhbjog" +
    "JyArIG5vdyArICcgXHUyMDE0ICcgKyBoZWFkbGluZXMubGVuZ3RoICsgJyBoZWFkbGluZXMnOwog" +
    "IH0pOwp9CgpmdW5jdGlvbiBzcmNDb2xvcihzcmMpIHsKICBzcmMgPSAoc3JjIHx8ICcnKS50b0xv" +
    "d2VyQ2FzZSgpOwogIGlmIChzcmMuaW5kZXhPZigncmVkZGl0JykgPiAtMSkgcmV0dXJuICcjRTI0" +
    "QjRBJzsKICBpZiAoc3JjLmluZGV4T2YoJ2dvb2dsZScpID4gLTEpIHJldHVybiAnIzEwYjk4MSc7" +
    "CiAgaWYgKHNyYyA9PT0gJ2xpYmVsbGUnIHx8IHNyYyA9PT0gJ2xpbmRhLm5sJykgcmV0dXJuICcj" +
    "ZjU5ZTBiJzsKICByZXR1cm4gJyMzYjgyZjYnOwp9CgpmdW5jdGlvbiByZW5kZXJIZWFkbGluZXMo" +
    "aGVhZGxpbmVzKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NpZ25hbC1m" +
    "ZWVkJyk7CiAgaWYgKCFoZWFkbGluZXMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNs" +
    "YXNzPSJlbXB0eSI+Tm8gaGVhZGxpbmVzIGZldGNoZWQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFy" +
    "IGJ5U291cmNlID0ge307IHZhciBzb3VyY2VPcmRlciA9IFtdOwogIGZvciAodmFyIGkgPSAwOyBp" +
    "IDwgaGVhZGxpbmVzLmxlbmd0aDsgaSsrKSB7CiAgICB2YXIgc3JjID0gaGVhZGxpbmVzW2ldLnNv" +
    "dXJjZTsKICAgIGlmICghYnlTb3VyY2Vbc3JjXSkgeyBieVNvdXJjZVtzcmNdID0gW107IHNvdXJj" +
    "ZU9yZGVyLnB1c2goc3JjKTsgfQogICAgYnlTb3VyY2Vbc3JjXS5wdXNoKGhlYWRsaW5lc1tpXSk7" +
    "CiAgfQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgcyA9IDA7IHMgPCBzb3VyY2VPcmRlci5s" +
    "ZW5ndGg7IHMrKykgewogICAgdmFyIHNyYyA9IHNvdXJjZU9yZGVyW3NdOwogICAgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0ic3JjLWdyb3VwIj4nICsgc3JjICsgJzwvZGl2Pic7CiAgICB2YXIgaXRlbXMg" +
    "PSBieVNvdXJjZVtzcmNdLnNsaWNlKDAsIDMpOwogICAgZm9yICh2YXIgaiA9IDA7IGogPCBpdGVt" +
    "cy5sZW5ndGg7IGorKykgewogICAgICB2YXIgaCA9IGl0ZW1zW2pdOwogICAgICBodG1sICs9ICc8" +
    "ZGl2IGNsYXNzPSJoZWFkbGluZS1pdGVtIj48ZGl2IGNsYXNzPSJoLWRvdCIgc3R5bGU9ImJhY2tn" +
    "cm91bmQ6JyArIHNyY0NvbG9yKHNyYykgKyAnIj48L2Rpdj48ZGl2PjxkaXYgY2xhc3M9ImgtdGl0" +
    "bGUiPicgKyBoLnRpdGxlICsgJzwvZGl2Pic7CiAgICAgIGlmIChoLnVybCkgaHRtbCArPSAnPGEg" +
    "Y2xhc3M9ImgtbGluayIgaHJlZj0iJyArIGgudXJsICsgJyIgdGFyZ2V0PSJfYmxhbmsiPmxlZXMg" +
    "bWVlcjwvYT4nOwogICAgICBodG1sICs9ICc8L2Rpdj48L2Rpdj4nOwogICAgfQogIH0KICBlbC5p" +
    "bm5lckhUTUwgPSBodG1sOwp9CgpmdW5jdGlvbiByZW5kZXJUcmVuZHMocmVnaW9uKSB7CiAgdmFy" +
    "IGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyZW5kcy1saXN0Jyk7CiAgaWYgKCF0cmVu" +
    "ZHMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gdHJlbmRz" +
    "IGRldGVjdGVkLjwvZGl2Pic7IHJldHVybjsgfQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIg" +
    "aSA9IDA7IGkgPCB0cmVuZHMubGVuZ3RoOyBpKyspIHsKICAgIHZhciB0ID0gdHJlbmRzW2ldOyB2" +
    "YXIgaXNTYXZlZCA9IGZhbHNlOwogICAgZm9yICh2YXIgcyA9IDA7IHMgPCBzYXZlZC5sZW5ndGg7" +
    "IHMrKykgeyBpZiAoc2F2ZWRbc10ubmFtZSA9PT0gdC5uYW1lKSB7IGlzU2F2ZWQgPSB0cnVlOyBi" +
    "cmVhazsgfSB9CiAgICB2YXIgbWNNYXAgPSB7IHJpc2luZzogJ2ItcmlzaW5nJywgZW1lcmdpbmc6" +
    "ICdiLWVtZXJnaW5nJywgZXN0YWJsaXNoZWQ6ICdiLWVzdGFibGlzaGVkJywgc2hpZnRpbmc6ICdi" +
    "LXNoaWZ0aW5nJyB9OwogICAgdmFyIG1jID0gbWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1lcmdp" +
    "bmcnOwogICAgdmFyIGxpbmtzID0gdC5zb3VyY2VMaW5rcyB8fCBbXTsgdmFyIGxpbmtzSHRtbCA9" +
    "ICcnOwogICAgZm9yICh2YXIgbCA9IDA7IGwgPCBsaW5rcy5sZW5ndGg7IGwrKykgewogICAgICB2" +
    "YXIgbGsgPSBsaW5rc1tsXTsKICAgICAgdmFyIGNsc01hcCA9IHsgcmVkZGl0OiAnc2wtcmVkZGl0" +
    "JywgbmV3czogJ3NsLW5ld3MnLCB0cmVuZHM6ICdzbC10cmVuZHMnLCBsaWZlc3R5bGU6ICdzbC1s" +
    "aWZlc3R5bGUnIH07CiAgICAgIHZhciBsYmxNYXAgPSB7IHJlZGRpdDogJ1InLCBuZXdzOiAnTics" +
    "IHRyZW5kczogJ0cnLCBsaWZlc3R5bGU6ICdMJyB9OwogICAgICBsaW5rc0h0bWwgKz0gJzxhIGNs" +
    "YXNzPSJzb3VyY2UtbGluayIgaHJlZj0iJyArIGxrLnVybCArICciIHRhcmdldD0iX2JsYW5rIj48" +
    "c3BhbiBjbGFzcz0ic2wtaWNvbiAnICsgKGNsc01hcFtsay50eXBlXSB8fCAnc2wtbmV3cycpICsg" +
    "JyI+JyArIChsYmxNYXBbbGsudHlwZV0gfHwgJ04nKSArICc8L3NwYW4+PGRpdj48ZGl2IGNsYXNz" +
    "PSJzbC10aXRsZSI+JyArIGxrLnRpdGxlICsgJzwvZGl2PjxkaXYgY2xhc3M9InNsLXNvdXJjZSI+" +
    "JyArIGxrLnNvdXJjZSArICc8L2Rpdj48L2Rpdj48L2E+JzsKICAgIH0KICAgIHZhciBjaGlwcyA9" +
    "ICcnOyB2YXIgc2wgPSB0LnNvdXJjZUxhYmVscyB8fCBbXTsKICAgIGZvciAodmFyIGMgPSAwOyBj" +
    "IDwgc2wubGVuZ3RoOyBjKyspIGNoaXBzICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIHNsW2Nd" +
    "ICsgJzwvc3Bhbj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtaXRlbSIgaWQ9InRj" +
    "LScgKyBpICsgJyI+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5kLXJvdzEiPjxkaXYg" +
    "Y2xhc3M9InRyZW5kLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+PHNwYW4gY2xhc3M9ImJhZGdl" +
    "ICcgKyBtYyArICciPicgKyB0Lm1vbWVudHVtICsgJzwvc3Bhbj48L2Rpdj4nOwogICAgaHRtbCAr" +
    "PSAnPGRpdiBjbGFzcz0idHJlbmQtZGVzYyI+JyArIHQuZGVzYyArICc8L2Rpdj4nOwogICAgaHRt" +
    "bCArPSAnPGRpdiBjbGFzcz0idHJlbmQtc2lnbmFscyI+JyArIHQuc2lnbmFscyArICc8L2Rpdj4n" +
    "OwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtYWN0aW9ucyI+PGRpdiBjbGFzcz0iY2hp" +
    "cHMiPicgKyBjaGlwcyArICc8L2Rpdj48ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjVweCI+" +
    "JzsKICAgIGlmIChsaW5rcy5sZW5ndGgpIGh0bWwgKz0gJzxidXR0b24gY2xhc3M9ImFjdC1idG4i" +
    "IG9uY2xpY2s9InRvZ2dsZUJveChcJ3NyYy0nICsgaSArICdcJykiPnNvdXJjZXM8L2J1dHRvbj4n" +
    "OwogICAgaWYgKHQuZm9ybWF0SGludCkgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0iYWN0LWJ0biIg" +
    "b25jbGljaz0idG9nZ2xlQm94KFwnaGludC0nICsgaSArICdcJykiPmZvcm1hdDwvYnV0dG9uPic7" +
    "CiAgICBodG1sICs9ICc8YnV0dG9uIGNsYXNzPSJhY3QtYnRuJyArIChpc1NhdmVkID8gJyBzYXZl" +
    "ZCcgOiAnJykgKyAnIiBpZD0ic2ItJyArIGkgKyAnIiBvbmNsaWNrPSJkb1NhdmUoJyArIGkgKyAn" +
    "LFwnJyArIHJlZ2lvbiArICdcJykiPicgKyAoaXNTYXZlZCA/ICdzYXZlZCcgOiAnc2F2ZScpICsg" +
    "JzwvYnV0dG9uPic7CiAgICBodG1sICs9ICc8L2Rpdj48L2Rpdj4nOwogICAgaHRtbCArPSAnPGRp" +
    "diBjbGFzcz0iZXhwYW5kLWJveCIgaWQ9InNyYy0nICsgaSArICciPicgKyAobGlua3NIdG1sIHx8" +
    "ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCkiPk5vIHNvdXJj" +
    "ZSBsaW5rcy48L2Rpdj4nKSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iaGlu" +
    "dC1ib3giIGlkPSJoaW50LScgKyBpICsgJyI+JyArICh0LmZvcm1hdEhpbnQgfHwgJycpICsgJzwv" +
    "ZGl2Pic7CiAgICBodG1sICs9ICc8L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9" +
    "CgpmdW5jdGlvbiB0b2dnbGVCb3goaWQpIHsKICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50" +
    "QnlJZChpZCk7CiAgaWYgKGVsKSBlbC5zdHlsZS5kaXNwbGF5ID0gZWwuc3R5bGUuZGlzcGxheSA9" +
    "PT0gJ2Jsb2NrJyA/ICdub25lJyA6ICdibG9jayc7Cn0KCmZ1bmN0aW9uIGRvU2F2ZShpLCByZWdp" +
    "b24pIHsKICB2YXIgdCA9IHRyZW5kc1tpXTsKICBmb3IgKHZhciBzID0gMDsgcyA8IHNhdmVkLmxl" +
    "bmd0aDsgcysrKSB7IGlmIChzYXZlZFtzXS5uYW1lID09PSB0Lm5hbWUpIHJldHVybjsgfQogIHNh" +
    "dmVkLnB1c2goeyBuYW1lOiB0Lm5hbWUsIGRlc2M6IHQuZGVzYywgdGFnOiAnJyB9KTsKICBkb2N1" +
    "bWVudC5nZXRFbGVtZW50QnlJZCgnc2ItJyArIGkpLnRleHRDb250ZW50ID0gJ3NhdmVkJzsKICBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2ItJyArIGkpLmNsYXNzTGlzdC5hZGQoJ3NhdmVkJyk7" +
    "CiAgcmVuZGVyU2F2ZWQoKTsKICBmZXRjaCgnL2FyY2hpdmUvc2F2ZScsIHsgbWV0aG9kOiAnUE9T" +
    "VCcsIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBib2R5" +
    "OiBKU09OLnN0cmluZ2lmeSh7IG5hbWU6IHQubmFtZSwgZGVzYzogdC5kZXNjLCBtb21lbnR1bTog" +
    "dC5tb21lbnR1bSwgc2lnbmFsczogdC5zaWduYWxzLCBzb3VyY2VfbGFiZWxzOiB0LnNvdXJjZUxh" +
    "YmVscyB8fCBbXSwgc291cmNlX2xpbmtzOiB0LnNvdXJjZUxpbmtzIHx8IFtdLCBmb3JtYXRfaGlu" +
    "dDogdC5mb3JtYXRIaW50LCB0YWc6ICcnLCByZWdpb246IHJlZ2lvbiB8fCAnbmwnIH0pIH0pCiAg" +
    "LmNhdGNoKGZ1bmN0aW9uKGUpIHsgY29uc29sZS5lcnJvcignYXJjaGl2ZSBzYXZlIGZhaWxlZCcs" +
    "IGUpOyB9KTsKfQoKZnVuY3Rpb24gcmVuZGVyU2F2ZWQoKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQu" +
    "Z2V0RWxlbWVudEJ5SWQoJ3NhdmVkLWxpc3QnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgn" +
    "Z2VuLXJvdycpLnN0eWxlLmRpc3BsYXkgPSBzYXZlZC5sZW5ndGggPyAnJyA6ICdub25lJzsKICBp" +
    "ZiAoIXNhdmVkLmxlbmd0aCkgeyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPk5v" +
    "IHNhdmVkIHRyZW5kcyB5ZXQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIGh0bWwgPSAnJzsKICBm" +
    "b3IgKHZhciBpID0gMDsgaSA8IHNhdmVkLmxlbmd0aDsgaSsrKSB7CiAgICB2YXIgdCA9IHNhdmVk" +
    "W2ldOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0ic2F2ZWQtaXRlbSI+PGRpdiBjbGFzcz0ic2F2" +
    "ZWQtbmFtZSI+JyArIHQubmFtZSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBzdHlsZT0i" +
    "ZGlzcGxheTpmbGV4O2dhcDo2cHg7YWxpZ24taXRlbXM6Y2VudGVyIj48aW5wdXQgY2xhc3M9InRh" +
    "Zy1pbnB1dCIgcGxhY2Vob2xkZXI9InRhZy4uLiIgdmFsdWU9IicgKyB0LnRhZyArICciIG9uaW5w" +
    "dXQ9InNhdmVkWycgKyBpICsgJ10udGFnPXRoaXMudmFsdWUiLz4nOwogICAgaHRtbCArPSAnPHNw" +
    "YW4gc3R5bGU9ImN1cnNvcjpwb2ludGVyO2ZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dGVk" +
    "KSIgb25jbGljaz0ic2F2ZWQuc3BsaWNlKCcgKyBpICsgJywxKTtyZW5kZXJTYXZlZCgpIj4mI3gy" +
    "NzE1Ozwvc3Bhbj48L2Rpdj48L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9Cgp2" +
    "YXIgZ2VuZXJhdGVkRm9ybWF0cyA9IFtdOwoKZnVuY3Rpb24gZ2VuZXJhdGVGb3JtYXRzKCkgewog" +
    "IGlmICghc2F2ZWQubGVuZ3RoKSByZXR1cm47CiAgc3dpdGNoVGFiKCdmb3JtYXRzJyk7CiAgZG9j" +
    "dW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbCcpLnN0eWxlLmRpc3BsYXkgPSAnbm9uZSc7" +
    "CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9ICc8" +
    "ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlJlYWRpbmcgeW91" +
    "ciBjYXRhbG9ndWUgJmFtcDsgZ2VuZXJhdGluZyBpZGVhcy4uLjwvZGl2Pic7CiAgZmV0Y2goJy9n" +
    "ZW5lcmF0ZS1mb3JtYXRzJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdD" +
    "b250ZW50LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5n" +
    "aWZ5KHsgdHJlbmRzOiBzYXZlZCB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4g" +
    "ci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24ocmVzdWx0KSB7CiAgICBpZiAocmVzdWx0LmVy" +
    "cm9yKSB0aHJvdyBuZXcgRXJyb3IocmVzdWx0LmVycm9yKTsKICAgIHZhciBmb3JtYXRzID0gcmVz" +
    "dWx0LmZvcm1hdHMgfHwgW107CiAgICBpZiAoIWZvcm1hdHMubGVuZ3RoKSB0aHJvdyBuZXcgRXJy" +
    "b3IoJ05vIGZvcm1hdHMgcmV0dXJuZWQnKTsKICAgIGdlbmVyYXRlZEZvcm1hdHMgPSBmb3JtYXRz" +
    "OwogICAgdmFyIGh0bWwgPSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgZm9ybWF0cy5sZW5n" +
    "dGg7IGkrKykgewogICAgICB2YXIgZiA9IGZvcm1hdHNbaV07CiAgICAgIGh0bWwgKz0gJzxkaXYg" +
    "Y2xhc3M9ImZvcm1hdC1pdGVtIj4nOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQt" +
    "dGl0bGUiPicgKyBmLnRpdGxlICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9" +
    "ImZvcm1hdC1sb2dsaW5lIj4nICsgZi5sb2dsaW5lICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0g" +
    "JzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6NnB4O2ZsZXgtd3JhcDp3cmFwO21hcmdpbi10" +
    "b3A6NXB4Ij4nOwogICAgICBodG1sICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIGYuY2hhbm5l" +
    "bCArICc8L3NwYW4+JzsKICAgICAgaHRtbCArPSAnPHNwYW4gY2xhc3M9ImNoaXAiPicgKyBmLnRy" +
    "ZW5kQmFzaXMgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICAgIGlmIChm" +
    "Lmhvb2spIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1hdC1ob29rIj4iJyArIGYuaG9vayArICci" +
    "PC9kaXY+JzsKICAgICAgaWYgKGYud2h5TmV3KSBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250LXNp" +
    "emU6MTFweDtjb2xvcjp2YXIoLS1ncmVlbik7bWFyZ2luLXRvcDo1cHg7Zm9udC1zdHlsZTppdGFs" +
    "aWMiPicgKyBmLndoeU5ldyArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8YnV0dG9uIGNsYXNz" +
    "PSJkZXYtYnRuIiBvbmNsaWNrPSJzdGFydERldmVsb3BtZW50KCcgKyBpICsgJykiPiYjOTY2MDsg" +
    "RGV2ZWxvcCB0aGlzIGZvcm1hdDwvYnV0dG9uPic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAg" +
    "ICB9CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZm9ybWF0cy1saXN0JykuaW5uZXJIVE1M" +
    "ID0gaHRtbDsKICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7CiAgICBzaG93RXJyKCdGb3JtYXQg" +
    "Z2VuZXJhdGlvbiBmYWlsZWQ6ICcgKyBlLm1lc3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVu" +
    "dEJ5SWQoJ2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+RmFp" +
    "bGVkLjwvZGl2Pic7CiAgfSk7Cn0KCi8vIOKUgOKUgCBGb3JtYXQgZGV2ZWxvcG1lbnQgY2hhdCDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKdmFyIGRldk1lc3NhZ2VzID0g" +
    "W107CnZhciBkZXZGb3JtYXQgPSBudWxsOwoKZnVuY3Rpb24gc3RhcnREZXZlbG9wbWVudChpKSB7" +
    "CiAgZGV2Rm9ybWF0ID0gZ2VuZXJhdGVkRm9ybWF0c1tpXSB8fCBudWxsOwogIGRldk1lc3NhZ2Vz" +
    "ID0gW107CiAgdmFyIHBhbmVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbCcp" +
    "OwogIHZhciBjaGF0ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1jaGF0Jyk7CiAgcGFu" +
    "ZWwuc3R5bGUuZGlzcGxheSA9ICdmbGV4JzsKICBjaGF0LmlubmVySFRNTCA9ICc8ZGl2IGNsYXNz" +
    "PSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlN0YXJ0aW5nIGRldmVsb3BtZW50" +
    "IHNlc3Npb24uLi48L2Rpdj4nOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtcGFuZWwt" +
    "c3VidGl0bGUnKS50ZXh0Q29udGVudCA9ICdEZXZlbG9waW5nOiAnICsgKGRldkZvcm1hdCA/IGRl" +
    "dkZvcm1hdC50aXRsZSA6ICdGb3JtYXQgaWRlYScpOwogIHBhbmVsLnNjcm9sbEludG9WaWV3KHsg" +
    "YmVoYXZpb3I6ICdzbW9vdGgnLCBibG9jazogJ3N0YXJ0JyB9KTsKCiAgLy8gT3BlbmluZyBtZXNz" +
    "YWdlIGZyb20gdGhlIEFJCiAgZmV0Y2goJy9kZXZlbG9wJywgewogICAgbWV0aG9kOiAnUE9TVCcs" +
    "CiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAg" +
    "IGJvZHk6IEpTT04uc3RyaW5naWZ5KHsKICAgICAgZm9ybWF0X2lkZWE6IGRldkZvcm1hdCwKICAg" +
    "ICAgdHJlbmRzOiBzYXZlZCwKICAgICAgbWVzc2FnZXM6IFt7CiAgICAgICAgcm9sZTogJ3VzZXIn" +
    "LAogICAgICAgIGNvbnRlbnQ6ICdJIHdhbnQgdG8gZGV2ZWxvcCB0aGlzIGZvcm1hdCBpZGVhLiBI" +
    "ZXJlIGlzIHdoYXQgd2UgaGF2ZSBzbyBmYXI6IFRpdGxlOiAiJyArIChkZXZGb3JtYXQgPyBkZXZG" +
    "b3JtYXQudGl0bGUgOiAnJykgKyAnIi4gTG9nbGluZTogJyArIChkZXZGb3JtYXQgPyBkZXZGb3Jt" +
    "YXQubG9nbGluZSA6ICcnKSArICcuIFBsZWFzZSBzdGFydCBvdXIgZGV2ZWxvcG1lbnQgc2Vzc2lv" +
    "bi4nCiAgICAgIH1dCiAgICB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5q" +
    "c29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgaWYgKGQuZXJyb3IpIHRocm93IG5l" +
    "dyBFcnJvcihkLmVycm9yKTsKICAgIGRldk1lc3NhZ2VzID0gWwogICAgICB7IHJvbGU6ICd1c2Vy" +
    "JywgY29udGVudDogJ0kgd2FudCB0byBkZXZlbG9wIHRoaXMgZm9ybWF0IGlkZWEuIEhlcmUgaXMg" +
    "d2hhdCB3ZSBoYXZlIHNvIGZhcjogVGl0bGU6ICInICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC50" +
    "aXRsZSA6ICcnKSArICciLiBMb2dsaW5lOiAnICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC5sb2ds" +
    "aW5lIDogJycpICsgJy4gUGxlYXNlIHN0YXJ0IG91ciBkZXZlbG9wbWVudCBzZXNzaW9uLicgfSwK" +
    "ICAgICAgeyByb2xlOiAnYXNzaXN0YW50JywgY29udGVudDogZC5yZXNwb25zZSB9CiAgICBdOwog" +
    "ICAgcmVuZGVyRGV2Q2hhdCgpOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAgIGNoYXQu" +
    "aW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5Db3VsZCBub3Qgc3RhcnQgc2Vzc2lvbjog" +
    "JyArIGUubWVzc2FnZSArICc8L2Rpdj4nOwogIH0pOwp9CgpmdW5jdGlvbiBzZW5kRGV2TWVzc2Fn" +
    "ZSgpIHsKICB2YXIgaW5wdXQgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LWlucHV0Jyk7" +
    "CiAgdmFyIG1zZyA9IGlucHV0LnZhbHVlLnRyaW0oKTsKICBpZiAoIW1zZyB8fCAhZGV2Rm9ybWF0" +
    "KSByZXR1cm47CiAgaW5wdXQudmFsdWUgPSAnJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgn" +
    "ZGV2LXNlbmQnKS5kaXNhYmxlZCA9IHRydWU7CgogIGRldk1lc3NhZ2VzLnB1c2goeyByb2xlOiAn" +
    "dXNlcicsIGNvbnRlbnQ6IG1zZyB9KTsKICByZW5kZXJEZXZDaGF0KCk7CgogIGZldGNoKCcvZGV2" +
    "ZWxvcCcsIHsKICAgIG1ldGhvZDogJ1BPU1QnLAogICAgaGVhZGVyczogeyAnQ29udGVudC1UeXBl" +
    "JzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sCiAgICBib2R5OiBKU09OLnN0cmluZ2lmeSh7CiAgICAg" +
    "IGZvcm1hdF9pZGVhOiBkZXZGb3JtYXQsCiAgICAgIHRyZW5kczogc2F2ZWQsCiAgICAgIG1lc3Nh" +
    "Z2VzOiBkZXZNZXNzYWdlcwogICAgfSkKICB9KQogIC50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJu" +
    "IHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0aW9uKGQpIHsKICAgIGlmIChkLmVycm9yKSB0aHJv" +
    "dyBuZXcgRXJyb3IoZC5lcnJvcik7CiAgICBkZXZNZXNzYWdlcy5wdXNoKHsgcm9sZTogJ2Fzc2lz" +
    "dGFudCcsIGNvbnRlbnQ6IGQucmVzcG9uc2UgfSk7CiAgICByZW5kZXJEZXZDaGF0KCk7CiAgICBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXNlbmQnKS5kaXNhYmxlZCA9IGZhbHNlOwogICAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1pbnB1dCcpLmZvY3VzKCk7CiAgfSkKICAuY2F0" +
    "Y2goZnVuY3Rpb24oZSkgewogICAgZGV2TWVzc2FnZXMucHVzaCh7IHJvbGU6ICdhc3Npc3RhbnQn" +
    "LCBjb250ZW50OiAnU29ycnksIHNvbWV0aGluZyB3ZW50IHdyb25nOiAnICsgZS5tZXNzYWdlIH0p" +
    "OwogICAgcmVuZGVyRGV2Q2hhdCgpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1z" +
    "ZW5kJykuZGlzYWJsZWQgPSBmYWxzZTsKICB9KTsKfQoKZnVuY3Rpb24gcmVuZGVyRGV2Q2hhdCgp" +
    "IHsKICB2YXIgY2hhdCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtY2hhdCcpOwogIHZh" +
    "ciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBkZXZNZXNzYWdlcy5sZW5ndGg7IGkr" +
    "KykgewogICAgdmFyIG0gPSBkZXZNZXNzYWdlc1tpXTsKICAgIHZhciBjbHMgPSBtLnJvbGUgPT09" +
    "ICdhc3Npc3RhbnQnID8gJ2FpJyA6ICd1c2VyJzsKICAgIHZhciB0ZXh0ID0gbS5jb250ZW50LnJl" +
    "cGxhY2UoL1xuL2csICc8YnI+Jyk7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJkZXYtbXNnICcg" +
    "KyBjbHMgKyAnIj4nICsgdGV4dCArICc8L2Rpdj4nOwogIH0KICBjaGF0LmlubmVySFRNTCA9IGh0" +
    "bWw7CiAgY2hhdC5zY3JvbGxUb3AgPSBjaGF0LnNjcm9sbEhlaWdodDsKfQoKZnVuY3Rpb24gbG9h" +
    "ZFJlc2VhcmNoKCkgewogIGZldGNoKCcvcmVzZWFyY2gnKS50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0" +
    "dXJuIHIuanNvbigpOyB9KS50aGVuKGZ1bmN0aW9uKGQpIHsgcmVuZGVyUmVzZWFyY2goZC5pdGVt" +
    "cyB8fCBbXSk7IH0pCiAgLmNhdGNoKGZ1bmN0aW9uKCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJ" +
    "ZCgncmVzZWFyY2gtZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Q291bGQg" +
    "bm90IGxvYWQgcmVzZWFyY2guPC9kaXY+JzsgfSk7Cn0KCmZ1bmN0aW9uIHJlbmRlclJlc2VhcmNo" +
    "KGl0ZW1zKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Jlc2VhcmNoLWZl" +
    "ZWQnKTsKICBpZiAoIWl0ZW1zLmxlbmd0aCkgeyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0i" +
    "ZW1wdHkiPk5vIHJlc2VhcmNoIGl0ZW1zIGZvdW5kLjwvZGl2Pic7IHJldHVybjsgfQogIHZhciB0" +
    "eXBlTWFwID0geyByZXNlYXJjaDogJ1Jlc2VhcmNoJywgY3VsdHVyZTogJ0N1bHR1cmUnLCB0cmVu" +
    "ZHM6ICdUcmVuZHMnIH07IHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBpdGVt" +
    "cy5sZW5ndGg7IGkrKykgewogICAgdmFyIGl0ZW0gPSBpdGVtc1tpXTsKICAgIGh0bWwgKz0gJzxk" +
    "aXYgY2xhc3M9InJlc2VhcmNoLWl0ZW0iPjxkaXYgY2xhc3M9InJlc2VhcmNoLXRpdGxlIj48YSBo" +
    "cmVmPSInICsgaXRlbS51cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+JyArIGl0ZW0udGl0bGUgKyAn" +
    "PC9hPjwvZGl2Pic7CiAgICBpZiAoaXRlbS5kZXNjKSBodG1sICs9ICc8ZGl2IGNsYXNzPSJyZXNl" +
    "YXJjaC1kZXNjIj4nICsgaXRlbS5kZXNjICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNs" +
    "YXNzPSJyZXNlYXJjaC1tZXRhIj48c3BhbiBjbGFzcz0ici1zcmMiPicgKyBpdGVtLnNvdXJjZSAr" +
    "ICc8L3NwYW4+PHNwYW4gY2xhc3M9InItdHlwZSI+JyArICh0eXBlTWFwW2l0ZW0udHlwZV0gfHwg" +
    "aXRlbS50eXBlKSArICc8L3NwYW4+PC9kaXY+PC9kaXY+JzsKICB9CiAgZWwuaW5uZXJIVE1MID0g" +
    "aHRtbDsKfQoKZnVuY3Rpb24gZG9BcmNoaXZlU2VhcmNoKCkgewogIHZhciBxdWVyeSA9IGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLXNlYXJjaC1pbnB1dCcpLnZhbHVlLnRyaW0oKTsK" +
    "ICBpZiAoIXF1ZXJ5KSByZXR1cm47CiAgdmFyIHJlc3VsdHNFbCA9IGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdzZWFyY2gtcmVzdWx0cycpOwogIHJlc3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBz" +
    "dHlsZT0iZm9udC1zaXplOjEycHg7Y29sb3I6dmFyKC0tbXV0ZWQpIj48c3BhbiBjbGFzcz0ibG9h" +
    "ZGVyIj48L3NwYW4+U2VhcmNoaW5nIGFyY2hpdmUuLi48L2Rpdj4nOwoKICBmZXRjaCgnL2FyY2hp" +
    "dmUvc2VhcmNoJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50" +
    "LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsg" +
    "cXVlcnk6IHF1ZXJ5IH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24o" +
    "KTsgfSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3IEVy" +
    "cm9yKGQuZXJyb3IpOwogICAgdmFyIHJlc3VsdHMgPSBkLnJlc3VsdHMgfHwgW107CiAgICBpZiAo" +
    "IXJlc3VsdHMubGVuZ3RoKSB7CiAgICAgIHJlc3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBzdHls" +
    "ZT0iZm9udC1zaXplOjEycHg7Y29sb3I6dmFyKC0tbXV0ZWQpO3BhZGRpbmc6OHB4IDAiPk5vIHJl" +
    "bGV2YW50IHRyZW5kcyBmb3VuZCBmb3IgIicgKyBxdWVyeSArICciLjwvZGl2Pic7CiAgICAgIHJl" +
    "dHVybjsKICAgIH0KICAgIHZhciBtY01hcCA9IHsgcmlzaW5nOiAnYi1yaXNpbmcnLCBlbWVyZ2lu" +
    "ZzogJ2ItZW1lcmdpbmcnLCBlc3RhYmxpc2hlZDogJ2ItZXN0YWJsaXNoZWQnLCBzaGlmdGluZzog" +
    "J2Itc2hpZnRpbmcnIH07CiAgICB2YXIgaHRtbCA9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTBw" +
    "eDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJhbnNmb3JtOnVwcGVy" +
    "Y2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9tOjEwcHgiPicgKyByZXN1bHRz" +
    "Lmxlbmd0aCArICcgcmVsZXZhbnQgdHJlbmRzIGZvdW5kPC9kaXY+JzsKICAgIGZvciAodmFyIGkg" +
    "PSAwOyBpIDwgcmVzdWx0cy5sZW5ndGg7IGkrKykgewogICAgICB2YXIgdCA9IHJlc3VsdHNbaV07" +
    "CiAgICAgIHZhciBtYyA9IG1jTWFwW3QubW9tZW50dW1dIHx8ICdiLWVtZXJnaW5nJzsKICAgICAg" +
    "aHRtbCArPSAnPGRpdiBzdHlsZT0icGFkZGluZzoxMnB4IDA7Ym9yZGVyLWJvdHRvbToxcHggc29s" +
    "aWQgdmFyKC0tYm9yZGVyKSI+JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZGlzcGxheTpm" +
    "bGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6OHB4O21hcmdpbi1ib3R0b206NXB4Ij4nOwogICAg" +
    "ICBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTNweDtmb250LXdlaWdodDo2MDA7Y29s" +
    "b3I6I2ZmZiI+JyArIHQubmFtZSArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8c3BhbiBjbGFz" +
    "cz0iYmFkZ2UgJyArIG1jICsgJyI+JyArICh0Lm1vbWVudHVtIHx8ICcnKSArICc8L3NwYW4+JzsK" +
    "ICAgICAgaHRtbCArPSAnPHNwYW4gc3R5bGU9ImZvbnQtc2l6ZToxMHB4O2NvbG9yOnZhcigtLW11" +
    "dGVkKSI+JyArIHQuc2F2ZWRfYXQuc2xpY2UoMCwxMCkgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwg" +
    "Kz0gJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2Nv" +
    "bG9yOnZhcigtLW11dGVkKTtsaW5lLWhlaWdodDoxLjU7bWFyZ2luLWJvdHRvbTo1cHgiPicgKyAo" +
    "dC5kZXNjIHx8ICcnKSArICc8L2Rpdj4nOwogICAgICBpZiAodC5yZWxldmFuY2UpIGh0bWwgKz0g" +
    "JzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLWFjY2VudDIpO2ZvbnQtc3R5" +
    "bGU6aXRhbGljIj4nICsgdC5yZWxldmFuY2UgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPC9k" +
    "aXY+JzsKICAgIH0KICAgIHJlc3VsdHNFbC5pbm5lckhUTUwgPSBodG1sOwogIH0pCiAgLmNhdGNo" +
    "KGZ1bmN0aW9uKGUpIHsKICAgIHJlc3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0iZm9u" +
    "dC1zaXplOjEycHg7Y29sb3I6I2ZjYTVhNSI+U2VhcmNoIGZhaWxlZDogJyArIGUubWVzc2FnZSAr" +
    "ICc8L2Rpdj4nOwogIH0pOwp9CgpmdW5jdGlvbiBsb2FkQXJjaGl2ZSgpIHsKICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5" +
    "IiBzdHlsZT0icGFkZGluZzoxcmVtIDAiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj48L2Rp" +
    "dj4nOwogIGZldGNoKCcvYXJjaGl2ZS9kYXRlcycpLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4g" +
    "ci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgaWYgKCFkLmRhdGVzIHx8ICFk" +
    "LmRhdGVzLmxlbmd0aCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0JykuaW5u" +
    "ZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5IiBzdHlsZT0icGFkZGluZzoxcmVtIDA7Zm9udC1z" +
    "aXplOjExcHgiPk5vIGFyY2hpdmVkIHRyZW5kcyB5ZXQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgICB2" +
    "YXIgaHRtbCA9ICcnOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCBkLmRhdGVzLmxlbmd0aDsgaSsr" +
    "KSB7IGh0bWwgKz0gJzxkaXYgY2xhc3M9ImRhdGUtaXRlbSIgb25jbGljaz0ibG9hZERhdGUoXCcn" +
    "ICsgZC5kYXRlc1tpXS5kYXRlICsgJ1wnLHRoaXMpIj4nICsgZC5kYXRlc1tpXS5kYXRlICsgJzxz" +
    "cGFuIGNsYXNzPSJkYXRlLWNvdW50Ij4nICsgZC5kYXRlc1tpXS5jb3VudCArICc8L3NwYW4+PC9k" +
    "aXY+JzsgfQogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RhdGUtbGlzdCcpLmlubmVySFRN" +
    "TCA9IGh0bWw7CiAgICB2YXIgZmlyc3QgPSBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKCcuZGF0ZS1p" +
    "dGVtJyk7IGlmIChmaXJzdCkgZmlyc3QuY2xpY2soKTsKICB9KQogIC5jYXRjaChmdW5jdGlvbihl" +
    "KSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLWVycicpLmlubmVySFRNTCA9ICc8" +
    "ZGl2IGNsYXNzPSJlcnJib3giPkNvdWxkIG5vdCBsb2FkIGFyY2hpdmU6ICcgKyBlLm1lc3NhZ2Ug" +
    "KyAnPC9kaXY+JzsgfSk7Cn0KCmZ1bmN0aW9uIGxvYWREYXRlKGRhdGUsIGVsKSB7CiAgdmFyIGl0" +
    "ZW1zID0gZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgnLmRhdGUtaXRlbScpOyBmb3IgKHZhciBp" +
    "ID0gMDsgaSA8IGl0ZW1zLmxlbmd0aDsgaSsrKSBpdGVtc1tpXS5jbGFzc0xpc3QucmVtb3ZlKCdh" +
    "Y3RpdmUnKTsKICBlbC5jbGFzc0xpc3QuYWRkKCdhY3RpdmUnKTsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnYXJjaGl2ZS1oZWFkaW5nJykudGV4dENvbnRlbnQgPSAnU2F2ZWQgb24gJyArIGRh" +
    "dGU7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtY29udGVudCcpLmlubmVySFRN" +
    "TCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPjwvZGl2" +
    "Pic7CiAgZmV0Y2goJy9hcmNoaXZlL2J5LWRhdGU/ZGF0ZT0nICsgZW5jb2RlVVJJQ29tcG9uZW50" +
    "KGRhdGUpKS50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1" +
    "bmN0aW9uKGQpIHsKICAgIGlmICghZC50cmVuZHMgfHwgIWQudHJlbmRzLmxlbmd0aCkgeyBkb2N1" +
    "bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYg" +
    "Y2xhc3M9ImVtcHR5Ij5ObyB0cmVuZHMgZm9yIHRoaXMgZGF0ZS48L2Rpdj4nOyByZXR1cm47IH0K" +
    "ICAgIHZhciBodG1sID0gJyc7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IGQudHJlbmRzLmxlbmd0" +
    "aDsgaSsrKSB7CiAgICAgIHZhciB0ID0gZC50cmVuZHNbaV07CiAgICAgIHZhciBtY01hcCA9IHsg" +
    "cmlzaW5nOiAnYi1yaXNpbmcnLCBlbWVyZ2luZzogJ2ItZW1lcmdpbmcnLCBlc3RhYmxpc2hlZDog" +
    "J2ItZXN0YWJsaXNoZWQnLCBzaGlmdGluZzogJ2Itc2hpZnRpbmcnIH07CiAgICAgIHZhciBtYyA9" +
    "IG1jTWFwW3QubW9tZW50dW1dIHx8ICdiLWVtZXJnaW5nJzsgdmFyIGxpbmtzID0gW107CiAgICAg" +
    "IHRyeSB7IGxpbmtzID0gSlNPTi5wYXJzZSh0LnNvdXJjZV9saW5rcyB8fCAnW10nKTsgfSBjYXRj" +
    "aChlKSB7fQogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJhcmNoLWl0ZW0iPjxkaXYgc3R5bGU9" +
    "ImRpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjhweDttYXJnaW4tYm90dG9tOjNw" +
    "eCI+PGRpdiBjbGFzcz0iYXJjaC1uYW1lIj4nICsgdC5uYW1lICsgJzwvZGl2PjxzcGFuIGNsYXNz" +
    "PSJiYWRnZSAnICsgbWMgKyAnIj4nICsgKHQubW9tZW50dW0gfHwgJycpICsgJzwvc3Bhbj48L2Rp" +
    "dj4nOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJhcmNoLW1ldGEiPicgKyB0LnNhdmVkX2F0" +
    "ICsgKHQucmVnaW9uID8gJyAmbWlkZG90OyAnICsgdC5yZWdpb24udG9VcHBlckNhc2UoKSA6ICcn" +
    "KSArICh0LnRhZyA/ICcgJm1pZGRvdDsgJyArIHQudGFnIDogJycpICsgJzwvZGl2Pic7CiAgICAg" +
    "IGh0bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gtZGVzYyI+JyArICh0LmRlc2MgfHwgJycpICsgJzwv" +
    "ZGl2Pic7CiAgICAgIGZvciAodmFyIGwgPSAwOyBsIDwgbGlua3MubGVuZ3RoOyBsKyspIHsgaHRt" +
    "bCArPSAnPGEgY2xhc3M9ImFyY2gtbGluayIgaHJlZj0iJyArIGxpbmtzW2xdLnVybCArICciIHRh" +
    "cmdldD0iX2JsYW5rIj4nICsgbGlua3NbbF0udGl0bGUgKyAnPC9hPic7IH0KICAgICAgaHRtbCAr" +
    "PSAnPC9kaXY+JzsKICAgIH0KICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLWNv" +
    "bnRlbnQnKS5pbm5lckhUTUwgPSBodG1sOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKCkgeyBkb2N1" +
    "bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYg" +
    "Y2xhc3M9ImVtcHR5Ij5Db3VsZCBub3QgbG9hZC48L2Rpdj4nOyB9KTsKfQo8L3NjcmlwdD4KPC9i" +
    "b2R5Pgo8L2h0bWw+Cg=="
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
