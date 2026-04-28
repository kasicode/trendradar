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
    "cGlsbCBvbiI+UGFyb29sPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5Ucm91" +
    "dzwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+TGliZWxsZTwvc3Bhbj4KICAg" +
    "IDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+TGluZGEubmw8L3NwYW4+CiAgICA8c3BhbiBjbGFz" +
    "cz0ic3JjLXBpbGwgb24iPlJUTDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+" +
    "Tk9TPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5Hb29nbGUgTmV3cyBOTDwv" +
    "c3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+R29vZ2xlIFRyZW5kczwvc3Bhbj4K" +
    "ICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+TllUIEJvb2tzPC9zcGFuPgogICAgPHNwYW4g" +
    "Y2xhc3M9InNyYy1waWxsIG9uIj5TQ1A8L3NwYW4+CiAgICA8c3BhbiBjbGFzcz0ic3JjLXBpbGwg" +
    "b24iPkNCUzwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMtcGlsbCBvbiI+UGV3IFJlc2VhcmNo" +
    "PC9zcGFuPgogIDwvZGl2Pgo8L2Rpdj4KCjxkaXYgY2xhc3M9Im1haW4iPgogIDxkaXYgY2xhc3M9" +
    "InRvcGJhciI+CiAgICA8ZGl2IGNsYXNzPSJ0b3BiYXItdGl0bGUiIGlkPSJwYWdlLXRpdGxlIj5E" +
    "YXNoYm9hcmQ8L2Rpdj4KICAgIDxkaXYgY2xhc3M9InRvcGJhci1yaWdodCIgaWQ9InNjYW4tY29u" +
    "dHJvbHMiPgogICAgICA8c2VsZWN0IGNsYXNzPSJzZWwiIGlkPSJyZWdpb24tc2VsIj4KICAgICAg" +
    "ICA8b3B0aW9uIHZhbHVlPSJubCI+TkwgZm9jdXM8L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZh" +
    "bHVlPSJldSI+RVUgLyBnbG9iYWw8L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJhbGwi" +
    "PkFsbCBtYXJrZXRzPC9vcHRpb24+CiAgICAgIDwvc2VsZWN0PgogICAgICA8c2VsZWN0IGNsYXNz" +
    "PSJzZWwiIGlkPSJob3Jpem9uLXNlbCI+CiAgICAgICAgPG9wdGlvbiB2YWx1ZT0iZW1lcmdpbmci" +
    "PkVtZXJnaW5nPC9vcHRpb24+CiAgICAgICAgPG9wdGlvbiB2YWx1ZT0icmlzaW5nIj5SaXNpbmc8" +
    "L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJhbGwiPkFsbCBzaWduYWxzPC9vcHRpb24+" +
    "CiAgICAgIDwvc2VsZWN0PgogICAgICA8YnV0dG9uIGNsYXNzPSJzY2FuLWJ0biIgaWQ9InNjYW4t" +
    "YnRuIiBvbmNsaWNrPSJydW5TY2FuKCkiPlNjYW4gbm93PC9idXR0b24+CiAgICA8L2Rpdj4KICA8" +
    "L2Rpdj4KCiAgPGRpdiBjbGFzcz0iY29udGVudCI+CiAgICA8ZGl2IGlkPSJ2aWV3LWRhc2hib2Fy" +
    "ZCI+CiAgICAgIDxkaXYgY2xhc3M9InN0YXR1cy1iYXIiPgogICAgICAgIDxkaXYgY2xhc3M9InN0" +
    "YXR1cy1kb3QiIGlkPSJzdGF0dXMtZG90Ij48L2Rpdj4KICAgICAgICA8c3BhbiBpZD0ic3RhdHVz" +
    "LXRleHQiPlJlYWR5IHRvIHNjYW48L3NwYW4+CiAgICAgICAgPHNwYW4gaWQ9ImhlYWRsaW5lLWNv" +
    "dW50IiBzdHlsZT0iY29sb3I6cmdiYSgyNTUsMjU1LDI1NSwwLjIpIj48L3NwYW4+CiAgICAgIDwv" +
    "ZGl2PgogICAgICA8ZGl2IGNsYXNzPSJwcm9ncmVzcy1iYXIiPjxkaXYgY2xhc3M9InByb2dyZXNz" +
    "LWZpbGwiIGlkPSJwcm9ncmVzcy1maWxsIj48L2Rpdj48L2Rpdj4KICAgICAgPGRpdiBpZD0iZXJy" +
    "LWJveCI+PC9kaXY+CgogICAgICA8ZGl2IGNsYXNzPSJncmlkLTMiPgogICAgICAgIDxkaXY+CiAg" +
    "ICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkIj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1o" +
    "ZWFkZXIiIHN0eWxlPSJwYWRkaW5nLWJvdHRvbTowIj4KICAgICAgICAgICAgICA8ZGl2IGNsYXNz" +
    "PSJ0YWJzIj4KICAgICAgICAgICAgICAgIDxidXR0b24gY2xhc3M9InRhYi1idG4gYWN0aXZlIiBp" +
    "ZD0idGFiLXQiIG9uY2xpY2s9InN3aXRjaFRhYigndHJlbmRzJykiPkN1bHR1cmFsIHRyZW5kczwv" +
    "YnV0dG9uPgogICAgICAgICAgICAgICAgPGJ1dHRvbiBjbGFzcz0idGFiLWJ0biIgaWQ9InRhYi1m" +
    "IiBvbmNsaWNrPSJzd2l0Y2hUYWIoJ2Zvcm1hdHMnKSI+Rm9ybWF0IGlkZWFzPC9idXR0b24+CiAg" +
    "ICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8ZGl2IGNs" +
    "YXNzPSJjYXJkLWJvZHkiPgogICAgICAgICAgICAgIDxkaXYgaWQ9InBhbmUtdHJlbmRzIj48ZGl2" +
    "IGlkPSJ0cmVuZHMtbGlzdCI+PGRpdiBjbGFzcz0iZW1wdHkiPlByZXNzICJTY2FuIG5vdyIgdG8g" +
    "ZGV0ZWN0IHRyZW5kcy48L2Rpdj48L2Rpdj48L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlkPSJw" +
    "YW5lLWZvcm1hdHMiIHN0eWxlPSJkaXNwbGF5Om5vbmUiPgogICAgICAgICAgICAgICAgPGRpdiBp" +
    "ZD0iZm9ybWF0cy1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0eSI+U2F2ZSB0cmVuZHMsIHRoZW4gZ2Vu" +
    "ZXJhdGUgZm9ybWF0IGlkZWFzLjwvZGl2PjwvZGl2PgogICAgICAgICAgICAgIDwvZGl2PgogICAg" +
    "ICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgIDwvZGl2PgoKICAgICAgICA8" +
    "ZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZCI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9" +
    "ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxlIj5TbG93IHRyZW5kcyAmbWRhc2g7" +
    "IHJlc2VhcmNoICZhbXA7IHJlcG9ydHM8L2Rpdj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFz" +
    "cz0iY2FyZC1ib2R5Ij48ZGl2IGlkPSJyZXNlYXJjaC1mZWVkIj48ZGl2IGNsYXNzPSJlbXB0eSI+" +
    "UmVzZWFyY2ggbG9hZHMgd2hlbiB5b3Ugc2Nhbi48L2Rpdj48L2Rpdj48L2Rpdj4KICAgICAgICAg" +
    "IDwvZGl2PgogICAgICAgIDwvZGl2PgoKICAgICAgICA8ZGl2PgogICAgICAgICAgPGRpdiBjbGFz" +
    "cz0iY2FyZCI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNz" +
    "PSJjYXJkLXRpdGxlIj5MaXZlIGhlYWRsaW5lczwvZGl2PjwvZGl2PgogICAgICAgICAgICA8ZGl2" +
    "IGNsYXNzPSJjYXJkLWJvZHkiPjxkaXYgaWQ9InNpZ25hbC1mZWVkIj48ZGl2IGNsYXNzPSJlbXB0" +
    "eSI+SGVhZGxpbmVzIGFwcGVhciBhZnRlciBzY2FubmluZy48L2Rpdj48L2Rpdj48L2Rpdj4KICAg" +
    "ICAgICAgIDwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZCBzZWN0aW9uLWdhcCI+CiAg" +
    "ICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxl" +
    "Ij5TYXZlZCB0cmVuZHM8L2Rpdj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1i" +
    "b2R5Ij4KICAgICAgICAgICAgICA8ZGl2IGlkPSJzYXZlZC1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0" +
    "eSI+Tm8gc2F2ZWQgdHJlbmRzIHlldC48L2Rpdj48L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlk" +
    "PSJnZW4tcm93IiBzdHlsZT0iZGlzcGxheTpub25lIj48YnV0dG9uIGNsYXNzPSJnZW4tYnRuIiBv" +
    "bmNsaWNrPSJnZW5lcmF0ZUZvcm1hdHMoKSI+R2VuZXJhdGUgZm9ybWF0IGlkZWFzICZyYXJyOzwv" +
    "YnV0dG9uPjwvZGl2PgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAg" +
    "IDwvZGl2PgogICAgICA8L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9ImRldi1wYW5lbCIgaWQ9ImRl" +
    "di1wYW5lbCIgc3R5bGU9Im1hcmdpbi10b3A6MTZweCI+CiAgICAgICAgPGRpdiBjbGFzcz0iZGV2" +
    "LXBhbmVsLWhlYWRlciIgc3R5bGU9ImRpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7anVz" +
    "dGlmeS1jb250ZW50OnNwYWNlLWJldHdlZW4iPgogICAgICAgICAgPGRpdj4KICAgICAgICAgICAg" +
    "PGRpdiBjbGFzcz0iZGV2LXBhbmVsLXRpdGxlIj4mIzk2Nzk7IEZvcm1hdCBEZXZlbG9wbWVudCBT" +
    "ZXNzaW9uPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImRldi1wYW5lbC1zdWJ0aXRsZSIg" +
    "aWQ9ImRldi1wYW5lbC1zdWJ0aXRsZSI+RGV2ZWxvcGluZzogJm1kYXNoOzwvZGl2PgogICAgICAg" +
    "ICAgPC9kaXY+CiAgICAgICAgICA8YnV0dG9uIG9uY2xpY2s9ImRvY3VtZW50LmdldEVsZW1lbnRC" +
    "eUlkKCdkZXYtcGFuZWwnKS5zdHlsZS5kaXNwbGF5PSdub25lJyIgc3R5bGU9ImJhY2tncm91bmQ6" +
    "bm9uZTtib3JkZXI6bm9uZTtjb2xvcjp2YXIoLS1tdXRlZCk7Y3Vyc29yOnBvaW50ZXI7Zm9udC1z" +
    "aXplOjE4cHg7cGFkZGluZzo0cHggOHB4Ij4mdGltZXM7PC9idXR0b24+CiAgICAgICAgPC9kaXY+" +
    "CiAgICAgICAgPGRpdiBjbGFzcz0iZGV2LWNoYXQiIGlkPSJkZXYtY2hhdCI+PC9kaXY+CiAgICAg" +
    "ICAgPGRpdiBjbGFzcz0iZGV2LWlucHV0LXJvdyI+CiAgICAgICAgICA8aW5wdXQgY2xhc3M9ImRl" +
    "di1pbnB1dCIgaWQ9ImRldi1pbnB1dCIgdHlwZT0idGV4dCIgcGxhY2Vob2xkZXI9IlJlcGx5IHRv" +
    "IHlvdXIgZGV2ZWxvcG1lbnQgZXhlYy4uLiIgb25rZXlkb3duPSJpZihldmVudC5rZXk9PT0nRW50" +
    "ZXInKXNlbmREZXZNZXNzYWdlKCkiIC8+CiAgICAgICAgICA8YnV0dG9uIGNsYXNzPSJkZXYtc2Vu" +
    "ZCIgaWQ9ImRldi1zZW5kIiBvbmNsaWNrPSJzZW5kRGV2TWVzc2FnZSgpIj5TZW5kPC9idXR0b24+" +
    "CiAgICAgICAgPC9kaXY+CiAgICAgIDwvZGl2PgogICAgPC9kaXY+CgogICAgPGRpdiBpZD0idmll" +
    "dy1hcmNoaXZlIiBzdHlsZT0iZGlzcGxheTpub25lIj4KICAgICAgPGRpdiBpZD0iYXJjaGl2ZS1l" +
    "cnIiPjwvZGl2PgoKICAgICAgPCEtLSBTZW1hbnRpYyBzZWFyY2ggYmFyIC0tPgogICAgICA8ZGl2" +
    "IGNsYXNzPSJjYXJkIiBzdHlsZT0ibWFyZ2luLWJvdHRvbToxNnB4Ij4KICAgICAgICA8ZGl2IGNs" +
    "YXNzPSJjYXJkLWhlYWRlciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+U2VhcmNoIGFyY2hpdmUg" +
    "YnkgY29uY2VwdCBvciBmb3JtYXQgaWRlYTwvZGl2PjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9" +
    "ImNhcmQtYm9keSIgc3R5bGU9InBhZGRpbmc6MTRweCAxNnB4Ij4KICAgICAgICAgIDxkaXYgc3R5" +
    "bGU9ImRpc3BsYXk6ZmxleDtnYXA6MTBweDthbGlnbi1pdGVtczpjZW50ZXIiPgogICAgICAgICAg" +
    "ICA8aW5wdXQgaWQ9ImFyY2hpdmUtc2VhcmNoLWlucHV0IiB0eXBlPSJ0ZXh0IgogICAgICAgICAg" +
    "ICAgIHBsYWNlaG9sZGVyPSJlLmcuICdlZW56YWFtaGVpZCBvbmRlciBqb25nZXJlbicgb3IgJ2Zh" +
    "bWlsaWVzIHVuZGVyIHByZXNzdXJlJy4uLiIKICAgICAgICAgICAgICBzdHlsZT0iZmxleDoxO2Zv" +
    "bnQtc2l6ZToxM3B4O3BhZGRpbmc6OXB4IDE0cHg7Ym9yZGVyLXJhZGl1czo4cHg7Ym9yZGVyOjFw" +
    "eCBzb2xpZCB2YXIoLS1ib3JkZXIyKTtiYWNrZ3JvdW5kOnJnYmEoMjU1LDI1NSwyNTUsMC4wNCk7" +
    "Y29sb3I6dmFyKC0tdGV4dCk7b3V0bGluZTpub25lIgogICAgICAgICAgICAgIG9ua2V5ZG93bj0i" +
    "aWYoZXZlbnQua2V5PT09J0VudGVyJylkb0FyY2hpdmVTZWFyY2goKSIKICAgICAgICAgICAgLz4K" +
    "ICAgICAgICAgICAgPGJ1dHRvbiBvbmNsaWNrPSJkb0FyY2hpdmVTZWFyY2goKSIgc3R5bGU9ImZv" +
    "bnQtc2l6ZToxMnB4O2ZvbnQtd2VpZ2h0OjYwMDtwYWRkaW5nOjlweCAxOHB4O2JvcmRlci1yYWRp" +
    "dXM6OHB4O2JvcmRlcjpub25lO2JhY2tncm91bmQ6bGluZWFyLWdyYWRpZW50KDEzNWRlZyx2YXIo" +
    "LS1hY2NlbnQpLHZhcigtLWFjY2VudDIpKTtjb2xvcjojZmZmO2N1cnNvcjpwb2ludGVyO3doaXRl" +
    "LXNwYWNlOm5vd3JhcCI+U2VhcmNoPC9idXR0b24+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICAg" +
    "IDxkaXYgaWQ9InNlYXJjaC1yZXN1bHRzIiBzdHlsZT0ibWFyZ2luLXRvcDoxMnB4Ij48L2Rpdj4K" +
    "ICAgICAgICA8L2Rpdj4KICAgICAgPC9kaXY+CgogICAgICA8IS0tIEJyb3dzZSBieSBkYXRlIC0t" +
    "PgogICAgICA8ZGl2IGNsYXNzPSJjYXJkIj4KICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWhlYWRl" +
    "ciI+PGRpdiBjbGFzcz0iY2FyZC10aXRsZSI+U2F2ZWQgdHJlbmRzIGFyY2hpdmU8L2Rpdj48L2Rp" +
    "dj4KICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkLWJvZHkiIHN0eWxlPSJwYWRkaW5nOjE2cHgiPgog" +
    "ICAgICAgICAgPGRpdiBjbGFzcz0iYXJjaGl2ZS1sYXlvdXQiPgogICAgICAgICAgICA8ZGl2Pgog" +
    "ICAgICAgICAgICAgIDxkaXYgc3R5bGU9ImZvbnQtc2l6ZTo5cHg7Zm9udC13ZWlnaHQ6NjAwO2Nv" +
    "bG9yOnZhcigtLW11dGVkKTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2U7bGV0dGVyLXNwYWNpbmc6" +
    "MC44cHg7bWFyZ2luLWJvdHRvbToxMHB4Ij5CeSBkYXRlPC9kaXY+CiAgICAgICAgICAgICAgPGRp" +
    "diBpZD0iZGF0ZS1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0eSIgc3R5bGU9InBhZGRpbmc6MXJlbSAw" +
    "Ij5Mb2FkaW5nLi4uPC9kaXY+PC9kaXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8" +
    "ZGl2PgogICAgICAgICAgICAgIDxkaXYgc3R5bGU9ImZvbnQtc2l6ZTo5cHg7Zm9udC13ZWlnaHQ6" +
    "NjAwO2NvbG9yOnZhcigtLW11dGVkKTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2U7bGV0dGVyLXNw" +
    "YWNpbmc6MC44cHg7bWFyZ2luLWJvdHRvbToxMHB4IiBpZD0iYXJjaGl2ZS1oZWFkaW5nIj5TZWxl" +
    "Y3QgYSBkYXRlPC9kaXY+CiAgICAgICAgICAgICAgPGRpdiBpZD0iYXJjaGl2ZS1jb250ZW50Ij48" +
    "ZGl2IGNsYXNzPSJlbXB0eSI+U2VsZWN0IGEgZGF0ZS48L2Rpdj48L2Rpdj4KICAgICAgICAgICAg" +
    "PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgICAgPC9kaXY+CiAgICA8" +
    "L2Rpdj4KICA8L2Rpdj4KPC9kaXY+Cgo8c2NyaXB0Pgp2YXIgc2F2ZWQgPSBbXTsKdmFyIHRyZW5k" +
    "cyA9IFtdOwoKZnVuY3Rpb24gc3dpdGNoVmlldyh2KSB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5" +
    "SWQoJ3ZpZXctZGFzaGJvYXJkJykuc3R5bGUuZGlzcGxheSA9IHYgPT09ICdkYXNoYm9hcmQnID8g" +
    "JycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3ZpZXctYXJjaGl2ZScpLnN0" +
    "eWxlLmRpc3BsYXkgPSB2ID09PSAnYXJjaGl2ZScgPyAnJyA6ICdub25lJzsKICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnc2Nhbi1jb250cm9scycpLnN0eWxlLmRpc3BsYXkgPSB2ID09PSAnZGFz" +
    "aGJvYXJkJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCduYXYtZCcp" +
    "LmNsYXNzTmFtZSA9ICduYXYtaXRlbScgKyAodiA9PT0gJ2Rhc2hib2FyZCcgPyAnIGFjdGl2ZScg" +
    "OiAnJyk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ25hdi1hJykuY2xhc3NOYW1lID0gJ25h" +
    "di1pdGVtJyArICh2ID09PSAnYXJjaGl2ZScgPyAnIGFjdGl2ZScgOiAnJyk7CiAgZG9jdW1lbnQu" +
    "Z2V0RWxlbWVudEJ5SWQoJ3BhZ2UtdGl0bGUnKS50ZXh0Q29udGVudCA9IHYgPT09ICdkYXNoYm9h" +
    "cmQnID8gJ0Rhc2hib2FyZCcgOiAnQXJjaGl2ZSc7CiAgaWYgKHYgPT09ICdhcmNoaXZlJykgbG9h" +
    "ZEFyY2hpdmUoKTsKfQoKZnVuY3Rpb24gc3dpdGNoVGFiKHQpIHsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgncGFuZS10cmVuZHMnKS5zdHlsZS5kaXNwbGF5ID0gdCA9PT0gJ3RyZW5kcycgPyAn" +
    "JyA6ICdub25lJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncGFuZS1mb3JtYXRzJykuc3R5" +
    "bGUuZGlzcGxheSA9IHQgPT09ICdmb3JtYXRzJyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCd0YWItdCcpLmNsYXNzTmFtZSA9ICd0YWItYnRuJyArICh0ID09PSAndHJl" +
    "bmRzJyA/ICcgYWN0aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndGFiLWYn" +
    "KS5jbGFzc05hbWUgPSAndGFiLWJ0bicgKyAodCA9PT0gJ2Zvcm1hdHMnID8gJyBhY3RpdmUnIDog" +
    "JycpOwp9CgpmdW5jdGlvbiBzaG93RXJyKG1zZykgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgn" +
    "ZXJyLWJveCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlcnJib3giPjxzdHJvbmc+RXJyb3I6" +
    "PC9zdHJvbmc+ICcgKyBtc2cgKyAnPC9kaXY+JzsgfQpmdW5jdGlvbiBjbGVhckVycigpIHsgZG9j" +
    "dW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Vyci1ib3gnKS5pbm5lckhUTUwgPSAnJzsgfQpmdW5jdGlv" +
    "biBzZXRQcm9ncmVzcyhwKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwcm9ncmVzcy1maWxs" +
    "Jykuc3R5bGUud2lkdGggPSBwICsgJyUnOyB9CmZ1bmN0aW9uIHNldFNjYW5uaW5nKG9uKSB7IGRv" +
    "Y3VtZW50LmdldEVsZW1lbnRCeUlkKCdzdGF0dXMtZG90JykuY2xhc3NOYW1lID0gJ3N0YXR1cy1k" +
    "b3QnICsgKG9uID8gJyBzY2FubmluZycgOiAnJyk7IH0KCmZ1bmN0aW9uIHJ1blNjYW4oKSB7CiAg" +
    "Y2xlYXJFcnIoKTsKICB2YXIgYnRuID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NjYW4tYnRu" +
    "Jyk7CiAgYnRuLmRpc2FibGVkID0gdHJ1ZTsgYnRuLnRleHRDb250ZW50ID0gJ1NjYW5uaW5nLi4u" +
    "JzsKICBzZXRQcm9ncmVzcygxMCk7IHNldFNjYW5uaW5nKHRydWUpOwogIGRvY3VtZW50LmdldEVs" +
    "ZW1lbnRCeUlkKCdzdGF0dXMtdGV4dCcpLmlubmVySFRNTCA9ICc8c3BhbiBjbGFzcz0ibG9hZGVy" +
    "Ij48L3NwYW4+RmV0Y2hpbmcgbGl2ZSBoZWFkbGluZXMuLi4nOwogIGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdoZWFkbGluZS1jb3VudCcpLnRleHRDb250ZW50ID0gJyc7CiAgZG9jdW1lbnQuZ2V0" +
    "RWxlbWVudEJ5SWQoJ3RyZW5kcy1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5" +
    "Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+RmV0Y2hpbmcgbWVlc3QgZ2VsZXplbi4uLjwv" +
    "ZGl2Pic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NpZ25hbC1mZWVkJykuaW5uZXJIVE1M" +
    "ID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+TG9hZGlu" +
    "Zy4uLjwvZGl2Pic7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Jlc2VhcmNoLWZlZWQnKS5p" +
    "bm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bh" +
    "bj5Mb2FkaW5nIHJlc2VhcmNoLi4uPC9kaXY+JzsKCiAgdmFyIHJlZ2lvbiA9IGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdyZWdpb24tc2VsJykudmFsdWU7CiAgdmFyIGhvcml6b24gPSBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgnaG9yaXpvbi1zZWwnKS52YWx1ZTsKCiAgZmV0Y2goJy9zY3JhcGUn" +
    "LCB7IG1ldGhvZDogJ1BPU1QnLCBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAnYXBwbGljYXRp" +
    "b24vanNvbicgfSwgYm9keTogSlNPTi5zdHJpbmdpZnkoeyByZWdpb246IHJlZ2lvbiB9KSB9KQog" +
    "IC50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0aW9u" +
    "KGQpIHsKICAgIHZhciBoZWFkbGluZXMgPSBkLml0ZW1zIHx8IFtdOwogICAgc2V0UHJvZ3Jlc3Mo" +
    "NDApOwogICAgaWYgKGQuZXJyb3IpIHsKICAgICAgc2hvd0luZm8oJ1NjcmFwZXIgbm90ZTogJyAr" +
    "IGQuZXJyb3IgKyAnIOKAlCBzeW50aGVzaXppbmcgdHJlbmRzIGZyb20gQUkga25vd2xlZGdlIGlu" +
    "c3RlYWQuJyk7CiAgICB9CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnaGVhZGxpbmUtY291" +
    "bnQnKS50ZXh0Q29udGVudCA9IGhlYWRsaW5lcy5sZW5ndGggKyAnIGhlYWRsaW5lcyc7CiAgICBy" +
    "ZW5kZXJIZWFkbGluZXMoaGVhZGxpbmVzKTsKICAgIGxvYWRSZXNlYXJjaCgpOwogICAgcmV0dXJu" +
    "IHN5bnRoZXNpemVUcmVuZHMoaGVhZGxpbmVzLCByZWdpb24sIGhvcml6b24pOwogIH0pCiAgLnRo" +
    "ZW4oZnVuY3Rpb24oKSB7IGJ0bi5kaXNhYmxlZCA9IGZhbHNlOyBidG4udGV4dENvbnRlbnQgPSAn" +
    "U2NhbiBub3cnOyBzZXRTY2FubmluZyhmYWxzZSk7IH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsK" +
    "ICAgIHNob3dFcnIoJ1NjYW4gZmFpbGVkOiAnICsgZS5tZXNzYWdlKTsKICAgIGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdzdGF0dXMtdGV4dCcpLnRleHRDb250ZW50ID0gJ1NjYW4gZmFpbGVkLic7" +
    "CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndHJlbmRzLWxpc3QnKS5pbm5lckhUTUwgPSAn" +
    "PGRpdiBjbGFzcz0iZW1wdHkiPlNlZSBlcnJvciBhYm92ZS48L2Rpdj4nOwogICAgc2V0UHJvZ3Jl" +
    "c3MoMCk7IHNldFNjYW5uaW5nKGZhbHNlKTsKICAgIGJ0bi5kaXNhYmxlZCA9IGZhbHNlOyBidG4u" +
    "dGV4dENvbnRlbnQgPSAnU2NhbiBub3cnOwogIH0pOwp9CgpmdW5jdGlvbiBzeW50aGVzaXplVHJl" +
    "bmRzKGhlYWRsaW5lcywgcmVnaW9uLCBob3Jpem9uKSB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5" +
    "SWQoJ3N0YXR1cy10ZXh0JykuaW5uZXJIVE1MID0gJzxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bh" +
    "bj5TeW50aGVzaXppbmcgdHJlbmRzLi4uJzsKICBzZXRQcm9ncmVzcyg2NSk7CiAgdmFyIGhlYWRs" +
    "aW5lVGV4dCA9IGhlYWRsaW5lcy5sZW5ndGgKICAgID8gaGVhZGxpbmVzLm1hcChmdW5jdGlvbiho" +
    "KSB7IHJldHVybiAnLSBbJyArIGguc291cmNlICsgJ10gJyArIGgudGl0bGUgKyAnICgnICsgaC51" +
    "cmwgKyAnKSc7IH0pLmpvaW4oJ1xuJykKICAgIDogJyhObyBsaXZlIGhlYWRsaW5lcyAtIHVzZSB0" +
    "cmFpbmluZyBrbm93bGVkZ2UgZm9yIER1dGNoIGN1bHR1cmFsIHRyZW5kcyknOwogIHZhciBob3Jp" +
    "em9uTWFwID0geyBlbWVyZ2luZzogJ2VtZXJnaW5nICh3ZWFrIHNpZ25hbHMpJywgcmlzaW5nOiAn" +
    "cmlzaW5nIChncm93aW5nIG1vbWVudHVtKScsIGFsbDogJ2FsbCBtb21lbnR1bSBzdGFnZXMnIH07" +
    "CiAgdmFyIHJlZ2lvbk1hcCA9IHsgbmw6ICdEdXRjaCAvIE5ldGhlcmxhbmRzJywgZXU6ICdFdXJv" +
    "cGVhbicsIGFsbDogJ2dsb2JhbCBpbmNsdWRpbmcgTkwnIH07CiAgdmFyIHByb21wdCA9IFsKICAg" +
    "ICdZb3UgYXJlIGEgY3VsdHVyYWwgdHJlbmQgYW5hbHlzdCBmb3IgYSBEdXRjaCB1bnNjcmlwdGVk" +
    "IFRWIGZvcm1hdCBkZXZlbG9wbWVudCB0ZWFtIHRoYXQgZGV2ZWxvcHMgcmVhbGl0eSBhbmQgZW50" +
    "ZXJ0YWlubWVudCBmb3JtYXRzLicsCiAgICAnJywgJ1JlYWwgaGVhZGxpbmVzIGZldGNoZWQgTk9X" +
    "IGZyb20gRHV0Y2ggbWVlc3QtZ2VsZXplbiBzZWN0aW9ucywgR29vZ2xlIFRyZW5kcyBOTCwgYW5k" +
    "IFJlZGRpdDonLCAnJywKICAgIGhlYWRsaW5lVGV4dCwgJycsCiAgICAnSWRlbnRpZnkgJyArICho" +
    "b3Jpem9uTWFwW2hvcml6b25dIHx8ICdlbWVyZ2luZycpICsgJyBodW1hbiBhbmQgY3VsdHVyYWwg" +
    "dHJlbmRzIGZvciAnICsgKHJlZ2lvbk1hcFtyZWdpb25dIHx8ICdEdXRjaCcpICsgJyBjb250ZXh0" +
    "LicsCiAgICAnJywKICAgICdJTVBPUlRBTlQg4oCUIEZvY3VzIGFyZWFzICh1c2UgdGhlc2UgYXMg" +
    "dHJlbmQgZXZpZGVuY2UpOicsCiAgICAnSHVtYW4gY29ubmVjdGlvbiwgaWRlbnRpdHksIGJlbG9u" +
    "Z2luZywgbG9uZWxpbmVzcywgcmVsYXRpb25zaGlwcywgbGlmZXN0eWxlLCB3b3JrIGN1bHR1cmUs" +
    "IGFnaW5nLCB5b3V0aCwgZmFtaWx5IGR5bmFtaWNzLCB0ZWNobm9sb2d5XCdzIGVtb3Rpb25hbCBp" +
    "bXBhY3QsIG1vbmV5IGFuZCBjbGFzcywgaGVhbHRoIGFuZCBib2R5LCBkYXRpbmcgYW5kIGxvdmUs" +
    "IGZyaWVuZHNoaXAsIGhvdXNpbmcsIGxlaXN1cmUsIGNyZWF0aXZpdHksIHNwaXJpdHVhbGl0eSwg" +
    "Zm9vZCBhbmQgY29uc3VtcHRpb24gaGFiaXRzLicsCiAgICAnJywKICAgICdJTVBPUlRBTlQg4oCU" +
    "IFN0cmljdCBleGNsdXNpb25zIChuZXZlciB1c2UgdGhlc2UgYXMgdHJlbmQgZXZpZGVuY2UsIHNr" +
    "aXAgdGhlc2UgaGVhZGxpbmVzIGVudGlyZWx5KTonLAogICAgJ0hhcmQgcG9saXRpY2FsIG5ld3Ms" +
    "IGVsZWN0aW9uIHJlc3VsdHMsIGdvdmVybm1lbnQgcG9saWN5IGRlYmF0ZXMsIHdhciwgYXJtZWQg" +
    "Y29uZmxpY3QsIHRlcnJvcmlzbSwgYXR0YWNrcywgYm9tYmluZ3MsIHNob290aW5ncywgbXVyZGVy" +
    "cywgY3JpbWUsIGRpc2FzdGVycywgYWNjaWRlbnRzLCBmbG9vZHMsIGVhcnRocXVha2VzLCBkZWF0" +
    "aCB0b2xscywgYWJ1c2UsIHNleHVhbCB2aW9sZW5jZSwgZXh0cmVtZSB2aW9sZW5jZSwgY291cnQg" +
    "Y2FzZXMsIGxlZ2FsIHByb2NlZWRpbmdzLCBzYW5jdGlvbnMsIGRpcGxvbWF0aWMgZGlzcHV0ZXMu" +
    "JywKICAgICcnLAogICAgJ0lmIGEgaGVhZGxpbmUgaXMgYWJvdXQgYW4gZXhjbHVkZWQgdG9waWMs" +
    "IGlnbm9yZSBpdCBjb21wbGV0ZWx5IOKAlCBkbyBub3QgdXNlIGl0IGFzIGV2aWRlbmNlIGV2ZW4g" +
    "aW5kaXJlY3RseS4nLAogICAgJ0lmIGEgaHVtYW4gdHJlbmQgKGUuZy4gYW54aWV0eSwgc29saWRh" +
    "cml0eSwgZGlzdHJ1c3QpIGlzIHZpc2libGUgQkVISU5EIGEgcG9saXRpY2FsIG9yIGNyaW1lIGhl" +
    "YWRsaW5lLCB5b3UgbWF5IHJlZmVyZW5jZSB0aGUgdW5kZXJseWluZyBodW1hbiBwYXR0ZXJuIOKA" +
    "lCBidXQgbmV2ZXIgdGhlIGV2ZW50IGl0c2VsZi4nLAogICAgJ0lmIHRoZXJlIGFyZSBub3QgZW5v" +
    "dWdoIG5vbi1leGNsdWRlZCBoZWFkbGluZXMgdG8gc3VwcG9ydCA1IHRyZW5kcywgZ2VuZXJhdGUg" +
    "ZmV3ZXIgdHJlbmRzIHJhdGhlciB0aGFuIHVzaW5nIGV4Y2x1ZGVkIHRvcGljcy4nLAogICAgJycs" +
    "CiAgICAnUmVmZXJlbmNlIGFjdHVhbCBub24tZXhjbHVkZWQgaGVhZGxpbmVzIGZyb20gdGhlIGxp" +
    "c3QgYXMgZXZpZGVuY2UuIFVzZSBhY3R1YWwgVVJMcyBwcm92aWRlZC4nLCAnJywKICAgICdSZXR1" +
    "cm4gT05MWSBhIEpTT04gb2JqZWN0LCBzdGFydGluZyB3aXRoIHsgYW5kIGVuZGluZyB3aXRoIH06" +
    "JywKICAgICd7InRyZW5kcyI6W3sibmFtZSI6IlRyZW5kIG5hbWUgMy01IHdvcmRzIiwibW9tZW50" +
    "dW0iOiJyaXNpbmd8ZW1lcmdpbmd8ZXN0YWJsaXNoZWR8c2hpZnRpbmciLCJkZXNjIjoiVHdvIHNl" +
    "bnRlbmNlcyBmb3IgYSBUViBmb3JtYXQgZGV2ZWxvcGVyLiIsInNpZ25hbHMiOiJUd28gc3BlY2lm" +
    "aWMgb2JzZXJ2YXRpb25zIGZyb20gdGhlIGhlYWRsaW5lcy4iLCJzb3VyY2VMYWJlbHMiOlsiTlUu" +
    "bmwiLCJSZWRkaXQiXSwic291cmNlTGlua3MiOlt7InRpdGxlIjoiRXhhY3QgaGVhZGxpbmUgdGl0" +
    "bGUiLCJ1cmwiOiJodHRwczovL2V4YWN0LXVybC1mcm9tLWxpc3QiLCJzb3VyY2UiOiJOVS5ubCIs" +
    "InR5cGUiOiJuZXdzIn1dLCJmb3JtYXRIaW50IjoiT25lLWxpbmUgdW5zY3JpcHRlZCBUViBmb3Jt" +
    "YXQgYW5nbGUuIn1dfScsCiAgICAnJywgJ0dlbmVyYXRlIHVwIHRvIDUgdHJlbmRzLiBPbmx5IHVz" +
    "ZSBVUkxzIGZyb20gbm9uLWV4Y2x1ZGVkIGhlYWRsaW5lcyBhYm92ZS4nCiAgXS5qb2luKCdcbicp" +
    "OwogIHJldHVybiBmZXRjaCgnL2NoYXQnLCB7IG1ldGhvZDogJ1BPU1QnLCBoZWFkZXJzOiB7ICdD" +
    "b250ZW50LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwgYm9keTogSlNPTi5zdHJpbmdpZnko" +
    "eyBtYXhfdG9rZW5zOiAyNTAwLCBtZXNzYWdlczogW3sgcm9sZTogJ3VzZXInLCBjb250ZW50OiBw" +
    "cm9tcHQgfV0gfSkgfSkKICAudGhlbihmdW5jdGlvbihyKSB7CiAgICBpZiAoIXIub2spIHRocm93" +
    "IG5ldyBFcnJvcignU2VydmVyIGVycm9yICcgKyByLnN0YXR1cyArICcgb24gL2NoYXQg4oCUIGNo" +
    "ZWNrIFJhaWx3YXkgbG9ncycpOwogICAgdmFyIGN0ID0gci5oZWFkZXJzLmdldCgnY29udGVudC10" +
    "eXBlJykgfHwgJyc7CiAgICBpZiAoY3QuaW5kZXhPZignanNvbicpID09PSAtMSkgdGhyb3cgbmV3" +
    "IEVycm9yKCdOb24tSlNPTiByZXNwb25zZSBmcm9tIC9jaGF0IChzdGF0dXMgJyArIHIuc3RhdHVz" +
    "ICsgJyknKTsKICAgIHJldHVybiByLmpzb24oKTsKICB9KQogIC50aGVuKGZ1bmN0aW9uKGNkKSB7" +
    "CiAgICBpZiAoY2QuZXJyb3IpIHRocm93IG5ldyBFcnJvcignQ2xhdWRlIEFQSSBlcnJvcjogJyAr" +
    "IGNkLmVycm9yKTsKICAgIHZhciBibG9ja3MgPSBjZC5jb250ZW50IHx8IFtdOyB2YXIgdGV4dCA9" +
    "ICcnOwogICAgZm9yICh2YXIgaSA9IDA7IGkgPCBibG9ja3MubGVuZ3RoOyBpKyspIHsgaWYgKGJs" +
    "b2Nrc1tpXS50eXBlID09PSAndGV4dCcpIHRleHQgKz0gYmxvY2tzW2ldLnRleHQ7IH0KICAgIHZh" +
    "ciBjbGVhbmVkID0gdGV4dC5yZXBsYWNlKC9gYGBqc29uXG4/L2csICcnKS5yZXBsYWNlKC9gYGBc" +
    "bj8vZywgJycpLnRyaW0oKTsKICAgIHZhciBtYXRjaCA9IGNsZWFuZWQubWF0Y2goL1x7W1xzXFNd" +
    "Klx9Lyk7CiAgICBpZiAoIW1hdGNoKSB0aHJvdyBuZXcgRXJyb3IoJ05vIEpTT04gaW4gcmVzcG9u" +
    "c2UnKTsKICAgIHZhciByZXN1bHQgPSBKU09OLnBhcnNlKG1hdGNoWzBdKTsKICAgIGlmICghcmVz" +
    "dWx0LnRyZW5kcyB8fCAhcmVzdWx0LnRyZW5kcy5sZW5ndGgpIHRocm93IG5ldyBFcnJvcignTm8g" +
    "dHJlbmRzIGluIHJlc3BvbnNlJyk7CiAgICB0cmVuZHMgPSByZXN1bHQudHJlbmRzOyBzZXRQcm9n" +
    "cmVzcygxMDApOyByZW5kZXJUcmVuZHMocmVnaW9uKTsKICAgIHZhciBub3cgPSBuZXcgRGF0ZSgp" +
    "LnRvTG9jYWxlVGltZVN0cmluZygnbmwtTkwnLCB7IGhvdXI6ICcyLWRpZ2l0JywgbWludXRlOiAn" +
    "Mi1kaWdpdCcgfSk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhdHVzLXRleHQnKS50" +
    "ZXh0Q29udGVudCA9ICdMYXN0IHNjYW46ICcgKyBub3cgKyAnIFx1MjAxNCAnICsgaGVhZGxpbmVz" +
    "Lmxlbmd0aCArICcgaGVhZGxpbmVzJzsKICB9KTsKfQoKZnVuY3Rpb24gc3JjQ29sb3Ioc3JjKSB7" +
    "CiAgc3JjID0gKHNyYyB8fCAnJykudG9Mb3dlckNhc2UoKTsKICBpZiAoc3JjLmluZGV4T2YoJ3Jl" +
    "ZGRpdCcpID4gLTEpIHJldHVybiAnI0UyNEI0QSc7CiAgaWYgKHNyYy5pbmRleE9mKCdnb29nbGUn" +
    "KSA+IC0xKSByZXR1cm4gJyMxMGI5ODEnOwogIGlmIChzcmMgPT09ICdsaWJlbGxlJyB8fCBzcmMg" +
    "PT09ICdsaW5kYS5ubCcpIHJldHVybiAnI2Y1OWUwYic7CiAgcmV0dXJuICcjM2I4MmY2JzsKfQoK" +
    "ZnVuY3Rpb24gcmVuZGVySGVhZGxpbmVzKGhlYWRsaW5lcykgewogIHZhciBlbCA9IGRvY3VtZW50" +
    "LmdldEVsZW1lbnRCeUlkKCdzaWduYWwtZmVlZCcpOwogIGlmICghaGVhZGxpbmVzLmxlbmd0aCkg" +
    "eyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPk5vIGhlYWRsaW5lcyBmZXRjaGVk" +
    "LjwvZGl2Pic7IHJldHVybjsgfQogIHZhciBieVNvdXJjZSA9IHt9OyB2YXIgc291cmNlT3JkZXIg" +
    "PSBbXTsKICBmb3IgKHZhciBpID0gMDsgaSA8IGhlYWRsaW5lcy5sZW5ndGg7IGkrKykgewogICAg" +
    "dmFyIHNyYyA9IGhlYWRsaW5lc1tpXS5zb3VyY2U7CiAgICBpZiAoIWJ5U291cmNlW3NyY10pIHsg" +
    "YnlTb3VyY2Vbc3JjXSA9IFtdOyBzb3VyY2VPcmRlci5wdXNoKHNyYyk7IH0KICAgIGJ5U291cmNl" +
    "W3NyY10ucHVzaChoZWFkbGluZXNbaV0pOwogIH0KICB2YXIgaHRtbCA9ICcnOwogIGZvciAodmFy" +
    "IHMgPSAwOyBzIDwgc291cmNlT3JkZXIubGVuZ3RoOyBzKyspIHsKICAgIHZhciBzcmMgPSBzb3Vy" +
    "Y2VPcmRlcltzXTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InNyYy1ncm91cCI+JyArIHNyYyAr" +
    "ICc8L2Rpdj4nOwogICAgdmFyIGl0ZW1zID0gYnlTb3VyY2Vbc3JjXS5zbGljZSgwLCAzKTsKICAg" +
    "IGZvciAodmFyIGogPSAwOyBqIDwgaXRlbXMubGVuZ3RoOyBqKyspIHsKICAgICAgdmFyIGggPSBp" +
    "dGVtc1tqXTsKICAgICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iaGVhZGxpbmUtaXRlbSI+PGRpdiBj" +
    "bGFzcz0iaC1kb3QiIHN0eWxlPSJiYWNrZ3JvdW5kOicgKyBzcmNDb2xvcihzcmMpICsgJyI+PC9k" +
    "aXY+PGRpdj48ZGl2IGNsYXNzPSJoLXRpdGxlIj4nICsgaC50aXRsZSArICc8L2Rpdj4nOwogICAg" +
    "ICBpZiAoaC51cmwpIGh0bWwgKz0gJzxhIGNsYXNzPSJoLWxpbmsiIGhyZWY9IicgKyBoLnVybCAr" +
    "ICciIHRhcmdldD0iX2JsYW5rIj5sZWVzIG1lZXI8L2E+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+" +
    "PC9kaXY+JzsKICAgIH0KICB9CiAgZWwuaW5uZXJIVE1MID0gaHRtbDsKfQoKZnVuY3Rpb24gcmVu" +
    "ZGVyVHJlbmRzKHJlZ2lvbikgewogIHZhciBlbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0" +
    "cmVuZHMtbGlzdCcpOwogIGlmICghdHJlbmRzLmxlbmd0aCkgeyBlbC5pbm5lckhUTUwgPSAnPGRp" +
    "diBjbGFzcz0iZW1wdHkiPk5vIHRyZW5kcyBkZXRlY3RlZC48L2Rpdj4nOyByZXR1cm47IH0KICB2" +
    "YXIgaHRtbCA9ICcnOwogIGZvciAodmFyIGkgPSAwOyBpIDwgdHJlbmRzLmxlbmd0aDsgaSsrKSB7" +
    "CiAgICB2YXIgdCA9IHRyZW5kc1tpXTsgdmFyIGlzU2F2ZWQgPSBmYWxzZTsKICAgIGZvciAodmFy" +
    "IHMgPSAwOyBzIDwgc2F2ZWQubGVuZ3RoOyBzKyspIHsgaWYgKHNhdmVkW3NdLm5hbWUgPT09IHQu" +
    "bmFtZSkgeyBpc1NhdmVkID0gdHJ1ZTsgYnJlYWs7IH0gfQogICAgdmFyIG1jTWFwID0geyByaXNp" +
    "bmc6ICdiLXJpc2luZycsIGVtZXJnaW5nOiAnYi1lbWVyZ2luZycsIGVzdGFibGlzaGVkOiAnYi1l" +
    "c3RhYmxpc2hlZCcsIHNoaWZ0aW5nOiAnYi1zaGlmdGluZycgfTsKICAgIHZhciBtYyA9IG1jTWFw" +
    "W3QubW9tZW50dW1dIHx8ICdiLWVtZXJnaW5nJzsKICAgIHZhciBsaW5rcyA9IHQuc291cmNlTGlu" +
    "a3MgfHwgW107IHZhciBsaW5rc0h0bWwgPSAnJzsKICAgIGZvciAodmFyIGwgPSAwOyBsIDwgbGlu" +
    "a3MubGVuZ3RoOyBsKyspIHsKICAgICAgdmFyIGxrID0gbGlua3NbbF07CiAgICAgIHZhciBjbHNN" +
    "YXAgPSB7IHJlZGRpdDogJ3NsLXJlZGRpdCcsIG5ld3M6ICdzbC1uZXdzJywgdHJlbmRzOiAnc2wt" +
    "dHJlbmRzJywgbGlmZXN0eWxlOiAnc2wtbGlmZXN0eWxlJyB9OwogICAgICB2YXIgbGJsTWFwID0g" +
    "eyByZWRkaXQ6ICdSJywgbmV3czogJ04nLCB0cmVuZHM6ICdHJywgbGlmZXN0eWxlOiAnTCcgfTsK" +
    "ICAgICAgbGlua3NIdG1sICs9ICc8YSBjbGFzcz0ic291cmNlLWxpbmsiIGhyZWY9IicgKyBsay51" +
    "cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+PHNwYW4gY2xhc3M9InNsLWljb24gJyArIChjbHNNYXBb" +
    "bGsudHlwZV0gfHwgJ3NsLW5ld3MnKSArICciPicgKyAobGJsTWFwW2xrLnR5cGVdIHx8ICdOJykg" +
    "KyAnPC9zcGFuPjxkaXY+PGRpdiBjbGFzcz0ic2wtdGl0bGUiPicgKyBsay50aXRsZSArICc8L2Rp" +
    "dj48ZGl2IGNsYXNzPSJzbC1zb3VyY2UiPicgKyBsay5zb3VyY2UgKyAnPC9kaXY+PC9kaXY+PC9h" +
    "Pic7CiAgICB9CiAgICB2YXIgY2hpcHMgPSAnJzsgdmFyIHNsID0gdC5zb3VyY2VMYWJlbHMgfHwg" +
    "W107CiAgICBmb3IgKHZhciBjID0gMDsgYyA8IHNsLmxlbmd0aDsgYysrKSBjaGlwcyArPSAnPHNw" +
    "YW4gY2xhc3M9ImNoaXAiPicgKyBzbFtjXSArICc8L3NwYW4+JzsKICAgIGh0bWwgKz0gJzxkaXYg" +
    "Y2xhc3M9InRyZW5kLWl0ZW0iIGlkPSJ0Yy0nICsgaSArICciPic7CiAgICBodG1sICs9ICc8ZGl2" +
    "IGNsYXNzPSJ0cmVuZC1yb3cxIj48ZGl2IGNsYXNzPSJ0cmVuZC1uYW1lIj4nICsgdC5uYW1lICsg" +
    "JzwvZGl2PjxzcGFuIGNsYXNzPSJiYWRnZSAnICsgbWMgKyAnIj4nICsgdC5tb21lbnR1bSArICc8" +
    "L3NwYW4+PC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5kLWRlc2MiPicgKyB0" +
    "LmRlc2MgKyAnPC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5kLXNpZ25hbHMi" +
    "PicgKyB0LnNpZ25hbHMgKyAnPC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InRyZW5k" +
    "LWFjdGlvbnMiPjxkaXYgY2xhc3M9ImNoaXBzIj4nICsgY2hpcHMgKyAnPC9kaXY+PGRpdiBzdHls" +
    "ZT0iZGlzcGxheTpmbGV4O2dhcDo1cHgiPic7CiAgICBpZiAobGlua3MubGVuZ3RoKSBodG1sICs9" +
    "ICc8YnV0dG9uIGNsYXNzPSJhY3QtYnRuIiBvbmNsaWNrPSJ0b2dnbGVCb3goXCdzcmMtJyArIGkg" +
    "KyAnXCcpIj5zb3VyY2VzPC9idXR0b24+JzsKICAgIGlmICh0LmZvcm1hdEhpbnQpIGh0bWwgKz0g" +
    "JzxidXR0b24gY2xhc3M9ImFjdC1idG4iIG9uY2xpY2s9InRvZ2dsZUJveChcJ2hpbnQtJyArIGkg" +
    "KyAnXCcpIj5mb3JtYXQ8L2J1dHRvbj4nOwogICAgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0iYWN0" +
    "LWJ0bicgKyAoaXNTYXZlZCA/ICcgc2F2ZWQnIDogJycpICsgJyIgaWQ9InNiLScgKyBpICsgJyIg" +
    "b25jbGljaz0iZG9TYXZlKCcgKyBpICsgJyxcJycgKyByZWdpb24gKyAnXCcpIj4nICsgKGlzU2F2" +
    "ZWQgPyAnc2F2ZWQnIDogJ3NhdmUnKSArICc8L2J1dHRvbj4nOwogICAgaHRtbCArPSAnPC9kaXY+" +
    "PC9kaXY+JzsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImV4cGFuZC1ib3giIGlkPSJzcmMtJyAr" +
    "IGkgKyAnIj4nICsgKGxpbmtzSHRtbCB8fCAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjExcHg7Y29s" +
    "b3I6dmFyKC0tbXV0ZWQpIj5ObyBzb3VyY2UgbGlua3MuPC9kaXY+JykgKyAnPC9kaXY+JzsKICAg" +
    "IGh0bWwgKz0gJzxkaXYgY2xhc3M9ImhpbnQtYm94IiBpZD0iaGludC0nICsgaSArICciPicgKyAo" +
    "dC5mb3JtYXRIaW50IHx8ICcnKSArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPC9kaXY+JzsKICB9" +
    "CiAgZWwuaW5uZXJIVE1MID0gaHRtbDsKfQoKZnVuY3Rpb24gdG9nZ2xlQm94KGlkKSB7CiAgdmFy" +
    "IGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoaWQpOwogIGlmIChlbCkgZWwuc3R5bGUuZGlz" +
    "cGxheSA9IGVsLnN0eWxlLmRpc3BsYXkgPT09ICdibG9jaycgPyAnbm9uZScgOiAnYmxvY2snOwp9" +
    "CgpmdW5jdGlvbiBkb1NhdmUoaSwgcmVnaW9uKSB7CiAgdmFyIHQgPSB0cmVuZHNbaV07CiAgZm9y" +
    "ICh2YXIgcyA9IDA7IHMgPCBzYXZlZC5sZW5ndGg7IHMrKykgeyBpZiAoc2F2ZWRbc10ubmFtZSA9" +
    "PT0gdC5uYW1lKSByZXR1cm47IH0KICBzYXZlZC5wdXNoKHsgbmFtZTogdC5uYW1lLCBkZXNjOiB0" +
    "LmRlc2MsIHRhZzogJycgfSk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NiLScgKyBpKS50" +
    "ZXh0Q29udGVudCA9ICdzYXZlZCc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NiLScgKyBp" +
    "KS5jbGFzc0xpc3QuYWRkKCdzYXZlZCcpOwogIHJlbmRlclNhdmVkKCk7CiAgZmV0Y2goJy9hcmNo" +
    "aXZlL3NhdmUnLCB7IG1ldGhvZDogJ1BPU1QnLCBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAn" +
    "YXBwbGljYXRpb24vanNvbicgfSwgYm9keTogSlNPTi5zdHJpbmdpZnkoeyBuYW1lOiB0Lm5hbWUs" +
    "IGRlc2M6IHQuZGVzYywgbW9tZW50dW06IHQubW9tZW50dW0sIHNpZ25hbHM6IHQuc2lnbmFscywg" +
    "c291cmNlX2xhYmVsczogdC5zb3VyY2VMYWJlbHMgfHwgW10sIHNvdXJjZV9saW5rczogdC5zb3Vy" +
    "Y2VMaW5rcyB8fCBbXSwgZm9ybWF0X2hpbnQ6IHQuZm9ybWF0SGludCwgdGFnOiAnJywgcmVnaW9u" +
    "OiByZWdpb24gfHwgJ25sJyB9KSB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7IGNvbnNvbGUuZXJy" +
    "b3IoJ2FyY2hpdmUgc2F2ZSBmYWlsZWQnLCBlKTsgfSk7Cn0KCmZ1bmN0aW9uIHJlbmRlclNhdmVk" +
    "KCkgewogIHZhciBlbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzYXZlZC1saXN0Jyk7CiAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2dlbi1yb3cnKS5zdHlsZS5kaXNwbGF5ID0gc2F2ZWQu" +
    "bGVuZ3RoID8gJycgOiAnbm9uZSc7CiAgaWYgKCFzYXZlZC5sZW5ndGgpIHsgZWwuaW5uZXJIVE1M" +
    "ID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyBzYXZlZCB0cmVuZHMgeWV0LjwvZGl2Pic7IHJldHVy" +
    "bjsgfQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBzYXZlZC5sZW5ndGg7" +
    "IGkrKykgewogICAgdmFyIHQgPSBzYXZlZFtpXTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InNh" +
    "dmVkLWl0ZW0iPjxkaXYgY2xhc3M9InNhdmVkLW5hbWUiPicgKyB0Lm5hbWUgKyAnPC9kaXY+JzsK" +
    "ICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6NnB4O2FsaWduLWl0ZW1z" +
    "OmNlbnRlciI+PGlucHV0IGNsYXNzPSJ0YWctaW5wdXQiIHBsYWNlaG9sZGVyPSJ0YWcuLi4iIHZh" +
    "bHVlPSInICsgdC50YWcgKyAnIiBvbmlucHV0PSJzYXZlZFsnICsgaSArICddLnRhZz10aGlzLnZh" +
    "bHVlIi8+JzsKICAgIGh0bWwgKz0gJzxzcGFuIHN0eWxlPSJjdXJzb3I6cG9pbnRlcjtmb250LXNp" +
    "emU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCkiIG9uY2xpY2s9InNhdmVkLnNwbGljZSgnICsgaSAr" +
    "ICcsMSk7cmVuZGVyU2F2ZWQoKSI+JiN4MjcxNTs8L3NwYW4+PC9kaXY+PC9kaXY+JzsKICB9CiAg" +
    "ZWwuaW5uZXJIVE1MID0gaHRtbDsKfQoKdmFyIGdlbmVyYXRlZEZvcm1hdHMgPSBbXTsKCmZ1bmN0" +
    "aW9uIGdlbmVyYXRlRm9ybWF0cygpIHsKICBpZiAoIXNhdmVkLmxlbmd0aCkgcmV0dXJuOwogIHN3" +
    "aXRjaFRhYignZm9ybWF0cycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtcGFuZWwn" +
    "KS5zdHlsZS5kaXNwbGF5ID0gJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdmb3Jt" +
    "YXRzLWxpc3QnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNzPSJs" +
    "b2FkZXIiPjwvc3Bhbj5SZWFkaW5nIHlvdXIgY2F0YWxvZ3VlICZhbXA7IGdlbmVyYXRpbmcgaWRl" +
    "YXMuLi48L2Rpdj4nOwogIGZldGNoKCcvZ2VuZXJhdGUtZm9ybWF0cycsIHsKICAgIG1ldGhvZDog" +
    "J1BPU1QnLAogICAgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24n" +
    "IH0sCiAgICBib2R5OiBKU09OLnN0cmluZ2lmeSh7IHRyZW5kczogc2F2ZWQgfSkKICB9KQogIC50" +
    "aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0aW9uKHJl" +
    "c3VsdCkgewogICAgaWYgKHJlc3VsdC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKHJlc3VsdC5lcnJv" +
    "cik7CiAgICB2YXIgZm9ybWF0cyA9IHJlc3VsdC5mb3JtYXRzIHx8IFtdOwogICAgaWYgKCFmb3Jt" +
    "YXRzLmxlbmd0aCkgdGhyb3cgbmV3IEVycm9yKCdObyBmb3JtYXRzIHJldHVybmVkJyk7CiAgICBn" +
    "ZW5lcmF0ZWRGb3JtYXRzID0gZm9ybWF0czsKICAgIHZhciBodG1sID0gJyc7CiAgICBmb3IgKHZh" +
    "ciBpID0gMDsgaSA8IGZvcm1hdHMubGVuZ3RoOyBpKyspIHsKICAgICAgdmFyIGYgPSBmb3JtYXRz" +
    "W2ldOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQtaXRlbSI+JzsKICAgICAgaHRt" +
    "bCArPSAnPGRpdiBjbGFzcz0iZm9ybWF0LXRpdGxlIj4nICsgZi50aXRsZSArICc8L2Rpdj4nOwog" +
    "ICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQtbG9nbGluZSI+JyArIGYubG9nbGluZSAr" +
    "ICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjZw" +
    "eDtmbGV4LXdyYXA6d3JhcDttYXJnaW4tdG9wOjVweCI+JzsKICAgICAgaHRtbCArPSAnPHNwYW4g" +
    "Y2xhc3M9ImNoaXAiPicgKyBmLmNoYW5uZWwgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzxz" +
    "cGFuIGNsYXNzPSJjaGlwIj4nICsgZi50cmVuZEJhc2lzICsgJzwvc3Bhbj4nOwogICAgICBodG1s" +
    "ICs9ICc8L2Rpdj4nOwogICAgICBpZiAoZi5ob29rKSBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3Jt" +
    "YXQtaG9vayI+IicgKyBmLmhvb2sgKyAnIjwvZGl2Pic7CiAgICAgIGlmIChmLndoeU5ldykgaHRt" +
    "bCArPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tZ3JlZW4pO21hcmdp" +
    "bi10b3A6NXB4O2ZvbnQtc3R5bGU6aXRhbGljIj4nICsgZi53aHlOZXcgKyAnPC9kaXY+JzsKICAg" +
    "ICAgaHRtbCArPSAnPGJ1dHRvbiBjbGFzcz0iZGV2LWJ0biIgb25jbGljaz0ic3RhcnREZXZlbG9w" +
    "bWVudCgnICsgaSArICcpIj4mIzk2NjA7IERldmVsb3AgdGhpcyBmb3JtYXQ8L2J1dHRvbj4nOwog" +
    "ICAgICBodG1sICs9ICc8L2Rpdj4nOwogICAgfQogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9IGh0bWw7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24o" +
    "ZSkgewogICAgc2hvd0VycignRm9ybWF0IGdlbmVyYXRpb24gZmFpbGVkOiAnICsgZS5tZXNzYWdl" +
    "KTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdmb3JtYXRzLWxpc3QnKS5pbm5lckhUTUwg" +
    "PSAnPGRpdiBjbGFzcz0iZW1wdHkiPkZhaWxlZC48L2Rpdj4nOwogIH0pOwp9CgovLyDilIDilIAg" +
    "Rm9ybWF0IGRldmVsb3BtZW50IGNoYXQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA" +
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA" +
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA" +
    "4pSA4pSACnZhciBkZXZNZXNzYWdlcyA9IFtdOwp2YXIgZGV2Rm9ybWF0ID0gbnVsbDsKCmZ1bmN0" +
    "aW9uIHN0YXJ0RGV2ZWxvcG1lbnQoaSkgewogIGRldkZvcm1hdCA9IGdlbmVyYXRlZEZvcm1hdHNb" +
    "aV0gfHwgbnVsbDsKICBkZXZNZXNzYWdlcyA9IFtdOwogIHZhciBwYW5lbCA9IGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdkZXYtcGFuZWwnKTsKICB2YXIgY2hhdCA9IGRvY3VtZW50LmdldEVsZW1l" +
    "bnRCeUlkKCdkZXYtY2hhdCcpOwogIHBhbmVsLnN0eWxlLmRpc3BsYXkgPSAnZmxleCc7CiAgY2hh" +
    "dC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwv" +
    "c3Bhbj5TdGFydGluZyBkZXZlbG9wbWVudCBzZXNzaW9uLi4uPC9kaXY+JzsKICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnZGV2LXBhbmVsLXN1YnRpdGxlJykudGV4dENvbnRlbnQgPSAnRGV2ZWxv" +
    "cGluZzogJyArIChkZXZGb3JtYXQgPyBkZXZGb3JtYXQudGl0bGUgOiAnRm9ybWF0IGlkZWEnKTsK" +
    "ICBwYW5lbC5zY3JvbGxJbnRvVmlldyh7IGJlaGF2aW9yOiAnc21vb3RoJywgYmxvY2s6ICdzdGFy" +
    "dCcgfSk7CgogIC8vIE9wZW5pbmcgbWVzc2FnZSBmcm9tIHRoZSBBSQogIGZldGNoKCcvZGV2ZWxv" +
    "cCcsIHsKICAgIG1ldGhvZDogJ1BPU1QnLAogICAgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzog" +
    "J2FwcGxpY2F0aW9uL2pzb24nIH0sCiAgICBib2R5OiBKU09OLnN0cmluZ2lmeSh7CiAgICAgIGZv" +
    "cm1hdF9pZGVhOiBkZXZGb3JtYXQsCiAgICAgIHRyZW5kczogc2F2ZWQsCiAgICAgIG1lc3NhZ2Vz" +
    "OiBbewogICAgICAgIHJvbGU6ICd1c2VyJywKICAgICAgICBjb250ZW50OiAnSSB3YW50IHRvIGRl" +
    "dmVsb3AgdGhpcyBmb3JtYXQgaWRlYS4gSGVyZSBpcyB3aGF0IHdlIGhhdmUgc28gZmFyOiBUaXRs" +
    "ZTogIicgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LnRpdGxlIDogJycpICsgJyIuIExvZ2xpbmU6" +
    "ICcgKyAoZGV2Rm9ybWF0ID8gZGV2Rm9ybWF0LmxvZ2xpbmUgOiAnJykgKyAnLiBQbGVhc2Ugc3Rh" +
    "cnQgb3VyIGRldmVsb3BtZW50IHNlc3Npb24uJwogICAgICB9XQogICAgfSkKICB9KQogIC50aGVu" +
    "KGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0aW9uKGQpIHsK" +
    "ICAgIGlmIChkLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoZC5lcnJvcik7CiAgICBkZXZNZXNzYWdl" +
    "cyA9IFsKICAgICAgeyByb2xlOiAndXNlcicsIGNvbnRlbnQ6ICdJIHdhbnQgdG8gZGV2ZWxvcCB0" +
    "aGlzIGZvcm1hdCBpZGVhLiBIZXJlIGlzIHdoYXQgd2UgaGF2ZSBzbyBmYXI6IFRpdGxlOiAiJyAr" +
    "IChkZXZGb3JtYXQgPyBkZXZGb3JtYXQudGl0bGUgOiAnJykgKyAnIi4gTG9nbGluZTogJyArIChk" +
    "ZXZGb3JtYXQgPyBkZXZGb3JtYXQubG9nbGluZSA6ICcnKSArICcuIFBsZWFzZSBzdGFydCBvdXIg" +
    "ZGV2ZWxvcG1lbnQgc2Vzc2lvbi4nIH0sCiAgICAgIHsgcm9sZTogJ2Fzc2lzdGFudCcsIGNvbnRl" +
    "bnQ6IGQucmVzcG9uc2UgfQogICAgXTsKICAgIHJlbmRlckRldkNoYXQoKTsKICB9KQogIC5jYXRj" +
    "aChmdW5jdGlvbihlKSB7CiAgICBjaGF0LmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+" +
    "Q291bGQgbm90IHN0YXJ0IHNlc3Npb246ICcgKyBlLm1lc3NhZ2UgKyAnPC9kaXY+JzsKICB9KTsK" +
    "fQoKZnVuY3Rpb24gc2VuZERldk1lc3NhZ2UoKSB7CiAgdmFyIGlucHV0ID0gZG9jdW1lbnQuZ2V0" +
    "RWxlbWVudEJ5SWQoJ2Rldi1pbnB1dCcpOwogIHZhciBtc2cgPSBpbnB1dC52YWx1ZS50cmltKCk7" +
    "CiAgaWYgKCFtc2cgfHwgIWRldkZvcm1hdCkgcmV0dXJuOwogIGlucHV0LnZhbHVlID0gJyc7CiAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1zZW5kJykuZGlzYWJsZWQgPSB0cnVlOwoKICBk" +
    "ZXZNZXNzYWdlcy5wdXNoKHsgcm9sZTogJ3VzZXInLCBjb250ZW50OiBtc2cgfSk7CiAgcmVuZGVy" +
    "RGV2Q2hhdCgpOwoKICBmZXRjaCgnL2RldmVsb3AnLCB7CiAgICBtZXRob2Q6ICdQT1NUJywKICAg" +
    "IGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LAogICAgYm9k" +
    "eTogSlNPTi5zdHJpbmdpZnkoewogICAgICBmb3JtYXRfaWRlYTogZGV2Rm9ybWF0LAogICAgICB0" +
    "cmVuZHM6IHNhdmVkLAogICAgICBtZXNzYWdlczogZGV2TWVzc2FnZXMKICAgIH0pCiAgfSkKICAu" +
    "dGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkKICAudGhlbihmdW5jdGlvbihk" +
    "KSB7CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKGQuZXJyb3IpOwogICAgZGV2TWVz" +
    "c2FnZXMucHVzaCh7IHJvbGU6ICdhc3Npc3RhbnQnLCBjb250ZW50OiBkLnJlc3BvbnNlIH0pOwog" +
    "ICAgcmVuZGVyRGV2Q2hhdCgpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1zZW5k" +
    "JykuZGlzYWJsZWQgPSBmYWxzZTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtaW5w" +
    "dXQnKS5mb2N1cygpOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAgIGRldk1lc3NhZ2Vz" +
    "LnB1c2goeyByb2xlOiAnYXNzaXN0YW50JywgY29udGVudDogJ1NvcnJ5LCBzb21ldGhpbmcgd2Vu" +
    "dCB3cm9uZzogJyArIGUubWVzc2FnZSB9KTsKICAgIHJlbmRlckRldkNoYXQoKTsKICAgIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtc2VuZCcpLmRpc2FibGVkID0gZmFsc2U7CiAgfSk7Cn0K" +
    "CmZ1bmN0aW9uIHJlbmRlckRldkNoYXQoKSB7CiAgdmFyIGNoYXQgPSBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnZGV2LWNoYXQnKTsKICB2YXIgaHRtbCA9ICcnOwogIGZvciAodmFyIGkgPSAwOyBp" +
    "IDwgZGV2TWVzc2FnZXMubGVuZ3RoOyBpKyspIHsKICAgIHZhciBtID0gZGV2TWVzc2FnZXNbaV07" +
    "CiAgICB2YXIgY2xzID0gbS5yb2xlID09PSAnYXNzaXN0YW50JyA/ICdhaScgOiAndXNlcic7CiAg" +
    "ICB2YXIgdGV4dCA9IG0uY29udGVudC5yZXBsYWNlKC9cbi9nLCAnPGJyPicpOwogICAgaHRtbCAr" +
    "PSAnPGRpdiBjbGFzcz0iZGV2LW1zZyAnICsgY2xzICsgJyI+JyArIHRleHQgKyAnPC9kaXY+JzsK" +
    "ICB9CiAgY2hhdC5pbm5lckhUTUwgPSBodG1sOwogIGNoYXQuc2Nyb2xsVG9wID0gY2hhdC5zY3Jv" +
    "bGxIZWlnaHQ7Cn0KCmZ1bmN0aW9uIGxvYWRSZXNlYXJjaCgpIHsKICBmZXRjaCgnL3Jlc2VhcmNo" +
    "JykudGhlbihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkudGhlbihmdW5jdGlvbihk" +
    "KSB7IHJlbmRlclJlc2VhcmNoKGQuaXRlbXMgfHwgW10pOyB9KQogIC5jYXRjaChmdW5jdGlvbigp" +
    "IHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Jlc2VhcmNoLWZlZWQnKS5pbm5lckhUTUwgPSAn" +
    "PGRpdiBjbGFzcz0iZW1wdHkiPkNvdWxkIG5vdCBsb2FkIHJlc2VhcmNoLjwvZGl2Pic7IH0pOwp9" +
    "CgpmdW5jdGlvbiByZW5kZXJSZXNlYXJjaChpdGVtcykgewogIHZhciBlbCA9IGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdyZXNlYXJjaC1mZWVkJyk7CiAgaWYgKCFpdGVtcy5sZW5ndGgpIHsgZWwu" +
    "aW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyByZXNlYXJjaCBpdGVtcyBmb3VuZC48" +
    "L2Rpdj4nOyByZXR1cm47IH0KICB2YXIgdHlwZU1hcCA9IHsgcmVzZWFyY2g6ICdSZXNlYXJjaCcs" +
    "IGN1bHR1cmU6ICdDdWx0dXJlJywgdHJlbmRzOiAnVHJlbmRzJyB9OyB2YXIgaHRtbCA9ICcnOwog" +
    "IGZvciAodmFyIGkgPSAwOyBpIDwgaXRlbXMubGVuZ3RoOyBpKyspIHsKICAgIHZhciBpdGVtID0g" +
    "aXRlbXNbaV07CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJyZXNlYXJjaC1pdGVtIj48ZGl2IGNs" +
    "YXNzPSJyZXNlYXJjaC10aXRsZSI+PGEgaHJlZj0iJyArIGl0ZW0udXJsICsgJyIgdGFyZ2V0PSJf" +
    "YmxhbmsiPicgKyBpdGVtLnRpdGxlICsgJzwvYT48L2Rpdj4nOwogICAgaWYgKGl0ZW0uZGVzYykg" +
    "aHRtbCArPSAnPGRpdiBjbGFzcz0icmVzZWFyY2gtZGVzYyI+JyArIGl0ZW0uZGVzYyArICc8L2Rp" +
    "dj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0icmVzZWFyY2gtbWV0YSI+PHNwYW4gY2xhc3M9" +
    "InItc3JjIj4nICsgaXRlbS5zb3VyY2UgKyAnPC9zcGFuPjxzcGFuIGNsYXNzPSJyLXR5cGUiPicg" +
    "KyAodHlwZU1hcFtpdGVtLnR5cGVdIHx8IGl0ZW0udHlwZSkgKyAnPC9zcGFuPjwvZGl2PjwvZGl2" +
    "Pic7CiAgfQogIGVsLmlubmVySFRNTCA9IGh0bWw7Cn0KCmZ1bmN0aW9uIGRvQXJjaGl2ZVNlYXJj" +
    "aCgpIHsKICB2YXIgcXVlcnkgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1zZWFy" +
    "Y2gtaW5wdXQnKS52YWx1ZS50cmltKCk7CiAgaWYgKCFxdWVyeSkgcmV0dXJuOwogIHZhciByZXN1" +
    "bHRzRWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2VhcmNoLXJlc3VsdHMnKTsKICByZXN1" +
    "bHRzRWwuaW5uZXJIVE1MID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2NvbG9yOnZhcigt" +
    "LW11dGVkKSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPlNlYXJjaGluZyBhcmNoaXZlLi4u" +
    "PC9kaXY+JzsKCiAgZmV0Y2goJy9hcmNoaXZlL3NlYXJjaCcsIHsKICAgIG1ldGhvZDogJ1BPU1Qn" +
    "LAogICAgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sCiAg" +
    "ICBib2R5OiBKU09OLnN0cmluZ2lmeSh7IHF1ZXJ5OiBxdWVyeSB9KQogIH0pCiAgLnRoZW4oZnVu" +
    "Y3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24oZCkgewogICAg" +
    "aWYgKGQuZXJyb3IpIHRocm93IG5ldyBFcnJvcihkLmVycm9yKTsKICAgIHZhciByZXN1bHRzID0g" +
    "ZC5yZXN1bHRzIHx8IFtdOwogICAgaWYgKCFyZXN1bHRzLmxlbmd0aCkgewogICAgICByZXN1bHRz" +
    "RWwuaW5uZXJIVE1MID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2NvbG9yOnZhcigtLW11" +
    "dGVkKTtwYWRkaW5nOjhweCAwIj5ObyByZWxldmFudCB0cmVuZHMgZm91bmQgZm9yICInICsgcXVl" +
    "cnkgKyAnIi48L2Rpdj4nOwogICAgICByZXR1cm47CiAgICB9CiAgICB2YXIgbWNNYXAgPSB7IHJp" +
    "c2luZzogJ2ItcmlzaW5nJywgZW1lcmdpbmc6ICdiLWVtZXJnaW5nJywgZXN0YWJsaXNoZWQ6ICdi" +
    "LWVzdGFibGlzaGVkJywgc2hpZnRpbmc6ICdiLXNoaWZ0aW5nJyB9OwogICAgdmFyIGh0bWwgPSAn" +
    "PGRpdiBzdHlsZT0iZm9udC1zaXplOjEwcHg7Zm9udC13ZWlnaHQ6NjAwO2NvbG9yOnZhcigtLW11" +
    "dGVkKTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2U7bGV0dGVyLXNwYWNpbmc6MC44cHg7bWFyZ2lu" +
    "LWJvdHRvbToxMHB4Ij4nICsgcmVzdWx0cy5sZW5ndGggKyAnIHJlbGV2YW50IHRyZW5kcyBmb3Vu" +
    "ZDwvZGl2Pic7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IHJlc3VsdHMubGVuZ3RoOyBpKyspIHsK" +
    "ICAgICAgdmFyIHQgPSByZXN1bHRzW2ldOwogICAgICB2YXIgbWMgPSBtY01hcFt0Lm1vbWVudHVt" +
    "XSB8fCAnYi1lbWVyZ2luZyc7CiAgICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9InBhZGRpbmc6MTJw" +
    "eCAwO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcikiPic7CiAgICAgIGh0bWwg" +
    "Kz0gJzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjhweDtt" +
    "YXJnaW4tYm90dG9tOjVweCI+JzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZm9udC1zaXpl" +
    "OjEzcHg7Zm9udC13ZWlnaHQ6NjAwO2NvbG9yOiNmZmYiPicgKyB0Lm5hbWUgKyAnPC9kaXY+JzsK" +
    "ICAgICAgaHRtbCArPSAnPHNwYW4gY2xhc3M9ImJhZGdlICcgKyBtYyArICciPicgKyAodC5tb21l" +
    "bnR1bSB8fCAnJykgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzxzcGFuIHN0eWxlPSJmb250" +
    "LXNpemU6MTBweDtjb2xvcjp2YXIoLS1tdXRlZCkiPicgKyB0LnNhdmVkX2F0LnNsaWNlKDAsMTAp" +
    "ICsgJzwvc3Bhbj4nOwogICAgICBodG1sICs9ICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8ZGl2" +
    "IHN0eWxlPSJmb250LXNpemU6MTJweDtjb2xvcjp2YXIoLS1tdXRlZCk7bGluZS1oZWlnaHQ6MS41" +
    "O21hcmdpbi1ib3R0b206NXB4Ij4nICsgKHQuZGVzYyB8fCAnJykgKyAnPC9kaXY+JzsKICAgICAg" +
    "aWYgKHQucmVsZXZhbmNlKSBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTFweDtjb2xv" +
    "cjp2YXIoLS1hY2NlbnQyKTtmb250LXN0eWxlOml0YWxpYyI+JyArIHQucmVsZXZhbmNlICsgJzwv" +
    "ZGl2Pic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICB9CiAgICByZXN1bHRzRWwuaW5uZXJI" +
    "VE1MID0gaHRtbDsKICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7CiAgICByZXN1bHRzRWwuaW5u" +
    "ZXJIVE1MID0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2NvbG9yOiNmY2E1YTUiPlNlYXJj" +
    "aCBmYWlsZWQ6ICcgKyBlLm1lc3NhZ2UgKyAnPC9kaXY+JzsKICB9KTsKfQoKZnVuY3Rpb24gbG9h" +
    "ZEFyY2hpdmUoKSB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RhdGUtbGlzdCcpLmlubmVy" +
    "SFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSIgc3R5bGU9InBhZGRpbmc6MXJlbSAwIj48c3BhbiBj" +
    "bGFzcz0ibG9hZGVyIj48L3NwYW4+PC9kaXY+JzsKICBmZXRjaCgnL2FyY2hpdmUvZGF0ZXMnKS50" +
    "aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0aW9uKGQp" +
    "IHsKICAgIGlmICghZC5kYXRlcyB8fCAhZC5kYXRlcy5sZW5ndGgpIHsgZG9jdW1lbnQuZ2V0RWxl" +
    "bWVudEJ5SWQoJ2RhdGUtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSIgc3R5" +
    "bGU9InBhZGRpbmc6MXJlbSAwO2ZvbnQtc2l6ZToxMXB4Ij5ObyBhcmNoaXZlZCB0cmVuZHMgeWV0" +
    "LjwvZGl2Pic7IHJldHVybjsgfQogICAgdmFyIGh0bWwgPSAnJzsKICAgIGZvciAodmFyIGkgPSAw" +
    "OyBpIDwgZC5kYXRlcy5sZW5ndGg7IGkrKykgeyBodG1sICs9ICc8ZGl2IGNsYXNzPSJkYXRlLWl0" +
    "ZW0iIG9uY2xpY2s9ImxvYWREYXRlKFwnJyArIGQuZGF0ZXNbaV0uZGF0ZSArICdcJyx0aGlzKSI+" +
    "JyArIGQuZGF0ZXNbaV0uZGF0ZSArICc8c3BhbiBjbGFzcz0iZGF0ZS1jb3VudCI+JyArIGQuZGF0" +
    "ZXNbaV0uY291bnQgKyAnPC9zcGFuPjwvZGl2Pic7IH0KICAgIGRvY3VtZW50LmdldEVsZW1lbnRC" +
    "eUlkKCdkYXRlLWxpc3QnKS5pbm5lckhUTUwgPSBodG1sOwogICAgdmFyIGZpcnN0ID0gZG9jdW1l" +
    "bnQucXVlcnlTZWxlY3RvcignLmRhdGUtaXRlbScpOyBpZiAoZmlyc3QpIGZpcnN0LmNsaWNrKCk7" +
    "CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXJj" +
    "aGl2ZS1lcnInKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZXJyYm94Ij5Db3VsZCBub3QgbG9h" +
    "ZCBhcmNoaXZlOiAnICsgZS5tZXNzYWdlICsgJzwvZGl2Pic7IH0pOwp9CgpmdW5jdGlvbiBsb2Fk" +
    "RGF0ZShkYXRlLCBlbCkgewogIHZhciBpdGVtcyA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwo" +
    "Jy5kYXRlLWl0ZW0nKTsgZm9yICh2YXIgaSA9IDA7IGkgPCBpdGVtcy5sZW5ndGg7IGkrKykgaXRl" +
    "bXNbaV0uY2xhc3NMaXN0LnJlbW92ZSgnYWN0aXZlJyk7CiAgZWwuY2xhc3NMaXN0LmFkZCgnYWN0" +
    "aXZlJyk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtaGVhZGluZycpLnRleHRD" +
    "b250ZW50ID0gJ1NhdmVkIG9uICcgKyBkYXRlOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdh" +
    "cmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNs" +
    "YXNzPSJsb2FkZXIiPjwvc3Bhbj48L2Rpdj4nOwogIGZldGNoKCcvYXJjaGl2ZS9ieS1kYXRlP2Rh" +
    "dGU9JyArIGVuY29kZVVSSUNvbXBvbmVudChkYXRlKSkudGhlbihmdW5jdGlvbihyKSB7IHJldHVy" +
    "biByLmpzb24oKTsgfSkKICAudGhlbihmdW5jdGlvbihkKSB7CiAgICBpZiAoIWQudHJlbmRzIHx8" +
    "ICFkLnRyZW5kcy5sZW5ndGgpIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtY29u" +
    "dGVudCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gdHJlbmRzIGZvciB0aGlz" +
    "IGRhdGUuPC9kaXY+JzsgcmV0dXJuOyB9CiAgICB2YXIgaHRtbCA9ICcnOwogICAgZm9yICh2YXIg" +
    "aSA9IDA7IGkgPCBkLnRyZW5kcy5sZW5ndGg7IGkrKykgewogICAgICB2YXIgdCA9IGQudHJlbmRz" +
    "W2ldOwogICAgICB2YXIgbWNNYXAgPSB7IHJpc2luZzogJ2ItcmlzaW5nJywgZW1lcmdpbmc6ICdi" +
    "LWVtZXJnaW5nJywgZXN0YWJsaXNoZWQ6ICdiLWVzdGFibGlzaGVkJywgc2hpZnRpbmc6ICdiLXNo" +
    "aWZ0aW5nJyB9OwogICAgICB2YXIgbWMgPSBtY01hcFt0Lm1vbWVudHVtXSB8fCAnYi1lbWVyZ2lu" +
    "Zyc7IHZhciBsaW5rcyA9IFtdOwogICAgICB0cnkgeyBsaW5rcyA9IEpTT04ucGFyc2UodC5zb3Vy" +
    "Y2VfbGlua3MgfHwgJ1tdJyk7IH0gY2F0Y2goZSkge30KICAgICAgaHRtbCArPSAnPGRpdiBjbGFz" +
    "cz0iYXJjaC1pdGVtIj48ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVy" +
    "O2dhcDo4cHg7bWFyZ2luLWJvdHRvbTozcHgiPjxkaXYgY2xhc3M9ImFyY2gtbmFtZSI+JyArIHQu" +
    "bmFtZSArICc8L2Rpdj48c3BhbiBjbGFzcz0iYmFkZ2UgJyArIG1jICsgJyI+JyArICh0Lm1vbWVu" +
    "dHVtIHx8ICcnKSArICc8L3NwYW4+PC9kaXY+JzsKICAgICAgaHRtbCArPSAnPGRpdiBjbGFzcz0i" +
    "YXJjaC1tZXRhIj4nICsgdC5zYXZlZF9hdCArICh0LnJlZ2lvbiA/ICcgJm1pZGRvdDsgJyArIHQu" +
    "cmVnaW9uLnRvVXBwZXJDYXNlKCkgOiAnJykgKyAodC50YWcgPyAnICZtaWRkb3Q7ICcgKyB0LnRh" +
    "ZyA6ICcnKSArICc8L2Rpdj4nOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJhcmNoLWRlc2Mi" +
    "PicgKyAodC5kZXNjIHx8ICcnKSArICc8L2Rpdj4nOwogICAgICBmb3IgKHZhciBsID0gMDsgbCA8" +
    "IGxpbmtzLmxlbmd0aDsgbCsrKSB7IGh0bWwgKz0gJzxhIGNsYXNzPSJhcmNoLWxpbmsiIGhyZWY9" +
    "IicgKyBsaW5rc1tsXS51cmwgKyAnIiB0YXJnZXQ9Il9ibGFuayI+JyArIGxpbmtzW2xdLnRpdGxl" +
    "ICsgJzwvYT4nOyB9CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICB9CiAgICBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1jb250ZW50JykuaW5uZXJIVE1MID0gaHRtbDsKICB9KQog" +
    "IC5jYXRjaChmdW5jdGlvbigpIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FyY2hpdmUtY29u" +
    "dGVudCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Q291bGQgbm90IGxvYWQuPC9k" +
    "aXY+JzsgfSk7Cn0KPC9zY3JpcHQ+CjwvYm9keT4KPC9odG1sPgo="
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
