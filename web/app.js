/* QuantForge dashboard controller.
 * All computation happens locally through window.QF (engine.js).
 */
(function () {
  "use strict";
  var QF = window.QF, DATA = window.QF_DATA, PRESETS = window.QF_PRESETS;
  var $ = function (id) { return document.getElementById(id); };
  var clone = function (o) { return JSON.parse(JSON.stringify(o)); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };

  var cfg, selection, result;
  var paperN = 0, paperTarget = 20, paperHalted = false, paperTimer = null, paperExtraLog = [];
  var PAPER_START = 60, runTimer = null;

  var fmt = {
    pct: function (x, d) { return x == null ? "—" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d === undefined ? 2 : d) + "%"; },
    pctPlain: function (x, d) { return x == null ? "—" : (x * 100).toFixed(d === undefined ? 2 : d) + "%"; },
    money: function (x) { return "¥" + Number(x || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 }); },
    money2: function (x) { return "¥" + Number(x || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); },
    num: function (x, d) { return Number(x || 0).toFixed(d === undefined ? 2 : d); }
  };
  function cls(x) { return x > 0 ? "up" : (x < 0 ? "down" : "neutral"); }
  function toast(msg) {
    var t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(t._timer); t._timer = setTimeout(function () { t.classList.remove("show"); }, 2200);
  }

  // ------------------------------------------------------------------ config
  function setSelectionFromCfg() {
    selection = {};
    QF.FACTORS.forEach(function (f) { selection[f.name] = { enabled: false, weight: 1, params: {} }; });
    cfg.factors.forEach(function (f) {
      if (selection[f.name]) selection[f.name] = { enabled: true, weight: f.weight, params: f.params || {} };
    });
  }
  function cfgFromSelection() {
    cfg.factors = QF.FACTORS.filter(function (f) { return selection[f.name].enabled; })
      .map(function (f) { return { name: f.name, weight: selection[f.name].weight, params: selection[f.name].params }; });
  }

  function renderFactorList() {
    $("factorList").innerHTML = QF.FACTORS.map(function (f) {
      var s = selection[f.name];
      return '<div class="factor-item ' + (s.enabled ? "on" : "") + '" data-name="' + f.name + '">' +
        '<label class="factor-top"><input type="checkbox" data-role="enable" ' + (s.enabled ? "checked" : "") + '>' +
        '<span class="factor-name">' + esc(f.label) + '</span><span class="tag">' + esc(f.category) + '</span></label>' +
        '<div class="factor-desc">' + esc(f.description) + '</div>' +
        '<div class="factor-weight"><span>权重</span><input type="range" data-role="weight" min="0" max="2" step="0.1" value="' + s.weight + '">' +
        '<b>' + Number(s.weight).toFixed(1) + '</b></div></div>';
    }).join("");
    $("factorList").querySelectorAll(".factor-item").forEach(function (el) {
      var name = el.dataset.name;
      el.querySelector('[data-role="enable"]').addEventListener("change", function (e) {
        selection[name].enabled = e.target.checked;
        el.classList.toggle("on", e.target.checked);
        updateFactorCount(); scheduleRun();
      });
      el.querySelector('[data-role="weight"]').addEventListener("input", function (e) {
        selection[name].weight = parseFloat(e.target.value);
        el.querySelector(".factor-weight b").textContent = selection[name].weight.toFixed(1);
        scheduleRun();
      });
    });
    updateFactorCount();
  }
  function updateFactorCount() {
    var n = QF.FACTORS.filter(function (f) { return selection[f.name].enabled; }).length;
    $("factorCount").textContent = n + " / " + QF.FACTORS.length + " 已选";
  }

  function renderBlacklist() {
    var list = cfg.risk.blacklist || [];
    $("blacklistBoxes").innerHTML = cfg.symbols.map(function (s) {
      return '<label><input type="checkbox" value="' + s + '" ' + (list.indexOf(s) >= 0 ? "checked" : "") + '>' + s + '</label>';
    }).join("");
    $("blacklistBoxes").querySelectorAll("input").forEach(function (el) {
      el.addEventListener("change", function () {
        cfg.risk.blacklist = Array.prototype.slice.call($("blacklistBoxes").querySelectorAll("input:checked")).map(function (x) { return x.value; });
        scheduleRun();
      });
    });
  }

  var RANGES = [
    ["buyThreshold", "buyThresholdVal", "signal", "buy_threshold", function (v) { return v.toFixed(2); }],
    ["sellThreshold", "sellThresholdVal", "signal", "sell_threshold", function (v) { return v.toFixed(2); }],
    ["smoothing", "smoothingVal", "signal", "smoothing", function (v) { return v.toFixed(2); }],
    ["minHolding", "minHoldingVal", "signal", "min_holding_bars", function (v) { return String(v); }],
    ["commissionBps", "commissionBpsVal", "backtest", "commission_bps", function (v) { return v + " bps"; }],
    ["slippageBps", "slippageBpsVal", "backtest", "slippage_bps", function (v) { return v + " bps"; }],
    ["maxPositionPct", "maxPositionPctVal", "risk", "max_position_pct", function (v) { return (v * 100).toFixed(0) + "%"; }],
    ["maxDailyLossPct", "maxDailyLossPctVal", "risk", "max_daily_loss_pct", function (v) { return (v * 100).toFixed(0) + "%"; }],
    ["maxDrawdownPct", "maxDrawdownPctVal", "risk", "max_drawdown_pct", function (v) { return (v * 100).toFixed(0) + "%"; }],
    ["cooldownBars", "cooldownBarsVal", "risk", "cooldown_bars", function (v) { return String(v); }]
  ];

  function syncUI() {
    RANGES.forEach(function (r) {
      var v = cfg[r[2]][r[3]]; $(r[0]).value = v; $(r[1]).textContent = r[4](Number(v));
    });
    $("combineMethod").value = cfg.signal.combine_method;
    $("initialCash").value = cfg.backtest.initial_cash;
    $("maxOrderNotional").value = cfg.risk.max_order_notional;
    $("killSwitch").checked = !!cfg.risk.kill_switch;
    $("presetDesc").textContent = cfg.description || "";
    renderFactorList(); renderBlacklist();
  }

  function bindControls() {
    RANGES.forEach(function (r) {
      $(r[0]).addEventListener("input", function (e) {
        var v = parseFloat(e.target.value); cfg[r[2]][r[3]] = v;
        if (r[3] === "max_position_pct") cfg.backtest.max_position_pct = v;
        $(r[1]).textContent = r[4](v); scheduleRun();
      });
    });
    $("combineMethod").addEventListener("change", function (e) { cfg.signal.combine_method = e.target.value; scheduleRun(); });
    $("initialCash").addEventListener("change", function (e) {
      cfg.backtest.initial_cash = Math.max(1000, parseFloat(e.target.value) || 100000); scheduleRun();
    });
    $("maxOrderNotional").addEventListener("change", function (e) {
      cfg.risk.max_order_notional = Math.max(1000, parseFloat(e.target.value) || 30000); scheduleRun();
    });
    $("killSwitch").addEventListener("change", function (e) {
      cfg.risk.kill_switch = e.target.checked;
      if (e.target.checked) { paperHalted = true; stopPaperTimer(); }
      syncHaltButton(); scheduleRun();
    });
    $("presetSelect").addEventListener("change", function (e) { applyPreset(e.target.value); });
    $("allFactors").addEventListener("click", function () {
      QF.FACTORS.forEach(function (f) { selection[f.name].enabled = true; }); renderFactorList(); scheduleRun();
    });
    $("clearFactors").addEventListener("click", function () {
      QF.FACTORS.forEach(function (f) { selection[f.name].enabled = false; }); renderFactorList();
      toast("至少保留一个因子才能回测");
    });
    $("runBtn").addEventListener("click", function () { runBacktest(); });
    $("resetBtn").addEventListener("click", function () { applyPreset($("presetSelect").value); });
  }

  function scheduleRun() {
    clearTimeout(runTimer);
    runTimer = setTimeout(function () { runBacktest(true); }, 220);
  }

  function applyPreset(key) {
    cfg = clone(PRESETS[key]);
    setSelectionFromCfg(); paperN = 0; paperHalted = false; paperExtraLog = [];
    syncUI(); syncHaltButton(); runBacktest();
  }

  // ------------------------------------------------------------------ backtest
  function runBacktest(keepPaperState) {
    cfgFromSelection();
    if (!cfg.factors.length) {
      $("kpiGrid").innerHTML = '<div class="card" style="grid-column:1/-1;color:var(--muted)">请至少选择一个因子后再运行回测。</div>';
      return;
    }
    try { result = QF.backtest(cfg, DATA.data); }
    catch (e) { toast("回测失败：" + e.message); return; }
    stopPaperTimer();
    if (!keepPaperState) { /* explicit run keeps the playback cursor */ }
    renderAll(); renderPaper();
  }

  function renderAll() {
    renderKPIs(); renderEquityChart(result.equity_curve); renderDrawdown(result.equity_curve);
    renderImpact(); renderSignals(); renderTrades(); renderBlocks(); renderTradeoff();
  }

  function kpi(label, value, sub, color) {
    return '<div class="kpi"><div class="kpi-label">' + label + '</div>' +
      '<div class="kpi-value ' + (color || "neutral") + '">' + value + '</div>' +
      '<div class="kpi-sub">' + sub + '</div></div>';
  }
  function renderKPIs() {
    var m = result.metrics;
    $("kpiGrid").innerHTML = [
      kpi("总收益", fmt.pct(m.total_return), "同期等权买入持有 " + fmt.pct(m.buy_hold_return), cls(m.total_return)),
      kpi("年化收益 CAGR", fmt.pct(m.cagr), "年化波动率 " + fmt.pctPlain(m.annual_volatility), cls(m.cagr)),
      kpi("夏普比率", fmt.num(m.sharpe, 2), "索提诺 " + fmt.num(m.sortino, 2) + " · Calmar " + fmt.num(m.calmar, 2), cls(m.sharpe)),
      kpi("最大回撤", fmt.pctPlain(m.max_drawdown), "买入持有 " + fmt.pctPlain(m.buy_hold_max_drawdown), "down"),
      kpi("胜率", fmt.pctPlain(m.win_rate), "平仓 " + m.closed_trades + " 笔 · 盈亏比 " + (m.profit_factor == null ? "—" : fmt.num(m.profit_factor, 2)), "neutral"),
      kpi("成交笔数", String(m.num_trades), "手续费 " + fmt.money2(m.total_commission) + " · 滑点 " + fmt.money2(m.total_slippage), "neutral"),
      kpi("风控拦截", String(m.risk_blocks), "每笔委托逐条检查 12 条规则", m.risk_blocks > 0 ? "down" : "neutral"),
      kpi("期末权益", fmt.money(m.final_equity), "初始 " + fmt.money(m.initial_cash) + " · " + m.bars + " 根 K 线", cls(m.total_return))
    ].join("");
  }

  function renderEquityChart(curve) {
    var W = 960, H = 300, pl = 66, pr = 18, pt = 16, pb = 30;
    var pw = W - pl - pr, ph = H - pt - pb;
    var vals = [];
    curve.forEach(function (p) { vals.push(p.equity, p.benchmark); });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    var X = function (i) { return pl + i / (curve.length - 1) * pw; };
    var Y = function (v) { return pt + (hi - v) / (hi - lo) * ph; };
    var path = function (key) {
      return curve.map(function (p, i) { return (i ? "L" : "M") + X(i).toFixed(2) + "," + Y(p[key]).toFixed(2); }).join(" ");
    };
    var area = path("equity") + " L" + X(curve.length - 1).toFixed(2) + "," + (pt + ph) + " L" + pl + "," + (pt + ph) + " Z";
    var g = "";
    for (var k = 0; k <= 4; k++) {
      var v = lo + (hi - lo) * k / 4, yy = Y(v);
      g += '<line x1="' + pl + '" y1="' + yy.toFixed(2) + '" x2="' + (W - pr) + '" y2="' + yy.toFixed(2) + '" stroke="#eef2f8"/>' +
        '<text x="' + (pl - 9) + '" y="' + (yy + 4).toFixed(2) + '" text-anchor="end" font-size="11" fill="#8391a5">' + (v / 1000).toFixed(0) + 'k</text>';
    }
    for (var q = 0; q <= 4; q++) {
      var idx = Math.round(q * (curve.length - 1) / 4);
      g += '<text x="' + X(idx).toFixed(2) + '" y="' + (H - 7) + '" text-anchor="middle" font-size="11" fill="#8391a5">' + curve[idx].date + '</text>';
    }
    var svg = $("equityChart");
    svg.innerHTML = '<defs><linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#d92b2b" stop-opacity=".17"/><stop offset="100%" stop-color="#d92b2b" stop-opacity="0"/></linearGradient></defs>' +
      g + '<path d="' + area + '" fill="url(#eqFill)"/>' +
      '<path d="' + path("benchmark") + '" fill="none" stroke="#94a3b8" stroke-width="1.8" stroke-dasharray="6 4"/>' +
      '<path d="' + path("equity") + '" fill="none" stroke="#d92b2b" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>' +
      '<line id="crosshair" x1="0" y1="' + pt + '" x2="0" y2="' + (pt + ph) + '" stroke="#94a3b8" stroke-dasharray="4 3" opacity="0"/>' +
      '<circle id="hoverDot" r="4.5" fill="#d92b2b" stroke="#fff" stroke-width="2" opacity="0"/>' +
      '<rect id="hoverZone" x="' + pl + '" y="' + pt + '" width="' + pw + '" height="' + ph + '" fill="transparent" style="cursor:crosshair"/>';
    var zone = $("hoverZone"), tip = $("chartTooltip"), cross = $("crosshair"), dot = $("hoverDot");
    zone.addEventListener("mousemove", function (e) {
      var rect = svg.getBoundingClientRect();
      var svgX = (e.clientX - rect.left) / rect.width * W;
      var i = Math.max(0, Math.min(curve.length - 1, Math.round((svgX - pl) / pw * (curve.length - 1))));
      var p = curve[i], xx = X(i), yy = Y(p.equity);
      cross.setAttribute("x1", xx); cross.setAttribute("x2", xx); cross.setAttribute("opacity", "1");
      dot.setAttribute("cx", xx); dot.setAttribute("cy", yy); dot.setAttribute("opacity", "1");
      tip.style.left = (xx / W * 100) + "%"; tip.style.top = (yy / H * 100) + "%";
      tip.innerHTML = '<b>' + p.date + '</b><br>策略 <b>' + fmt.money2(p.equity) + '</b><br>买入持有 ' + fmt.money2(p.benchmark) +
        '<br>回撤 <b style="color:#7fe3b6">' + fmt.pctPlain(p.drawdown) + '</b>';
      tip.style.opacity = "1";
    });
    zone.addEventListener("mouseleave", function () {
      cross.setAttribute("opacity", "0"); dot.setAttribute("opacity", "0"); tip.style.opacity = "0";
    });
  }

  function renderDrawdown(curve) {
    var W = 960, H = 110, pl = 66, pr = 18, pt = 8, pb = 18;
    var pw = W - pl - pr, ph = H - pt - pb;
    var lo = Math.min.apply(null, curve.map(function (p) { return p.drawdown; }));
    lo = Math.min(lo, -0.01) * 1.1;
    var X = function (i) { return pl + i / (curve.length - 1) * pw; };
    var Y = function (v) { return pt + (0 - v) / (0 - lo) * ph; };
    var line = curve.map(function (p, i) { return (i ? "L" : "M") + X(i).toFixed(2) + "," + Y(p.drawdown).toFixed(2); }).join(" ");
    var area = line + " L" + X(curve.length - 1).toFixed(2) + "," + pt + " L" + pl + "," + pt + " Z";
    var grid = "";
    [0, 0.5, 1].forEach(function (f) {
      var v = lo * f, yy = Y(v);
      grid += '<line x1="' + pl + '" y1="' + yy.toFixed(2) + '" x2="' + (W - pr) + '" y2="' + yy.toFixed(2) + '" stroke="#eef2f8"/>' +
        '<text x="' + (pl - 9) + '" y="' + (yy + 4).toFixed(2) + '" text-anchor="end" font-size="10" fill="#8391a5">' + (v * 100).toFixed(0) + '%</text>';
    });
    $("drawdownChart").innerHTML = grid +
      '<path d="' + area + '" fill="#0f9d68" fill-opacity=".13"/>' +
      '<path d="' + line + '" fill="none" stroke="#0f9d68" stroke-width="1.6"/>' +
      '<text x="' + (pl + 4) + '" y="' + (pt + 11) + '" font-size="10" fill="#8391a5">回撤</text>';
  }

  function renderImpact() {
    var rows = result.factor_impact;
    if (!rows.length) { $("factorImpact").innerHTML = '<p class="muted tiny">无数据</p>'; return; }
    var max = rows[0].impact || 1;
    $("factorImpact").innerHTML = rows.map(function (r) {
      var meta = QF.FACTOR_MAP[r.name] || {};
      return '<div class="impact-row"><span title="' + esc(meta.description || "") + '">' + esc(r.label) + '</span>' +
        '<div class="impact-bar"><div class="impact-fill" style="width:' + (r.impact / max * 100).toFixed(1) + '%"></div></div>' +
        '<span class="impact-pct">' + (r.share * 100).toFixed(1) + '%</span></div>';
    }).join("") + '<p class="tiny muted" style="margin-top:6px">占比高 = 该因子在组合得分中话语权大，不代表它更赚钱。</p>';
  }

  function scoreCell(s) {
    var v = s.score, w = Math.min(1, Math.abs(v)) * 50;
    var left = v >= 0 ? 50 : 50 - w;
    var color = v >= 0 ? "var(--up)" : "var(--down)";
    return '<div class="score-bar"><span class="num ' + cls(v) + '">' + (v >= 0 ? "+" : "") + v.toFixed(3) + '</span>' +
      '<span class="score-track"><i style="left:' + left.toFixed(1) + '%;width:' + w.toFixed(1) + '%;background:' + color + '"></i></span></div>';
  }
  function renderSignals() {
    var sigs = result.latest_signals || [];
    $("signalAsOf").textContent = sigs.length ? "截至 " + sigs[0].date + " 收盘 · 信号于次一交易日开盘执行" : "";
    $("signalTableBody").innerHTML = sigs.map(function (s) {
      var pill = '<span class="pill pill-' + s.action.toLowerCase() + '">' + s.action + '</span>';
      var tw = s.target_weight === null ? "保持不变" : (s.target_weight * 100).toFixed(1) + "%";
      return '<tr><td><b>' + esc(s.symbol) + '</b></td><td>' + pill + '</td><td>' + scoreCell(s) + '</td>' +
        '<td class="num">' + tw + '</td><td class="reason">' + esc(s.reason) + '</td></tr>';
    }).join("") || '<tr><td colspan="5" class="muted">无信号</td></tr>';
  }

  function renderTrades() {
    var t = result.trades.slice(-40).reverse();
    $("tradesCount").textContent = "共 " + result.trades.length + " 笔，显示最近 " + t.length + " 笔";
    $("tradesBody").innerHTML = t.map(function (x) {
      var pnl = x.pnl == null ? '<span class="muted">—</span>' :
        '<span class="' + cls(x.pnl) + ' num">' + (x.pnl >= 0 ? "+" : "") + fmt.money2(x.pnl) + '</span>';
      return '<tr><td class="num">' + x.date + '</td><td><b>' + esc(x.symbol) + '</b></td>' +
        '<td><span class="pill pill-' + (x.side === "BUY" ? "buy" : "sell") + '">' + x.side + '</span></td>' +
        '<td class="num">' + x.qty + '</td><td class="num">' + fmt.money2(x.price) + '</td><td>' + pnl + '</td></tr>';
    }).join("") || '<tr><td colspan="6" class="muted">无成交</td></tr>';
  }

  function renderBlocks() {
    var b = result.risk_events.slice(-40).reverse();
    $("blocksCount").textContent = "共 " + result.risk_events.length + " 次拦截，显示最近 " + b.length + " 条";
    var labels = {}; QF.RULES.forEach(function (r) { labels[r.rule] = r.label; });
    $("blocksBody").innerHTML = b.map(function (x) {
      var detail = (x.failed_checks || []).map(function (c) { return c.detail; }).join("；");
      return '<tr><td class="num">' + x.date + '</td><td><b>' + esc(x.symbol) + '</b></td>' +
        '<td>' + esc(x.side) + ' ' + x.qty + '</td>' +
        '<td><span class="pill pill-block">' + esc(labels[x.blocked_by] || x.blocked_by) + '</span></td>' +
        '<td class="reason">' + esc(detail) + '</td></tr>';
    }).join("") || '<tr><td colspan="5" class="muted">无拦截。试试勾选「紧急停机」或把单票仓位上限调到 5%，再运行回测。</td></tr>';
  }

  function renderTradeoff() {
    var m = result.metrics;
    $("tradeoffNote").textContent = "策略 " + fmt.pct(m.total_return) + "，等权买入持有 " + fmt.pct(m.buy_hold_return) +
      "，超额 " + fmt.pct(m.excess_return) + "；策略最大回撤 " + fmt.pctPlain(m.max_drawdown) +
      " vs 买入持有 " + fmt.pctPlain(m.buy_hold_max_drawdown) + "。样例数据含一段熊市区间，防御性因子与风控的价值主要体现为回撤压缩，而非牛市弹性。";
  }

  // ------------------------------------------------------------------ paper trading
  function stopPaperTimer() { if (paperTimer) { clearInterval(paperTimer); paperTimer = null; } }
  function syncHaltButton() {
    var btn = $("paperHaltBtn");
    btn.classList.toggle("active", paperHalted);
    btn.textContent = paperHalted ? "解除停机" : "紧急停机";
  }

  function renderPaper() {
    var sess = QF.paperSession(cfg, DATA.data, { startIndex: PAPER_START, steps: paperN });
    var status = "已模拟 " + paperN + " 个周期 · 成交 " + sess.orders.length + " 笔 · 风控拦截 " + sess.blocks.length + " 笔";
    if (paperHalted) status = "⛔ 已停机（KILL SWITCH 生效，调度循环暂停） · " + status;
    else if (paperTimer) status = "▶ 运行中 · " + status;
    else status = (paperN ? "已暂停 · " : "待运行 · ") + status;
    $("paperStatus").textContent = status;
    $("paperStatus").classList.toggle("halted", paperHalted);

    var a = sess.account;
    $("paperAccount").innerHTML = [
      ["账户权益", fmt.money2(a.equity)], ["可用现金", fmt.money2(a.cash)],
      ["总敞口", fmt.money2(a.gross_exposure)],
      ["已实现盈亏", fmt.money2(a.realized_pnl)], ["手续费", fmt.money2(a.total_commission)],
      ["成交笔数", String(a.trade_count)]
    ].map(function (r) { return '<div class="account-cell"><span>' + r[0] + '</span><b>' + r[1] + '</b></div>'; }).join("");

    var logs = sess.log.slice(-40).concat(paperExtraLog.slice(-8));
    $("paperLog").innerHTML = logs.length ? logs.map(function (l) {
      return '<div class="log-line ' + esc(l.kind) + '"><span class="date">' + esc(l.date || "") + '</span><span class="text">' + esc(l.text) + '</span></div>';
    }).join("") : '<p class="muted tiny">点击「自动跑」开始逐周期模拟。</p>';
    $("paperLog").scrollTop = $("paperLog").scrollHeight;

    renderChecks(sess);
  }

  function renderChecks(sess) {
    var labels = {}; QF.RULES.forEach(function (r) { labels[r.rule] = r.label; });
    var checks = null, title = "";
    if (sess.orders.length) { checks = sess.orders[sess.orders.length - 1].checks; title = "最近成交：" + sess.orders[sess.orders.length - 1].symbol; }
    else if (sess.blocks.length) { checks = sess.blocks[sess.blocks.length - 1].failed_checks; title = "最近拦截：" + sess.blocks[sess.blocks.length - 1].symbol; }
    if (!checks || !checks.length) {
      $("lastChecks").innerHTML = '<p class="muted tiny">尚无委托。运行后这里会显示每笔委托的 12 条规则逐条判定结果。</p>' +
        QF.RULES.map(function (r) { return '<div class="check-row"><span class="check-mark" style="background:#cbd5e1">·</span><span class="check-name">' + esc(r.label) + '</span><span class="check-detail">' + esc(r.description) + '</span></div>'; }).join("");
      return;
    }
    $("lastChecks").innerHTML = '<p class="tiny muted" style="margin-bottom:6px">' + esc(title) + '</p>' + checks.map(function (c) {
      return '<div class="check-row"><span class="check-mark ' + (c.passed ? "ok" : "no") + '">' + (c.passed ? "✓" : "✕") + '</span>' +
        '<span class="check-name">' + esc(labels[c.rule] || c.rule) + '</span><span class="check-detail">' + esc(c.detail) + '</span></div>';
    }).join("");
  }

  function bindPaper() {
    $("paperStartBtn").addEventListener("click", function () {
      if (!cfg.factors.length) { toast("请先选择因子"); return; }
      paperTarget = Math.max(1, Math.min(200, parseInt($("paperSteps").value, 10) || 20));
      if (paperN >= paperTarget) paperN = 0;
      stopPaperTimer();
      paperTimer = setInterval(function () {
        paperN += 1; renderPaper();
        if (paperN >= paperTarget) { stopPaperTimer(); renderPaper(); toast("模拟盘完成 " + paperN + " 个周期"); }
      }, 170);
      renderPaper();
    });
    $("paperStepBtn").addEventListener("click", function () { stopPaperTimer(); paperN += 1; renderPaper(); });
    $("paperResetBtn").addEventListener("click", function () {
      stopPaperTimer(); paperN = 0; paperHalted = false; paperExtraLog = [];
      $("killSwitch").checked = false; cfg.risk.kill_switch = false;
      syncHaltButton(); runBacktest(); renderPaper();
    });
    $("paperHaltBtn").addEventListener("click", function () {
      paperHalted = !paperHalted;
      stopPaperTimer();
      $("killSwitch").checked = paperHalted;
      cfg.risk.kill_switch = paperHalted;
      paperExtraLog.push({ kind: paperHalted ? "block" : "info", date: "—",
        text: paperHalted ? "ENGINE_HALT：调度循环暂停，所有新委托将被 KILL_SWITCH 拦截" : "ENGINE_RESUME：停机解除" });
      syncHaltButton(); renderPaper();
    });
  }

  // ------------------------------------------------------------------ boot
  function boot() {
    if (!QF || !DATA || !PRESETS) {
      document.body.innerHTML = '<div style="padding:40px;font-family:sans-serif">前端资源未加载完整，请确认 data.js / presets.js / engine.js 与 index.html 在同一目录。</div>';
      return;
    }
    cfg = clone(PRESETS.momentum);
    setSelectionFromCfg();
    bindControls(); bindPaper();
    syncUI(); syncHaltButton();
    runBacktest(); renderPaper();
  }
  boot();
})();
