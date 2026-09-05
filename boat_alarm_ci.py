#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import json
import datetime
import requests
from bs4 import BeautifulSoup

TARGET_BOAT = 1
TARGET_RANK = 6  # 6位 = 6艇中もっとも遅い（標準的な意味）
NTFY_TOPIC = "tanaka-boat-alert-3958"
ALERTED_FILE = "alerted.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
BASE = "https://www.boatrace.jp/owpc/pc/race"

# 展示タイムらしき文字列だけを拾うための正規表現（例: 6.85 のような小数）
TIME_PATTERN = re.compile(r"^\d\.\d{1,2}$")


def today_str():
    return datetime.datetime.now().strftime("%Y%m%d")


def load_alerted():
    if not os.path.exists(ALERTED_FILE):
        return {"date": today_str(), "races": []}
    try:
        with open(ALERTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"date": today_str(), "races": []}
    if data.get("date") != today_str():
        return {"date": today_str(), "races": []}
    return data


def save_alerted(data):
    with open(ALERTED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_active_venues(hd):
    url = f"{BASE}/index?hd={hd}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
    except Exception as e:
        print(f"[エラー] 開催一覧の取得に失敗: {e}")
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    venues = []
    seen = set()

    for a in soup.select('a[href*="raceindex?jcd="]'):
        href = a.get("href", "")
        if "jcd=" not in href:
            continue
        jcd = href.split("jcd=")[1].split("&")[0]
        if jcd in seen:
            continue

        row = a.find_parent("tr")
        rno = None
        if row:
            text = row.get_text()
            if "発売中" in text or "以降" in text:
                m = re.search(r"(\d{1,2})R", text)
                if m:
                    rno = int(m.group(1))
        if rno:
            venues.append({"jcd": jcd, "rno": rno})
            seen.add(jcd)

    return venues


def get_exhibition_times(jcd, rno, hd):
    url = f"{BASE}/beforeinfo?rno={rno}&jcd={jcd}&hd={hd}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
    except Exception as e:
        print(f"[エラー] 直前情報の取得に失敗 (jcd={jcd}, rno={rno}): {e}")
        return None

    soup = BeautifulSoup(res.text, "html.parser")
    times = {}

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            first_text = cells[0].get_text(strip=True)
            if first_text in ["1", "2", "3", "4", "5", "6"]:
                boat_no = int(first_text)
                # 艇番セル(cells[0])自体は候補から除外し、
                # 「6.85」のような小数表記のセルだけを展示タイムとして拾う
                for c in cells[1:]:
                    t = c.get_text(strip=True)
                    if not TIME_PATTERN.match(t):
                        continue
                    val = float(t)
                    if 5.5 <= val <= 8.5 and boat_no not in times:
                        times[boat_no] = val

    return times if len(times) == 6 else None


def send_ntfy(jcd, rno, times, rank):
    msg = (f"場コード{jcd} {rno}R\n"
           f"1号艇の展示タイムが{rank}位（6艇中）です！\n{times}")
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={
                "Title": f"競艇アラーム：1号艇 展示{rank}位".encode("utf-8"),
                "Priority": "high",
                "Tags": "rotating_light",
            },
            timeout=10,
        )
        print(f"通知送信: {msg}")
    except Exception as e:
        print(f"[エラー] ntfy通知の送信に失敗: {e}")


def main():
    hd = today_str()
    alerted = load_alerted()
    alerted_set = set(alerted["races"])

    venues = get_active_venues(hd)
    print(f"開催中の場数: {len(venues)}")

    for v in venues:
        jcd, rno = v["jcd"], v["rno"]
        race_key = f"{hd}-{jcd}-{rno}"
        if race_key in alerted_set:
            continue

        times = get_exhibition_times(jcd, rno, hd)
        if not times:
            continue

        # 標準的な意味: タイムが速い(小さい)順に1位〜6位
        ranked = sorted(times.items(), key=lambda x: x[1])
        rank_map = {boat: i + 1 for i, (boat, t) in enumerate(ranked)}
        boat1_rank = rank_map.get(TARGET_BOAT)

        print(f"jcd={jcd} {rno}R 1号艇展示={times.get(1)} 順位(速い順)={boat1_rank}位  全艇={times}")

        if boat1_rank == TARGET_RANK:
            send_ntfy(jcd, rno, times, boat1_rank)
            alerted_set.add(race_key)

    alerted["races"] = list(alerted_set)
    save_alerted(alerted)


if __name__ == "__main__":
    main()

                    

