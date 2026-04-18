"""
Sofascore Division 3 Herrar 2026 — Scraper + JSON API
========================================================
Hämtar alla matcher och tabeller från Sofascores API
och sparar som JSON-filer som kan servas som statisk API.

Körs automatiskt via GitHub Actions varje timme 06–23.
JSON-filerna publiceras till GitHub Pages → Emergent hämtar dem.

Output-struktur (i /docs):
    api/meta.json               ← Tidsstämpel + serielista
    api/standings.json          ← Alla tabeller
    api/matches.json            ← Alla matcher (spelade + kommande)
    api/series/{id}.json        ← Per-serie (tabell + matcher)
"""

import requests
import json
import time
import os
import random
from datetime import datetime

# ─── Konfiguration ────────────────────────────────────────────────────────────

BASE_URL = "https://www.sofascore.com/api/v1"
TARGET_YEAR = 2026
OUTPUT_DIR = "docs/api"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    "Referer": "https://www.sofascore.com/",
    "Cache-Control": "no-cache",
}

WAIT_MIN = 1.5
WAIT_MAX = 3.0

# Alla 12 Division 3-serier
DIV3_TOURNAMENTS = {
    "Norra Norrland":       20959,
    "Mellersta Norrland":   20960,
    "Södra Norrland":       20963,
    "Norra Svealand":       20961,
    "Västra Svealand":      20962,
    "Östra Svealand":       20964,
    "Nordvästra Götaland":  20965,
    "Sydvästra Götaland":   20966,
    "Mellersta Götaland":   20967,
    "Nordöstra Götaland":   20968,
    "Sydöstra Götaland":    20969,
    "Södra Götaland":       20970,
}


# ─── API-lager ─────────────────────────────────────────────────────────────────

def _wait():
    time.sleep(random.uniform(WAIT_MIN, WAIT_MAX))


def api_get(endpoint: str, retries: int = 3) -> dict | None:
    url = f"{BASE_URL}{endpoint}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 403:
                wait = 30 * attempt
                print(f"  ⚠  403 Cloudflare — väntar {wait}s ({attempt}/{retries})")
                time.sleep(wait)
            elif resp.status_code == 404:
                return None
            else:
                print(f"  ⚠  HTTP {resp.status_code} ({attempt}/{retries})")
                time.sleep(5 * attempt)
        except requests.RequestException as e:
            print(f"  ✖  {e} ({attempt}/{retries})")
            time.sleep(5 * attempt)
    return None


# ─── Datahämtning ─────────────────────────────────────────────────────────────

def find_2026_season(tournament_id: int) -> dict | None:
    data = api_get(f"/unique-tournament/{tournament_id}/seasons")
    _wait()
    if not data or "seasons" not in data:
        return None
    for season in data["seasons"]:
        name = str(season.get("name", ""))
        year = str(season.get("year", ""))
        if str(TARGET_YEAR) in name or str(TARGET_YEAR) in year:
            return season
    return data["seasons"][0] if data["seasons"] else None


def fetch_standings(tid: int, sid: int) -> list[dict]:
    data = api_get(f"/unique-tournament/{tid}/season/{sid}/standings/total")
    _wait()
    if not data or "standings" not in data:
        return []
    rows = []
    for group in data["standings"]:
        for row in group.get("rows", []):
            team = row.get("team", {})
            promo = row.get("promotion", {})
            rows.append({
                "pos":          row.get("position"),
                "lag":          team.get("name"),
                "lag_id":       team.get("id"),
                "s":            row.get("matches", 0),
                "v":            row.get("wins", 0),
                "o":            row.get("draws", 0),
                "f":            row.get("losses", 0),
                "gm":           row.get("scoresFor", 0),
                "im":           row.get("scoresAgainst", 0),
                "ms":           row.get("scoresFor", 0) - row.get("scoresAgainst", 0),
                "p":            row.get("points", 0),
                "flytt":        promo.get("text", ""),
                "flytt_id":     promo.get("id"),
            })
    return rows


def fetch_all_matches(tid: int, sid: int) -> list[dict]:
    matches = []

    # Spelade
    page = 0
    while True:
        data = api_get(f"/unique-tournament/{tid}/season/{sid}/events/last/{page}")
        _wait()
        if not data or "events" not in data or not data["events"]:
            break
        for ev in data["events"]:
            matches.append(_parse(ev))
        if not data.get("hasNextPage", False):
            break
        page += 1

    # Kommande
    page = 0
    while True:
        data = api_get(f"/unique-tournament/{tid}/season/{sid}/events/next/{page}")
        _wait()
        if not data or "events" not in data or not data["events"]:
            break
        for ev in data["events"]:
            matches.append(_parse(ev))
        if not data.get("hasNextPage", False):
            break
        page += 1

    matches.sort(key=lambda m: m.get("datum") or "9999")
    return matches


def _parse(ev: dict) -> dict:
    home = ev.get("homeTeam", {})
    away = ev.get("awayTeam", {})
    hs = ev.get("homeScore", {})
    as_ = ev.get("awayScore", {})
    st = ev.get("status", {})
    ri = ev.get("roundInfo", {})
    ts = ev.get("startTimestamp")

    if ts:
        dt = datetime.fromtimestamp(ts)
        datum = dt.strftime("%Y-%m-%d")
        tid_str = dt.strftime("%H:%M")
        dag = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"][dt.weekday()]
    else:
        datum = tid_str = dag = None

    code = st.get("code", 0)
    if code == 100:   status = "Slutförd"
    elif code == 0:   status = "Ej startad"
    elif code in (6, 7): status = "Pågår"
    elif code == 70:  status = "Uppskjuten"
    elif code == 60:  status = "Inställd"
    else:             status = st.get("description", f"Okänd ({code})")

    hm = hs.get("current")
    bm = as_.get("current")

    return {
        "id":       ev.get("id"),
        "omgang":   ri.get("round"),
        "datum":    datum,
        "dag":      dag,
        "tid":      tid_str,
        "hemma":    home.get("name"),
        "hemma_id": home.get("id"),
        "borta":    away.get("name"),
        "borta_id": away.get("id"),
        "hm":       hm,
        "bm":       bm,
        "ht_hm":    hs.get("period1"),
        "ht_bm":    as_.get("period1"),
        "resultat": f"{hm}–{bm}" if hm is not None else None,
        "status":   status,
    }


# ─── Huvudflöde ────────────────────────────────────────────────────────────────

def run():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(f"{OUTPUT_DIR}/series", exist_ok=True)

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{'='*60}")
    print(f"  FOTBOLLSLIV — DIV 3 SCRAPER")
    print(f"  {now}")
    print(f"{'='*60}")

    meta_series = []
    all_standings = []
    all_matches = []

    for region, tid in sorted(DIV3_TOURNAMENTS.items()):
        full_name = f"Division 3 {region}"
        print(f"\n🏟  {full_name} (ID: {tid})")

        season = find_2026_season(tid)
        if not season:
            print(f"    ❌ Ingen säsong")
            continue

        sid = season["id"]
        print(f"    📅 Säsong: {season.get('name')} (ID: {sid})")

        # Tabell
        print(f"    📊 Tabell...")
        standings = fetch_standings(tid, sid)

        # Matcher
        print(f"    ⚽ Matcher...")
        matches = fetch_all_matches(tid, sid)

        spelade = sum(1 for m in matches if m["status"] == "Slutförd")
        kommande = sum(1 for m in matches if m["status"] == "Ej startad")
        print(f"    ✅ {len(matches)} matcher ({spelade} spelade, {kommande} kommande)")

        # Per-serie JSON
        serie_data = {
            "serie": full_name,
            "serie_id": tid,
            "sasong": season.get("name"),
            "sasong_id": sid,
            "uppdaterad": now,
            "tabell": standings,
            "matcher": matches,
            "statistik": {
                "totalt": len(matches),
                "spelade": spelade,
                "kommande": kommande,
                "mal_totalt": sum((m["hm"] or 0) + (m["bm"] or 0) for m in matches if m["status"] == "Slutförd"),
            }
        }
        if spelade > 0:
            serie_data["statistik"]["mal_per_match"] = round(
                serie_data["statistik"]["mal_totalt"] / spelade, 2
            )

        _write_json(f"{OUTPUT_DIR}/series/{tid}.json", serie_data)

        # Samla
        for row in standings:
            row["serie"] = full_name
            row["serie_id"] = tid
        all_standings.extend(standings)

        for m in matches:
            m["serie"] = full_name
            m["serie_id"] = tid
        all_matches.extend(m for m in matches)

        meta_series.append({
            "namn": full_name,
            "id": tid,
            "sasong": season.get("name"),
            "sasong_id": sid,
            "spelade": spelade,
            "kommande": kommande,
            "totalt": len(matches),
        })

    # Aggregerade filer
    _write_json(f"{OUTPUT_DIR}/standings.json", {
        "uppdaterad": now,
        "serier": len(meta_series),
        "tabeller": all_standings,
    })

    _write_json(f"{OUTPUT_DIR}/matches.json", {
        "uppdaterad": now,
        "serier": len(meta_series),
        "matcher": all_matches,
    })

    _write_json(f"{OUTPUT_DIR}/meta.json", {
        "uppdaterad": now,
        "sasong": TARGET_YEAR,
        "serier": meta_series,
        "totalt_matcher": sum(s["totalt"] for s in meta_series),
        "totalt_spelade": sum(s["spelade"] for s in meta_series),
        "totalt_kommande": sum(s["kommande"] for s in meta_series),
    })

    # Sammanfattning
    print(f"\n{'='*60}")
    print(f"  KLART — {len(meta_series)} serier skrapade")
    print(f"  {sum(s['spelade'] for s in meta_series)} spelade, "
          f"{sum(s['kommande'] for s in meta_series)} kommande")
    print(f"  Output: {OUTPUT_DIR}/")
    print(f"{'='*60}")


def _write_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"    📁 {path}")


if __name__ == "__main__":
    run()
