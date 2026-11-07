"""A-share market microstructure rules, with traceable first-party sources.

Every constant below carries a source URL and an effective date. The point is
not decoration: a backtest used for real money must be able to answer "which
version of the rule produced this number?".

IMPORTANT: this module encodes rules as of 2026-11-06. Rules change. Re-verify
against exchange publications before each live deployment; see
docs/ashare-rules.md for the re-verification checklist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence

# China has had no DST since 1991, so a fixed +08:00 is exact and avoids a
# tzdata dependency on Windows.
CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

# --------------------------------------------------------------------------- #
# Regulatory constants (all with source + effective date)
# --------------------------------------------------------------------------- #
RULE_SOURCES: tuple[dict[str, str], ...] = (
    {"topic": "program-trading", "value": "individual investors must report to broker BEFORE first program trade",
     "source": "CSRC / SZSE 程序化交易管理实施细则 第二章 报告管理 第七~九条",
     "url": "https://www.szse.cn/lawrules/rule/trade/t20250403_612770.html", "effective": "2025-07-07"},
    {"topic": "program-trading-agreement", "value": "broker-client program trading agreement (model text)",
     "source": "中国证券业协会《程序化交易委托协议(示范文本)》",
     "url": "https://www.sac.net.cn/sjb/zlgl/zlgz/202512/t20251231_69956.html", "effective": "2025-12-31"},
    {"topic": "price-limit-main", "value": "main board +/-10%",
     "source": "上交所/深交所 交易规则；新华网投教", "url": "https://www.sse.com.cn/star/en/gettingstarted/features/trading/", "effective": "2023-02-17"},
    {"topic": "price-limit-star-chi", "value": "STAR / ChiNext +/-20%",
     "source": "上交所科创板交易机制 / 深交所创业板交易特别规定",
     "url": "https://www.sse.com.cn/star/en/gettingstarted/features/trading/", "effective": "2020-08-24"},
    {"topic": "price-limit-st-change", "value": "main board ST/*ST limit 5% -> 10%; STAR/ChiNext ST stays 20%; after-hours fixed-price expanded to all A shares and SH/SZ ETF",
     "source": "一手: 沪深北《交易规则(2026年修订)》2026-04-24发布/2026-07-06施行. 此链接为央视网/央广网报道(非一手交叉印证, 需核实规则原文)",
     "url": "https://news.cctv.cn/2026/07/06/ARTIJUkfhAGrSpiQqDrUizkG260706.shtml", "effective": "2026-07-06"},
    {"topic": "ipo-no-limit", "value": "first 5 trading days of IPO on main/STAR/ChiNext have no price limit",
     "source": "中国基金报《全面注册制》第五期；深交所投教",
     "url": "https://app-web.chnfund.com/YHHEediting/202402/t20240229_4329393.html", "effective": "2023-02-17"},
    {"topic": "stamp-tax", "value": "0.05% of turnover, SELL side only (halved from 0.1%)",
     "source": "上交所 股票投资一件事 / 财政部 税务总局公告 2023年第39号",
     "url": "https://one.sse.com.cn/onething/gptz", "effective": "2023-08-28"},
    {"topic": "transfer-fee", "value": "0.001% of turnover, BOTH sides, Shanghai and Shenzhen",
     "source": "中国结算；上交所收费一览 / 券商现行公示",
     "url": "https://one.sse.com.cn/onething/gptz", "effective": "2022-04-29"},
    {"topic": "commission", "value": "cap 0.3% of turnover, minimum CNY 5 per order, both sides",
     "source": "上交所 股票投资一件事；券商收费标准公示",
     "url": "https://one.sse.com.cn/onething/gptz", "effective": "2002-05-01"},
    {"topic": "regulatory-fee", "value": "经手费 0.00341% + 证管费 0.002% = 0.00541%, usually INSIDE broker commission",
     "source": "上交所收费一览表", "url": "https://www.sse.com.cn/services/tradingservice/charge/ssecharge/", "effective": "2023-08-28"},
    {"topic": "lot-main-chi", "value": "buy in multiples of 100 shares; residual <100 must be sold in one order",
     "source": "中国投资者网 投教材料 / 深交所", "url": "https://www.investor.org.cn/", "effective": "2023-02-17"},
    {"topic": "lot-star", "value": "STAR: single order >=200 shares, increments of 1 share above 200; residual <200 sold in one order",
     "source": "上交所科创板交易机制 Order Submission",
     "url": "https://www.sse.com.cn/star/en/gettingstarted/features/trading/", "effective": "2019-07-22"},
    {"topic": "t-plus-1", "value": "shares bought on T can only be sold from T+1",
     "source": "新华网投教 / 深交所", "url": "https://app.xinhuanet.com/news/article.html?articleId=67a44f8d-aa4b-4a00-820e-f2ac8712f196", "effective": "1995-01-01"},
    {"topic": "sessions", "value": "open call auction 09:15-09:25; continuous 09:30-11:30 & 13:00-14:57; close call 14:57-15:00; after-hours fixed price 15:05-15:30 (all A shares + ETF since 2026-07-06)",
     "source": "中国投资者网投教 PDF / 央视网 2026-07-06 新规", "url": "https://news.cctv.cn/2026/07/06/ARTIJUkfhAGrSpiQqDrUizkG260706.shtml", "effective": "2026-07-06"},
)

MAIN = "MAIN"
STAR = "STAR"
CHINEXT = "CHINEXT"
BSE = "BSE"

MAIN_LIMIT = 0.10
STAR_CHINEXT_LIMIT = 0.20
BSE_LIMIT = 0.30
ST_MAIN_OLD_LIMIT = 0.05
ST_CHANGE_DATE = date(2026, 7, 6)
IPO_NO_LIMIT_DAYS = 5

STAMP_TAX_SELL = 0.0005
TRANSFER_FEE_BOTH = 0.00001
COMMISSION_CAP = 0.003
COMMISSION_MIN_CNY = 5.0
REGULATORY_FEE_IN_COMMISSION = 0.0000541
PRICE_TICK = 0.01
LOT_MAIN = 100
LOT_STAR_MIN = 200


def normalise_symbol(raw: str) -> str:
    """Return a 6-digit A-share code. Raises on non A-share input."""
    s = str(raw).strip().upper()
    for suffix in (".SH", ".SZ", ".BJ", ".SS"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    if len(s) != 6 or not s.isdigit():
        raise ValueError(f"not a 6-digit A-share code: {raw!r}")
    return s


def board_of(symbol: str) -> str:
    s = normalise_symbol(symbol)
    if s.startswith(("688", "689")):
        return STAR
    if s.startswith(("300", "301", "302")):
        return CHINEXT
    if s.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return MAIN
    if s.startswith(("43", "83", "87", "88", "92", "8", "4")):
        return BSE
    raise ValueError(f"cannot determine board for {symbol!r}")


def is_shanghai(symbol: str) -> bool:
    return normalise_symbol(symbol).startswith(("6", "688", "689", "5"))


def price_limit_pct(symbol: str, *, is_st: bool = False, is_delisting: bool = False,
                    listing_day: int | None = None, as_of: date | None = None) -> float | None:
    """Return the daily price-limit ratio, or None when no limit applies.

    ``listing_day`` is the 1-based trading-day index since IPO; days 1..5 are
    unrestricted on main/STAR/ChiNext. ``as_of`` governs the 2026-07-06 ST
    rule change; pass the backtest bar date, never ``date.today()``.
    """
    board = board_of(symbol)
    as_of = as_of or date.today()
    if listing_day is not None and 1 <= listing_day <= IPO_NO_LIMIT_DAYS and board in (MAIN, STAR, CHINEXT):
        return None
    if is_delisting and listing_day == 1:
        return None
    if is_st:
        if board == MAIN:
            return MAIN_LIMIT if as_of >= ST_CHANGE_DATE else ST_MAIN_OLD_LIMIT
        if board in (STAR, CHINEXT):
            return STAR_CHINEXT_LIMIT
        return BSE_LIMIT
    if board == MAIN:
        return MAIN_LIMIT if not is_delisting else MAIN_LIMIT
    if board in (STAR, CHINEXT):
        return STAR_CHINEXT_LIMIT
    return BSE_LIMIT


def _round_tick(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def price_limits(prev_close: float, pct: float | None) -> tuple[float | None, float | None]:
    """(lower, upper) limit prices rounded to 0.01. (None, None) = no limit."""
    if pct is None or prev_close <= 0:
        return None, None
    return _round_tick(prev_close * (1 - pct)), _round_tick(prev_close * (1 + pct))


@dataclass(frozen=True)
class FeeSchedule:
    commission_rate: float = 0.00025      # user-configurable; broker-specific, default ~wan2.5
    commission_min_cny: float = COMMISSION_MIN_CNY
    stamp_tax_sell: float = STAMP_TAX_SELL
    transfer_fee_both: float = TRANSFER_FEE_BOTH
    regulatory_fee_included: bool = True  # when False, add REGULATORY_FEE_IN_COMMISSION

    def validate(self) -> None:
        if not 0 <= self.commission_rate <= COMMISSION_CAP:
            raise ValueError(f"commission_rate must be within [0, {COMMISSION_CAP}] (regulatory cap)")


@dataclass(frozen=True)
class FeeBreakdown:
    notional: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    regulatory_fee: float

    @property
    def total(self) -> float:
        return self.commission + self.stamp_tax + self.transfer_fee + self.regulatory_fee


def calculate_fees(side: str, price: float, qty: int, schedule: FeeSchedule | None = None) -> FeeBreakdown:
    """Exchange/CSRC fees. ``side`` is 'BUY' or 'SELL'."""
    s = schedule or FeeSchedule()
    s.validate()
    if price <= 0 or qty <= 0:
        return FeeBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)
    notional = price * qty
    commission = max(notional * s.commission_rate, s.commission_min_cny)
    stamp = notional * s.stamp_tax_sell if side == "SELL" else 0.0
    transfer = notional * s.transfer_fee_both
    reg = 0.0 if s.regulatory_fee_included else notional * REGULATORY_FEE_IN_COMMISSION
    return FeeBreakdown(notional, commission, stamp, transfer, reg)


def normalise_qty(symbol: str, qty: float, side: str, held: int = 0) -> tuple[int, str]:
    """Round an intended quantity into a legal A-share order size.

    Returns (qty, note). A note is recorded so the backtest can report how
    often market microstructure actually changed the intended trade.
    """
    board = board_of(symbol)
    want = int(qty)
    if want <= 0:
        return 0, "ZERO_QTY"
    if side == "SELL":
        if want >= held:
            return held, "SELL_ALL_RESIDUAL" if held % 100 else "SELL_ALL"
        if board == STAR and held - want < LOT_STAR_MIN:
            return held, "SELL_ALL_RESIDUAL"
        if board in (MAIN, CHINEXT) and held - want < LOT_MAIN:
            return held, "SELL_ALL_RESIDUAL"
    if board == STAR:
        if want < LOT_STAR_MIN:
            return 0, "BELOW_STAR_MIN_200"
        return want, "STAR_1_SHARE_INCREMENT"
    if board == BSE:
        if want < LOT_MAIN:
            return 0, "BELOW_BSE_MIN_100"
        return want, "BSE_1_SHARE_INCREMENT"
    rounded = (want // LOT_MAIN) * LOT_MAIN
    if rounded != want:
        return rounded, "ROUNDED_TO_LOT_100"
    return rounded, "LOT_100_OK"


SESSION_OPEN_CALL = (time(9, 15), time(9, 25))
SESSION_AM = (time(9, 30), time(11, 30))
SESSION_PM = (time(13, 0), time(14, 57))
SESSION_CLOSE_CALL = (time(14, 57), time(15, 0))
SESSION_AFTER_HOURS = (time(15, 5), time(15, 30))


def market_phase(ts: datetime | None = None) -> str:
    """Classify a Beijing-time timestamp into an A-share trading phase."""
    ts = ts or datetime.now(CN_TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=CN_TZ)
    t = ts.astimezone(CN_TZ).time()
    if SESSION_OPEN_CALL[0] <= t < SESSION_OPEN_CALL[1]:
        return "OPEN_CALL_AUCTION"
    if SESSION_AM[0] <= t < SESSION_AM[1]:
        return "CONTINUOUS_AM"
    if SESSION_PM[0] <= t < SESSION_CLOSE_CALL[0]:
        return "CONTINUOUS_PM"
    if SESSION_CLOSE_CALL[0] <= t < SESSION_CLOSE_CALL[1]:
        return "CLOSE_CALL_AUCTION"
    if SESSION_AFTER_HOURS[0] <= t <= SESSION_AFTER_HOURS[1]:
        return "AFTER_HOURS_FIXED_PRICE"
    return "CLOSED"


def is_continuous_session(ts: datetime | None = None) -> bool:
    return market_phase(ts) in ("CONTINUOUS_AM", "CONTINUOUS_PM")


class TradingCalendar:
    """Explicit, sourced trading-day set.

    There is deliberately NO hard-coded holiday table: fabricating regulatory
    dates would defeat the purpose of a production backtest. Load the calendar
    from the broker feed (QMT/xtdata) or an authorised data vendor, and let the
    engine refuse to run on an unverified calendar unless explicitly allowed.
    """

    def __init__(self, trading_dates: Iterable[str], source: str, authoritative: bool = True):
        self.dates = sorted({str(d)[:10] for d in trading_dates})
        self._set = set(self.dates)
        self.source = source
        self.authoritative = authoritative
        if not self.dates:
            raise ValueError("trading calendar is empty")

    @classmethod
    def from_dates(cls, dates: Iterable[str], source: str = "explicit test fixture") -> "TradingCalendar":
        return cls(dates, source, authoritative=True)

    @classmethod
    def weekday_fallback(cls, start: str, end: str) -> "TradingCalendar":
        """NOT authoritative. Weekdays only, ignores all holidays. For tests only."""
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
        out, d = [], d0
        while d <= d1:
            if d.weekday() < 5:
                out.append(d.isoformat())
            d += timedelta(days=1)
        return cls(out, "WEEKDAY_FALLBACK_NOT_AUTHORITATIVE(no holidays)", authoritative=False)

    def is_trading_day(self, d: str | date) -> bool:
        return (d if isinstance(d, str) else d.isoformat())[:10] in self._set

    def next_trading_day(self, d: str, steps: int = 1) -> str | None:
        future = [x for x in self.dates if x > d[:10]]
        return future[steps - 1] if len(future) >= steps else None

    def between(self, start: str, end: str) -> list[str]:
        return [d for d in self.dates if start <= d <= end]

    def describe(self) -> dict:
        return {"source": self.source, "authoritative": self.authoritative,
                "days": len(self.dates), "first": self.dates[0], "last": self.dates[-1]}


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str = ""
    board: str = ""
    is_st: bool = False
    is_delisting: bool = False
    listing_date: str = ""
    suspended: bool = False
    adj_factor: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalise_symbol(self.symbol))
        if not self.board:
            object.__setattr__(self, "board", board_of(self.symbol))
