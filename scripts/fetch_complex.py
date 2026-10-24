#!/usr/bin/env python3
"""
공동주택(K-apt) 단지정보 수집: 세대수, 동수, 사용승인일, 시공사, 난방, 주차대수, 지하철역/도보시간.

- 공공데이터포털 '국토교통부_공동주택 단지 목록제공 서비스' + '공동주택 기본 정보제공 서비스' 활용신청 필요
- 인증키: MOLIT_API_KEY (실거래와 같은 키)
- 단지정보는 거의 안 바뀌므로 data/kapt.json 에 저장해 두고, 없는 단지·오래된 단지만 새로 받음
- 한 번 실행에 TIME_BUDGET_MIN(기본 20분)까지만 일하고 멈춤 → 처음엔 며칠에 걸쳐 채워짐
"""
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

KST = dt.timezone(dt.timedelta(hours=9))
BASE = "https://apis.data.go.kr/1613000"
LIST_EPS = [f"{BASE}/AptListService4/getSigunguAptList4", f"{BASE}/AptListService3/getSigunguAptList3", f"{BASE}/AptListService2/getSigunguAptList"]
INFO_EPS = [  # (기본정보, 상세정보)
    (f"{BASE}/AptBasisInfoServiceV5/getAphusBassInfoV5", f"{BASE}/AptBasisInfoServiceV5/getAphusDtlInfoV5"),
    (f"{BASE}/AptBasisInfoServiceV4/getAphusBassInfoV4", f"{BASE}/AptBasisInfoServiceV4/getAphusDtlInfoV4"),
    (f"{BASE}/AptBasisInfoServiceV3/getAphusBassInfoV3", f"{BASE}/AptBasisInfoServiceV3/getAphusDtlInfoV3"),
    (f"{BASE}/AptBasisInfoService1/getAphusBassInfo", f"{BASE}/AptBasisInfoService1/getAphusDtlInfo"),
]
SEOUL = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}
CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "kapt.json")
LIST_MAX_AGE = 30     # 일
INFO_MAX_AGE = 180    # 일
SCHEMA = 2            # 저장 형식이 바뀌면 올려서 전부 다시 받음


class ApiError(RuntimeError):
    pass


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "seoul-apartment-detector/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def parse(raw: bytes):
    """JSON/XML 둘 다 처리. (결과코드, 메시지, item 목록, totalCount)"""
    text = raw.decode("utf-8", "replace").strip()
    if text.startswith("{"):
        j = json.loads(text)
        resp = j.get("response", j)
        h = resp.get("header", {})
        body = resp.get("body", {}) or {}
        items = body.get("items", body.get("item"))
        if isinstance(items, dict):
            items = items.get("item", items)
        if isinstance(items, dict):
            items = [items]
        if items is None and isinstance(body.get("item"), dict):
            items = [body["item"]]
        return str(h.get("resultCode", "")), h.get("resultMsg", ""), items or [], int(body.get("totalCount") or 0)
    root = ET.fromstring(raw)
    auth = root.findtext(".//returnAuthMsg")
    if auth:
        raise ApiError(f"{auth} ({root.findtext('.//errMsg')})")
    code = (root.findtext(".//header/resultCode") or "").strip()
    msg = root.findtext(".//header/resultMsg") or ""
    nodes = root.findall(".//items/item") or root.findall(".//body/item")
    items = [{c.tag: (c.text or "").strip() for c in n} for n in nodes]
    return code, msg, items, int((root.findtext(".//totalCount") or "0").strip() or 0)


def call(url: str, key: str, **params):
    q = urllib.parse.urlencode({"serviceKey": key, **params})
    last = None
    for attempt in range(3):
        try:
            raw = http_get(f"{url}?{q}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code == 429:
                raise ApiError("하루 호출량 소진(429) — 내일 자동 실행에서 이어서 받음")
            if e.code in (401, 403):
                try:
                    parse(raw)
                except ApiError:
                    raise
                raise ApiError(f"HTTP {e.code}: {raw[:200]!r}")
            last = f"HTTP {e.code} {raw[:160].decode('utf-8', 'replace')!r}"
            if e.code == 400:
                break
            time.sleep(2 * (attempt + 1))
            continue
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
            continue
        code, msg, items, total = parse(raw)
        if code and code not in ("00", "000"):
            raise ApiError(f"API 오류 {code}: {msg}")
        return items, total
    raise RuntimeError(f"요청 실패: {last}")


def first_working(cands, key, **params):
    errs = []
    for c in cands:
        url = c[0] if isinstance(c, tuple) else c
        try:
            call(url, key, **params)
            return c
        except Exception as e:
            errs.append(f"{url.split('/')[-2]}: {e}")
    raise ApiError("사용 가능한 엔드포인트 없음 → " + " | ".join(errs))


def to_int(v):
    """'461.0', 461.0, '1,200' 모두 처리"""
    s = re.sub(r"[^0-9.]", "", str(v if v is not None else ""))
    try:
        return int(float(s)) if s else 0
    except ValueError:
        return 0


def split_addr(addr: str, gu: str):
    """'서울특별시 성북구 길음동 1282 길음뉴타운...' → ('길음동', '1282')"""
    toks = (addr or "").split()
    if gu in toks:
        i = toks.index(gu)
        umd = toks[i + 1] if len(toks) > i + 1 else ""
        jb = (toks[i + 2] if len(toks) > i + 2 else "").rstrip("-")
        if re.fullmatch(r"산?\d+(-\d+)?", jb):
            return umd, jb
        return umd, ""
    return "", ""


def main() -> int:
    key = os.environ.get("MOLIT_API_KEY", "").strip()
    if "%" in key:
        key = urllib.parse.unquote(key)
    if not key:
        print("MOLIT_API_KEY 없음", file=sys.stderr)
        return 2
    budget = time.time() + float(os.environ.get("TIME_BUDGET_MIN", "20")) * 60
    today = dt.datetime.now(KST).date()

    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {"listFetched": None, "complexes": {}}
    cx = cache["complexes"]

    # 1) 단지 목록 (한 달에 한 번)
    try:
        list_ep = first_working(LIST_EPS, key, sigunguCode="11110", pageNo=1, numOfRows=1)
    except ApiError as e:
        print(f"[단지 목록 서비스 사용 불가] {e}\n→ 공공데이터포털에서 '공동주택 단지 목록제공 서비스' 활용신청이 필요합니다.")
        return 0
    lf = cache.get("listFetched")
    if not lf or (today - dt.date.fromisoformat(lf)).days >= LIST_MAX_AGE:
        n = 0
        for code, gu in SEOUL.items():
            page = 1
            while True:
                items, total = call(list_ep, key, sigunguCode=code, pageNo=page, numOfRows=1000)
                for it in items:
                    kc = it.get("kaptCode")
                    if not kc:
                        continue
                    c = cx.setdefault(kc, {})
                    c.update({"name": it.get("kaptName", ""), "gu": gu, "umdList": it.get("as3", ""),
                              "bjd": it.get("bjdCode", "")})
                    n += 1
                if page * 1000 >= total or not items:
                    break
                page += 1
        cache["listFetched"] = today.isoformat()
        print(f"단지 목록 {n}개")

    # 2) 기본·상세 정보 (없는 것, 오래된 것만)
    try:
        sample = next(iter(cx))
        bas_ep, dtl_ep = first_working(INFO_EPS, key, kaptCode=sample)
    except StopIteration:
        print("단지 목록이 비어 있음")
        return 0
    except ApiError as e:
        print(f"[기본정보 서비스 사용 불가] {e}\n→ '공동주택 기본 정보제공 서비스' 활용신청이 필요합니다.")
        save(cache)
        return 0

    todo = [k for k, c in cx.items()
            if c.get("v") != SCHEMA or not c.get("addr")
            or (today - dt.date.fromisoformat(c["fetched"])).days >= INFO_MAX_AGE]
    print(f"정보 받을 단지 {len(todo)}개 (전체 {len(cx)}개)")
    lock = threading.Lock()
    done = 0
    auth_fail = []

    misses = [0]   # 연속 빈 응답 수 → 하루 호출량이 바닥난 것으로 보고 멈춤

    def work(kc):
        if time.time() > budget or auth_fail or misses[0] >= 25:
            return kc, None
        for attempt in range(3):           # 너무 빨리 부르면 빈 응답이 오기도 해서 재시도
            b, _ = call(bas_ep, key, kaptCode=kc)
            d, _ = call(dtl_ep, key, kaptCode=kc)
            if b and b[0].get("kaptAddr"):
                return kc, (b[0], d[0] if d else {})
            time.sleep(1.5 * (attempt + 1))
        return kc, None

    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(work, kc) for kc in todo]
        for fu in as_completed(futs):
            try:
                kc, res = fu.result()
            except ApiError as e:
                auth_fail.append(str(e))
                continue
            except Exception as e:
                print(f"[경고] {e}", file=sys.stderr)
                continue
            if res is None:
                misses[0] += 1
                continue
            misses[0] = 0
            b, d = res
            with lock:
                c = cx[kc]
                umd, jb = split_addr(b.get("kaptAddr", ""), c.get("gu", ""))
                hh = to_int(b.get("kaptdaCnt"))
                pk = to_int(d.get("kaptdPcnt")) + to_int(d.get("kaptdPcntu"))
                c.update({
                    "addr": b.get("kaptAddr", ""), "road": b.get("doroJuso", ""),
                    "umd": umd, "jibun": jb,
                    "hh": hh, "dong": to_int(b.get("kaptDongCnt")) or None,
                    "used": (b.get("kaptUsedate") or "")[:8], "builder": b.get("kaptBcompany", ""),
                    "heat": b.get("codeHeatNm", ""),
                    "pk": round(pk / hh, 2) if hh and pk else None,
                    "subLine": d.get("subwayLine", ""), "subSt": d.get("subwayStation", ""),
                    "subTime": d.get("kaptdWtimesub", ""), "busTime": d.get("kaptdWtimebus", ""),
                    "edu": (d.get("educationFacility") or "")[:200],
                    "fetched": today.isoformat(), "v": SCHEMA,
                })
                done += 1
                if done % 200 == 0:
                    save(cache)
                    print(f"  {done}개 저장")
    if auth_fail:
        print(f"[중단] 인증/권한 오류: {auth_fail[0]}")
    save(cache)
    if misses[0] >= 25:
        print("빈 응답이 계속돼 멈춤(하루 호출량 소진 추정) → 다음 실행에서 이어서 받음")
    left = sum(1 for c in cx.values() if c.get("v") != SCHEMA or not c.get("addr"))
    print(f"이번 실행 {done}개 수집 · 아직 남은 단지 {left}개")
    return 0


def save(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    sys.exit(main())
