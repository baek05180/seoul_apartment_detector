// 대출·비용 계산 (금액 단위: 만원, 금리: %)
(function (root) {
  const R = () => root.RULES;

  function pmt(principal, ratePct, years) {           // 원리금균등 월 상환액
    const r = ratePct / 100 / 12, n = years * 12;
    if (principal <= 0) return 0;
    if (r === 0) return principal / n;
    return principal * r / (1 - Math.pow(1 + r, -n));
  }
  function pv(monthly, ratePct, years) {                 // 월 상환액으로 빌릴 수 있는 원금
    const r = ratePct / 100 / 12, n = years * 12;
    if (monthly <= 0) return 0;
    if (r === 0) return monthly * n;
    return monthly * (1 - Math.pow(1 + r, -n)) / r;
  }

  function acquisitionTax(price, area, first) {
    let rate;
    if (price <= 60000) rate = 0.01;
    else if (price <= 90000) rate = ((price / 10000) * 2 / 3 - 3) / 100;
    else rate = 0.03;
    let tax = price * rate;
    if (first && price <= R().firstHomeReliefMaxPrice) tax = Math.max(0, tax - R().firstHomeTaxRelief);
    const edu = price * rate * 0.1;
    const rural = area > 85 ? price * 0.002 : 0;
    return { tax, edu, rural, total: tax + edu + rural };
  }

  function brokerage(price) {
    const b = R().brokerage.find(([lim]) => price < lim) || R().brokerage[R().brokerage.length - 1];
    let fee = price * b[1];
    if (b[2] != null) fee = Math.min(fee, b[2]);
    return fee * R().brokerageVat;
  }

  function capFor(price) {
    return R().caps.find(([lim]) => price <= lim)[1];
  }

  // p: {income, cash, debt, rtype, term, first, newlywed}, rate: 실제 예상 금리(%)
  function dsrLimit(p, rate) {
    const annual = p.income * R().dsr - (p.debt || 0);
    const stress = rate + R().stressRate * R().stressRatio[p.rtype];
    return { amount: pv(annual / 12, stress, p.term), stress };
  }

  function assess(price, area, p, rate) {
    const ltvRate = p.first ? R().ltv.firstHome : R().ltv.normal;
    const limits = {
      ltv: price * ltvRate,
      cap: capFor(price),
      dsr: dsrLimit(p, rate).amount,
    };
    const bind = Object.entries(limits).sort((a, b) => a[1] - b[1])[0][0];
    const maxLoan = Math.max(0, Math.floor(limits[bind] / 100) * 100);
    const acq = acquisitionTax(price, area, p.first);
    const costs = acq.total + brokerage(price) + price * R().etcCostRate;
    const needCash = price + costs - maxLoan;          // 은행 대출을 최대로 받을 때 필요한 자금(자기자금+사내대출)
    const funds = p.cash + (p.corp || 0);              // 사내대출은 DSR에 안 들어가지만 매수 자금으로 씀
    const margin = funds - needCash;
    const loanUsed = maxLoan;                           // 최대로 빌린다고 가정(여유분만큼 덜 빌리면 상환액 감소)
    const bankMonthly = pmt(loanUsed, rate, p.term);
    const corpMonthly = p.corp ? pmt(p.corp, p.corpRate, p.corpTerm) : 0;
    const monthly = bankMonthly + corpMonthly;
    const P = R().policy;
    const policy = price <= P.maxPrice && area <= P.maxArea &&
      p.income <= (p.newlywed ? P.incomeNewlywed : P.incomeFirst);
    return { ok: margin >= 0, margin, needCash, maxLoan, limits, bind, costs, acq, loanUsed, monthly, bankMonthly, corpMonthly,
             monthlyRatio: p.income ? monthly * 12 / p.income : null, policy };
  }

  // 자기자금으로 살 수 있는 최대 가격(대략, 전용 84㎡ 가정)
  function maxPrice(p, rate, area = 84) {
    let lo = 0, hi = 1000000;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      assess(mid, area, p, rate).ok ? (lo = mid) : (hi = mid);
    }
    return Math.floor(lo / 100) * 100;
  }

  root.Loan = { pmt, pv, acquisitionTax, brokerage, capFor, dsrLimit, assess, maxPrice };
})(typeof window !== "undefined" ? window : globalThis);
