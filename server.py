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
    "Tk9TPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5Hb29nbGUgVHJlbmRzPC9z" +
    "cGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5OWVQgQm9va3M8L3NwYW4+CiAgICA8" +
    "c3BhbiBjbGFzcz0ic3JjLXBpbGwgb24iPlNDUDwvc3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJzcmMt" +
    "cGlsbCBvbiI+Q0JTPC9zcGFuPgogICAgPHNwYW4gY2xhc3M9InNyYy1waWxsIG9uIj5QZXcgUmVz" +
    "ZWFyY2g8L3NwYW4+CiAgPC9kaXY+CjwvZGl2PgoKPGRpdiBjbGFzcz0ibWFpbiI+CiAgPGRpdiBj" +
    "bGFzcz0idG9wYmFyIj4KICAgIDxkaXYgY2xhc3M9InRvcGJhci10aXRsZSIgaWQ9InBhZ2UtdGl0" +
    "bGUiPkRhc2hib2FyZDwvZGl2PgogICAgPGRpdiBjbGFzcz0idG9wYmFyLXJpZ2h0IiBpZD0ic2Nh" +
    "bi1jb250cm9scyI+CiAgICAgIDxzZWxlY3QgY2xhc3M9InNlbCIgaWQ9InJlZ2lvbi1zZWwiPgog" +
    "ICAgICAgIDxvcHRpb24gdmFsdWU9Im5sIj5OTCBmb2N1czwvb3B0aW9uPgogICAgICAgIDxvcHRp" +
    "b24gdmFsdWU9ImV1Ij5FVSAvIGdsb2JhbDwvb3B0aW9uPgogICAgICAgIDxvcHRpb24gdmFsdWU9" +
    "ImFsbCI+QWxsIG1hcmtldHM8L29wdGlvbj4KICAgICAgPC9zZWxlY3Q+CiAgICAgIDxzZWxlY3Qg" +
    "Y2xhc3M9InNlbCIgaWQ9Imhvcml6b24tc2VsIj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJlbWVy" +
    "Z2luZyI+RW1lcmdpbmc8L29wdGlvbj4KICAgICAgICA8b3B0aW9uIHZhbHVlPSJyaXNpbmciPlJp" +
    "c2luZzwvb3B0aW9uPgogICAgICAgIDxvcHRpb24gdmFsdWU9ImFsbCI+QWxsIHNpZ25hbHM8L29w" +
    "dGlvbj4KICAgICAgPC9zZWxlY3Q+CiAgICAgIDxidXR0b24gY2xhc3M9InNjYW4tYnRuIiBpZD0i" +
    "c2Nhbi1idG4iIG9uY2xpY2s9InJ1blNjYW4oKSI+U2NhbiBub3c8L2J1dHRvbj4KICAgIDwvZGl2" +
    "PgogIDwvZGl2PgoKICA8ZGl2IGNsYXNzPSJjb250ZW50Ij4KICAgIDxkaXYgaWQ9InZpZXctZGFz" +
    "aGJvYXJkIj4KICAgICAgPGRpdiBjbGFzcz0ic3RhdHVzLWJhciI+CiAgICAgICAgPGRpdiBjbGFz" +
    "cz0ic3RhdHVzLWRvdCIgaWQ9InN0YXR1cy1kb3QiPjwvZGl2PgogICAgICAgIDxzcGFuIGlkPSJz" +
    "dGF0dXMtdGV4dCI+UmVhZHkgdG8gc2Nhbjwvc3Bhbj4KICAgICAgICA8c3BhbiBpZD0iaGVhZGxp" +
    "bmUtY291bnQiIHN0eWxlPSJjb2xvcjpyZ2JhKDI1NSwyNTUsMjU1LDAuMikiPjwvc3Bhbj4KICAg" +
    "ICAgPC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InByb2dyZXNzLWJhciI+PGRpdiBjbGFzcz0icHJv" +
    "Z3Jlc3MtZmlsbCIgaWQ9InByb2dyZXNzLWZpbGwiPjwvZGl2PjwvZGl2PgogICAgICA8ZGl2IGlk" +
    "PSJlcnItYm94Ij48L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9ImdyaWQtMyI+CiAgICAgICAgPGRp" +
    "dj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJj" +
    "YXJkLWhlYWRlciIgc3R5bGU9InBhZGRpbmctYm90dG9tOjAiPgogICAgICAgICAgICAgIDxkaXYg" +
    "Y2xhc3M9InRhYnMiPgogICAgICAgICAgICAgICAgPGJ1dHRvbiBjbGFzcz0idGFiLWJ0biBhY3Rp" +
    "dmUiIGlkPSJ0YWItdCIgb25jbGljaz0ic3dpdGNoVGFiKCd0cmVuZHMnKSI+Q3VsdHVyYWwgdHJl" +
    "bmRzPC9idXR0b24+CiAgICAgICAgICAgICAgICA8YnV0dG9uIGNsYXNzPSJ0YWItYnRuIiBpZD0i" +
    "dGFiLWYiIG9uY2xpY2s9InN3aXRjaFRhYignZm9ybWF0cycpIj5Gb3JtYXQgaWRlYXM8L2J1dHRv" +
    "bj4KICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxk" +
    "aXYgY2xhc3M9ImNhcmQtYm9keSI+CiAgICAgICAgICAgICAgPGRpdiBpZD0icGFuZS10cmVuZHMi" +
    "PjxkaXYgaWQ9InRyZW5kcy1saXN0Ij48ZGl2IGNsYXNzPSJlbXB0eSI+UHJlc3MgIlNjYW4gbm93" +
    "IiB0byBkZXRlY3QgdHJlbmRzLjwvZGl2PjwvZGl2PjwvZGl2PgogICAgICAgICAgICAgIDxkaXYg" +
    "aWQ9InBhbmUtZm9ybWF0cyIgc3R5bGU9ImRpc3BsYXk6bm9uZSI+CiAgICAgICAgICAgICAgICA8" +
    "ZGl2IGlkPSJmb3JtYXRzLWxpc3QiPjxkaXYgY2xhc3M9ImVtcHR5Ij5TYXZlIHRyZW5kcywgdGhl" +
    "biBnZW5lcmF0ZSBmb3JtYXQgaWRlYXMuPC9kaXY+PC9kaXY+CiAgICAgICAgICAgICAgPC9kaXY+" +
    "CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+CgogICAg" +
    "ICAgIDxkaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkIj4KICAgICAgICAgICAgPGRpdiBj" +
    "bGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQtdGl0bGUiPlNsb3cgdHJlbmRzICZt" +
    "ZGFzaDsgcmVzZWFyY2ggJmFtcDsgcmVwb3J0czwvZGl2PjwvZGl2PgogICAgICAgICAgICA8ZGl2" +
    "IGNsYXNzPSJjYXJkLWJvZHkiPjxkaXYgaWQ9InJlc2VhcmNoLWZlZWQiPjxkaXYgY2xhc3M9ImVt" +
    "cHR5Ij5SZXNlYXJjaCBsb2FkcyB3aGVuIHlvdSBzY2FuLjwvZGl2PjwvZGl2PjwvZGl2PgogICAg" +
    "ICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+CgogICAgICAgIDxkaXY+CiAgICAgICAgICA8ZGl2" +
    "IGNsYXNzPSJjYXJkIj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYg" +
    "Y2xhc3M9ImNhcmQtdGl0bGUiPkxpdmUgaGVhZGxpbmVzPC9kaXY+PC9kaXY+CiAgICAgICAgICAg" +
    "IDxkaXYgY2xhc3M9ImNhcmQtYm9keSI+PGRpdiBpZD0ic2lnbmFsLWZlZWQiPjxkaXYgY2xhc3M9" +
    "ImVtcHR5Ij5IZWFkbGluZXMgYXBwZWFyIGFmdGVyIHNjYW5uaW5nLjwvZGl2PjwvZGl2PjwvZGl2" +
    "PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJjYXJkIHNlY3Rpb24tZ2Fw" +
    "Ij4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iY2FyZC1oZWFkZXIiPjxkaXYgY2xhc3M9ImNhcmQt" +
    "dGl0bGUiPlNhdmVkIHRyZW5kczwvZGl2PjwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJj" +
    "YXJkLWJvZHkiPgogICAgICAgICAgICAgIDxkaXYgaWQ9InNhdmVkLWxpc3QiPjxkaXYgY2xhc3M9" +
    "ImVtcHR5Ij5ObyBzYXZlZCB0cmVuZHMgeWV0LjwvZGl2PjwvZGl2PgogICAgICAgICAgICAgIDxk" +
    "aXYgaWQ9Imdlbi1yb3ciIHN0eWxlPSJkaXNwbGF5Om5vbmUiPjxidXR0b24gY2xhc3M9Imdlbi1i" +
    "dG4iIG9uY2xpY2s9ImdlbmVyYXRlRm9ybWF0cygpIj5HZW5lcmF0ZSBmb3JtYXQgaWRlYXMgJnJh" +
    "cnI7PC9idXR0b24+PC9kaXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAg" +
    "ICAgICAgPC9kaXY+CiAgICAgIDwvZGl2PgoKICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsIiBp" +
    "ZD0iZGV2LXBhbmVsIiBzdHlsZT0ibWFyZ2luLXRvcDoxNnB4Ij4KICAgICAgICA8ZGl2IGNsYXNz" +
    "PSJkZXYtcGFuZWwtaGVhZGVyIiBzdHlsZT0iZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRl" +
    "cjtqdXN0aWZ5LWNvbnRlbnQ6c3BhY2UtYmV0d2VlbiI+CiAgICAgICAgICA8ZGl2PgogICAgICAg" +
    "ICAgICA8ZGl2IGNsYXNzPSJkZXYtcGFuZWwtdGl0bGUiPiYjOTY3OTsgRm9ybWF0IERldmVsb3Bt" +
    "ZW50IFNlc3Npb248L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0iZGV2LXBhbmVsLXN1YnRp" +
    "dGxlIiBpZD0iZGV2LXBhbmVsLXN1YnRpdGxlIj5EZXZlbG9waW5nOiAmbWRhc2g7PC9kaXY+CiAg" +
    "ICAgICAgICA8L2Rpdj4KICAgICAgICAgIDxidXR0b24gb25jbGljaz0iZG9jdW1lbnQuZ2V0RWxl" +
    "bWVudEJ5SWQoJ2Rldi1wYW5lbCcpLnN0eWxlLmRpc3BsYXk9J25vbmUnIiBzdHlsZT0iYmFja2dy" +
    "b3VuZDpub25lO2JvcmRlcjpub25lO2NvbG9yOnZhcigtLW11dGVkKTtjdXJzb3I6cG9pbnRlcjtm" +
    "b250LXNpemU6MThweDtwYWRkaW5nOjRweCA4cHgiPiZ0aW1lczs8L2J1dHRvbj4KICAgICAgICA8" +
    "L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJkZXYtY2hhdCIgaWQ9ImRldi1jaGF0Ij48L2Rpdj4K" +
    "ICAgICAgICA8ZGl2IGNsYXNzPSJkZXYtaW5wdXQtcm93Ij4KICAgICAgICAgIDxpbnB1dCBjbGFz" +
    "cz0iZGV2LWlucHV0IiBpZD0iZGV2LWlucHV0IiB0eXBlPSJ0ZXh0IiBwbGFjZWhvbGRlcj0iUmVw" +
    "bHkgdG8geW91ciBkZXZlbG9wbWVudCBleGVjLi4uIiBvbmtleWRvd249ImlmKGV2ZW50LmtleT09" +
    "PSdFbnRlcicpc2VuZERldk1lc3NhZ2UoKSIgLz4KICAgICAgICAgIDxidXR0b24gY2xhc3M9ImRl" +
    "di1zZW5kIiBpZD0iZGV2LXNlbmQiIG9uY2xpY2s9InNlbmREZXZNZXNzYWdlKCkiPlNlbmQ8L2J1" +
    "dHRvbj4KICAgICAgICA8L2Rpdj4KICAgICAgPC9kaXY+CiAgICA8L2Rpdj4KCiAgICA8ZGl2IGlk" +
    "PSJ2aWV3LWFyY2hpdmUiIHN0eWxlPSJkaXNwbGF5Om5vbmUiPgogICAgICA8ZGl2IGlkPSJhcmNo" +
    "aXZlLWVyciI+PC9kaXY+CgogICAgICA8IS0tIFNlbWFudGljIHNlYXJjaCBiYXIgLS0+CiAgICAg" +
    "IDxkaXYgY2xhc3M9ImNhcmQiIHN0eWxlPSJtYXJnaW4tYm90dG9tOjE2cHgiPgogICAgICAgIDxk" +
    "aXYgY2xhc3M9ImNhcmQtaGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxlIj5TZWFyY2ggYXJj" +
    "aGl2ZSBieSBjb25jZXB0IG9yIGZvcm1hdCBpZGVhPC9kaXY+PC9kaXY+CiAgICAgICAgPGRpdiBj" +
    "bGFzcz0iY2FyZC1ib2R5IiBzdHlsZT0icGFkZGluZzoxNHB4IDE2cHgiPgogICAgICAgICAgPGRp" +
    "diBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDoxMHB4O2FsaWduLWl0ZW1zOmNlbnRlciI+CiAgICAg" +
    "ICAgICAgIDxpbnB1dCBpZD0iYXJjaGl2ZS1zZWFyY2gtaW5wdXQiIHR5cGU9InRleHQiCiAgICAg" +
    "ICAgICAgICAgcGxhY2Vob2xkZXI9ImUuZy4gJ2VlbnphYW1oZWlkIG9uZGVyIGpvbmdlcmVuJyBv" +
    "ciAnZmFtaWxpZXMgdW5kZXIgcHJlc3N1cmUnLi4uIgogICAgICAgICAgICAgIHN0eWxlPSJmbGV4" +
    "OjE7Zm9udC1zaXplOjEzcHg7cGFkZGluZzo5cHggMTRweDtib3JkZXItcmFkaXVzOjhweDtib3Jk" +
    "ZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpO2JhY2tncm91bmQ6cmdiYSgyNTUsMjU1LDI1NSww" +
    "LjA0KTtjb2xvcjp2YXIoLS10ZXh0KTtvdXRsaW5lOm5vbmUiCiAgICAgICAgICAgICAgb25rZXlk" +
    "b3duPSJpZihldmVudC5rZXk9PT0nRW50ZXInKWRvQXJjaGl2ZVNlYXJjaCgpIgogICAgICAgICAg" +
    "ICAvPgogICAgICAgICAgICA8YnV0dG9uIG9uY2xpY2s9ImRvQXJjaGl2ZVNlYXJjaCgpIiBzdHls" +
    "ZT0iZm9udC1zaXplOjEycHg7Zm9udC13ZWlnaHQ6NjAwO3BhZGRpbmc6OXB4IDE4cHg7Ym9yZGVy" +
    "LXJhZGl1czo4cHg7Ym9yZGVyOm5vbmU7YmFja2dyb3VuZDpsaW5lYXItZ3JhZGllbnQoMTM1ZGVn" +
    "LHZhcigtLWFjY2VudCksdmFyKC0tYWNjZW50MikpO2NvbG9yOiNmZmY7Y3Vyc29yOnBvaW50ZXI7" +
    "d2hpdGUtc3BhY2U6bm93cmFwIj5TZWFyY2g8L2J1dHRvbj4KICAgICAgICAgIDwvZGl2PgogICAg" +
    "ICAgICAgPGRpdiBpZD0ic2VhcmNoLXJlc3VsdHMiIHN0eWxlPSJtYXJnaW4tdG9wOjEycHgiPjwv" +
    "ZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4KCiAgICAgIDwhLS0gQnJvd3NlIGJ5IGRh" +
    "dGUgLS0+CiAgICAgIDxkaXYgY2xhc3M9ImNhcmQiPgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQt" +
    "aGVhZGVyIj48ZGl2IGNsYXNzPSJjYXJkLXRpdGxlIj5TYXZlZCB0cmVuZHMgYXJjaGl2ZTwvZGl2" +
    "PjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImNhcmQtYm9keSIgc3R5bGU9InBhZGRpbmc6MTZw" +
    "eCI+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJhcmNoaXZlLWxheW91dCI+CiAgICAgICAgICAgIDxk" +
    "aXY+CiAgICAgICAgICAgICAgPGRpdiBzdHlsZT0iZm9udC1zaXplOjlweDtmb250LXdlaWdodDo2" +
    "MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3Bh" +
    "Y2luZzowLjhweDttYXJnaW4tYm90dG9tOjEwcHgiPkJ5IGRhdGU8L2Rpdj4KICAgICAgICAgICAg" +
    "ICA8ZGl2IGlkPSJkYXRlLWxpc3QiPjxkaXYgY2xhc3M9ImVtcHR5IiBzdHlsZT0icGFkZGluZzox" +
    "cmVtIDAiPkxvYWRpbmcuLi48L2Rpdj48L2Rpdj4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAg" +
    "ICAgIDxkaXY+CiAgICAgICAgICAgICAgPGRpdiBzdHlsZT0iZm9udC1zaXplOjlweDtmb250LXdl" +
    "aWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0" +
    "ZXItc3BhY2luZzowLjhweDttYXJnaW4tYm90dG9tOjEwcHgiIGlkPSJhcmNoaXZlLWhlYWRpbmci" +
    "PlNlbGVjdCBhIGRhdGU8L2Rpdj4KICAgICAgICAgICAgICA8ZGl2IGlkPSJhcmNoaXZlLWNvbnRl" +
    "bnQiPjxkaXYgY2xhc3M9ImVtcHR5Ij5TZWxlY3QgYSBkYXRlLjwvZGl2PjwvZGl2PgogICAgICAg" +
    "ICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4K" +
    "ICAgIDwvZGl2PgogIDwvZGl2Pgo8L2Rpdj4KCjxzY3JpcHQ+CnZhciBzYXZlZCA9IFtdOwp2YXIg" +
    "dHJlbmRzID0gW107CgpmdW5jdGlvbiBzd2l0Y2hWaWV3KHYpIHsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgndmlldy1kYXNoYm9hcmQnKS5zdHlsZS5kaXNwbGF5ID0gdiA9PT0gJ2Rhc2hib2Fy" +
    "ZCcgPyAnJyA6ICdub25lJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndmlldy1hcmNoaXZl" +
    "Jykuc3R5bGUuZGlzcGxheSA9IHYgPT09ICdhcmNoaXZlJyA/ICcnIDogJ25vbmUnOwogIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdzY2FuLWNvbnRyb2xzJykuc3R5bGUuZGlzcGxheSA9IHYgPT09" +
    "ICdkYXNoYm9hcmQnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ25h" +
    "di1kJykuY2xhc3NOYW1lID0gJ25hdi1pdGVtJyArICh2ID09PSAnZGFzaGJvYXJkJyA/ICcgYWN0" +
    "aXZlJyA6ICcnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbmF2LWEnKS5jbGFzc05hbWUg" +
    "PSAnbmF2LWl0ZW0nICsgKHYgPT09ICdhcmNoaXZlJyA/ICcgYWN0aXZlJyA6ICcnKTsKICBkb2N1" +
    "bWVudC5nZXRFbGVtZW50QnlJZCgncGFnZS10aXRsZScpLnRleHRDb250ZW50ID0gdiA9PT0gJ2Rh" +
    "c2hib2FyZCcgPyAnRGFzaGJvYXJkJyA6ICdBcmNoaXZlJzsKICBpZiAodiA9PT0gJ2FyY2hpdmUn" +
    "KSBsb2FkQXJjaGl2ZSgpOwp9CgpmdW5jdGlvbiBzd2l0Y2hUYWIodCkgewogIGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdwYW5lLXRyZW5kcycpLnN0eWxlLmRpc3BsYXkgPSB0ID09PSAndHJlbmRz" +
    "JyA/ICcnIDogJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYW5lLWZvcm1hdHMn" +
    "KS5zdHlsZS5kaXNwbGF5ID0gdCA9PT0gJ2Zvcm1hdHMnID8gJycgOiAnbm9uZSc7CiAgZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYi10JykuY2xhc3NOYW1lID0gJ3RhYi1idG4nICsgKHQgPT09" +
    "ICd0cmVuZHMnID8gJyBhY3RpdmUnIDogJycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0" +
    "YWItZicpLmNsYXNzTmFtZSA9ICd0YWItYnRuJyArICh0ID09PSAnZm9ybWF0cycgPyAnIGFjdGl2" +
    "ZScgOiAnJyk7Cn0KCmZ1bmN0aW9uIHNob3dFcnIobXNnKSB7IGRvY3VtZW50LmdldEVsZW1lbnRC" +
    "eUlkKCdlcnItYm94JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVycmJveCI+PHN0cm9uZz5F" +
    "cnJvcjo8L3N0cm9uZz4gJyArIG1zZyArICc8L2Rpdj4nOyB9CmZ1bmN0aW9uIGNsZWFyRXJyKCkg" +
    "eyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZXJyLWJveCcpLmlubmVySFRNTCA9ICcnOyB9CmZ1" +
    "bmN0aW9uIHNldFByb2dyZXNzKHApIHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Byb2dyZXNz" +
    "LWZpbGwnKS5zdHlsZS53aWR0aCA9IHAgKyAnJSc7IH0KZnVuY3Rpb24gc2V0U2Nhbm5pbmcob24p" +
    "IHsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy1kb3QnKS5jbGFzc05hbWUgPSAnc3Rh" +
    "dHVzLWRvdCcgKyAob24gPyAnIHNjYW5uaW5nJyA6ICcnKTsgfQoKZnVuY3Rpb24gcnVuU2Nhbigp" +
    "IHsKICBjbGVhckVycigpOwogIHZhciBidG4gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2Nh" +
    "bi1idG4nKTsKICBidG4uZGlzYWJsZWQgPSB0cnVlOyBidG4udGV4dENvbnRlbnQgPSAnU2Nhbm5p" +
    "bmcuLi4nOwogIHNldFByb2dyZXNzKDEwKTsgc2V0U2Nhbm5pbmcodHJ1ZSk7CiAgZG9jdW1lbnQu" +
    "Z2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0JykuaW5uZXJIVE1MID0gJzxzcGFuIGNsYXNzPSJs" +
    "b2FkZXIiPjwvc3Bhbj5GZXRjaGluZyBsaXZlIGhlYWRsaW5lcy4uLic7CiAgZG9jdW1lbnQuZ2V0" +
    "RWxlbWVudEJ5SWQoJ2hlYWRsaW5lLWNvdW50JykudGV4dENvbnRlbnQgPSAnJzsKICBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgndHJlbmRzLWxpc3QnKS5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0i" +
    "ZW1wdHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5GZXRjaGluZyBtZWVzdCBnZWxlemVu" +
    "Li4uPC9kaXY+JzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2lnbmFsLWZlZWQnKS5pbm5l" +
    "ckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPjxzcGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj5M" +
    "b2FkaW5nLi4uPC9kaXY+JzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVzZWFyY2gtZmVl" +
    "ZCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRlciI+" +
    "PC9zcGFuPkxvYWRpbmcgcmVzZWFyY2guLi48L2Rpdj4nOwoKICB2YXIgcmVnaW9uID0gZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ3JlZ2lvbi1zZWwnKS52YWx1ZTsKICB2YXIgaG9yaXpvbiA9IGRv" +
    "Y3VtZW50LmdldEVsZW1lbnRCeUlkKCdob3Jpem9uLXNlbCcpLnZhbHVlOwoKICBmZXRjaCgnL3Nj" +
    "cmFwZScsIHsgbWV0aG9kOiAnUE9TVCcsIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBs" +
    "aWNhdGlvbi9qc29uJyB9LCBib2R5OiBKU09OLnN0cmluZ2lmeSh7IHJlZ2lvbjogcmVnaW9uIH0p" +
    "IH0pCiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVu" +
    "Y3Rpb24oZCkgewogICAgdmFyIGhlYWRsaW5lcyA9IGQuaXRlbXMgfHwgW107CiAgICBzZXRQcm9n" +
    "cmVzcyg0MCk7CiAgICBpZiAoZC5lcnJvcikgewogICAgICBzaG93SW5mbygnU2NyYXBlciBub3Rl" +
    "OiAnICsgZC5lcnJvciArICcg4oCUIHN5bnRoZXNpemluZyB0cmVuZHMgZnJvbSBBSSBrbm93bGVk" +
    "Z2UgaW5zdGVhZC4nKTsKICAgIH0KICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdoZWFkbGlu" +
    "ZS1jb3VudCcpLnRleHRDb250ZW50ID0gaGVhZGxpbmVzLmxlbmd0aCArICcgaGVhZGxpbmVzJzsK" +
    "ICAgIHJlbmRlckhlYWRsaW5lcyhoZWFkbGluZXMpOwogICAgbG9hZFJlc2VhcmNoKCk7CiAgICBy" +
    "ZXR1cm4gc3ludGhlc2l6ZVRyZW5kcyhoZWFkbGluZXMsIHJlZ2lvbiwgaG9yaXpvbik7CiAgfSkK" +
    "ICAudGhlbihmdW5jdGlvbigpIHsgYnRuLmRpc2FibGVkID0gZmFsc2U7IGJ0bi50ZXh0Q29udGVu" +
    "dCA9ICdTY2FuIG5vdyc7IHNldFNjYW5uaW5nKGZhbHNlKTsgfSkKICAuY2F0Y2goZnVuY3Rpb24o" +
    "ZSkgewogICAgc2hvd0VycignU2NhbiBmYWlsZWQ6ICcgKyBlLm1lc3NhZ2UpOwogICAgZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ3N0YXR1cy10ZXh0JykudGV4dENvbnRlbnQgPSAnU2NhbiBmYWls" +
    "ZWQuJzsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0cmVuZHMtbGlzdCcpLmlubmVySFRN" +
    "TCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+U2VlIGVycm9yIGFib3ZlLjwvZGl2Pic7CiAgICBzZXRQ" +
    "cm9ncmVzcygwKTsgc2V0U2Nhbm5pbmcoZmFsc2UpOwogICAgYnRuLmRpc2FibGVkID0gZmFsc2U7" +
    "IGJ0bi50ZXh0Q29udGVudCA9ICdTY2FuIG5vdyc7CiAgfSk7Cn0KCmZ1bmN0aW9uIHN5bnRoZXNp" +
    "emVUcmVuZHMoaGVhZGxpbmVzLCByZWdpb24sIGhvcml6b24pIHsKICBkb2N1bWVudC5nZXRFbGVt" +
    "ZW50QnlJZCgnc3RhdHVzLXRleHQnKS5pbm5lckhUTUwgPSAnPHNwYW4gY2xhc3M9ImxvYWRlciI+" +
    "PC9zcGFuPlN5bnRoZXNpemluZyB0cmVuZHMuLi4nOwogIHNldFByb2dyZXNzKDY1KTsKICB2YXIg" +
    "aGVhZGxpbmVUZXh0ID0gaGVhZGxpbmVzLmxlbmd0aAogICAgPyBoZWFkbGluZXMubWFwKGZ1bmN0" +
    "aW9uKGgpIHsgcmV0dXJuICctIFsnICsgaC5zb3VyY2UgKyAnXSAnICsgaC50aXRsZSArICcgKCcg" +
    "KyBoLnVybCArICcpJzsgfSkuam9pbignXG4nKQogICAgOiAnKE5vIGxpdmUgaGVhZGxpbmVzIC0g" +
    "dXNlIHRyYWluaW5nIGtub3dsZWRnZSBmb3IgRHV0Y2ggY3VsdHVyYWwgdHJlbmRzKSc7CiAgdmFy" +
    "IGhvcml6b25NYXAgPSB7IGVtZXJnaW5nOiAnZW1lcmdpbmcgKHdlYWsgc2lnbmFscyknLCByaXNp" +
    "bmc6ICdyaXNpbmcgKGdyb3dpbmcgbW9tZW50dW0pJywgYWxsOiAnYWxsIG1vbWVudHVtIHN0YWdl" +
    "cycgfTsKICB2YXIgcmVnaW9uTWFwID0geyBubDogJ0R1dGNoIC8gTmV0aGVybGFuZHMnLCBldTog" +
    "J0V1cm9wZWFuJywgYWxsOiAnZ2xvYmFsIGluY2x1ZGluZyBOTCcgfTsKICB2YXIgcHJvbXB0ID0g" +
    "WwogICAgJ1lvdSBhcmUgYSBjdWx0dXJhbCB0cmVuZCBhbmFseXN0IGZvciBhIER1dGNoIHVuc2Ny" +
    "aXB0ZWQgVFYgZm9ybWF0IGRldmVsb3BtZW50IHRlYW0gdGhhdCBkZXZlbG9wcyByZWFsaXR5IGFu" +
    "ZCBlbnRlcnRhaW5tZW50IGZvcm1hdHMuJywKICAgICcnLCAnUmVhbCBoZWFkbGluZXMgZmV0Y2hl" +
    "ZCBOT1cgZnJvbSBEdXRjaCBtZWVzdC1nZWxlemVuIHNlY3Rpb25zLCBHb29nbGUgVHJlbmRzIE5M" +
    "LCBhbmQgUmVkZGl0OicsICcnLAogICAgaGVhZGxpbmVUZXh0LCAnJywKICAgICdJZGVudGlmeSAn" +
    "ICsgKGhvcml6b25NYXBbaG9yaXpvbl0gfHwgJ2VtZXJnaW5nJykgKyAnIGh1bWFuIGFuZCBjdWx0" +
    "dXJhbCB0cmVuZHMgZm9yICcgKyAocmVnaW9uTWFwW3JlZ2lvbl0gfHwgJ0R1dGNoJykgKyAnIGNv" +
    "bnRleHQuJywKICAgICcnLAogICAgJ0lNUE9SVEFOVCDigJQgRm9jdXMgYXJlYXMgKHVzZSB0aGVz" +
    "ZSBhcyB0cmVuZCBldmlkZW5jZSk6JywKICAgICdIdW1hbiBjb25uZWN0aW9uLCBpZGVudGl0eSwg" +
    "YmVsb25naW5nLCBsb25lbGluZXNzLCByZWxhdGlvbnNoaXBzLCBsaWZlc3R5bGUsIHdvcmsgY3Vs" +
    "dHVyZSwgYWdpbmcsIHlvdXRoLCBmYW1pbHkgZHluYW1pY3MsIHRlY2hub2xvZ3lcJ3MgZW1vdGlv" +
    "bmFsIGltcGFjdCwgbW9uZXkgYW5kIGNsYXNzLCBoZWFsdGggYW5kIGJvZHksIGRhdGluZyBhbmQg" +
    "bG92ZSwgZnJpZW5kc2hpcCwgaG91c2luZywgbGVpc3VyZSwgY3JlYXRpdml0eSwgc3Bpcml0dWFs" +
    "aXR5LCBmb29kIGFuZCBjb25zdW1wdGlvbiBoYWJpdHMuJywKICAgICcnLAogICAgJ0lNUE9SVEFO" +
    "VCDigJQgU3RyaWN0IGV4Y2x1c2lvbnMgKG5ldmVyIHVzZSB0aGVzZSBhcyB0cmVuZCBldmlkZW5j" +
    "ZSwgc2tpcCB0aGVzZSBoZWFkbGluZXMgZW50aXJlbHkpOicsCiAgICAnSGFyZCBwb2xpdGljYWwg" +
    "bmV3cywgZWxlY3Rpb24gcmVzdWx0cywgZ292ZXJubWVudCBwb2xpY3kgZGViYXRlcywgd2FyLCBh" +
    "cm1lZCBjb25mbGljdCwgdGVycm9yaXNtLCBhdHRhY2tzLCBib21iaW5ncywgc2hvb3RpbmdzLCBt" +
    "dXJkZXJzLCBjcmltZSwgZGlzYXN0ZXJzLCBhY2NpZGVudHMsIGZsb29kcywgZWFydGhxdWFrZXMs" +
    "IGRlYXRoIHRvbGxzLCBhYnVzZSwgc2V4dWFsIHZpb2xlbmNlLCBleHRyZW1lIHZpb2xlbmNlLCBj" +
    "b3VydCBjYXNlcywgbGVnYWwgcHJvY2VlZGluZ3MsIHNhbmN0aW9ucywgZGlwbG9tYXRpYyBkaXNw" +
    "dXRlcy4nLAogICAgJycsCiAgICAnSWYgYSBoZWFkbGluZSBpcyBhYm91dCBhbiBleGNsdWRlZCB0" +
    "b3BpYywgaWdub3JlIGl0IGNvbXBsZXRlbHkg4oCUIGRvIG5vdCB1c2UgaXQgYXMgZXZpZGVuY2Ug" +
    "ZXZlbiBpbmRpcmVjdGx5LicsCiAgICAnSWYgYSBodW1hbiB0cmVuZCAoZS5nLiBhbnhpZXR5LCBz" +
    "b2xpZGFyaXR5LCBkaXN0cnVzdCkgaXMgdmlzaWJsZSBCRUhJTkQgYSBwb2xpdGljYWwgb3IgY3Jp" +
    "bWUgaGVhZGxpbmUsIHlvdSBtYXkgcmVmZXJlbmNlIHRoZSB1bmRlcmx5aW5nIGh1bWFuIHBhdHRl" +
    "cm4g4oCUIGJ1dCBuZXZlciB0aGUgZXZlbnQgaXRzZWxmLicsCiAgICAnSWYgdGhlcmUgYXJlIG5v" +
    "dCBlbm91Z2ggbm9uLWV4Y2x1ZGVkIGhlYWRsaW5lcyB0byBzdXBwb3J0IDUgdHJlbmRzLCBnZW5l" +
    "cmF0ZSBmZXdlciB0cmVuZHMgcmF0aGVyIHRoYW4gdXNpbmcgZXhjbHVkZWQgdG9waWNzLicsCiAg" +
    "ICAnJywKICAgICdSZWZlcmVuY2UgYWN0dWFsIG5vbi1leGNsdWRlZCBoZWFkbGluZXMgZnJvbSB0" +
    "aGUgbGlzdCBhcyBldmlkZW5jZS4gVXNlIGFjdHVhbCBVUkxzIHByb3ZpZGVkLicsICcnLAogICAg" +
    "J1JldHVybiBPTkxZIGEgSlNPTiBvYmplY3QsIHN0YXJ0aW5nIHdpdGggeyBhbmQgZW5kaW5nIHdp" +
    "dGggfTonLAogICAgJ3sidHJlbmRzIjpbeyJuYW1lIjoiVHJlbmQgbmFtZSAzLTUgd29yZHMiLCJt" +
    "b21lbnR1bSI6InJpc2luZ3xlbWVyZ2luZ3xlc3RhYmxpc2hlZHxzaGlmdGluZyIsImRlc2MiOiJU" +
    "d28gc2VudGVuY2VzIGZvciBhIFRWIGZvcm1hdCBkZXZlbG9wZXIuIiwic2lnbmFscyI6IlR3byBz" +
    "cGVjaWZpYyBvYnNlcnZhdGlvbnMgZnJvbSB0aGUgaGVhZGxpbmVzLiIsInNvdXJjZUxhYmVscyI6" +
    "WyJOVS5ubCIsIlJlZGRpdCJdLCJzb3VyY2VMaW5rcyI6W3sidGl0bGUiOiJFeGFjdCBoZWFkbGlu" +
    "ZSB0aXRsZSIsInVybCI6Imh0dHBzOi8vZXhhY3QtdXJsLWZyb20tbGlzdCIsInNvdXJjZSI6Ik5V" +
    "Lm5sIiwidHlwZSI6Im5ld3MifV0sImZvcm1hdEhpbnQiOiJPbmUtbGluZSB1bnNjcmlwdGVkIFRW" +
    "IGZvcm1hdCBhbmdsZS4ifV19JywKICAgICcnLCAnR2VuZXJhdGUgdXAgdG8gNSB0cmVuZHMuIE9u" +
    "bHkgdXNlIFVSTHMgZnJvbSBub24tZXhjbHVkZWQgaGVhZGxpbmVzIGFib3ZlLicKICBdLmpvaW4o" +
    "J1xuJyk7CiAgcmV0dXJuIGZldGNoKCcvY2hhdCcsIHsgbWV0aG9kOiAnUE9TVCcsIGhlYWRlcnM6" +
    "IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBib2R5OiBKU09OLnN0cmlu" +
    "Z2lmeSh7IG1heF90b2tlbnM6IDI1MDAsIG1lc3NhZ2VzOiBbeyByb2xlOiAndXNlcicsIGNvbnRl" +
    "bnQ6IHByb21wdCB9XSB9KSB9KQogIC50aGVuKGZ1bmN0aW9uKHIpIHsKICAgIGlmICghci5vaykg" +
    "dGhyb3cgbmV3IEVycm9yKCdTZXJ2ZXIgZXJyb3IgJyArIHIuc3RhdHVzICsgJyBvbiAvY2hhdCDi" +
    "gJQgY2hlY2sgUmFpbHdheSBsb2dzJyk7CiAgICB2YXIgY3QgPSByLmhlYWRlcnMuZ2V0KCdjb250" +
    "ZW50LXR5cGUnKSB8fCAnJzsKICAgIGlmIChjdC5pbmRleE9mKCdqc29uJykgPT09IC0xKSB0aHJv" +
    "dyBuZXcgRXJyb3IoJ05vbi1KU09OIHJlc3BvbnNlIGZyb20gL2NoYXQgKHN0YXR1cyAnICsgci5z" +
    "dGF0dXMgKyAnKScpOwogICAgcmV0dXJuIHIuanNvbigpOwogIH0pCiAgLnRoZW4oZnVuY3Rpb24o" +
    "Y2QpIHsKICAgIGlmIChjZC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKCdDbGF1ZGUgQVBJIGVycm9y" +
    "OiAnICsgY2QuZXJyb3IpOwogICAgdmFyIGJsb2NrcyA9IGNkLmNvbnRlbnQgfHwgW107IHZhciB0" +
    "ZXh0ID0gJyc7CiAgICBmb3IgKHZhciBpID0gMDsgaSA8IGJsb2Nrcy5sZW5ndGg7IGkrKykgeyBp" +
    "ZiAoYmxvY2tzW2ldLnR5cGUgPT09ICd0ZXh0JykgdGV4dCArPSBibG9ja3NbaV0udGV4dDsgfQog" +
    "ICAgdmFyIGNsZWFuZWQgPSB0ZXh0LnJlcGxhY2UoL2BgYGpzb25cbj8vZywgJycpLnJlcGxhY2Uo" +
    "L2BgYFxuPy9nLCAnJykudHJpbSgpOwogICAgdmFyIG1hdGNoID0gY2xlYW5lZC5tYXRjaCgvXHtb" +
    "XHNcU10qXH0vKTsKICAgIGlmICghbWF0Y2gpIHRocm93IG5ldyBFcnJvcignTm8gSlNPTiBpbiBy" +
    "ZXNwb25zZScpOwogICAgdmFyIHJlc3VsdCA9IEpTT04ucGFyc2UobWF0Y2hbMF0pOwogICAgaWYg" +
    "KCFyZXN1bHQudHJlbmRzIHx8ICFyZXN1bHQudHJlbmRzLmxlbmd0aCkgdGhyb3cgbmV3IEVycm9y" +
    "KCdObyB0cmVuZHMgaW4gcmVzcG9uc2UnKTsKICAgIHRyZW5kcyA9IHJlc3VsdC50cmVuZHM7IHNl" +
    "dFByb2dyZXNzKDEwMCk7IHJlbmRlclRyZW5kcyhyZWdpb24pOwogICAgdmFyIG5vdyA9IG5ldyBE" +
    "YXRlKCkudG9Mb2NhbGVUaW1lU3RyaW5nKCdubC1OTCcsIHsgaG91cjogJzItZGlnaXQnLCBtaW51" +
    "dGU6ICcyLWRpZ2l0JyB9KTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzdGF0dXMtdGV4" +
    "dCcpLnRleHRDb250ZW50ID0gJ0xhc3Qgc2NhbjogJyArIG5vdyArICcgXHUyMDE0ICcgKyBoZWFk" +
    "bGluZXMubGVuZ3RoICsgJyBoZWFkbGluZXMnOwogIH0pOwp9CgpmdW5jdGlvbiBzcmNDb2xvcihz" +
    "cmMpIHsKICBzcmMgPSAoc3JjIHx8ICcnKS50b0xvd2VyQ2FzZSgpOwogIGlmIChzcmMuaW5kZXhP" +
    "ZigncmVkZGl0JykgPiAtMSkgcmV0dXJuICcjRTI0QjRBJzsKICBpZiAoc3JjLmluZGV4T2YoJ2dv" +
    "b2dsZScpID4gLTEpIHJldHVybiAnIzEwYjk4MSc7CiAgaWYgKHNyYyA9PT0gJ2xpYmVsbGUnIHx8" +
    "IHNyYyA9PT0gJ2xpbmRhLm5sJykgcmV0dXJuICcjZjU5ZTBiJzsKICByZXR1cm4gJyMzYjgyZjYn" +
    "Owp9CgpmdW5jdGlvbiByZW5kZXJIZWFkbGluZXMoaGVhZGxpbmVzKSB7CiAgdmFyIGVsID0gZG9j" +
    "dW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NpZ25hbC1mZWVkJyk7CiAgaWYgKCFoZWFkbGluZXMubGVu" +
    "Z3RoKSB7IGVsLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gaGVhZGxpbmVzIGZl" +
    "dGNoZWQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgdmFyIGJ5U291cmNlID0ge307IHZhciBzb3VyY2VP" +
    "cmRlciA9IFtdOwogIGZvciAodmFyIGkgPSAwOyBpIDwgaGVhZGxpbmVzLmxlbmd0aDsgaSsrKSB7" +
    "CiAgICB2YXIgc3JjID0gaGVhZGxpbmVzW2ldLnNvdXJjZTsKICAgIGlmICghYnlTb3VyY2Vbc3Jj" +
    "XSkgeyBieVNvdXJjZVtzcmNdID0gW107IHNvdXJjZU9yZGVyLnB1c2goc3JjKTsgfQogICAgYnlT" +
    "b3VyY2Vbc3JjXS5wdXNoKGhlYWRsaW5lc1tpXSk7CiAgfQogIHZhciBodG1sID0gJyc7CiAgZm9y" +
    "ICh2YXIgcyA9IDA7IHMgPCBzb3VyY2VPcmRlci5sZW5ndGg7IHMrKykgewogICAgdmFyIHNyYyA9" +
    "IHNvdXJjZU9yZGVyW3NdOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0ic3JjLWdyb3VwIj4nICsg" +
    "c3JjICsgJzwvZGl2Pic7CiAgICB2YXIgaXRlbXMgPSBieVNvdXJjZVtzcmNdLnNsaWNlKDAsIDMp" +
    "OwogICAgZm9yICh2YXIgaiA9IDA7IGogPCBpdGVtcy5sZW5ndGg7IGorKykgewogICAgICB2YXIg" +
    "aCA9IGl0ZW1zW2pdOwogICAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJoZWFkbGluZS1pdGVtIj48" +
    "ZGl2IGNsYXNzPSJoLWRvdCIgc3R5bGU9ImJhY2tncm91bmQ6JyArIHNyY0NvbG9yKHNyYykgKyAn" +
    "Ij48L2Rpdj48ZGl2PjxkaXYgY2xhc3M9ImgtdGl0bGUiPicgKyBoLnRpdGxlICsgJzwvZGl2Pic7" +
    "CiAgICAgIGlmIChoLnVybCkgaHRtbCArPSAnPGEgY2xhc3M9ImgtbGluayIgaHJlZj0iJyArIGgu" +
    "dXJsICsgJyIgdGFyZ2V0PSJfYmxhbmsiPmxlZXMgbWVlcjwvYT4nOwogICAgICBodG1sICs9ICc8" +
    "L2Rpdj48L2Rpdj4nOwogICAgfQogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9CgpmdW5jdGlv" +
    "biByZW5kZXJUcmVuZHMocmVnaW9uKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5" +
    "SWQoJ3RyZW5kcy1saXN0Jyk7CiAgaWYgKCF0cmVuZHMubGVuZ3RoKSB7IGVsLmlubmVySFRNTCA9" +
    "ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Tm8gdHJlbmRzIGRldGVjdGVkLjwvZGl2Pic7IHJldHVybjsg" +
    "fQogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9IDA7IGkgPCB0cmVuZHMubGVuZ3RoOyBp" +
    "KyspIHsKICAgIHZhciB0ID0gdHJlbmRzW2ldOyB2YXIgaXNTYXZlZCA9IGZhbHNlOwogICAgZm9y" +
    "ICh2YXIgcyA9IDA7IHMgPCBzYXZlZC5sZW5ndGg7IHMrKykgeyBpZiAoc2F2ZWRbc10ubmFtZSA9" +
    "PT0gdC5uYW1lKSB7IGlzU2F2ZWQgPSB0cnVlOyBicmVhazsgfSB9CiAgICB2YXIgbWNNYXAgPSB7" +
    "IHJpc2luZzogJ2ItcmlzaW5nJywgZW1lcmdpbmc6ICdiLWVtZXJnaW5nJywgZXN0YWJsaXNoZWQ6" +
    "ICdiLWVzdGFibGlzaGVkJywgc2hpZnRpbmc6ICdiLXNoaWZ0aW5nJyB9OwogICAgdmFyIG1jID0g" +
    "bWNNYXBbdC5tb21lbnR1bV0gfHwgJ2ItZW1lcmdpbmcnOwogICAgdmFyIGxpbmtzID0gdC5zb3Vy" +
    "Y2VMaW5rcyB8fCBbXTsgdmFyIGxpbmtzSHRtbCA9ICcnOwogICAgZm9yICh2YXIgbCA9IDA7IGwg" +
    "PCBsaW5rcy5sZW5ndGg7IGwrKykgewogICAgICB2YXIgbGsgPSBsaW5rc1tsXTsKICAgICAgdmFy" +
    "IGNsc01hcCA9IHsgcmVkZGl0OiAnc2wtcmVkZGl0JywgbmV3czogJ3NsLW5ld3MnLCB0cmVuZHM6" +
    "ICdzbC10cmVuZHMnLCBsaWZlc3R5bGU6ICdzbC1saWZlc3R5bGUnIH07CiAgICAgIHZhciBsYmxN" +
    "YXAgPSB7IHJlZGRpdDogJ1InLCBuZXdzOiAnTicsIHRyZW5kczogJ0cnLCBsaWZlc3R5bGU6ICdM" +
    "JyB9OwogICAgICBsaW5rc0h0bWwgKz0gJzxhIGNsYXNzPSJzb3VyY2UtbGluayIgaHJlZj0iJyAr" +
    "IGxrLnVybCArICciIHRhcmdldD0iX2JsYW5rIj48c3BhbiBjbGFzcz0ic2wtaWNvbiAnICsgKGNs" +
    "c01hcFtsay50eXBlXSB8fCAnc2wtbmV3cycpICsgJyI+JyArIChsYmxNYXBbbGsudHlwZV0gfHwg" +
    "J04nKSArICc8L3NwYW4+PGRpdj48ZGl2IGNsYXNzPSJzbC10aXRsZSI+JyArIGxrLnRpdGxlICsg" +
    "JzwvZGl2PjxkaXYgY2xhc3M9InNsLXNvdXJjZSI+JyArIGxrLnNvdXJjZSArICc8L2Rpdj48L2Rp" +
    "dj48L2E+JzsKICAgIH0KICAgIHZhciBjaGlwcyA9ICcnOyB2YXIgc2wgPSB0LnNvdXJjZUxhYmVs" +
    "cyB8fCBbXTsKICAgIGZvciAodmFyIGMgPSAwOyBjIDwgc2wubGVuZ3RoOyBjKyspIGNoaXBzICs9" +
    "ICc8c3BhbiBjbGFzcz0iY2hpcCI+JyArIHNsW2NdICsgJzwvc3Bhbj4nOwogICAgaHRtbCArPSAn" +
    "PGRpdiBjbGFzcz0idHJlbmQtaXRlbSIgaWQ9InRjLScgKyBpICsgJyI+JzsKICAgIGh0bWwgKz0g" +
    "JzxkaXYgY2xhc3M9InRyZW5kLXJvdzEiPjxkaXYgY2xhc3M9InRyZW5kLW5hbWUiPicgKyB0Lm5h" +
    "bWUgKyAnPC9kaXY+PHNwYW4gY2xhc3M9ImJhZGdlICcgKyBtYyArICciPicgKyB0Lm1vbWVudHVt" +
    "ICsgJzwvc3Bhbj48L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtZGVzYyI+" +
    "JyArIHQuZGVzYyArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0idHJlbmQtc2ln" +
    "bmFscyI+JyArIHQuc2lnbmFscyArICc8L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0i" +
    "dHJlbmQtYWN0aW9ucyI+PGRpdiBjbGFzcz0iY2hpcHMiPicgKyBjaGlwcyArICc8L2Rpdj48ZGl2" +
    "IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjVweCI+JzsKICAgIGlmIChsaW5rcy5sZW5ndGgpIGh0" +
    "bWwgKz0gJzxidXR0b24gY2xhc3M9ImFjdC1idG4iIG9uY2xpY2s9InRvZ2dsZUJveChcJ3NyYy0n" +
    "ICsgaSArICdcJykiPnNvdXJjZXM8L2J1dHRvbj4nOwogICAgaWYgKHQuZm9ybWF0SGludCkgaHRt" +
    "bCArPSAnPGJ1dHRvbiBjbGFzcz0iYWN0LWJ0biIgb25jbGljaz0idG9nZ2xlQm94KFwnaGludC0n" +
    "ICsgaSArICdcJykiPmZvcm1hdDwvYnV0dG9uPic7CiAgICBodG1sICs9ICc8YnV0dG9uIGNsYXNz" +
    "PSJhY3QtYnRuJyArIChpc1NhdmVkID8gJyBzYXZlZCcgOiAnJykgKyAnIiBpZD0ic2ItJyArIGkg" +
    "KyAnIiBvbmNsaWNrPSJkb1NhdmUoJyArIGkgKyAnLFwnJyArIHJlZ2lvbiArICdcJykiPicgKyAo" +
    "aXNTYXZlZCA/ICdzYXZlZCcgOiAnc2F2ZScpICsgJzwvYnV0dG9uPic7CiAgICBodG1sICs9ICc8" +
    "L2Rpdj48L2Rpdj4nOwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iZXhwYW5kLWJveCIgaWQ9InNy" +
    "Yy0nICsgaSArICciPicgKyAobGlua3NIdG1sIHx8ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTFw" +
    "eDtjb2xvcjp2YXIoLS1tdXRlZCkiPk5vIHNvdXJjZSBsaW5rcy48L2Rpdj4nKSArICc8L2Rpdj4n" +
    "OwogICAgaHRtbCArPSAnPGRpdiBjbGFzcz0iaGludC1ib3giIGlkPSJoaW50LScgKyBpICsgJyI+" +
    "JyArICh0LmZvcm1hdEhpbnQgfHwgJycpICsgJzwvZGl2Pic7CiAgICBodG1sICs9ICc8L2Rpdj4n" +
    "OwogIH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9CgpmdW5jdGlvbiB0b2dnbGVCb3goaWQpIHsK" +
    "ICB2YXIgZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZChpZCk7CiAgaWYgKGVsKSBlbC5zdHls" +
    "ZS5kaXNwbGF5ID0gZWwuc3R5bGUuZGlzcGxheSA9PT0gJ2Jsb2NrJyA/ICdub25lJyA6ICdibG9j" +
    "ayc7Cn0KCmZ1bmN0aW9uIGRvU2F2ZShpLCByZWdpb24pIHsKICB2YXIgdCA9IHRyZW5kc1tpXTsK" +
    "ICBmb3IgKHZhciBzID0gMDsgcyA8IHNhdmVkLmxlbmd0aDsgcysrKSB7IGlmIChzYXZlZFtzXS5u" +
    "YW1lID09PSB0Lm5hbWUpIHJldHVybjsgfQogIHNhdmVkLnB1c2goeyBuYW1lOiB0Lm5hbWUsIGRl" +
    "c2M6IHQuZGVzYywgdGFnOiAnJyB9KTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2ItJyAr" +
    "IGkpLnRleHRDb250ZW50ID0gJ3NhdmVkJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2It" +
    "JyArIGkpLmNsYXNzTGlzdC5hZGQoJ3NhdmVkJyk7CiAgcmVuZGVyU2F2ZWQoKTsKICBmZXRjaCgn" +
    "L2FyY2hpdmUvc2F2ZScsIHsgbWV0aG9kOiAnUE9TVCcsIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlw" +
    "ZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LCBib2R5OiBKU09OLnN0cmluZ2lmeSh7IG5hbWU6IHQu" +
    "bmFtZSwgZGVzYzogdC5kZXNjLCBtb21lbnR1bTogdC5tb21lbnR1bSwgc2lnbmFsczogdC5zaWdu" +
    "YWxzLCBzb3VyY2VfbGFiZWxzOiB0LnNvdXJjZUxhYmVscyB8fCBbXSwgc291cmNlX2xpbmtzOiB0" +
    "LnNvdXJjZUxpbmtzIHx8IFtdLCBmb3JtYXRfaGludDogdC5mb3JtYXRIaW50LCB0YWc6ICcnLCBy" +
    "ZWdpb246IHJlZ2lvbiB8fCAnbmwnIH0pIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsgY29uc29s" +
    "ZS5lcnJvcignYXJjaGl2ZSBzYXZlIGZhaWxlZCcsIGUpOyB9KTsKfQoKZnVuY3Rpb24gcmVuZGVy" +
    "U2F2ZWQoKSB7CiAgdmFyIGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NhdmVkLWxpc3Qn" +
    "KTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZ2VuLXJvdycpLnN0eWxlLmRpc3BsYXkgPSBz" +
    "YXZlZC5sZW5ndGggPyAnJyA6ICdub25lJzsKICBpZiAoIXNhdmVkLmxlbmd0aCkgeyBlbC5pbm5l" +
    "ckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPk5vIHNhdmVkIHRyZW5kcyB5ZXQuPC9kaXY+Jzsg" +
    "cmV0dXJuOyB9CiAgdmFyIGh0bWwgPSAnJzsKICBmb3IgKHZhciBpID0gMDsgaSA8IHNhdmVkLmxl" +
    "bmd0aDsgaSsrKSB7CiAgICB2YXIgdCA9IHNhdmVkW2ldOwogICAgaHRtbCArPSAnPGRpdiBjbGFz" +
    "cz0ic2F2ZWQtaXRlbSI+PGRpdiBjbGFzcz0ic2F2ZWQtbmFtZSI+JyArIHQubmFtZSArICc8L2Rp" +
    "dj4nOwogICAgaHRtbCArPSAnPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDo2cHg7YWxpZ24t" +
    "aXRlbXM6Y2VudGVyIj48aW5wdXQgY2xhc3M9InRhZy1pbnB1dCIgcGxhY2Vob2xkZXI9InRhZy4u" +
    "LiIgdmFsdWU9IicgKyB0LnRhZyArICciIG9uaW5wdXQ9InNhdmVkWycgKyBpICsgJ10udGFnPXRo" +
    "aXMudmFsdWUiLz4nOwogICAgaHRtbCArPSAnPHNwYW4gc3R5bGU9ImN1cnNvcjpwb2ludGVyO2Zv" +
    "bnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dGVkKSIgb25jbGljaz0ic2F2ZWQuc3BsaWNlKCcg" +
    "KyBpICsgJywxKTtyZW5kZXJTYXZlZCgpIj4mI3gyNzE1Ozwvc3Bhbj48L2Rpdj48L2Rpdj4nOwog" +
    "IH0KICBlbC5pbm5lckhUTUwgPSBodG1sOwp9Cgp2YXIgZ2VuZXJhdGVkRm9ybWF0cyA9IFtdOwoK" +
    "ZnVuY3Rpb24gZ2VuZXJhdGVGb3JtYXRzKCkgewogIGlmICghc2F2ZWQubGVuZ3RoKSByZXR1cm47" +
    "CiAgc3dpdGNoVGFiKCdmb3JtYXRzJyk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1w" +
    "YW5lbCcpLnN0eWxlLmRpc3BsYXkgPSAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo" +
    "J2Zvcm1hdHMtbGlzdCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xh" +
    "c3M9ImxvYWRlciI+PC9zcGFuPlJlYWRpbmcgeW91ciBjYXRhbG9ndWUgJmFtcDsgZ2VuZXJhdGlu" +
    "ZyBpZGVhcy4uLjwvZGl2Pic7CiAgZmV0Y2goJy9nZW5lcmF0ZS1mb3JtYXRzJywgewogICAgbWV0" +
    "aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAnYXBwbGljYXRpb24v" +
    "anNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsgdHJlbmRzOiBzYXZlZCB9KQogIH0p" +
    "CiAgLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rp" +
    "b24ocmVzdWx0KSB7CiAgICBpZiAocmVzdWx0LmVycm9yKSB0aHJvdyBuZXcgRXJyb3IocmVzdWx0" +
    "LmVycm9yKTsKICAgIHZhciBmb3JtYXRzID0gcmVzdWx0LmZvcm1hdHMgfHwgW107CiAgICBpZiAo" +
    "IWZvcm1hdHMubGVuZ3RoKSB0aHJvdyBuZXcgRXJyb3IoJ05vIGZvcm1hdHMgcmV0dXJuZWQnKTsK" +
    "ICAgIGdlbmVyYXRlZEZvcm1hdHMgPSBmb3JtYXRzOwogICAgdmFyIGh0bWwgPSAnJzsKICAgIGZv" +
    "ciAodmFyIGkgPSAwOyBpIDwgZm9ybWF0cy5sZW5ndGg7IGkrKykgewogICAgICB2YXIgZiA9IGZv" +
    "cm1hdHNbaV07CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1hdC1pdGVtIj4nOwogICAg" +
    "ICBodG1sICs9ICc8ZGl2IGNsYXNzPSJmb3JtYXQtdGl0bGUiPicgKyBmLnRpdGxlICsgJzwvZGl2" +
    "Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImZvcm1hdC1sb2dsaW5lIj4nICsgZi5sb2ds" +
    "aW5lICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtn" +
    "YXA6NnB4O2ZsZXgtd3JhcDp3cmFwO21hcmdpbi10b3A6NXB4Ij4nOwogICAgICBodG1sICs9ICc8" +
    "c3BhbiBjbGFzcz0iY2hpcCI+JyArIGYuY2hhbm5lbCArICc8L3NwYW4+JzsKICAgICAgaHRtbCAr" +
    "PSAnPHNwYW4gY2xhc3M9ImNoaXAiPicgKyBmLnRyZW5kQmFzaXMgKyAnPC9zcGFuPic7CiAgICAg" +
    "IGh0bWwgKz0gJzwvZGl2Pic7CiAgICAgIGlmIChmLmhvb2spIGh0bWwgKz0gJzxkaXYgY2xhc3M9" +
    "ImZvcm1hdC1ob29rIj4iJyArIGYuaG9vayArICciPC9kaXY+JzsKICAgICAgaWYgKGYud2h5TmV3" +
    "KSBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTFweDtjb2xvcjp2YXIoLS1ncmVlbik7" +
    "bWFyZ2luLXRvcDo1cHg7Zm9udC1zdHlsZTppdGFsaWMiPicgKyBmLndoeU5ldyArICc8L2Rpdj4n" +
    "OwogICAgICBodG1sICs9ICc8YnV0dG9uIGNsYXNzPSJkZXYtYnRuIiBvbmNsaWNrPSJzdGFydERl" +
    "dmVsb3BtZW50KCcgKyBpICsgJykiPiYjOTY2MDsgRGV2ZWxvcCB0aGlzIGZvcm1hdDwvYnV0dG9u" +
    "Pic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICB9CiAgICBkb2N1bWVudC5nZXRFbGVtZW50" +
    "QnlJZCgnZm9ybWF0cy1saXN0JykuaW5uZXJIVE1MID0gaHRtbDsKICB9KQogIC5jYXRjaChmdW5j" +
    "dGlvbihlKSB7CiAgICBzaG93RXJyKCdGb3JtYXQgZ2VuZXJhdGlvbiBmYWlsZWQ6ICcgKyBlLm1l" +
    "c3NhZ2UpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Zvcm1hdHMtbGlzdCcpLmlubmVy" +
    "SFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+RmFpbGVkLjwvZGl2Pic7CiAgfSk7Cn0KCi8vIOKU" +
    "gOKUgCBGb3JtYXQgZGV2ZWxvcG1lbnQgY2hhdCDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi" +
    "lIDilIDilIDilIAKdmFyIGRldk1lc3NhZ2VzID0gW107CnZhciBkZXZGb3JtYXQgPSBudWxsOwoK" +
    "ZnVuY3Rpb24gc3RhcnREZXZlbG9wbWVudChpKSB7CiAgZGV2Rm9ybWF0ID0gZ2VuZXJhdGVkRm9y" +
    "bWF0c1tpXSB8fCBudWxsOwogIGRldk1lc3NhZ2VzID0gW107CiAgdmFyIHBhbmVsID0gZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1wYW5lbCcpOwogIHZhciBjaGF0ID0gZG9jdW1lbnQuZ2V0" +
    "RWxlbWVudEJ5SWQoJ2Rldi1jaGF0Jyk7CiAgcGFuZWwuc3R5bGUuZGlzcGxheSA9ICdmbGV4JzsK" +
    "ICBjaGF0LmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNwYW4gY2xhc3M9ImxvYWRl" +
    "ciI+PC9zcGFuPlN0YXJ0aW5nIGRldmVsb3BtZW50IHNlc3Npb24uLi48L2Rpdj4nOwogIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdkZXYtcGFuZWwtc3VidGl0bGUnKS50ZXh0Q29udGVudCA9ICdE" +
    "ZXZlbG9waW5nOiAnICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC50aXRsZSA6ICdGb3JtYXQgaWRl" +
    "YScpOwogIHBhbmVsLnNjcm9sbEludG9WaWV3KHsgYmVoYXZpb3I6ICdzbW9vdGgnLCBibG9jazog" +
    "J3N0YXJ0JyB9KTsKCiAgLy8gT3BlbmluZyBtZXNzYWdlIGZyb20gdGhlIEFJCiAgZmV0Y2goJy9k" +
    "ZXZlbG9wJywgewogICAgbWV0aG9kOiAnUE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5" +
    "cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsKICAg" +
    "ICAgZm9ybWF0X2lkZWE6IGRldkZvcm1hdCwKICAgICAgdHJlbmRzOiBzYXZlZCwKICAgICAgbWVz" +
    "c2FnZXM6IFt7CiAgICAgICAgcm9sZTogJ3VzZXInLAogICAgICAgIGNvbnRlbnQ6ICdJIHdhbnQg" +
    "dG8gZGV2ZWxvcCB0aGlzIGZvcm1hdCBpZGVhLiBIZXJlIGlzIHdoYXQgd2UgaGF2ZSBzbyBmYXI6" +
    "IFRpdGxlOiAiJyArIChkZXZGb3JtYXQgPyBkZXZGb3JtYXQudGl0bGUgOiAnJykgKyAnIi4gTG9n" +
    "bGluZTogJyArIChkZXZGb3JtYXQgPyBkZXZGb3JtYXQubG9nbGluZSA6ICcnKSArICcuIFBsZWFz" +
    "ZSBzdGFydCBvdXIgZGV2ZWxvcG1lbnQgc2Vzc2lvbi4nCiAgICAgIH1dCiAgICB9KQogIH0pCiAg" +
    "LnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rpb24o" +
    "ZCkgewogICAgaWYgKGQuZXJyb3IpIHRocm93IG5ldyBFcnJvcihkLmVycm9yKTsKICAgIGRldk1l" +
    "c3NhZ2VzID0gWwogICAgICB7IHJvbGU6ICd1c2VyJywgY29udGVudDogJ0kgd2FudCB0byBkZXZl" +
    "bG9wIHRoaXMgZm9ybWF0IGlkZWEuIEhlcmUgaXMgd2hhdCB3ZSBoYXZlIHNvIGZhcjogVGl0bGU6" +
    "ICInICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC50aXRsZSA6ICcnKSArICciLiBMb2dsaW5lOiAn" +
    "ICsgKGRldkZvcm1hdCA/IGRldkZvcm1hdC5sb2dsaW5lIDogJycpICsgJy4gUGxlYXNlIHN0YXJ0" +
    "IG91ciBkZXZlbG9wbWVudCBzZXNzaW9uLicgfSwKICAgICAgeyByb2xlOiAnYXNzaXN0YW50Jywg" +
    "Y29udGVudDogZC5yZXNwb25zZSB9CiAgICBdOwogICAgcmVuZGVyRGV2Q2hhdCgpOwogIH0pCiAg" +
    "LmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAgIGNoYXQuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVt" +
    "cHR5Ij5Db3VsZCBub3Qgc3RhcnQgc2Vzc2lvbjogJyArIGUubWVzc2FnZSArICc8L2Rpdj4nOwog" +
    "IH0pOwp9CgpmdW5jdGlvbiBzZW5kRGV2TWVzc2FnZSgpIHsKICB2YXIgaW5wdXQgPSBkb2N1bWVu" +
    "dC5nZXRFbGVtZW50QnlJZCgnZGV2LWlucHV0Jyk7CiAgdmFyIG1zZyA9IGlucHV0LnZhbHVlLnRy" +
    "aW0oKTsKICBpZiAoIW1zZyB8fCAhZGV2Rm9ybWF0KSByZXR1cm47CiAgaW5wdXQudmFsdWUgPSAn" +
    "JzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2LXNlbmQnKS5kaXNhYmxlZCA9IHRydWU7" +
    "CgogIGRldk1lc3NhZ2VzLnB1c2goeyByb2xlOiAndXNlcicsIGNvbnRlbnQ6IG1zZyB9KTsKICBy" +
    "ZW5kZXJEZXZDaGF0KCk7CgogIGZldGNoKCcvZGV2ZWxvcCcsIHsKICAgIG1ldGhvZDogJ1BPU1Qn" +
    "LAogICAgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sCiAg" +
    "ICBib2R5OiBKU09OLnN0cmluZ2lmeSh7CiAgICAgIGZvcm1hdF9pZGVhOiBkZXZGb3JtYXQsCiAg" +
    "ICAgIHRyZW5kczogc2F2ZWQsCiAgICAgIG1lc3NhZ2VzOiBkZXZNZXNzYWdlcwogICAgfSkKICB9" +
    "KQogIC50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0" +
    "aW9uKGQpIHsKICAgIGlmIChkLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoZC5lcnJvcik7CiAgICBk" +
    "ZXZNZXNzYWdlcy5wdXNoKHsgcm9sZTogJ2Fzc2lzdGFudCcsIGNvbnRlbnQ6IGQucmVzcG9uc2Ug" +
    "fSk7CiAgICByZW5kZXJEZXZDaGF0KCk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGV2" +
    "LXNlbmQnKS5kaXNhYmxlZCA9IGZhbHNlOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rl" +
    "di1pbnB1dCcpLmZvY3VzKCk7CiAgfSkKICAuY2F0Y2goZnVuY3Rpb24oZSkgewogICAgZGV2TWVz" +
    "c2FnZXMucHVzaCh7IHJvbGU6ICdhc3Npc3RhbnQnLCBjb250ZW50OiAnU29ycnksIHNvbWV0aGlu" +
    "ZyB3ZW50IHdyb25nOiAnICsgZS5tZXNzYWdlIH0pOwogICAgcmVuZGVyRGV2Q2hhdCgpOwogICAg" +
    "ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rldi1zZW5kJykuZGlzYWJsZWQgPSBmYWxzZTsKICB9" +
    "KTsKfQoKZnVuY3Rpb24gcmVuZGVyRGV2Q2hhdCgpIHsKICB2YXIgY2hhdCA9IGRvY3VtZW50Lmdl" +
    "dEVsZW1lbnRCeUlkKCdkZXYtY2hhdCcpOwogIHZhciBodG1sID0gJyc7CiAgZm9yICh2YXIgaSA9" +
    "IDA7IGkgPCBkZXZNZXNzYWdlcy5sZW5ndGg7IGkrKykgewogICAgdmFyIG0gPSBkZXZNZXNzYWdl" +
    "c1tpXTsKICAgIHZhciBjbHMgPSBtLnJvbGUgPT09ICdhc3Npc3RhbnQnID8gJ2FpJyA6ICd1c2Vy" +
    "JzsKICAgIHZhciB0ZXh0ID0gbS5jb250ZW50LnJlcGxhY2UoL1xuL2csICc8YnI+Jyk7CiAgICBo" +
    "dG1sICs9ICc8ZGl2IGNsYXNzPSJkZXYtbXNnICcgKyBjbHMgKyAnIj4nICsgdGV4dCArICc8L2Rp" +
    "dj4nOwogIH0KICBjaGF0LmlubmVySFRNTCA9IGh0bWw7CiAgY2hhdC5zY3JvbGxUb3AgPSBjaGF0" +
    "LnNjcm9sbEhlaWdodDsKfQoKZnVuY3Rpb24gbG9hZFJlc2VhcmNoKCkgewogIGZldGNoKCcvcmVz" +
    "ZWFyY2gnKS50aGVuKGZ1bmN0aW9uKHIpIHsgcmV0dXJuIHIuanNvbigpOyB9KS50aGVuKGZ1bmN0" +
    "aW9uKGQpIHsgcmVuZGVyUmVzZWFyY2goZC5pdGVtcyB8fCBbXSk7IH0pCiAgLmNhdGNoKGZ1bmN0" +
    "aW9uKCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVzZWFyY2gtZmVlZCcpLmlubmVySFRN" +
    "TCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+Q291bGQgbm90IGxvYWQgcmVzZWFyY2guPC9kaXY+Jzsg" +
    "fSk7Cn0KCmZ1bmN0aW9uIHJlbmRlclJlc2VhcmNoKGl0ZW1zKSB7CiAgdmFyIGVsID0gZG9jdW1l" +
    "bnQuZ2V0RWxlbWVudEJ5SWQoJ3Jlc2VhcmNoLWZlZWQnKTsKICBpZiAoIWl0ZW1zLmxlbmd0aCkg" +
    "eyBlbC5pbm5lckhUTUwgPSAnPGRpdiBjbGFzcz0iZW1wdHkiPk5vIHJlc2VhcmNoIGl0ZW1zIGZv" +
    "dW5kLjwvZGl2Pic7IHJldHVybjsgfQogIHZhciB0eXBlTWFwID0geyByZXNlYXJjaDogJ1Jlc2Vh" +
    "cmNoJywgY3VsdHVyZTogJ0N1bHR1cmUnLCB0cmVuZHM6ICdUcmVuZHMnIH07IHZhciBodG1sID0g" +
    "Jyc7CiAgZm9yICh2YXIgaSA9IDA7IGkgPCBpdGVtcy5sZW5ndGg7IGkrKykgewogICAgdmFyIGl0" +
    "ZW0gPSBpdGVtc1tpXTsKICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9InJlc2VhcmNoLWl0ZW0iPjxk" +
    "aXYgY2xhc3M9InJlc2VhcmNoLXRpdGxlIj48YSBocmVmPSInICsgaXRlbS51cmwgKyAnIiB0YXJn" +
    "ZXQ9Il9ibGFuayI+JyArIGl0ZW0udGl0bGUgKyAnPC9hPjwvZGl2Pic7CiAgICBpZiAoaXRlbS5k" +
    "ZXNjKSBodG1sICs9ICc8ZGl2IGNsYXNzPSJyZXNlYXJjaC1kZXNjIj4nICsgaXRlbS5kZXNjICsg" +
    "JzwvZGl2Pic7CiAgICBodG1sICs9ICc8ZGl2IGNsYXNzPSJyZXNlYXJjaC1tZXRhIj48c3BhbiBj" +
    "bGFzcz0ici1zcmMiPicgKyBpdGVtLnNvdXJjZSArICc8L3NwYW4+PHNwYW4gY2xhc3M9InItdHlw" +
    "ZSI+JyArICh0eXBlTWFwW2l0ZW0udHlwZV0gfHwgaXRlbS50eXBlKSArICc8L3NwYW4+PC9kaXY+" +
    "PC9kaXY+JzsKICB9CiAgZWwuaW5uZXJIVE1MID0gaHRtbDsKfQoKZnVuY3Rpb24gZG9BcmNoaXZl" +
    "U2VhcmNoKCkgewogIHZhciBxdWVyeSA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZl" +
    "LXNlYXJjaC1pbnB1dCcpLnZhbHVlLnRyaW0oKTsKICBpZiAoIXF1ZXJ5KSByZXR1cm47CiAgdmFy" +
    "IHJlc3VsdHNFbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzZWFyY2gtcmVzdWx0cycpOwog" +
    "IHJlc3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjEycHg7Y29sb3I6" +
    "dmFyKC0tbXV0ZWQpIj48c3BhbiBjbGFzcz0ibG9hZGVyIj48L3NwYW4+U2VhcmNoaW5nIGFyY2hp" +
    "dmUuLi48L2Rpdj4nOwoKICBmZXRjaCgnL2FyY2hpdmUvc2VhcmNoJywgewogICAgbWV0aG9kOiAn" +
    "UE9TVCcsCiAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicg" +
    "fSwKICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsgcXVlcnk6IHF1ZXJ5IH0pCiAgfSkKICAudGhl" +
    "bihmdW5jdGlvbihyKSB7IHJldHVybiByLmpzb24oKTsgfSkKICAudGhlbihmdW5jdGlvbihkKSB7" +
    "CiAgICBpZiAoZC5lcnJvcikgdGhyb3cgbmV3IEVycm9yKGQuZXJyb3IpOwogICAgdmFyIHJlc3Vs" +
    "dHMgPSBkLnJlc3VsdHMgfHwgW107CiAgICBpZiAoIXJlc3VsdHMubGVuZ3RoKSB7CiAgICAgIHJl" +
    "c3VsdHNFbC5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjEycHg7Y29sb3I6dmFy" +
    "KC0tbXV0ZWQpO3BhZGRpbmc6OHB4IDAiPk5vIHJlbGV2YW50IHRyZW5kcyBmb3VuZCBmb3IgIicg" +
    "KyBxdWVyeSArICciLjwvZGl2Pic7CiAgICAgIHJldHVybjsKICAgIH0KICAgIHZhciBtY01hcCA9" +
    "IHsgcmlzaW5nOiAnYi1yaXNpbmcnLCBlbWVyZ2luZzogJ2ItZW1lcmdpbmcnLCBlc3RhYmxpc2hl" +
    "ZDogJ2ItZXN0YWJsaXNoZWQnLCBzaGlmdGluZzogJ2Itc2hpZnRpbmcnIH07CiAgICB2YXIgaHRt" +
    "bCA9ICc8ZGl2IHN0eWxlPSJmb250LXNpemU6MTBweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFy" +
    "KC0tbXV0ZWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzowLjhweDtt" +
    "YXJnaW4tYm90dG9tOjEwcHgiPicgKyByZXN1bHRzLmxlbmd0aCArICcgcmVsZXZhbnQgdHJlbmRz" +
    "IGZvdW5kPC9kaXY+JzsKICAgIGZvciAodmFyIGkgPSAwOyBpIDwgcmVzdWx0cy5sZW5ndGg7IGkr" +
    "KykgewogICAgICB2YXIgdCA9IHJlc3VsdHNbaV07CiAgICAgIHZhciBtYyA9IG1jTWFwW3QubW9t" +
    "ZW50dW1dIHx8ICdiLWVtZXJnaW5nJzsKICAgICAgaHRtbCArPSAnPGRpdiBzdHlsZT0icGFkZGlu" +
    "ZzoxMnB4IDA7Ym9yZGVyLWJvdHRvbToxcHggc29saWQgdmFyKC0tYm9yZGVyKSI+JzsKICAgICAg" +
    "aHRtbCArPSAnPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6" +
    "OHB4O21hcmdpbi1ib3R0b206NXB4Ij4nOwogICAgICBodG1sICs9ICc8ZGl2IHN0eWxlPSJmb250" +
    "LXNpemU6MTNweDtmb250LXdlaWdodDo2MDA7Y29sb3I6I2ZmZiI+JyArIHQubmFtZSArICc8L2Rp" +
    "dj4nOwogICAgICBodG1sICs9ICc8c3BhbiBjbGFzcz0iYmFkZ2UgJyArIG1jICsgJyI+JyArICh0" +
    "Lm1vbWVudHVtIHx8ICcnKSArICc8L3NwYW4+JzsKICAgICAgaHRtbCArPSAnPHNwYW4gc3R5bGU9" +
    "ImZvbnQtc2l6ZToxMHB4O2NvbG9yOnZhcigtLW11dGVkKSI+JyArIHQuc2F2ZWRfYXQuc2xpY2Uo" +
    "MCwxMCkgKyAnPC9zcGFuPic7CiAgICAgIGh0bWwgKz0gJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0g" +
    "JzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMnB4O2NvbG9yOnZhcigtLW11dGVkKTtsaW5lLWhlaWdo" +
    "dDoxLjU7bWFyZ2luLWJvdHRvbTo1cHgiPicgKyAodC5kZXNjIHx8ICcnKSArICc8L2Rpdj4nOwog" +
    "ICAgICBpZiAodC5yZWxldmFuY2UpIGh0bWwgKz0gJzxkaXYgc3R5bGU9ImZvbnQtc2l6ZToxMXB4" +
    "O2NvbG9yOnZhcigtLWFjY2VudDIpO2ZvbnQtc3R5bGU6aXRhbGljIj4nICsgdC5yZWxldmFuY2Ug" +
    "KyAnPC9kaXY+JzsKICAgICAgaHRtbCArPSAnPC9kaXY+JzsKICAgIH0KICAgIHJlc3VsdHNFbC5p" +
    "bm5lckhUTUwgPSBodG1sOwogIH0pCiAgLmNhdGNoKGZ1bmN0aW9uKGUpIHsKICAgIHJlc3VsdHNF" +
    "bC5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0iZm9udC1zaXplOjEycHg7Y29sb3I6I2ZjYTVhNSI+" +
    "U2VhcmNoIGZhaWxlZDogJyArIGUubWVzc2FnZSArICc8L2Rpdj4nOwogIH0pOwp9CgpmdW5jdGlv" +
    "biBsb2FkQXJjaGl2ZSgpIHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0Jyku" +
    "aW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5IiBzdHlsZT0icGFkZGluZzoxcmVtIDAiPjxz" +
    "cGFuIGNsYXNzPSJsb2FkZXIiPjwvc3Bhbj48L2Rpdj4nOwogIGZldGNoKCcvYXJjaGl2ZS9kYXRl" +
    "cycpLnRoZW4oZnVuY3Rpb24ocikgeyByZXR1cm4gci5qc29uKCk7IH0pCiAgLnRoZW4oZnVuY3Rp" +
    "b24oZCkgewogICAgaWYgKCFkLmRhdGVzIHx8ICFkLmRhdGVzLmxlbmd0aCkgeyBkb2N1bWVudC5n" +
    "ZXRFbGVtZW50QnlJZCgnZGF0ZS1saXN0JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5" +
    "IiBzdHlsZT0icGFkZGluZzoxcmVtIDA7Zm9udC1zaXplOjExcHgiPk5vIGFyY2hpdmVkIHRyZW5k" +
    "cyB5ZXQuPC9kaXY+JzsgcmV0dXJuOyB9CiAgICB2YXIgaHRtbCA9ICcnOwogICAgZm9yICh2YXIg" +
    "aSA9IDA7IGkgPCBkLmRhdGVzLmxlbmd0aDsgaSsrKSB7IGh0bWwgKz0gJzxkaXYgY2xhc3M9ImRh" +
    "dGUtaXRlbSIgb25jbGljaz0ibG9hZERhdGUoXCcnICsgZC5kYXRlc1tpXS5kYXRlICsgJ1wnLHRo" +
    "aXMpIj4nICsgZC5kYXRlc1tpXS5kYXRlICsgJzxzcGFuIGNsYXNzPSJkYXRlLWNvdW50Ij4nICsg" +
    "ZC5kYXRlc1tpXS5jb3VudCArICc8L3NwYW4+PC9kaXY+JzsgfQogICAgZG9jdW1lbnQuZ2V0RWxl" +
    "bWVudEJ5SWQoJ2RhdGUtbGlzdCcpLmlubmVySFRNTCA9IGh0bWw7CiAgICB2YXIgZmlyc3QgPSBk" +
    "b2N1bWVudC5xdWVyeVNlbGVjdG9yKCcuZGF0ZS1pdGVtJyk7IGlmIChmaXJzdCkgZmlyc3QuY2xp" +
    "Y2soKTsKICB9KQogIC5jYXRjaChmdW5jdGlvbihlKSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlk" +
    "KCdhcmNoaXZlLWVycicpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlcnJib3giPkNvdWxkIG5v" +
    "dCBsb2FkIGFyY2hpdmU6ICcgKyBlLm1lc3NhZ2UgKyAnPC9kaXY+JzsgfSk7Cn0KCmZ1bmN0aW9u" +
    "IGxvYWREYXRlKGRhdGUsIGVsKSB7CiAgdmFyIGl0ZW1zID0gZG9jdW1lbnQucXVlcnlTZWxlY3Rv" +
    "ckFsbCgnLmRhdGUtaXRlbScpOyBmb3IgKHZhciBpID0gMDsgaSA8IGl0ZW1zLmxlbmd0aDsgaSsr" +
    "KSBpdGVtc1tpXS5jbGFzc0xpc3QucmVtb3ZlKCdhY3RpdmUnKTsKICBlbC5jbGFzc0xpc3QuYWRk" +
    "KCdhY3RpdmUnKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2ZS1oZWFkaW5nJyku" +
    "dGV4dENvbnRlbnQgPSAnU2F2ZWQgb24gJyArIGRhdGU7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5" +
    "SWQoJ2FyY2hpdmUtY29udGVudCcpLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eSI+PHNw" +
    "YW4gY2xhc3M9ImxvYWRlciI+PC9zcGFuPjwvZGl2Pic7CiAgZmV0Y2goJy9hcmNoaXZlL2J5LWRh" +
    "dGU/ZGF0ZT0nICsgZW5jb2RlVVJJQ29tcG9uZW50KGRhdGUpKS50aGVuKGZ1bmN0aW9uKHIpIHsg" +
    "cmV0dXJuIHIuanNvbigpOyB9KQogIC50aGVuKGZ1bmN0aW9uKGQpIHsKICAgIGlmICghZC50cmVu" +
    "ZHMgfHwgIWQudHJlbmRzLmxlbmd0aCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2" +
    "ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5ObyB0cmVuZHMgZm9y" +
    "IHRoaXMgZGF0ZS48L2Rpdj4nOyByZXR1cm47IH0KICAgIHZhciBodG1sID0gJyc7CiAgICBmb3Ig" +
    "KHZhciBpID0gMDsgaSA8IGQudHJlbmRzLmxlbmd0aDsgaSsrKSB7CiAgICAgIHZhciB0ID0gZC50" +
    "cmVuZHNbaV07CiAgICAgIHZhciBtY01hcCA9IHsgcmlzaW5nOiAnYi1yaXNpbmcnLCBlbWVyZ2lu" +
    "ZzogJ2ItZW1lcmdpbmcnLCBlc3RhYmxpc2hlZDogJ2ItZXN0YWJsaXNoZWQnLCBzaGlmdGluZzog" +
    "J2Itc2hpZnRpbmcnIH07CiAgICAgIHZhciBtYyA9IG1jTWFwW3QubW9tZW50dW1dIHx8ICdiLWVt" +
    "ZXJnaW5nJzsgdmFyIGxpbmtzID0gW107CiAgICAgIHRyeSB7IGxpbmtzID0gSlNPTi5wYXJzZSh0" +
    "LnNvdXJjZV9saW5rcyB8fCAnW10nKTsgfSBjYXRjaChlKSB7fQogICAgICBodG1sICs9ICc8ZGl2" +
    "IGNsYXNzPSJhcmNoLWl0ZW0iPjxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpj" +
    "ZW50ZXI7Z2FwOjhweDttYXJnaW4tYm90dG9tOjNweCI+PGRpdiBjbGFzcz0iYXJjaC1uYW1lIj4n" +
    "ICsgdC5uYW1lICsgJzwvZGl2PjxzcGFuIGNsYXNzPSJiYWRnZSAnICsgbWMgKyAnIj4nICsgKHQu" +
    "bW9tZW50dW0gfHwgJycpICsgJzwvc3Bhbj48L2Rpdj4nOwogICAgICBodG1sICs9ICc8ZGl2IGNs" +
    "YXNzPSJhcmNoLW1ldGEiPicgKyB0LnNhdmVkX2F0ICsgKHQucmVnaW9uID8gJyAmbWlkZG90OyAn" +
    "ICsgdC5yZWdpb24udG9VcHBlckNhc2UoKSA6ICcnKSArICh0LnRhZyA/ICcgJm1pZGRvdDsgJyAr" +
    "IHQudGFnIDogJycpICsgJzwvZGl2Pic7CiAgICAgIGh0bWwgKz0gJzxkaXYgY2xhc3M9ImFyY2gt" +
    "ZGVzYyI+JyArICh0LmRlc2MgfHwgJycpICsgJzwvZGl2Pic7CiAgICAgIGZvciAodmFyIGwgPSAw" +
    "OyBsIDwgbGlua3MubGVuZ3RoOyBsKyspIHsgaHRtbCArPSAnPGEgY2xhc3M9ImFyY2gtbGluayIg" +
    "aHJlZj0iJyArIGxpbmtzW2xdLnVybCArICciIHRhcmdldD0iX2JsYW5rIj4nICsgbGlua3NbbF0u" +
    "dGl0bGUgKyAnPC9hPic7IH0KICAgICAgaHRtbCArPSAnPC9kaXY+JzsKICAgIH0KICAgIGRvY3Vt" +
    "ZW50LmdldEVsZW1lbnRCeUlkKCdhcmNoaXZlLWNvbnRlbnQnKS5pbm5lckhUTUwgPSBodG1sOwog" +
    "IH0pCiAgLmNhdGNoKGZ1bmN0aW9uKCkgeyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXJjaGl2" +
    "ZS1jb250ZW50JykuaW5uZXJIVE1MID0gJzxkaXYgY2xhc3M9ImVtcHR5Ij5Db3VsZCBub3QgbG9h" +
    "ZC48L2Rpdj4nOyB9KTsKfQo8L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+Cg=="
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
