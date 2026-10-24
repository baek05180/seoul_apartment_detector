(() => {
  const GUS = ["종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구","은평구","서대문구","마포구","양천구","강서구","구로구","금천구","영등포구","동작구","관악구","서초구","강남구","송파구","강동구"];
  const PAGE = 60;
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k){ try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
    set(k,v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };

  let DATA = [], META = null, shown = PAGE;
  const selGu = new Set(store.get("gu") || []);

  const won = (m) => {           // 만원 → "7억 6,000만"
    if (m == null) return "–";
    const eok = Math.floor(m / 10000), man = m % 10000;
    if (!eok) return `${man.toLocaleString()}만`;
    return man ? `${eok}억 ${man.toLocaleString()}만` : `${eok}억`;
  };
  const pyeong = (a) => (a / 3.3058).toFixed(1);
  const trend = (it) => (it.s3 && it.sp ? (it.s3 - it.sp) / it.sp * 100 : null);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  // ------------------------------------------------ 데이터 기준 표시
  function renderFresh() {
    const m = META, box = $("fresh");
    const gen = new Date(m.generatedAt);
    const max = Math.max(...m.months.map((x) => x.trade), 1);
    const now = new Date(m.generatedAt);
    const thisYm = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}`;
    const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const prevYm = `${prev.getFullYear()}${String(prev.getMonth() + 1).padStart(2, "0")}`;
    const bars = m.months.map((x) => {
      const partial = x.ym === thisYm || x.ym === prevYm;
      return `<div class="bar${partial ? " partial" : ""}" title="${x.ym.slice(0,4)}년 ${+x.ym.slice(4)}월 매매 ${x.trade.toLocaleString()}건${partial ? " (신고 진행 중)" : ""}">
        <i style="height:${Math.max(3, x.trade / max * 40)}px"></i>${+x.ym.slice(4)}월</div>`;
    }).join("");
    const s = m.stats;
    box.innerHTML = `
      <div class="facts">
        <div><div class="k">데이터 수집</div><div class="v">${gen.toLocaleString("ko-KR", {month:"long", day:"numeric", hour:"2-digit", minute:"2-digit"})}</div></div>
        <div><div class="k">가장 최근 계약일</div><div class="v">${m.latestDeal}</div></div>
        <div><div class="k">반영 매매</div><div class="v">${s.tradeUsed.toLocaleString()}건</div></div>
        <div><div class="k">제외(해제/직거래)</div><div class="v">${s.cancelled.toLocaleString()} / ${s.direct.toLocaleString()}건</div></div>
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
  const FIELDS = ["q","pmin","pmax","amin","amax","bmin","cmin","sort"];
  const saved = store.get("filters") || {};
  FIELDS.forEach((f) => { if (saved[f] != null) $(f).value = saved[f]; $(f).addEventListener("input", () => { shown = PAGE; saveF(); render(); }); });
  function saveF(){ const o = {}; FIELDS.forEach((f) => o[f] = $(f).value); store.set("filters", o); }
  $("reset").addEventListener("click", () => {
    FIELDS.forEach((f) => $(f).value = ""); $("cmin").value = "1"; $("sort").value = "s3a";
    selGu.clear(); store.set("gu", []); renderGu(); saveF(); shown = PAGE; render();
  });

  const numv = (id) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : null; };

  function filtered() {
    const q = $("q").value.trim().replace(/\s+/g, "");
    const pmin = numv("pmin"), pmax = numv("pmax"), amin = numv("amin"), amax = numv("amax"), bmin = numv("bmin"), cmin = numv("cmin") ?? 0;
    const out = DATA.filter((it) => {
      const price = it.s3 ?? it.s6;
      if (selGu.size && !selGu.has(it.g)) return false;
      if (q && !(it.n + it.d).replace(/\s+/g, "").includes(q)) return false;
      if (pmin != null && price < pmin * 10000) return false;
      if (pmax != null && price > pmax * 10000) return false;
      if (amin != null && it.a < amin) return false;
      if (amax != null && it.a > amax) return false;
      if (bmin != null && (it.b ?? 0) < bmin) return false;
      if (it.c3 < cmin) return false;
      return true;
    });
    const key = $("sort").value;
    const nz = (v, d) => (v == null || Number.isNaN(v) ? d : v);
    const cmp = {
      s3a: (a, b) => nz(a.s3 ?? a.s6, 1e12) - nz(b.s3 ?? b.s6, 1e12),
      s3d: (a, b) => nz(b.s3 ?? b.s6, -1) - nz(a.s3 ?? a.s6, -1),
      c3d: (a, b) => b.c3 - a.c3 || b.c6 - a.c6,
      lastd: (a, b) => (b.t[0]?.[0] || "").localeCompare(a.t[0]?.[0] || ""),
      trendd: (a, b) => nz(trend(b), -1e9) - nz(trend(a), -1e9),
      trenda: (a, b) => nz(trend(a), 1e9) - nz(trend(b), 1e9),
      jrd: (a, b) => nz(b.jr, -1) - nz(a.jr, -1),
      ppa: (a, b) => nz((a.s3 ?? a.s6) / a.a, 1e12) - nz((b.s3 ?? b.s6) / b.a, 1e12),
    }[key] || (() => 0);
    return out.sort(cmp);
  }

  // ------------------------------------------------ 카드
  function card(it) {
    const tr = trend(it);
    const trTxt = tr == null ? `<span class="muted">비교 불가</span>` :
      `<b class="${tr >= 0 ? "up" : "down"}">${tr >= 0 ? "▲" : "▼"} ${Math.abs(tr).toFixed(1)}%</b>`;
    const hasS3 = it.s3 != null;
    const last = it.t[0];
    const q = encodeURIComponent(`${it.g} ${it.d} ${it.n}`);
    const rows = it.t.map(([d, p, f]) => `<tr><td>${d}</td><td>${won(p)}</td><td>${f}층</td></tr>`).join("");
    return `<article class="card">
      <div class="top">
        <div>
          <div class="name">${esc(it.n)}</div>
          <div class="loc">${esc(it.g)} ${esc(it.d)} · 전용 ${it.a}㎡ (${pyeong(it.a)}평)${it.b ? ` · ${it.b}년 준공` : ""}</div>
        </div>
        <div class="price">
          <div class="big">${won(hasS3 ? it.s3 : it.s6)}</div>
          <div class="sm">${hasS3 ? `최근 3개월 중간값 · ${it.c3}건${it.c3 > 1 ? ` (${won(it.lo)}~${won(it.hi)})` : ""}` : `6개월 중간값 · ${it.c6}건`}
          ${it.c3 === 1 ? '<span class="tag">거래 1건</span>' : ""}</div>
        </div>
      </div>
      <div class="metrics">
        <span>최근 거래 <b>${last ? `${last[0]} · ${won(last[1])} · ${last[2]}층` : "–"}</b></span>
        <span>직전 3개월 대비 ${trTxt}</span>
        <span>전세 <b>${won(it.j)}</b>${it.j ? ` <span class="muted">(${it.jf ? `6개월 ${it.jc6}건` : `${it.jc3}건`})</span>` : ""}</span>
        <span>전세가율 <b>${it.jr != null ? it.jr + "%" : "–"}</b></span>
        <span>㎡당 <b>${won(Math.round((it.s3 ?? it.s6) / it.a))}</b></span>
      </div>
      <details><summary>최근 거래 ${it.t.length}건 보기</summary>
        <table><thead><tr><th>계약일</th><th>금액</th><th>층</th></tr></thead><tbody>${rows}</tbody></table>
      </details>
      <div class="links">
        <a href="https://map.naver.com/p/search/${q}" target="_blank" rel="noopener">네이버지도</a>
        <a href="https://m.land.naver.com/search/result/${q}" target="_blank" rel="noopener">네이버부동산 호가</a>
        <a href="https://kbland.kr/" target="_blank" rel="noopener">KB부동산</a>
        <a href="https://rt.molit.go.kr/" target="_blank" rel="noopener">국토부 실거래</a>
      </div>
    </article>`;
  }

  function render() {
    const list = filtered();
    $("count").textContent = `조건에 맞는 단지·평형 ${list.length.toLocaleString()}개`;
    $("list").innerHTML = list.length ? list.slice(0, shown).map(card).join("") :
      `<div class="empty">조건에 맞는 단지가 없어요. 필터를 조금 넓혀 보세요.</div>`;
    $("more").hidden = list.length <= shown;
  }
  $("more").addEventListener("click", () => { shown += PAGE; render(); });

  // ------------------------------------------------ 시작
  renderGu();
  fetch("data/summary.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((j) => { META = j.meta; DATA = j.items; renderFresh(); render(); })
    .catch(() => {
      $("list").innerHTML = `<div class="empty">아직 데이터가 없어요.<br>GitHub 저장소의 Actions 탭에서 ‘실거래 데이터 업데이트’를 한 번 실행하면 몇 분 뒤 채워져요.</div>`;
    });
})();
