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
    "L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9ImRldi1wYW5lbCIgaWQ9ImRldi1wYW5lbCIgc3R5bGU9" +
    "Im1hcmdpbi10b3A6MTZweCI+CiAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsLWhlYWRlciI+" +
    "CiAgICAgICAgICA8ZGl2IGNsYXNzPSJkZXYtcGFuZWwtdGl0bGUiPiYjOTY3OTsgRm9ybWF0IERl" +
    "dmVsb3BtZW50IFNlc3Npb248L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImRldi1wYW5lbC1z" +
    "dWJ0aXRsZSIgaWQ9ImRldi1wYW5lbC1zdWJ0aXRsZSI+RGV2ZWxvcGluZzogJm1kYXNoOzwvZGl2" +
    "PgogICAgICAgIDwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImRldi1jaGF0IiBpZD0iZGV2LWNo" +
    "YXQiPjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImRldi1pbnB1dC1yb3ciPgogICAgICAgICAg" +
    "PGlucHV0IGNsYXNzPSJkZXYtaW5wdXQiIGlkPSJkZXYtaW5wdXQiIHR5cGU9InRleHQiIHBsYWNl" +
    "aG9sZGVyPSJSZXBseSB0byB5b3VyIGRldmVsb3BtZW50IGV4ZWMuLi4iIG9ua2V5ZG93bj0iaWYo" +
    "ZXZlbnQua2V5PT09J0VudGVyJylzZW5kRGV2TWVzc2FnZSgpIiAvPgogICAgICAgICAgPGJ1dHRv" +
    "biBjbGFzcz0iZGV2LXNlbmQiIGlkPSJkZXYtc2VuZCIgb25jbGljaz0ic2VuZERldk1lc3NhZ2Uo" +
    "KSI+U2VuZDwvYnV0dG9uPgogICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4KICAgIDwvZGl2PgoK" +
    "ICAgIDxkaXYgaWQ9InZpZXctYXJjaGl2ZSIgc3R5bGU9ImRpc3BsYXk6bm9uZSI+CiAgICAgIDxk" +
    "aXYgaWQ9ImFyY2hpdmUtZXJyIj48L2Rpdj4KCiAgICAgIDwhLS0gU2VtYW50aWMgc2VhcmNoIGJh" +
    "ciAtLT4KICAgICAgPGRpdiBjbGFzcz0iY2FyZCIgc3R5bGU9Im1hcmdpbi1ib3R0b206MTZweCI+" +
    "CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0bGUi" +
    "PlNlYXJjaCBhcmNoaXZlIGJ5IGNvbmNlcHQgb3IgZm9ybWF0IGlkZWE8L2Rpdj48L2Rpdj4KICAg" +
    "ICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHkiIHN0eWxlPSJwYWRkaW5nOjE0cHggMTZweCI+CiAg" +
    "ICAgICAgICA8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjEwcHg7YWxpZ24taXRlbXM6Y2Vu" +
    "dGVyIj4KICAgICAgICAgICAgPGlucHV0IGlkPSJhcmNoaXZlLXNlYXJjaC1pbnB1dCIgdHlwZT0i" +
    "dGV4dCIKICAgICAgICAgICAgICBwbGFjZWhvbGRlcj0iZS5nLiAnZWVuemFhbWhlaWQgb25kZXIg" +
    "am9uZ2VyZW4nIG9yICdmYW1pbGllcyB1bmRlciBwcmVzc3VyZScuLi4iCiAgICAgICAgICAgICAg" +
    "c3R5bGU9ImZsZXg6MTtmb250LXNpemU6MTNweDtwYWRkaW5nOjlweCAxNHB4O2JvcmRlci1yYWRp" +
    "dXM6OHB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyMik7YmFja2dyb3VuZDpyZ2JhKDI1" +
    "NSwyNTUsMjU1LDAuMDQpO2NvbG9yOnZhcigtLXRleHQpO291dGxpbmU6bm9uZSIKICAgICAgICAg" +
    "ICAgICBvbmtleWRvd249ImlmKGV2ZW50LmtleT09PSdFbnRlcicpZG9BcmNoaXZlU2VhcmNoKCki" +
    "CiAgICAgICAgICAgIC8+CiAgICAgICAgICAgIDxidXR0b24gb25jbGljaz0iZG9BcmNoaXZlU2Vh" +
    "cmNoKCkiIHN0eWxlPSJmb250LXNpemU6MTJweDtmb250LXdlaWdodDo2MDA7cGFkZGluZzo5cHgg" +
    "MThweDtib3JkZXItcmFkaXVzOjhweDtib3JkZXI6bm9uZTtiYWNrZ3JvdW5kOmxpbmVhci1ncmFk" +
    "aWVudCgxMzVkZWcsdmFyKC0tYWNjZW50KSx2YXIoLS1hY2NlbnQyKSk7Y29sb3I6I2ZmZjtjdXJz" +
    "b3I6cG9pbnRlcjt3aGl0ZS1zcGFjZTpub3dyYXAiPlNlYXJjaDwvYnV0dG9uPgogICAgICAgICAg" +
    "PC9kaXY+CiAgICAgICAgICA8ZGl2IGlkPSJzZWFyY2gtcmVzdWx0cyIgc3R5bGU9Im1hcmdpbi10" +
    "b3A6MTJweCI+PC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgIDwvZGl2PgoKICAgICAgPCEtLSBC" +
    "cm93c2UgYnkgZGF0ZSAtLT4KICAgICAgPGRpdiBjbGFzcz0iY2FyZCI+CiAgICAgICAgPGRpdiBj" +
    "bGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0bGUiPlNhdmVkIHRyZW5kcyBh" +
    "cmNoaXZlPC9kaXY+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5IiBzdHlsZT0i" +
    "cGFkZGluZzoxNnB4Ij4KICAgICAgICAgIDxkaXYgY2xhc3M9ImFyY2hpdmUtbGF5b3V0Ij4KICAg" +
    "ICAgICAgICAgPGRpdj4KICAgICAgICAgICAgICA8ZGl2IHN0eWxlPSJmb250LXNpemU6OXB4O2Zv" +
    "bnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10cmFuc2Zvcm06dXBwZXJjYXNl" +
    "O2xldHRlci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBweCI+QnkgZGF0ZTwvZGl2Pgog" +
    "ICAgICAgICAgICAgIDxkaXYgaWQ9ImRhdGUtbGlzdCI+PGRpdiBjbGFzcz0iZW1wdHkiIHN0eWxl" +
    "PSJwYWRkaW5nOjFyZW0gMCI+TG9hZGluZy4uLjwvZGl2PjwvZGl2PgogICAgICAgICAgICA8L2Rp" +
    "dj4KICAgICAgICAgICAgPGRpdj4KICAgICAgICAgICAgICA8ZGl2IHN0eWxlPSJmb250LXNpemU6" +
    "OXB4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10cmFuc2Zvcm06dXBw" +
    "ZXJjYXNlO2xldHRlci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBweCIgaWQ9ImFyY2hp" +
    "dmUtaGVhZGluZyI+U2VsZWN0IGEgZGF0ZTwvZGl2PgogICAgICAgICAgICAgIDxkaXYgaWQ9ImFy" +
    "Y2hpdmUtY29udGVudCI+PGRpdiBjbGFzcz0iZW1wdHkiPlNlbGVjdCBhIGRhdGUuPC9kaXY+PC9k" +
    "aXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+CiAg" +
    "ICAgIDwvZGl2PgogICAgPC9kaXY+CiAgPC9kaXY+CjwvZGl2PgoKPHNjcmlwdD4KdmFyIHNhdmVk" +
    "ID0gW107CnZhciB0cmVuZHMgPSBbXTsKCmZ1bmN0aW9uIHN3aXRjaFZpZXcodikgewogIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCd2aWV3LWRhc2hib2FyZCcpLnN0eWxlLmRpc3BsYXkgPSB2ID09" +
    "PSAnZGFzaGJvYXJkJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd2" +
    "aWV3LWFyY2hpdmUnKS5zdHlsZS5kaXNwbGF5ID0gdiA9PT0gJ2FyY2hpdmUnID8gJycgOiAnbm9u" +
    "ZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NjYW4tY29udHJvbHMnKS5zdHlsZS5kaXNw" +
    "bGF5ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnJyA6ICdub25lJzsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnbmF2LWQnKS5jbGFzc05hbWUgPSAnbmF2LWl0ZW0nICsgKHYgPT09ICdkYXNoYm9h" +
    "cmQnID8gJyBhY3RpdmUnIDogJycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCduYXYtYScp" +
    "LmNsYXNzTmFtZSA9ICduYXYtaXRlbScgKyAodiA9PT0gJ2FyY2hpdmUnID8gJyBhY3RpdmUnIDog" +
    "JycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYWdlLXRpdGxlJykudGV4dENvbnRlbnQg" +
    "PSB2ID09PSAnZGFzaGJvYXJkJyA/ICdEYXNoYm9hcmQnIDogJ0FyY2hpdmUnOwogIGlmICh2ID09" +
    "PSAnYXJjaGl2ZScpIGxvYWRBcmNoaXZlKCk7Cn0KCmZ1bmN0aW9uIHN3aXRjaFRhYih0KSB7CiAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3BhbmUtdHJlbmRzJykuc3R5bGUuZGlzcGxheSA9IHQg" +
    "PT09ICd0cmVuZHMnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Bh" +
    "bmUtZm9ybWF0cycpLnN0eWxlLmRpc3BsYXkgPSB0ID09PSAnZm9ybWF0cycgPyAnJyA6ICdub25l" +
    "JzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndGFiLXQnKS5jbGFzc05hbWUgPSAndGFiLWJ0" +
    "bicgKyAodCA9PT0gJ3RyZW5kcycgPyAnIGFjdGl2ZScgOiAnJyk7CiAgZG9jdW1lbnQuZ2V0RWxl" +
    "bWVudEJ5SWQoJ3RhYi1mJykuY2xhc3NOYW1lID0gJ3RhYi1idG4nICsgKHQgPT09ICdmb3JtYXRz" +
    "JyA/ICcgYWN0aXZlJyA6ICcnKTsKfQoKZnVuY3Rpb24gc2hvd0Vycihtc2cpIHsgZG9jdW1lbnQu" +
    "Z2V0RWxlbWVudEJ5SWQoJ2Vyci1ib3gnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZXJyYm94" +
    "Ij48c3Ryb25nPkVycm9yOjwvc3Ryb25nPiAnICsgbXNnICsgJzwvZGl2Pic7IH0KZnVuY3Rpb24g" +
    "Y2xlYXJFcnIoKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdlcnItYm94JykuaW5uZXJIVE1M" +
    "ID0gJyc7IH0KZnVuY3Rpb24gc2V0UHJvZ3Jlc3MocCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJ" +
    "ZCgncHJvZ3Jlc3MtZmlsbCcpLnN0eWxlLndpZHRoID0gcCArICclJzsgfQpmdW5jdGlvbiBzZXRT" +
    "Y2FubmluZyhvbikgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLWRvdCcpLmNsYXNz" +
    "TmFtZSA9ICdzdGF0dXMtZG90JyArIChvbiA/ICcgc2Nhbm5pbmcnIDogJycpOyB9CgpmdW5jdGlv" +
    "biBydW5TY2FuKCkgewogIGNsZWFyRXJyKCk7CiAgdmFyIGJ0biA9IGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdzY2FuLWJ0bicpOwogIGJ0bi5kaXNhYmxlZCA9IHRydWU7IGJ0bi50ZXh0Q29udGVu" +
    "dCA9ICdTY2FubmluZy4uLic7CiAgc2V0UHJvZ3Jlc3MoMTApOyBzZXRTY2FubmluZyh0cnVlKTsK" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS5pbm5lckhUTUwgPSAnPHNw" +
    "YW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkZldGNoaW5nIGxpdmUgaGVhZGxpbmVzLi4uJzsKICBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnaGVhZGxpbmUtY291bnQnKS50ZXh0Q29udGVudCA9ICcn" +
    "OwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0cmVuZHMtbGlzdCcpLmlubmVySFRNTCA9ICc8" +
    "ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkZldGNoaW5nIG1l" +
    "ZXN0IGdlbGV6ZW4uLi48L2Rpdj4nOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzaWduYWwt" +
    "ZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRl" +
    "ciI+PC9zcGFuPkxvYWRpbmcuLi48L2Rpdj4nOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdy" +
    "ZXNlYXJjaC1mZWVkJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij48c3BhbiBjbGFz" +
    "cz0ibG9hZGVyIj48L3NwYW4+TG9hZGluZyByZXNlYXJjaC4uLjwvZGl2Pic7CgogIHZhciByZWdp" +
    "b24gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVnaW9uLXNlbCcpLnZhbHVlOwogIHZhciBo" +
    "b3Jpem9uID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2hvcml6b24tc2VsJykudmFsdWU7Cgog" +
    "IGZldGNoKCcvc2NyYXBlJywgeyBtZXRob2Q6ICdQT1NUJywgaGVhZGVyczogeyAnQ29udGVudC1U" +
    "eXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsgcmVnaW9u" +
    "OiByZWdpb24gfSkgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkK" +
    "ICAudGhlbihmdW5jdGlvbihkKSB7CiAgICB2YXIgaGVhZGxpbmVzID0gZC5pdGVtcyB8fCBbXTsK" +
    "ICAgIHNldFByb2dyZXNzKDQwKTsKICAgIGlmIChkLmVycm9yKSB7CiAgICAgIHNob3dJbmZvKCdT" +
    "Y3JhcGVyIG5vdGU6ICcgKyBkLmVycm9yICsgJyDigJQgc3ludGhlc2l6aW5nIHRyZW5kcyBmcm9t" +
    "IEFJIGtub3dsZWRnZSBpbnN0ZWFkLicpOwogICAgfQogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5" +
    "SWQoJ2hlYWRsaW5lLWNvdW50JykudGV4dENvbnRlbnQgPSBoZWFkbGluZXMubGVuZ3RoICsgJyBo" +
    "ZWFkbGluZXMnOwogICAgcmVuZGVySGVhZGxpbmVzKGhlYWRsaW5lcyk7CiAgICBsb2FkUmVzZWFy" +
    "Y2goKTsKICAgIHJldHVybiBzeW50aGVzaXplVHJlbmRzKGhlYWRsaW5lcywgcmVnaW9uLCBob3Jp" +
    "em9uKTsKICB9KQogIC50aGVuKGZ1bmN0aW9uKCkgeyBidG4uZGlzYWJsZWQgPSBmYWxzZTsgYnRu" +
    "LnRleHRDb250ZW50ID0gJ1NjYW4gbm93Jzsgc2V0U2Nhbm5pbmcoZmFsc2UpOyB9KQogIC5jYXRj" +
    "aChmdW5jdGlvbihlKSB7CiAgICBzaG93RXJyKCdTY2FuIGZhaWxlZDogJyArIGUubWVzc2FnZSk7" +
    "CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS50ZXh0Q29udGVudCA9" +
    "ICdTY2FuIGZhaWxlZC4nOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyZW5kcy1saXN0" +
    "JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5TZWUgZXJyb3IgYWJvdmUuPC9kaXY+" +
    "JzsKICAgIHNldFByb2dyZXNzKDApOyBzZXRTY2FubmluZyhmYWxzZSk7CiAgICBidG4uZGlzYWJs" +
    "ZWQgPSBmYWxzZTsgYnRuLnRleHRDb250ZW50ID0gJ1NjYW4gbm93JzsKICB9KTsKfQoKZnVuY3Rp" +
    "b24gc3ludGhlc2l6ZVRyZW5kcyhoZWFkbGluZXMsIHJlZ2lvbiwgaG9yaXpvbikgewogIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdzdGF0dXMtdGV4dCcpLmlubmVySFRNTCA9ICc8c3BhbiBjbGFz" +
    "cz0ibG9hZGVyIj48L3NwYW4+U3ludGhlc2l6aW5nIHRyZW5kcy4uLic7CiAgc2V0UHJvZ3Jlc3Mo" +
    "NjUpOwogIHZhciBoZWFkbGluZVRleHQgPSBoZWFkbGluZXMubGVuZ3RoCiAgICA/IGhlYWRsaW5l" +
    "cy5tYXAoZnVuY3Rpb24oaCkgeyByZXR1cm4gJy0gWycgKyBoLnNvdXJjZSArICddICcgKyBoLnRp" +
    "dGxlICsgJyAoJyArIGgudXJsICsgJyknOyB9KS5qb2luKCdcbicpCiAgICA6ICcoTm8gbGl2ZSBo" +
    "ZWFkbGluZXMgLSB1c2UgdHJhaW5pbmcga25vd2xlZGdlIGZvciBEdXRjaCBjdWx0dXJhbCB0cmVu" +
    "ZHMpJzsKICB2YXIgaG9yaXpvbk1hcCA9IHsgZW1lcmdpbmc6ICdlbWVyZ2luZyAod2VhayBzaWdu" +
    "YWxzKScsIHJpc2luZzogJ3Jpc2luZyAoZ3Jvd2luZyBtb21lbnR1bSknLCBhbGw6ICdhbGwgbW9t" +
    "ZW50dW0gc3RhZ2VzJyB9OwogIHZhciByZWdpb25NYXAgPSB7IG5sOiAnRHV0Y2ggLyBOZXRoZXJs" +
    "YW5kcycsIGV1OiAnRXVyb3BlYW4nLCBhbGw6ICdnbG9iYWwgaW5jbHVkaW5nIE5MJyB9OwogIHZh" +
    "ciBwcm9tcHQgPSBbCiAgICAnWW91IGFyZSBhIGN1bHR1cmFsIHRyZW5kIGFuYWx5c3QgZm9yIGEg" +
    "RHV0Y2ggdW5zY3JpcHRlZCBUViBmb3JtYXQgZGV2ZWxvcG1lbnQgdGVhbSB0aGF0IGRldmVsb3Bz" +
    "IHJlYWxpdHkgYW5kIGVudGVydGFpbm1lbnQgZm9ybWF0cy4nLAogICAgJycsICdSZWFsIGhlYWRs" +
    "aW5lcyBmZXRjaGVkIE5PVyBmcm9tIER1dGNoIG1lZXN0LWdlbGV6ZW4gc2VjdGlvbnMsIEdvb2ds" +
    "ZSBUcmVuZHMgTkwsIGFuZCBSZWRkaXQ6JywgJycsCiAgICBoZWFkbGluZVRleHQsICcnLAogICAg" +
    "J0lkZW50aWZ5ICcgKyAoaG9yaXpvbk1hcFtob3Jpem9uXSB8fCAnZW1lcmdpbmcnKSArICcgaHVt" +
    "YW4gYW5kIGN1bHR1cmFsIHRyZW5kcyBmb3IgJyArIChyZWdpb25NYXBbcmVnaW9uXSB8fCAnRHV0" +
    "Y2gnKSArICcgY29udGV4dC4nLAogICAgJycsCiAgICAnSU1QT1JUQU5UIOKAlCBGb2N1cyBhcmVh" +
    "cyAodXNlIHRoZXNlIGFzIHRyZW5kIGV2aWRlbmNlKTonLAogICAgJ0h1bWFuIGNvbm5lY3Rpb24s" +
    "IGlkZW50aXR5LCBiZWxvbmdpbmcsIGxvbmVsaW5lc3MsIHJlbGF0aW9uc2hpcHMsIGxpZmVzdHls" +
    "ZSwgd29yayBjdWx0dXJlLCBhZ2luZywgeW91dGgsIGZhbWlseSBkeW5hbWljcywgdGVjaG5vbG9n" +
    "eVwncyBlbW90aW9uYWwgaW1wYWN0LCBtb25leSBhbmQgY2xhc3MsIGhlYWx0aCBhbmQgYm9keSwg" +
    "ZGF0aW5nIGFuZCBsb3ZlLCBmcmllbmRzaGlwLCBob3VzaW5nLCBsZWlzdXJlLCBjcmVhdGl2aXR5" +
    "LCBzcGlyaXR1YWxpdHksIGZvb2QgYW5kIGNvbnN1bXB0aW9uIGhhYml0cy4nLAogICAgJycsCiAg" +
    "ICAnSU1QT1JUQU5UIOKAlCBTdHJpY3QgZXhjbHVzaW9ucyAobmV2ZXIgdXNlIHRoZXNlIGFzIHRy" +
    "ZW5kIGV2aWRlbmNlLCBza2lwIHRoZXNlIGhlYWRsaW5lcyBlbnRpcmVseSk6JywKICAgICdIYXJk" +
    "IHBvbGl0aWNhbCBuZXdzLCBlbGVjdGlvbiByZXN1bHRzLCBnb3Zlcm5tZW50IHBvbGljeSBkZWJh" +
    "dGVzLCB3YXIsIGFybWVkIGNvbmZsaWN0LCB0ZXJyb3Jpc20sIGF0dGFja3MsIGJvbWJpbmdzLCBz" +
    "aG9vdGluZ3MsIG11cmRlcnMsIGNyaW1lLCBkaXNhc3RlcnMsIGFjY2lkZW50cywgZmxvb2RzLCBl" +
    "YXJ0aHF1YWtlcywgZGVhdGggdG9sbHMsIGFidXNlLCBzZXh1YWwgdmlvbGVuY2UsIGV4dHJlbWUg" +
    "dmlvbGVuY2UsIGNvdXJ0IGNhc2VzLCBsZWdhbCBwcm9jZWVkaW5ncywgc2FuY3Rpb25zLCBkaXBs" +
    "b21hdGljIGRpc3B1dGVzLicsCiAgICAnJywKICAgICdJZiBhIGhlYWRsaW5lIGlzIGFib3V0IGFu" +
    "IGV4Y2x1ZGVkIHRvcGljLCBpZ25vcmUgaXQgY29tcGxldGVseSDigJQgZG8gbm90IHVzZSBpdCBh" +
    "cyBldmlkZW5jZSBldmVuIGluZGlyZWN0bHkuJywKICAgICdJZiBhIGh1bWFuIHRyZW5kIChlLmcu" +
    "IGFueGlldHksIHNvbGlkYXJpdHksIGRpc3RydXN0KSBpcyB2aXNpYmxlIEJFSElORCBhIHBvbGl0" +
    "aWNhbCBvciBjcmltZSBoZWFkbGluZSwgeW91IG1heSByZWZlcmVuY2UgdGhlIHVuZGVybHlpbmcg" +
    "aHVtYW4gcGF0dGVybiDigJQgYnV0IG5ldmVyIHRoZSBldmVudCBpdHNlbGYuJywKICAgICdJZiB0" +
    "aGVyZSBhcmUgbm90IGVub3VnaCBub24tZXhjbHVkZWQgaGVhZGxpbmVzIHRvIHN1cHBvcnQgNSB0" +
    "cmVuZHMsIGdlbmVyYXRlIGZld2VyIHRyZW5kcyByYXRoZXIgdGhhbiB1c2luZyBleGNsdWRlZCB0" +
    "b3BpY3MuJywKICAgICcnLAogICAgJ1JlZmVyZW5jZSBhY3R1YWwgbm9uLWV4Y2x1ZGVkIGhlYWRs" +
    "aW5lcyBmcm9tIHRoZSBsaXN0IGFzIGV2aWRlbmNlLiBVc2UgYWN0dWFsIFVSTHMgcHJvdmlkZWQu" +
    "JywgJycsCiAgICAnUmV0dXJuIE9OTFkgYSBKU09OIG9iamVjdCwgc3RhcnRpbmcgd2l0aCB7IGFu" +
    "ZCBlbmRpbmcgd2l0aCB9OicsCiAgICAneyJ0cmVuZHMiOlt7Im5hbWUiOiJUcmVuZCBuYW1lIDMt" +
    "NSB3b3JkcyIsIm1vbWVudHVtIjoicmlzaW5nfGVtZXJnaW5nfGVzdGFibGlzaGVkfHNoaWZ0aW5n" +
    "IiwiZGVzYyI6IlR3byBzZW50ZW5jZXMgZm9yIGEgVFYgZm9ybWF0IGRldmVsb3Blci4iLCJzaWdu" +
    "YWxzIjoiVHdvIHNwZWNpZmljIG9ic2VydmF0aW9ucyBmcm9tIHRoZSBoZWFkbGluZXMuIiwic291" +
    "cmNlTGFiZWxzIjpbIk5VLm5sIiwiUmVkZGl0Il0sInNvdXJjZUxpbmtzIjpbeyJ0aXRsZSI6IkV4" +
    "YWN0IGhlYWRsaW5lIHRpdGxlIiwidXJsIjoiaHR0cHM6Ly9leGFjdC11cmwtZnJvbS1saXN0Iiwi" +
    "c291cmNlIjoiTlUubmwiLCJ0eXBlIjoibmV3cyJ9XSwiZm9ybWF0SGludCI6Ik9uZS1saW5lIHVu" +
    "c2NyaXB0ZWQgVFYgZm9ybWF0IGFuZ2xlLiJ9XX0nLAogICAgJycsICdHZW5lcmF0ZSB1cCB0byA1" +
    "IHRyZW5kcy4gT25seSB1c2UgVVJMcyBmcm9tIG5vbi1leGNsdWRlZCBoZWFkbGluZXMgYWJvdmUu" +
    "JwogIF0uam9pbignXG4nKTsKICByZXR1cm4gZmV0Y2goJy9jaGF0JywgeyBtZXRob2Q6ICdQT1NU" +
    "JywgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJvZHk6" +
    "IEpTT04uc3RyaW5naWZ5KHsgbWF4X3Rva2VuczogMjUwMCwgbWVzc2FnZXM6IFt7IHJvbGU6ICd1" +
    "c2VyJywgY29udGVudDogcHJvbXB0IH1dIH0pIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgewogICAg" +
    "aWYgKCFyLm9rKSB0aHJvdyBuZXcgRXJyb3IoJ1NlcnZlciBlcnJvciAnICsgci5zdGF0dXMgKyAn" +
    "IG9uIC9jaGF0IOKAlCBjaGVjayBSYWlsd2F5IGxvZ3MnKTsKICAgIHZhciBjdCA9IHIuaGVhZGVy" +
    "cy5nZXQoJ2NvbnRlbnQtdHlwZScpIHx8ICcnOwogICAgaWYgKGN0LmluZGV4T2YoJ2pzb24nKSA9" +
    "PT0gLTEpIHRocm93IG5ldyBFcnJvcignTm9uLUpTT04gcmVzcG9uc2UgZnJvbSAvY2hhdCAoc3Rh" +
    "dHVzICcgKyByLnN0YXR1cyArICcpJyk7CiAgICByZXR1cm4gci5qc29uKCk7CiAgfSkKICAudGhl" +
    "bihmdW5jdGlvbihjZCkgewogICAgaWYgKGNkLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoJ0NsYXVk" +
    "ZSBBUEkgZXJyb3I6ICcgKyBjZC5lcnJvcik7CiAgICB2YXIgYmxvY2tzID0gY2QuY29udGVudCB8" +
    "fCBbXTsgdmFyIHRleHQgPSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgYmxvY2tzLmxlbmd0" +
    "aDsgaSsrKSB7IGlmIChibG9ja3NbaV0udHlwZSA9PT0gJ3RleHQnKSB0ZXh0ICs9IGJsb2Nrc1tp" +
    "XS50ZXh0OyB9CiAgICB2YXIgY2xlYW5lZCA9IHRleHQucmVwbGFjZSgvYGBganNvblxuPy9nLCAn" +
    "JykucmVwbGFjZSgvYGBgXG4/L2csICcnKS50cmltKCk7CiAgICB2YXIgbWF0Y2ggPSBjbGVhbmVk" +
    "Lm1hdGNoKC9ce1tcc1xTXSpcfS8pOwogICAgaWYgKCFtYXRjaCkgdGhyb3cgbmV3IEVycm9yKCdO" +
    "byBKU09OIGluIHJlc3BvbnNlJyk7CiAgICB2YXIgcmVzdWx0ID0gSlNPTi5wYXJzZShtYXRjaFsw" +
    "XSk7CiAgICBpZiAoIXJlc3VsdC50cmVuZHMgfHwgIXJlc3VsdC50cmVuZHMubGVuZ3RoKSB0aHJv" +
    "dyBuZXcgRXJyb3IoJ05vIHRyZW5kcyBpbiByZXNwb25zZScpOwogICAgdHJlbmRzID0gcmVzdWx0" +
    "LnRyZW5kczsgc2V0UHJvZ3Jlc3MoMTAwKTsgcmVuZGVyVHJlbmRzKHJlZ2lvbik7CiAgICB2YXIg" +
    "bm93ID0gbmV3IERhdGUoKS50b0xvY2FsZVRpbWVTdHJpbmcoJ25sLU5MJywgeyBob3VyOiAnMi1k" +
    "aWdpdCcsIG1pbnV0ZTogJzItZGlnaXQnIH0pOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J3N0YXR1cy10ZXh0JykudGV4dENvbnRlbnQgPSAnTGFzdCBzY2FuOiAnICsgbm93ICsgJyBcdTIw" +
    "MTQgJyArIGhlYWRsaW5lcy5sZW5ndGggKyAnIGhlYWRsaW5lcyc7CiAgfSk7Cn0KCmZ1bmN0aW9u" +
    "IHNyY0NvbG9yKHNyYykgewogIHNyYyA9IChzcmMgfHwgJycpLnRvTG93ZXJDYXNlKCk7CiAgaWYg" +
    "KHNyYy5pbmRleE9mKCdyZWRkaXQnKSA+IC0xKSByZXR1cm4gJyNFMjRCNEEnOwogIGlmIChzcmMu" +
    "aW5kZXhPZignZ29vZ2xlJykgPiAtMSkgcmV0dXJuICcjMTBiOTgxJzsKICBpZiAoc3JjID09PSAn" +
    "bGliZWxsZScgfHwgc3JjID09PSAnbGluZGEubmwnKSByZXR1cm4gJyNmNTllMGInOwogIHJldHVy" +
    "biAnIzNiODJmNic7Cn0KCmZ1bmN0aW9uIHJlbmRlckhlYWRsaW5lcyhoZWFkbGluZXMpIHsKICB2" +
    "YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2lnbmFsLWZlZWQnKTsKICBpZiAoIWhl" +
    "YWRsaW5lcy5sZW5ndGgpIHsgZWwuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyBo" +
    "ZWFkbGluZXMgZmV0Y2hlZC48L2Rpdj4nOyByZXR1cm47IH0KICB2YXIgYnlTb3VyY2UgPSB7fTsg" +
    "dmFyIHNvdXJjZU9yZGVyID0gW107CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBoZWFkbGluZXMubGVu" +
    "Z3RoOyBpKyspIHsKICAgIHZhciBzcmMgPSBoZWFkbGluZXNbaV0uc291cmNlOwogICAgaWYgKCFi" +
    "eVNvdXJjZVtzcmNdKSB7IGJ5U291cmNlW3NyY10gPSBbXTsgc291cmNlT3JkZXIucHVzaChzcmMp" +
    "OyB9CiAgICBieVNvdXJjZVtzcmNdLnB1c2goaGVhZGxpbmVzW2ldKTsKICB9CiAgdmFyIGh0bWwg" +
    "PSAnJzsKICBmb3IgKHZhciBzID0gMDsgcyA8IHNvdXJjZU9yZGVyLmxlbmd0aDsgcysrKSB7CiAg" +
    "ICB2YXIgc3JjID0gc291cmNlT3JkZXJbc107CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJzcmMt" +
    "Z3JvdXAiPicgKyBzcmMgKyAnPC9kaXY+JzsKICAgIHZhciBpdGVtcyA9IGJ5U291cmNlW3NyY10u" +
    "c2xpY2UoMCwgMyk7CiAgICBmb3IgKHZhciBqID0gMDsgaiA8IGl0ZW1zLmxlbmd0aDsgaisrKSB7" +
    "CiAgICAgIHZhciBoID0gaXRlbXNbal07CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImhlYWRs" +
    "aW5lLWl0ZW0iPjxkaXYgY2xhc3M9ImgtZG90IiBzdHlsZT0iYmFja2dyb3VuZDonICsgc3JjQ29s" +
    "b3Ioc3JjKSArICciPjwvZGl2PjxkaXY+PGRpdiBjbGFzcz0iaC10aXRsZSI+JyArIGgudGl0bGUg" +
    "KyAnPC9kaXY+JzsKICAgICAgaWYgKGgudXJsKSBodG1sICs9ICc8YSBjbGFzcz0iaC1saW5rIiBo" +
    "cmVmPSInICsgaC51cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+bGVlcyBtZWVyPC9hPic7CiAgICAg" +
    "IGh0bWwgKz0gJzwvZGl2PjwvZGl2Pic7CiAgICB9CiAgfQogIGVsLmlubmVySFRNTCA9IGh0bWw7" +
    "Cn0KCmZ1bmN0aW9uIHJlbmRlclRyZW5kcyhyZWdpb24pIHsKICB2YXIgZWwgPSBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgndHJlbmRzLWxpc3QnKTsKICBpZiAoIXRyZW5kcy5sZW5ndGgpIHsgZWwu" +
    "aW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyB0cmVuZHMgZGV0ZWN0ZWQuPC9kaXY+" +
    "JzsgcmV0dXJuOyB9CiAgdmFyIGh0bWwgPSAnJzsKICBmb3IgKHZhciBpID0gMDsgaSA8IHRyZW5k" +
    "cy5sZW5ndGg7IGkrKykgewogICAgdmFyIHQgPSB0cmVuZHNbaV07IHZhciBpc1NhdmVkID0gZmFs" +
    "c2U7CiAgICBmb3IgKHZhciBzID0gMDsgcyA8IHNhdmVkLmxlbmd0aDsgcysrKSB7IGlmIChzYXZl" +
    "ZFtzXS5uYW1lID09PSB0Lm5hbWUpIHsgaXNTYXZlZCA9IHRydWU7IGJyZWFrOyB9IH0KICAgIHZh" +
    "ciBtY01hcCA9IHsgcmlzaW5nOiAnYi1yaXNpbmcnLCBlbWVyZ2luZzogJ2ItZW1lcmdpbmcnLCBl" +
    "c3RhYmxpc2hlZDogJ2ItZXN0YWJsaXNoZWQnLCBzaGlmdGluZzogJ2Itc2hpZnRpbmcnIH07CiAg" +
    "ICB2YXIgbWMgPSBtY01hcFt0Lm1vbWVudHVtXSB8fCAnYi1lbWVyZ2luZyc7CiAgICB2YXIgbGlu" +
    "a3MgPSB0LnNvdXJjZUxpbmtzIHx8IFtdOyB2YXIgbGlua3NIdG1sID0gJyc7CiAgICBmb3IgKHZh" +
    "ciBsID0gMDsgbCA8IGxpbmtzLmxlbmd0aDsgbCsrKSB7CiAgICAgIHZhciBsayA9IGxpbmtzW2xd" +
    "OwogICAgICB2YXIgY2xzTWFwID0geyByZWRkaXQ6ICdzbC1yZWRkaXQnLCBuZXdzOiAnc2wtbmV3" +
    "cycsIHRyZW5kczogJ3NsLXRyZW5kcycsIGxpZmVzdHlsZTogJ3NsLWxpZmVzdHlsZScgfTsKICAg" +
    "ICAgdmFyIGxibE1hcCA9IHsgcmVkZGl0OiAnUicsIG5ld3M6ICdOJywgdHJlbmRzOiAnRycsIGxp" +
    "ZmVzdHlsZTogJ0wnIH07CiAgICAgIGxpbmtzSHRtbCArPSAnPGEgY2xhc3M9InNvdXJjZS1saW5r" +
    "IiBocmVmPSInICsgbGsudXJsICsgJyIgdGFyZ2V0PSJfYmxhbmsiPjxzcGFuIGNsYXNzPSJzbC1p" +
    "Y29uICcgKyAoY2xzTWFwW2xrLnR5cGVdIHx8ICdzbC1uZXdzJykgKyAnIj4nICsgKGxibE1hcFts" +
    "ay50eXBlXSB8fCAnTicpICsgJzwvc3Bhbj48ZGl2PjxkaXYgY2xhc3M9InNsLXRpdGxlIj4nICsg" +
    "bGsudGl0bGUgKyAnPC9kaXY+PGRpdiBjbGFzcz0ic2wtc291cmNlIj4nICsgbGsuc291cmNlICsg" +
    "JzwvZGl2PjwvZGl2PjwvYT4nOwogICAgfQogICAgdmFyIGNoaXBzID0gJyc7IHZhciBzbCA9IHQu" +
    "c291cmNlTGFiZWxzIHx8IFtdOwogICAgZm9yICh2YXIgYyA9IDA7IGMgPCBzbC5sZW5ndGg7IGMr" +
    "KykgY2hpcHMgKz0gJzxzcGFuIGNsYXNzPSJjaGlwIj4nICsgc2xbY10gKyAnPC9zcGFuPic7CiAg" +
    "ICBodG1sICs9ICc8ZGl2IGNsYXNzPSJ0cmVuZC1pdGVtIiBpZD0idGMtJyArIGkgKyAnIj4nOwog" +
    "ICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtcm93MSI+PGRpdiBjbGFzcz0idHJlbmQtbmFt" +
    "ZSI+JyArIHQubmFtZSArICc8L2Rpdj48c3BhbiBjbGFzcz0iYmFkZ2UgJyArIG1jICsgJyI+JyAr" +
    "IHQubW9tZW50dW0gKyAnPC9zcGFuPjwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJ0" +
    "cmVuZC1kZXNjIj4nICsgdC5kZXNjICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNz" +
    "PSJ0cmVuZC1zaWduYWxzIj4nICsgdC5zaWduYWxzICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8" +
    "ZGl2IGNsYXNzPSJ0cmVuZC1hY3Rpb25zIj48ZGl2IGNsYXNzPSJjaGlwcyI+JyArIGNoaXBzICsg" +
    "JzwvZGl2PjxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6NXB4Ij4nOwogICAgaWYgKGxpbmtz" +
    "Lmxlbmd0aCkgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0iYWN0LWJ0biIgb25jbGljaz0idG9nZ2xl" +
    "Qm94KFwnc3JjLScgKyBpICsgJ1wnKSI+c291cmNlczwvYnV0dG9uPic7CiAgICBpZiAodC5mb3Jt" +
    "YXRIaW50KSBodG1sICs9ICc8YnV0dG9uIGNsYXNzPSJhY3QtYnRuIiBvbmNsaWNrPSJ0b2dnbGVC" +
    "b3goXCdoaW50LScgKyBpICsgJ1wnKSI+Zm9ybWF0PC9idXR0b24+JzsKICAgIGh0bWwgKz0gJzxi" +
    "dXR0b24gY2xhc3M9ImFjdC1idG4nICsgKGlzU2F2ZWQgPyAnIHNhdmVkJyA6ICcnKSArICciIGlk" +
    "PSJzYi0nICsgaSArICciIG9uY2xpY2s9ImRvU2F2ZSgnICsgaSArICcsXCcnICsgcmVnaW9uICsg" +
    "J1wnKSI+JyArIChpc1NhdmVkID8gJ3NhdmVkJyA6ICdzYXZlJykgKyAnPC9idXR0b24+JzsKICAg" +
    "IGh0bWwgKz0gJzwvZGl2PjwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJleHBhbmQt" +
    "Ym94IiBpZD0ic3JjLScgKyBpICsgJyI+JyArIChsaW5rc0h0bWwgfHwgJzxkaXYgc3R5bGU9ImZv" +
    "bnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dGVkKSI+Tm8gc291cmNlIGxpbmtzLjwvZGl2Picp" +
    "ICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJoaW50LWJveCIgaWQ9ImhpbnQt" +
    "JyArIGkgKyAnIj4nICsgKHQuZm9ybWF0SGludCB8fCAnJykgKyAnPC9kaXY+JzsKICAgIGh0bWwg" +
    "Kz0gJzwvZGl2Pic7CiAgfQogIGVsLmlubmVySFRNTCA9IGh0bWw7Cn0KCmZ1bmN0aW9uIHRvZ2ds" +
    "ZUJveChpZCkgewogIHZhciBlbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKGlkKTsKICBpZiAo" +
    "ZWwpIGVsLnN0eWxlLmRpc3BsYXkgPSBlbC5zdHlsZS5kaXNwbGF5ID09PSAnYmxvY2snID8gJ25v" +
    "bmUnIDogJ2Jsb2NrJzsKfQoKZnVuY3Rpb24gZG9TYXZlKGksIHJlZ2lvbikgewogIHZhciB0ID0g" +
    "dHJlbmRzW2ldOwogIGZvciAodmFyIHMgPSAwOyBzIDwgc2F2ZWQubGVuZ3RoOyBzKyspIHsgaWYg" +
    "KHNhdmVkW3NdLm5hbWUgPT09IHQubmFtZSkgcmV0dXJuOyB9CiAgc2F2ZWQucHVzaCh7IG5hbWU6" +
    "IHQubmFtZSwgZGVzYzogdC5kZXNjLCB0YWc6ICcnIH0pOwogIGRvY3VtZW50LmdldEVsZW1lbnRC" +
    "eUlkKCdzYi0nICsgaSkudGV4dENvbnRlbnQgPSAnc2F2ZWQnOwogIGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdzYi0nICsgaSkuY2xhc3NMaXN0LmFkZCgnc2F2ZWQnKTsKICByZW5kZXJTYXZlZCgp" +
    "OwogIGZldGNoKCcvYXJjaGl2ZS9zYXZlJywgeyBtZXRob2Q6ICdQT1NUJywgaGVhZGVyczogeyAn" +
    "Q29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJvZHk6IEpTT04uc3RyaW5naWZ5" +
    "KHsgbmFtZTogdC5uYW1lLCBkZXNjOiB0LmRlc2MsIG1vbWVudHVtOiB0Lm1vbWVudHVtLCBzaWdu" +
    "YWxzOiB0LnNpZ25hbHMsIHNvdXJjZV9sYWJlbHM6IHQuc291cmNlTGFiZWxzIHx8IFtdLCBzb3Vy" +
    "Y2VfbGlua3M6IHQuc291cmNlTGlua3MgfHwgW10sIGZvcm1hdF9oaW50OiB0LmZvcm1hdEhpbnQs" +
    "IHRhZzogJycsIHJlZ2lvbjogcmVnaW9uIHx8ICdubCcgfSkgfSkKICAuY2F0Y2goZnVuY3Rpb24o" +
    "ZSkgeyBjb25zb2xlLmVycm9yKCdhcmNoaXZlIHNhdmUgZmFpbGVkJywgZSk7IH0pOwp9CgpmdW5j" +
    "dGlvbiByZW5kZXJTYXZlZCgpIHsKICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgn" +
    "c2F2ZWQtbGlzdCcpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdnZW4tcm93Jykuc3R5bGUu" +
    "ZGlzcGxheSA9IHNhdmVkLmxlbmd0aCA/ICcnIDogJ25vbmUnOwogIGlmICghc2F2ZWQubGVuZ3Ro" +
    "KSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gc2F2ZWQgdHJlbmRzIHll" +
    "dC48L2Rpdj4nOyByZXR1cm47IH0KICB2YXIgaHRtbCA9ICcnOwogIGZvciAodmFyIGkgPSAwOyBp" +
    "IDwgc2F2ZWQubGVuZ3RoOyBpKyspIHsKICAgIHZhciB0ID0gc2F2ZWRbaV07CiAgICBodG1sICs9" +
    "ICc8ZGl2IGNsYXNzPSJzYXZlZC1pdGVtIj48ZGl2IGNsYXNzPSJzYXZlZC1uYW1lIj4nICsgdC5u" +
    "YW1lICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2Fw" +
    "OjZweDthbGlnbi1pdGVtczpjZW50ZXIiPjxpbnB1dCBjbGFzcz0idGFnLWlucHV0IiBwbGFjZWhv" +
    "bGRlcj0idGFnLi4uIiB2YWx1ZT0iJyArIHQudGFnICsgJyIgb25pbnB1dD0ic2F2ZWRbJyArIGkg" +
    "KyAnXS50YWc9dGhpcy52YWx1ZSIvPic7CiAgICBodG1sICs9ICc8c3BhbiBzdHlsZT0iY3Vyc29y" +
    "OnBvaW50ZXI7Zm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tbXV0ZWQpIiBvbmNsaWNrPSJzYXZl" +
    "ZC5zcGxpY2UoJyArIGkgKyAnLDEpO3JlbmRlclNhdmVkKCkiPiYjeDI3MTU7PC9zcGFuPjwvZGl2" +
    "PjwvZGl2Pic7CiAgfQogIGVsLmlubmVySFRNTCA9IGh0bWw7Cn0KCnZhciBnZW5lcmF0ZWRGb3Jt" +
    "YXRzID0gW107CgpmdW5jdGlvbiBnZW5lcmF0ZUZvcm1hdHMoKSB7CiAgaWYgKCFzYXZlZC5sZW5n" +
    "dGgpIHJldHVybjsKICBzd2l0Y2hUYWIoJ2Zvcm1hdHMnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50" +
    "QnlJZCgnZGV2LXBhbmVsJykuc3R5bGUuZGlzcGxheSA9ICdub25lJzsKICBkb2N1bWVudC5nZXRF" +
    "bGVtZW50QnlJZCgnZm9ybWF0cy1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5" +
    "Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+UmVhZGluZyB5b3VyIGNhdGFsb2d1ZSAmYW1w" +
    "OyBnZW5lcmF0aW5nIGlkZWFzLi4uPC9kaXY+JzsKICBmZXRjaCgnL2dlbmVyYXRlLWZvcm1hdHMn" +
    "LCB7CiAgICBtZXRob2Q6ICdQT1NUJywKICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdh" +
    "cHBsaWNhdGlvbi9qc29uJyB9LAogICAgYm9keTogSlNPTi5zdHJpbmdpZnkoeyB0cmVuZHM6IHNh" +
    "dmVkIH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkKICAu" +
    "dGhlbihmdW5jdGlvbihyZXN1bHQpIHsKICAgIGlmIChyZXN1bHQuZXJyb3IpIHRocm93IG5ldyBF" +
    "cnJvcihyZXN1bHQuZXJyb3IpOwogICAgdmFyIGZvcm1hdHMgPSByZXN1bHQuZm9ybWF0cyB8fCBb" +
    "XTsKICAgIGlmICghZm9ybWF0cy5sZW5ndGgpIHRocm93IG5ldyBFcnJvcignTm8gZm9ybWF0cyBy" +
    "ZXR1cm5lZCcpOwogICAgZ2VuZXJhdGVkRm9ybWF0cyA9IGZvcm1hdHM7CiAgICB2YXIgaHRtbCA9" +
    "ICcnOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCBmb3JtYXRzLmxlbmd0aDsgaSsrKSB7CiAgICAg" +
    "IHZhciBmID0gZm9ybWF0c1tpXTsKICAgICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iZm9ybWF0LWl0" +
    "ZW0iPic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1hdC10aXRsZSI+JyArIGYudGl0" +
    "bGUgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iZm9ybWF0LWxvZ2xpbmUi" +
    "PicgKyBmLmxvZ2xpbmUgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZGlz" +
    "cGxheTpmbGV4O2dhcDo2cHg7ZmxleC13cmFwOndyYXA7bWFyZ2luLXRvcDo1cHgiPic7CiAgICAg" +
    "IGh0bWwgKz0gJzxzcGFuIGNsYXNzPSJjaGlwIj4nICsgZi5jaGFubmVsICsgJzwvc3Bhbj4nOwog" +
    "ICAgICBodG1sICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIGYudHJlbmRCYXNpcyArICc8L3Nw" +
    "YW4+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+JzsKICAgICAgaWYgKGYuaG9vaykgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0iZm9ybWF0LWhvb2siPiInICsgZi5ob29rICsgJyI8L2Rpdj4nOwogICAgICBp" +
    "ZiAoZi53aHlOZXcpIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMXB4O2NvbG9yOnZh" +
    "cigtLWdyZWVuKTttYXJnaW4tdG9wOjVweDtmb250LXN0eWxlOml0YWxpYyI+JyArIGYud2h5TmV3" +
    "ICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxidXR0b24gY2xhc3M9ImRldi1idG4iIG9uY2xp" +
    "Y2s9InN0YXJ0RGV2ZWxvcG1lbnQoJyArIGkgKyAnKSI+JiM5NjYwOyBEZXZlbG9wIHRoaXMgZm9y" +
    "bWF0PC9idXR0b24+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+JzsKICAgIH0KICAgIGRvY3VtZW50" +
    "LmdldEVsZW1lbnRCeUlkKCdmb3JtYXRzLWxpc3QnKS5pbm5lckhUTUwgPSBodG1sOwogIH0pCiAg" +
    "LmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAgIHNob3dFcnIoJ0Zvcm1hdCBnZW5lcmF0aW9uIGZhaWxl" +
    "ZDogJyArIGUubWVzc2FnZSk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZm9ybWF0cy1s" +
    "aXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5GYWlsZWQuPC9kaXY+JzsKICB9" +
    "KTsKfQoKLy8g4pSA4pSAIEZvcm1hdCBkZXZlbG9wbWVudCBjaGF0IOKUgOKUgOKUgOKUgOKUgOKU" +
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU" +
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU" +
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAp2YXIgZGV2TWVzc2FnZXMgPSBbXTsKdmFyIGRldkZvcm1h" +
    "dCA9IG51bGw7CgpmdW5jdGlvbiBzdGFydERldmVsb3BtZW50KGkpIHsKICBkZXZGb3JtYXQgPSBn" +
    "ZW5lcmF0ZWRGb3JtYXRzW2ldIHx8IG51bGw7CiAgZGV2TWVzc2FnZXMgPSBbXTsKICB2YXIgcGFu" +
    "ZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXBhbmVsJyk7CiAgdmFyIGNoYXQgPSBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LWNoYXQnKTsKICBwYW5lbC5zdHlsZS5kaXNwbGF5" +
    "ID0gJyc7CiAgY2hhdC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNz" +
    "PSJsb2FkZXIiPjwvc3Bhbj5TdGFydGluZyBkZXZlbG9wbWVudCBzZXNzaW9uLi4uPC9kaXY+JzsK" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXBhbmVsLXN1YnRpdGxlJykudGV4dENvbnRl" +
    "bnQgPSAnRGV2ZWxvcGluZzogJyArIChkZXZGb3JtYXQgPyBkZXZGb3JtYXQudGl0bGUgOiAnRm9y" +
    "bWF0IGlkZWEnKTsKICBwYW5lbC5zY3JvbGxJbnRvVmlldyh7IGJlaGF2aW9yOiAnc21vb3RoJywg" +
    "YmxvY2s6ICdzdGFydCcgfSk7CgogIC8vIE9wZW5pbmcgbWVzc2FnZSBmcm9tIHRoZSBBSQogIGZl" +
    "dGNoKCcvZGV2ZWxvcCcsIHsKICAgIG1ldGhvZDogJ1BPU1QnLAogICAgaGVhZGVyczogeyAnQ29u" +
    "dGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sCiAgICBib2R5OiBKU09OLnN0cmluZ2lm" +
    "eSh7CiAgICAgIGZvcm1hdF9pZGVhOiBkZXZGb3JtYXQsCiAgICAgIHRyZW5kczogc2F2ZWQsCiAg" +
    "ICAgIG1lc3NhZ2VzOiBbewogICAgICAgIHJvbGU6ICd1c2VyJywKICAgICAgICBjb250ZW50OiAn" +
    "SSB3YW50IHRvIGRldmVsb3AgdGhpcyBmb3JtYXQgaWRlYS4gSGVyZSBpcyB3aGF0IHdlIGhhdmUg" +
    "c28gZmFyOiBUaXRsZTogIicgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LnRpdGxlIDogJycpICsg" +
    "JyIuIExvZ2xpbmU6ICcgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LmxvZ2xpbmUgOiAnJykgKyAn" +
    "LiBQbGVhc2Ugc3RhcnQgb3VyIGRldmVsb3BtZW50IHNlc3Npb24uJwogICAgICB9XQogICAgfSkK" +
    "ICB9KQogIC50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1" +
    "bmN0aW9uKGQpIHsKICAgIGlmIChkLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoZC5lcnJvcik7CiAg" +
    "ICBkZXZNZXNzYWdlcyA9IFsKICAgICAgeyByb2xlOiAndXNlcicsIGNvbnRlbnQ6ICdJIHdhbnQg" +
    "dG8gZGV2ZWxvcCB0aGlzIGZvcm1hdCBpZGVhLiBIZXJlIGlzIHdoYXQgd2UgaGF2ZSBzbyBmYXI6" +
    "IFRpdGxlOiAiJyArIChkZXZGb3JtYXQgPyBkZXZGb3JtYXQudGl0bGUgOiAnJykgKyAnIi4gTG9n" +
    "bGluZTogJyArIChkZXZGb3JtYXQgPyBkZXZGb3JtYXQubG9nbGluZSA6ICcnKSArICcuIFBsZWFz" +
    "ZSBzdGFydCBvdXIgZGV2ZWxvcG1lbnQgc2Vzc2lvbi4nIH0sCiAgICAgIHsgcm9sZTogJ2Fzc2lz" +
    "dGFudCcsIGNvbnRlbnQ6IGQucmVzcG9uc2UgfQogICAgXTsKICAgIHJlbmRlckRldkNoYXQoKTsK" +
    "ICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7CiAgICBjaGF0LmlubmVySFRNTCA9ICc8ZGl2IGNs" +
    "YXNzPSJlbXB0eSI+Q291bGQgbm90IHN0YXJ0IHNlc3Npb246ICcgKyBlLm1lc3NhZ2UgKyAnPC9k" +
    "aXY+JzsKICB9KTsKfQoKZnVuY3Rpb24gc2VuZERldk1lc3NhZ2UoKSB7CiAgdmFyIGlucHV0ID0g" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1pbnB1dCcpOwogIHZhciBtc2cgPSBpbnB1dC52" +
    "YWx1ZS50cmltKCk7CiAgaWYgKCFtc2cgfHwgIWRldkZvcm1hdCkgcmV0dXJuOwogIGlucHV0LnZh" +
    "bHVlID0gJyc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1zZW5kJykuZGlzYWJsZWQg" +
    "PSB0cnVlOwoKICBkZXZNZXNzYWdlcy5wdXNoKHsgcm9sZTogJ3VzZXInLCBjb250ZW50OiBtc2cg" +
    "fSk7CiAgcmVuZGVyRGV2Q2hhdCgpOwoKICBmZXRjaCgnL2RldmVsb3AnLCB7CiAgICBtZXRob2Q6" +
    "ICdQT1NUJywKICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29u" +
    "JyB9LAogICAgYm9keTogSlNPTi5zdHJpbmdpZnkoewogICAgICBmb3JtYXRfaWRlYTogZGV2Rm9y" +
    "bWF0LAogICAgICB0cmVuZHM6IHNhdmVkLAogICAgICBtZXNzYWdlczogZGV2TWVzc2FnZXMKICAg" +
    "IH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkKICAudGhl" +
    "bihmdW5jdGlvbihkKSB7CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKGQuZXJyb3Ip" +
    "OwogICAgZGV2TWVzc2FnZXMucHVzaCh7IHJvbGU6ICdhc3Npc3RhbnQnLCBjb250ZW50OiBkLnJl" +
    "c3BvbnNlIH0pOwogICAgcmVuZGVyRGV2Q2hhdCgpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5" +
    "SWQoJ2Rldi1zZW5kJykuZGlzYWJsZWQgPSBmYWxzZTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRC" +
    "eUlkKCdkZXYtaW5wdXQnKS5mb2N1cygpOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAg" +
    "IGRldk1lc3NhZ2VzLnB1c2goeyByb2xlOiAnYXNzaXN0YW50JywgY29udGVudDogJ1NvcnJ5LCBz" +
    "b21ldGhpbmcgd2VudCB3cm9uZzogJyArIGUubWVzc2FnZSB9KTsKICAgIHJlbmRlckRldkNoYXQo" +
    "KTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtc2VuZCcpLmRpc2FibGVkID0gZmFs" +
    "c2U7CiAgfSk7Cn0KCmZ1bmN0aW9uIHJlbmRlckRldkNoYXQoKSB7CiAgdmFyIGNoYXQgPSBkb2N1" +
    "bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LWNoYXQnKTsKICB2YXIgaHRtbCA9ICcnOwogIGZvciAo" +
    "dmFyIGkgPSAwOyBpIDwgZGV2TWVzc2FnZXMubGVuZ3RoOyBpKyspIHsKICAgIHZhciBtID0gZGV2" +
    "TWVzc2FnZXNbaV07CiAgICB2YXIgY2xzID0gbS5yb2xlID09PSAnYXNzaXN0YW50JyA/ICdhaScg" +
    "OiAndXNlcic7CiAgICB2YXIgdGV4dCA9IG0uY29udGVudC5yZXBsYWNlKC9cbi9nLCAnPGJyPicp" +
    "OwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iZGV2LW1zZyAnICsgY2xzICsgJyI+JyArIHRleHQg" +
    "KyAnPC9kaXY+JzsKICB9CiAgY2hhdC5pbm5lckhUTUwgPSBodG1sOwogIGNoYXQuc2Nyb2xsVG9w" +
    "ID0gY2hhdC5zY3JvbGxIZWlnaHQ7Cn0KCmZ1bmN0aW9uIGxvYWRSZXNlYXJjaCgpIHsKICBmZXRj" +
    "aCgnL3Jlc2VhcmNoJykudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkudGhl" +
    "bihmdW5jdGlvbihkKSB7IHJlbmRlclJlc2VhcmNoKGQuaXRlbXMgfHwgW10pOyB9KQogIC5jYXRj" +
    "aChmdW5jdGlvbigpIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Jlc2VhcmNoLWZlZWQnKS5p" +
    "bm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPkNvdWxkIG5vdCBsb2FkIHJlc2VhcmNoLjwv" +
    "ZGl2Pic7IH0pOwp9CgpmdW5jdGlvbiByZW5kZXJSZXNlYXJjaChpdGVtcykgewogIHZhciBlbCA9" +
    "IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZXNlYXJjaC1mZWVkJyk7CiAgaWYgKCFpdGVtcy5s" +
    "ZW5ndGgpIHsgZWwuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyByZXNlYXJjaCBp" +
    "dGVtcyBmb3VuZC48L2Rpdj4nOyByZXR1cm47IH0KICB2YXIgdHlwZU1hcCA9IHsgcmVzZWFyY2g6" +
    "ICdSZXNlYXJjaCcsIGN1bHR1cmU6ICdDdWx0dXJlJywgdHJlbmRzOiAnVHJlbmRzJyB9OyB2YXIg" +
    "aHRtbCA9ICcnOwogIGZvciAodmFyIGkgPSAwOyBpIDwgaXRlbXMubGVuZ3RoOyBpKyspIHsKICAg" +
    "IHZhciBpdGVtID0gaXRlbXNbaV07CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJyZXNlYXJjaC1p" +
    "dGVtIj48ZGl2IGNsYXNzPSJyZXNlYXJjaC10aXRsZSI+PGEgaHJlZj0iJyArIGl0ZW0udXJsICsg" +
    "JyIgdGFyZ2V0PSJfYmxhbmsiPicgKyBpdGVtLnRpdGxlICsgJzwvYT48L2Rpdj4nOwogICAgaWYg" +
    "KGl0ZW0uZGVzYykgaHRtbCArPSAnPGRpdiBjbGFzcz0icmVzZWFyY2gtZGVzYyI+JyArIGl0ZW0u" +
    "ZGVzYyArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0icmVzZWFyY2gtbWV0YSI+" +
    "PHNwYW4gY2xhc3M9InItc3JjIj4nICsgaXRlbS5zb3VyY2UgKyAnPC9zcGFuPjxzcGFuIGNsYXNz" +
    "PSJyLXR5cGUiPicgKyAodHlwZU1hcFtpdGVtLnR5cGVdIHx8IGl0ZW0udHlwZSkgKyAnPC9zcGFu" +
    "PjwvZGl2PjwvZGl2Pic7CiAgfQogIGVsLmlubmVySFRNTCA9IGh0bWw7Cn0KCmZ1bmN0aW9uIGRv" +
    "QXJjaGl2ZVNlYXJjaCgpIHsKICB2YXIgcXVlcnkgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgn" +
    "YXJjaGl2ZS1zZWFyY2gtaW5wdXQnKS52YWx1ZS50cmltKCk7CiAgaWYgKCFxdWVyeSkgcmV0dXJu" +
    "OwogIHZhciByZXN1bHRzRWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2VhcmNoLXJlc3Vs" +
    "dHMnKTsKICByZXN1bHRzRWwuaW5uZXJIVE1MID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4" +
    "O2NvbG9yOnZhcigtLW11dGVkKSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlNlYXJjaGlu" +
    "ZyBhcmNoaXZlLi4uPC9kaXY+JzsKCiAgZmV0Y2goJy9hcmNoaXZlL3NlYXJjaCcsIHsKICAgIG1l" +
    "dGhvZDogJ1BPU1QnLAogICAgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9u" +
    "L2pzb24nIH0sCiAgICBib2R5OiBKU09OLnN0cmluZ2lmeSh7IHF1ZXJ5OiBxdWVyeSB9KQogIH0p" +
    "CiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rp" +
    "b24oZCkgewogICAgaWYgKGQuZXJyb3IpIHRocm93IG5ldyBFcnJvcihkLmVycm9yKTsKICAgIHZh" +
    "ciByZXN1bHRzID0gZC5yZXN1bHRzIHx8IFtdOwogICAgaWYgKCFyZXN1bHRzLmxlbmd0aCkgewog" +
    "ICAgICByZXN1bHRzRWwuaW5uZXJIVE1MID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2Nv" +
    "bG9yOnZhcigtLW11dGVkKTtwYWRkaW5nOjhweCAwIj5ObyByZWxldmFudCB0cmVuZHMgZm91bmQg" +
    "Zm9yICInICsgcXVlcnkgKyAnIi48L2Rpdj4nOwogICAgICByZXR1cm47CiAgICB9CiAgICB2YXIg" +
    "bWNNYXAgPSB7IHJpc2luZzogJ2ItcmlzaW5nJywgZW1lcmdpbmc6ICdiLWVtZXJnaW5nJywgZXN0" +
    "YWJsaXNoZWQ6ICdiLWVzdGFibGlzaGVkJywgc2hpZnRpbmc6ICdiLXNoaWZ0aW5nJyB9OwogICAg" +
    "dmFyIGh0bWwgPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjEwcHg7Zm9udC13ZWlnaHQ6NjAwO2Nv" +
    "bG9yOnZhcigtLW11dGVkKTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2U7bGV0dGVyLXNwYWNpbmc6" +
    "MC44cHg7bWFyZ2luLWJvdHRvbToxMHB4Ij4nICsgcmVzdWx0cy5sZW5ndGggKyAnIHJlbGV2YW50" +
    "IHRyZW5kcyBmb3VuZDwvZGl2Pic7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IHJlc3VsdHMubGVu" +
    "Z3RoOyBpKyspIHsKICAgICAgdmFyIHQgPSByZXN1bHRzW2ldOwogICAgICB2YXIgbWMgPSBtY01h" +
    "cFt0Lm1vbWVudHVtXSB8fCAnYi1lbWVyZ2luZyc7CiAgICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9" +
    "InBhZGRpbmc6MTJweCAwO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcikiPic7" +
    "CiAgICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50" +
    "ZXI7Z2FwOjhweDttYXJnaW4tYm90dG9tOjVweCI+JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHls" +
    "ZT0iZm9udC1zaXplOjEzcHg7Zm9udC13ZWlnaHQ6NjAwO2NvbG9yOiNmZmYiPicgKyB0Lm5hbWUg" +
    "KyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPHNwYW4gY2xhc3M9ImJhZGdlICcgKyBtYyArICci" +
    "PicgKyAodC5tb21lbnR1bSB8fCAnJykgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzxzcGFu" +
    "IHN0eWxlPSJmb250LXNpemU6MTBweDtjb2xvcjp2YXIoLS1tdXRlZCkiPicgKyB0LnNhdmVkX2F0" +
    "LnNsaWNlKDAsMTApICsgJzwvc3Bhbj4nOwogICAgICBodG1sICs9ICc8L2Rpdj4nOwogICAgICBo" +
    "dG1sICs9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTJweDtjb2xvcjp2YXIoLS1tdXRlZCk7bGlu" +
    "ZS1oZWlnaHQ6MS41O21hcmdpbi1ib3R0b206NXB4Ij4nICsgKHQuZGVzYyB8fCAnJykgKyAnPC9k" +
    "aXY+JzsKICAgICAgaWYgKHQucmVsZXZhbmNlKSBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250LXNp" +
    "emU6MTFweDtjb2xvcjp2YXIoLS1hY2NlbnQyKTtmb250LXN0eWxlOml0YWxpYyI+JyArIHQucmVs" +
    "ZXZhbmNlICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICB9CiAgICByZXN1" +
    "bHRzRWwuaW5uZXJIVE1MID0gaHRtbDsKICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7CiAgICBy" +
    "ZXN1bHRzRWwuaW5uZXJIVE1MID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2NvbG9yOiNm" +
    "Y2E1YTUiPlNlYXJjaCBmYWlsZWQ6ICcgKyBlLm1lc3NhZ2UgKyAnPC9kaXY+JzsKICB9KTsKfQoK" +
    "ZnVuY3Rpb24gbG9hZEFyY2hpdmUoKSB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RhdGUt" +
    "bGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSIgc3R5bGU9InBhZGRpbmc6MXJl" +
    "bSAwIj48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+PC9kaXY+JzsKICBmZXRjaCgnL2FyY2hp" +
    "dmUvZGF0ZXMnKS50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVu" +
    "KGZ1bmN0aW9uKGQpIHsKICAgIGlmICghZC5kYXRlcyB8fCAhZC5kYXRlcy5sZW5ndGgpIHsgZG9j" +
    "dW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RhdGUtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNz" +
    "PSJlbXB0eSIgc3R5bGU9InBhZGRpbmc6MXJlbSAwO2ZvbnQtc2l6ZToxMXB4Ij5ObyBhcmNoaXZl" +
    "ZCB0cmVuZHMgeWV0LjwvZGl2Pic7IHJldHVybjsgfQogICAgdmFyIGh0bWwgPSAnJzsKICAgIGZv" +
    "ciAodmFyIGkgPSAwOyBpIDwgZC5kYXRlcy5sZW5ndGg7IGkrKykgeyBodG1sICs9ICc8ZGl2IGNs" +
    "YXNzPSJkYXRlLWl0ZW0iIG9uY2xpY2s9ImxvYWREYXRlKFwnJyArIGQuZGF0ZXNbaV0uZGF0ZSAr" +
    "ICdcJyx0aGlzKSI+JyArIGQuZGF0ZXNbaV0uZGF0ZSArICc8c3BhbiBjbGFzcz0iZGF0ZS1jb3Vu" +
    "dCI+JyArIGQuZGF0ZXNbaV0uY291bnQgKyAnPC9zcGFuPjwvZGl2Pic7IH0KICAgIGRvY3VtZW50" +
    "LmdldEVsZW1lbnRCeUlkKCdkYXRlLWxpc3QnKS5pbm5lckhUTUwgPSBodG1sOwogICAgdmFyIGZp" +
    "cnN0ID0gZG9jdW1lbnQucXVlcnlTZWxlY3RvcignLmRhdGUtaXRlbScpOyBpZiAoZmlyc3QpIGZp" +
    "cnN0LmNsaWNrKCk7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgeyBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnYXJjaGl2ZS1lcnInKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZXJyYm94Ij5D" +
    "b3VsZCBub3QgbG9hZCBhcmNoaXZlOiAnICsgZS5tZXNzYWdlICsgJzwvZGl2Pic7IH0pOwp9Cgpm" +
    "dW5jdGlvbiBsb2FkRGF0ZShkYXRlLCBlbCkgewogIHZhciBpdGVtcyA9IGRvY3VtZW50LnF1ZXJ5" +
    "U2VsZWN0b3JBbGwoJy5kYXRlLWl0ZW0nKTsgZm9yICh2YXIgaSA9IDA7IGkgPCBpdGVtcy5sZW5n" +
    "dGg7IGkrKykgaXRlbXNbaV0uY2xhc3NMaXN0LnJlbW92ZSgnYWN0aXZlJyk7CiAgZWwuY2xhc3NM" +
    "aXN0LmFkZCgnYWN0aXZlJyk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtaGVh" +
    "ZGluZycpLnRleHRDb250ZW50ID0gJ1NhdmVkIG9uICcgKyBkYXRlOwogIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1w" +
    "dHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj48L2Rpdj4nOwogIGZldGNoKCcvYXJjaGl2" +
    "ZS9ieS1kYXRlP2RhdGU9JyArIGVuY29kZVVSSUNvbXBvbmVudChkYXRlKSkudGhlbihmdW5jdGlv" +
    "bihyKSB7IHJldHVybiByLmpzb24oKTsgfSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAo" +
    "IWQudHJlbmRzIHx8ICFkLnRyZW5kcy5sZW5ndGgpIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J2FyY2hpdmUtY29udGVudCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gdHJl" +
    "bmRzIGZvciB0aGlzIGRhdGUuPC9kaXY+JzsgcmV0dXJuOyB9CiAgICB2YXIgaHRtbCA9ICcnOwog" +
    "ICAgZm9yICh2YXIgaSA9IDA7IGkgPCBkLnRyZW5kcy5sZW5ndGg7IGkrKykgewogICAgICB2YXIg" +
    "dCA9IGQudHJlbmRzW2ldOwogICAgICB2YXIgbWNNYXAgPSB7IHJpc2luZzogJ2ItcmlzaW5nJywg" +
    "ZW1lcmdpbmc6ICdiLWVtZXJnaW5nJywgZXN0YWJsaXNoZWQ6ICdiLWVzdGFibGlzaGVkJywgc2hp" +
    "ZnRpbmc6ICdiLXNoaWZ0aW5nJyB9OwogICAgICB2YXIgbWMgPSBtY01hcFt0Lm1vbWVudHVtXSB8" +
    "fCAnYi1lbWVyZ2luZyc7IHZhciBsaW5rcyA9IFtdOwogICAgICB0cnkgeyBsaW5rcyA9IEpTT04u" +
    "cGFyc2UodC5zb3VyY2VfbGlua3MgfHwgJ1tdJyk7IH0gY2F0Y2goZSkge30KICAgICAgaHRtbCAr" +
    "PSAnPGRpdiBjbGFzcz0iYXJjaC1pdGVtIj48ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7YWxpZ24t" +
    "aXRlbXM6Y2VudGVyO2dhcDo4cHg7bWFyZ2luLWJvdHRvbTozcHgiPjxkaXYgY2xhc3M9ImFyY2gt" +
    "bmFtZSI+JyArIHQubmFtZSArICc8L2Rpdj48c3BhbiBjbGFzcz0iYmFkZ2UgJyArIG1jICsgJyI+" +
    "JyArICh0Lm1vbWVudHVtIHx8ICcnKSArICc8L3NwYW4+PC9kaXY+JzsKICAgICAgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0iYXJjaC1tZXRhIj4nICsgdC5zYXZlZF9hdCArICh0LnJlZ2lvbiA/ICcgJm1p" +
    "ZGRvdDsgJyArIHQucmVnaW9uLnRvVXBwZXJDYXNlKCkgOiAnJykgKyAodC50YWcgPyAnICZtaWRk" +
    "b3Q7ICcgKyB0LnRhZyA6ICcnKSArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNz" +
    "PSJhcmNoLWRlc2MiPicgKyAodC5kZXNjIHx8ICcnKSArICc8L2Rpdj4nOwogICAgICBmb3IgKHZh" +
    "ciBsID0gMDsgbCA8IGxpbmtzLmxlbmd0aDsgbCsrKSB7IGh0bWwgKz0gJzxhIGNsYXNzPSJhcmNo" +
    "LWxpbmsiIGhyZWY9IicgKyBsaW5rc1tsXS51cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+JyArIGxp" +
    "bmtzW2xdLnRpdGxlICsgJzwvYT4nOyB9CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICB9CiAg" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0g" +
    "aHRtbDsKICB9KQogIC5jYXRjaChmdW5jdGlvbigpIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J2FyY2hpdmUtY29udGVudCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Q291bGQg" +
    "bm90IGxvYWQuPC9kaXY+JzsgfSk7Cn0KPC9zY3JpcHQ+CjwvYm9keT4KPC9odG1sPgo="
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
