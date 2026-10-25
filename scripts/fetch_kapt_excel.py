#!/usr/bin/env python3
"""
K-apt '공동주택 단지 기본정보' 엑셀(전국, 매주 갱신)을 받아 서울 단지의 세대수·주차·주소 등을 data/kapt.json 에 채움.
API(하루 호출 한도)를 기다리지 않고 한 번에 세대수를 채우기 위한 경로. 지하철 정보는 API(상세정보)로 계속 보강.
"""
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request

URL = "https://www.k-apt.go.kr/web/board/goKaptBasicExcelDownload.do"
CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "kapt.json")
MAX_AGE_DAYS = 7
KST = dt.timezone(dt.timedelta(hours=9))


def to_int(v):
    s = re.sub(r"[^0-9.]", "", str(v if v is not None else ""))
    try:
        return int(float(s)) if s else 0
    except ValueError:
        return 0


def download() -> bytes:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.k-apt.go.kr/"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        print(f"다운로드 {len(data):,}바이트 · {r.headers.get('Content-Type')} · {r.headers.get('Content-Disposition')}")
        return data


def rows_from(data: bytes):
    if data[:2] == b"PK":  # xlsx
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)  # read_only는 이 파일에서 행을 못 읽음
        ws = wb.worksheets[0]
        for row in ws.iter_rows(values_only=True):
            yield [("" if c is None else str(c).strip()) for c in row]
    else:
        raise RuntimeError(f"엑셀 형식이 아님: {data[:200]!r}")


def main() -> int:
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {"listFetched": None, "complexes": {}}
    today = dt.datetime.now(KST).date()
    xf = cache.get("excelFetched")
    if len(sys.argv) > 1:                       # 직접 받은 파일: python fetch_kapt_excel.py 파일.xlsx
        with open(sys.argv[1], "rb") as f:
            data = f.read()
    else:
        if xf and (today - dt.date.fromisoformat(xf)).days < MAX_AGE_DAYS and os.environ.get("FORCE") != "1":
            print(f"엑셀은 {xf}에 반영돼서 건너뜀")
            return 0
        data = download()
    it = rows_from(data)
    header, col = None, {}
    for row in it:
        if any("단지코드" in c for c in row):
            header = row
            break
    if not header:
        print("헤더(단지코드)를 찾지 못함")
        return 0
    print("컬럼:", " | ".join(header))

    def find(*keys, exclude=()):
        for i, h in enumerate(header):
            hn = h.replace(" ", "")
            if all(k in hn for k in keys) and not any(x in hn for x in exclude):
                return i
        return None

    c_code = find("단지코드")
    c_name = find("단지명")
    c_addr = find("법정동주소") if find("법정동주소") is not None else find("주소", exclude=("도로명", "관리사무소"))
    c_road = find("도로명주소")
    c_hh = find("세대수")
    c_dong = find("동수")
    c_used = find("사용승인일")
    c_heat = find("난방")
    c_builder = find("시공사")
    c_pk = find("총주차대수")
    c_pk_up = find("지상주차")
    c_pk_dn = find("지하주차")
    c_sido = find("시도")
    c_sgg = find("시군구")
    print({"code": c_code, "name": c_name, "addr": c_addr, "hh": c_hh, "pk": c_pk, "up": c_pk_up, "dn": c_pk_dn,
           "dong": c_dong, "used": c_used, "heat": c_heat, "sido": c_sido, "sgg": c_sgg})
    if c_code is None or c_hh is None:
        print("필수 컬럼(단지코드/세대수) 없음")
        return 0

    cx = cache["complexes"]
    n = 0
    for row in it:
        if len(row) <= max(c_code, c_hh):
            continue
        addr = row[c_addr] if c_addr is not None else ""
        sido = row[c_sido] if c_sido is not None else ""
        if "서울" not in (sido + addr[:6]):
            continue
        code = row[c_code]
        if not code:
            continue
        toks = addr.split()
        gu = next((t for t in toks if t.endswith("구")), row[c_sgg] if c_sgg is not None else "")
        umd, jb = "", ""
        if gu in toks:
            i = toks.index(gu)
            umd = toks[i + 1] if len(toks) > i + 1 else ""
            cand = (toks[i + 2] if len(toks) > i + 2 else "").rstrip("-")
            if re.fullmatch(r"산?\d+(-\d+)?", cand):
                jb = cand
        hh = to_int(row[c_hh])
        pk = to_int(row[c_pk]) if c_pk is not None else 0
        if not pk and c_pk_up is not None and c_pk_dn is not None:
            pk = to_int(row[c_pk_up]) + to_int(row[c_pk_dn])
        c = cx.setdefault(code, {})
        c.update({
            "name": row[c_name] if c_name is not None else c.get("name", ""),
            "gu": gu or c.get("gu", ""), "addr": addr, "umd": umd, "jibun": jb,
            "road": row[c_road] if c_road is not None else c.get("road", ""),
            "hh": hh, "pk": round(pk / hh, 2) if hh and pk else c.get("pk"),
            "dong": to_int(row[c_dong]) if c_dong is not None else c.get("dong"),
            "used": (row[c_used] or "")[:10] if c_used is not None else c.get("used", ""),
            "heat": row[c_heat] if c_heat is not None else c.get("heat", ""),
            "builder": row[c_builder] if c_builder is not None else c.get("builder", ""),
            "v": 2, "src": c.get("src") or "excel",
            "fetched": c.get("fetched") or today.isoformat(),
        })
        n += 1
    cache["excelFetched"] = today.isoformat()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    print(f"엑셀에서 서울 단지 {n}개 반영")
    return 0


if __name__ == "__main__":
    sys.exit(main())
