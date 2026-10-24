#!/usr/bin/env python3
"""
국토교통부 아파트 실거래가(매매 상세 + 전월세)를 받아 서울 단지·평형별 요약 JSON을 만든다.

- 인증키: 환경변수 MOLIT_API_KEY (공공데이터포털 '일반 인증키(Decoding)')
- 수집 기간: 환경변수 MONTHS (기본 6 → 이번 달 포함 최근 6개월)
- 출력: site/data/summary.json

정제 규칙
- 매매: 해제된 거래(cdealType='O') 제외, 직거래 제외(가족 간 저가 거래 등 왜곡 방지)
- 단지 병합: 같은 구·같은 동·같은 단지명(공백/'아파트' 제거)은 하나로 합침
- 평형: 전용면적을 1㎡ 단위로 반올림해서 묶음
- 대표값: 평균 대신 중간값(이상치에 덜 흔들림)
"""
import datetime as dt
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

KST = dt.timezone(dt.timedelta(hours=9))

TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
RENT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

SEOUL = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}

ROWS = 1000
TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "20"))
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data", "summary.json")


class ApiError(RuntimeError):
    pass


# ---------------------------------------------------------------- HTTP
def http_get(url: str) -> bytes:
    """테스트에서 바꿔 끼울 수 있도록 분리."""
    req = urllib.request.Request(url, headers={"User-Agent": "seoul-apartment-detector/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def call(base: str, key: str, lawd: str, ymd: str, page: int) -> ET.Element:
    q = urllib.parse.urlencode({
        "serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ymd,
        "pageNo": page, "numOfRows": ROWS,
    })
    last = None
    for attempt in range(4):
        try:
            raw = http_get(f"{base}?{q}")
            root = ET.fromstring(raw)
            check(root)
            return root
        except ApiError:
            raise
        except Exception as e:  # 네트워크/일시 오류는 재시도
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 실패 {lawd} {ymd} p{page}: {last}")


def check(root: ET.Element) -> None:
    # 인증키 오류 등은 OpenAPI_ServiceResponse 형식으로 옴
    auth = root.findtext(".//returnAuthMsg")
    if auth:
        raise ApiError(f"인증 오류: {auth} (reasonCode={root.findtext('.//returnReasonCode')})")
    code = (root.findtext(".//header/resultCode") or "").strip()
    if code and code not in ("00", "000"):
        raise ApiError(f"API 오류 {code}: {root.findtext('.//header/resultMsg')}")


def fetch_all(base: str, key: str, lawd: str, ymd: str) -> list:
    items, page = [], 1
    while True:
        root = call(base, key, lawd, ymd, page)
        got = root.findall(".//items/item")
        items.extend(got)
        total = int((root.findtext(".//totalCount") or "0").strip() or 0)
        if page * ROWS >= total or not got:
            return items
        page += 1
        time.sleep(0.15)


# ---------------------------------------------------------------- 파싱
def g(item: ET.Element, *names: str) -> str:
    for n in names:
        v = item.findtext(n)
        if v is not None and v.strip() != "":
            return v.strip()
    return ""


def num(s: str) -> float:
    s = re.sub(r"[^0-9.\-]", "", s or "")
    return float(s) if s not in ("", "-", ".") else 0.0


def norm_name(s: str) -> str:
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"아파트$", "", s)


def deal_date(item) -> str:
    y = int(num(g(item, "dealYear", "년")))
    m = int(num(g(item, "dealMonth", "월")))
    d = int(num(g(item, "dealDay", "일")) or 1)
    return f"{y:04d}-{m:02d}-{d:02d}"


def parse_trade(item, sgg_code):
    cancel = g(item, "cdealType", "해제여부")
    return {
        "sgg": sgg_code,
        "umd": g(item, "umdNm", "법정동"),
        "name": g(item, "aptNm", "아파트"),
        "jibun": g(item, "jibun", "지번"),
        "road": g(item, "roadNm", "도로명"),
        "area": num(g(item, "excluUseAr", "전용면적")),
        "price": int(num(g(item, "dealAmount", "거래금액"))),  # 만원
        "floor": int(num(g(item, "floor", "층"))),
        "built": int(num(g(item, "buildYear", "건축년도"))),
        "date": deal_date(item),
        "cancelled": cancel.upper() == "O",
        "direct": g(item, "dealingGbn", "거래유형") == "직거래",
    }


def parse_rent(item, sgg_code):
    return {
        "sgg": sgg_code,
        "umd": g(item, "umdNm", "법정동"),
        "name": g(item, "aptNm", "아파트"),
        "jibun": g(item, "jibun", "지번"),
        "area": num(g(item, "excluUseAr", "전용면적")),
        "deposit": int(num(g(item, "deposit", "보증금액"))),
        "monthly": int(num(g(item, "monthlyRent", "월세금액"))),
        "built": int(num(g(item, "buildYear", "건축년도"))),
        "date": deal_date(item),
        "ctype": g(item, "contractType", "계약구분"),  # 신규/갱신
    }


# ---------------------------------------------------------------- 집계
def months_back(n: int, today: dt.date) -> list:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def gkey(r) -> str:
    return f"{r['sgg']}|{r['umd']}|{norm_name(r['name'])}"


def med(xs):
    return int(statistics.median(xs)) if xs else None


def build(trades, rents, today: dt.date) -> list:
    d90 = (today - dt.timedelta(days=90)).isoformat()
    d180 = (today - dt.timedelta(days=180)).isoformat()

    groups = {}
    for t in trades:
        if t["area"] <= 0 or t["price"] <= 0:
            continue
        k = (gkey(t), round(t["area"]))
        grp = groups.setdefault(k, {"t": [], "r": [], "names": {}, "jibun": set(), "road": set(),
                                    "built": set(), "areas": {}})
        grp["t"].append(t)
        grp["names"][t["name"]] = grp["names"].get(t["name"], 0) + 1
        if t["jibun"]:
            grp["jibun"].add(t["jibun"])
        if t["road"]:
            grp["road"].add(t["road"])
        if t["built"]:
            grp["built"].add(t["built"])
        a = round(t["area"], 2)
        grp["areas"][a] = grp["areas"].get(a, 0) + 1

    for r in rents:
        k = (gkey(r), round(r["area"]))
        if k in groups:
            groups[k]["r"].append(r)

    items = []
    for (key, _bucket), grp in groups.items():
        sgg, umd, _ = key.split("|", 2)
        ts = sorted(grp["t"], key=lambda x: x["date"], reverse=True)
        p3 = [t["price"] for t in ts if t["date"] >= d90]
        pprev = [t["price"] for t in ts if d180 <= t["date"] < d90]
        jeonse = [r for r in grp["r"] if r["monthly"] == 0 and r["deposit"] > 0]
        j3 = [r["deposit"] for r in jeonse if r["date"] >= d90]
        j6 = [r["deposit"] for r in jeonse]
        wolse = [r for r in grp["r"] if r["monthly"] > 0]

        sale3 = med(p3)
        sale6 = med([t["price"] for t in ts])
        js = med(j3) if j3 else med(j6)
        base_sale = sale3 or sale6
        area = max(grp["areas"], key=grp["areas"].get)
        items.append({
            "id": f"{key}|{round(area)}",
            "n": max(grp["names"], key=grp["names"].get),
            "g": SEOUL.get(sgg, sgg),
            "d": umd,
            "a": area,
            "b": max(grp["built"]) if grp["built"] else None,
            "jb": sorted(grp["jibun"])[:4],
            "rd": sorted(grp["road"])[:2],
            "s3": sale3, "c3": len(p3),               # 최근 3개월 매매 중간값/건수
            "s6": sale6, "c6": len(ts),               # 6개월
            "sp": med(pprev),                         # 직전 3개월(3~6개월 전) 중간값
            "lo": min(p3) if p3 else None, "hi": max(p3) if p3 else None,
            "j": js, "jc3": len(j3), "jc6": len(j6),  # 전세 중간값/건수
            "jr": round(js / base_sale * 100, 1) if js and base_sale else None,
            "jf": not j3 and bool(j6),               # 전세가 6개월 값으로 대체됐는지
            "wc": len(wolse),
            "t": [[t["date"], t["price"], t["floor"]] for t in ts[:10]],
        })
    items.sort(key=lambda x: (x["g"], x["d"], x["n"], x["a"]))
    return items


# ---------------------------------------------------------------- main
def probe(key: str) -> int:
    """접속 진단: 성북구 지난달 1건만 요청해서 응답 시간과 내용을 보여줌(키는 가림)."""
    last = (dt.datetime.now(KST).replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")
    for name, base in (("매매", TRADE_URL), ("전월세", RENT_URL)):
        q = urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": "11290", "DEAL_YMD": last, "pageNo": 1, "numOfRows": 1})
        t0 = time.time()
        try:
            raw = http_get(f"{base}?{q}")
            print(f"[{name}] {time.time()-t0:.1f}초 · {len(raw)}바이트")
            print(raw[:700].decode("utf-8", "replace").replace(key, "***"))
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode("utf-8", "replace").replace(key, "***")
            print(f"[{name}] 실패 {time.time()-t0:.1f}초: HTTP {e.code} 헤더={dict(e.headers)} 본문={body}")
        except Exception as e:
            print(f"[{name}] 실패 {time.time()-t0:.1f}초: {type(e).__name__}: {e}")
    # 키 없이도 같은 결과면 키 문제가 아니라 접속(IP) 차단
    try:
        raw = http_get(f"{TRADE_URL}?serviceKey=invalid&LAWD_CD=11290&DEAL_YMD={last}")
        print(f"[키 없이] 응답 {len(raw)}바이트: {raw[:300].decode('utf-8','replace')}")
    except urllib.error.HTTPError as e:
        print(f"[키 없이] HTTP {e.code}: {e.read()[:300].decode('utf-8','replace')}")
    except Exception as e:
        print(f"[키 없이] {type(e).__name__}: {e}")
    try:
        ip = http_get("https://api.ipify.org").decode()
        print(f"[실행 서버 IP] {ip}")
    except Exception as e:
        print(f"[실행 서버 IP] 확인 실패 {e}")
    print(f"[키 형태] 길이 {len(key)} · '%' 포함={'%' in key} · 앞뒤공백={key != key.strip()}")
    return 0


def main() -> int:
    key = os.environ.get("MOLIT_API_KEY", "").strip()
    if not key:
        print("MOLIT_API_KEY 가 비어 있습니다. GitHub 저장소 Secrets에 등록했는지 확인하세요.", file=sys.stderr)
        return 2
    if os.environ.get("PROBE") == "1":
        return probe(key)
    n_months = int(os.environ.get("MONTHS", "6"))
    now = dt.datetime.now(KST)
    today = now.date()
    yms = months_back(n_months, today)

    trades, rents = [], []
    stats = {"tradeRaw": 0, "cancelled": 0, "direct": 0, "rentRaw": 0}
    by_month = {ym: {"trade": 0, "rent": 0} for ym in yms}
    failures = []

    for lawd, gu in SEOUL.items():
        for ym in yms:
            try:
                for it in fetch_all(TRADE_URL, key, lawd, ym):
                    t = parse_trade(it, lawd)
                    stats["tradeRaw"] += 1
                    if t["cancelled"]:
                        stats["cancelled"] += 1
                        continue
                    if t["direct"]:
                        stats["direct"] += 1
                        continue
                    trades.append(t)
                    by_month[ym]["trade"] += 1
                for it in fetch_all(RENT_URL, key, lawd, ym):
                    rents.append(parse_rent(it, lawd))
                    stats["rentRaw"] += 1
                    by_month[ym]["rent"] += 1
            except ApiError as e:
                # 인증키 문제는 계속해도 소용없으니 바로 중단
                print(f"[중단] {e}", file=sys.stderr)
                return 3
            except Exception as e:
                failures.append(f"{gu} {ym}: {e}")
                print(f"[경고] {gu} {ym}: {e}", file=sys.stderr)
                if len(failures) >= 5 and not trades:
                    print("[중단] 처음부터 연속 실패 — 국토부 서버 접속 문제로 보입니다.", file=sys.stderr)
                    return 5
        print(f"{gu} 완료 (누적 매매 {len(trades)}건, 전월세 {len(rents)}건)")

    if not trades:
        print("매매 데이터가 0건이라 기존 파일을 덮어쓰지 않습니다.", file=sys.stderr)
        return 4

    if len(failures) > len(SEOUL) * len(yms) * 0.2:
        print(f"실패 {len(failures)}건으로 데이터가 불완전해 기존 파일을 유지합니다.", file=sys.stderr)
        return 1

    items = build(trades, rents, today)
    latest = max(t["date"] for t in trades)
    out = {
        "meta": {
            "generatedAt": now.isoformat(timespec="minutes"),
            "latestDeal": latest,
            "months": [{"ym": ym, **by_month[ym]} for ym in sorted(yms)],
            "stats": {**stats, "tradeUsed": len(trades), "groups": len(items)},
            "failures": failures,
        },
        "items": items,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"저장: {OUT} · 단지·평형 {len(items)}개 · 최신 계약일 {latest} · 실패 {len(failures)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
