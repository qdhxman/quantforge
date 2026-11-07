"""End-to-end acceptance run for the A-share path, on CLEARLY SYNTHETIC data.

    python scripts/ashare_pipeline.py

What it proves (and what it does NOT prove) -- read the emitted report:
  PROVES  rules engine, data gate, strict execution, IC/IR, layered test,
          walk-forward, monitor-only tickets, provenance tagging all run.
  DOES NOT prove  any strategy works. The input is synthetic, the calendar is
          not authoritative and the span is < 3 years, so the readiness gate
          MUST return NOT_READY. That is the correct, honest output.

Output:
    data/ashare_synthetic_fixture/   cached synthetic bars (never production)
    web/ashare_signals.json          dashboard snapshot (labelled synthetic)
    reports/ashare_monitor.db        monitor history
    reports/ashare_readiness.json    full acceptance report
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.ashare import (  # noqa: E402
    AShareBacktestEngine, CachedFeed, DataQualityGate, Monitor,
    assert_no_execution_path, build_factor_panel, compute_ic_ir, layered_backtest,
    overfit_diagnosis, rolling_windows, walk_forward, write_cache,
)
from quantforge.ashare.config import AShareSettings  # noqa: E402
from quantforge.ashare.engine import _adjust  # noqa: E402
from quantforge.ashare.rules import CN_TZ  # noqa: E402
from quantforge.ashare.synthetic import SYNTHETIC_LICENSE, build_synthetic_fixture  # noqa: E402
from quantforge.journal import Journal  # noqa: E402

CACHE = ROOT / "data" / "ashare_synthetic_fixture"
REPORT = ROOT / "reports" / "ashare_readiness.json"


def main() -> int:
    settings = AShareSettings.load()
    symbols = settings.symbols
    lines: list[str] = []
    report: dict = {"generated_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
                    "data_class": "SYNTHETIC TEST FIXTURE - NOT REAL MARKET DATA",
                    "purpose": "pipeline acceptance only, NOT strategy evidence"}

    forbidden = assert_no_execution_path()
    report["no_execution_path"] = {"passed": not forbidden, "found": forbidden}
    lines.append(f"[1] 无下单调用检查: {'PASS' if not forbidden else 'FAIL ' + str(forbidden)}")

    bars, calendar, instruments, snapshots = build_synthetic_fixture(symbols, n_bars=504)
    write_cache(CACHE, bars, calendar, instruments,
                source="SYNTHETIC-FIXTURE", license=SYNTHETIC_LICENSE,
                note="NOT REAL MARKET DATA. weekday-only calendar. For acceptance tests only.",
                snapshots=snapshots)
    feed = CachedFeed(CACHE)
    lines.append(f"[2] 缓存写入: {CACHE} ({sum(len(v) for v in bars.values())} bars, license={SYNTHETIC_LICENSE})")

    # Gate test: a non-authoritative calendar MUST be refused by default.
    real_calendar = feed.trading_calendar(calendar.dates[0], calendar.dates[-1])
    gate_refused = False
    try:
        AShareBacktestEngine(settings.backtest_config(), feed, real_calendar,
                             gate=DataQualityGate())
    except ValueError as exc:
        gate_refused = "authoritative" in str(exc)
    report["calendar_gate"] = {"passed": gate_refused,
                               "note": "non-authoritative calendar refused unless explicitly allowed"}
    lines.append(f"[3] 交易日历权威门禁: {'PASS (拒绝非权威日历)' if gate_refused else 'FAIL'}")

    cfg = settings.backtest_config(allow_unverified_calendar=True, run_id="ashare-acceptance")
    engine = AShareBacktestEngine(cfg, feed, real_calendar, gate=DataQualityGate())
    result = engine.run(calendar.dates[0], calendar.dates[-1])
    report["backtest"] = {"summary": result.summary(), "metrics": result.metrics,
                          "rule_blocks": result.rule_blocks,
                          "quality": result.quality, "assumptions": result.assumptions}
    lines.append(f"[4] 严格回测: {result.summary()}")
    lines.append(f"    规则拦截分布: {result.rule_blocks}")

    adj = {s: [_adjust(b) for b in rows] for s, rows in feed.history(symbols, calendar.dates[0], calendar.dates[-1]).items()}
    panel = build_factor_panel(adj, settings.factors, horizon=1, method=settings.signal.combine_method)
    ic = compute_ic_ir(panel)
    layers = layered_backtest(panel, groups=5)
    report["factor_validation"] = {"panel_rows": len(panel), "ic_ir": ic.as_dict(),
                                   "layers": layers.as_dict()}
    lines.append(f"[5] 因子检验: {len(panel)} 截面行, IC={ic.ic_mean:+.4f}, IR={ic.ir:+.3f}, "
                 f"正率={ic.positive_ratio:.2%}, 判定={ic.verdict}")
    lines.append(f"    分层单调={layers.monotonic}, spread={layers.spread:+.4%}, 判定={layers.verdict}")

    windows = rolling_windows(calendar.dates, train_days=100, test_days=30, step=60)

    def evaluator(dates: list[str]) -> dict:
        e = AShareBacktestEngine(settings.backtest_config(allow_unverified_calendar=True),
                                 feed, real_calendar, gate=DataQualityGate())
        return e.run(dates[0], dates[-1]).metrics

    wf = walk_forward(windows, evaluator)
    span_years = len(calendar.dates) / 252.0
    diagnosis = overfit_diagnosis(ic, layers, wf, span_years=span_years)
    report["walk_forward"] = wf.as_dict()
    report["readiness"] = diagnosis
    lines.append(f"[6] Walk-forward: {wf.windows} 窗口, 判定={wf.verdict}, flags={wf.flags}")
    lines.append(f"[7] 就绪度: {diagnosis['verdict']} | gates={diagnosis['gates']}")

    mcfg = settings.monitor_config(allow_unverified_calendar=True)
    monitor = Monitor(mcfg, feed, real_calendar, gate=DataQualityGate(),
                      journal=Journal(str(ROOT / "reports" / "ashare_acceptance_journal.jsonl")))
    now = datetime.combine(datetime.now(CN_TZ).date(), time(10, 0), CN_TZ)
    cycle = monitor.run_once(now=now)
    report["monitor"] = {"session": cycle.session, "skipped": cycle.skipped,
                         "quality": cycle.quality, "tickets": len(cycle.tickets),
                         "alerts": cycle.alerts}
    lines.append(f"[8] 监控守护: session={cycle.session}, 质量门禁={'PASS' if cycle.quality.get('ok') else 'BLOCK'}, "
                 f"人工执行建议单 {len(cycle.tickets)} 张")
    for t in cycle.tickets[:4]:
        lines.append(f"    {t.symbol} {t.side} qty={t.suggested_qty} tradable={t.tradable} "
                     f"score={t.signal_score:+.3f}")
    monitor.stop()

    # Bundle a clearly-labelled baseline snapshot so web/ashare.html also works
    # when opened directly via file:// (where fetch() is blocked).
    live_snapshot = ROOT / "web" / "ashare_signals.json"
    if live_snapshot.exists():
        (ROOT / "web" / "ashare_demo_data.js").write_text(
            "/* SYNTHETIC ACCEPTANCE SNAPSHOT - NOT REAL MARKET DATA. Regenerate with "
            "python scripts/ashare_pipeline.py */\nwindow.QF_ASHARE_SNAPSHOT = " +
            live_snapshot.read_text(encoding="utf-8") + ";\n", encoding="utf-8")
        lines.append("[9] 面板基线快照: web/ashare_demo_data.js（标注为合成演示数据）")

    report["verdict"] = ("PIPELINE_OK_BUT_NOT_READY_FOR_LIVE" if diagnosis["verdict"] != "READY_FOR_PAPER"
                         else "READY_FOR_PAPER")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines.append(f"[9] 报告: {REPORT}")
    lines.append("结论: 链路全通，但合成数据 + 非权威日历 + 跨度<3年 => 不得用于实盘结论。")
    (ROOT / "reports" / "ashare_pipeline_log.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        (ROOT / "reports" / "ashare_pipeline_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
