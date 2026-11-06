/* QuantForge browser engine.
 *
 * A literal port of quantforge/{factors,signals,portfolio,risk,backtest,metrics}.py.
 * Kept dependency-free so the dashboard works offline and on a static host.
 * tests/test_js_parity.py + scripts/verify_parity.js assert the two agree.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof globalThis !== "undefined") globalThis.QF = api;
  if (typeof window !== "undefined") window.QF = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ---------------------------------------------------------------- helpers
  function mean(xs) { return xs.length ? xs.reduce(function (a, b) { return a + b; }, 0) / xs.length : 0; }
  function pstdev(xs) {
    if (!xs.length) return 0;
    var m = mean(xs), s = 0;
    for (var k = 0; k < xs.length; k++) s += (xs[k] - m) * (xs[k] - m);
    return Math.sqrt(s / xs.length);
  }
  function emaSeries(xs, period) {
    if (!xs.length) return [];
    var a = 2 / (period + 1), out = [xs[0]];
    for (var k = 1; k < xs.length; k++) out.push(a * xs[k] + (1 - a) * out[k - 1]);
    return out;
  }
  function closes(bars, i, n) { return bars.slice(i - n + 1, i + 1).map(function (b) { return b.close; }); }
  function returns(cs) {
    var o = [];
    for (var k = 1; k < cs.length; k++) if (cs[k - 1] !== 0) o.push(cs[k] / cs[k - 1] - 1);
    return o;
  }
  function trueRanges(bars, i, n) {
    var o = [];
    for (var k = i - n + 1; k <= i; k++) {
      var b = bars[k], prev = bars[k - 1];
      if (k === 0 || !prev || prev.close === 0) o.push(b.high - b.low);
      else o.push(Math.max(b.high - b.low, Math.abs(b.high - prev.close), Math.abs(b.low - prev.close)));
    }
    return o;
  }
  function tanh(x) { return Math.tanh(Math.max(-30, Math.min(30, x))); }
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
  function r2(x) { return Math.round(x * 100) / 100; }
  function r6(x) { return Math.round(x * 1e6) / 1e6; }

  // ---------------------------------------------------------------- factors
  var FACTORS = [
    { name: "momentum", label: "动量 ROC", category: "趋势", default_params: { lookback: 20 }, min_bars: 21,
      description: "N 日收益率除以同期波动率，衡量风险调整后的趋势强度",
      fn: function (bars, i, p) {
        var lb = p.lookback; if (i < lb) return null;
        var cs = closes(bars, i, lb + 1); if (cs[0] <= 0) return null;
        var ret = cs[cs.length - 1] / cs[0] - 1, vol = pstdev(returns(cs)) * Math.sqrt(lb);
        return tanh(ret / Math.max(vol, 1e-6) / 1.5);
      } },
    { name: "ma_cross", label: "均线交叉", category: "趋势", default_params: { fast: 10, slow: 30 }, min_bars: 30,
      description: "快慢均线之差相对慢均线的偏离度",
      fn: function (bars, i, p) {
        var fast = p.fast, slow = p.slow; if (i < slow || fast >= slow) return null;
        var cs = closes(bars, i, slow), maf = mean(cs.slice(-fast)), mas = mean(cs);
        return tanh((maf - mas) / Math.max(mas, 1e-9) * 12);
      } },
    { name: "rsi", label: "RSI 超买超卖", category: "反转", default_params: { period: 14 }, min_bars: 15,
      description: "RSI 相对 50 中轴的反向偏离：超卖给正分、超买给负分",
      fn: function (bars, i, p) {
        var period = p.period; if (i < period) return null;
        var cs = closes(bars, i, period + 1), gains = [], losses = [];
        for (var k = 1; k < cs.length; k++) { var d = cs[k] - cs[k - 1]; gains.push(Math.max(d, 0)); losses.push(Math.max(-d, 0)); }
        var ag = mean(gains), al = mean(losses), rsi = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
        return tanh((50 - rsi) / 50);
      } },
    { name: "macd", label: "MACD 柱", category: "趋势", default_params: { fast: 12, slow: 26, signal: 9 }, min_bars: 35,
      description: "MACD 柱相对价格归一化，捕捉趋势加速",
      fn: function (bars, i, p) {
        var fast = p.fast, slow = p.slow, sig = p.signal; if (i < slow + sig) return null;
        var cs = bars.slice(0, i + 1).map(function (b) { return b.close; });
        var ef = emaSeries(cs, fast), es = emaSeries(cs, slow), line = [];
        for (var k = 0; k < ef.length; k++) line.push(ef[k] - es[k]);
        var signal = emaSeries(line, sig), hist = line[line.length - 1] - signal[signal.length - 1];
        return tanh(hist / Math.max(cs[cs.length - 1] * 0.01, 1e-9));
      } },
    { name: "bollinger_z", label: "布林带 Z 值", category: "反转", default_params: { period: 20 }, min_bars: 20,
      description: "价格偏离均线的标准差倍数，方向取反（均值回归）",
      fn: function (bars, i, p) {
        var period = p.period; if (i < period - 1) return null;
        var cs = closes(bars, i, period), sd = pstdev(cs); if (sd < 1e-9) return 0;
        return tanh(-((cs[cs.length - 1] - mean(cs)) / sd) / 1.5);
      } },
    { name: "breakout", label: "通道突破", category: "趋势", default_params: { channel: 20 }, min_bars: 20,
      description: "收盘价在 N 日高低通道中的相对位置",
      fn: function (bars, i, p) {
        var c = p.channel; if (i < c) return null;
        var w = bars.slice(i - c, i + 1), hi = -Infinity, lo = Infinity;
        for (var k = 0; k < w.length; k++) { hi = Math.max(hi, w[k].high); lo = Math.min(lo, w[k].low); }
        if (hi - lo < 1e-9) return 0;
        return tanh(((bars[i].close - lo) / (hi - lo) - 0.5) * 3);
      } },
    { name: "volume_spike", label: "放量确认", category: "量能", default_params: { period: 20 }, min_bars: 21,
      description: "成交量相对均值的放大程度，乘当日价格方向",
      fn: function (bars, i, p) {
        var period = p.period; if (i < period || bars[i - 1].close === 0) return null;
        var avg = mean(bars.slice(i - period, i).map(function (b) { return b.volume; }));
        if (avg <= 0) return 0;
        var dir = bars[i].close >= bars[i - 1].close ? 1 : -1;
        return tanh((bars[i].volume / avg - 1) / 0.8) * dir;
      } },
    { name: "low_volatility", label: "低波偏好", category: "风险", default_params: { period: 20, target: 0.018 }, min_bars: 21,
      description: "实现波动率低于目标时给正分，用于过滤高波动行情",
      fn: function (bars, i, p) {
        var period = p.period, target = p.target; if (i < period) return null;
        var vol = pstdev(returns(closes(bars, i, period + 1)));
        return tanh((target - vol) / Math.max(target, 1e-9));
      } },
    { name: "atr_trend", label: "ATR 趋势", category: "趋势", default_params: { period: 14 }, min_bars: 15,
      description: "N 日价格变动除以 ATR×√N，波动率归一化的趋势强度",
      fn: function (bars, i, p) {
        var period = p.period; if (i < period) return null;
        var atr = mean(trueRanges(bars, i, period)), change = bars[i].close - bars[i - period].close;
        return tanh(change / Math.max(atr * Math.sqrt(period), 1e-9) / 1.5);
      } },
    { name: "reversal_1d", label: "隔夜反转", category: "反转", default_params: { scale: 40 }, min_bars: 1,
      description: "单日涨跌幅的反向信号，捕捉短期过度反应",
      fn: function (bars, i, p) {
        if (i < 1 || bars[i - 1].close <= 0) return null;
        return tanh(-(bars[i].close / bars[i - 1].close - 1) * p.scale);
      } }
  ];
  var FACTOR_MAP = {};
  FACTORS.forEach(function (f) { FACTOR_MAP[f.name] = f; });

  function computeFactors(bars, i, specs, method) {
    var values = {}, contributions = {}, totalW = 0, availW = 0, valid = [];
    for (var s = 0; s < specs.length; s++) {
      var spec = specs[s]; totalW += spec.weight;
      var meta = FACTOR_MAP[spec.name]; if (!meta) continue;
      var params = Object.assign({}, meta.default_params, spec.params || {});
      var v = meta.fn(bars, i, params);
      if (v === null || v === undefined || Number.isNaN(v)) continue;
      v = clamp(v, -1, 1);
      values[spec.name] = v; contributions[spec.name] = spec.weight * v;
      availW += spec.weight; valid.push([spec.weight, v]);
    }
    if (availW <= 0) return { value: 0, contributions: {}, raw_values: values, coverage: 0 };
    var value;
    if (method === "majority") value = valid.reduce(function (a, x) { return a + x[0] * (x[1] > 0 ? 1 : (x[1] < 0 ? -1 : 0)); }, 0) / availW;
    else if (method === "min") value = Math.min.apply(null, valid.map(function (x) { return x[1]; }));
    else if (method === "max") value = Math.max.apply(null, valid.map(function (x) { return x[1]; }));
    else value = valid.reduce(function (a, x) { return a + x[0] * x[1]; }, 0) / availW;
    return { value: clamp(value, -1, 1), contributions: contributions, raw_values: values,
             coverage: availW / (totalW || 1) };
  }

  // ---------------------------------------------------------------- signals
  function makeSignalEngine(cfg) {
    var eff = {}, side = {}, lastFlip = {}, lastWeight = {};
    function evaluate(bars, i, symbol) {
      var sc = cfg.signal, panel = computeFactors(bars, i, cfg.factors, sc.combine_method);
      var raw = panel.value, prev = eff[symbol] === undefined ? raw : eff[symbol];
      var e = (1 - sc.smoothing) * raw + sc.smoothing * prev;
      eff[symbol] = e;
      var desired = e >= sc.buy_threshold ? 1 : (e <= sc.sell_threshold ? -1 : 0);
      var cur = side[symbol] || 0, blocked = false;
      if (desired !== 0 && desired !== cur) {
        var since = i - (lastFlip[symbol] === undefined ? -1e9 : lastFlip[symbol]);
        if (since < sc.min_holding_bars) { desired = cur; blocked = true; }
        else { side[symbol] = desired; lastFlip[symbol] = i; }
      }
      var maxPos = Math.min(cfg.backtest.max_position_pct, cfg.risk.max_position_pct);
      var thr = Math.min(0.95, Math.max(Math.abs(sc.buy_threshold), Math.abs(sc.sell_threshold), 0.01));
      var intensity = clamp((Math.abs(e) - thr) / (1 - thr), 0, 1);
      var scale = 0.45 + 0.55 * intensity;
      var action, weight;
      if (desired === 1) { action = "BUY"; weight = maxPos * scale; lastWeight[symbol] = weight; }
      else if (desired === -1) { action = "SELL"; weight = cfg.risk.allow_short ? -maxPos * scale : 0; lastWeight[symbol] = weight; }
      else { action = "HOLD"; weight = null; }
      var leaders = Object.keys(panel.contributions).sort(function (a, b) {
        return Math.abs(panel.contributions[b]) - Math.abs(panel.contributions[a]);
      }).slice(0, 2).map(function (k) { return k + "(" + (panel.contributions[k] >= 0 ? "+" : "") + panel.contributions[k].toFixed(2) + ")"; });
      var reason = blocked ? "方向翻转被 min_holding_bars=" + sc.min_holding_bars + " 抑制，维持原方向"
        : "综合得分 " + (e >= 0 ? "+" : "") + e.toFixed(3) + "（" + action + "），阈值 ±" + Math.abs(sc.buy_threshold).toFixed(2);
      if (leaders.length) reason += "；主导因子 " + leaders.join("、");
      return { date: bars[i].date, symbol: symbol, action: action, score: e, raw_score: raw,
               target_weight: weight, contributions: panel.contributions, raw_values: panel.raw_values,
               coverage: panel.coverage, reason: reason };
    }
    return { evaluate: evaluate };
  }

  // ---------------------------------------------------------------- portfolio
  function Portfolio(cash) {
    this.cash = cash; this.initial_cash = cash; this.positions = {}; this.lastPrices = {};
    this.realized_pnl = 0; this.total_commission = 0; this.total_slippage = 0; this.trade_count = 0;
  }
  Portfolio.prototype.setPrice = function (s, p) { this.lastPrices[s] = p; };
  Portfolio.prototype.positionValue = function (s) {
    var p = this.positions[s]; if (!p || p.qty === 0) return 0;
    return p.qty * (this.lastPrices[s] === undefined ? p.avg_cost : this.lastPrices[s]);
  };
  Portfolio.prototype.grossExposure = function () {
    var self = this; return Object.keys(this.positions).reduce(function (a, s) { return a + Math.abs(self.positionValue(s)); }, 0);
  };
  Portfolio.prototype.equity = function () {
    var self = this; return this.cash + Object.keys(this.positions).reduce(function (a, s) { return a + self.positionValue(s); }, 0);
  };
  Portfolio.prototype.applyFill = function (symbol, side, qty, price, commission, slippage) {
    commission = commission || 0; slippage = slippage || 0;
    var signed = side === "BUY" ? qty : -qty;
    var pos = this.positions[symbol] || { symbol: symbol, qty: 0, avg_cost: 0 };
    var oldQty = pos.qty, oldCost = pos.avg_cost, newQty = oldQty + signed, realized = 0, newCost;
    if (oldQty === 0 || oldQty * signed > 0) newCost = (Math.abs(oldQty) * oldCost + qty * price) / (Math.abs(oldQty) + qty);
    else {
      var closed = Math.min(Math.abs(signed), Math.abs(oldQty));
      realized = (price - oldCost) * closed * (oldQty > 0 ? 1 : -1);
      this.realized_pnl += realized;
      newCost = Math.abs(signed) > Math.abs(oldQty) ? price : oldCost;
    }
    this.cash -= signed * price; this.cash -= commission;
    this.total_commission += commission; this.total_slippage += slippage; this.trade_count += 1;
    this.setPrice(symbol, price);
    if (Math.abs(newQty) < 1e-9) delete this.positions[symbol];
    else { pos.qty = newQty; pos.avg_cost = newCost; this.positions[symbol] = pos; }
    return realized;
  };
  Portfolio.prototype.snapshot = function () {
    var self = this;
    return { cash: r2(this.cash), equity: r2(this.equity()), gross_exposure: r2(this.grossExposure()),
      realized_pnl: r2(this.realized_pnl), total_commission: r2(this.total_commission),
      total_slippage: r2(this.total_slippage), trade_count: this.trade_count,
      positions: Object.keys(this.positions).filter(function (s) { return Math.abs(self.positions[s].qty) > 1e-9; })
        .map(function (s) { return { symbol: s, qty: self.positions[s].qty, avg_cost: r2(self.positions[s].avg_cost),
                                      market_value: r2(self.positionValue(s)) }; }) };
  };

  // ---------------------------------------------------------------- risk
  var RULES = [
    ["KILL_SWITCH", "紧急停机", "一键停止所有下单，配置或环境变量均可触发"],
    ["SYMBOL_BLACKLIST", "标的黑名单", "禁止交易指定标的"],
    ["MIN_QTY", "最小下单量", "过滤零股/空单"],
    ["MAX_ORDER_NOTIONAL", "单笔金额上限", "限制单笔委托名义金额，防 fat finger"],
    ["MAX_POSITION_WEIGHT", "单票仓位上限", "限制单一标的占净值比例"],
    ["MAX_GROSS_EXPOSURE", "总敞口上限", "限制组合总持仓占净值比例"],
    ["MAX_DAILY_LOSS", "日内亏损熔断", "当日亏损超阈值后停止开新仓"],
    ["MAX_DRAWDOWN", "回撤熔断", "自峰值回撤超阈值后停机"],
    ["COOLDOWN", "交易冷却", "限制同一标的连续下单频率"],
    ["BUYING_POWER", "购买力", "买单金额不得超过可用现金"],
    ["SHORTING_DISABLED", "禁止做空", "不允许卖出超过当前持仓"],
    ["PENDING_ORDER_LIMIT", "挂单数量", "限制同一周期未成交委托数量"]
  ].map(function (r) { return { rule: r[0], label: r[1], description: r[2] }; });

  function riskEvaluate(req, pf, price, ctx, rc) {
    var equity = Math.max(ctx.equity, 1e-9), qty = Math.abs(req.qty);
    var notional = qty * Math.max(price, 0), isBuy = req.side === "BUY", signed = isBuy ? qty : -qty;
    var curQty = pf.positions[req.symbol] ? pf.positions[req.symbol].qty : 0;
    var afterValue = (curQty + signed) * price;
    var afterGross = pf.grossExposure() - Math.abs(curQty * price) + Math.abs(afterValue);
    var checks = [];
    function add(rule, passed, detail) { checks.push({ rule: rule, passed: !!passed, detail: detail }); }
    var killed = rc.kill_switch || ctx.halted || ctx.env_kill;
    add("KILL_SWITCH", !killed, killed ? "已停机，所有委托拒绝" : "运行中");
    var blacklisted = (rc.blacklist || []).indexOf(req.symbol) >= 0;
    add("SYMBOL_BLACKLIST", !blacklisted, blacklisted ? req.symbol + " 在黑名单" : req.symbol + " 可交易");
    add("MIN_QTY", qty > 0, "qty=" + qty);
    add("MAX_ORDER_NOTIONAL", notional <= rc.max_order_notional,
        "单笔 " + Math.round(notional) + " / 上限 " + Math.round(rc.max_order_notional));
    add("MAX_POSITION_WEIGHT", Math.abs(afterValue) / equity <= rc.max_position_pct + 1e-9,
        "下单后仓位 " + (Math.abs(afterValue) / equity * 100).toFixed(1) + "% / 上限 " + (rc.max_position_pct * 100).toFixed(0) + "%");
    add("MAX_GROSS_EXPOSURE", afterGross / equity <= rc.max_gross_exposure_pct + 1e-9,
        "下单后总敞口 " + (afterGross / equity * 100).toFixed(1) + "% / 上限 " + (rc.max_gross_exposure_pct * 100).toFixed(0) + "%");
    var daily = ctx.equity / Math.max(ctx.day_start_equity, 1e-9) - 1;
    add("MAX_DAILY_LOSS", daily > -rc.max_daily_loss_pct,
        "当日 " + (daily >= 0 ? "+" : "") + (daily * 100).toFixed(2) + "% / 阈值 -" + (rc.max_daily_loss_pct * 100).toFixed(0) + "%");
    var dd = ctx.equity / Math.max(ctx.peak_equity, 1e-9) - 1;
    add("MAX_DRAWDOWN", dd > -rc.max_drawdown_pct,
        "当前回撤 " + (dd >= 0 ? "+" : "") + (dd * 100).toFixed(2) + "% / 阈值 -" + (rc.max_drawdown_pct * 100).toFixed(0) + "%");
    add("COOLDOWN", ctx.bars_since_last_trade >= rc.cooldown_bars,
        "距上次成交 " + ctx.bars_since_last_trade + " bar / 要求 " + rc.cooldown_bars);
    add("BUYING_POWER", !isBuy || notional <= pf.cash + 1e-6,
        isBuy ? "需 " + Math.round(notional) + " / 可用 " + Math.round(pf.cash) : "卖出无需购买力");
    var oversell = !isBuy && !rc.allow_short && qty > curQty + 1e-9;
    add("SHORTING_DISABLED", !oversell, oversell ? "卖出 " + qty + " 超过持仓 " + curQty : "未超卖");
    add("PENDING_ORDER_LIMIT", ctx.pending_count < ctx.max_pending,
        "挂单 " + ctx.pending_count + " / 上限 " + ctx.max_pending);
    var failed = null;
    for (var k = 0; k < checks.length; k++) if (!checks[k].passed) { failed = checks[k]; break; }
    return { allowed: failed === null, blocked_by: failed ? failed.rule : null, checks: checks };
  }

  // ---------------------------------------------------------------- metrics
  function computeMetrics(curve, trades, initialCash, benchCurve) {
    var eq = curve.map(function (p) { return p.equity; });
    if (eq.length < 2) return { error: "not enough bars", bars: eq.length };
    var rets = [];
    for (var k = 1; k < eq.length; k++) if (eq[k - 1] > 0) rets.push(eq[k] / eq[k - 1] - 1);
    var mu = mean(rets), sd = pstdev(rets), downside = rets.filter(function (r) { return r < 0; });
    var dsd = rets.length ? Math.sqrt(downside.reduce(function (a, r) { return a + r * r; }, 0) / rets.length) : 0;
    var peak = eq[0], peakI = 0, maxDD = 0, longest = 0;
    for (var i = 0; i < eq.length; i++) {
      if (eq[i] > peak) { peak = eq[i]; peakI = i; }
      var dd = peak > 0 ? eq[i] / peak - 1 : 0;
      maxDD = Math.min(maxDD, dd);
      longest = Math.max(longest, dd < 0 ? i - peakI : 0);
    }
    var years = rets.length / 252, totalReturn = eq[eq.length - 1] / initialCash - 1;
    var cagr = years > 0 && eq[eq.length - 1] > 0 ? Math.pow(eq[eq.length - 1] / initialCash, 1 / years) - 1 : 0;
    var closed = trades.filter(function (t) { return t.pnl !== null && t.pnl !== undefined; }).map(function (t) { return t.pnl; });
    var wins = closed.filter(function (p) { return p > 0; }), losses = closed.filter(function (p) { return p < 0; });
    var grossWin = wins.reduce(function (a, b) { return a + b; }, 0);
    var grossLoss = Math.abs(losses.reduce(function (a, b) { return a + b; }, 0));
    var out = {
      start: curve[0].date, end: curve[curve.length - 1].date, bars: curve.length,
      initial_cash: r2(initialCash), final_equity: r2(eq[eq.length - 1]),
      total_return: r6(totalReturn), cagr: r6(cagr), annual_volatility: r6(sd * Math.sqrt(252)),
      sharpe: Math.round((sd > 0 ? mu / sd * Math.sqrt(252) : 0) * 1e4) / 1e4,
      sortino: Math.round((dsd > 0 ? mu / dsd * Math.sqrt(252) : 0) * 1e4) / 1e4,
      max_drawdown: r6(maxDD), max_drawdown_bars: longest,
      calmar: Math.round((maxDD < 0 ? cagr / Math.abs(maxDD) : 0) * 1e4) / 1e4,
      num_trades: trades.length, closed_trades: closed.length,
      win_rate: closed.length ? Math.round(wins.length / closed.length * 1e4) / 1e4 : 0,
      profit_factor: grossLoss > 0 ? Math.round(grossWin / grossLoss * 1e4) / 1e4 : (wins.length ? 999 : null),
      total_commission: r2(trades.reduce(function (a, t) { return a + (t.commission || 0); }, 0)),
      total_slippage: r2(trades.reduce(function (a, t) { return a + (t.slippage || 0); }, 0)),
      risk_blocks: 0
    };
    if (benchCurve && benchCurve.length && benchCurve[0].benchmark > 0) {
      var b = benchCurve.map(function (p) { return p.benchmark; });
      var bh = b[b.length - 1] / b[0] - 1;
      out.buy_hold_return = r6(bh); out.excess_return = r6(totalReturn - bh);
      var bp = b[0], bdd = 0;
      for (var j = 0; j < b.length; j++) { bp = Math.max(bp, b[j]); bdd = Math.min(bdd, b[j] / bp - 1); }
      out.buy_hold_max_drawdown = r6(bdd);
    }
    return out;
  }

  // ---------------------------------------------------------------- backtest
  function backtest(cfg, data) {
    var bc = cfg.backtest, rc = cfg.risk, tc = cfg.trading;
    var symbols = cfg.symbols.filter(function (s) { return data[s] && data[s].length; });
    if (!symbols.length) throw new Error("No bars for configured symbols");
    var idxMaps = {}, allDates = {};
    symbols.forEach(function (s) {
      idxMaps[s] = {}; data[s].forEach(function (b, i) { idxMaps[s][b.date] = i; allDates[b.date] = 1; });
    });
    var dates = Object.keys(allDates).sort();
    var pf = new Portfolio(bc.initial_cash), se = makeSignalEngine(cfg);
    var pending = [], trades = [], signals = [], riskEvents = [], curve = [], impact = {};
    var latestSignals = [], lastTradeBar = {}, basePrice = {}, peak = bc.initial_cash;
    symbols.forEach(function (s) { basePrice[s] = data[s][0].close; });

    for (var t = 0; t < dates.length; t++) {
      var day = dates[t], todayBars = {};
      symbols.forEach(function (s) { if (idxMaps[s][day] !== undefined) todayBars[s] = data[s][idxMaps[s][day]]; });
      var dayStart = curve.length ? curve[curve.length - 1].equity : bc.initial_cash;
      var slipRate = bc.slippage_bps / 10000;

      for (var q = 0; q < pending.length; q++) {
        var item = pending[q], req = item.req, sig = item.sig;
        if (!todayBars[req.symbol]) continue;
        var bar = todayBars[req.symbol], isBuy = req.side === "BUY";
        var px = isBuy ? bar.open * (1 + slipRate) : bar.open * (1 - slipRate);
        var slipCost = req.qty * bar.open * slipRate;
        var commission = req.qty * px * bc.commission_bps / 10000;
        var ctx = { equity: pf.equity(), day_start_equity: dayStart, peak_equity: peak,
          bars_since_last_trade: t - (lastTradeBar[req.symbol] === undefined ? -1e6 : lastTradeBar[req.symbol]),
          pending_count: 0, max_pending: tc.max_orders_per_cycle, halted: false, env_kill: !!rc.kill_switch };
        var decision = riskEvaluate(req, pf, px, ctx, rc);
        if (!decision.allowed) {
          riskEvents.push({ date: day, symbol: req.symbol, side: req.side, qty: req.qty,
            blocked_by: decision.blocked_by, failed_checks: decision.checks.filter(function (c) { return !c.passed; }),
            reason: sig.reason });
          continue;
        }
        var realized = pf.applyFill(req.symbol, req.side, req.qty, px, commission, slipCost);
        lastTradeBar[req.symbol] = t;
        trades.push({ date: day, symbol: req.symbol, side: req.side, qty: req.qty, price: Math.round(px * 1e4) / 1e4,
          notional: r2(req.qty * px), commission: r2(commission), slippage: r2(slipCost),
          pnl: Math.abs(realized) > 1e-9 ? r2(realized) : null, reason: sig.reason });
      }
      pending = [];

      Object.keys(todayBars).forEach(function (s) { pf.setPrice(s, todayBars[s].close); });
      var equity = pf.equity(); peak = Math.max(peak, equity);
      var ratios = symbols.filter(function (s) { return todayBars[s] && basePrice[s] > 0; })
        .map(function (s) { return todayBars[s].close / basePrice[s]; });
      var benchmark = ratios.length ? bc.initial_cash * mean(ratios) : bc.initial_cash;
      curve.push({ date: day, equity: equity, cash: pf.cash, exposure: pf.grossExposure(),
                   benchmark: benchmark, drawdown: equity / peak - 1 });

      var idxToday = {}, subset = {};
      symbols.forEach(function (s) { if (idxMaps[s][day] !== undefined) { idxToday[s] = idxMaps[s][day]; subset[s] = data[s]; } });
      var sigs = Object.keys(idxToday).map(function (s) { return se.evaluate(subset[s], idxToday[s], s); });
      latestSignals = sigs;
      sigs.forEach(function (sig) {
        Object.keys(sig.contributions).forEach(function (n) { impact[n] = (impact[n] || 0) + Math.abs(sig.contributions[n]); });
        if (sig.action !== "HOLD") signals.push(sig);
      });
      var targets = {};
      sigs.forEach(function (sig) { if (sig.target_weight !== null) targets[sig.symbol] = sig.target_weight; });
      var gross = Object.keys(targets).reduce(function (a, s) { return a + Math.abs(targets[s]); }, 0);
      var cap = Math.min(bc.max_gross_exposure_pct, rc.max_gross_exposure_pct);
      if (gross > cap && gross > 0) Object.keys(targets).forEach(function (s) { targets[s] *= cap / gross; });
      var sigMap = {}; sigs.forEach(function (sig) { sigMap[sig.symbol] = sig; });
      Object.keys(targets).forEach(function (sym) {
        var close = todayBars[sym].close, delta = targets[sym] * equity - pf.positionValue(sym);
        if (Math.abs(delta) < bc.min_order_value || close <= 0) return;
        var lot = Math.max(1, bc.lot_size | 0);
        var qty = Math.floor(Math.abs(delta) / close / lot) * lot;
        qty = Math.min(qty, Math.floor(rc.max_order_notional / close / lot) * lot);
        if (qty <= 0) return;
        pending.push({ req: { symbol: sym, side: delta > 0 ? "BUY" : "SELL", qty: qty,
                              limit_price: close, reason: sigMap[sym].reason, target_weight: targets[sym] },
                       sig: sigMap[sym] });
      });
    }

    var metrics = computeMetrics(curve, trades, bc.initial_cash, curve);
    metrics.risk_blocks = riskEvents.length;
    var totalImpact = Object.keys(impact).reduce(function (a, n) { return a + impact[n]; }, 0) || 1;
    var factorImpact = Object.keys(impact).sort(function (a, b) { return impact[b] - impact[a]; })
      .map(function (n) { var m = FACTOR_MAP[n]; return { name: n, label: m ? m.label : n,
        impact: Math.round(impact[n] * 1e4) / 1e4, share: Math.round(impact[n] / totalImpact * 1e4) / 1e4 }; });
    return {
      config: cfg, metrics: metrics,
      equity_curve: curve.map(function (p) { return { date: p.date, equity: r2(p.equity), cash: r2(p.cash),
        exposure: r2(p.exposure), benchmark: r2(p.benchmark), drawdown: r6(p.drawdown) }; }),
      trades: trades, signals: signals, latest_signals: latestSignals,
      risk_events: riskEvents, factor_impact: factorImpact, _pf: pf
    };
  }

  // ---------------------------------------------------------------- paper session
  function paperSession(cfg, data, opts) {
    opts = opts || {};
    var bc = cfg.backtest, rc = cfg.risk;
    var symbols = cfg.symbols.filter(function (s) { return data[s] && data[s].length; });
    var length = Math.min.apply(null, symbols.map(function (s) { return data[s].length; }));
    var pf = new Portfolio(bc.initial_cash), se = makeSignalEngine(cfg);
    var start = opts.startIndex === undefined ? 60 : opts.startIndex;
    var steps = opts.steps === undefined ? 20 : opts.steps;
    var orders = [], blocks = [], log = [], lastTrade = {}, peak = bc.initial_cash;
    var dayStart = bc.initial_cash, lastDate = "";
    for (var i = start; i < Math.min(start + steps, length); i++) {
      var date = data[symbols[0]][i].date, prices = {};
      symbols.forEach(function (s) { prices[s] = data[s][i].close; pf.setPrice(s, prices[s]); });
      var equity = pf.equity();
      if (date !== lastDate) { dayStart = equity; lastDate = date; }
      peak = Math.max(peak, equity);
      var sigs = symbols.map(function (s) { return se.evaluate(data[s], i, s); });
      var targets = {};
      sigs.forEach(function (sg) { if (sg.target_weight !== null) targets[sg.symbol] = sg.target_weight; });
      var gross = Object.keys(targets).reduce(function (a, s) { return a + Math.abs(targets[s]); }, 0);
      var cap = Math.min(bc.max_gross_exposure_pct, rc.max_gross_exposure_pct);
      if (gross > cap && gross > 0) Object.keys(targets).forEach(function (s) { targets[s] *= cap / gross; });
      var pendingCount = 0;
      Object.keys(targets).forEach(function (sym) {
        var price = prices[sym], delta = targets[sym] * equity - pf.positionValue(sym);
        if (Math.abs(delta) < bc.min_order_value || price <= 0) return;
        var lot = Math.max(1, bc.lot_size | 0);
        var qty = Math.floor(Math.abs(delta) / price / lot) * lot;
        qty = Math.min(qty, Math.floor(rc.max_order_notional / price / lot) * lot);
        if (qty <= 0 || pendingCount >= cfg.trading.max_orders_per_cycle) return;
        var side = delta > 0 ? "BUY" : "SELL";
        var req = { symbol: sym, side: side, qty: qty, reason: sigs.filter(function (x) { return x.symbol === sym; })[0].reason };
        var ctx = { equity: equity, day_start_equity: dayStart, peak_equity: peak,
          bars_since_last_trade: i - (lastTrade[sym] === undefined ? -1e6 : lastTrade[sym]),
          pending_count: pendingCount, max_pending: cfg.trading.max_orders_per_cycle,
          halted: false, env_kill: !!rc.kill_switch };
        var dec = riskEvaluate(req, pf, price, ctx, rc);
        if (!dec.allowed) {
          var ev = { date: date, symbol: sym, side: side, qty: qty, blocked_by: dec.blocked_by,
                     failed_checks: dec.checks.filter(function (c) { return !c.passed; }), reason: req.reason };
          blocks.push(ev); log.push({ kind: "block", date: date, text: sym + " " + side + " " + qty + " 股 被 " + dec.blocked_by + " 拦截" });
          return;
        }
        var slip = bc.slippage_bps / 10000;
        var px = side === "BUY" ? price * (1 + slip) : price * (1 - slip);
        var commission = qty * px * bc.commission_bps / 10000;
        pf.applyFill(sym, side, qty, px, commission, qty * price * slip);
        lastTrade[sym] = i; pendingCount += 1;
        orders.push({ date: date, symbol: sym, side: side, qty: qty, price: r2(px), reason: req.reason,
                      checks: dec.checks });
        log.push({ kind: "order", date: date, text: sym + " " + side + " " + qty + " 股 @ " + r2(px) });
      });
    }
    return { orders: orders, blocks: blocks, log: log, account: pf.snapshot(),
             steps: Math.min(steps, Math.max(0, length - start)) };
  }

  return {
    FACTORS: FACTORS, FACTOR_MAP: FACTOR_MAP, RULES: RULES, COMBINE_METHODS: ["weighted", "majority", "min", "max"],
    computeFactors: computeFactors, makeSignalEngine: makeSignalEngine, Portfolio: Portfolio,
    riskEvaluate: riskEvaluate, computeMetrics: computeMetrics, backtest: backtest,
    paperSession: paperSession, helpers: { mean: mean, pstdev: pstdev, emaSeries: emaSeries, tanh: tanh }
  };
});
