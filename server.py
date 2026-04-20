from flask import Flask, request, jsonify, render_template_string
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
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS saved_trends (
            id {PK_DEF},
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
        print(f"[scraper] Failed {url}: {e}")
        return None

# ── Fast signal scrapers ──────────────────────────────────────────────────────

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
        print(f"[nu.nl] {e}")
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
        print(f"[ad.nl] {e}")
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
        print(f"[volkskrant] {e}")
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
        print(f"[parool] {e}")
    return items[:6]

def scrape_libelle():
    items = []
    try:
        soup = safe_get("https://www.libelle.nl") or safe_get("https://www.libelle.nl/populair")
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
        print(f"[libelle] {e}")
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
        print(f"[linda] {e}")
    return items[:6]

def scrape_rtl():
    items = []
    try:
        soup = safe_get("https://www.rtlnieuws.nl") or safe_get("https://www.rtlnieuws.nl/meest-gelezen")
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
        print(f"[rtl] {e}")
    return items[:6]

def scrape_reddit_hot(subreddit):
    items = []
    try:
        r = requests.get(
            f"https://www.reddit.com/r/{subreddit}/hot.json?limit=8",
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
                    "source": f"r/{subreddit}",
                    "type": "reddit"
                })
    except Exception as e:
        print(f"[reddit/{subreddit}] {e}")
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
        print(f"[google trends] {e}")
    _gtrends_cache["data"] = items
    _gtrends_cache["fetched_at"] = time.time()
    return items

def gather_all_headlines(region="nl"):
    """Fetch all sources in parallel — much faster than sequential."""
    all_items = []
    subreddits = ["Netherlands", "europe"] if region == "nl" else ["worldnews", "europe", "sociology"]
    subreddits += ["psychology", "TrueOffMyChest"]

    scrapers = [
        scrape_nu, scrape_ad, scrape_volkskrant, scrape_parool,
        scrape_libelle, scrape_linda, scrape_rtl, scrape_google_trends_nl
    ]
    scrapers += [lambda s=s: scrape_reddit_hot(s) for s in subreddits]

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(fn): fn for fn in scrapers}
        for future in as_completed(futures, timeout=15):
            try:
                result = future.result()
                if result:
                    all_items.extend(result)
            except Exception as e:
                print(f"[parallel error] {e}")

    return all_items

# ── Slow trend / research scrapers ───────────────────────────────────────────

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
        print(f"[rss/{source_name}] {e}")
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
        print(f"[scp] {e}")
    return items[:5]

def gather_research():
    """Fetch all research sources in parallel."""
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
                print(f"[research parallel error] {e}")

    _research_cache["data"] = all_items
    _research_cache["fetched_at"] = time.time()
    print(f"[research] fetched {len(all_items)} items")
    return all_items

# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trentradar</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f9f9f7; color: #1a1a1a; min-height: 100vh; }
.dash { max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem; }
.top-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 12px; }
.logo { font-size: 16px; font-weight: 600; color: #1a1a1a; }
.logo span { color: #888; font-weight: 400; }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
select { font-size: 12px; padding: 5px 12px; border-radius: 20px; border: 1px solid #ddd; background: #fff; color: #555; cursor: pointer; }
.btn { font-size: 13px; padding: 8px 18px; border-radius: 8px; border: 1px solid #ddd; background: #fff; color: #1a1a1a; cursor: pointer; font-weight: 500; white-space: nowrap; }
.btn:hover { background: #f0f0f0; }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn.primary { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
.btn.primary:hover { background: #333; }
.source-bar { display: flex; gap: 6px; margin-bottom: 1.5rem; flex-wrap: wrap; }
.src-tag { font-size: 11px; padding: 4px 10px; border-radius: 20px; border: 1px solid #e0e0e0; background: #fff; color: #888; cursor: pointer; user-select: none; }
.src-tag.on { border-color: #5DCAA5; background: #E1F5EE; color: #0F6E56; }
.status-row { font-size: 12px; color: #aaa; margin-bottom: 1rem; display: flex; gap: 1rem; flex-wrap: wrap; }
.nav-tabs { display: flex; margin-bottom: 2rem; border-bottom: 1px solid #e8e8e8; }
.nav-tab { font-size: 13px; padding: 8px 18px; cursor: pointer; color: #aaa; border-bottom: 2px solid transparent; margin-bottom: -1px; font-weight: 500; }
.nav-tab.active { color: #1a1a1a; border-bottom-color: #1a1a1a; }
.grid { display: grid; grid-template-columns: 2fr 1.3fr 1fr; gap: 1.25rem; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
.col-head { font-size: 10px; font-weight: 600; color: #aaa; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 10px; }
.tab-row { display: flex; margin-bottom: 1rem; border-bottom: 1px solid #e8e8e8; }
.tab { font-size: 13px; padding: 6px 14px; cursor: pointer; color: #aaa; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab.active { color: #1a1a1a; border-bottom-color: #1a1a1a; font-weight: 500; }
.trend-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 10px; }
.trend-card.saved { border-left: 3px solid #1D9E75; }
.trend-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
.trend-name { font-size: 15px; font-weight: 600; color: #1a1a1a; line-height: 1.3; }
.mbadge { font-size: 10px; padding: 3px 8px; border-radius: 20px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
.m-rising { background: #EAF3DE; color: #3B6D11; }
.m-emerging { background: #FAEEDA; color: #854F0B; }
.m-established { background: #E6F1FB; color: #185FA5; }
.m-shifting { background: #FBEAF0; color: #993556; }
.trend-desc { font-size: 13px; color: #555; line-height: 1.6; margin-bottom: 8px; }
.trend-signals { font-size: 12px; color: #999; line-height: 1.5; }
.trend-footer { display: flex; gap: 6px; margin-top: 10px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
.src-chip { font-size: 10px; padding: 2px 8px; border-radius: 20px; background: #f5f5f5; color: #888; border: 1px solid #e8e8e8; }
.act-btn { font-size: 11px; padding: 4px 10px; border-radius: 6px; border: 1px solid #ddd; background: transparent; color: #888; cursor: pointer; }
.act-btn:hover { background: #f5f5f5; }
.act-btn.is-saved { color: #0F6E56; border-color: #5DCAA5; background: #E1F5EE; }
.expand-box { display: none; margin-top: 10px; border-top: 1px solid #f0f0f0; padding-top: 10px; }
.source-link { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f5f5f5; text-decoration: none; color: inherit; }
.source-link:last-child { border-bottom: none; }
.source-link:hover .sl-title { color: #185FA5; text-decoration: underline; }
.sl-icon { font-size: 9px; font-weight: 700; color: #fff; border-radius: 4px; padding: 2px 5px; flex-shrink: 0; margin-top: 1px; }
.sl-reddit { background: #E24B4A; } .sl-news { background: #185FA5; } .sl-trends { background: #1D9E75; } .sl-lifestyle { background: #BA7517; }
.sl-title { font-size: 12px; color: #1a1a1a; line-height: 1.4; }
.sl-source { font-size: 10px; color: #aaa; margin-top: 1px; }
.research-card { background: #fff; border: 1px solid #e8e8e8; border-left: 3px solid #9FE1CB; border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 8px; }
.research-title { font-size: 13px; font-weight: 500; color: #1a1a1a; line-height: 1.4; margin-bottom: 4px; }
.research-title a { color: inherit; text-decoration: none; }
.research-title a:hover { color: #185FA5; text-decoration: underline; }
.research-desc { font-size: 12px; color: #888; line-height: 1.5; margin-bottom: 6px; }
.research-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.r-source { font-size: 10px; padding: 2px 8px; border-radius: 20px; background: #E1F5EE; color: #0F6E56; }
.r-type { font-size: 10px; padding: 2px 8px; border-radius: 20px; background: #f5f5f5; color: #888; }
.r-pub { font-size: 10px; color: #bbb; }
.signal-item { display: flex; gap: 8px; padding: 7px 0; border-bottom: 1px solid #f0f0f0; }
.signal-item:last-child { border-bottom: none; }
.sig-dot { width: 6px; height: 6px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
.sig-text { font-size: 12px; color: #1a1a1a; line-height: 1.4; }
.sig-meta { font-size: 10px; color: #aaa; margin-top: 1px; }
.sig-link { font-size: 10px; color: #185FA5; text-decoration: none; display: block; margin-top: 1px; }
.sig-link:hover { text-decoration: underline; }
.src-group-label { font-size: 10px; font-weight: 600; color: #bbb; text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 4px; }
.saved-item { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid #f0f0f0; }
.saved-item:last-child { border-bottom: none; }
.tag-input { font-size: 11px; border: 1px solid #e0e0e0; border-radius: 6px; padding: 3px 8px; background: #f9f9f7; color: #555; width: 80px; }
.format-card { background: #f5f5f3; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 10px; border: 1px solid #e8e8e8; }
.format-title { font-size: 14px; font-weight: 600; color: #1a1a1a; margin-bottom: 4px; }
.format-desc { font-size: 13px; color: #555; line-height: 1.6; }
.format-hook { font-size: 12px; color: #999; margin-top: 6px; font-style: italic; }
.empty { text-align: center; padding: 2rem; color: #bbb; font-size: 13px; }
.errbox { background: #fff0f0; border: 1px solid #ffcccc; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #c00; margin-bottom: 1rem; }
.infobox { background: #E6F1FB; border: 1px solid #B5D4F4; border-radius: 8px; padding: 8px 12px; font-size: 12px; color: #185FA5; margin-bottom: 1rem; }
.loader { display: inline-block; width: 10px; height: 10px; border: 1.5px solid #ddd; border-top-color: #888; border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; margin-right: 5px; }
@keyframes spin { to { transform: rotate(360deg); } }
.progress-bar { background: #f0f0f0; border-radius: 4px; height: 3px; margin-bottom: 1.5rem; }
.progress-fill { background: #1a1a1a; height: 3px; border-radius: 4px; width: 0%; transition: width 0.4s; }
.archive-grid { display: grid; grid-template-columns: 200px 1fr; gap: 1.5rem; }
@media (max-width: 700px) { .archive-grid { grid-template-columns: 1fr; } }
.date-item { padding: 8px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; font-size: 13px; color: #555; }
.date-item:hover { background: #f0f0f0; }
.date-item.active { background: #1a1a1a; color: #fff; }
.date-count { font-size: 11px; opacity: 0.6; margin-left: 6px; }
.archive-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 10px; }
.arch-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.arch-name { font-size: 14px; font-weight: 600; color: #1a1a1a; }
.arch-meta { font-size: 11px; color: #aaa; margin-bottom: 6px; }
.arch-desc { font-size: 13px; color: #555; line-height: 1.5; }
</style>
</head>
<body>
<div class="dash">
  <div class="top-bar">
    <div class="logo">Trentradar <span>— live cultural signals for unscripted formats</span></div>
    <div class="controls" id="scan-controls">
      <select id="region-sel">
        <option value="nl">NL focus</option>
        <option value="eu">EU / global</option>
        <option value="all">All markets</option>
      </select>
      <select id="horizon-sel">
        <option value="emerging">Emerging</option>
        <option value="rising">Rising</option>
        <option value="all">All signals</option>
      </select>
      <button class="btn primary" id="scan-btn" onclick="runScan()">Scan now</button>
    </div>
  </div>

  <div class="nav-tabs">
    <div class="nav-tab active" id="nav-d" onclick="switchView('dashboard')">Dashboard</div>
    <div class="nav-tab" id="nav-a" onclick="switchView('archive')">Archive</div>
  </div>

  <div id="view-dashboard">
    <div class="source-bar">
      <span class="src-tag on" data-src="NU.nl" onclick="this.classList.toggle('on')">NU.nl</span>
      <span class="src-tag on" data-src="AD.nl" onclick="this.classList.toggle('on')">AD.nl</span>
      <span class="src-tag on" data-src="Volkskrant" onclick="this.classList.toggle('on')">Volkskrant</span>
      <span class="src-tag on" data-src="Parool" onclick="this.classList.toggle('on')">Parool</span>
      <span class="src-tag on" data-src="Libelle" onclick="this.classList.toggle('on')">Libelle</span>
      <span class="src-tag on" data-src="Linda.nl" onclick="this.classList.toggle('on')">Linda.nl</span>
      <span class="src-tag on" data-src="RTL Nieuws" onclick="this.classList.toggle('on')">RTL Nieuws</span>
      <span class="src-tag on" data-src="Reddit" onclick="this.classList.toggle('on')">Reddit</span>
      <span class="src-tag on" data-src="Google Trends NL" onclick="this.classList.toggle('on')">Google Trends NL</span>
    </div>
    <div id="err-box"></div>
    <div id="info-box"></div>
    <div class="status-row">
      <span id="status-text">Last scan: —</span>
      <span id="headline-count"></span>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>

    <div class="grid">
      <div>
        <div class="tab-row">
          <div class="tab active" id="tab-t" onclick="switchTab('trends')">Cultural trends</div>
          <div class="tab" id="tab-f" onclick="switchTab('formats')">Format ideas</div>
        </div>
        <div id="pane-trends">
          <div class="col-head">Detected trends</div>
          <div id="trends-list"><div class="empty">Press "Scan now" to fetch live headlines and detect trends.</div></div>
        </div>
        <div id="pane-formats" style="display:none">
          <div class="col-head">Format concepts</div>
          <div id="formats-list"><div class="empty">Save some trends, then generate format ideas.</div></div>
        </div>
      </div>
      <div>
        <div class="col-head">Slow trends — research &amp; reports</div>
        <div id="research-feed"><div class="empty"><span class="loader"></span>Loading...</div></div>
      </div>
      <div>
        <div class="col-head">Live headlines</div>
        <div id="signal-feed"><div class="empty">Headlines appear here after scanning.</div></div>
        <div style="margin-top:1.5rem">
          <div class="col-head">Saved this session</div>
          <div id="saved-list"><div class="empty">No saved trends yet.</div></div>
          <div id="gen-row" style="display:none;margin-top:12px">
            <button class="btn" style="width:100%" onclick="generateFormats()">Generate format ideas</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div id="view-archive" style="display:none">
    <div id="archive-err"></div>
    <div class="archive-grid">
      <div>
        <div class="col-head">Browse by date</div>
        <div id="date-list"><div class="empty" style="padding:1rem 0">Loading...</div></div>
      </div>
      <div>
        <div class="col-head" id="archive-heading">Select a date</div>
        <div id="archive-content"><div class="empty">Select a date to browse saved trends.</div></div>
      </div>
    </div>
  </div>
</div>

<script>
var saved = [];
var trends = [];

window.addEventListener('load', function() { loadResearch(); });

function switchView(v) {
  document.getElementById('view-dashboard').style.display = v==='dashboard' ? '' : 'none';
  document.getElementById('view-archive').style.display = v==='archive' ? '' : 'none';
  document.getElementById('scan-controls').style.display = v==='dashboard' ? '' : 'none';
  document.getElementById('nav-d').className = 'nav-tab' + (v==='dashboard' ? ' active' : '');
  document.getElementById('nav-a').className = 'nav-tab' + (v==='archive' ? ' active' : '');
  if (v === 'archive') loadArchive();
}

function switchTab(t) {
  document.getElementById('pane-trends').style.display = t==='trends' ? '' : 'none';
  document.getElementById('pane-formats').style.display = t==='formats' ? '' : 'none';
  document.getElementById('tab-t').className = 'tab' + (t==='trends' ? ' active' : '');
  document.getElementById('tab-f').className = 'tab' + (t==='formats' ? ' active' : '');
}

function showErr(msg) { document.getElementById('err-box').innerHTML = '<div class="errbox"><strong>Error:</strong> ' + msg + '</div>'; }
function clearErr() { document.getElementById('err-box').innerHTML = ''; document.getElementById('info-box').innerHTML = ''; }
function showInfo(msg) { document.getElementById('info-box').innerHTML = '<div class="infobox">' + msg + '</div>'; }
function setProgress(p) { document.getElementById('progress-fill').style.width = p + '%'; }

async function runScan() {
  clearErr();
  var btn = document.getElementById('scan-btn');
  btn.disabled = true; btn.textContent = 'Scanning...';
  setProgress(10);
  document.getElementById('status-text').innerHTML = '<span class="loader"></span>Fetching live headlines...';
  document.getElementById('headline-count').textContent = '';
  document.getElementById('trends-list').innerHTML = '<div class="empty"><span class="loader"></span>Fetching meest gelezen...</div>';
  document.getElementById('signal-feed').innerHTML = '<div class="empty"><span class="loader"></span>Loading headlines...</div>';

  var region = document.getElementById('region-sel').value;
  var horizon = document.getElementById('horizon-sel').value;
  var headlines = [];

  try {
    var r = await fetch('/scrape', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({region:region}) });
    var d = await r.json();
    headlines = d.items || [];
    setProgress(40);
    document.getElementById('headline-count').textContent = headlines.length + ' headlines fetched';
    renderHeadlines(headlines);
  } catch(e) {
    showErr('Could not fetch headlines: ' + e.message);
    btn.disabled = false; btn.textContent = 'Scan now';
    setProgress(0);
    return;
  }

  if (!headlines.length) showInfo('No headlines fetched — using AI knowledge for trend synthesis.');

  document.getElementById('status-text').innerHTML = '<span class="loader"></span>Synthesizing trends...';
  setProgress(65);

  var headlineText = headlines.length
    ? headlines.map(function(h){ return '- [' + h.source + '] ' + h.title + ' (' + h.url + ')'; }).join('\n')
    : '(No live headlines — use training knowledge for Dutch cultural trends)';

  var horizonLabel = {emerging:'emerging (weak signals)',rising:'rising (growing momentum)',all:'all momentum stages'}[horizon];
  var regionLabel = {nl:'Dutch / Netherlands',eu:'European',all:'global including NL'}[region];

  var prompt = 'You are a cultural trend analyst for a Dutch unscripted TV format development team.\n\nReal headlines fetched NOW from Dutch meest-gelezen sections, Google Trends NL, and Reddit:\n\n' + headlineText + '\n\nIdentify ' + horizonLabel + ' human and cultural trends for ' + regionLabel + ' context.\nFocus: human connection, identity, belonging, loneliness, relationships, lifestyle, work, aging, youth, family, technology emotion.\n\nReference actual headlines from the list as evidence. Use actual URLs provided.\n\nReturn ONLY a JSON object, starting with { and ending with }:\n{"trends":[{"name":"Trend name 3-5 words","momentum":"rising|emerging|established|shifting","desc":"Two sentences for a TV format developer.","signals":"Two specific observations from the headlines.","sourceLabels":["NU.nl","Reddit"],"sourceLinks":[{"title":"Exact headline title","url":"https://exact-url-from-list","source":"NU.nl","type":"news|reddit|trends|lifestyle"}],"formatHint":"One-line unscripted TV format angle."}]}\n\nGenerate exactly 5 trends. Only use URLs from the headlines list above.';

  try {
    var cr = await fetch('/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({max_tokens:2500, messages:[{role:'user',content:prompt}]}) });
    var cd = await cr.json();
    if (!cr.ok) throw new Error(cd.error || cr.status);
    var text = cd.content.filter(function(b){return b.type==='text';}).map(function(b){return b.text;}).join('\n');
    var cleaned = text.replace(/```json\n?/g,'').replace(/```\n?/g,'').trim();
    var match = cleaned.match(/\{[\s\S]*\}/);
    if (!match) throw new Error('No JSON in response');
    var result = JSON.parse(match[0]);
    if (!result.trends || !result.trends.length) throw new Error('No trends in response');
    trends = result.trends;
    setProgress(100);
    renderTrends(region);
    var now = new Date().toLocaleTimeString('nl-NL',{hour:'2-digit',minute:'2-digit'});
    document.getElementById('status-text').textContent = 'Last scan: ' + now + ' — ' + headlines.length + ' live headlines';
    if (!headlines.length) showInfo('Trends from AI knowledge (live scraping returned 0 headlines).');
  } catch(e) {
    showErr('Trend synthesis failed: ' + e.message);
    document.getElementById('status-text').textContent = 'Scan failed.';
    document.getElementById('trends-list').innerHTML = '<div class="empty">See error above.</div>';
    setProgress(0);
  }
  btn.disabled = false; btn.textContent = 'Scan now';
}

function srcColor(src) {
  src = (src||'').toLowerCase();
  if (src.indexOf('reddit') > -1) return '#E24B4A';
  if (src.indexOf('google') > -1) return '#1D9E75';
  if (src === 'libelle' || src === 'linda.nl') return '#BA7517';
  return '#185FA5';
}

function renderHeadlines(headlines) {
  var el = document.getElementById('signal-feed');
  if (!headlines.length) { el.innerHTML='<div class="empty">No headlines fetched.</div>'; return; }
  var bySource = {};
  headlines.forEach(function(h) {
    if (!bySource[h.source]) bySource[h.source] = [];
    bySource[h.source].push(h);
  });
  var html = '';
  Object.keys(bySource).forEach(function(src) {
    html += '<div class="src-group-label">' + src + '</div>';
    bySource[src].slice(0,3).forEach(function(h) {
      html += '<div class="signal-item"><div class="sig-dot" style="background:' + srcColor(src) + '"></div><div><div class="sig-text">' + h.title + '</div>' + (h.url ? '<a class="sig-link" href="' + h.url + '" target="_blank">lees meer ↗</a>' : '') + '</div></div>';
    });
  });
  el.innerHTML = html;
}

function renderTrends(region) {
  var el = document.getElementById('trends-list');
  if (!trends.length) { el.innerHTML='<div class="empty">No trends detected.</div>'; return; }
  el.innerHTML = trends.map(function(t,i) {
    var isSaved = saved.find(function(s){return s.name===t.name;});
    var mc = {rising:'m-rising',emerging:'m-emerging',established:'m-established',shifting:'m-shifting'}[t.momentum]||'m-emerging';
    var links = t.sourceLinks || [];
    var iconCls = {reddit:'sl-reddit',news:'sl-news',trends:'sl-trends',lifestyle:'sl-lifestyle'};
    var iconLbl = {reddit:'R',news:'N',trends:'G',lifestyle:'L'};
    var linksHtml = links.map(function(l) {
      var cls = iconCls[l.type] || 'sl-news';
      var lbl = iconLbl[l.type] || 'N';
      return '<a class="source-link" href="' + l.url + '" target="_blank"><span class="sl-icon ' + cls + '">' + lbl + '</span><div><div class="sl-title">' + l.title + '</div><div class="sl-source">' + l.source + '</div></div></a>';
    }).join('');
    return '<div class="trend-card' + (isSaved?' saved':'') + '" id="tc-' + i + '">' +
      '<div class="trend-top"><div class="trend-name">' + t.name + '</div><span class="mbadge ' + mc + '">' + t.momentum + '</span></div>' +
      '<div class="trend-desc">' + t.desc + '</div>' +
      '<div class="trend-signals">' + t.signals + '</div>' +
      '<div class="trend-footer">' +
        '<div style="display:flex;gap:4px;flex-wrap:wrap">' + (t.sourceLabels||[]).map(function(s){return '<span class="src-chip">'+s+'</span>';}).join('') + '</div>' +
        '<div style="display:flex;gap:6px">' +
          (links.length ? '<button class="act-btn" onclick="toggleBox(\'src-'+i+'\')">sources ('+links.length+')</button>' : '') +
          (t.formatHint ? '<button class="act-btn" onclick="toggleBox(\'hint-'+i+'\')">format hint</button>' : '') +
          '<button class="act-btn' + (isSaved?' is-saved':'') + '" id="sb-'+i+'" onclick="doSave('+i+',\''+region+'\')">' + (isSaved?'saved':'save') + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="expand-box" id="src-'+i+'">' + (linksHtml||'<div style="font-size:12px;color:#aaa">No source links.</div>') + '</div>' +
      '<div class="expand-box" id="hint-'+i+'" style="font-size:12px;font-style:italic;color:#185FA5">' + (t.formatHint||'') + '</div>' +
    '</div>';
  }).join('');
}

function toggleBox(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = el.style.display==='block' ? 'none' : 'block';
}

async function doSave(i, region) {
  var t = trends[i];
  if (saved.find(function(s){return s.name===t.name;})) return;
  saved.push({name:t.name, desc:t.desc, tag:''});
  document.getElementById('sb-'+i).textContent='saved';
  document.getElementById('sb-'+i).classList.add('is-saved');
  document.getElementById('tc-'+i).classList.add('saved');
  renderSaved();
  try {
    await fetch('/archive/save', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name:t.name,desc:t.desc,momentum:t.momentum,signals:t.signals,source_labels:t.sourceLabels||[],source_links:t.sourceLinks||[],format_hint:t.formatHint,tag:'',region:region||'nl'}) });
  } catch(e) { console.error('archive save failed', e); }
}

function renderSaved() {
  var el = document.getElementById('saved-list');
  document.getElementById('gen-row').style.display = saved.length ? '' : 'none';
  if (!saved.length) { el.innerHTML='<div class="empty">No saved trends yet.</div>'; return; }
  el.innerHTML = saved.map(function(t,i){
    return '<div class="saved-item"><div style="font-size:13px;color:#1a1a1a;flex:1">' + t.name + '</div><div style="display:flex;gap:6px;align-items:center"><input class="tag-input" placeholder="tag..." value="' + t.tag + '" oninput="saved['+i+'].tag=this.value"/><span style="cursor:pointer;font-size:12px;color:#aaa" onclick="saved.splice('+i+',1);renderSaved()">&#x2715;</span></div></div>';
  }).join('');
}

async function generateFormats() {
  if (!saved.length) return;
  switchTab('formats');
  document.getElementById('formats-list').innerHTML='<div class="empty"><span class="loader"></span>Generating format concepts...</div>';
  var trendList = saved.map(function(t,i){return (i+1)+'. "'+t.name+'": '+t.desc+(t.tag?' [tag: '+t.tag+']':'');}).join('\n');
  var prompt = 'You are a senior unscripted TV format developer at a Dutch production company (KRO-NCRV, BNNVARA, Talpa). Generate format concepts from these cultural trends spotted in Dutch media today:\n\n' + trendList + '\n\nReturn ONLY a JSON object starting with { ending with }:\n{"formats":[{"title":"Format title","logline":"One punchy sentence.","trendBasis":"Which trend(s)","hook":"What makes this emotionally compelling for Dutch audience?","channel":"e.g. NPO1, RTL4, Netflix NL"}]}\n\nGenerate exactly 3 specific, pitchable format concepts.';
  try {
    var r = await fetch('/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_tokens:1200,messages:[{role:'user',content:prompt}]})});
    var d = await r.json();
    var text = d.content.filter(function(b){return b.type==='text';}).map(function(b){return b.text;}).join('\n');
    var match = text.replace(/```json\n?/g,'').replace(/```\n?/g,'').trim().match(/\{[\s\S]*\}/);
    if (!match) throw new Error('No JSON');
    var result = JSON.parse(match[0]);
    document.getElementById('formats-list').innerHTML = result.formats.map(function(f){
      return '<div class="format-card"><div class="format-title">'+f.title+'</div><div class="format-desc">'+f.logline+'</div><div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap"><span class="src-chip">'+f.channel+'</span><span class="src-chip" style="font-style:italic">'+f.trendBasis+'</span></div><div class="format-hook">"'+f.hook+'"</div></div>';
    }).join('');
  } catch(e) {
    showErr('Format generation failed: ' + e.message);
    document.getElementById('formats-list').innerHTML='<div class="empty">Failed.</div>';
  }
}

async function loadResearch() {
  document.getElementById('research-feed').innerHTML = '<div class="empty"><span class="loader"></span>Loading research...</div>';
  try {
    var r = await fetch('/research');
    var d = await r.json();
    renderResearch(d.items || []);
  } catch(e) {
    document.getElementById('research-feed').innerHTML = '<div class="empty">Could not load research feed.</div>';
  }
}

function renderResearch(items) {
  var el = document.getElementById('research-feed');
  if (!items.length) { el.innerHTML='<div class="empty">No research items found.</div>'; return; }
  var typeMap = {research:'Research',culture:'Culture',trends:'Trends'};
  el.innerHTML = items.map(function(item){
    return '<div class="research-card"><div class="research-title"><a href="' + item.url + '" target="_blank">' + item.title + ' ↗</a></div>' + (item.desc ? '<div class="research-desc">' + item.desc + '</div>' : '') + '<div class="research-meta"><span class="r-source">' + item.source + '</span><span class="r-type">' + (typeMap[item.type]||item.type) + '</span>' + (item.pub ? '<span class="r-pub">' + item.pub + '</span>' : '') + '</div></div>';
  }).join('');
}

async function loadArchive() {
  document.getElementById('date-list').innerHTML = '<div class="empty" style="padding:1rem 0"><span class="loader"></span></div>';
  try {
    var r = await fetch('/archive/dates');
    var d = await r.json();
    if (!d.dates || !d.dates.length) {
      document.getElementById('date-list').innerHTML = '<div class="empty" style="padding:1rem 0;font-size:12px">No archived trends yet.</div>';
      return;
    }
    document.getElementById('date-list').innerHTML = d.dates.map(function(x){
      return '<div class="date-item" onclick="loadDate(\''+x.date+'\',this)">'+x.date+'<span class="date-count">'+x.count+'</span></div>';
    }).join('');
    var first = document.querySelector('.date-item');
    if (first) first.click();
  } catch(e) {
    document.getElementById('archive-err').innerHTML = '<div class="errbox">Could not load archive: '+e.message+'</div>';
  }
}

async function loadDate(date, el) {
  document.querySelectorAll('.date-item').forEach(function(d){d.classList.remove('active');});
  el.classList.add('active');
  document.getElementById('archive-heading').textContent = 'Saved on ' + date;
  document.getElementById('archive-content').innerHTML = '<div class="empty"><span class="loader"></span></div>';
  try {
    var r = await fetch('/archive/by-date?date=' + encodeURIComponent(date));
    var d = await r.json();
    if (!d.trends || !d.trends.length) { document.getElementById('archive-content').innerHTML='<div class="empty">No trends for this date.</div>'; return; }
    document.getElementById('archive-content').innerHTML = d.trends.map(function(t){
      var mc = {rising:'m-rising',emerging:'m-emerging',established:'m-established',shifting:'m-shifting'}[t.momentum]||'m-emerging';
      var links = [];
      try { links = JSON.parse(t.source_links||'[]'); } catch(e) {}
      var linksHtml = links.map(function(l){ return '<a href="'+l.url+'" target="_blank" style="display:block;font-size:11px;color:#185FA5;margin-top:3px;text-decoration:none">'+l.title+' ↗</a>'; }).join('');
      return '<div class="archive-card"><div class="arch-top"><div class="arch-name">'+t.name+'</div><span class="mbadge '+mc+'">'+(t.momentum||'')+'</span></div><div class="arch-meta">'+t.saved_at+(t.region?' &middot; '+t.region.toUpperCase():'')+(t.tag?' &middot; <strong>'+t.tag+'</strong>':'')+'</div><div class="arch-desc">'+(t.desc||'')+'</div>'+linksHtml+'</div>';
    }).join('');
  } catch(e) {
    document.getElementById('archive-content').innerHTML='<div class="empty">Could not load.</div>';
  }
}
</script>
</body>
</html>"""

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/scrape", methods=["POST"])
def scrape():
    body = request.json or {}
    items = gather_all_headlines(body.get("region", "nl"))
    return jsonify({"items": items, "count": len(items)})

@app.route("/research")
def research():
    items = gather_research()
    return jsonify({"items": items, "count": len(items)})

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
    cur.execute(
        f"INSERT INTO saved_trends (name, desc, momentum, signals, source_labels, source_links, format_hint, tag, region, saved_at) VALUES ({PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER},{PLACEHOLDER})",
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
    cur.execute(f"SELECT * FROM saved_trends WHERE substr(saved_at, 1, 10) = {PLACEHOLDER} ORDER BY saved_at DESC", (date,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"trends": [dict(r) for r in rows]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
