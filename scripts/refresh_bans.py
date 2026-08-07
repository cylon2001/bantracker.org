#!/usr/bin/env python3
"""
Refreshes ban-tracker.json with fresh messenger-ban news.
Uses Google News RSS (no API key required). Runs via GitHub Actions every 6h.
"""

import json
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

JSON_PATH = "ban-tracker.json"
MAX_ITEMS = 60  # keep the feed from growing forever

# Platforms we track. Add more here as needed — no code changes required elsewhere.
PLATFORMS = ["Telegram", "WhatsApp", "Signal", "Session", "Messenger"]

# Ambiguous platform names double as common English words ("Trump signals...",
# "pro forma session"). For these, require at least one confirming word in the
# headline before accepting the story. Unambiguous platforms need no extra check.
AMBIGUOUS_PLATFORM_CONFIRM = {
    "Signal": ["app", "messenger", "messaging", "encrypted", "chat"],
    "Session": ["app", "messenger", "messaging", "encrypted", "chat"],
}

# Ban/block keywords paired with each platform to build search queries.
BAN_TERMS = ["banned", "blocked", "blocks", "ban on", "restricts", "throttles", "shuts down"]

# Known country names to detect in headlines. Extend as new countries appear.
COUNTRIES = [
    "India", "Russia", "Iran", "China", "Brazil", "Turkey", "Pakistan",
    "Belarus", "Myanmar", "Cuba", "Egypt", "Ethiopia", "Turkmenistan",
    "Uganda", "North Korea", "Indonesia", "Bangladesh", "Venezuela",
    "Nigeria", "Vietnam", "Thailand", "Saudi Arabia", "UAE", "Kazakhstan",
    "Tajikistan", "Uzbekistan", "Sudan", "Chad", "Senegal", "Ukraine",
    "Germany", "France", "United Kingdom", "United States", "Spain", "Italy"
]

USER_AGENT = "Mozilla/5.0 (compatible; BanTrackerBot/1.0; +https://bantracker.org)"


def fetch_rss(query):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        return ET.fromstring(data)
    except Exception as e:
        print(f"WARN: failed to fetch '{query}': {e}")
        return None


def detect_country(text):
    for c in COUNTRIES:
        if c.lower() in text.lower():
            return c
    return None


def parse_pubdate(pubdate_str):
    try:
        dt = datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %Z")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def collect_candidates():
    candidates = []
    for platform in PLATFORMS:
        for term in BAN_TERMS:
            query = f'{platform} {term}'
            root = fetch_rss(query)
            if root is None:
                continue
            channel = root.find("channel")
            if channel is None:
                continue
            for item in channel.findall("item")[:8]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pubdate = item.findtext("pubDate") or ""
                source_el = item.find("source")
                source_name = source_el.text if source_el is not None else "News"

                if not title or not link:
                    continue

                # For ambiguous platform names, require a confirming word so we
                # don't pull in unrelated stories (e.g. "Trump signals reversal").
                confirm_words = AMBIGUOUS_PLATFORM_CONFIRM.get(platform)
                if confirm_words:
                    title_lower = title.lower()
                    if not any(w in title_lower for w in confirm_words):
                        continue

                country = detect_country(title)
                if not country:
                    continue  # skip stories we can't attribute to a country

                candidates.append({
                    "date": parse_pubdate(pubdate),
                    "platform": platform,
                    "title": title,
                    "summary": f"Reported by {source_name}",
                    "url": link,
                    "country": country
                })
    return candidates


def load_existing():
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data.get("items", [])
    except Exception:
        return []

    # Retroactively scrub old entries that would fail today's confirming-keyword check
    cleaned = []
    removed = 0
    for it in items:
        platform = it.get("platform", "")
        confirm_words = AMBIGUOUS_PLATFORM_CONFIRM.get(platform)
        if confirm_words:
            title_lower = it.get("title", "").lower()
            if not any(w in title_lower for w in confirm_words):
                removed += 1
                continue
        cleaned.append(it)
    if removed:
        print(f"Cleanup: removed {removed} previously-added false-positive item(s).")
    return cleaned


def dedupe_and_merge(existing, new_items):
    seen_urls = {it.get("url") for it in existing}
    merged = list(existing)
    added = 0
    for it in new_items:
        if it["url"] in seen_urls:
            continue
        seen_urls.add(it["url"])
        merged.append(it)
        added += 1
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)
    return merged[:MAX_ITEMS], added


def main():
    existing = load_existing()
    candidates = collect_candidates()
    merged, added = dedupe_and_merge(existing, candidates)

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "items": merged
    }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Done. Added {added} new item(s). Total tracked: {len(merged)}.")


if __name__ == "__main__":
    main()
