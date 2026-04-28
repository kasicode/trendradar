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
    "ZWwgeyBiYWNrZ3JvdW5kOiB2YXIoLS1jYXJkKTsgYm9yZGVyOiAxcHggc29saWQgdmFyKC0tYm9y" +
    "ZGVyKTsgYm9yZGVyLXJhZGl1czogMTJweDsgbWFyZ2luLXRvcDogMTZweDsgb3ZlcmZsb3c6IGhp" +
    "ZGRlbjsgZGlzcGxheTogbm9uZTsgfQouZGV2LXBhbmVsLWhlYWRlciB7IHBhZGRpbmc6IDEycHgg" +
    "MTZweDsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLmRldi1wYW5l" +
    "bC10aXRsZSB7IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IDYwMDsgY29sb3I6IHZhcigt" +
    "LWdyZWVuKTsgfQouZGV2LXBhbmVsLXN1YnRpdGxlIHsgZm9udC1zaXplOiAxMXB4OyBjb2xvcjog" +
    "dmFyKC0tbXV0ZWQpOyBtYXJnaW4tdG9wOiAycHg7IH0KLmRldi1jaGF0IHsgaGVpZ2h0OiAzNjBw" +
    "eDsgb3ZlcmZsb3cteTogYXV0bzsgcGFkZGluZzogMTZweDsgZGlzcGxheTogZmxleDsgZmxleC1k" +
    "aXJlY3Rpb246IGNvbHVtbjsgZ2FwOiAxMHB4OyB9Ci5kZXYtbXNnIHsgbWF4LXdpZHRoOiA4NSU7" +
    "IHBhZGRpbmc6IDEwcHggMTRweDsgYm9yZGVyLXJhZGl1czogMTBweDsgZm9udC1zaXplOiAxM3B4" +
    "OyBsaW5lLWhlaWdodDogMS42OyB9Ci5kZXYtbXNnLmFpIHsgYmFja2dyb3VuZDogdmFyKC0tY2Fy" +
    "ZDIpOyBjb2xvcjogdmFyKC0tdGV4dCk7IGFsaWduLXNlbGY6IGZsZXgtc3RhcnQ7IGJvcmRlci1i" +
    "b3R0b20tbGVmdC1yYWRpdXM6IDNweDsgfQouZGV2LW1zZy51c2VyIHsgYmFja2dyb3VuZDogcmdi" +
    "YSgxMjQsNTgsMjM3LDAuMTUpOyBjb2xvcjogdmFyKC0tdGV4dCk7IGFsaWduLXNlbGY6IGZsZXgt" +
    "ZW5kOyBib3JkZXItYm90dG9tLXJpZ2h0LXJhZGl1czogM3B4OyBib3JkZXI6IDFweCBzb2xpZCBy" +
    "Z2JhKDEyNCw1OCwyMzcsMC4yNSk7IH0KLmRldi1pbnB1dC1yb3cgeyBkaXNwbGF5OiBmbGV4OyBn" +
    "YXA6IDhweDsgcGFkZGluZzogMTJweCAxNnB4OyBib3JkZXItdG9wOiAxcHggc29saWQgdmFyKC0t" +
    "Ym9yZGVyKTsgfQouZGV2LWlucHV0IHsgZmxleDogMTsgZm9udC1zaXplOiAxM3B4OyBwYWRkaW5n" +
    "OiA5cHggMTRweDsgYm9yZGVyLXJhZGl1czogOHB4OyBib3JkZXI6IDFweCBzb2xpZCB2YXIoLS1i" +
    "b3JkZXIyKTsgYmFja2dyb3VuZDogcmdiYSgyNTUsMjU1LDI1NSwwLjA0KTsgY29sb3I6IHZhcigt" +
    "LXRleHQpOyBvdXRsaW5lOiBub25lOyBmb250LWZhbWlseTogaW5oZXJpdDsgfQouZGV2LWlucHV0" +
    "OjpwbGFjZWhvbGRlciB7IGNvbG9yOiByZ2JhKDI1NSwyNTUsMjU1LDAuMik7IH0KLmRldi1zZW5k" +
    "IHsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogNjAwOyBwYWRkaW5nOiA5cHggMTZweDsg" +
    "Ym9yZGVyLXJhZGl1czogOHB4OyBib3JkZXI6IG5vbmU7IGJhY2tncm91bmQ6IGxpbmVhci1ncmFk" +
    "aWVudCgxMzVkZWcsIHZhcigtLWFjY2VudCksIHZhcigtLWFjY2VudDIpKTsgY29sb3I6ICNmZmY7" +
    "IGN1cnNvcjogcG9pbnRlcjsgd2hpdGUtc3BhY2U6IG5vd3JhcDsgfQouZGV2LXNlbmQ6ZGlzYWJs" +
    "ZWQgeyBvcGFjaXR5OiAwLjQ7IGN1cnNvcjogbm90LWFsbG93ZWQ7IH0KCi5hcmNoaXZlLWxheW91" +
    "dCB7IGRpc3BsYXk6IGdyaWQ7IGdyaWQtdGVtcGxhdGUtY29sdW1uczogMTcwcHggMWZyOyBnYXA6" +
    "IDIwcHg7IH0KQG1lZGlhIChtYXgtd2lkdGg6IDcwMHB4KSB7IC5hcmNoaXZlLWxheW91dCB7IGdy" +
    "aWQtdGVtcGxhdGUtY29sdW1uczogMWZyOyB9IH0KLmRhdGUtaXRlbSB7IHBhZGRpbmc6IDdweCAx" +
    "MHB4OyBib3JkZXItcmFkaXVzOiA4cHg7IGN1cnNvcjogcG9pbnRlcjsgZm9udC1zaXplOiAxMnB4" +
    "OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBtYXJnaW4tYm90dG9tOiAycHg7IGRpc3BsYXk6IGZsZXg7" +
    "IGFsaWduLWl0ZW1zOiBjZW50ZXI7IGp1c3RpZnktY29udGVudDogc3BhY2UtYmV0d2VlbjsgdHJh" +
    "bnNpdGlvbjogYWxsIDAuMTVzOyB9Ci5kYXRlLWl0ZW06aG92ZXIgeyBiYWNrZ3JvdW5kOiByZ2Jh" +
    "KDI1NSwyNTUsMjU1LDAuMDUpOyBjb2xvcjogdmFyKC0tdGV4dCk7IH0KLmRhdGUtaXRlbS5hY3Rp" +
    "dmUgeyBiYWNrZ3JvdW5kOiB2YXIoLS1nbG93KTsgY29sb3I6ICNmZmY7IH0KLmRhdGUtY291bnQg" +
    "eyBmb250LXNpemU6IDEwcHg7IG9wYWNpdHk6IDAuNTsgfQouYXJjaC1pdGVtIHsgcGFkZGluZzog" +
    "MTJweCAwOyBib3JkZXItYm90dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgfQouYXJjaC1p" +
    "dGVtOmxhc3QtY2hpbGQgeyBib3JkZXItYm90dG9tOiBub25lOyB9Ci5hcmNoLW5hbWUgeyBmb250" +
    "LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiA2MDA7IGNvbG9yOiAjZmZmOyB9Ci5hcmNoLW1ldGEg" +
    "eyBmb250LXNpemU6IDEwcHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IG1hcmdpbjogM3B4IDAgNXB4" +
    "OyB9Ci5hcmNoLWRlc2MgeyBmb250LXNpemU6IDEycHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGxp" +
    "bmUtaGVpZ2h0OiAxLjU7IH0KLmFyY2gtbGluayB7IGZvbnQtc2l6ZTogMTBweDsgY29sb3I6IHZh" +
    "cigtLWFjY2VudDIpOyB0ZXh0LWRlY29yYXRpb246IG5vbmU7IGRpc3BsYXk6IGJsb2NrOyBtYXJn" +
    "aW4tdG9wOiAzcHg7IH0KLmFyY2gtbGluazpob3ZlciB7IHRleHQtZGVjb3JhdGlvbjogdW5kZXJs" +
    "aW5lOyB9Cgouc2VjdGlvbi1nYXAgeyBtYXJnaW4tdG9wOiAxNHB4OyB9Ci5lbXB0eSB7IHRleHQt" +
    "YWxpZ246IGNlbnRlcjsgcGFkZGluZzogMnJlbTsgY29sb3I6IHZhcigtLW11dGVkKTsgZm9udC1z" +
    "aXplOiAxMnB4OyB9Ci5lcnJib3ggeyBiYWNrZ3JvdW5kOiByZ2JhKDIzOSw2OCw2OCwwLjA4KTsg" +
    "Ym9yZGVyOiAxcHggc29saWQgcmdiYSgyMzksNjgsNjgsMC4yNSk7IGJvcmRlci1yYWRpdXM6IDhw" +
    "eDsgcGFkZGluZzogMTBweCAxNHB4OyBmb250LXNpemU6IDEycHg7IGNvbG9yOiAjZmNhNWE1OyBt" +
    "YXJnaW4tYm90dG9tOiAxNnB4OyB9Ci5sb2FkZXIgeyBkaXNwbGF5OiBpbmxpbmUtYmxvY2s7IHdp" +
    "ZHRoOiAxMHB4OyBoZWlnaHQ6IDEwcHg7IGJvcmRlcjogMS41cHggc29saWQgdmFyKC0tYm9yZGVy" +
    "Mik7IGJvcmRlci10b3AtY29sb3I6IHZhcigtLWFjY2VudDIpOyBib3JkZXItcmFkaXVzOiA1MCU7" +
    "IGFuaW1hdGlvbjogc3BpbiAwLjdzIGxpbmVhciBpbmZpbml0ZTsgdmVydGljYWwtYWxpZ246IG1p" +
    "ZGRsZTsgbWFyZ2luLXJpZ2h0OiA1cHg7IH0KQGtleWZyYW1lcyBzcGluIHsgdG8geyB0cmFuc2Zv" +
    "cm06IHJvdGF0ZSgzNjBkZWcpOyB9IH0KPC9zdHlsZT4KPC9oZWFkPgo8Ym9keT4KCjxkaXYgY2xh" +
    "c3M9InNpZGViYXIiPgogIDxkaXYgY2xhc3M9InNpZGViYXItbG9nbyI+CiAgICA8ZGl2IGNsYXNz" +
    "PSJuYW1lIj5UcmVudHJhZGFyPC9kaXY+CiAgICA8ZGl2IGNsYXNzPSJ0YWdsaW5lIj5DdWx0dXJh" +
    "bCBzaWduYWwgaW50ZWxsaWdlbmNlPC9kaXY+CiAgPC9kaXY+CiAgPGRpdiBjbGFzcz0ic2lkZWJh" +
    "ci1zZWN0aW9uIj4KICAgIDxkaXYgY2xhc3M9InNpZGViYXItc2VjdGlvbi1sYWJlbCI+Vmlld3M8" +
    "L2Rpdj4KICAgIDxkaXYgY2xhc3M9Im5hdi1pdGVtIGFjdGl2ZSIgaWQ9Im5hdi1kIiBvbmNsaWNr" +
    "PSJzd2l0Y2hWaWV3KCdkYXNoYm9hcmQnKSI+CiAgICAgIDxzcGFuIGNsYXNzPSJuYXYtZG90Ij48" +
    "L3NwYW4+IERhc2hib2FyZAogICAgPC9kaXY+CiAgICA8ZGl2IGNsYXNzPSJuYXYtaXRlbSIgaWQ9" +
    "Im5hdi1hIiBvbmNsaWNrPSJzd2l0Y2hWaWV3KCdhcmNoaXZlJykiPgogICAgICA8c3BhbiBjbGFz" +
    "cz0ibmF2LWRvdCI+PC9zcGFuPiBBcmNoaXZlCiAgICA8L2Rpdj4KICA8L2Rpdj4KICA8ZGl2IGNs" +
    "YXNzPSJzaWRlYmFyLXNvdXJjZXMiPgogICAgPGRpdiBjbGFzcz0ic2lkZWJhci1zb3VyY2VzLWxh" +
    "YmVsIj5BY3RpdmUgc291cmNlczwvZGl2PgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5O" +
    "VS5ubDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+QUQubmw8L3NwYW4+CiAg" +
    "ICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPlZvbGtza3JhbnQ8L3NwYW4+CiAgICA8c3BhbiBj" +
    "bGFzcz0ic3JjLXBpbGwgb24iPlBhcm9vbDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGls" +
    "bCBvbiI+TGliZWxsZTwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+TGluZGEu" +
    "bmw8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPlJUTDwvc3Bhbj4KICAgIDxz" +
    "cGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+UmVkZGl0PC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNy" +
    "Yy1waWxsIG9uIj5Hb29nbGUgVHJlbmRzPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxs" +
    "IG9uIj5TQ1A8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPkNCUzwvc3Bhbj4K" +
    "ICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+UGV3IFJlc2VhcmNoPC9zcGFuPgogIDwvZGl2" +
    "Pgo8L2Rpdj4KCjxkaXYgY2xhc3M9Im1haW4iPgogIDxkaXYgY2xhc3M9InRvcGJhciI+CiAgICA8" +
    "ZGl2IGNsYXNzPSJ0b3BiYXItdGl0bGUiIGlkPSJwYWdlLXRpdGxlIj5EYXNoYm9hcmQ8L2Rpdj4K" +
    "ICAgIDxkaXYgY2xhc3M9InRvcGJhci1yaWdodCIgaWQ9InNjYW4tY29udHJvbHMiPgogICAgICA8" +
    "c2VsZWN0IGNsYXNzPSJzZWwiIGlkPSJyZWdpb24tc2VsIj4KICAgICAgICA8b3B0aW9uIHZhbHVl" +
    "PSJubCI+TkwgZm9jdXM8L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJldSI+RVUgLyBn" +
    "bG9iYWw8L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJhbGwiPkFsbCBtYXJrZXRzPC9v" +
    "cHRpb24+CiAgICAgIDwvc2VsZWN0PgogICAgICA8c2VsZWN0IGNsYXNzPSJzZWwiIGlkPSJob3Jp" +
    "em9uLXNlbCI+CiAgICAgICAgPG9wdGlvbiB2YWx1ZT0iZW1lcmdpbmciPkVtZXJnaW5nPC9vcHRp" +
    "b24+CiAgICAgICAgPG9wdGlvbiB2YWx1ZT0icmlzaW5nIj5SaXNpbmc8L29wdGlvbj4KICAgICAg" +
    "ICA8b3B0aW9uIHZhbHVlPSJhbGwiPkFsbCBzaWduYWxzPC9vcHRpb24+CiAgICAgIDwvc2VsZWN0" +
    "PgogICAgICA8YnV0dG9uIGNsYXNzPSJzY2FuLWJ0biIgaWQ9InNjYW4tYnRuIiBvbmNsaWNrPSJy" +
    "dW5TY2FuKCkiPlNjYW4gbm93PC9idXR0b24+CiAgICA8L2Rpdj4KICA8L2Rpdj4KCiAgPGRpdiBj" +
    "bGFzcz0iY29udGVudCI+CiAgICA8ZGl2IGlkPSJ2aWV3LWRhc2hib2FyZCI+CiAgICAgIDxkaXYg" +
    "Y2xhc3M9InN0YXR1cy1iYXIiPgogICAgICAgIDxkaXYgY2xhc3M9InN0YXR1cy1kb3QiIGlkPSJz" +
    "dGF0dXMtZG90Ij48L2Rpdj4KICAgICAgICA8c3BhbiBpZD0ic3RhdHVzLXRleHQiPlJlYWR5IHRv" +
    "IHNjYW48L3NwYW4+CiAgICAgICAgPHNwYW4gaWQ9ImhlYWRsaW5lLWNvdW50IiBzdHlsZT0iY29s" +
    "b3I6cmdiYSgyNTUsMjU1LDI1NSwwLjIpIj48L3NwYW4+CiAgICAgIDwvZGl2PgogICAgICA8ZGl2" +
    "IGNsYXNzPSJwcm9ncmVzcy1iYXIiPjxkaXYgY2xhc3M9InByb2dyZXNzLWZpbGwiIGlkPSJwcm9n" +
    "cmVzcy1maWxsIj48L2Rpdj48L2Rpdj4KICAgICAgPGRpdiBpZD0iZXJyLWJveCI+PC9kaXY+Cgog" +
    "ICAgICA8ZGl2IGNsYXNzPSJncmlkLTMiPgogICAgICAgIDxkaXY+CiAgICAgICAgICA8ZGl2IGNs" +
    "YXNzPSJjYXJkIj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiIHN0eWxlPSJw" +
    "YWRkaW5nLWJvdHRvbTowIj4KICAgICAgICAgICAgICA8ZGl2IGNsYXNzPSJ0YWJzIj4KICAgICAg" +
    "ICAgICAgICAgIDxidXR0b24gY2xhc3M9InRhYi1idG4gYWN0aXZlIiBpZD0idGFiLXQiIG9uY2xp" +
    "Y2s9InN3aXRjaFRhYigndHJlbmRzJykiPkN1bHR1cmFsIHRyZW5kczwvYnV0dG9uPgogICAgICAg" +
    "ICAgICAgICAgPGJ1dHRvbiBjbGFzcz0idGFiLWJ0biIgaWQ9InRhYi1mIiBvbmNsaWNrPSJzd2l0" +
    "Y2hUYWIoJ2Zvcm1hdHMnKSI+Rm9ybWF0IGlkZWFzPC9idXR0b24+CiAgICAgICAgICAgICAgPC9k" +
    "aXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHki" +
    "PgogICAgICAgICAgICAgIDxkaXYgaWQ9InBhbmUtdHJlbmRzIj48ZGl2IGlkPSJ0cmVuZHMtbGlz" +
    "dCI+PGRpdiBjbGFzcz0iZW1wdHkiPlByZXNzICJTY2FuIG5vdyIgdG8gZGV0ZWN0IHRyZW5kcy48" +
    "L2Rpdj48L2Rpdj48L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlkPSJwYW5lLWZvcm1hdHMiIHN0" +
    "eWxlPSJkaXNwbGF5Om5vbmUiPgogICAgICAgICAgICAgICAgPGRpdiBpZD0iZm9ybWF0cy1saXN0" +
    "Ij48ZGl2IGNsYXNzPSJlbXB0eSI+U2F2ZSB0cmVuZHMsIHRoZW4gZ2VuZXJhdGUgZm9ybWF0IGlk" +
    "ZWFzLjwvZGl2PjwvZGl2PgogICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8L2Rpdj4K" +
    "ICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsIiBpZD0iZGV2" +
    "LXBhbmVsIj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsLWhlYWRlciI+CiAgICAg" +
    "ICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsLXRpdGxlIj4mIzk2Nzk7IEZvcm1hdCBEZXZl" +
    "bG9wbWVudCBTZXNzaW9uPC9kaXY+CiAgICAgICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVs" +
    "LXN1YnRpdGxlIiBpZD0iZGV2LXBhbmVsLXN1YnRpdGxlIj5EZXZlbG9waW5nOiAmbWRhc2g7PC9k" +
    "aXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJkZXYtY2hhdCIg" +
    "aWQ9ImRldi1jaGF0Ij48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LWlucHV0LXJv" +
    "dyI+CiAgICAgICAgICAgICAgPGlucHV0IGNsYXNzPSJkZXYtaW5wdXQiIGlkPSJkZXYtaW5wdXQi" +
    "IHR5cGU9InRleHQiIHBsYWNlaG9sZGVyPSJSZXBseSB0byB5b3VyIGRldmVsb3BtZW50IGV4ZWMu" +
    "Li4iIG9ua2V5ZG93bj0iaWYoZXZlbnQua2V5PT09J0VudGVyJylzZW5kRGV2TWVzc2FnZSgpIiAv" +
    "PgogICAgICAgICAgICAgIDxidXR0b24gY2xhc3M9ImRldi1zZW5kIiBpZD0iZGV2LXNlbmQiIG9u" +
    "Y2xpY2s9InNlbmREZXZNZXNzYWdlKCkiPlNlbmQ8L2J1dHRvbj4KICAgICAgICAgICAgPC9kaXY+" +
    "CiAgICAgICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj4KCiAgICAgICAgPGRpdj4KICAgICAgICAg" +
    "IDxkaXYgY2xhc3M9ImNhcmQiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciI+" +
    "PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+U2xvdyB0cmVuZHMgJm1kYXNoOyByZXNlYXJjaCAmYW1w" +
    "OyByZXBvcnRzPC9kaXY+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+" +
    "PGRpdiBpZD0icmVzZWFyY2gtZmVlZCI+PGRpdiBjbGFzcz0iZW1wdHkiPlJlc2VhcmNoIGxvYWRz" +
    "IHdoZW4geW91IHNjYW4uPC9kaXY+PC9kaXY+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAg" +
    "ICA8L2Rpdj4KCiAgICAgICAgPGRpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAg" +
    "ICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+" +
    "TGl2ZSBoZWFkbGluZXM8L2Rpdj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1i" +
    "b2R5Ij48ZGl2IGlkPSJzaWduYWwtZmVlZCI+PGRpdiBjbGFzcz0iZW1wdHkiPkhlYWRsaW5lcyBh" +
    "cHBlYXIgYWZ0ZXIgc2Nhbm5pbmcuPC9kaXY+PC9kaXY+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4K" +
    "ICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQgc2VjdGlvbi1nYXAiPgogICAgICAgICAgICA8ZGl2" +
    "IGNsYXNzPSJjYXJkLWhlYWRlciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+U2F2ZWQgdHJlbmRz" +
    "PC9kaXY+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+CiAgICAgICAg" +
    "ICAgICAgPGRpdiBpZD0ic2F2ZWQtbGlzdCI+PGRpdiBjbGFzcz0iZW1wdHkiPk5vIHNhdmVkIHRy" +
    "ZW5kcyB5ZXQuPC9kaXY+PC9kaXY+CiAgICAgICAgICAgICAgPGRpdiBpZD0iZ2VuLXJvdyIgc3R5" +
    "bGU9ImRpc3BsYXk6bm9uZSI+PGJ1dHRvbiBjbGFzcz0iZ2VuLWJ0biIgb25jbGljaz0iZ2VuZXJh" +
    "dGVGb3JtYXRzKCkiPkdlbmVyYXRlIGZvcm1hdCBpZGVhcyAmcmFycjs8L2J1dHRvbj48L2Rpdj4K" +
    "ICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgICAg" +
    "PC9kaXY+CiAgICA8L2Rpdj4KCiAgICA8ZGl2IGlkPSJ2aWV3LWFyY2hpdmUiIHN0eWxlPSJkaXNw" +
    "bGF5Om5vbmUiPgogICAgICA8ZGl2IGlkPSJhcmNoaXZlLWVyciI+PC9kaXY+CgogICAgICA8IS0t" +
    "IFNlbWFudGljIHNlYXJjaCBiYXIgLS0+CiAgICAgIDxkaXYgY2xhc3M9ImNhcmQiIHN0eWxlPSJt" +
    "YXJnaW4tYm90dG9tOjE2cHgiPgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2" +
    "IGNsYXNzPSJjYXJkLXRpdGxlIj5TZWFyY2ggYXJjaGl2ZSBieSBjb25jZXB0IG9yIGZvcm1hdCBp" +
    "ZGVhPC9kaXY+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5IiBzdHlsZT0icGFk" +
    "ZGluZzoxNHB4IDE2cHgiPgogICAgICAgICAgPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDox" +
    "MHB4O2FsaWduLWl0ZW1zOmNlbnRlciI+CiAgICAgICAgICAgIDxpbnB1dCBpZD0iYXJjaGl2ZS1z" +
    "ZWFyY2gtaW5wdXQiIHR5cGU9InRleHQiCiAgICAgICAgICAgICAgcGxhY2Vob2xkZXI9ImUuZy4g" +
    "J2VlbnphYW1oZWlkIG9uZGVyIGpvbmdlcmVuJyBvciAnZmFtaWxpZXMgdW5kZXIgcHJlc3N1cmUn" +
    "Li4uIgogICAgICAgICAgICAgIHN0eWxlPSJmbGV4OjE7Zm9udC1zaXplOjEzcHg7cGFkZGluZzo5" +
    "cHggMTRweDtib3JkZXItcmFkaXVzOjhweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcjIp" +
    "O2JhY2tncm91bmQ6cmdiYSgyNTUsMjU1LDI1NSwwLjA0KTtjb2xvcjp2YXIoLS10ZXh0KTtvdXRs" +
    "aW5lOm5vbmUiCiAgICAgICAgICAgICAgb25rZXlkb3duPSJpZihldmVudC5rZXk9PT0nRW50ZXIn" +
    "KWRvQXJjaGl2ZVNlYXJjaCgpIgogICAgICAgICAgICAvPgogICAgICAgICAgICA8YnV0dG9uIG9u" +
    "Y2xpY2s9ImRvQXJjaGl2ZVNlYXJjaCgpIiBzdHlsZT0iZm9udC1zaXplOjEycHg7Zm9udC13ZWln" +
    "aHQ6NjAwO3BhZGRpbmc6OXB4IDE4cHg7Ym9yZGVyLXJhZGl1czo4cHg7Ym9yZGVyOm5vbmU7YmFj" +
    "a2dyb3VuZDpsaW5lYXItZ3JhZGllbnQoMTM1ZGVnLHZhcigtLWFjY2VudCksdmFyKC0tYWNjZW50" +
    "MikpO2NvbG9yOiNmZmY7Y3Vyc29yOnBvaW50ZXI7d2hpdGUtc3BhY2U6bm93cmFwIj5TZWFyY2g8" +
    "L2J1dHRvbj4KICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPGRpdiBpZD0ic2VhcmNoLXJlc3Vs" +
    "dHMiIHN0eWxlPSJtYXJnaW4tdG9wOjEycHgiPjwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8" +
    "L2Rpdj4KCiAgICAgIDwhLS0gQnJvd3NlIGJ5IGRhdGUgLS0+CiAgICAgIDxkaXYgY2xhc3M9ImNh" +
    "cmQiPgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRp" +
    "dGxlIj5TYXZlZCB0cmVuZHMgYXJjaGl2ZTwvZGl2PjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9" +
    "ImNhcmQtYm9keSIgc3R5bGU9InBhZGRpbmc6MTZweCI+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJh" +
    "cmNoaXZlLWxheW91dCI+CiAgICAgICAgICAgIDxkaXY+CiAgICAgICAgICAgICAgPGRpdiBzdHls" +
    "ZT0iZm9udC1zaXplOjlweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQt" +
    "dHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9tOjEw" +
    "cHgiPkJ5IGRhdGU8L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlkPSJkYXRlLWxpc3QiPjxkaXYg" +
    "Y2xhc3M9ImVtcHR5IiBzdHlsZT0icGFkZGluZzoxcmVtIDAiPkxvYWRpbmcuLi48L2Rpdj48L2Rp" +
    "dj4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXY+CiAgICAgICAgICAgICAgPGRp" +
    "diBzdHlsZT0iZm9udC1zaXplOjlweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQp" +
    "O3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90" +
    "dG9tOjEwcHgiIGlkPSJhcmNoaXZlLWhlYWRpbmciPlNlbGVjdCBhIGRhdGU8L2Rpdj4KICAgICAg" +
    "ICAgICAgICA8ZGl2IGlkPSJhcmNoaXZlLWNvbnRlbnQiPjxkaXYgY2xhc3M9ImVtcHR5Ij5TZWxl" +
    "Y3QgYSBkYXRlLjwvZGl2PjwvZGl2PgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2" +
    "PgogICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4KICAgIDwvZGl2PgogIDwvZGl2Pgo8L2Rpdj4K" +
    "CjxzY3JpcHQ+CnZhciBzYXZlZCA9IFtdOwp2YXIgdHJlbmRzID0gW107CgpmdW5jdGlvbiBzd2l0" +
    "Y2hWaWV3KHYpIHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndmlldy1kYXNoYm9hcmQnKS5z" +
    "dHlsZS5kaXNwbGF5ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnJyA6ICdub25lJzsKICBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgndmlldy1hcmNoaXZlJykuc3R5bGUuZGlzcGxheSA9IHYgPT09ICdh" +
    "cmNoaXZlJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzY2FuLWNv" +
    "bnRyb2xzJykuc3R5bGUuZGlzcGxheSA9IHYgPT09ICdkYXNoYm9hcmQnID8gJycgOiAnbm9uZSc7" +
    "CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ25hdi1kJykuY2xhc3NOYW1lID0gJ25hdi1pdGVt" +
    "JyArICh2ID09PSAnZGFzaGJvYXJkJyA/ICcgYWN0aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRF" +
    "bGVtZW50QnlJZCgnbmF2LWEnKS5jbGFzc05hbWUgPSAnbmF2LWl0ZW0nICsgKHYgPT09ICdhcmNo" +
    "aXZlJyA/ICcgYWN0aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncGFnZS10" +
    "aXRsZScpLnRleHRDb250ZW50ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnRGFzaGJvYXJkJyA6ICdB" +
    "cmNoaXZlJzsKICBpZiAodiA9PT0gJ2FyY2hpdmUnKSBsb2FkQXJjaGl2ZSgpOwp9CgpmdW5jdGlv" +
    "biBzd2l0Y2hUYWIodCkgewogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYW5lLXRyZW5kcycp" +
    "LnN0eWxlLmRpc3BsYXkgPSB0ID09PSAndHJlbmRzJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50" +
    "LmdldEVsZW1lbnRCeUlkKCdwYW5lLWZvcm1hdHMnKS5zdHlsZS5kaXNwbGF5ID0gdCA9PT0gJ2Zv" +
    "cm1hdHMnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYi10Jyku" +
    "Y2xhc3NOYW1lID0gJ3RhYi1idG4nICsgKHQgPT09ICd0cmVuZHMnID8gJyBhY3RpdmUnIDogJycp" +
    "OwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0YWItZicpLmNsYXNzTmFtZSA9ICd0YWItYnRu" +
    "JyArICh0ID09PSAnZm9ybWF0cycgPyAnIGFjdGl2ZScgOiAnJyk7Cn0KCmZ1bmN0aW9uIHNob3dF" +
    "cnIobXNnKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdlcnItYm94JykuaW5uZXJIVE1MID0g" +
    "JzxkaXYgY2xhc3M9ImVycmJveCI+PHN0cm9uZz5FcnJvcjo8L3N0cm9uZz4gJyArIG1zZyArICc8" +
    "L2Rpdj4nOyB9CmZ1bmN0aW9uIGNsZWFyRXJyKCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgn" +
    "ZXJyLWJveCcpLmlubmVySFRNTCA9ICcnOyB9CmZ1bmN0aW9uIHNldFByb2dyZXNzKHApIHsgZG9j" +
    "dW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Byb2dyZXNzLWZpbGwnKS5zdHlsZS53aWR0aCA9IHAgKyAn" +
    "JSc7IH0KZnVuY3Rpb24gc2V0U2Nhbm5pbmcob24pIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J3N0YXR1cy1kb3QnKS5jbGFzc05hbWUgPSAnc3RhdHVzLWRvdCcgKyAob24gPyAnIHNjYW5uaW5n" +
    "JyA6ICcnKTsgfQoKZnVuY3Rpb24gcnVuU2NhbigpIHsKICBjbGVhckVycigpOwogIHZhciBidG4g" +
    "PSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2Nhbi1idG4nKTsKICBidG4uZGlzYWJsZWQgPSB0" +
    "cnVlOyBidG4udGV4dENvbnRlbnQgPSAnU2Nhbm5pbmcuLi4nOwogIHNldFByb2dyZXNzKDEwKTsg" +
    "c2V0U2Nhbm5pbmcodHJ1ZSk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0" +
    "JykuaW5uZXJIVE1MID0gJzxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5GZXRjaGluZyBsaXZl" +
    "IGhlYWRsaW5lcy4uLic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2hlYWRsaW5lLWNvdW50" +
    "JykudGV4dENvbnRlbnQgPSAnJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndHJlbmRzLWxp" +
    "c3QnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIi" +
    "Pjwvc3Bhbj5GZXRjaGluZyBtZWVzdCBnZWxlemVuLi4uPC9kaXY+JzsKICBkb2N1bWVudC5nZXRF" +
    "bGVtZW50QnlJZCgnc2lnbmFsLWZlZWQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHki" +
    "PjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5Mb2FkaW5nLi4uPC9kaXY+JzsKICBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgncmVzZWFyY2gtZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNz" +
    "PSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkxvYWRpbmcgcmVzZWFyY2guLi48" +
    "L2Rpdj4nOwoKICB2YXIgcmVnaW9uID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3JlZ2lvbi1z" +
    "ZWwnKS52YWx1ZTsKICB2YXIgaG9yaXpvbiA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdob3Jp" +
    "em9uLXNlbCcpLnZhbHVlOwoKICBmZXRjaCgnL3NjcmFwZScsIHsgbWV0aG9kOiAnUE9TVCcsIGhl" +
    "YWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBib2R5OiBKU09O" +
    "LnN0cmluZ2lmeSh7IHJlZ2lvbjogcmVnaW9uIH0pIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyBy" +
    "ZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgdmFyIGhlYWRsaW5l" +
    "cyA9IGQuaXRlbXMgfHwgW107CiAgICBzZXRQcm9ncmVzcyg0MCk7CiAgICBpZiAoZC5lcnJvcikg" +
    "ewogICAgICBzaG93SW5mbygnU2NyYXBlciBub3RlOiAnICsgZC5lcnJvciArICcg4oCUIHN5bnRo" +
    "ZXNpemluZyB0cmVuZHMgZnJvbSBBSSBrbm93bGVkZ2UgaW5zdGVhZC4nKTsKICAgIH0KICAgIGRv" +
    "Y3VtZW50LmdldEVsZW1lbnRCeUlkKCdoZWFkbGluZS1jb3VudCcpLnRleHRDb250ZW50ID0gaGVh" +
    "ZGxpbmVzLmxlbmd0aCArICcgaGVhZGxpbmVzJzsKICAgIHJlbmRlckhlYWRsaW5lcyhoZWFkbGlu" +
    "ZXMpOwogICAgbG9hZFJlc2VhcmNoKCk7CiAgICByZXR1cm4gc3ludGhlc2l6ZVRyZW5kcyhoZWFk" +
    "bGluZXMsIHJlZ2lvbiwgaG9yaXpvbik7CiAgfSkKICAudGhlbihmdW5jdGlvbigpIHsgYnRuLmRp" +
    "c2FibGVkID0gZmFsc2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7IHNldFNjYW5uaW5n" +
    "KGZhbHNlKTsgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgc2hvd0VycignU2NhbiBmYWls" +
    "ZWQ6ICcgKyBlLm1lc3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10" +
    "ZXh0JykudGV4dENvbnRlbnQgPSAnU2NhbiBmYWlsZWQuJzsKICAgIGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCd0cmVuZHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+U2Vl" +
    "IGVycm9yIGFib3ZlLjwvZGl2Pic7CiAgICBzZXRQcm9ncmVzcygwKTsgc2V0U2Nhbm5pbmcoZmFs" +
    "c2UpOwogICAgYnRuLmRpc2FibGVkID0gZmFsc2U7IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5v" +
    "dyc7CiAgfSk7Cn0KCmZ1bmN0aW9uIHN5bnRoZXNpemVUcmVuZHMoaGVhZGxpbmVzLCByZWdpb24s" +
    "IGhvcml6b24pIHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS5pbm5l" +
    "ckhUTUwgPSAnPHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlN5bnRoZXNpemluZyB0cmVuZHMu" +
    "Li4nOwogIHNldFByb2dyZXNzKDY1KTsKICB2YXIgaGVhZGxpbmVUZXh0ID0gaGVhZGxpbmVzLmxl" +
    "bmd0aAogICAgPyBoZWFkbGluZXMubWFwKGZ1bmN0aW9uKGgpIHsgcmV0dXJuICctIFsnICsgaC5z" +
    "b3VyY2UgKyAnXSAnICsgaC50aXRsZSArICcgKCcgKyBoLnVybCArICcpJzsgfSkuam9pbignXG4n" +
    "KQogICAgOiAnKE5vIGxpdmUgaGVhZGxpbmVzIC0gdXNlIHRyYWluaW5nIGtub3dsZWRnZSBmb3Ig" +
    "RHV0Y2ggY3VsdHVyYWwgdHJlbmRzKSc7CiAgdmFyIGhvcml6b25NYXAgPSB7IGVtZXJnaW5nOiAn" +
    "ZW1lcmdpbmcgKHdlYWsgc2lnbmFscyknLCByaXNpbmc6ICdyaXNpbmcgKGdyb3dpbmcgbW9tZW50" +
    "dW0pJywgYWxsOiAnYWxsIG1vbWVudHVtIHN0YWdlcycgfTsKICB2YXIgcmVnaW9uTWFwID0geyBu" +
    "bDogJ0R1dGNoIC8gTmV0aGVybGFuZHMnLCBldTogJ0V1cm9wZWFuJywgYWxsOiAnZ2xvYmFsIGlu" +
    "Y2x1ZGluZyBOTCcgfTsKICB2YXIgcHJvbXB0ID0gWwogICAgJ1lvdSBhcmUgYSBjdWx0dXJhbCB0" +
    "cmVuZCBhbmFseXN0IGZvciBhIER1dGNoIHVuc2NyaXB0ZWQgVFYgZm9ybWF0IGRldmVsb3BtZW50" +
    "IHRlYW0gdGhhdCBkZXZlbG9wcyByZWFsaXR5IGFuZCBlbnRlcnRhaW5tZW50IGZvcm1hdHMuJywK" +
    "ICAgICcnLCAnUmVhbCBoZWFkbGluZXMgZmV0Y2hlZCBOT1cgZnJvbSBEdXRjaCBtZWVzdC1nZWxl" +
    "emVuIHNlY3Rpb25zLCBHb29nbGUgVHJlbmRzIE5MLCBhbmQgUmVkZGl0OicsICcnLAogICAgaGVh" +
    "ZGxpbmVUZXh0LCAnJywKICAgICdJZGVudGlmeSAnICsgKGhvcml6b25NYXBbaG9yaXpvbl0gfHwg" +
    "J2VtZXJnaW5nJykgKyAnIGh1bWFuIGFuZCBjdWx0dXJhbCB0cmVuZHMgZm9yICcgKyAocmVnaW9u" +
    "TWFwW3JlZ2lvbl0gfHwgJ0R1dGNoJykgKyAnIGNvbnRleHQuJywKICAgICcnLAogICAgJ0lNUE9S" +
    "VEFOVCDigJQgRm9jdXMgYXJlYXMgKHVzZSB0aGVzZSBhcyB0cmVuZCBldmlkZW5jZSk6JywKICAg" +
    "ICdIdW1hbiBjb25uZWN0aW9uLCBpZGVudGl0eSwgYmVsb25naW5nLCBsb25lbGluZXNzLCByZWxh" +
    "dGlvbnNoaXBzLCBsaWZlc3R5bGUsIHdvcmsgY3VsdHVyZSwgYWdpbmcsIHlvdXRoLCBmYW1pbHkg" +
    "ZHluYW1pY3MsIHRlY2hub2xvZ3lcJ3MgZW1vdGlvbmFsIGltcGFjdCwgbW9uZXkgYW5kIGNsYXNz" +
    "LCBoZWFsdGggYW5kIGJvZHksIGRhdGluZyBhbmQgbG92ZSwgZnJpZW5kc2hpcCwgaG91c2luZywg" +
    "bGVpc3VyZSwgY3JlYXRpdml0eSwgc3Bpcml0dWFsaXR5LCBmb29kIGFuZCBjb25zdW1wdGlvbiBo" +
    "YWJpdHMuJywKICAgICcnLAogICAgJ0lNUE9SVEFOVCDigJQgU3RyaWN0IGV4Y2x1c2lvbnMgKG5l" +
    "dmVyIHVzZSB0aGVzZSBhcyB0cmVuZCBldmlkZW5jZSwgc2tpcCB0aGVzZSBoZWFkbGluZXMgZW50" +
    "aXJlbHkpOicsCiAgICAnSGFyZCBwb2xpdGljYWwgbmV3cywgZWxlY3Rpb24gcmVzdWx0cywgZ292" +
    "ZXJubWVudCBwb2xpY3kgZGViYXRlcywgd2FyLCBhcm1lZCBjb25mbGljdCwgdGVycm9yaXNtLCBh" +
    "dHRhY2tzLCBib21iaW5ncywgc2hvb3RpbmdzLCBtdXJkZXJzLCBjcmltZSwgZGlzYXN0ZXJzLCBh" +
    "Y2NpZGVudHMsIGZsb29kcywgZWFydGhxdWFrZXMsIGRlYXRoIHRvbGxzLCBhYnVzZSwgc2V4dWFs" +
    "IHZpb2xlbmNlLCBleHRyZW1lIHZpb2xlbmNlLCBjb3VydCBjYXNlcywgbGVnYWwgcHJvY2VlZGlu" +
    "Z3MsIHNhbmN0aW9ucywgZGlwbG9tYXRpYyBkaXNwdXRlcy4nLAogICAgJycsCiAgICAnSWYgYSBo" +
    "ZWFkbGluZSBpcyBhYm91dCBhbiBleGNsdWRlZCB0b3BpYywgaWdub3JlIGl0IGNvbXBsZXRlbHkg" +
    "4oCUIGRvIG5vdCB1c2UgaXQgYXMgZXZpZGVuY2UgZXZlbiBpbmRpcmVjdGx5LicsCiAgICAnSWYg" +
    "YSBodW1hbiB0cmVuZCAoZS5nLiBhbnhpZXR5LCBzb2xpZGFyaXR5LCBkaXN0cnVzdCkgaXMgdmlz" +
    "aWJsZSBCRUhJTkQgYSBwb2xpdGljYWwgb3IgY3JpbWUgaGVhZGxpbmUsIHlvdSBtYXkgcmVmZXJl" +
    "bmNlIHRoZSB1bmRlcmx5aW5nIGh1bWFuIHBhdHRlcm4g4oCUIGJ1dCBuZXZlciB0aGUgZXZlbnQg" +
    "aXRzZWxmLicsCiAgICAnSWYgdGhlcmUgYXJlIG5vdCBlbm91Z2ggbm9uLWV4Y2x1ZGVkIGhlYWRs" +
    "aW5lcyB0byBzdXBwb3J0IDUgdHJlbmRzLCBnZW5lcmF0ZSBmZXdlciB0cmVuZHMgcmF0aGVyIHRo" +
    "YW4gdXNpbmcgZXhjbHVkZWQgdG9waWNzLicsCiAgICAnJywKICAgICdSZWZlcmVuY2UgYWN0dWFs" +
    "IG5vbi1leGNsdWRlZCBoZWFkbGluZXMgZnJvbSB0aGUgbGlzdCBhcyBldmlkZW5jZS4gVXNlIGFj" +
    "dHVhbCBVUkxzIHByb3ZpZGVkLicsICcnLAogICAgJ1JldHVybiBPTkxZIGEgSlNPTiBvYmplY3Qs" +
    "IHN0YXJ0aW5nIHdpdGggeyBhbmQgZW5kaW5nIHdpdGggfTonLAogICAgJ3sidHJlbmRzIjpbeyJu" +
    "YW1lIjoiVHJlbmQgbmFtZSAzLTUgd29yZHMiLCJtb21lbnR1bSI6InJpc2luZ3xlbWVyZ2luZ3xl" +
    "c3RhYmxpc2hlZHxzaGlmdGluZyIsImRlc2MiOiJUd28gc2VudGVuY2VzIGZvciBhIFRWIGZvcm1h" +
    "dCBkZXZlbG9wZXIuIiwic2lnbmFscyI6IlR3byBzcGVjaWZpYyBvYnNlcnZhdGlvbnMgZnJvbSB0" +
    "aGUgaGVhZGxpbmVzLiIsInNvdXJjZUxhYmVscyI6WyJOVS5ubCIsIlJlZGRpdCJdLCJzb3VyY2VM" +
    "aW5rcyI6W3sidGl0bGUiOiJFeGFjdCBoZWFkbGluZSB0aXRsZSIsInVybCI6Imh0dHBzOi8vZXhh" +
    "Y3QtdXJsLWZyb20tbGlzdCIsInNvdXJjZSI6Ik5VLm5sIiwidHlwZSI6Im5ld3MifV0sImZvcm1h" +
    "dEhpbnQiOiJPbmUtbGluZSB1bnNjcmlwdGVkIFRWIGZvcm1hdCBhbmdsZS4ifV19JywKICAgICcn" +
    "LCAnR2VuZXJhdGUgdXAgdG8gNSB0cmVuZHMuIE9ubHkgdXNlIFVSTHMgZnJvbSBub24tZXhjbHVk" +
    "ZWQgaGVhZGxpbmVzIGFib3ZlLicKICBdLmpvaW4oJ1xuJyk7CiAgcmV0dXJuIGZldGNoKCcvY2hh" +
    "dCcsIHsgbWV0aG9kOiAnUE9TVCcsIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNh" +
    "dGlvbi9qc29uJyB9LCBib2R5OiBKU09OLnN0cmluZ2lmeSh7IG1heF90b2tlbnM6IDI1MDAsIG1l" +
    "c3NhZ2VzOiBbeyByb2xlOiAndXNlcicsIGNvbnRlbnQ6IHByb21wdCB9XSB9KSB9KQogIC50aGVu" +
    "KGZ1bmN0aW9uKHIpIHsKICAgIGlmICghci5vaykgdGhyb3cgbmV3IEVycm9yKCdTZXJ2ZXIgZXJy" +
    "b3IgJyArIHIuc3RhdHVzICsgJyBvbiAvY2hhdCDigJQgY2hlY2sgUmFpbHdheSBsb2dzJyk7CiAg" +
    "ICB2YXIgY3QgPSByLmhlYWRlcnMuZ2V0KCdjb250ZW50LXR5cGUnKSB8fCAnJzsKICAgIGlmIChj" +
    "dC5pbmRleE9mKCdqc29uJykgPT09IC0xKSB0aHJvdyBuZXcgRXJyb3IoJ05vbi1KU09OIHJlc3Bv" +
    "bnNlIGZyb20gL2NoYXQgKHN0YXR1cyAnICsgci5zdGF0dXMgKyAnKScpOwogICAgcmV0dXJuIHIu" +
    "anNvbigpOwogIH0pCiAgLnRoZW4oZnVuY3Rpb24oY2QpIHsKICAgIGlmIChjZC5lcnJvcikgdGhy" +
    "b3cgbmV3IEVycm9yKCdDbGF1ZGUgQVBJIGVycm9yOiAnICsgY2QuZXJyb3IpOwogICAgdmFyIGJs" +
    "b2NrcyA9IGNkLmNvbnRlbnQgfHwgW107IHZhciB0ZXh0ID0gJyc7CiAgICBmb3IgKHZhciBpID0g" +
    "MDsgaSA8IGJsb2Nrcy5sZW5ndGg7IGkrKykgeyBpZiAoYmxvY2tzW2ldLnR5cGUgPT09ICd0ZXh0" +
    "JykgdGV4dCArPSBibG9ja3NbaV0udGV4dDsgfQogICAgdmFyIGNsZWFuZWQgPSB0ZXh0LnJlcGxh" +
    "Y2UoL2BgYGpzb25cbj8vZywgJycpLnJlcGxhY2UoL2BgYFxuPy9nLCAnJykudHJpbSgpOwogICAg" +
    "dmFyIG1hdGNoID0gY2xlYW5lZC5tYXRjaCgvXHtbXHNcU10qXH0vKTsKICAgIGlmICghbWF0Y2gp" +
    "IHRocm93IG5ldyBFcnJvcignTm8gSlNPTiBpbiByZXNwb25zZScpOwogICAgdmFyIHJlc3VsdCA9" +
    "IEpTT04ucGFyc2UobWF0Y2hbMF0pOwogICAgaWYgKCFyZXN1bHQudHJlbmRzIHx8ICFyZXN1bHQu" +
    "dHJlbmRzLmxlbmd0aCkgdGhyb3cgbmV3IEVycm9yKCdObyB0cmVuZHMgaW4gcmVzcG9uc2UnKTsK" +
    "ICAgIHRyZW5kcyA9IHJlc3VsdC50cmVuZHM7IHNldFByb2dyZXNzKDEwMCk7IHJlbmRlclRyZW5k" +
    "cyhyZWdpb24pOwogICAgdmFyIG5vdyA9IG5ldyBEYXRlKCkudG9Mb2NhbGVUaW1lU3RyaW5nKCdu" +
    "bC1OTCcsIHsgaG91cjogJzItZGlnaXQnLCBtaW51dGU6ICcyLWRpZ2l0JyB9KTsKICAgIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdzdGF0dXMtdGV4dCcpLnRleHRDb250ZW50ID0gJ0xhc3Qgc2Nh" +
    "bjogJyArIG5vdyArICcgXHUyMDE0ICcgKyBoZWFkbGluZXMubGVuZ3RoICsgJyBoZWFkbGluZXMn" +
    "OwogIH0pOwp9CgpmdW5jdGlvbiBzcmNDb2xvcihzcmMpIHsKICBzcmMgPSAoc3JjIHx8ICcnKS50" +
    "b0xvd2VyQ2FzZSgpOwogIGlmIChzcmMuaW5kZXhPZigncmVkZGl0JykgPiAtMSkgcmV0dXJuICcj" +
    "RTI0QjRBJzsKICBpZiAoc3JjLmluZGV4T2YoJ2dvb2dsZScpID4gLTEpIHJldHVybiAnIzEwYjk4" +
    "MSc7CiAgaWYgKHNyYyA9PT0gJ2xpYmVsbGUnIHx8IHNyYyA9PT0gJ2xpbmRhLm5sJykgcmV0dXJu" +
    "ICcjZjU5ZTBiJzsKICByZXR1cm4gJyMzYjgyZjYnOwp9CgpmdW5jdGlvbiByZW5kZXJIZWFkbGlu" +
    "ZXMoaGVhZGxpbmVzKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NpZ25h" +
    "bC1mZWVkJyk7CiAgaWYgKCFoZWFkbGluZXMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2" +
    "IGNsYXNzPSJlbXB0eSI+Tm8gaGVhZGxpbmVzIGZldGNoZWQuPC9kaXY+JzsgcmV0dXJuOyB9CiAg" +
    "dmFyIGJ5U291cmNlID0ge307IHZhciBzb3VyY2VPcmRlciA9IFtdOwogIGZvciAodmFyIGkgPSAw" +
    "OyBpIDwgaGVhZGxpbmVzLmxlbmd0aDsgaSsrKSB7CiAgICB2YXIgc3JjID0gaGVhZGxpbmVzW2ld" +
    "LnNvdXJjZTsKICAgIGlmICghYnlTb3VyY2Vbc3JjXSkgeyBieVNvdXJjZVtzcmNdID0gW107IHNv" +
    "dXJjZU9yZGVyLnB1c2goc3JjKTsgfQogICAgYnlTb3VyY2Vbc3JjXS5wdXNoKGhlYWRsaW5lc1tp" +
    "XSk7CiAgfQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgcyA9IDA7IHMgPCBzb3VyY2VPcmRl" +
    "ci5sZW5ndGg7IHMrKykgewogICAgdmFyIHNyYyA9IHNvdXJjZU9yZGVyW3NdOwogICAgaHRtbCAr" +
    "PSAnPGRpdiBjbGFzcz0ic3JjLWdyb3VwIj4nICsgc3JjICsgJzwvZGl2Pic7CiAgICB2YXIgaXRl" +
    "bXMgPSBieVNvdXJjZVtzcmNdLnNsaWNlKDAsIDMpOwogICAgZm9yICh2YXIgaiA9IDA7IGogPCBp" +
    "dGVtcy5sZW5ndGg7IGorKykgewogICAgICB2YXIgaCA9IGl0ZW1zW2pdOwogICAgICBodG1sICs9" +
    "ICc8ZGl2IGNsYXNzPSJoZWFkbGluZS1pdGVtIj48ZGl2IGNsYXNzPSJoLWRvdCIgc3R5bGU9ImJh" +
    "Y2tncm91bmQ6JyArIHNyY0NvbG9yKHNyYykgKyAnIj48L2Rpdj48ZGl2PjxkaXYgY2xhc3M9Imgt" +
    "dGl0bGUiPicgKyBoLnRpdGxlICsgJzwvZGl2Pic7CiAgICAgIGlmIChoLnVybCkgaHRtbCArPSAn" +
    "PGEgY2xhc3M9ImgtbGluayIgaHJlZj0iJyArIGgudXJsICsgJyIgdGFyZ2V0PSJfYmxhbmsiPmxl" +
    "ZXMgbWVlcjwvYT4nOwogICAgICBodG1sICs9ICc8L2Rpdj48L2Rpdj4nOwogICAgfQogIH0KICBl" +
    "bC5pbm5lckhUTUwgPSBodG1sOwp9CgpmdW5jdGlvbiByZW5kZXJUcmVuZHMocmVnaW9uKSB7CiAg" +
    "dmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyZW5kcy1saXN0Jyk7CiAgaWYgKCF0" +
    "cmVuZHMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gdHJl" +
    "bmRzIGRldGVjdGVkLjwvZGl2Pic7IHJldHVybjsgfQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2" +
    "YXIgaSA9IDA7IGkgPCB0cmVuZHMubGVuZ3RoOyBpKyspIHsKICAgIHZhciB0ID0gdHJlbmRzW2ld" +
    "OyB2YXIgaXNTYXZlZCA9IGZhbHNlOwogICAgZm9yICh2YXIgcyA9IDA7IHMgPCBzYXZlZC5sZW5n" +
    "dGg7IHMrKykgeyBpZiAoc2F2ZWRbc10ubmFtZSA9PT0gdC5uYW1lKSB7IGlzU2F2ZWQgPSB0cnVl" +
    "OyBicmVhazsgfSB9CiAgICB2YXIgbWNNYXAgPSB7IHJpc2luZzogJ2ItcmlzaW5nJywgZW1lcmdp" +
    "bmc6ICdiLWVtZXJnaW5nJywgZXN0YWJsaXNoZWQ6ICdiLWVzdGFibGlzaGVkJywgc2hpZnRpbmc6" +
    "ICdiLXNoaWZ0aW5nJyB9OwogICAgdmFyIG1jID0gbWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1l" +
    "cmdpbmcnOwogICAgdmFyIGxpbmtzID0gdC5zb3VyY2VMaW5rcyB8fCBbXTsgdmFyIGxpbmtzSHRt" +
    "bCA9ICcnOwogICAgZm9yICh2YXIgbCA9IDA7IGwgPCBsaW5rcy5sZW5ndGg7IGwrKykgewogICAg" +
    "ICB2YXIgbGsgPSBsaW5rc1tsXTsKICAgICAgdmFyIGNsc01hcCA9IHsgcmVkZGl0OiAnc2wtcmVk" +
    "ZGl0JywgbmV3czogJ3NsLW5ld3MnLCB0cmVuZHM6ICdzbC10cmVuZHMnLCBsaWZlc3R5bGU6ICdz" +
    "bC1saWZlc3R5bGUnIH07CiAgICAgIHZhciBsYmxNYXAgPSB7IHJlZGRpdDogJ1InLCBuZXdzOiAn" +
    "TicsIHRyZW5kczogJ0cnLCBsaWZlc3R5bGU6ICdMJyB9OwogICAgICBsaW5rc0h0bWwgKz0gJzxh" +
    "IGNsYXNzPSJzb3VyY2UtbGluayIgaHJlZj0iJyArIGxrLnVybCArICciIHRhcmdldD0iX2JsYW5r" +
    "Ij48c3BhbiBjbGFzcz0ic2wtaWNvbiAnICsgKGNsc01hcFtsay50eXBlXSB8fCAnc2wtbmV3cycp" +
    "ICsgJyI+JyArIChsYmxNYXBbbGsudHlwZV0gfHwgJ04nKSArICc8L3NwYW4+PGRpdj48ZGl2IGNs" +
    "YXNzPSJzbC10aXRsZSI+JyArIGxrLnRpdGxlICsgJzwvZGl2PjxkaXYgY2xhc3M9InNsLXNvdXJj" +
    "ZSI+JyArIGxrLnNvdXJjZSArICc8L2Rpdj48L2Rpdj48L2E+JzsKICAgIH0KICAgIHZhciBjaGlw" +
    "cyA9ICcnOyB2YXIgc2wgPSB0LnNvdXJjZUxhYmVscyB8fCBbXTsKICAgIGZvciAodmFyIGMgPSAw" +
    "OyBjIDwgc2wubGVuZ3RoOyBjKyspIGNoaXBzICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIHNs" +
    "W2NdICsgJzwvc3Bhbj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtaXRlbSIgaWQ9" +
    "InRjLScgKyBpICsgJyI+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5kLXJvdzEiPjxk" +
    "aXYgY2xhc3M9InRyZW5kLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+PHNwYW4gY2xhc3M9ImJh" +
    "ZGdlICcgKyBtYyArICciPicgKyB0Lm1vbWVudHVtICsgJzwvc3Bhbj48L2Rpdj4nOwogICAgaHRt" +
    "bCArPSAnPGRpdiBjbGFzcz0idHJlbmQtZGVzYyI+JyArIHQuZGVzYyArICc8L2Rpdj4nOwogICAg" +
    "aHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtc2lnbmFscyI+JyArIHQuc2lnbmFscyArICc8L2Rp" +
    "dj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtYWN0aW9ucyI+PGRpdiBjbGFzcz0i" +
    "Y2hpcHMiPicgKyBjaGlwcyArICc8L2Rpdj48ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjVw" +
    "eCI+JzsKICAgIGlmIChsaW5rcy5sZW5ndGgpIGh0bWwgKz0gJzxidXR0b24gY2xhc3M9ImFjdC1i" +
    "dG4iIG9uY2xpY2s9InRvZ2dsZUJveChcJ3NyYy0nICsgaSArICdcJykiPnNvdXJjZXM8L2J1dHRv" +
    "bj4nOwogICAgaWYgKHQuZm9ybWF0SGludCkgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0iYWN0LWJ0" +
    "biIgb25jbGljaz0idG9nZ2xlQm94KFwnaGludC0nICsgaSArICdcJykiPmZvcm1hdDwvYnV0dG9u" +
    "Pic7CiAgICBodG1sICs9ICc8YnV0dG9uIGNsYXNzPSJhY3QtYnRuJyArIChpc1NhdmVkID8gJyBz" +
    "YXZlZCcgOiAnJykgKyAnIiBpZD0ic2ItJyArIGkgKyAnIiBvbmNsaWNrPSJkb1NhdmUoJyArIGkg" +
    "KyAnLFwnJyArIHJlZ2lvbiArICdcJykiPicgKyAoaXNTYXZlZCA/ICdzYXZlZCcgOiAnc2F2ZScp" +
    "ICsgJzwvYnV0dG9uPic7CiAgICBodG1sICs9ICc8L2Rpdj48L2Rpdj4nOwogICAgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0iZXhwYW5kLWJveCIgaWQ9InNyYy0nICsgaSArICciPicgKyAobGlua3NIdG1s" +
    "IHx8ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCkiPk5vIHNv" +
    "dXJjZSBsaW5rcy48L2Rpdj4nKSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0i" +
    "aGludC1ib3giIGlkPSJoaW50LScgKyBpICsgJyI+JyArICh0LmZvcm1hdEhpbnQgfHwgJycpICsg" +
    "JzwvZGl2Pic7CiAgICBodG1sICs9ICc8L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1s" +
    "Owp9CgpmdW5jdGlvbiB0b2dnbGVCb3goaWQpIHsKICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZChpZCk7CiAgaWYgKGVsKSBlbC5zdHlsZS5kaXNwbGF5ID0gZWwuc3R5bGUuZGlzcGxh" +
    "eSA9PT0gJ2Jsb2NrJyA/ICdub25lJyA6ICdibG9jayc7Cn0KCmZ1bmN0aW9uIGRvU2F2ZShpLCBy" +
    "ZWdpb24pIHsKICB2YXIgdCA9IHRyZW5kc1tpXTsKICBmb3IgKHZhciBzID0gMDsgcyA8IHNhdmVk" +
    "Lmxlbmd0aDsgcysrKSB7IGlmIChzYXZlZFtzXS5uYW1lID09PSB0Lm5hbWUpIHJldHVybjsgfQog" +
    "IHNhdmVkLnB1c2goeyBuYW1lOiB0Lm5hbWUsIGRlc2M6IHQuZGVzYywgdGFnOiAnJyB9KTsKICBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2ItJyArIGkpLnRleHRDb250ZW50ID0gJ3NhdmVkJzsK" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2ItJyArIGkpLmNsYXNzTGlzdC5hZGQoJ3NhdmVk" +
    "Jyk7CiAgcmVuZGVyU2F2ZWQoKTsKICBmZXRjaCgnL2FyY2hpdmUvc2F2ZScsIHsgbWV0aG9kOiAn" +
    "UE9TVCcsIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBi" +
    "b2R5OiBKU09OLnN0cmluZ2lmeSh7IG5hbWU6IHQubmFtZSwgZGVzYzogdC5kZXNjLCBtb21lbnR1" +
    "bTogdC5tb21lbnR1bSwgc2lnbmFsczogdC5zaWduYWxzLCBzb3VyY2VfbGFiZWxzOiB0LnNvdXJj" +
    "ZUxhYmVscyB8fCBbXSwgc291cmNlX2xpbmtzOiB0LnNvdXJjZUxpbmtzIHx8IFtdLCBmb3JtYXRf" +
    "aGludDogdC5mb3JtYXRIaW50LCB0YWc6ICcnLCByZWdpb246IHJlZ2lvbiB8fCAnbmwnIH0pIH0p" +
    "CiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsgY29uc29sZS5lcnJvcignYXJjaGl2ZSBzYXZlIGZhaWxl" +
    "ZCcsIGUpOyB9KTsKfQoKZnVuY3Rpb24gcmVuZGVyU2F2ZWQoKSB7CiAgdmFyIGVsID0gZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ3NhdmVkLWxpc3QnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJ" +
    "ZCgnZ2VuLXJvdycpLnN0eWxlLmRpc3BsYXkgPSBzYXZlZC5sZW5ndGggPyAnJyA6ICdub25lJzsK" +
    "ICBpZiAoIXNhdmVkLmxlbmd0aCkgeyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHki" +
    "Pk5vIHNhdmVkIHRyZW5kcyB5ZXQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIGh0bWwgPSAnJzsK" +
    "ICBmb3IgKHZhciBpID0gMDsgaSA8IHNhdmVkLmxlbmd0aDsgaSsrKSB7CiAgICB2YXIgdCA9IHNh" +
    "dmVkW2ldOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0ic2F2ZWQtaXRlbSI+PGRpdiBjbGFzcz0i" +
    "c2F2ZWQtbmFtZSI+JyArIHQubmFtZSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBzdHls" +
    "ZT0iZGlzcGxheTpmbGV4O2dhcDo2cHg7YWxpZ24taXRlbXM6Y2VudGVyIj48aW5wdXQgY2xhc3M9" +
    "InRhZy1pbnB1dCIgcGxhY2Vob2xkZXI9InRhZy4uLiIgdmFsdWU9IicgKyB0LnRhZyArICciIG9u" +
    "aW5wdXQ9InNhdmVkWycgKyBpICsgJ10udGFnPXRoaXMudmFsdWUiLz4nOwogICAgaHRtbCArPSAn" +
    "PHNwYW4gc3R5bGU9ImN1cnNvcjpwb2ludGVyO2ZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11" +
    "dGVkKSIgb25jbGljaz0ic2F2ZWQuc3BsaWNlKCcgKyBpICsgJywxKTtyZW5kZXJTYXZlZCgpIj4m" +
    "I3gyNzE1Ozwvc3Bhbj48L2Rpdj48L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9" +
    "Cgp2YXIgZ2VuZXJhdGVkRm9ybWF0cyA9IFtdOwoKZnVuY3Rpb24gZ2VuZXJhdGVGb3JtYXRzKCkg" +
    "ewogIGlmICghc2F2ZWQubGVuZ3RoKSByZXR1cm47CiAgc3dpdGNoVGFiKCdmb3JtYXRzJyk7CiAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbCcpLnN0eWxlLmRpc3BsYXkgPSAnbm9u" +
    "ZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9" +
    "ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlJlYWRpbmcg" +
    "eW91ciBjYXRhbG9ndWUgJmFtcDsgZ2VuZXJhdGluZyBpZGVhcy4uLjwvZGl2Pic7CiAgZmV0Y2go" +
    "Jy9nZW5lcmF0ZS1mb3JtYXRzJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7" +
    "ICdDb250ZW50LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3Ry" +
    "aW5naWZ5KHsgdHJlbmRzOiBzYXZlZCB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1" +
    "cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24ocmVzdWx0KSB7CiAgICBpZiAocmVzdWx0" +
    "LmVycm9yKSB0aHJvdyBuZXcgRXJyb3IocmVzdWx0LmVycm9yKTsKICAgIHZhciBmb3JtYXRzID0g" +
    "cmVzdWx0LmZvcm1hdHMgfHwgW107CiAgICBpZiAoIWZvcm1hdHMubGVuZ3RoKSB0aHJvdyBuZXcg" +
    "RXJyb3IoJ05vIGZvcm1hdHMgcmV0dXJuZWQnKTsKICAgIGdlbmVyYXRlZEZvcm1hdHMgPSBmb3Jt" +
    "YXRzOwogICAgdmFyIGh0bWwgPSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgZm9ybWF0cy5s" +
    "ZW5ndGg7IGkrKykgewogICAgICB2YXIgZiA9IGZvcm1hdHNbaV07CiAgICAgIGh0bWwgKz0gJzxk" +
    "aXYgY2xhc3M9ImZvcm1hdC1pdGVtIj4nOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3Jt" +
    "YXQtdGl0bGUiPicgKyBmLnRpdGxlICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xh" +
    "c3M9ImZvcm1hdC1sb2dsaW5lIj4nICsgZi5sb2dsaW5lICsgJzwvZGl2Pic7CiAgICAgIGh0bWwg" +
    "Kz0gJzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6NnB4O2ZsZXgtd3JhcDp3cmFwO21hcmdp" +
    "bi10b3A6NXB4Ij4nOwogICAgICBodG1sICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIGYuY2hh" +
    "bm5lbCArICc8L3NwYW4+JzsKICAgICAgaHRtbCArPSAnPHNwYW4gY2xhc3M9ImNoaXAiPicgKyBm" +
    "LnRyZW5kQmFzaXMgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICAgIGlm" +
    "IChmLmhvb2spIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1hdC1ob29rIj4iJyArIGYuaG9vayAr" +
    "ICciPC9kaXY+JzsKICAgICAgaWYgKGYud2h5TmV3KSBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250" +
    "LXNpemU6MTFweDtjb2xvcjp2YXIoLS1ncmVlbik7bWFyZ2luLXRvcDo1cHg7Zm9udC1zdHlsZTpp" +
    "dGFsaWMiPicgKyBmLndoeU5ldyArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8YnV0dG9uIGNs" +
    "YXNzPSJkZXYtYnRuIiBvbmNsaWNrPSJzdGFydERldmVsb3BtZW50KCcgKyBpICsgJykiPiYjOTY2" +
    "MDsgRGV2ZWxvcCB0aGlzIGZvcm1hdDwvYnV0dG9uPic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7" +
    "CiAgICB9CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZm9ybWF0cy1saXN0JykuaW5uZXJI" +
    "VE1MID0gaHRtbDsKICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7CiAgICBzaG93RXJyKCdGb3Jt" +
    "YXQgZ2VuZXJhdGlvbiBmYWlsZWQ6ICcgKyBlLm1lc3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxl" +
    "bWVudEJ5SWQoJ2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+" +
    "RmFpbGVkLjwvZGl2Pic7CiAgfSk7Cn0KCi8vIOKUgOKUgCBGb3JtYXQgZGV2ZWxvcG1lbnQgY2hh" +
    "dCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKdmFyIGRldk1lc3NhZ2Vz" +
    "ID0gW107CnZhciBkZXZGb3JtYXQgPSBudWxsOwoKZnVuY3Rpb24gc3RhcnREZXZlbG9wbWVudChp" +
    "KSB7CiAgZGV2Rm9ybWF0ID0gZ2VuZXJhdGVkRm9ybWF0c1tpXSB8fCBudWxsOwogIGRldk1lc3Nh" +
    "Z2VzID0gW107CiAgdmFyIHBhbmVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5l" +
    "bCcpOwogIHZhciBjaGF0ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1jaGF0Jyk7CiAg" +
    "cGFuZWwuc3R5bGUuZGlzcGxheSA9ICcnOwogIGNoYXQuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9" +
    "ImVtcHR5Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+U3RhcnRpbmcgZGV2ZWxvcG1lbnQg" +
    "c2Vzc2lvbi4uLjwvZGl2Pic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbC1z" +
    "dWJ0aXRsZScpLnRleHRDb250ZW50ID0gJ0RldmVsb3Bpbmc6ICcgKyAoZGV2Rm9ybWF0ID8gZGV2" +
    "Rm9ybWF0LnRpdGxlIDogJ0Zvcm1hdCBpZGVhJyk7CiAgcGFuZWwuc2Nyb2xsSW50b1ZpZXcoeyBi" +
    "ZWhhdmlvcjogJ3Ntb290aCcsIGJsb2NrOiAnc3RhcnQnIH0pOwoKICAvLyBPcGVuaW5nIG1lc3Nh" +
    "Z2UgZnJvbSB0aGUgQUkKICBmZXRjaCgnL2RldmVsb3AnLCB7CiAgICBtZXRob2Q6ICdQT1NUJywK" +
    "ICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LAogICAg" +
    "Ym9keTogSlNPTi5zdHJpbmdpZnkoewogICAgICBmb3JtYXRfaWRlYTogZGV2Rm9ybWF0LAogICAg" +
    "ICB0cmVuZHM6IHNhdmVkLAogICAgICBtZXNzYWdlczogW3sKICAgICAgICByb2xlOiAndXNlcics" +
    "CiAgICAgICAgY29udGVudDogJ0kgd2FudCB0byBkZXZlbG9wIHRoaXMgZm9ybWF0IGlkZWEuIEhl" +
    "cmUgaXMgd2hhdCB3ZSBoYXZlIHNvIGZhcjogVGl0bGU6ICInICsgKGRldkZvcm1hdCA/IGRldkZv" +
    "cm1hdC50aXRsZSA6ICcnKSArICciLiBMb2dsaW5lOiAnICsgKGRldkZvcm1hdCA/IGRldkZvcm1h" +
    "dC5sb2dsaW5lIDogJycpICsgJy4gUGxlYXNlIHN0YXJ0IG91ciBkZXZlbG9wbWVudCBzZXNzaW9u" +
    "LicKICAgICAgfV0KICAgIH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpz" +
    "b24oKTsgfSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3" +
    "IEVycm9yKGQuZXJyb3IpOwogICAgZGV2TWVzc2FnZXMgPSBbCiAgICAgIHsgcm9sZTogJ3VzZXIn" +
    "LCBjb250ZW50OiAnSSB3YW50IHRvIGRldmVsb3AgdGhpcyBmb3JtYXQgaWRlYS4gSGVyZSBpcyB3" +
    "aGF0IHdlIGhhdmUgc28gZmFyOiBUaXRsZTogIicgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LnRp" +
    "dGxlIDogJycpICsgJyIuIExvZ2xpbmU6ICcgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LmxvZ2xp" +
    "bmUgOiAnJykgKyAnLiBQbGVhc2Ugc3RhcnQgb3VyIGRldmVsb3BtZW50IHNlc3Npb24uJyB9LAog" +
    "ICAgICB7IHJvbGU6ICdhc3Npc3RhbnQnLCBjb250ZW50OiBkLnJlc3BvbnNlIH0KICAgIF07CiAg" +
    "ICByZW5kZXJEZXZDaGF0KCk7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgY2hhdC5p" +
    "bm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPkNvdWxkIG5vdCBzdGFydCBzZXNzaW9uOiAn" +
    "ICsgZS5tZXNzYWdlICsgJzwvZGl2Pic7CiAgfSk7Cn0KCmZ1bmN0aW9uIHNlbmREZXZNZXNzYWdl" +
    "KCkgewogIHZhciBpbnB1dCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtaW5wdXQnKTsK" +
    "ICB2YXIgbXNnID0gaW5wdXQudmFsdWUudHJpbSgpOwogIGlmICghbXNnIHx8ICFkZXZGb3JtYXQp" +
    "IHJldHVybjsKICBpbnB1dC52YWx1ZSA9ICcnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdk" +
    "ZXYtc2VuZCcpLmRpc2FibGVkID0gdHJ1ZTsKCiAgZGV2TWVzc2FnZXMucHVzaCh7IHJvbGU6ICd1" +
    "c2VyJywgY29udGVudDogbXNnIH0pOwogIHJlbmRlckRldkNoYXQoKTsKCiAgZmV0Y2goJy9kZXZl" +
    "bG9wJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUn" +
    "OiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsKICAgICAg" +
    "Zm9ybWF0X2lkZWE6IGRldkZvcm1hdCwKICAgICAgdHJlbmRzOiBzYXZlZCwKICAgICAgbWVzc2Fn" +
    "ZXM6IGRldk1lc3NhZ2VzCiAgICB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4g" +
    "ci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgaWYgKGQuZXJyb3IpIHRocm93" +
    "IG5ldyBFcnJvcihkLmVycm9yKTsKICAgIGRldk1lc3NhZ2VzLnB1c2goeyByb2xlOiAnYXNzaXN0" +
    "YW50JywgY29udGVudDogZC5yZXNwb25zZSB9KTsKICAgIHJlbmRlckRldkNoYXQoKTsKICAgIGRv" +
    "Y3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtc2VuZCcpLmRpc2FibGVkID0gZmFsc2U7CiAgICBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LWlucHV0JykuZm9jdXMoKTsKICB9KQogIC5jYXRj" +
    "aChmdW5jdGlvbihlKSB7CiAgICBkZXZNZXNzYWdlcy5wdXNoKHsgcm9sZTogJ2Fzc2lzdGFudCcs" +
    "IGNvbnRlbnQ6ICdTb3JyeSwgc29tZXRoaW5nIHdlbnQgd3Jvbmc6ICcgKyBlLm1lc3NhZ2UgfSk7" +
    "CiAgICByZW5kZXJEZXZDaGF0KCk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXNl" +
    "bmQnKS5kaXNhYmxlZCA9IGZhbHNlOwogIH0pOwp9CgpmdW5jdGlvbiByZW5kZXJEZXZDaGF0KCkg" +
    "ewogIHZhciBjaGF0ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1jaGF0Jyk7CiAgdmFy" +
    "IGh0bWwgPSAnJzsKICBmb3IgKHZhciBpID0gMDsgaSA8IGRldk1lc3NhZ2VzLmxlbmd0aDsgaSsr" +
    "KSB7CiAgICB2YXIgbSA9IGRldk1lc3NhZ2VzW2ldOwogICAgdmFyIGNscyA9IG0ucm9sZSA9PT0g" +
    "J2Fzc2lzdGFudCcgPyAnYWknIDogJ3VzZXInOwogICAgdmFyIHRleHQgPSBtLmNvbnRlbnQucmVw" +
    "bGFjZSgvXG4vZywgJzxicj4nKTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImRldi1tc2cgJyAr" +
    "IGNscyArICciPicgKyB0ZXh0ICsgJzwvZGl2Pic7CiAgfQogIGNoYXQuaW5uZXJIVE1MID0gaHRt" +
    "bDsKICBjaGF0LnNjcm9sbFRvcCA9IGNoYXQuc2Nyb2xsSGVpZ2h0Owp9CgpmdW5jdGlvbiBsb2Fk" +
    "UmVzZWFyY2goKSB7CiAgZmV0Y2goJy9yZXNlYXJjaCcpLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1" +
    "cm4gci5qc29uKCk7IH0pLnRoZW4oZnVuY3Rpb24oZCkgeyByZW5kZXJSZXNlYXJjaChkLml0ZW1z" +
    "IHx8IFtdKTsgfSkKICAuY2F0Y2goZnVuY3Rpb24oKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlk" +
    "KCdyZXNlYXJjaC1mZWVkJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5Db3VsZCBu" +
    "b3QgbG9hZCByZXNlYXJjaC48L2Rpdj4nOyB9KTsKfQoKZnVuY3Rpb24gcmVuZGVyUmVzZWFyY2go" +
    "aXRlbXMpIHsKICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVzZWFyY2gtZmVl" +
    "ZCcpOwogIGlmICghaXRlbXMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJl" +
    "bXB0eSI+Tm8gcmVzZWFyY2ggaXRlbXMgZm91bmQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIHR5" +
    "cGVNYXAgPSB7IHJlc2VhcmNoOiAnUmVzZWFyY2gnLCBjdWx0dXJlOiAnQ3VsdHVyZScsIHRyZW5k" +
    "czogJ1RyZW5kcycgfTsgdmFyIGh0bWwgPSAnJzsKICBmb3IgKHZhciBpID0gMDsgaSA8IGl0ZW1z" +
    "Lmxlbmd0aDsgaSsrKSB7CiAgICB2YXIgaXRlbSA9IGl0ZW1zW2ldOwogICAgaHRtbCArPSAnPGRp" +
    "diBjbGFzcz0icmVzZWFyY2gtaXRlbSI+PGRpdiBjbGFzcz0icmVzZWFyY2gtdGl0bGUiPjxhIGhy" +
    "ZWY9IicgKyBpdGVtLnVybCArICciIHRhcmdldD0iX2JsYW5rIj4nICsgaXRlbS50aXRsZSArICc8" +
    "L2E+PC9kaXY+JzsKICAgIGlmIChpdGVtLmRlc2MpIGh0bWwgKz0gJzxkaXYgY2xhc3M9InJlc2Vh" +
    "cmNoLWRlc2MiPicgKyBpdGVtLmRlc2MgKyAnPC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xh" +
    "c3M9InJlc2VhcmNoLW1ldGEiPjxzcGFuIGNsYXNzPSJyLXNyYyI+JyArIGl0ZW0uc291cmNlICsg" +
    "Jzwvc3Bhbj48c3BhbiBjbGFzcz0ici10eXBlIj4nICsgKHR5cGVNYXBbaXRlbS50eXBlXSB8fCBp" +
    "dGVtLnR5cGUpICsgJzwvc3Bhbj48L2Rpdj48L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBo" +
    "dG1sOwp9CgpmdW5jdGlvbiBkb0FyY2hpdmVTZWFyY2goKSB7CiAgdmFyIHF1ZXJ5ID0gZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtc2VhcmNoLWlucHV0JykudmFsdWUudHJpbSgpOwog" +
    "IGlmICghcXVlcnkpIHJldHVybjsKICB2YXIgcmVzdWx0c0VsID0gZG9jdW1lbnQuZ2V0RWxlbWVu" +
    "dEJ5SWQoJ3NlYXJjaC1yZXN1bHRzJyk7CiAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0" +
    "eWxlPSJmb250LXNpemU6MTJweDtjb2xvcjp2YXIoLS1tdXRlZCkiPjxzcGFuIGNsYXNzPSJsb2Fk" +
    "ZXIiPjwvc3Bhbj5TZWFyY2hpbmcgYXJjaGl2ZS4uLjwvZGl2Pic7CgogIGZldGNoKCcvYXJjaGl2" +
    "ZS9zZWFyY2gnLCB7CiAgICBtZXRob2Q6ICdQT1NUJywKICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQt" +
    "VHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LAogICAgYm9keTogSlNPTi5zdHJpbmdpZnkoeyBx" +
    "dWVyeTogcXVlcnkgfSkKICB9KQogIC50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigp" +
    "OyB9KQogIC50aGVuKGZ1bmN0aW9uKGQpIHsKICAgIGlmIChkLmVycm9yKSB0aHJvdyBuZXcgRXJy" +
    "b3IoZC5lcnJvcik7CiAgICB2YXIgcmVzdWx0cyA9IGQucmVzdWx0cyB8fCBbXTsKICAgIGlmICgh" +
    "cmVzdWx0cy5sZW5ndGgpIHsKICAgICAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxl" +
    "PSJmb250LXNpemU6MTJweDtjb2xvcjp2YXIoLS1tdXRlZCk7cGFkZGluZzo4cHggMCI+Tm8gcmVs" +
    "ZXZhbnQgdHJlbmRzIGZvdW5kIGZvciAiJyArIHF1ZXJ5ICsgJyIuPC9kaXY+JzsKICAgICAgcmV0" +
    "dXJuOwogICAgfQogICAgdmFyIG1jTWFwID0geyByaXNpbmc6ICdiLXJpc2luZycsIGVtZXJnaW5n" +
    "OiAnYi1lbWVyZ2luZycsIGVzdGFibGlzaGVkOiAnYi1lc3RhYmxpc2hlZCcsIHNoaWZ0aW5nOiAn" +
    "Yi1zaGlmdGluZycgfTsKICAgIHZhciBodG1sID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMHB4" +
    "O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10cmFuc2Zvcm06dXBwZXJj" +
    "YXNlO2xldHRlci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBweCI+JyArIHJlc3VsdHMu" +
    "bGVuZ3RoICsgJyByZWxldmFudCB0cmVuZHMgZm91bmQ8L2Rpdj4nOwogICAgZm9yICh2YXIgaSA9" +
    "IDA7IGkgPCByZXN1bHRzLmxlbmd0aDsgaSsrKSB7CiAgICAgIHZhciB0ID0gcmVzdWx0c1tpXTsK" +
    "ICAgICAgdmFyIG1jID0gbWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1lcmdpbmcnOwogICAgICBo" +
    "dG1sICs9ICc8ZGl2IHN0eWxlPSJwYWRkaW5nOjEycHggMDtib3JkZXItYm90dG9tOjFweCBzb2xp" +
    "ZCB2YXIoLS1ib3JkZXIpIj4nOwogICAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZs" +
    "ZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDo4cHg7bWFyZ2luLWJvdHRvbTo1cHgiPic7CiAgICAg" +
    "IGh0bWwgKz0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xv" +
    "cjojZmZmIj4nICsgdC5uYW1lICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxzcGFuIGNsYXNz" +
    "PSJiYWRnZSAnICsgbWMgKyAnIj4nICsgKHQubW9tZW50dW0gfHwgJycpICsgJzwvc3Bhbj4nOwog" +
    "ICAgICBodG1sICs9ICc8c3BhbiBzdHlsZT0iZm9udC1zaXplOjEwcHg7Y29sb3I6dmFyKC0tbXV0" +
    "ZWQpIj4nICsgdC5zYXZlZF9hdC5zbGljZSgwLDEwKSArICc8L3NwYW4+JzsKICAgICAgaHRtbCAr" +
    "PSAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjEycHg7Y29s" +
    "b3I6dmFyKC0tbXV0ZWQpO2xpbmUtaGVpZ2h0OjEuNTttYXJnaW4tYm90dG9tOjVweCI+JyArICh0" +
    "LmRlc2MgfHwgJycpICsgJzwvZGl2Pic7CiAgICAgIGlmICh0LnJlbGV2YW5jZSkgaHRtbCArPSAn" +
    "PGRpdiBzdHlsZT0iZm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tYWNjZW50Mik7Zm9udC1zdHls" +
    "ZTppdGFsaWMiPicgKyB0LnJlbGV2YW5jZSArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8L2Rp" +
    "dj4nOwogICAgfQogICAgcmVzdWx0c0VsLmlubmVySFRNTCA9IGh0bWw7CiAgfSkKICAuY2F0Y2go" +
    "ZnVuY3Rpb24oZSkgewogICAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxlPSJmb250" +
    "LXNpemU6MTJweDtjb2xvcjojZmNhNWE1Ij5TZWFyY2ggZmFpbGVkOiAnICsgZS5tZXNzYWdlICsg" +
    "JzwvZGl2Pic7CiAgfSk7Cn0KCmZ1bmN0aW9uIGxvYWRBcmNoaXZlKCkgewogIGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdkYXRlLWxpc3QnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHki" +
    "IHN0eWxlPSJwYWRkaW5nOjFyZW0gMCI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPjwvZGl2" +
    "Pic7CiAgZmV0Y2goJy9hcmNoaXZlL2RhdGVzJykudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiBy" +
    "Lmpzb24oKTsgfSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoIWQuZGF0ZXMgfHwgIWQu" +
    "ZGF0ZXMubGVuZ3RoKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkYXRlLWxpc3QnKS5pbm5l" +
    "ckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiIHN0eWxlPSJwYWRkaW5nOjFyZW0gMDtmb250LXNp" +
    "emU6MTFweCI+Tm8gYXJjaGl2ZWQgdHJlbmRzIHlldC48L2Rpdj4nOyByZXR1cm47IH0KICAgIHZh" +
    "ciBodG1sID0gJyc7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IGQuZGF0ZXMubGVuZ3RoOyBpKysp" +
    "IHsgaHRtbCArPSAnPGRpdiBjbGFzcz0iZGF0ZS1pdGVtIiBvbmNsaWNrPSJsb2FkRGF0ZShcJycg" +
    "KyBkLmRhdGVzW2ldLmRhdGUgKyAnXCcsdGhpcykiPicgKyBkLmRhdGVzW2ldLmRhdGUgKyAnPHNw" +
    "YW4gY2xhc3M9ImRhdGUtY291bnQiPicgKyBkLmRhdGVzW2ldLmNvdW50ICsgJzwvc3Bhbj48L2Rp" +
    "dj4nOyB9CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0JykuaW5uZXJIVE1M" +
    "ID0gaHRtbDsKICAgIHZhciBmaXJzdCA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoJy5kYXRlLWl0" +
    "ZW0nKTsgaWYgKGZpcnN0KSBmaXJzdC5jbGljaygpOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUp" +
    "IHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtZXJyJykuaW5uZXJIVE1MID0gJzxk" +
    "aXYgY2xhc3M9ImVycmJveCI+Q291bGQgbm90IGxvYWQgYXJjaGl2ZTogJyArIGUubWVzc2FnZSAr" +
    "ICc8L2Rpdj4nOyB9KTsKfQoKZnVuY3Rpb24gbG9hZERhdGUoZGF0ZSwgZWwpIHsKICB2YXIgaXRl" +
    "bXMgPSBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcuZGF0ZS1pdGVtJyk7IGZvciAodmFyIGkg" +
    "PSAwOyBpIDwgaXRlbXMubGVuZ3RoOyBpKyspIGl0ZW1zW2ldLmNsYXNzTGlzdC5yZW1vdmUoJ2Fj" +
    "dGl2ZScpOwogIGVsLmNsYXNzTGlzdC5hZGQoJ2FjdGl2ZScpOwogIGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdhcmNoaXZlLWhlYWRpbmcnKS50ZXh0Q29udGVudCA9ICdTYXZlZCBvbiAnICsgZGF0" +
    "ZTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1M" +
    "ID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+PC9kaXY+" +
    "JzsKICBmZXRjaCgnL2FyY2hpdmUvYnktZGF0ZT9kYXRlPScgKyBlbmNvZGVVUklDb21wb25lbnQo" +
    "ZGF0ZSkpLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVu" +
    "Y3Rpb24oZCkgewogICAgaWYgKCFkLnRyZW5kcyB8fCAhZC50cmVuZHMubGVuZ3RoKSB7IGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBj" +
    "bGFzcz0iZW1wdHkiPk5vIHRyZW5kcyBmb3IgdGhpcyBkYXRlLjwvZGl2Pic7IHJldHVybjsgfQog" +
    "ICAgdmFyIGh0bWwgPSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgZC50cmVuZHMubGVuZ3Ro" +
    "OyBpKyspIHsKICAgICAgdmFyIHQgPSBkLnRyZW5kc1tpXTsKICAgICAgdmFyIG1jTWFwID0geyBy" +
    "aXNpbmc6ICdiLXJpc2luZycsIGVtZXJnaW5nOiAnYi1lbWVyZ2luZycsIGVzdGFibGlzaGVkOiAn" +
    "Yi1lc3RhYmxpc2hlZCcsIHNoaWZ0aW5nOiAnYi1zaGlmdGluZycgfTsKICAgICAgdmFyIG1jID0g" +
    "bWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1lcmdpbmcnOyB2YXIgbGlua3MgPSBbXTsKICAgICAg" +
    "dHJ5IHsgbGlua3MgPSBKU09OLnBhcnNlKHQuc291cmNlX2xpbmtzIHx8ICdbXScpOyB9IGNhdGNo" +
    "KGUpIHt9CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gtaXRlbSI+PGRpdiBzdHlsZT0i" +
    "ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6OHB4O21hcmdpbi1ib3R0b206M3B4" +
    "Ij48ZGl2IGNsYXNzPSJhcmNoLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+PHNwYW4gY2xhc3M9" +
    "ImJhZGdlICcgKyBtYyArICciPicgKyAodC5tb21lbnR1bSB8fCAnJykgKyAnPC9zcGFuPjwvZGl2" +
    "Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gtbWV0YSI+JyArIHQuc2F2ZWRfYXQg" +
    "KyAodC5yZWdpb24gPyAnICZtaWRkb3Q7ICcgKyB0LnJlZ2lvbi50b1VwcGVyQ2FzZSgpIDogJycp" +
    "ICsgKHQudGFnID8gJyAmbWlkZG90OyAnICsgdC50YWcgOiAnJykgKyAnPC9kaXY+JzsKICAgICAg" +
    "aHRtbCArPSAnPGRpdiBjbGFzcz0iYXJjaC1kZXNjIj4nICsgKHQuZGVzYyB8fCAnJykgKyAnPC9k" +
    "aXY+JzsKICAgICAgZm9yICh2YXIgbCA9IDA7IGwgPCBsaW5rcy5sZW5ndGg7IGwrKykgeyBodG1s" +
    "ICs9ICc8YSBjbGFzcz0iYXJjaC1saW5rIiBocmVmPSInICsgbGlua3NbbF0udXJsICsgJyIgdGFy" +
    "Z2V0PSJfYmxhbmsiPicgKyBsaW5rc1tsXS50aXRsZSArICc8L2E+JzsgfQogICAgICBodG1sICs9" +
    "ICc8L2Rpdj4nOwogICAgfQogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtY29u" +
    "dGVudCcpLmlubmVySFRNTCA9IGh0bWw7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oKSB7IGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBj" +
    "bGFzcz0iZW1wdHkiPkNvdWxkIG5vdCBsb2FkLjwvZGl2Pic7IH0pOwp9Cjwvc2NyaXB0Pgo8L2Jv" +
    "ZHk+CjwvaHRtbD4K"
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
