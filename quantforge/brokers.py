"""Broker adapters.

PaperBroker is the default and is fully functional. AlpacaBroker speaks the
Alpaca REST API and is guarded by a triple gate: config flag + two environment
variables + a non-paper base URL. A typo in a config file must never be enough
to route real money.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .orders import Fill, Order, OrderRequest, OrderStatus, OrderType, Side
from .portfolio import Portfolio

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
CONFIRMATION_PHRASE = "I_UNDERSTAND"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Broker(ABC):
    name = "base"
    is_live = False

    @abstractmethod
    def submit_order(self, request: OrderRequest, reference_price: float) -> Order: ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool: ...

    @abstractmethod
    def get_positions(self) -> dict[str, float]: ...

    @abstractmethod
    def get_account(self) -> dict[str, Any]: ...

    def get_quote(self, symbol: str) -> float | None:
        return None


class PaperBroker(Broker):
    """Immediate-fill simulator with the same fee/slippage model as the backtest."""

    name = "paper"

    def __init__(self, initial_cash: float = 100_000.0, commission_bps: float = 5.0,
                 slippage_bps: float = 5.0):
        self.portfolio = Portfolio(initial_cash)
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []

    def submit_order(self, request: OrderRequest, reference_price: float) -> Order:
        order = Order(request=request, created_at=_utcnow(), status=OrderStatus.PENDING)
        if reference_price <= 0 or request.qty <= 0:
            order.transition(OrderStatus.REJECTED, "invalid price or qty")
            self.orders[request.client_order_id] = order
            return order

        slip = self.slippage_bps / 10_000.0
        is_buy = request.side == Side.BUY
        px = reference_price * (1.0 + slip) if is_buy else reference_price * (1.0 - slip)
        if request.order_type == OrderType.LIMIT and request.limit_price:
            px = request.limit_price
            if is_buy and px < reference_price:
                order.transition(OrderStatus.REJECTED, "limit not marketable in simulation")
                self.orders[request.client_order_id] = order
                return order
            if not is_buy and px > reference_price:
                order.transition(OrderStatus.REJECTED, "limit not marketable in simulation")
                self.orders[request.client_order_id] = order
                return order

        commission = request.qty * px * self.commission_bps / 10_000.0
        slip_cost = request.qty * reference_price * slip
        order.transition(OrderStatus.SUBMITTED)
        realized = self.portfolio.apply_fill(request.symbol, request.side.value, request.qty, px, commission, slip_cost)
        fill = Fill(request.symbol, request.side, request.qty, px, commission, slip_cost, _utcnow(), realized)
        self.fills.append(fill)
        order.transition(OrderStatus.FILLED)
        order.filled_qty = request.qty
        order.avg_fill_price = px
        order.broker_order_id = "paper-" + request.client_order_id
        order.updated_at = _utcnow()
        self.orders[request.client_order_id] = order
        return order

    def cancel_order(self, broker_order_id: str) -> bool:
        return False  # market orders fill immediately; nothing pending

    def get_positions(self) -> dict[str, float]:
        return {s: p.qty for s, p in self.portfolio.positions.items() if abs(p.qty) > 1e-9}

    def get_account(self) -> dict[str, Any]:
        return {**self.portfolio.snapshot(), "broker": self.name, "is_live": False}

    def get_quote(self, symbol: str) -> float | None:
        return self.portfolio.last_prices.get(symbol)


class AlpacaBroker(Broker):
    """Alpaca REST adapter. Defaults to the PAPER endpoint.

    Live mode requires ALL of:
      * ``enable_live=True`` in code / ``trading.mode = live`` in config
      * ``QFI_ALLOW_LIVE=1`` in the environment
      * ``QFI_CONFIRM_LIVE_TRADING=I_UNDERSTAND`` in the environment
      * ``base_url`` pointing at the non-paper endpoint
      * non-empty API key and secret
    """

    name = "alpaca"

    def __init__(self, api_key: str | None = None, secret_key: str | None = None,
                 base_url: str = PAPER_URL, *, enable_live: bool = False,
                 env: Mapping[str, str] | None = None,
                 request_fn: Callable[[str, str, dict[str, str], dict | None], dict] | None = None):
        self.env = env if env is not None else os.environ
        self.api_key = api_key or self.env.get("ALPACA_API_KEY", "")
        self.secret_key = secret_key or self.env.get("ALPACA_SECRET_KEY", "")
        self.base_url = (base_url or self.env.get("ALPACA_BASE_URL", PAPER_URL)).rstrip("/")
        self.enable_live = bool(enable_live)
        self._request_fn = request_fn or self._http
        self.orders: dict[str, Order] = {}
        if self.enable_live:
            self._assert_live_gate()

    @property
    def is_live(self) -> bool:
        return self.enable_live

    def _assert_live_gate(self) -> None:
        problems = []
        if self.env.get("QFI_ALLOW_LIVE") != "1":
            problems.append("环境变量 QFI_ALLOW_LIVE 必须为 '1'")
        if self.env.get("QFI_CONFIRM_LIVE_TRADING") != CONFIRMATION_PHRASE:
            problems.append(f"环境变量 QFI_CONFIRM_LIVE_TRADING 必须为 '{CONFIRMATION_PHRASE}'")
        if "paper" in self.base_url.lower():
            problems.append("base_url 仍是模拟盘地址（启用实盘时必须指向 https://api.alpaca.markets）")
        if not self.api_key or not self.secret_key:
            problems.append("缺少 ALPACA_API_KEY / ALPACA_SECRET_KEY")
        if problems:
            raise PermissionError("实盘闸门未打开，已拒绝创建实盘券商连接：\n  - " + "\n  - ".join(problems)
                                  + "\n见 docs/live-trading.md")

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "quantforge/0.1",
        }

    def _http(self, method: str, path: str, headers: dict[str, str], payload: dict | None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode()
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:300]
            raise RuntimeError(f"Alpaca {method} {path} failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Alpaca network error on {path}: {exc.reason}") from exc

    def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        return self._request_fn(method, path, self._headers(), payload)

    def submit_order(self, request: OrderRequest, reference_price: float) -> Order:
        order = Order(request=request, created_at=_utcnow(), status=OrderStatus.PENDING)
        payload: dict[str, Any] = {
            "symbol": request.symbol,
            "qty": str(request.qty),
            "side": request.side.value.lower(),
            "type": request.order_type.value.lower(),
            "time_in_force": "day",
            "client_order_id": request.client_order_id,
        }
        if request.order_type == OrderType.LIMIT and request.limit_price:
            payload["limit_price"] = str(round(request.limit_price, 2))
        try:
            resp = self._call("POST", "/v2/orders", payload)
        except Exception as exc:
            order.transition(OrderStatus.REJECTED, str(exc)[:200])
            self.orders[request.client_order_id] = order
            return order
        order.transition(OrderStatus.SUBMITTED)
        order.broker_order_id = str(resp.get("id", ""))
        order.updated_at = _utcnow()
        status = str(resp.get("status", "")).upper()
        if status == "FILLED":
            order.transition(OrderStatus.FILLED)
            order.filled_qty = request.qty
            order.avg_fill_price = float(resp.get("filled_avg_price") or reference_price)
        self.orders[request.client_order_id] = order
        return order

    def cancel_order(self, broker_order_id: str) -> bool:
        try:
            self._call("DELETE", f"/v2/orders/{broker_order_id}")
            return True
        except RuntimeError:
            return False

    def get_positions(self) -> dict[str, float]:
        rows = self._call("GET", "/v2/positions") or []
        return {str(r["symbol"]): float(r["qty"]) for r in rows} if isinstance(rows, list) else {}

    def get_account(self) -> dict[str, Any]:
        a = self._call("GET", "/v2/account") or {}
        return {
            "cash": float(a.get("cash", 0) or 0), "equity": float(a.get("equity", 0) or 0),
            "buying_power": float(a.get("buying_power", 0) or 0),
            "broker": self.name, "is_live": self.is_live,
        }

    def __repr__(self) -> str:
        return f"AlpacaBroker(base_url={self.base_url!r}, live={self.is_live}, key_set={bool(self.api_key)})"
