#!/usr/bin/env python3
"""
카카오 로컬 API로 단지 좌표·가장 가까운 지하철역을 구해 site/data/summary.json 에 넣음.
- 인증키: KAKAO_REST_KEY (없으면 건너뜀)
- 결과는 data/geo.json 에 주소별로 저장해 두고, 새 주소만 조회
- 주소: '서울특별시 {구} {동} {지번}' (실거래 신고 지번 기준)
"""
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.join(os.path.dirname(__file__), "..")
SUMMARY = os.path.join(ROOT, "site", "data", "summary.json")
CACHE = os.path.join(ROOT, "data", "geo.json")
BUDGET = time.time() + float(os.environ.get("GEO_BUDGET_MIN", "15")) * 60


class Quota(RuntimeError):
    pass


def get(key, path, **params):
    url = f"https://dapi.kakao.com{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {key}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", "replace")
            if e.code in (401, 403):
                raise Quota(f"인증/권한 오류 {e.code}: {body}")
            if e.code == 429:
                raise Quota(f"호출 한도 초과: {body}")
            time.sleep(1 + attempt)
        except Exception:
            time.sleep(1 + attempt)
    return None


def dist_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def lookup(key, addr, name):
    lat = lng = None
    j = get(key, "/v2/local/search/address.json", query=addr, size=1)
    if j and j.get("documents"):
        d = j["documents"][0]
        lat, lng = float(d["y"]), float(d["x"])
    else:  # 지번 검색 실패 시 '동 + 단지명' 키워드 검색
        q = " ".join(addr.split()[1:3] + [name])
        j = get(key, "/v2/local/search/keyword.json", query=q, size=1)
        if j and j.get("documents"):
            d = j["documents"][0]
            lat, lng = float(d["y"]), float(d["x"])
    if lat is None:
        return {"ok": False}
    out = {"ok": True, "lat": round(lat, 6), "lng": round(lng, 6)}
    s = get(key, "/v2/local/search/category.json", category_group_code="SW8",
            x=lng, y=lat, radius=3000, sort="distance", size=1)
    if s and s.get("documents"):
        d = s["documents"][0]
        out["st"] = d["place_name"].split()[0]
        out["sd"] = int(d.get("distance") or dist_m(lat, lng, float(d["y"]), float(d["x"])))
    return out


def main() -> int:
    key = os.environ.get("KAKAO_REST_KEY", "").strip()
    with open(SUMMARY, encoding="utf-8") as f:
        summary = json.load(f)
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}

    items = summary["items"]
    addr_of = lambda it: f"서울특별시 {it['g']} {it['d']} {it['jb'][0]}" if it.get("jb") else None
    need = {}
    for it in items:
        a = addr_of(it)
        if a and a not in cache:
            need.setdefault(a, it["n"])

    if key and need:
        print(f"좌표 조회할 주소 {len(need)}개 (저장된 주소 {len(cache)}개)")
        lock, stop, done = threading.Lock(), [], [0]

        def work(a, n):
            if stop or time.time() > BUDGET:
                return a, None
            return a, lookup(key, a, n)

        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(work, a, n) for a, n in need.items()]
            for fu in as_completed(futs):
                try:
                    a, res = fu.result()
                except Quota as e:
                    if not stop:
                        print(f"[중단] {e}")
                    stop.append(1)
                    continue
                if res is not None:
                    with lock:
                        cache[a] = res
                        done[0] += 1
        print(f"이번에 {done[0]}개 조회 · 남은 주소 {sum(1 for a in need if a not in cache)}개")
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    elif not key:
        print("KAKAO_REST_KEY 없음 → 저장된 좌표만 사용")

    n = 0
    for it in items:
        g = cache.get(addr_of(it) or "")
        if g and g.get("ok"):
            it["lat"], it["lng"] = g["lat"], g["lng"]
            if g.get("st"):
                it["sn"], it["sm"] = g["st"], g["sd"]   # 가까운 역 이름 / 직선거리(m)
            n += 1
    with open(SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, separators=(",", ":"))
    print(f"좌표 붙은 단지·평형 {n}/{len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
