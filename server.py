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
    "InNyYy1waWxsIG9uIj5OT1M8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPkdv" +
    "b2dsZSBUcmVuZHM8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPk5ZVCBCb29r" +
    "czwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+U0NQPC9zcGFuPgogICAgPHNw" +
    "YW4gY2xhc3M9InNyYy1waWxsIG9uIj5DQlM8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBp" +
    "bGwgb24iPlBldyBSZXNlYXJjaDwvc3Bhbj4KICA8L2Rpdj4KPC9kaXY+Cgo8ZGl2IGNsYXNzPSJt" +
    "YWluIj4KICA8ZGl2IGNsYXNzPSJ0b3BiYXIiPgogICAgPGRpdiBjbGFzcz0idG9wYmFyLXRpdGxl" +
    "IiBpZD0icGFnZS10aXRsZSI+RGFzaGJvYXJkPC9kaXY+CiAgICA8ZGl2IGNsYXNzPSJ0b3BiYXIt" +
    "cmlnaHQiIGlkPSJzY2FuLWNvbnRyb2xzIj4KICAgICAgPHNlbGVjdCBjbGFzcz0ic2VsIiBpZD0i" +
    "cmVnaW9uLXNlbCI+CiAgICAgICAgPG9wdGlvbiB2YWx1ZT0ibmwiPk5MIGZvY3VzPC9vcHRpb24+" +
    "CiAgICAgICAgPG9wdGlvbiB2YWx1ZT0iZXUiPkVVIC8gZ2xvYmFsPC9vcHRpb24+CiAgICAgICAg" +
    "PG9wdGlvbiB2YWx1ZT0iYWxsIj5BbGwgbWFya2V0czwvb3B0aW9uPgogICAgICA8L3NlbGVjdD4K" +
    "ICAgICAgPHNlbGVjdCBjbGFzcz0ic2VsIiBpZD0iaG9yaXpvbi1zZWwiPgogICAgICAgIDxvcHRp" +
    "b24gdmFsdWU9ImVtZXJnaW5nIj5FbWVyZ2luZzwvb3B0aW9uPgogICAgICAgIDxvcHRpb24gdmFs" +
    "dWU9InJpc2luZyI+UmlzaW5nPC9vcHRpb24+CiAgICAgICAgPG9wdGlvbiB2YWx1ZT0iYWxsIj5B" +
    "bGwgc2lnbmFsczwvb3B0aW9uPgogICAgICA8L3NlbGVjdD4KICAgICAgPGJ1dHRvbiBjbGFzcz0i" +
    "c2Nhbi1idG4iIGlkPSJzY2FuLWJ0biIgb25jbGljaz0icnVuU2NhbigpIj5TY2FuIG5vdzwvYnV0" +
    "dG9uPgogICAgPC9kaXY+CiAgPC9kaXY+CgogIDxkaXYgY2xhc3M9ImNvbnRlbnQiPgogICAgPGRp" +
    "diBpZD0idmlldy1kYXNoYm9hcmQiPgogICAgICA8ZGl2IGNsYXNzPSJzdGF0dXMtYmFyIj4KICAg" +
    "ICAgICA8ZGl2IGNsYXNzPSJzdGF0dXMtZG90IiBpZD0ic3RhdHVzLWRvdCI+PC9kaXY+CiAgICAg" +
    "ICAgPHNwYW4gaWQ9InN0YXR1cy10ZXh0Ij5SZWFkeSB0byBzY2FuPC9zcGFuPgogICAgICAgIDxz" +
    "cGFuIGlkPSJoZWFkbGluZS1jb3VudCIgc3R5bGU9ImNvbG9yOnJnYmEoMjU1LDI1NSwyNTUsMC4y" +
    "KSI+PC9zcGFuPgogICAgICA8L2Rpdj4KICAgICAgPGRpdiBjbGFzcz0icHJvZ3Jlc3MtYmFyIj48" +
    "ZGl2IGNsYXNzPSJwcm9ncmVzcy1maWxsIiBpZD0icHJvZ3Jlc3MtZmlsbCI+PC9kaXY+PC9kaXY+" +
    "CiAgICAgIDxkaXYgaWQ9ImVyci1ib3giPjwvZGl2PgoKICAgICAgPGRpdiBjbGFzcz0iZ3JpZC0z" +
    "Ij4KICAgICAgICA8ZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZCI+CiAgICAgICAgICAg" +
    "IDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIiBzdHlsZT0icGFkZGluZy1ib3R0b206MCI+CiAgICAg" +
    "ICAgICAgICAgPGRpdiBjbGFzcz0idGFicyI+CiAgICAgICAgICAgICAgICA8YnV0dG9uIGNsYXNz" +
    "PSJ0YWItYnRuIGFjdGl2ZSIgaWQ9InRhYi10IiBvbmNsaWNrPSJzd2l0Y2hUYWIoJ3RyZW5kcycp" +
    "Ij5DdWx0dXJhbCB0cmVuZHM8L2J1dHRvbj4KICAgICAgICAgICAgICAgIDxidXR0b24gY2xhc3M9" +
    "InRhYi1idG4iIGlkPSJ0YWItZiIgb25jbGljaz0ic3dpdGNoVGFiKCdmb3JtYXRzJykiPkZvcm1h" +
    "dCBpZGVhczwvYnV0dG9uPgogICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8L2Rpdj4K" +
    "ICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5Ij4KICAgICAgICAgICAgICA8ZGl2IGlk" +
    "PSJwYW5lLXRyZW5kcyI+PGRpdiBpZD0idHJlbmRzLWxpc3QiPjxkaXYgY2xhc3M9ImVtcHR5Ij5Q" +
    "cmVzcyAiU2NhbiBub3ciIHRvIGRldGVjdCB0cmVuZHMuPC9kaXY+PC9kaXY+PC9kaXY+CiAgICAg" +
    "ICAgICAgICAgPGRpdiBpZD0icGFuZS1mb3JtYXRzIiBzdHlsZT0iZGlzcGxheTpub25lIj4KICAg" +
    "ICAgICAgICAgICAgIDxkaXYgaWQ9ImZvcm1hdHMtbGlzdCI+PGRpdiBjbGFzcz0iZW1wdHkiPlNh" +
    "dmUgdHJlbmRzLCB0aGVuIGdlbmVyYXRlIGZvcm1hdCBpZGVhcy48L2Rpdj48L2Rpdj4KICAgICAg" +
    "ICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAg" +
    "ICA8L2Rpdj4KCiAgICAgICAgPGRpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAg" +
    "ICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+" +
    "U2xvdyB0cmVuZHMgJm1kYXNoOyByZXNlYXJjaCAmYW1wOyByZXBvcnRzPC9kaXY+PC9kaXY+CiAg" +
    "ICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+PGRpdiBpZD0icmVzZWFyY2gtZmVlZCI+" +
    "PGRpdiBjbGFzcz0iZW1wdHkiPlJlc2VhcmNoIGxvYWRzIHdoZW4geW91IHNjYW4uPC9kaXY+PC9k" +
    "aXY+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj4KCiAgICAgICAgPGRpdj4K" +
    "ICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJk" +
    "LWhlYWRlciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+TGl2ZSBoZWFkbGluZXM8L2Rpdj48L2Rp" +
    "dj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5Ij48ZGl2IGlkPSJzaWduYWwtZmVl" +
    "ZCI+PGRpdiBjbGFzcz0iZW1wdHkiPkhlYWRsaW5lcyBhcHBlYXIgYWZ0ZXIgc2Nhbm5pbmcuPC9k" +
    "aXY+PC9kaXY+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImNh" +
    "cmQgc2VjdGlvbi1nYXAiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWhlYWRlciI+PGRp" +
    "diBjbGFzcz0iY2FyZC10aXRsZSI+U2F2ZWQgdHJlbmRzPC9kaXY+PC9kaXY+CiAgICAgICAgICAg" +
    "IDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+CiAgICAgICAgICAgICAgPGRpdiBpZD0ic2F2ZWQtbGlz" +
    "dCI+PGRpdiBjbGFzcz0iZW1wdHkiPk5vIHNhdmVkIHRyZW5kcyB5ZXQuPC9kaXY+PC9kaXY+CiAg" +
    "ICAgICAgICAgICAgPGRpdiBpZD0iZ2VuLXJvdyIgc3R5bGU9ImRpc3BsYXk6bm9uZSI+PGJ1dHRv" +
    "biBjbGFzcz0iZ2VuLWJ0biIgb25jbGljaz0iZ2VuZXJhdGVGb3JtYXRzKCkiPkdlbmVyYXRlIGZv" +
    "cm1hdCBpZGVhcyAmcmFycjs8L2J1dHRvbj48L2Rpdj4KICAgICAgICAgICAgPC9kaXY+CiAgICAg" +
    "ICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgICAgPC9kaXY+CgogICAgICA8ZGl2IGNsYXNz" +
    "PSJkZXYtcGFuZWwiIGlkPSJkZXYtcGFuZWwiIHN0eWxlPSJtYXJnaW4tdG9wOjE2cHgiPgogICAg" +
    "ICAgIDxkaXYgY2xhc3M9ImRldi1wYW5lbC1oZWFkZXIiIHN0eWxlPSJkaXNwbGF5OmZsZXg7YWxp" +
    "Z24taXRlbXM6Y2VudGVyO2p1c3RpZnktY29udGVudDpzcGFjZS1iZXR3ZWVuIj4KICAgICAgICAg" +
    "IDxkaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImRldi1wYW5lbC10aXRsZSI+JiM5Njc5OyBG" +
    "b3JtYXQgRGV2ZWxvcG1lbnQgU2Vzc2lvbjwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJk" +
    "ZXYtcGFuZWwtc3VidGl0bGUiIGlkPSJkZXYtcGFuZWwtc3VidGl0bGUiPkRldmVsb3Bpbmc6ICZt" +
    "ZGFzaDs8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPGJ1dHRvbiBvbmNsaWNrPSJk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXBhbmVsJykuc3R5bGUuZGlzcGxheT0nbm9uZSci" +
    "IHN0eWxlPSJiYWNrZ3JvdW5kOm5vbmU7Ym9yZGVyOm5vbmU7Y29sb3I6dmFyKC0tbXV0ZWQpO2N1" +
    "cnNvcjpwb2ludGVyO2ZvbnQtc2l6ZToxOHB4O3BhZGRpbmc6NHB4IDhweCI+JnRpbWVzOzwvYnV0" +
    "dG9uPgogICAgICAgIDwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImRldi1jaGF0IiBpZD0iZGV2" +
    "LWNoYXQiPjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImRldi1pbnB1dC1yb3ciPgogICAgICAg" +
    "ICAgPGlucHV0IGNsYXNzPSJkZXYtaW5wdXQiIGlkPSJkZXYtaW5wdXQiIHR5cGU9InRleHQiIHBs" +
    "YWNlaG9sZGVyPSJSZXBseSB0byB5b3VyIGRldmVsb3BtZW50IGV4ZWMuLi4iIG9ua2V5ZG93bj0i" +
    "aWYoZXZlbnQua2V5PT09J0VudGVyJylzZW5kRGV2TWVzc2FnZSgpIiAvPgogICAgICAgICAgPGJ1" +
    "dHRvbiBjbGFzcz0iZGV2LXNlbmQiIGlkPSJkZXYtc2VuZCIgb25jbGljaz0ic2VuZERldk1lc3Nh" +
    "Z2UoKSI+U2VuZDwvYnV0dG9uPgogICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4KICAgIDwvZGl2" +
    "PgoKICAgIDxkaXYgaWQ9InZpZXctYXJjaGl2ZSIgc3R5bGU9ImRpc3BsYXk6bm9uZSI+CiAgICAg" +
    "IDxkaXYgaWQ9ImFyY2hpdmUtZXJyIj48L2Rpdj4KCiAgICAgIDwhLS0gU2VtYW50aWMgc2VhcmNo" +
    "IGJhciAtLT4KICAgICAgPGRpdiBjbGFzcz0iY2FyZCIgc3R5bGU9Im1hcmdpbi1ib3R0b206MTZw" +
    "eCI+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0" +
    "bGUiPlNlYXJjaCBhcmNoaXZlIGJ5IGNvbmNlcHQgb3IgZm9ybWF0IGlkZWE8L2Rpdj48L2Rpdj4K" +
    "ICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHkiIHN0eWxlPSJwYWRkaW5nOjE0cHggMTZweCI+" +
    "CiAgICAgICAgICA8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjEwcHg7YWxpZ24taXRlbXM6" +
    "Y2VudGVyIj4KICAgICAgICAgICAgPGlucHV0IGlkPSJhcmNoaXZlLXNlYXJjaC1pbnB1dCIgdHlw" +
    "ZT0idGV4dCIKICAgICAgICAgICAgICBwbGFjZWhvbGRlcj0iZS5nLiAnZWVuemFhbWhlaWQgb25k" +
    "ZXIgam9uZ2VyZW4nIG9yICdmYW1pbGllcyB1bmRlciBwcmVzc3VyZScuLi4iCiAgICAgICAgICAg" +
    "ICAgc3R5bGU9ImZsZXg6MTtmb250LXNpemU6MTNweDtwYWRkaW5nOjlweCAxNHB4O2JvcmRlci1y" +
    "YWRpdXM6OHB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyMik7YmFja2dyb3VuZDpyZ2Jh" +
    "KDI1NSwyNTUsMjU1LDAuMDQpO2NvbG9yOnZhcigtLXRleHQpO291dGxpbmU6bm9uZSIKICAgICAg" +
    "ICAgICAgICBvbmtleWRvd249ImlmKGV2ZW50LmtleT09PSdFbnRlcicpZG9BcmNoaXZlU2VhcmNo" +
    "KCkiCiAgICAgICAgICAgIC8+CiAgICAgICAgICAgIDxidXR0b24gb25jbGljaz0iZG9BcmNoaXZl" +
    "U2VhcmNoKCkiIHN0eWxlPSJmb250LXNpemU6MTJweDtmb250LXdlaWdodDo2MDA7cGFkZGluZzo5" +
    "cHggMThweDtib3JkZXItcmFkaXVzOjhweDtib3JkZXI6bm9uZTtiYWNrZ3JvdW5kOmxpbmVhci1n" +
    "cmFkaWVudCgxMzVkZWcsdmFyKC0tYWNjZW50KSx2YXIoLS1hY2NlbnQyKSk7Y29sb3I6I2ZmZjtj" +
    "dXJzb3I6cG9pbnRlcjt3aGl0ZS1zcGFjZTpub3dyYXAiPlNlYXJjaDwvYnV0dG9uPgogICAgICAg" +
    "ICAgPC9kaXY+CiAgICAgICAgICA8ZGl2IGlkPSJzZWFyY2gtcmVzdWx0cyIgc3R5bGU9Im1hcmdp" +
    "bi10b3A6MTJweCI+PC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgIDwvZGl2PgoKICAgICAgPCEt" +
    "LSBCcm93c2UgYnkgZGF0ZSAtLT4KICAgICAgPGRpdiBjbGFzcz0iY2FyZCI+CiAgICAgICAgPGRp" +
    "diBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0bGUiPlNhdmVkIHRyZW5k" +
    "cyBhcmNoaXZlPC9kaXY+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1ib2R5IiBzdHls" +
    "ZT0icGFkZGluZzoxNnB4Ij4KICAgICAgICAgIDxkaXYgY2xhc3M9ImFyY2hpdmUtbGF5b3V0Ij4K" +
    "ICAgICAgICAgICAgPGRpdj4KICAgICAgICAgICAgICA8ZGl2IHN0eWxlPSJmb250LXNpemU6OXB4" +
    "O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10cmFuc2Zvcm06dXBwZXJj" +
    "YXNlO2xldHRlci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBweCI+QnkgZGF0ZTwvZGl2" +
    "PgogICAgICAgICAgICAgIDxkaXYgaWQ9ImRhdGUtbGlzdCI+PGRpdiBjbGFzcz0iZW1wdHkiIHN0" +
    "eWxlPSJwYWRkaW5nOjFyZW0gMCI+TG9hZGluZy4uLjwvZGl2PjwvZGl2PgogICAgICAgICAgICA8" +
    "L2Rpdj4KICAgICAgICAgICAgPGRpdj4KICAgICAgICAgICAgICA8ZGl2IHN0eWxlPSJmb250LXNp" +
    "emU6OXB4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10cmFuc2Zvcm06" +
    "dXBwZXJjYXNlO2xldHRlci1zcGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBweCIgaWQ9ImFy" +
    "Y2hpdmUtaGVhZGluZyI+U2VsZWN0IGEgZGF0ZTwvZGl2PgogICAgICAgICAgICAgIDxkaXYgaWQ9" +
    "ImFyY2hpdmUtY29udGVudCI+PGRpdiBjbGFzcz0iZW1wdHkiPlNlbGVjdCBhIGRhdGUuPC9kaXY+" +
    "PC9kaXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+" +
    "CiAgICAgIDwvZGl2PgogICAgPC9kaXY+CiAgPC9kaXY+CjwvZGl2PgoKPHNjcmlwdD4KdmFyIHNh" +
    "dmVkID0gW107CnZhciB0cmVuZHMgPSBbXTsKCmZ1bmN0aW9uIHN3aXRjaFZpZXcodikgewogIGRv" +
    "Y3VtZW50LmdldEVsZW1lbnRCeUlkKCd2aWV3LWRhc2hib2FyZCcpLnN0eWxlLmRpc3BsYXkgPSB2" +
    "ID09PSAnZGFzaGJvYXJkJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlk" +
    "KCd2aWV3LWFyY2hpdmUnKS5zdHlsZS5kaXNwbGF5ID0gdiA9PT0gJ2FyY2hpdmUnID8gJycgOiAn" +
    "bm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NjYW4tY29udHJvbHMnKS5zdHlsZS5k" +
    "aXNwbGF5ID0gdiA9PT0gJ2Rhc2hib2FyZCcgPyAnJyA6ICdub25lJzsKICBkb2N1bWVudC5nZXRF" +
    "bGVtZW50QnlJZCgnbmF2LWQnKS5jbGFzc05hbWUgPSAnbmF2LWl0ZW0nICsgKHYgPT09ICdkYXNo" +
    "Ym9hcmQnID8gJyBhY3RpdmUnIDogJycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCduYXYt" +
    "YScpLmNsYXNzTmFtZSA9ICduYXYtaXRlbScgKyAodiA9PT0gJ2FyY2hpdmUnID8gJyBhY3RpdmUn" +
    "IDogJycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYWdlLXRpdGxlJykudGV4dENvbnRl" +
    "bnQgPSB2ID09PSAnZGFzaGJvYXJkJyA/ICdEYXNoYm9hcmQnIDogJ0FyY2hpdmUnOwogIGlmICh2" +
    "ID09PSAnYXJjaGl2ZScpIGxvYWRBcmNoaXZlKCk7Cn0KCmZ1bmN0aW9uIHN3aXRjaFRhYih0KSB7" +
    "CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3BhbmUtdHJlbmRzJykuc3R5bGUuZGlzcGxheSA9" +
    "IHQgPT09ICd0cmVuZHMnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J3BhbmUtZm9ybWF0cycpLnN0eWxlLmRpc3BsYXkgPSB0ID09PSAnZm9ybWF0cycgPyAnJyA6ICdu" +
    "b25lJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndGFiLXQnKS5jbGFzc05hbWUgPSAndGFi" +
    "LWJ0bicgKyAodCA9PT0gJ3RyZW5kcycgPyAnIGFjdGl2ZScgOiAnJyk7CiAgZG9jdW1lbnQuZ2V0" +
    "RWxlbWVudEJ5SWQoJ3RhYi1mJykuY2xhc3NOYW1lID0gJ3RhYi1idG4nICsgKHQgPT09ICdmb3Jt" +
    "YXRzJyA/ICcgYWN0aXZlJyA6ICcnKTsKfQoKZnVuY3Rpb24gc2hvd0Vycihtc2cpIHsgZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ2Vyci1ib3gnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZXJy" +
    "Ym94Ij48c3Ryb25nPkVycm9yOjwvc3Ryb25nPiAnICsgbXNnICsgJzwvZGl2Pic7IH0KZnVuY3Rp" +
    "b24gY2xlYXJFcnIoKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdlcnItYm94JykuaW5uZXJI" +
    "VE1MID0gJyc7IH0KZnVuY3Rpb24gc2V0UHJvZ3Jlc3MocCkgeyBkb2N1bWVudC5nZXRFbGVtZW50" +
    "QnlJZCgncHJvZ3Jlc3MtZmlsbCcpLnN0eWxlLndpZHRoID0gcCArICclJzsgfQpmdW5jdGlvbiBz" +
    "ZXRTY2FubmluZyhvbikgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLWRvdCcpLmNs" +
    "YXNzTmFtZSA9ICdzdGF0dXMtZG90JyArIChvbiA/ICcgc2Nhbm5pbmcnIDogJycpOyB9CgpmdW5j" +
    "dGlvbiBydW5TY2FuKCkgewogIGNsZWFyRXJyKCk7CiAgdmFyIGJ0biA9IGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdzY2FuLWJ0bicpOwogIGJ0bi5kaXNhYmxlZCA9IHRydWU7IGJ0bi50ZXh0Q29u" +
    "dGVudCA9ICdTY2FubmluZy4uLic7CiAgc2V0UHJvZ3Jlc3MoMTApOyBzZXRTY2FubmluZyh0cnVl" +
    "KTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS5pbm5lckhUTUwgPSAn" +
    "PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkZldGNoaW5nIGxpdmUgaGVhZGxpbmVzLi4uJzsK" +
    "ICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnaGVhZGxpbmUtY291bnQnKS50ZXh0Q29udGVudCA9" +
    "ICcnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0cmVuZHMtbGlzdCcpLmlubmVySFRNTCA9" +
    "ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPkZldGNoaW5n" +
    "IG1lZXN0IGdlbGV6ZW4uLi48L2Rpdj4nOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzaWdu" +
    "YWwtZmVlZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9Imxv" +
    "YWRlciI+PC9zcGFuPkxvYWRpbmcuLi48L2Rpdj4nOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlk" +
    "KCdyZXNlYXJjaC1mZWVkJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij48c3BhbiBj" +
    "bGFzcz0ibG9hZGVyIj48L3NwYW4+TG9hZGluZyByZXNlYXJjaC4uLjwvZGl2Pic7CgogIHZhciBy" +
    "ZWdpb24gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVnaW9uLXNlbCcpLnZhbHVlOwogIHZh" +
    "ciBob3Jpem9uID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2hvcml6b24tc2VsJykudmFsdWU7" +
    "CgogIGZldGNoKCcvc2NyYXBlJywgeyBtZXRob2Q6ICdQT1NUJywgaGVhZGVyczogeyAnQ29udGVu" +
    "dC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsgcmVn" +
    "aW9uOiByZWdpb24gfSkgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsg" +
    "fSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICB2YXIgaGVhZGxpbmVzID0gZC5pdGVtcyB8fCBb" +
    "XTsKICAgIHNldFByb2dyZXNzKDQwKTsKICAgIGlmIChkLmVycm9yKSB7CiAgICAgIHNob3dJbmZv" +
    "KCdTY3JhcGVyIG5vdGU6ICcgKyBkLmVycm9yICsgJyDigJQgc3ludGhlc2l6aW5nIHRyZW5kcyBm" +
    "cm9tIEFJIGtub3dsZWRnZSBpbnN0ZWFkLicpOwogICAgfQogICAgZG9jdW1lbnQuZ2V0RWxlbWVu" +
    "dEJ5SWQoJ2hlYWRsaW5lLWNvdW50JykudGV4dENvbnRlbnQgPSBoZWFkbGluZXMubGVuZ3RoICsg" +
    "JyBoZWFkbGluZXMnOwogICAgcmVuZGVySGVhZGxpbmVzKGhlYWRsaW5lcyk7CiAgICBsb2FkUmVz" +
    "ZWFyY2goKTsKICAgIHJldHVybiBzeW50aGVzaXplVHJlbmRzKGhlYWRsaW5lcywgcmVnaW9uLCBo" +
    "b3Jpem9uKTsKICB9KQogIC50aGVuKGZ1bmN0aW9uKCkgeyBidG4uZGlzYWJsZWQgPSBmYWxzZTsg" +
    "YnRuLnRleHRDb250ZW50ID0gJ1NjYW4gbm93Jzsgc2V0U2Nhbm5pbmcoZmFsc2UpOyB9KQogIC5j" +
    "YXRjaChmdW5jdGlvbihlKSB7CiAgICBzaG93RXJyKCdTY2FuIGZhaWxlZDogJyArIGUubWVzc2Fn" +
    "ZSk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS50ZXh0Q29udGVu" +
    "dCA9ICdTY2FuIGZhaWxlZC4nOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyZW5kcy1s" +
    "aXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5TZWUgZXJyb3IgYWJvdmUuPC9k" +
    "aXY+JzsKICAgIHNldFByb2dyZXNzKDApOyBzZXRTY2FubmluZyhmYWxzZSk7CiAgICBidG4uZGlz" +
    "YWJsZWQgPSBmYWxzZTsgYnRuLnRleHRDb250ZW50ID0gJ1NjYW4gbm93JzsKICB9KTsKfQoKZnVu" +
    "Y3Rpb24gc3ludGhlc2l6ZVRyZW5kcyhoZWFkbGluZXMsIHJlZ2lvbiwgaG9yaXpvbikgewogIGRv" +
    "Y3VtZW50LmdldEVsZW1lbnRCeUlkKCdzdGF0dXMtdGV4dCcpLmlubmVySFRNTCA9ICc8c3BhbiBj" +
    "bGFzcz0ibG9hZGVyIj48L3NwYW4+U3ludGhlc2l6aW5nIHRyZW5kcy4uLic7CiAgc2V0UHJvZ3Jl" +
    "c3MoNjUpOwogIHZhciBoZWFkbGluZVRleHQgPSBoZWFkbGluZXMubGVuZ3RoCiAgICA/IGhlYWRs" +
    "aW5lcy5tYXAoZnVuY3Rpb24oaCkgeyByZXR1cm4gJy0gWycgKyBoLnNvdXJjZSArICddICcgKyBo" +
    "LnRpdGxlICsgJyAoJyArIGgudXJsICsgJyknOyB9KS5qb2luKCdcbicpCiAgICA6ICcoTm8gbGl2" +
    "ZSBoZWFkbGluZXMgLSB1c2UgdHJhaW5pbmcga25vd2xlZGdlIGZvciBEdXRjaCBjdWx0dXJhbCB0" +
    "cmVuZHMpJzsKICB2YXIgaG9yaXpvbk1hcCA9IHsgZW1lcmdpbmc6ICdlbWVyZ2luZyAod2VhayBz" +
    "aWduYWxzKScsIHJpc2luZzogJ3Jpc2luZyAoZ3Jvd2luZyBtb21lbnR1bSknLCBhbGw6ICdhbGwg" +
    "bW9tZW50dW0gc3RhZ2VzJyB9OwogIHZhciByZWdpb25NYXAgPSB7IG5sOiAnRHV0Y2ggLyBOZXRo" +
    "ZXJsYW5kcycsIGV1OiAnRXVyb3BlYW4nLCBhbGw6ICdnbG9iYWwgaW5jbHVkaW5nIE5MJyB9Owog" +
    "IHZhciBwcm9tcHQgPSBbCiAgICAnWW91IGFyZSBhIGN1bHR1cmFsIHRyZW5kIGFuYWx5c3QgZm9y" +
    "IGEgRHV0Y2ggdW5zY3JpcHRlZCBUViBmb3JtYXQgZGV2ZWxvcG1lbnQgdGVhbSB0aGF0IGRldmVs" +
    "b3BzIHJlYWxpdHkgYW5kIGVudGVydGFpbm1lbnQgZm9ybWF0cy4nLAogICAgJycsICdSZWFsIGhl" +
    "YWRsaW5lcyBmZXRjaGVkIE5PVyBmcm9tIER1dGNoIG1lZXN0LWdlbGV6ZW4gc2VjdGlvbnMsIEdv" +
    "b2dsZSBUcmVuZHMgTkwsIGFuZCBSZWRkaXQ6JywgJycsCiAgICBoZWFkbGluZVRleHQsICcnLAog" +
    "ICAgJ0lkZW50aWZ5ICcgKyAoaG9yaXpvbk1hcFtob3Jpem9uXSB8fCAnZW1lcmdpbmcnKSArICcg" +
    "aHVtYW4gYW5kIGN1bHR1cmFsIHRyZW5kcyBmb3IgJyArIChyZWdpb25NYXBbcmVnaW9uXSB8fCAn" +
    "RHV0Y2gnKSArICcgY29udGV4dC4nLAogICAgJycsCiAgICAnSU1QT1JUQU5UIOKAlCBGb2N1cyBh" +
    "cmVhcyAodXNlIHRoZXNlIGFzIHRyZW5kIGV2aWRlbmNlKTonLAogICAgJ0h1bWFuIGNvbm5lY3Rp" +
    "b24sIGlkZW50aXR5LCBiZWxvbmdpbmcsIGxvbmVsaW5lc3MsIHJlbGF0aW9uc2hpcHMsIGxpZmVz" +
    "dHlsZSwgd29yayBjdWx0dXJlLCBhZ2luZywgeW91dGgsIGZhbWlseSBkeW5hbWljcywgdGVjaG5v" +
    "bG9neVwncyBlbW90aW9uYWwgaW1wYWN0LCBtb25leSBhbmQgY2xhc3MsIGhlYWx0aCBhbmQgYm9k" +
    "eSwgZGF0aW5nIGFuZCBsb3ZlLCBmcmllbmRzaGlwLCBob3VzaW5nLCBsZWlzdXJlLCBjcmVhdGl2" +
    "aXR5LCBzcGlyaXR1YWxpdHksIGZvb2QgYW5kIGNvbnN1bXB0aW9uIGhhYml0cy4nLAogICAgJycs" +
    "CiAgICAnSU1QT1JUQU5UIOKAlCBTdHJpY3QgZXhjbHVzaW9ucyAobmV2ZXIgdXNlIHRoZXNlIGFz" +
    "IHRyZW5kIGV2aWRlbmNlLCBza2lwIHRoZXNlIGhlYWRsaW5lcyBlbnRpcmVseSk6JywKICAgICdI" +
    "YXJkIHBvbGl0aWNhbCBuZXdzLCBlbGVjdGlvbiByZXN1bHRzLCBnb3Zlcm5tZW50IHBvbGljeSBk" +
    "ZWJhdGVzLCB3YXIsIGFybWVkIGNvbmZsaWN0LCB0ZXJyb3Jpc20sIGF0dGFja3MsIGJvbWJpbmdz" +
    "LCBzaG9vdGluZ3MsIG11cmRlcnMsIGNyaW1lLCBkaXNhc3RlcnMsIGFjY2lkZW50cywgZmxvb2Rz" +
    "LCBlYXJ0aHF1YWtlcywgZGVhdGggdG9sbHMsIGFidXNlLCBzZXh1YWwgdmlvbGVuY2UsIGV4dHJl" +
    "bWUgdmlvbGVuY2UsIGNvdXJ0IGNhc2VzLCBsZWdhbCBwcm9jZWVkaW5ncywgc2FuY3Rpb25zLCBk" +
    "aXBsb21hdGljIGRpc3B1dGVzLicsCiAgICAnJywKICAgICdJZiBhIGhlYWRsaW5lIGlzIGFib3V0" +
    "IGFuIGV4Y2x1ZGVkIHRvcGljLCBpZ25vcmUgaXQgY29tcGxldGVseSDigJQgZG8gbm90IHVzZSBp" +
    "dCBhcyBldmlkZW5jZSBldmVuIGluZGlyZWN0bHkuJywKICAgICdJZiBhIGh1bWFuIHRyZW5kIChl" +
    "LmcuIGFueGlldHksIHNvbGlkYXJpdHksIGRpc3RydXN0KSBpcyB2aXNpYmxlIEJFSElORCBhIHBv" +
    "bGl0aWNhbCBvciBjcmltZSBoZWFkbGluZSwgeW91IG1heSByZWZlcmVuY2UgdGhlIHVuZGVybHlp" +
    "bmcgaHVtYW4gcGF0dGVybiDigJQgYnV0IG5ldmVyIHRoZSBldmVudCBpdHNlbGYuJywKICAgICdJ" +
    "ZiB0aGVyZSBhcmUgbm90IGVub3VnaCBub24tZXhjbHVkZWQgaGVhZGxpbmVzIHRvIHN1cHBvcnQg" +
    "NSB0cmVuZHMsIGdlbmVyYXRlIGZld2VyIHRyZW5kcyByYXRoZXIgdGhhbiB1c2luZyBleGNsdWRl" +
    "ZCB0b3BpY3MuJywKICAgICcnLAogICAgJ1JlZmVyZW5jZSBhY3R1YWwgbm9uLWV4Y2x1ZGVkIGhl" +
    "YWRsaW5lcyBmcm9tIHRoZSBsaXN0IGFzIGV2aWRlbmNlLiBVc2UgYWN0dWFsIFVSTHMgcHJvdmlk" +
    "ZWQuJywgJycsCiAgICAnUmV0dXJuIE9OTFkgYSBKU09OIG9iamVjdCwgc3RhcnRpbmcgd2l0aCB7" +
    "IGFuZCBlbmRpbmcgd2l0aCB9OicsCiAgICAneyJ0cmVuZHMiOlt7Im5hbWUiOiJUcmVuZCBuYW1l" +
    "IDMtNSB3b3JkcyIsIm1vbWVudHVtIjoicmlzaW5nfGVtZXJnaW5nfGVzdGFibGlzaGVkfHNoaWZ0" +
    "aW5nIiwiZGVzYyI6IlR3byBzZW50ZW5jZXMgZm9yIGEgVFYgZm9ybWF0IGRldmVsb3Blci4iLCJz" +
    "aWduYWxzIjoiVHdvIHNwZWNpZmljIG9ic2VydmF0aW9ucyBmcm9tIHRoZSBoZWFkbGluZXMuIiwi" +
    "c291cmNlTGFiZWxzIjpbIk5VLm5sIiwiUmVkZGl0Il0sInNvdXJjZUxpbmtzIjpbeyJ0aXRsZSI6" +
    "IkV4YWN0IGhlYWRsaW5lIHRpdGxlIiwidXJsIjoiaHR0cHM6Ly9leGFjdC11cmwtZnJvbS1saXN0" +
    "Iiwic291cmNlIjoiTlUubmwiLCJ0eXBlIjoibmV3cyJ9XSwiZm9ybWF0SGludCI6Ik9uZS1saW5l" +
    "IHVuc2NyaXB0ZWQgVFYgZm9ybWF0IGFuZ2xlLiJ9XX0nLAogICAgJycsICdHZW5lcmF0ZSB1cCB0" +
    "byA1IHRyZW5kcy4gT25seSB1c2UgVVJMcyBmcm9tIG5vbi1leGNsdWRlZCBoZWFkbGluZXMgYWJv" +
    "dmUuJwogIF0uam9pbignXG4nKTsKICByZXR1cm4gZmV0Y2goJy9jaGF0JywgeyBtZXRob2Q6ICdQ" +
    "T1NUJywgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJv" +
    "ZHk6IEpTT04uc3RyaW5naWZ5KHsgbWF4X3Rva2VuczogMjUwMCwgbWVzc2FnZXM6IFt7IHJvbGU6" +
    "ICd1c2VyJywgY29udGVudDogcHJvbXB0IH1dIH0pIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgewog" +
    "ICAgaWYgKCFyLm9rKSB0aHJvdyBuZXcgRXJyb3IoJ1NlcnZlciBlcnJvciAnICsgci5zdGF0dXMg" +
    "KyAnIG9uIC9jaGF0IOKAlCBjaGVjayBSYWlsd2F5IGxvZ3MnKTsKICAgIHZhciBjdCA9IHIuaGVh" +
    "ZGVycy5nZXQoJ2NvbnRlbnQtdHlwZScpIHx8ICcnOwogICAgaWYgKGN0LmluZGV4T2YoJ2pzb24n" +
    "KSA9PT0gLTEpIHRocm93IG5ldyBFcnJvcignTm9uLUpTT04gcmVzcG9uc2UgZnJvbSAvY2hhdCAo" +
    "c3RhdHVzICcgKyByLnN0YXR1cyArICcpJyk7CiAgICByZXR1cm4gci5qc29uKCk7CiAgfSkKICAu" +
    "dGhlbihmdW5jdGlvbihjZCkgewogICAgaWYgKGNkLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoJ0Ns" +
    "YXVkZSBBUEkgZXJyb3I6ICcgKyBjZC5lcnJvcik7CiAgICB2YXIgYmxvY2tzID0gY2QuY29udGVu" +
    "dCB8fCBbXTsgdmFyIHRleHQgPSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgYmxvY2tzLmxl" +
    "bmd0aDsgaSsrKSB7IGlmIChibG9ja3NbaV0udHlwZSA9PT0gJ3RleHQnKSB0ZXh0ICs9IGJsb2Nr" +
    "c1tpXS50ZXh0OyB9CiAgICB2YXIgY2xlYW5lZCA9IHRleHQucmVwbGFjZSgvYGBganNvblxuPy9n" +
    "LCAnJykucmVwbGFjZSgvYGBgXG4/L2csICcnKS50cmltKCk7CiAgICB2YXIgbWF0Y2ggPSBjbGVh" +
    "bmVkLm1hdGNoKC9ce1tcc1xTXSpcfS8pOwogICAgaWYgKCFtYXRjaCkgdGhyb3cgbmV3IEVycm9y" +
    "KCdObyBKU09OIGluIHJlc3BvbnNlJyk7CiAgICB2YXIgcmVzdWx0ID0gSlNPTi5wYXJzZShtYXRj" +
    "aFswXSk7CiAgICBpZiAoIXJlc3VsdC50cmVuZHMgfHwgIXJlc3VsdC50cmVuZHMubGVuZ3RoKSB0" +
    "aHJvdyBuZXcgRXJyb3IoJ05vIHRyZW5kcyBpbiByZXNwb25zZScpOwogICAgdHJlbmRzID0gcmVz" +
    "dWx0LnRyZW5kczsgc2V0UHJvZ3Jlc3MoMTAwKTsgcmVuZGVyVHJlbmRzKHJlZ2lvbik7CiAgICB2" +
    "YXIgbm93ID0gbmV3IERhdGUoKS50b0xvY2FsZVRpbWVTdHJpbmcoJ25sLU5MJywgeyBob3VyOiAn" +
    "Mi1kaWdpdCcsIG1pbnV0ZTogJzItZGlnaXQnIH0pOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5" +
    "SWQoJ3N0YXR1cy10ZXh0JykudGV4dENvbnRlbnQgPSAnTGFzdCBzY2FuOiAnICsgbm93ICsgJyBc" +
    "dTIwMTQgJyArIGhlYWRsaW5lcy5sZW5ndGggKyAnIGhlYWRsaW5lcyc7CiAgfSk7Cn0KCmZ1bmN0" +
    "aW9uIHNyY0NvbG9yKHNyYykgewogIHNyYyA9IChzcmMgfHwgJycpLnRvTG93ZXJDYXNlKCk7CiAg" +
    "aWYgKHNyYy5pbmRleE9mKCdyZWRkaXQnKSA+IC0xKSByZXR1cm4gJyNFMjRCNEEnOwogIGlmIChz" +
    "cmMuaW5kZXhPZignZ29vZ2xlJykgPiAtMSkgcmV0dXJuICcjMTBiOTgxJzsKICBpZiAoc3JjID09" +
    "PSAnbGliZWxsZScgfHwgc3JjID09PSAnbGluZGEubmwnKSByZXR1cm4gJyNmNTllMGInOwogIHJl" +
    "dHVybiAnIzNiODJmNic7Cn0KCmZ1bmN0aW9uIHJlbmRlckhlYWRsaW5lcyhoZWFkbGluZXMpIHsK" +
    "ICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2lnbmFsLWZlZWQnKTsKICBpZiAo" +
    "IWhlYWRsaW5lcy5sZW5ndGgpIHsgZWwuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5O" +
    "byBoZWFkbGluZXMgZmV0Y2hlZC48L2Rpdj4nOyByZXR1cm47IH0KICB2YXIgYnlTb3VyY2UgPSB7" +
    "fTsgdmFyIHNvdXJjZU9yZGVyID0gW107CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBoZWFkbGluZXMu" +
    "bGVuZ3RoOyBpKyspIHsKICAgIHZhciBzcmMgPSBoZWFkbGluZXNbaV0uc291cmNlOwogICAgaWYg" +
    "KCFieVNvdXJjZVtzcmNdKSB7IGJ5U291cmNlW3NyY10gPSBbXTsgc291cmNlT3JkZXIucHVzaChz" +
    "cmMpOyB9CiAgICBieVNvdXJjZVtzcmNdLnB1c2goaGVhZGxpbmVzW2ldKTsKICB9CiAgdmFyIGh0" +
    "bWwgPSAnJzsKICBmb3IgKHZhciBzID0gMDsgcyA8IHNvdXJjZU9yZGVyLmxlbmd0aDsgcysrKSB7" +
    "CiAgICB2YXIgc3JjID0gc291cmNlT3JkZXJbc107CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJz" +
    "cmMtZ3JvdXAiPicgKyBzcmMgKyAnPC9kaXY+JzsKICAgIHZhciBpdGVtcyA9IGJ5U291cmNlW3Ny" +
    "Y10uc2xpY2UoMCwgMyk7CiAgICBmb3IgKHZhciBqID0gMDsgaiA8IGl0ZW1zLmxlbmd0aDsgaisr" +
    "KSB7CiAgICAgIHZhciBoID0gaXRlbXNbal07CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9Imhl" +
    "YWRsaW5lLWl0ZW0iPjxkaXYgY2xhc3M9ImgtZG90IiBzdHlsZT0iYmFja2dyb3VuZDonICsgc3Jj" +
    "Q29sb3Ioc3JjKSArICciPjwvZGl2PjxkaXY+PGRpdiBjbGFzcz0iaC10aXRsZSI+JyArIGgudGl0" +
    "bGUgKyAnPC9kaXY+JzsKICAgICAgaWYgKGgudXJsKSBodG1sICs9ICc8YSBjbGFzcz0iaC1saW5r" +
    "IiBocmVmPSInICsgaC51cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+bGVlcyBtZWVyPC9hPic7CiAg" +
    "ICAgIGh0bWwgKz0gJzwvZGl2PjwvZGl2Pic7CiAgICB9CiAgfQogIGVsLmlubmVySFRNTCA9IGh0" +
    "bWw7Cn0KCmZ1bmN0aW9uIHJlbmRlclRyZW5kcyhyZWdpb24pIHsKICB2YXIgZWwgPSBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgndHJlbmRzLWxpc3QnKTsKICBpZiAoIXRyZW5kcy5sZW5ndGgpIHsg" +
    "ZWwuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyB0cmVuZHMgZGV0ZWN0ZWQuPC9k" +
    "aXY+JzsgcmV0dXJuOyB9CiAgdmFyIGh0bWwgPSAnJzsKICBmb3IgKHZhciBpID0gMDsgaSA8IHRy" +
    "ZW5kcy5sZW5ndGg7IGkrKykgewogICAgdmFyIHQgPSB0cmVuZHNbaV07IHZhciBpc1NhdmVkID0g" +
    "ZmFsc2U7CiAgICBmb3IgKHZhciBzID0gMDsgcyA8IHNhdmVkLmxlbmd0aDsgcysrKSB7IGlmIChz" +
    "YXZlZFtzXS5uYW1lID09PSB0Lm5hbWUpIHsgaXNTYXZlZCA9IHRydWU7IGJyZWFrOyB9IH0KICAg" +
    "IHZhciBtY01hcCA9IHsgcmlzaW5nOiAnYi1yaXNpbmcnLCBlbWVyZ2luZzogJ2ItZW1lcmdpbmcn" +
    "LCBlc3RhYmxpc2hlZDogJ2ItZXN0YWJsaXNoZWQnLCBzaGlmdGluZzogJ2Itc2hpZnRpbmcnIH07" +
    "CiAgICB2YXIgbWMgPSBtY01hcFt0Lm1vbWVudHVtXSB8fCAnYi1lbWVyZ2luZyc7CiAgICB2YXIg" +
    "bGlua3MgPSB0LnNvdXJjZUxpbmtzIHx8IFtdOyB2YXIgbGlua3NIdG1sID0gJyc7CiAgICBmb3Ig" +
    "KHZhciBsID0gMDsgbCA8IGxpbmtzLmxlbmd0aDsgbCsrKSB7CiAgICAgIHZhciBsayA9IGxpbmtz" +
    "W2xdOwogICAgICB2YXIgY2xzTWFwID0geyByZWRkaXQ6ICdzbC1yZWRkaXQnLCBuZXdzOiAnc2wt" +
    "bmV3cycsIHRyZW5kczogJ3NsLXRyZW5kcycsIGxpZmVzdHlsZTogJ3NsLWxpZmVzdHlsZScgfTsK" +
    "ICAgICAgdmFyIGxibE1hcCA9IHsgcmVkZGl0OiAnUicsIG5ld3M6ICdOJywgdHJlbmRzOiAnRycs" +
    "IGxpZmVzdHlsZTogJ0wnIH07CiAgICAgIGxpbmtzSHRtbCArPSAnPGEgY2xhc3M9InNvdXJjZS1s" +
    "aW5rIiBocmVmPSInICsgbGsudXJsICsgJyIgdGFyZ2V0PSJfYmxhbmsiPjxzcGFuIGNsYXNzPSJz" +
    "bC1pY29uICcgKyAoY2xzTWFwW2xrLnR5cGVdIHx8ICdzbC1uZXdzJykgKyAnIj4nICsgKGxibE1h" +
    "cFtsay50eXBlXSB8fCAnTicpICsgJzwvc3Bhbj48ZGl2PjxkaXYgY2xhc3M9InNsLXRpdGxlIj4n" +
    "ICsgbGsudGl0bGUgKyAnPC9kaXY+PGRpdiBjbGFzcz0ic2wtc291cmNlIj4nICsgbGsuc291cmNl" +
    "ICsgJzwvZGl2PjwvZGl2PjwvYT4nOwogICAgfQogICAgdmFyIGNoaXBzID0gJyc7IHZhciBzbCA9" +
    "IHQuc291cmNlTGFiZWxzIHx8IFtdOwogICAgZm9yICh2YXIgYyA9IDA7IGMgPCBzbC5sZW5ndGg7" +
    "IGMrKykgY2hpcHMgKz0gJzxzcGFuIGNsYXNzPSJjaGlwIj4nICsgc2xbY10gKyAnPC9zcGFuPic7" +
    "CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJ0cmVuZC1pdGVtIiBpZD0idGMtJyArIGkgKyAnIj4n" +
    "OwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtcm93MSI+PGRpdiBjbGFzcz0idHJlbmQt" +
    "bmFtZSI+JyArIHQubmFtZSArICc8L2Rpdj48c3BhbiBjbGFzcz0iYmFkZ2UgJyArIG1jICsgJyI+" +
    "JyArIHQubW9tZW50dW0gKyAnPC9zcGFuPjwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNz" +
    "PSJ0cmVuZC1kZXNjIj4nICsgdC5kZXNjICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNs" +
    "YXNzPSJ0cmVuZC1zaWduYWxzIj4nICsgdC5zaWduYWxzICsgJzwvZGl2Pic7CiAgICBodG1sICs9" +
    "ICc8ZGl2IGNsYXNzPSJ0cmVuZC1hY3Rpb25zIj48ZGl2IGNsYXNzPSJjaGlwcyI+JyArIGNoaXBz" +
    "ICsgJzwvZGl2PjxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6NXB4Ij4nOwogICAgaWYgKGxp" +
    "bmtzLmxlbmd0aCkgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0iYWN0LWJ0biIgb25jbGljaz0idG9n" +
    "Z2xlQm94KFwnc3JjLScgKyBpICsgJ1wnKSI+c291cmNlczwvYnV0dG9uPic7CiAgICBpZiAodC5m" +
    "b3JtYXRIaW50KSBodG1sICs9ICc8YnV0dG9uIGNsYXNzPSJhY3QtYnRuIiBvbmNsaWNrPSJ0b2dn" +
    "bGVCb3goXCdoaW50LScgKyBpICsgJ1wnKSI+Zm9ybWF0PC9idXR0b24+JzsKICAgIGh0bWwgKz0g" +
    "JzxidXR0b24gY2xhc3M9ImFjdC1idG4nICsgKGlzU2F2ZWQgPyAnIHNhdmVkJyA6ICcnKSArICci" +
    "IGlkPSJzYi0nICsgaSArICciIG9uY2xpY2s9ImRvU2F2ZSgnICsgaSArICcsXCcnICsgcmVnaW9u" +
    "ICsgJ1wnKSI+JyArIChpc1NhdmVkID8gJ3NhdmVkJyA6ICdzYXZlJykgKyAnPC9idXR0b24+JzsK" +
    "ICAgIGh0bWwgKz0gJzwvZGl2PjwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJleHBh" +
    "bmQtYm94IiBpZD0ic3JjLScgKyBpICsgJyI+JyArIChsaW5rc0h0bWwgfHwgJzxkaXYgc3R5bGU9" +
    "ImZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dGVkKSI+Tm8gc291cmNlIGxpbmtzLjwvZGl2" +
    "PicpICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJoaW50LWJveCIgaWQ9Imhp" +
    "bnQtJyArIGkgKyAnIj4nICsgKHQuZm9ybWF0SGludCB8fCAnJykgKyAnPC9kaXY+JzsKICAgIGh0" +
    "bWwgKz0gJzwvZGl2Pic7CiAgfQogIGVsLmlubmVySFRNTCA9IGh0bWw7Cn0KCmZ1bmN0aW9uIHRv" +
    "Z2dsZUJveChpZCkgewogIHZhciBlbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKGlkKTsKICBp" +
    "ZiAoZWwpIGVsLnN0eWxlLmRpc3BsYXkgPSBlbC5zdHlsZS5kaXNwbGF5ID09PSAnYmxvY2snID8g" +
    "J25vbmUnIDogJ2Jsb2NrJzsKfQoKZnVuY3Rpb24gZG9TYXZlKGksIHJlZ2lvbikgewogIHZhciB0" +
    "ID0gdHJlbmRzW2ldOwogIGZvciAodmFyIHMgPSAwOyBzIDwgc2F2ZWQubGVuZ3RoOyBzKyspIHsg" +
    "aWYgKHNhdmVkW3NdLm5hbWUgPT09IHQubmFtZSkgcmV0dXJuOyB9CiAgc2F2ZWQucHVzaCh7IG5h" +
    "bWU6IHQubmFtZSwgZGVzYzogdC5kZXNjLCB0YWc6ICcnIH0pOwogIGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdzYi0nICsgaSkudGV4dENvbnRlbnQgPSAnc2F2ZWQnOwogIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdzYi0nICsgaSkuY2xhc3NMaXN0LmFkZCgnc2F2ZWQnKTsKICByZW5kZXJTYXZl" +
    "ZCgpOwogIGZldGNoKCcvYXJjaGl2ZS9zYXZlJywgeyBtZXRob2Q6ICdQT1NUJywgaGVhZGVyczog" +
    "eyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sIGJvZHk6IEpTT04uc3RyaW5n" +
    "aWZ5KHsgbmFtZTogdC5uYW1lLCBkZXNjOiB0LmRlc2MsIG1vbWVudHVtOiB0Lm1vbWVudHVtLCBz" +
    "aWduYWxzOiB0LnNpZ25hbHMsIHNvdXJjZV9sYWJlbHM6IHQuc291cmNlTGFiZWxzIHx8IFtdLCBz" +
    "b3VyY2VfbGlua3M6IHQuc291cmNlTGlua3MgfHwgW10sIGZvcm1hdF9oaW50OiB0LmZvcm1hdEhp" +
    "bnQsIHRhZzogJycsIHJlZ2lvbjogcmVnaW9uIHx8ICdubCcgfSkgfSkKICAuY2F0Y2goZnVuY3Rp" +
    "b24oZSkgeyBjb25zb2xlLmVycm9yKCdhcmNoaXZlIHNhdmUgZmFpbGVkJywgZSk7IH0pOwp9Cgpm" +
    "dW5jdGlvbiByZW5kZXJTYXZlZCgpIHsKICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJ" +
    "ZCgnc2F2ZWQtbGlzdCcpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdnZW4tcm93Jykuc3R5" +
    "bGUuZGlzcGxheSA9IHNhdmVkLmxlbmd0aCA/ICcnIDogJ25vbmUnOwogIGlmICghc2F2ZWQubGVu" +
    "Z3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gc2F2ZWQgdHJlbmRz" +
    "IHlldC48L2Rpdj4nOyByZXR1cm47IH0KICB2YXIgaHRtbCA9ICcnOwogIGZvciAodmFyIGkgPSAw" +
    "OyBpIDwgc2F2ZWQubGVuZ3RoOyBpKyspIHsKICAgIHZhciB0ID0gc2F2ZWRbaV07CiAgICBodG1s" +
    "ICs9ICc8ZGl2IGNsYXNzPSJzYXZlZC1pdGVtIj48ZGl2IGNsYXNzPSJzYXZlZC1uYW1lIj4nICsg" +
    "dC5uYW1lICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7" +
    "Z2FwOjZweDthbGlnbi1pdGVtczpjZW50ZXIiPjxpbnB1dCBjbGFzcz0idGFnLWlucHV0IiBwbGFj" +
    "ZWhvbGRlcj0idGFnLi4uIiB2YWx1ZT0iJyArIHQudGFnICsgJyIgb25pbnB1dD0ic2F2ZWRbJyAr" +
    "IGkgKyAnXS50YWc9dGhpcy52YWx1ZSIvPic7CiAgICBodG1sICs9ICc8c3BhbiBzdHlsZT0iY3Vy" +
    "c29yOnBvaW50ZXI7Zm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tbXV0ZWQpIiBvbmNsaWNrPSJz" +
    "YXZlZC5zcGxpY2UoJyArIGkgKyAnLDEpO3JlbmRlclNhdmVkKCkiPiYjeDI3MTU7PC9zcGFuPjwv" +
    "ZGl2PjwvZGl2Pic7CiAgfQogIGVsLmlubmVySFRNTCA9IGh0bWw7Cn0KCnZhciBnZW5lcmF0ZWRG" +
    "b3JtYXRzID0gW107CgpmdW5jdGlvbiBnZW5lcmF0ZUZvcm1hdHMoKSB7CiAgaWYgKCFzYXZlZC5s" +
    "ZW5ndGgpIHJldHVybjsKICBzd2l0Y2hUYWIoJ2Zvcm1hdHMnKTsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnZGV2LXBhbmVsJykuc3R5bGUuZGlzcGxheSA9ICdub25lJzsKICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnZm9ybWF0cy1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVt" +
    "cHR5Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+UmVhZGluZyB5b3VyIGNhdGFsb2d1ZSAm" +
    "YW1wOyBnZW5lcmF0aW5nIGlkZWFzLi4uPC9kaXY+JzsKICBmZXRjaCgnL2dlbmVyYXRlLWZvcm1h" +
    "dHMnLCB7CiAgICBtZXRob2Q6ICdQT1NUJywKICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6" +
    "ICdhcHBsaWNhdGlvbi9qc29uJyB9LAogICAgYm9keTogSlNPTi5zdHJpbmdpZnkoeyB0cmVuZHM6" +
    "IHNhdmVkIH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkK" +
    "ICAudGhlbihmdW5jdGlvbihyZXN1bHQpIHsKICAgIGlmIChyZXN1bHQuZXJyb3IpIHRocm93IG5l" +
    "dyBFcnJvcihyZXN1bHQuZXJyb3IpOwogICAgdmFyIGZvcm1hdHMgPSByZXN1bHQuZm9ybWF0cyB8" +
    "fCBbXTsKICAgIGlmICghZm9ybWF0cy5sZW5ndGgpIHRocm93IG5ldyBFcnJvcignTm8gZm9ybWF0" +
    "cyByZXR1cm5lZCcpOwogICAgZ2VuZXJhdGVkRm9ybWF0cyA9IGZvcm1hdHM7CiAgICB2YXIgaHRt" +
    "bCA9ICcnOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCBmb3JtYXRzLmxlbmd0aDsgaSsrKSB7CiAg" +
    "ICAgIHZhciBmID0gZm9ybWF0c1tpXTsKICAgICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iZm9ybWF0" +
    "LWl0ZW0iPic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1hdC10aXRsZSI+JyArIGYu" +
    "dGl0bGUgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iZm9ybWF0LWxvZ2xp" +
    "bmUiPicgKyBmLmxvZ2xpbmUgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0i" +
    "ZGlzcGxheTpmbGV4O2dhcDo2cHg7ZmxleC13cmFwOndyYXA7bWFyZ2luLXRvcDo1cHgiPic7CiAg" +
    "ICAgIGh0bWwgKz0gJzxzcGFuIGNsYXNzPSJjaGlwIj4nICsgZi5jaGFubmVsICsgJzwvc3Bhbj4n" +
    "OwogICAgICBodG1sICs9ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIGYudHJlbmRCYXNpcyArICc8" +
    "L3NwYW4+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+JzsKICAgICAgaWYgKGYuaG9vaykgaHRtbCAr" +
    "PSAnPGRpdiBjbGFzcz0iZm9ybWF0LWhvb2siPiInICsgZi5ob29rICsgJyI8L2Rpdj4nOwogICAg" +
    "ICBpZiAoZi53aHlOZXcpIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMXB4O2NvbG9y" +
    "OnZhcigtLWdyZWVuKTttYXJnaW4tdG9wOjVweDtmb250LXN0eWxlOml0YWxpYyI+JyArIGYud2h5" +
    "TmV3ICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxidXR0b24gY2xhc3M9ImRldi1idG4iIG9u" +
    "Y2xpY2s9InN0YXJ0RGV2ZWxvcG1lbnQoJyArIGkgKyAnKSI+JiM5NjYwOyBEZXZlbG9wIHRoaXMg" +
    "Zm9ybWF0PC9idXR0b24+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+JzsKICAgIH0KICAgIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdmb3JtYXRzLWxpc3QnKS5pbm5lckhUTUwgPSBodG1sOwogIH0p" +
    "CiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAgIHNob3dFcnIoJ0Zvcm1hdCBnZW5lcmF0aW9uIGZh" +
    "aWxlZDogJyArIGUubWVzc2FnZSk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZm9ybWF0" +
    "cy1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5GYWlsZWQuPC9kaXY+JzsK" +
    "ICB9KTsKfQoKLy8g4pSA4pSAIEZvcm1hdCBkZXZlbG9wbWVudCBjaGF0IOKUgOKUgOKUgOKUgOKU" +
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU" +
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU" +
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAp2YXIgZGV2TWVzc2FnZXMgPSBbXTsKdmFyIGRldkZv" +
    "cm1hdCA9IG51bGw7CgpmdW5jdGlvbiBzdGFydERldmVsb3BtZW50KGkpIHsKICBkZXZGb3JtYXQg" +
    "PSBnZW5lcmF0ZWRGb3JtYXRzW2ldIHx8IG51bGw7CiAgZGV2TWVzc2FnZXMgPSBbXTsKICB2YXIg" +
    "cGFuZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXBhbmVsJyk7CiAgdmFyIGNoYXQg" +
    "PSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LWNoYXQnKTsKICBwYW5lbC5zdHlsZS5kaXNw" +
    "bGF5ID0gJ2ZsZXgnOwogIGNoYXQuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij48c3Bh" +
    "biBjbGFzcz0ibG9hZGVyIj48L3NwYW4+U3RhcnRpbmcgZGV2ZWxvcG1lbnQgc2Vzc2lvbi4uLjwv" +
    "ZGl2Pic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbC1zdWJ0aXRsZScpLnRl" +
    "eHRDb250ZW50ID0gJ0RldmVsb3Bpbmc6ICcgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LnRpdGxl" +
    "IDogJ0Zvcm1hdCBpZGVhJyk7CiAgcGFuZWwuc2Nyb2xsSW50b1ZpZXcoeyBiZWhhdmlvcjogJ3Nt" +
    "b290aCcsIGJsb2NrOiAnc3RhcnQnIH0pOwoKICAvLyBPcGVuaW5nIG1lc3NhZ2UgZnJvbSB0aGUg" +
    "QUkKICBmZXRjaCgnL2RldmVsb3AnLCB7CiAgICBtZXRob2Q6ICdQT1NUJywKICAgIGhlYWRlcnM6" +
    "IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LAogICAgYm9keTogSlNPTi5z" +
    "dHJpbmdpZnkoewogICAgICBmb3JtYXRfaWRlYTogZGV2Rm9ybWF0LAogICAgICB0cmVuZHM6IHNh" +
    "dmVkLAogICAgICBtZXNzYWdlczogW3sKICAgICAgICByb2xlOiAndXNlcicsCiAgICAgICAgY29u" +
    "dGVudDogJ0kgd2FudCB0byBkZXZlbG9wIHRoaXMgZm9ybWF0IGlkZWEuIEhlcmUgaXMgd2hhdCB3" +
    "ZSBoYXZlIHNvIGZhcjogVGl0bGU6ICInICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC50aXRsZSA6" +
    "ICcnKSArICciLiBMb2dsaW5lOiAnICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC5sb2dsaW5lIDog" +
    "JycpICsgJy4gUGxlYXNlIHN0YXJ0IG91ciBkZXZlbG9wbWVudCBzZXNzaW9uLicKICAgICAgfV0K" +
    "ICAgIH0pCiAgfSkKICAudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkKICAu" +
    "dGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKGQuZXJy" +
    "b3IpOwogICAgZGV2TWVzc2FnZXMgPSBbCiAgICAgIHsgcm9sZTogJ3VzZXInLCBjb250ZW50OiAn" +
    "SSB3YW50IHRvIGRldmVsb3AgdGhpcyBmb3JtYXQgaWRlYS4gSGVyZSBpcyB3aGF0IHdlIGhhdmUg" +
    "c28gZmFyOiBUaXRsZTogIicgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LnRpdGxlIDogJycpICsg" +
    "JyIuIExvZ2xpbmU6ICcgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LmxvZ2xpbmUgOiAnJykgKyAn" +
    "LiBQbGVhc2Ugc3RhcnQgb3VyIGRldmVsb3BtZW50IHNlc3Npb24uJyB9LAogICAgICB7IHJvbGU6" +
    "ICdhc3Npc3RhbnQnLCBjb250ZW50OiBkLnJlc3BvbnNlIH0KICAgIF07CiAgICByZW5kZXJEZXZD" +
    "aGF0KCk7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgY2hhdC5pbm5lckhUTUwgPSAn" +
    "PGRpdiBjbGFzcz0iZW1wdHkiPkNvdWxkIG5vdCBzdGFydCBzZXNzaW9uOiAnICsgZS5tZXNzYWdl" +
    "ICsgJzwvZGl2Pic7CiAgfSk7Cn0KCmZ1bmN0aW9uIHNlbmREZXZNZXNzYWdlKCkgewogIHZhciBp" +
    "bnB1dCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtaW5wdXQnKTsKICB2YXIgbXNnID0g" +
    "aW5wdXQudmFsdWUudHJpbSgpOwogIGlmICghbXNnIHx8ICFkZXZGb3JtYXQpIHJldHVybjsKICBp" +
    "bnB1dC52YWx1ZSA9ICcnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtc2VuZCcpLmRp" +
    "c2FibGVkID0gdHJ1ZTsKCiAgZGV2TWVzc2FnZXMucHVzaCh7IHJvbGU6ICd1c2VyJywgY29udGVu" +
    "dDogbXNnIH0pOwogIHJlbmRlckRldkNoYXQoKTsKCiAgZmV0Y2goJy9kZXZlbG9wJywgewogICAg" +
    "bWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAnYXBwbGljYXRp" +
    "b24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsKICAgICAgZm9ybWF0X2lkZWE6" +
    "IGRldkZvcm1hdCwKICAgICAgdHJlbmRzOiBzYXZlZCwKICAgICAgbWVzc2FnZXM6IGRldk1lc3Nh" +
    "Z2VzCiAgICB9KQogIH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0p" +
    "CiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAgaWYgKGQuZXJyb3IpIHRocm93IG5ldyBFcnJvcihk" +
    "LmVycm9yKTsKICAgIGRldk1lc3NhZ2VzLnB1c2goeyByb2xlOiAnYXNzaXN0YW50JywgY29udGVu" +
    "dDogZC5yZXNwb25zZSB9KTsKICAgIHJlbmRlckRldkNoYXQoKTsKICAgIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdkZXYtc2VuZCcpLmRpc2FibGVkID0gZmFsc2U7CiAgICBkb2N1bWVudC5nZXRF" +
    "bGVtZW50QnlJZCgnZGV2LWlucHV0JykuZm9jdXMoKTsKICB9KQogIC5jYXRjaChmdW5jdGlvbihl" +
    "KSB7CiAgICBkZXZNZXNzYWdlcy5wdXNoKHsgcm9sZTogJ2Fzc2lzdGFudCcsIGNvbnRlbnQ6ICdT" +
    "b3JyeSwgc29tZXRoaW5nIHdlbnQgd3Jvbmc6ICcgKyBlLm1lc3NhZ2UgfSk7CiAgICByZW5kZXJE" +
    "ZXZDaGF0KCk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXNlbmQnKS5kaXNhYmxl" +
    "ZCA9IGZhbHNlOwogIH0pOwp9CgpmdW5jdGlvbiByZW5kZXJEZXZDaGF0KCkgewogIHZhciBjaGF0" +
    "ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1jaGF0Jyk7CiAgdmFyIGh0bWwgPSAnJzsK" +
    "ICBmb3IgKHZhciBpID0gMDsgaSA8IGRldk1lc3NhZ2VzLmxlbmd0aDsgaSsrKSB7CiAgICB2YXIg" +
    "bSA9IGRldk1lc3NhZ2VzW2ldOwogICAgdmFyIGNscyA9IG0ucm9sZSA9PT0gJ2Fzc2lzdGFudCcg" +
    "PyAnYWknIDogJ3VzZXInOwogICAgdmFyIHRleHQgPSBtLmNvbnRlbnQucmVwbGFjZSgvXG4vZywg" +
    "Jzxicj4nKTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImRldi1tc2cgJyArIGNscyArICciPicg" +
    "KyB0ZXh0ICsgJzwvZGl2Pic7CiAgfQogIGNoYXQuaW5uZXJIVE1MID0gaHRtbDsKICBjaGF0LnNj" +
    "cm9sbFRvcCA9IGNoYXQuc2Nyb2xsSGVpZ2h0Owp9CgpmdW5jdGlvbiBsb2FkUmVzZWFyY2goKSB7" +
    "CiAgZmV0Y2goJy9yZXNlYXJjaCcpLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7" +
    "IH0pLnRoZW4oZnVuY3Rpb24oZCkgeyByZW5kZXJSZXNlYXJjaChkLml0ZW1zIHx8IFtdKTsgfSkK" +
    "ICAuY2F0Y2goZnVuY3Rpb24oKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZXNlYXJjaC1m" +
    "ZWVkJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5Db3VsZCBub3QgbG9hZCByZXNl" +
    "YXJjaC48L2Rpdj4nOyB9KTsKfQoKZnVuY3Rpb24gcmVuZGVyUmVzZWFyY2goaXRlbXMpIHsKICB2" +
    "YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVzZWFyY2gtZmVlZCcpOwogIGlmICgh" +
    "aXRlbXMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gcmVz" +
    "ZWFyY2ggaXRlbXMgZm91bmQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIHR5cGVNYXAgPSB7IHJl" +
    "c2VhcmNoOiAnUmVzZWFyY2gnLCBjdWx0dXJlOiAnQ3VsdHVyZScsIHRyZW5kczogJ1RyZW5kcycg" +
    "fTsgdmFyIGh0bWwgPSAnJzsKICBmb3IgKHZhciBpID0gMDsgaSA8IGl0ZW1zLmxlbmd0aDsgaSsr" +
    "KSB7CiAgICB2YXIgaXRlbSA9IGl0ZW1zW2ldOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0icmVz" +
    "ZWFyY2gtaXRlbSI+PGRpdiBjbGFzcz0icmVzZWFyY2gtdGl0bGUiPjxhIGhyZWY9IicgKyBpdGVt" +
    "LnVybCArICciIHRhcmdldD0iX2JsYW5rIj4nICsgaXRlbS50aXRsZSArICc8L2E+PC9kaXY+JzsK" +
    "ICAgIGlmIChpdGVtLmRlc2MpIGh0bWwgKz0gJzxkaXYgY2xhc3M9InJlc2VhcmNoLWRlc2MiPicg" +
    "KyBpdGVtLmRlc2MgKyAnPC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InJlc2VhcmNo" +
    "LW1ldGEiPjxzcGFuIGNsYXNzPSJyLXNyYyI+JyArIGl0ZW0uc291cmNlICsgJzwvc3Bhbj48c3Bh" +
    "biBjbGFzcz0ici10eXBlIj4nICsgKHR5cGVNYXBbaXRlbS50eXBlXSB8fCBpdGVtLnR5cGUpICsg" +
    "Jzwvc3Bhbj48L2Rpdj48L2Rpdj4nOwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9CgpmdW5j" +
    "dGlvbiBkb0FyY2hpdmVTZWFyY2goKSB7CiAgdmFyIHF1ZXJ5ID0gZG9jdW1lbnQuZ2V0RWxlbWVu" +
    "dEJ5SWQoJ2FyY2hpdmUtc2VhcmNoLWlucHV0JykudmFsdWUudHJpbSgpOwogIGlmICghcXVlcnkp" +
    "IHJldHVybjsKICB2YXIgcmVzdWx0c0VsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NlYXJj" +
    "aC1yZXN1bHRzJyk7CiAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxlPSJmb250LXNp" +
    "emU6MTJweDtjb2xvcjp2YXIoLS1tdXRlZCkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5T" +
    "ZWFyY2hpbmcgYXJjaGl2ZS4uLjwvZGl2Pic7CgogIGZldGNoKCcvYXJjaGl2ZS9zZWFyY2gnLCB7" +
    "CiAgICBtZXRob2Q6ICdQT1NUJywKICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBs" +
    "aWNhdGlvbi9qc29uJyB9LAogICAgYm9keTogSlNPTi5zdHJpbmdpZnkoeyBxdWVyeTogcXVlcnkg" +
    "fSkKICB9KQogIC50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVu" +
    "KGZ1bmN0aW9uKGQpIHsKICAgIGlmIChkLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoZC5lcnJvcik7" +
    "CiAgICB2YXIgcmVzdWx0cyA9IGQucmVzdWx0cyB8fCBbXTsKICAgIGlmICghcmVzdWx0cy5sZW5n" +
    "dGgpIHsKICAgICAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6" +
    "MTJweDtjb2xvcjp2YXIoLS1tdXRlZCk7cGFkZGluZzo4cHggMCI+Tm8gcmVsZXZhbnQgdHJlbmRz" +
    "IGZvdW5kIGZvciAiJyArIHF1ZXJ5ICsgJyIuPC9kaXY+JzsKICAgICAgcmV0dXJuOwogICAgfQog" +
    "ICAgdmFyIG1jTWFwID0geyByaXNpbmc6ICdiLXJpc2luZycsIGVtZXJnaW5nOiAnYi1lbWVyZ2lu" +
    "ZycsIGVzdGFibGlzaGVkOiAnYi1lc3RhYmxpc2hlZCcsIHNoaWZ0aW5nOiAnYi1zaGlmdGluZycg" +
    "fTsKICAgIHZhciBodG1sID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMHB4O2ZvbnQtd2VpZ2h0" +
    "OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7dGV4dC10cmFuc2Zvcm06dXBwZXJjYXNlO2xldHRlci1z" +
    "cGFjaW5nOjAuOHB4O21hcmdpbi1ib3R0b206MTBweCI+JyArIHJlc3VsdHMubGVuZ3RoICsgJyBy" +
    "ZWxldmFudCB0cmVuZHMgZm91bmQ8L2Rpdj4nOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCByZXN1" +
    "bHRzLmxlbmd0aDsgaSsrKSB7CiAgICAgIHZhciB0ID0gcmVzdWx0c1tpXTsKICAgICAgdmFyIG1j" +
    "ID0gbWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1lcmdpbmcnOwogICAgICBodG1sICs9ICc8ZGl2" +
    "IHN0eWxlPSJwYWRkaW5nOjEycHggMDtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1ib3Jk" +
    "ZXIpIj4nOwogICAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7YWxpZ24taXRl" +
    "bXM6Y2VudGVyO2dhcDo4cHg7bWFyZ2luLWJvdHRvbTo1cHgiPic7CiAgICAgIGh0bWwgKz0gJzxk" +
    "aXYgc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjojZmZmIj4nICsg" +
    "dC5uYW1lICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxzcGFuIGNsYXNzPSJiYWRnZSAnICsg" +
    "bWMgKyAnIj4nICsgKHQubW9tZW50dW0gfHwgJycpICsgJzwvc3Bhbj4nOwogICAgICBodG1sICs9" +
    "ICc8c3BhbiBzdHlsZT0iZm9udC1zaXplOjEwcHg7Y29sb3I6dmFyKC0tbXV0ZWQpIj4nICsgdC5z" +
    "YXZlZF9hdC5zbGljZSgwLDEwKSArICc8L3NwYW4+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+JzsK" +
    "ICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjEycHg7Y29sb3I6dmFyKC0tbXV0" +
    "ZWQpO2xpbmUtaGVpZ2h0OjEuNTttYXJnaW4tYm90dG9tOjVweCI+JyArICh0LmRlc2MgfHwgJycp" +
    "ICsgJzwvZGl2Pic7CiAgICAgIGlmICh0LnJlbGV2YW5jZSkgaHRtbCArPSAnPGRpdiBzdHlsZT0i" +
    "Zm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tYWNjZW50Mik7Zm9udC1zdHlsZTppdGFsaWMiPicg" +
    "KyB0LnJlbGV2YW5jZSArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8L2Rpdj4nOwogICAgfQog" +
    "ICAgcmVzdWx0c0VsLmlubmVySFRNTCA9IGh0bWw7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkg" +
    "ewogICAgcmVzdWx0c0VsLmlubmVySFRNTCA9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTJweDtj" +
    "b2xvcjojZmNhNWE1Ij5TZWFyY2ggZmFpbGVkOiAnICsgZS5tZXNzYWdlICsgJzwvZGl2Pic7CiAg" +
    "fSk7Cn0KCmZ1bmN0aW9uIGxvYWRBcmNoaXZlKCkgewogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlk" +
    "KCdkYXRlLWxpc3QnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiIHN0eWxlPSJwYWRk" +
    "aW5nOjFyZW0gMCI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPjwvZGl2Pic7CiAgZmV0Y2go" +
    "Jy9hcmNoaXZlL2RhdGVzJykudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkK" +
    "ICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoIWQuZGF0ZXMgfHwgIWQuZGF0ZXMubGVuZ3Ro" +
    "KSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkYXRlLWxpc3QnKS5pbm5lckhUTUwgPSAnPGRp" +
    "diBjbGFzcz0iZW1wdHkiIHN0eWxlPSJwYWRkaW5nOjFyZW0gMDtmb250LXNpemU6MTFweCI+Tm8g" +
    "YXJjaGl2ZWQgdHJlbmRzIHlldC48L2Rpdj4nOyByZXR1cm47IH0KICAgIHZhciBodG1sID0gJyc7" +
    "CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IGQuZGF0ZXMubGVuZ3RoOyBpKyspIHsgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0iZGF0ZS1pdGVtIiBvbmNsaWNrPSJsb2FkRGF0ZShcJycgKyBkLmRhdGVzW2ld" +
    "LmRhdGUgKyAnXCcsdGhpcykiPicgKyBkLmRhdGVzW2ldLmRhdGUgKyAnPHNwYW4gY2xhc3M9ImRh" +
    "dGUtY291bnQiPicgKyBkLmRhdGVzW2ldLmNvdW50ICsgJzwvc3Bhbj48L2Rpdj4nOyB9CiAgICBk" +
    "b2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0JykuaW5uZXJIVE1MID0gaHRtbDsKICAg" +
    "IHZhciBmaXJzdCA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoJy5kYXRlLWl0ZW0nKTsgaWYgKGZp" +
    "cnN0KSBmaXJzdC5jbGljaygpOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsgZG9jdW1lbnQu" +
    "Z2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtZXJyJykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVy" +
    "cmJveCI+Q291bGQgbm90IGxvYWQgYXJjaGl2ZTogJyArIGUubWVzc2FnZSArICc8L2Rpdj4nOyB9" +
    "KTsKfQoKZnVuY3Rpb24gbG9hZERhdGUoZGF0ZSwgZWwpIHsKICB2YXIgaXRlbXMgPSBkb2N1bWVu" +
    "dC5xdWVyeVNlbGVjdG9yQWxsKCcuZGF0ZS1pdGVtJyk7IGZvciAodmFyIGkgPSAwOyBpIDwgaXRl" +
    "bXMubGVuZ3RoOyBpKyspIGl0ZW1zW2ldLmNsYXNzTGlzdC5yZW1vdmUoJ2FjdGl2ZScpOwogIGVs" +
    "LmNsYXNzTGlzdC5hZGQoJ2FjdGl2ZScpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdhcmNo" +
    "aXZlLWhlYWRpbmcnKS50ZXh0Q29udGVudCA9ICdTYXZlZCBvbiAnICsgZGF0ZTsKICBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYgY2xh" +
    "c3M9ImVtcHR5Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+PC9kaXY+JzsKICBmZXRjaCgn" +
    "L2FyY2hpdmUvYnktZGF0ZT9kYXRlPScgKyBlbmNvZGVVUklDb21wb25lbnQoZGF0ZSkpLnRoZW4o" +
    "ZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewog" +
    "ICAgaWYgKCFkLnRyZW5kcyB8fCAhZC50cmVuZHMubGVuZ3RoKSB7IGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHki" +
    "Pk5vIHRyZW5kcyBmb3IgdGhpcyBkYXRlLjwvZGl2Pic7IHJldHVybjsgfQogICAgdmFyIGh0bWwg" +
    "PSAnJzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgZC50cmVuZHMubGVuZ3RoOyBpKyspIHsKICAg" +
    "ICAgdmFyIHQgPSBkLnRyZW5kc1tpXTsKICAgICAgdmFyIG1jTWFwID0geyByaXNpbmc6ICdiLXJp" +
    "c2luZycsIGVtZXJnaW5nOiAnYi1lbWVyZ2luZycsIGVzdGFibGlzaGVkOiAnYi1lc3RhYmxpc2hl" +
    "ZCcsIHNoaWZ0aW5nOiAnYi1zaGlmdGluZycgfTsKICAgICAgdmFyIG1jID0gbWNNYXBbdC5tb21l" +
    "bnR1bV0gfHwgJ2ItZW1lcmdpbmcnOyB2YXIgbGlua3MgPSBbXTsKICAgICAgdHJ5IHsgbGlua3Mg" +
    "PSBKU09OLnBhcnNlKHQuc291cmNlX2xpbmtzIHx8ICdbXScpOyB9IGNhdGNoKGUpIHt9CiAgICAg" +
    "IGh0bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gtaXRlbSI+PGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4" +
    "O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6OHB4O21hcmdpbi1ib3R0b206M3B4Ij48ZGl2IGNsYXNz" +
    "PSJhcmNoLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+PHNwYW4gY2xhc3M9ImJhZGdlICcgKyBt" +
    "YyArICciPicgKyAodC5tb21lbnR1bSB8fCAnJykgKyAnPC9zcGFuPjwvZGl2Pic7CiAgICAgIGh0" +
    "bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gtbWV0YSI+JyArIHQuc2F2ZWRfYXQgKyAodC5yZWdpb24g" +
    "PyAnICZtaWRkb3Q7ICcgKyB0LnJlZ2lvbi50b1VwcGVyQ2FzZSgpIDogJycpICsgKHQudGFnID8g" +
    "JyAmbWlkZG90OyAnICsgdC50YWcgOiAnJykgKyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPGRp" +
    "diBjbGFzcz0iYXJjaC1kZXNjIj4nICsgKHQuZGVzYyB8fCAnJykgKyAnPC9kaXY+JzsKICAgICAg" +
    "Zm9yICh2YXIgbCA9IDA7IGwgPCBsaW5rcy5sZW5ndGg7IGwrKykgeyBodG1sICs9ICc8YSBjbGFz" +
    "cz0iYXJjaC1saW5rIiBocmVmPSInICsgbGlua3NbbF0udXJsICsgJyIgdGFyZ2V0PSJfYmxhbmsi" +
    "PicgKyBsaW5rc1tsXS50aXRsZSArICc8L2E+JzsgfQogICAgICBodG1sICs9ICc8L2Rpdj4nOwog" +
    "ICAgfQogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtY29udGVudCcpLmlubmVy" +
    "SFRNTCA9IGh0bWw7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oKSB7IGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHki" +
    "PkNvdWxkIG5vdCBsb2FkLjwvZGl2Pic7IH0pOwp9Cjwvc2NyaXB0Pgo8L2JvZHk+CjwvaHRtbD4K"
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
