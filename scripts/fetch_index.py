#!/usr/bin/env python3
"""
한국부동산원 R-ONE: 주간 아파트 매매가격지수(서울 25개 구) → site/data/index.json
- 인증키: REB_API_KEY (없으면 건너뜀 → 화면은 시점 보정 없이 실거래 중간값 사용)
- 화면에서 '거래 당시 지수 → 최신 지수' 비율로 과거 거래가를 오늘 시점으로 환산
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://www.reb.or.kr/r-one/openapi"
STATBL_ID = "T244183132827305"   # (주) 매매가격지수 — 주간아파트동향
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data", "index.json")
WEEKS_BACK = 40
GUS = {"종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구",
       "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구",
       "관악구", "서초구", "강남구", "송파구", "강동구"}


def get(params):
    url = f"{BASE}/SttsApiTblData.do?{urllib.parse.urlencode(params)}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "seoul-apartment-detector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"R-ONE 요청 실패: {last}")


def main() -> int:
    key = os.environ.get("REB_API_KEY", "").strip()
    if not key:
        print("REB_API_KEY 없음 → 시점 보정 건너뜀")
        return 0
    start = dt.date.today() - dt.timedelta(weeks=WEEKS_BACK)
    y, w, _ = start.isocalendar()
    series, page, total = {}, 1, None
    while True:
        j = get({"KEY": key, "Type": "json", "pIndex": page, "pSize": 1000, "STATBL_ID": STATBL_ID,
                 "DTACYCLE_CD": "WK", "START_WRTTIME": f"{y}{w:02d}"})
        body = j.get("SttsApiTblData")
        if not body:
            print(f"응답 이상: {str(j)[:300]}")
            return 0
        head = body[0].get("head", [])
        total = next((h["list_total_count"] for h in head if "list_total_count" in h), total)
        rows = body[1].get("row", []) if len(body) > 1 else []
        for r in rows:
            full = r.get("CLS_FULLNM") or ""
            name = r.get("CLS_NM") or ""
            if not full.startswith("서울") or name not in GUS or r.get("DTA_VAL") is None:
                continue
            date = (r.get("WRTTIME_DESC") or "")[:10]
            series.setdefault(name, {})[date] = round(float(r["DTA_VAL"]), 4)
        if not rows or page * 1000 >= (total or 0):
            break
        page += 1
    if len(series) < 20:
        print(f"서울 구 지수가 {len(series)}개뿐이라 저장하지 않음")
        return 0
    out = {"source": "한국부동산원 R-ONE 주간 아파트 매매가격지수", "statbl": STATBL_ID,
           "series": {g: sorted(v.items()) for g, v in sorted(series.items())}}
    out["latest"] = max(d for v in out["series"].values() for d, _ in v)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    weeks = len(next(iter(out["series"].values())))
    print(f"주간 지수 저장: 서울 {len(series)}개 구 · {weeks}주 · 최신 {out['latest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
