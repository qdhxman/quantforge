"""Optional FastAPI service backing the dashboard.

    pip install -e '.[api]'
    quantforge serve --port 8000      # docs at /docs, demo at /demo/

The computation core never imports FastAPI -- you can use the whole engine from
a notebook without installing a web framework.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .backtest import BacktestEngine
from .brokers import PaperBroker
from .config import StrategyConfig, default_config, load_config, validate_factors
from .data import Dataset, generate_synthetic, load_csv
from .factors import FACTOR_REGISTRY, list_factors
from .journal import Journal
from .live import LiveTradingEngine
from .risk import list_rules
from .signals import SignalEngine

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(config: StrategyConfig | None = None, data: Dataset | None = None,
               config_path: str | Path | None = None):
    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("API extra missing. Run: pip install -e '.[api]'") from exc

    app = FastAPI(title="QuantForge", version="0.1.0", description="Factor research, backtesting and guarded execution")
    cfg = config or (load_config(config_path) if config_path else default_config())
    bars = data if data is not None else generate_synthetic()
    journal = Journal()
    broker = PaperBroker(cfg.backtest.initial_cash, cfg.backtest.commission_bps, cfg.backtest.slippage_bps)
    engine: LiveTradingEngine | None = None
    state: dict[str, Any] = {"last_backtest": None}
    app.state.qf = {"config": cfg, "data": bars, "journal": journal, "broker": broker,
                    "engine": engine, "state": state}

    def _engine() -> LiveTradingEngine:
        holder = app.state.qf
        if holder["engine"] is None or holder["config"] is not cfg:
            holder["engine"] = LiveTradingEngine(cfg, broker, bars, journal=journal)
        return holder["engine"]

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": "0.1.0", "symbols": list(bars), "broker": broker.name}

    @app.get("/api/factors")
    def factors():
        return {"factors": list_factors(), "combine_methods": ["weighted", "majority", "min", "max"]}

    @app.get("/api/risk-rules")
    def risk_rules():
        return {"rules": list_rules(), "config": cfg.risk.__dict__}

    @app.get("/api/data/symbols")
    def symbols():
        return {s: {"bars": len(v), "start": v[0].date, "end": v[-1].date} for s, v in bars.items()}

    @app.get("/api/config")
    def get_config():
        return cfg.to_dict()

    @app.put("/api/config")
    def put_config(payload: dict = Body(...)):
        nonlocal cfg
        try:
            new_cfg = StrategyConfig.from_dict(payload)
            validate_factors(new_cfg, FACTOR_REGISTRY)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        cfg = new_cfg
        app.state.qf["config"] = cfg
        app.state.qf["engine"] = None
        return cfg.to_dict()

    @app.post("/api/backtest")
    def backtest(payload: dict | None = Body(default=None)):
        use_cfg = StrategyConfig.from_dict(payload["config"]) if payload and "config" in payload else cfg
        try:
            result = BacktestEngine(use_cfg).run(bars)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        state["last_backtest"] = result
        journal.append("BACKTEST", strategy=use_cfg.name, metrics=result.metrics)
        return result.as_dict()

    @app.get("/api/signals/latest")
    def latest_signals():
        out = []
        for symbol, series in bars.items():
            if symbol not in cfg.symbols or len(series) < 2:
                continue
            out.append(SignalEngine(cfg).evaluate(series, len(series) - 1, symbol).as_dict())
        return {"signals": out, "as_of": max((v[-1].date for v in bars.values() if v), default="")}

    @app.get("/api/trading/status")
    def trading_status():
        e = _engine()
        return e.status()

    @app.post("/api/trading/step")
    def trading_step(payload: dict | None = Body(default=None)):
        e = _engine()
        n = int((payload or {}).get("cycles", 1))
        results = [e.run_cycle().as_dict() for _ in range(max(1, min(n, 250)))]
        return {"results": results, "status": e.status()}

    @app.post("/api/trading/halt")
    def trading_halt(payload: dict | None = Body(default=None)):
        e = _engine()
        e.halt((payload or {}).get("reason", "manual API halt"))
        return e.status()

    @app.post("/api/trading/resume")
    def trading_resume():
        e = _engine()
        e.resume()
        return e.status()

    @app.get("/api/journal")
    def get_journal(limit: int = 100, event_type: str | None = None):
        return {"events": journal.read(limit, event_type)}

    @app.get("/api/risk/events")
    def risk_events():
        r = state["last_backtest"]
        return {"events": r.risk_events if r else []}

    @app.get("/")
    def root():
        index = WEB_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"message": "QuantForge API", "docs": "/docs"})

    if (WEB_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    return app
