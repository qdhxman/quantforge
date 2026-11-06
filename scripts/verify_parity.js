/* Compare the browser engine against a Python reference backtest.
 *
 *   python scripts/verify_parity.py --out reports/python_reference.json
 *   node scripts/verify_parity.js reports/python_reference.json
 *
 * Exits non-zero if any metric or curve point diverges beyond tolerance.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const QF = require(path.join(ROOT, "web", "engine.js"));
const payload = require(path.join(ROOT, "web", "data.js"));
const cfg = require(path.join(ROOT, "config", "strategies", "momentum.json"));

const refPath = process.argv[2] || path.join(ROOT, "reports", "python_reference.json");
if (!fs.existsSync(refPath)) {
  console.error("Missing Python reference. Run: python scripts/verify_parity.py");
  process.exit(2);
}
const py = JSON.parse(fs.readFileSync(refPath, "utf8"));
const js = QF.backtest(cfg, payload.data);

const problems = [];
function near(a, b, tol, label) {
  if (a === null || b === null || a === undefined || b === undefined) {
    if (a !== b) problems.push(`${label}: ${a} vs ${b}`);
    return;
  }
  const d = Math.abs(Number(a) - Number(b));
  if (!(d <= tol)) problems.push(`${label}: py=${a} js=${b} diff=${d}`);
}
function eq(a, b, label) { if (a !== b) problems.push(`${label}: py=${a} js=${b}`); }

Object.keys(py.metrics).forEach(function (k) {
  const a = py.metrics[k], b = js.metrics[k];
  if (typeof a === "number" && typeof b === "number") near(a, b, 2e-4, "metrics." + k);
  else eq(a, b, "metrics." + k);
});
eq(py.equity_curve.length, js.equity_curve.length, "equity_curve.length");
[0, 1, Math.floor(py.equity_curve.length / 2), py.equity_curve.length - 1].forEach(function (i) {
  if (!py.equity_curve[i] || !js.equity_curve[i]) return;
  near(py.equity_curve[i].equity, js.equity_curve[i].equity, 0.02, `equity_curve[${i}].equity`);
  eq(py.equity_curve[i].date, js.equity_curve[i].date, `equity_curve[${i}].date`);
});
eq(py.trades.length, js.trades.length, "trades.length");
eq(py.risk_events.length, js.risk_events.length, "risk_events.length");
eq(py.signals.length, js.signals.length, "signals.length");
if (py.trades.length && js.trades.length) {
  near(py.trades[0].price, js.trades[0].price, 1e-4, "trades[0].price");
  eq(py.trades[0].date, js.trades[0].date, "trades[0].date");
  eq(py.trades[0].symbol, js.trades[0].symbol, "trades[0].symbol");
}
if (py.factor_impact.length !== js.factor_impact.length) {
  problems.push(`factor_impact.length: ${py.factor_impact.length} vs ${js.factor_impact.length}`);
} else {
  py.factor_impact.forEach(function (r, i) {
    near(r.impact, js.factor_impact[i].impact, 0.01, `factor_impact[${i}].impact`);
    eq(r.name, js.factor_impact[i].name, `factor_impact[${i}].name`);
  });
}

if (problems.length) {
  console.error("PARITY FAILED (" + problems.length + " issues)");
  problems.slice(0, 40).forEach(function (p) { console.error("  - " + p); });
  process.exit(1);
}
console.log("PARITY OK");
console.log(JSON.stringify({
  python: { total_return: py.metrics.total_return, sharpe: py.metrics.sharpe, trades: py.trades.length },
  javascript: { total_return: js.metrics.total_return, sharpe: js.metrics.sharpe, trades: js.trades.length },
  checked: Object.keys(py.metrics).length + " metrics, " + py.equity_curve.length + " curve points"
}, null, 2));
