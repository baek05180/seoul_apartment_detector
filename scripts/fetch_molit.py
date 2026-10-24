#!/usr/bin/env python3
"""
국토교통부 아파트 실거래가(매매 상세 + 전월세)를 받아 서울 단지·평형별 요약 JSON을 만든다.

- 인증키: 환경변수 MOLIT_API_KEY (공공데이터포털 '일반 인증키(Decoding)')
- 수집 기간: 환경변수 MONTHS (기본 6 → 이번 달 포함 최근 6개월)
- 출력: site/data/summary.json

정제 규칙
- 매매: 해제된 거래(cdealType='O') 제외, 직거래는 표시만 해 두고 화면에서 포함 여부 선택
- 단지 병합: 같은 구·같은 동·같은 단지명(공백/'아파트' 제거)은 하나로 합침
- 평형: 전용면적을 1㎡ 단위로 반올림해서 묶음
- 대표값(매매 중간값 등)은 화면에서 계산 / 전세 중간값은 여기서 계산
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
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                check(ET.fromstring(body))
            except ET.ParseError:
                pass
            last = e
            time.sleep(2 * (attempt + 1))
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
        "seq": g(item, "aptSeq"),
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
        "seq": g(item, "aptSeq"),
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


def jibun_keys(gu: str, umd: str, jibun: str) -> list:
    jibun = (jibun or "").strip()
    if not jibun:
        return []
    main = jibun.split("-")[0]
    keys = [f"{gu}|{umd}|{jibun}"]
    if main != jibun:
        keys.append(f"{gu}|{umd}|{main}")
    return keys


def load_kapt() -> dict:
    """공동주택 단지정보 캐시(fetch_complex.py가 만든 것)를 지번 키로 색인."""
    path = os.path.join(os.path.dirname(__file__), "..", "data", "kapt.json")
    try:
        with open(path, encoding="utf-8") as f:
            cx = json.load(f).get("complexes", {})
    except FileNotFoundError:
        return {}
    idx = {}
    for code, c in cx.items():
        if not c.get("hh"):
            continue
        for k in jibun_keys(c.get("gu", ""), c.get("umd", ""), c.get("jibun", "")):
            idx.setdefault(k, (code, c))
        umd = c.get("umd") or c.get("umdList", "")
        idx.setdefault(f"N|{c.get('gu')}|{umd}|{norm_name(c.get('name', '')).replace('아파트', '')}", (code, c))
    return idx


def kapt_lookup(kapt: dict, gu: str, umd: str, jbs: list, name: str):
    """지번 → 같은 동의 같은 이름 → 같은 동에서 이름이 서로 포함되는 단지(하나뿐일 때) 순으로 찾음."""
    for jb in jbs:
        for k in jibun_keys(gu, umd, jb):
            if k in kapt:
                return kapt[k]
    nm = norm_name(name).replace("아파트", "")
    hit = kapt.get(f"N|{gu}|{umd}|{nm}")
    if hit:
        return hit
    if len(nm) >= 3:
        pre = f"N|{gu}|{umd}|"
        cands = {v[0]: v for k, v in kapt.items() if k.startswith(pre) and len(k) > len(pre) + 2
                 and (nm in k[len(pre):] or k[len(pre):] in nm)}
        if len(cands) == 1:
            return next(iter(cands.values()))
    return None


def build(trades, rents, today: dt.date) -> list:
    d90 = (today - dt.timedelta(days=90)).isoformat()
    kapt = load_kapt()

    groups = {}
    seq2key = {}  # 단지 일련번호 → 병합 키 (전월세는 단지명이 다르게 신고되기도 해서 번호로 연결)
    for t in trades:
        if t["area"] <= 0 or t["price"] <= 0:
            continue
        k = (gkey(t), round(t["area"]))
        if t["seq"]:
            seq2key[t["seq"]] = gkey(t)
        grp = groups.setdefault(k, {"t": [], "r": [], "names": {}, "jibun": {}, "road": set(),
                                    "built": set(), "areas": {}})
        grp["t"].append(t)
        grp["names"][t["name"]] = grp["names"].get(t["name"], 0) + 1
        if t["jibun"]:
            grp["jibun"][t["jibun"]] = grp["jibun"].get(t["jibun"], 0) + 1
        if t["road"]:
            grp["road"].add(t["road"])
        if t["built"]:
            grp["built"].add(t["built"])
        a = round(t["area"], 2)
        grp["areas"][a] = grp["areas"].get(a, 0) + 1

    for r in rents:
        k = (seq2key.get(r["seq"]) or gkey(r), round(r["area"]))
        if k in groups:
            groups[k]["r"].append(r)

    items, matched = [], 0
    for (key, _bucket), grp in groups.items():
        sgg, umd, _ = key.split("|", 2)
        gu = SEOUL.get(sgg, sgg)
        ts = sorted(grp["t"], key=lambda x: x["date"], reverse=True)
        jeonse = [r for r in grp["r"] if r["monthly"] == 0 and r["deposit"] > 0]
        j3 = [r["deposit"] for r in jeonse if r["date"] >= d90]
        j6 = [r["deposit"] for r in jeonse]
        area = max(grp["areas"], key=grp["areas"].get)
        jbs = sorted(grp["jibun"], key=grp["jibun"].get, reverse=True)
        it = {
            "n": max(grp["names"], key=grp["names"].get),
            "g": gu,
            "d": umd,
            "a": area,
            "b": max(grp["built"]) if grp["built"] else None,
            "jb": jbs[:4],
            "rd": sorted(grp["road"])[:2],
            "j": med(j3) if j3 else med(j6), "jc3": len(j3), "jc6": len(j6),  # 전세 중간값/건수
            "jf": not j3 and bool(j6),                                       # 6개월 값으로 대체
            "wc": len([r for r in grp["r"] if r["monthly"] > 0]),
            # 6개월 매매 전부: [계약일, 금액(만원), 층, 직거래여부]
            "t": [[t["date"], t["price"], t["floor"], 1 if t["direct"] else 0] for t in ts],
        }
        # 단지정보(세대수·주차·지하철) 결합: 지번으로 찾음
        hit = kapt_lookup(kapt, gu, umd, jbs, it["n"])
        if hit:
            code, c = hit
            it.update({"kc": code, "hh": c.get("hh"), "pk": c.get("pk"), "sw": c.get("subTime") or None,
                       "st": c.get("subSt") or None, "sl": c.get("subLine") or None, "dc": c.get("dong"),
                       "hb": c.get("builder") or None, "ht": c.get("heat") or None})
            matched += 1
        items.append(it)
    items.sort(key=lambda x: (x["g"], x["d"], x["n"], x["a"]))
    print(f"단지정보 연결: {matched}/{len(items)}")
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
    # 단지정보 서비스 주소 후보 확인 (12=서비스 없음, 30=키 미등록, 000/00=정상)
    for c in ["AptBasisInfoServiceV5/getAphusBassInfoV5", "AptBasisInfoServiceV5/getAphusDtlInfoV5"]:
        for kc in ["A10045001", "A10027875"]:
            q = urllib.parse.urlencode({"serviceKey": key, "kaptCode": kc})
            try:
                raw = http_get(f"https://apis.data.go.kr/1613000/{c}?{q}")
            except urllib.error.HTTPError as e:
                raw = e.read()
            except Exception as e:
                raw = str(e).encode()
            print(f"[원문] {c} {kc}: {raw[:900].decode('utf-8', 'replace')}")
    print(f"[키 형태] 길이 {len(key)} · '%' 포함={'%' in key} · 앞뒤공백={key != key.strip()}")
    return 0


def main() -> int:
    key = os.environ.get("MOLIT_API_KEY", "").strip()
    if "%" in key:  # Encoding 키가 등록된 경우 Decoding 형태로 되돌림(이중 인코딩 방지)
        key = urllib.parse.unquote(key)
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
                        stats["direct"] += 1  # 직거래는 남겨두고 화면에서 포함 여부를 고름
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
