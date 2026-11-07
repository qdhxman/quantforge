/* A-share monitor dashboard. Reads a local JSON snapshot; no backend, no CDN.
 * Baseline data comes from ashare_demo_data.js so file:// also works.
 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var num = function (x, d) { return Number(x || 0).toFixed(d === undefined ? 2 : d); };
  var money = function (x) { return "¥" + Number(x || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 }); };

  var snap = window.QF_ASHARE_SNAPSHOT || null;

  function render() {
    if (!snap || !snap.cycle) {
      $("banner").className = "banner warn";
      $("banner").textContent = "未找到监控快照。请先运行 python scripts/ashare_pipeline.py 生成 web/ashare_signals.json。";
      return;
    }
    var cyc = snap.cycle, q = cyc.quality || {}, tickets = cyc.tickets || [], signals = cyc.signals || [];
    var cls = snap.data_class || "UNKNOWN";
    var synthetic = /SYNTHETIC|OFFLINE|NOT LIVE/i.test(cls);

    $("modeBadge").textContent = snap.mode === "MONITOR_ONLY_NO_EXECUTION" ? "MONITOR ONLY · 不自动下单" : (snap.mode || "—");
    $("dataBadge").textContent = cls;
    $("dataBadge").className = "badge " + (synthetic ? "synth" : "live");
    $("feedBadge").textContent = (snap.feed && (snap.feed.source || snap.feed.feed)) || "—";

    var banner = $("banner");
    banner.className = "banner " + (synthetic ? "warn" : "ok");
    banner.innerHTML = synthetic
      ? "<strong>离线/合成演示快照，不是实时行情，不可用于任何交易决策。</strong> 当前数据类别：" + esc(cls) +
        "。真实行情接入见 docs/ashare-runbook.md；数据源不可用或质量门禁失败时，系统会抑制全部信号而不是编造数据。"
      : "<strong>数据源：" + esc(cls) + "</strong> · 生成于 " + esc(snap.generated_at || cyc.ts) +
        "。本页仅为决策支持，系统不自动下单，需人工在券商客户端复核并执行。";

    var tradable = tickets.filter(function (t) { return t.tradable && !synthetic; }).length;
    $("kpis").innerHTML = [
      ["生成时间", esc(snap.generated_at || cyc.ts || "—")],
      ["交易时段", esc(cyc.session || "—")],
      ["数据质量门禁", q.ok === true ? "PASS" : (q.ok === false ? "BLOCK" : "—")],
      ["建议单", tickets.length + " 张"],
      ["可执行", synthetic ? "0 张（演示数据）" : tradable + " 张"],
      ["告警", (cyc.alerts || []).length + " 条"]
    ].map(function (r, i) {
      var color = (i === 2 && q.ok !== true) ? ' class="down"' : "";
      return '<div class="kpi"><span>' + r[0] + '</span><b' + color + '>' + r[1] + "</b></div>";
    }).join("");

    $("ticketCount").textContent = tickets.length + " 张 · 周期 " + esc(cyc.ts || "");
    $("tickets").innerHTML = tickets.length
      ? tickets.map(function (t) { return ticketHTML(t, synthetic); }).join("")
      : '<p class="muted">本周期无买卖信号（或处于非交易时段 / 数据质量门禁拦截）。</p>';

    var errs = q.errors || [], warns = q.warnings || [];
    $("qualityLine").textContent = "质量门禁 " + (q.ok ? "通过" : "未通过") +
      " · 错误 " + errs.length + " 条 · 警告 " + warns.length + " 条 · 检查项 " +
      JSON.stringify(q.checks || {}) + (cyc.alerts && cyc.alerts.length ? " · 告警：" + cyc.alerts.join(" / ") : "");
    $("signals").innerHTML = signals.length ? signals.map(function (s) {
      var pill = s.action === "BUY" ? "buy" : (s.action === "SELL" ? "sell" : "");
      var color = s.score > 0 ? "up" : (s.score < 0 ? "down" : "muted");
      return "<tr><td class='num'><b>" + esc(s.symbol) + "</b></td>" +
        "<td><span class='pill " + pill + "'>" + esc(s.action) + "</span></td>" +
        "<td class='num " + color + "'>" + (s.score >= 0 ? "+" : "") + num(s.score, 3) + "</td>" +
        "<td class='num'>" + (s.target_weight === null ? "保持不变" : num(s.target_weight * 100, 1) + "%") + "</td>" +
        "<td class='muted'>" + esc(s.reason) + "</td></tr>";
    }).join("") : '<tr><td colspan="5" class="muted">无信号记录</td></tr>';
  }

  function ticketHTML(t, synthetic) {
    var f = t.estimated_fees || {};
    var demoOnly = synthetic || !t.tradable;
    var statusText = synthetic ? "演示 · 不可执行"
      : (t.tradable ? "可交易" : "不可交易 · 仅提示");
    var checks = (t.checks || []).map(function (c) {
      return '<div class="check"><span class="mark ' + (c.passed ? "ok" : "no") + '">' +
        (c.passed ? "✓" : "✕") + "</span><b>" + esc(c.name) + "</b><em>" + esc(c.detail) + "</em></div>";
    }).join("");
    return '<div class="ticket ' + (demoOnly ? "blocked" : "") + '">' +
      '<div class="t-top"><span class="t-sym">' + esc(t.symbol) + '</span>' +
      '<span class="t-name">' + esc(t.name) + " · " + esc(t.board) + "</span>" +
      '<span class="pill ' + (t.side === "BUY" ? "buy" : "sell") + '">' + esc(t.side) + "</span>" +
      '<span class="pill ' + (!demoOnly ? "ok" : "no") + '">' + statusText + "</span>" +
      '<span class="score ' + (t.signal_score >= 0 ? "up" : "down") + '">' +
        (t.signal_score >= 0 ? "+" : "") + num(t.signal_score, 3) + "</span></div>" +
      '<div class="t-grid">' +
        cell("最新价", num(t.last_price, 3)) +
        cell("涨停 / 跌停", num(t.limit_up, 2) + " / " + num(t.limit_down, 2)) +
        cell("建议数量", t.suggested_qty + " 股") +
        cell("建议价区间", num(t.suggested_price_low, 2) + "~" + num(t.suggested_price_high, 2)) +
        cell("预计成交额", money(t.estimated_notional)) +
        cell("预计费用", money(f.total) +
          '<small style="display:block;color:var(--muted);font-size:10px;font-weight:400">佣 ' +
          num(f.commission, 0) + " · 印 " + num(f.stamp_tax, 0) + " · 过 " + num(f.transfer_fee, 0) + "</small>") +
      "</div>" +
      '<div class="reason">' + esc(t.signal_reason) + "</div>" +
      "<details><summary>查看 11 项合规检查</summary><div class='checks'>" + checks + "</div></details>" +
      '<div class="notes">' +
        (synthetic ? "<strong>当前为合成/离线演示数据，此单据不可用于任何交易决策。</strong><br>" : "") +
        (t.notes || []).map(esc).join("<br>") +
        "<br>数据源：" + esc(t.data_source) + " · 快照时间：" + esc(t.as_of) + "</div>" +
      "</div>";
  }
  function cell(label, value) {
    return '<div class="cell"><span>' + label + "</span><b>" + value + "</b></div>";
  }

  render();
  // Prefer a fresh JSON snapshot when served over HTTP; file:// falls back to
  // the bundled, clearly-labelled demo snapshot.
  if (typeof fetch === "function" && location.protocol !== "file:") {
    fetch("ashare_signals.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.cycle) { snap = d; render(); } })
      .catch(function () { /* keep baseline */ });
  }
})();
