(() => {
  const GUS = ["종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구","은평구","서대문구","마포구","양천구","강서구","구로구","금천구","영등포구","동작구","관악구","서초구","강남구","송파구","강동구"];
  const PAGE = 60;
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k){ try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
    set(k,v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };

  let RAW = [], META = null, RATE = window.RULES.defaultRate, shown = PAGE;
  let ROWS = [];                      // 현재 직거래 설정으로 계산된 단지 목록
  const selGu = new Set(store.get("gu") || []);

  const won = (m) => {               // 만원 → "7억 6,000만"
    if (m == null || Number.isNaN(m)) return "–";
    const neg = m < 0; m = Math.round(Math.abs(m));
    const eok = Math.floor(m / 10000), man = m % 10000;
    const s = !eok ? `${man.toLocaleString()}만` : man ? `${eok}억 ${man.toLocaleString()}만` : `${eok}억`;
    return (neg ? "-" : "") + s;
  };
  const pyeong = (a) => (a / 3.3058).toFixed(1);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const median = (xs) => {
    if (!xs.length) return null;
    const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
    return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
  };
  const distKm = (a, b, c, d) => {
    const r = 6371, p1 = a * Math.PI / 180, p2 = c * Math.PI / 180;
    const dp = p2 - p1, dl = (d - b) * Math.PI / 180;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * r * Math.asin(Math.sqrt(h));
  };
  const isoMinus = (d, days) => new Date(d.getTime() - days * 864e5).toISOString().slice(0, 10);

  // ------------------------------------------------ 직거래 포함 여부에 따라 통계 계산
  function compute() {
    const withDirect = $("direct").checked;
    const ref = new Date(META.generatedAt);
    const d90 = isoMinus(ref, 90), d180 = isoMinus(ref, 180);
    ROWS = [];
    for (const it of RAW) {
      const ts = withDirect ? it.t : it.t.filter((x) => !x[3]);
      if (!ts.length) continue;
      const p3 = ts.filter((x) => x[0] >= d90).map((x) => x[1]);
      const pp = ts.filter((x) => x[0] < d90 && x[0] >= d180).map((x) => x[1]);
      const s3 = median(p3), s6 = median(ts.map((x) => x[1]));
      const price = s3 ?? s6;
      const W = window.RULES.work;
      const wk = it.lat ? distKm(it.lat, it.lng, W.lat, W.lng) : null;
      const walk = it.sm != null ? Math.round(it.sm * window.RULES.walkFactor / window.RULES.walkMPerMin) : null;
      ROWS.push({
        ...it, ts, s3, s6, wk, walk, c3: p3.length, c6: ts.length, sp: median(pp), price,
        lo: p3.length ? Math.min(...p3) : null, hi: p3.length ? Math.max(...p3) : null,
        nd: it.t.filter((x) => x[3]).length,
        jr: it.j && price ? Math.round(it.j / price * 1000) / 10 : null,
        tr: s3 && median(pp) ? (s3 - median(pp)) / median(pp) * 100 : null,
      });
    }
    assessAll();
  }

  // ------------------------------------------------ 대출 계산기
  const CFIELDS = ["income","cash","debt","rtype","term","radj","first","newlywed"];
  const savedC = store.get("calc") || {};
  CFIELDS.forEach((f) => {
    const el = $(f);
    if (savedC[f] != null) el.type === "checkbox" ? (el.checked = savedC[f]) : (el.value = savedC[f]);
    el.addEventListener("input", () => {
      const o = {}; CFIELDS.forEach((k) => { const e = $(k); o[k] = e.type === "checkbox" ? e.checked : e.value; });
      store.set("calc", o); assessAll(); renderCalc(); render();
    });
  });
  if (savedC.income) $("calcBox").open = true;

  function profile() {
    const n = (id) => parseFloat($(id).value);
    if (!(n("income") > 0) || !(n("cash") >= 0) || $("cash").value === "") return null;
    return { income: n("income"), cash: n("cash"), debt: n("debt") || 0, rtype: $("rtype").value,
             term: +$("term").value, first: $("first").checked, newlywed: $("newlywed").checked };
  }
  const rate = () => RATE.base + (parseFloat($("radj").value) || 0);

  function assessAll() {
    const p = profile(), r = rate();
    for (const row of ROWS) row.L = p ? Loan.assess(row.price, row.a, p, r) : null;
  }

  function renderCalc() {
    const p = profile(), r = rate(), band = window.RULES.rateBand;
    const rateTxt = `${r.toFixed(2)}% <span class="muted">(${(r - band).toFixed(1)}~${(r + band).toFixed(1)}%)</span>`;
    if (!p) {
      $("calcOut").innerHTML = `<div class="stat"><div class="k">예상 대출금리</div><div class="v">${rateTxt}</div></div>`;
      $("calcHint").textContent = "입력하면 단지마다 매수 가능 여부가 표시돼요";
    } else {
      const d = Loan.dsrLimit(p, r);
      const mp = Loan.maxPrice(p, r);
      const ex = Loan.assess(mp, 84, p, r);
      $("calcOut").innerHTML = `
        <div class="stat"><div class="k">예상 대출금리</div><div class="v">${rateTxt}</div></div>
        <div class="stat"><div class="k">소득 기준(DSR) 최대 대출</div><div class="v">${won(Math.floor(d.amount / 100) * 100)}</div><div class="k">심사용 금리 ${d.stress.toFixed(2)}% 적용</div></div>
        <div class="stat"><div class="k">살 수 있는 최대 집값 (84㎡ 기준)</div><div class="v">약 ${won(mp)}</div><div class="k">대출 ${won(ex.maxLoan)} · 부대비용 ${won(ex.costs)}</div></div>
        <div class="stat"><div class="k">그때 월 상환액 (${p.term}년 원리금균등)</div><div class="v">${won(Math.round(ex.monthly))}</div><div class="k">월 소득의 ${Math.round(ex.monthlyRatio * 100)}%</div></div>`;
      $("calcHint").textContent = `최대 약 ${won(mp)} · 월 ${won(Math.round(ex.monthly))} 상환`;
    }
    const R = window.RULES;
    $("calcNote").innerHTML = `
      예상 금리 = ${esc(RATE.source)} ${esc(RATE.ym)} 평균 ${RATE.base.toFixed(2)}% + 직접 입력한 가감. 실제 금리는 은행·신용·우대조건에 따라 달라져요.<br>
      대출 한도 = ① LTV ${R.ltv.normal * 100}%(생애최초 ${R.ltv.firstHome * 100}%) ② 집값별 상한(15억 이하 6억 · 25억 이하 4억 · 초과 2억) ③ DSR ${R.dsr * 100}%(심사 때 금리에 스트레스 ${R.stressRate}%p × 변동 100% · 혼합 80% · 주기형 40% 가산) 중 가장 작은 값.<br>
      필요 자기자금은 대출을 최대로 받는다고 가정한 값이에요(여유가 있으면 덜 빌려 월 상환을 줄일 수 있어요). 부대비용 = 취득세·지방교육세(·85㎡ 초과 농특세) + 중개보수 상한(부가세 포함) + 기타 ${R.etcCostRate * 100}%. 서울 아파트는 토지거래허가구역이라 실거주 의무가 있어요. 입력값은 이 브라우저에만 저장돼요.`;
  }

  // ------------------------------------------------ 나만의 점수
  const WEIGHTS = [
    ["price", "가격(쌀수록)", 3], ["work", "여의도역 거리", 3], ["walk", "지하철역 도보", 3],
    ["hh", "세대수", 2], ["age", "신축", 2], ["pk", "주차", 1],
  ];
  const LEVEL = ["안 봄", "조금", "보통", "중요", "매우", "최우선"];
  const savedW = store.get("weights") || {};
  $("wGrid").innerHTML = WEIGHTS.map(([k, label, d]) =>
    `<label class="w-item"><span class="w-head"><span>${label}</span><b id="wv_${k}"></b></span><input type="range" min="0" max="5" step="1" id="w_${k}" value="${savedW[k] ?? d}"></label>`).join("");
  const weights = () => Object.fromEntries(WEIGHTS.map(([k]) => [k, +$("w_" + k).value]));
  const showW = () => WEIGHTS.forEach(([k]) => { $("wv_" + k).textContent = LEVEL[+$("w_" + k).value]; });
  showW();
  WEIGHTS.forEach(([k]) => $("w_" + k).addEventListener("input", () => {
    store.set("weights", weights()); showW(); if ($("sort").value !== "score") { $("sort").value = "score"; saveF(); }
    shown = PAGE; render();
  }));
  if (Object.keys(savedW).length) $("scoreBox").open = true;

  const lin = (v, best, worst) => v == null ? null : Math.max(0, Math.min(100, (v - worst) / (best - worst) * 100));
  function scoreAll(list) {
    const w = weights();
    const prices = list.map((x) => x.price).sort((a, b) => a - b);
    const rank = (p) => {                       // 가격 백분위(싼 쪽이 100)
      let lo = 0, hi = prices.length;
      while (lo < hi) { const m = (lo + hi) >> 1; prices[m] < p ? (lo = m + 1) : (hi = m); }
      return prices.length > 1 ? 100 - lo / (prices.length - 1) * 100 : 100;
    };
    const year = new Date(META.generatedAt).getFullYear();
    for (const it of list) {
      const part = {
        price: rank(it.price),
        work: lin(it.wk, 3, 20),
        walk: lin(it.walk, 5, 20),
        hh: it.hh ? lin(Math.log10(it.hh), Math.log10(3000), 2) : 0,   // 세대수 정보 없음 = 대부분 150세대 미만 소규모 → 0점
        age: it.b ? lin(year - it.b, 5, 35) : null,
        pk: lin(it.pk, 1.5, 0.5),
      };
      let sum = 0, ws = 0;
      for (const [k, v] of Object.entries(part)) if (v != null && w[k]) { sum += v * w[k]; ws += w[k]; }
      it.part = part;
      it.sc = ws ? Math.round(sum / ws) : null;
    }
  }

  // ------------------------------------------------ 데이터 기준 표시
  function renderFresh() {
    const m = META, box = $("fresh");
    const gen = new Date(m.generatedAt);
    const max = Math.max(...m.months.map((x) => x.trade), 1);
    const ym = (d) => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}`;
    const partialSet = new Set([ym(gen), ym(new Date(gen.getFullYear(), gen.getMonth() - 1, 1))]);
    const bars = m.months.map((x) => {
      const partial = partialSet.has(x.ym);
      return `<div class="bar${partial ? " partial" : ""}" title="${x.ym.slice(0,4)}년 ${+x.ym.slice(4)}월 매매 ${x.trade.toLocaleString()}건${partial ? " (신고 진행 중)" : ""}">
        <i style="height:${Math.max(3, x.trade / max * 40)}px"></i>${+x.ym.slice(4)}월</div>`;
    }).join("");
    const s = m.stats;
    box.innerHTML = `
      <div class="facts">
        <div><div class="k">데이터 수집</div><div class="v">${gen.toLocaleString("ko-KR", {month:"long", day:"numeric", hour:"2-digit", minute:"2-digit"})}</div></div>
        <div><div class="k">가장 최근 계약일</div><div class="v">${m.latestDeal}</div></div>
        <div><div class="k">매매 신고</div><div class="v">${s.tradeUsed.toLocaleString()}건</div></div>
        <div><div class="k">해제 제외 / 그중 직거래</div><div class="v">${s.cancelled.toLocaleString()} / ${s.direct.toLocaleString()}건</div></div>
      </div>
      <div class="bars" aria-label="월별 매매 신고 건수">${bars}</div>
      <div class="note">실거래는 계약 후 30일 안에 신고돼서, 빗금 친 최근 두 달은 아직 신고가 덜 들어온 상태예요. 표시 가격은 실제 계약가이고 지금 매물의 호가가 아니에요.${m.failures.length ? ` · 일부 수집 실패 ${m.failures.length}건` : ""}</div>`;
    box.hidden = false;
  }

  // ------------------------------------------------ 구 선택
  function renderGu() {
    $("gu").innerHTML = GUS.map((g) => `<button type="button" aria-pressed="${selGu.has(g)}" data-g="${g}">${g}</button>`).join("");
    $("guSummary").textContent = `구 선택: ${selGu.size ? [...selGu].join(", ") : "서울 전체"} ▾`;
  }
  $("gu").addEventListener("click", (e) => {
    const g = e.target.dataset.g; if (!g) return;
    selGu.has(g) ? selGu.delete(g) : selGu.add(g);
    store.set("gu", [...selGu]); renderGu(); shown = PAGE; render();
  });

  // ------------------------------------------------ 필터
  const FIELDS = ["q","pmin","pmax","amin","amax","bmin","hmin","wmax","kmax","cmin","sort","direct","affordable"];
  const saved = store.get("filters") || {};
  if (!saved.fv) { saved.hmin = saved.hmin || "300"; }   // 기본: 300세대 미만·세대수 정보 없는 단지 숨김
  FIELDS.forEach((f) => {
    const el = $(f);
    if (saved[f] != null) el.type === "checkbox" ? (el.checked = saved[f]) : (el.value = saved[f]);
    el.addEventListener("input", () => { shown = PAGE; saveF(); if (f === "direct") compute(); render(); });
  });
  function saveF(){ const o = { fv: 2 }; FIELDS.forEach((f) => { const e = $(f); o[f] = e.type === "checkbox" ? e.checked : e.value; }); store.set("filters", o); }
  $("reset").addEventListener("click", () => {
    FIELDS.forEach((f) => { const e = $(f); e.type === "checkbox" ? (e.checked = false) : (e.value = ""); });
    $("cmin").value = "1"; $("hmin").value = "300"; $("sort").value = "score";
    selGu.clear(); store.set("gu", []); renderGu(); saveF(); compute(); shown = PAGE; render();
  });

  const numv = (id) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : null; };

  function filtered() {
    const q = $("q").value.trim().replace(/\s+/g, "");
    const pmin = numv("pmin"), pmax = numv("pmax"), amin = numv("amin"), amax = numv("amax"),
      bmin = numv("bmin"), hmin = numv("hmin"), wmax = numv("wmax"), kmax = numv("kmax"), cmin = numv("cmin") ?? 0, aff = $("affordable").checked;
    const out = ROWS.filter((it) => {
      if (selGu.size && !selGu.has(it.g)) return false;
      if (q && !(it.n + it.d).replace(/\s+/g, "").includes(q)) return false;
      if (pmin != null && it.price < pmin * 10000) return false;
      if (pmax != null && it.price > pmax * 10000) return false;
      if (amin != null && it.a < amin) return false;
      if (amax != null && it.a > amax) return false;
      if (bmin != null && (it.b ?? 0) < bmin) return false;
      if (hmin != null && (it.hh ?? 0) < hmin) return false;
      if (wmax != null && (it.walk == null || it.walk > wmax)) return false;
      if (kmax != null && (it.wk == null || it.wk > kmax)) return false;
      if (it.c3 < cmin) return false;
      if (aff && it.L && !it.L.ok) return false;
      return true;
    });
    scoreAll(out);
    const nz = (v, d) => (v == null || Number.isNaN(v) ? d : v);
    const cmp = {
      score: (a, b) => nz(b.sc, -1) - nz(a.sc, -1),
      s3a: (a, b) => a.price - b.price,
      s3d: (a, b) => b.price - a.price,
      needa: (a, b) => nz(a.L?.needCash, a.price) - nz(b.L?.needCash, b.price),  // 대출 최대 기준
      hhd: (a, b) => nz(b.hh, -1) - nz(a.hh, -1),
      walka: (a, b) => nz(a.walk, 1e9) - nz(b.walk, 1e9),
      worka: (a, b) => nz(a.wk, 1e9) - nz(b.wk, 1e9),
      c3d: (a, b) => b.c3 - a.c3 || b.c6 - a.c6,
      lastd: (a, b) => b.ts[0][0].localeCompare(a.ts[0][0]),
      trendd: (a, b) => nz(b.tr, -1e9) - nz(a.tr, -1e9),
      trenda: (a, b) => nz(a.tr, 1e9) - nz(b.tr, 1e9),
      jrd: (a, b) => nz(b.jr, -1) - nz(a.jr, -1),
      ppa: (a, b) => a.price / a.a - b.price / b.a,
    }[$("sort").value] || (() => 0);
    return out.sort(cmp);
  }

  // ------------------------------------------------ 카드
  const BIND = { ltv: "LTV", cap: "집값별 상한", dsr: "소득(DSR)" };
  function loanBox(it) {
    const L = it.L; if (!L) return "";
    const head = L.ok
      ? `<span class="verdict">매수 가능</span> · 자기자금 ${won(L.margin)} 여유`
      : `<span class="verdict">자기자금 ${won(-L.margin)} 부족</span>`;
    return `<div class="loan ${L.ok ? "ok" : "no"}">${head}${L.policy ? '<span class="tag blue">정책대출 검토 대상</span>' : ""}
      <div class="sub">최대 대출 ${won(L.maxLoan)}(${BIND[L.bind]} 기준) · 부대비용 ${won(L.costs)} · 필요 자기자금 ${won(L.needCash)}
      · 최대 대출 시 월 상환 <b>${won(Math.round(L.monthly))}</b>${L.monthlyRatio != null ? ` (월소득의 ${Math.round(L.monthlyRatio * 100)}%)` : ""}</div></div>`;
  }

  function scoreTip(it) {
    const names = Object.fromEntries(WEIGHTS.map(([k, l]) => [k, l]));
    return Object.entries(it.part || {}).map(([k, v]) => `${names[k]} ${v == null ? "정보 없음" : Math.round(v) + "점"}`).join(" · ");
  }

  function card(it) {
    const trTxt = it.tr == null ? `<span class="muted">비교 불가</span>` :
      `<b class="${it.tr >= 0 ? "up" : "down"}">${it.tr >= 0 ? "▲" : "▼"} ${Math.abs(it.tr).toFixed(1)}%</b>`;
    const last = it.ts[0];
    const q = encodeURIComponent(`${it.g} ${it.d} ${it.n}`);
    const rows = it.t.slice(0, 15).map(([d, p, f, dir]) =>
      `<tr class="${dir ? "dir" : ""}"><td>${d}</td><td>${won(p)}</td><td>${f}층</td><td>${dir ? "직거래" : ""}</td></tr>`).join("");
    const cx = [
      it.hh ? `${it.hh.toLocaleString()}세대` : null,
      it.dc ? `${it.dc}개동` : null,
      it.pk ? `세대당 주차 ${it.pk}대` : null,
      it.st ? `${esc(it.st)}${it.sw ? ` ${esc(it.sw)}` : ""}` : null,
      it.ht ? esc(it.ht) : null,
    ].filter(Boolean).join(" · ");
    return `<article class="card">
      <div class="top">
        <div>
          <div class="name">${esc(it.n)}${it.sc != null ? `<span class="score" title="${esc(scoreTip(it))}">${it.sc}점</span>` : ""}</div>
          <div class="loc">${esc(it.g)} ${esc(it.d)} · 전용 ${it.a}㎡ (${pyeong(it.a)}평)${it.b ? ` · ${it.b}년 준공` : ""}</div>
          ${cx ? `<div class="loc">${cx}</div>` : ""}
      ${it.sn || it.wk != null ? `<div class="loc">${it.sn ? `🚇 ${esc(it.sn)} 도보 약 ${it.walk}분(${it.sm.toLocaleString()}m)` : ""}${it.sn && it.wk != null ? " · " : ""}${it.wk != null ? `${esc(window.RULES.work.name)}까지 직선 ${it.wk.toFixed(1)}km` : ""}</div>` : ""}
        </div>
        <div class="price">
          <div class="big">${won(it.price)}</div>
          <div class="sm">${it.s3 != null ? `최근 3개월 중간값 · ${it.c3}건${it.c3 > 1 ? ` (${won(it.lo)}~${won(it.hi)})` : ""}` : `6개월 중간값 · ${it.c6}건`}
          ${it.c3 === 1 ? '<span class="tag">거래 1건</span>' : ""}</div>
        </div>
      </div>
      <div class="metrics">
        <span>최근 거래 <b>${last[0]} · ${won(last[1])} · ${last[2]}층</b>${last[3] ? ' <span class="tag">직거래</span>' : ""}</span>
        <span>직전 3개월 대비 ${trTxt}</span>
        <span>전세 <b>${won(it.j)}</b>${it.j ? ` <span class="muted">(${it.jf ? `6개월 ${it.jc6}건` : `${it.jc3}건`})</span>` : ""}</span>
        <span>전세가율 <b>${it.jr != null ? it.jr + "%" : "–"}</b></span>
        <span>㎡당 <b>${won(Math.round(it.price / it.a))}</b></span>
      </div>
      ${loanBox(it)}
      <details><summary>최근 거래 ${it.t.length}건 보기${it.nd ? ` (직거래 ${it.nd}건 포함)` : ""}</summary>
        <table><thead><tr><th>계약일</th><th>금액</th><th>층</th><th></th></tr></thead><tbody>${rows}</tbody></table>
      </details>
      <div class="links">
        ${it.lat ? `<a href="https://map.kakao.com/link/by/traffic/${encodeURIComponent(it.n.replace(/[,/]/g, " "))},${it.lat},${it.lng}/${encodeURIComponent(window.RULES.work.name)},${window.RULES.work.lat},${window.RULES.work.lng}" target="_blank" rel="noopener"><b>${esc(window.RULES.work.name)}까지 대중교통 길찾기</b></a>` : ""}
        <a href="https://map.naver.com/p/search/${q}" target="_blank" rel="noopener">네이버지도</a>
        <a href="https://m.land.naver.com/search/result/${q}" target="_blank" rel="noopener">네이버부동산 호가</a>
        <a href="https://kbland.kr/" target="_blank" rel="noopener">KB부동산</a>
        <a href="https://rt.molit.go.kr/" target="_blank" rel="noopener">국토부 실거래</a>
      </div>
    </article>`;
  }

  function render() {
    if (!META) return;
    const list = filtered();
    const okN = list.filter((x) => x.L?.ok).length;
    $("count").textContent = `조건에 맞는 단지·평형 ${list.length.toLocaleString()}개` +
      (list[0]?.L !== undefined && profile() ? ` · 그중 매수 가능 ${okN.toLocaleString()}개` : "");
    $("list").innerHTML = list.length ? list.slice(0, shown).map(card).join("") :
      `<div class="empty">조건에 맞는 단지가 없어요. 필터를 조금 넓혀 보세요.</div>`;
    $("more").hidden = list.length <= shown;
  }
  $("more").addEventListener("click", () => { shown += PAGE; render(); });

  // ------------------------------------------------ 시작
  $("workLabel").textContent = window.RULES.work.name;
  renderGu();
  renderCalc();
  Promise.all([
    fetch("data/summary.json", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
    fetch("data/rate.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(([j, rate]) => {
    if (rate && rate.base) RATE = rate;
    META = j.meta; RAW = j.items;
    renderFresh(); compute(); renderCalc(); render();
  }).catch(() => {
    $("list").innerHTML = `<div class="empty">아직 데이터가 없어요.<br>GitHub 저장소의 Actions 탭에서 ‘실거래 데이터 업데이트’를 한 번 실행하면 몇 분 뒤 채워져요.</div>`;
  });
})();
