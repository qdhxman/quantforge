"""Order primitives shared by backtest, paper broker and live brokers."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


_ALLOWED: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.SUBMITTED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED},
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


@dataclass
class OrderRequest:
    """An *intended* order, produced by the strategy before risk checks."""

    symbol: str
    side: Side
    qty: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    reason: str = ""
    target_weight: float | None = None
    client_order_id: str = field(default_factory=lambda: "qf-" + uuid.uuid4().hex[:16])

    @property
    def notional(self) -> float:
        px = self.limit_price or 0.0
        return abs(self.qty) * px

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        d["order_type"] = self.order_type.value
        return d


@dataclass
class Fill:
    symbol: str
    side: Side
    qty: float
    price: float
    commission: float = 0.0
    slippage: float = 0.0
    timestamp: str = ""
    realized_pnl: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d


@dataclass
class Order:
    """Order state machine. Illegal transitions raise instead of silently corrupting state."""

    request: OrderRequest
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    broker_order_id: str = ""
    message: str = ""
    created_at: str = ""
    updated_at: str = ""

    def transition(self, new_status: OrderStatus, message: str = "") -> "Order":
        if new_status not in _ALLOWED[self.status]:
            raise ValueError(f"Illegal order transition {self.status.value} -> {new_status.value}")
        self.status = new_status
        if message:
            self.message = message
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.request.client_order_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.request.symbol,
            "side": self.request.side.value,
            "qty": self.request.qty,
            "order_type": self.request.order_type.value,
            "limit_price": self.request.limit_price,
            "status": self.status.value,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "message": self.message,
            "reason": self.request.reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
