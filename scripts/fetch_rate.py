#!/usr/bin/env python3
"""
한국은행 ECOS: 예금은행 주택담보대출 금리(신규취급액 기준, 가중평균) 최근 값 → site/data/rate.json
- 인증키: ECOS_API_KEY (없으면 아무것도 안 하고 종료 → 화면은 기본값 사용)
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data", "rate.json")
# 예금은행 가중평균금리(신규취급액) 대출 통계표 후보
STAT_CODES = ["121Y006", "121Y004"]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sad/1.0"}), timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    key = os.environ.get("ECOS_API_KEY", "").strip()
    if not key:
        print("ECOS_API_KEY 없음 → 금리는 화면 기본값 사용")
        return 0
    k = urllib.parse.quote(key)
    today = dt.date.today()
    start = f"{today.year - 1}{today.month:02d}"
    end = f"{today.year}{today.month:02d}"
    for stat in STAT_CODES:
        try:
            lst = get(f"https://ecos.bok.or.kr/api/StatisticItemList/{k}/json/kr/1/500/{stat}")
            rows = lst.get("StatisticItemList", {}).get("row", [])
            item = next((r for r in rows if r.get("ITEM_NAME", "").replace(" ", "") == "주택담보대출"), None)
            if not item:
                print(f"{stat}: 주택담보대출 항목 없음 ({lst.get('RESULT')})")
                continue
            data = get(f"https://ecos.bok.or.kr/api/StatisticSearch/{k}/json/kr/1/100/{stat}/M/{start}/{end}/{item['ITEM_CODE']}")
            pts = [(r["TIME"], float(r["DATA_VALUE"])) for r in data.get("StatisticSearch", {}).get("row", []) if r.get("DATA_VALUE")]
            if not pts:
                print(f"{stat}: 데이터 없음 ({data.get('RESULT')})")
                continue
            pts.sort()
            ym, val = pts[-1]
            out = {"base": val, "ym": f"{ym[:4]}-{ym[4:]}", "series": [[t, v] for t, v in pts[-12:]],
                   "source": f"한국은행 ECOS {stat} · {item.get('STAT_NAME', '')} · 주택담보대출(신규취급액)"}
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
            print(f"주담대 평균금리 {val}% ({out['ym']}) 저장")
            return 0
        except Exception as e:
            print(f"{stat}: 오류 {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
