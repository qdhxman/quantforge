/* SYNTHETIC ACCEPTANCE SNAPSHOT - NOT REAL MARKET DATA. Regenerate with python scripts/ashare_pipeline.py */
window.QF_ASHARE_SNAPSHOT = {
  "generated_at": "2026-11-07T10:00:00+08:00",
  "disclaimer": "决策支持信号，非投资建议；系统不自动下单，需人工在券商客户端执行。",
  "mode": "MONITOR_ONLY_NO_EXECUTION",
  "data_class": "SYNTHETIC TEST FIXTURE - NOT REAL MARKET DATA",
  "feed": {
    "feed": "local-cache",
    "available": true,
    "source": "SYNTHETIC-FIXTURE",
    "built_at": "2026-11-07T10:34:00+08:00",
    "license": "synthetic-test-fixture",
    "note": "offline snapshot, NOT live"
  },
  "cycle": {
    "ts": "2026-11-07T10:00:00+08:00",
    "session": "CONTINUOUS_AM",
    "skipped": false,
    "quality": {
      "ok": true,
      "checked_at": "2026-11-07T10:00:00+08:00",
      "errors": [],
      "warnings": [],
      "checks": {
        "symbols": 6,
        "stale": 0,
        "bad_price": 0,
        "bad_ohlc": 0,
        "limit_breach": 0,
        "missing_provenance": 0,
        "suspended": 0
      }
    },
    "tickets": [
      {
        "symbol": "300750",
        "name": "SYNTHETIC-300750",
        "board": "CHINEXT",
        "side": "BUY",
        "as_of": "2026-11-07T10:00:00+08:00",
        "session": "CONTINUOUS_AM",
        "signal_score": 0.4557876243766057,
        "signal_reason": "综合得分 +0.456（BUY），阈值 ±0.20；主导因子 momentum(+0.77)、ma_cross(+0.37)",
        "last_price": 43.9762,
        "limit_up": 52.7,
        "limit_down": 35.14,
        "suggested_qty": 2200,
        "suggested_price_low": 43.756,
        "suggested_price_high": 44.196,
        "estimated_notional": 96747.64,
        "estimated_fees": {
          "commission": 24.19,
          "stamp_tax": 0.0,
          "transfer_fee": 0.97,
          "total": 25.15
        },
        "tradable": true,
        "checks": [
          {
            "name": "数据质量门禁",
            "passed": true,
            "detail": "通过"
          },
          {
            "name": "行情新鲜度",
            "passed": true,
            "detail": "2026-11-07T10:00:00+08:00"
          },
          {
            "name": "停牌",
            "passed": true,
            "detail": "正常交易"
          },
          {
            "name": "ST 过滤",
            "passed": true,
            "detail": "非 ST"
          },
          {
            "name": "涨停不可买",
            "passed": true,
            "detail": "last=43.9762 upper=52.7"
          },
          {
            "name": "跌停不可卖",
            "passed": true,
            "detail": "last=43.9762 lower=35.14"
          },
          {
            "name": "T+1 可用持仓",
            "passed": true,
            "detail": "需人工核对可用持仓"
          },
          {
            "name": "单票仓位上限",
            "passed": true,
            "detail": "target=0.125 cap=0.2"
          },
          {
            "name": "单笔金额上限",
            "passed": true,
            "detail": "96,748 / 100,000"
          },
          {
            "name": "申报数量合规",
            "passed": true,
            "detail": "qty=2200 (ROUNDED_TO_LOT_100)"
          },
          {
            "name": "板块权限",
            "passed": true,
            "detail": "board=CHINEXT permitted=['MAIN', 'CHINEXT', 'STAR']"
          }
        ],
        "data_source": "SYNTHETIC-FIXTURE",
        "data_quality": "OK",
        "notes": [
          "本单据为人工执行建议，系统不会自动下单。",
          "建议数量已受单笔金额上限 100,000 元约束（目标仓位金额 125,171 元）。",
          "未接入真实账户，数量按假设资金估算；执行前请按实际可用资金与持仓换算。",
          "涨跌停价与复权口径来自行情源；执行前在券商客户端复核。"
        ]
      },
      {
        "symbol": "601318",
        "name": "SYNTHETIC-601318",
        "board": "MAIN",
        "side": "BUY",
        "as_of": "2026-11-07T10:00:00+08:00",
        "session": "CONTINUOUS_AM",
        "signal_score": 0.5614642952429465,
        "signal_reason": "综合得分 +0.561（BUY），阈值 ±0.20；主导因子 momentum(+0.87)、ma_cross(+0.35)",
        "last_price": 29.9246,
        "limit_up": 33.04,
        "limit_down": 27.04,
        "suggested_qty": 3300,
        "suggested_price_low": 29.775,
        "suggested_price_high": 30.074,
        "estimated_notional": 98751.18,
        "estimated_fees": {
          "commission": 24.69,
          "stamp_tax": 0.0,
          "transfer_fee": 0.99,
          "total": 25.68
        },
        "tradable": true,
        "checks": [
          {
            "name": "数据质量门禁",
            "passed": true,
            "detail": "通过"
          },
          {
            "name": "行情新鲜度",
            "passed": true,
            "detail": "2026-11-07T10:00:00+08:00"
          },
          {
            "name": "停牌",
            "passed": true,
            "detail": "正常交易"
          },
          {
            "name": "ST 过滤",
            "passed": true,
            "detail": "非 ST"
          },
          {
            "name": "涨停不可买",
            "passed": true,
            "detail": "last=29.9246 upper=33.04"
          },
          {
            "name": "跌停不可卖",
            "passed": true,
            "detail": "last=29.9246 lower=27.04"
          },
          {
            "name": "T+1 可用持仓",
            "passed": true,
            "detail": "需人工核对可用持仓"
          },
          {
            "name": "单票仓位上限",
            "passed": true,
            "detail": "target=0.140 cap=0.2"
          },
          {
            "name": "单笔金额上限",
            "passed": true,
            "detail": "98,751 / 100,000"
          },
          {
            "name": "申报数量合规",
            "passed": true,
            "detail": "qty=3300 (ROUNDED_TO_LOT_100)"
          },
          {
            "name": "板块权限",
            "passed": true,
            "detail": "board=MAIN permitted=['MAIN', 'CHINEXT', 'STAR']"
          }
        ],
        "data_source": "SYNTHETIC-FIXTURE",
        "data_quality": "OK",
        "notes": [
          "本单据为人工执行建议，系统不会自动下单。",
          "建议数量已受单笔金额上限 100,000 元约束（目标仓位金额 139,701 元）。",
          "未接入真实账户，数量按假设资金估算；执行前请按实际可用资金与持仓换算。",
          "涨跌停价与复权口径来自行情源；执行前在券商客户端复核。"
        ]
      }
    ],
    "alerts": [],
    "signals": [
      {
        "date": "2026-07-29",
        "symbol": "600519",
        "action": "HOLD",
        "score": 0.1126,
        "raw_score": 0.1126,
        "target_weight": null,
        "contributions": {
          "momentum": 0.084812,
          "ma_cross": 0.066114,
          "volume_spike": -0.003681,
          "low_volatility": 0.122995
        },
        "raw_values": {
          "momentum": 0.084812,
          "ma_cross": 0.094449,
          "volume_spike": -0.009203,
          "low_volatility": 0.409983
        },
        "coverage": 1.0,
        "reason": "综合得分 +0.113（HOLD），阈值 ±0.20；主导因子 low_volatility(+0.12)、momentum(+0.08)"
      },
      {
        "date": "2026-07-29",
        "symbol": "000001",
        "action": "HOLD",
        "score": -0.10821,
        "raw_score": -0.10821,
        "target_weight": null,
        "contributions": {
          "momentum": -0.143491,
          "ma_cross": -0.140196,
          "volume_spike": -0.008089,
          "low_volatility": 0.032073
        },
        "raw_values": {
          "momentum": -0.143491,
          "ma_cross": -0.200281,
          "volume_spike": -0.020223,
          "low_volatility": 0.106909
        },
        "coverage": 1.0,
        "reason": "综合得分 -0.108（HOLD），阈值 ±0.20；主导因子 momentum(-0.14)、ma_cross(-0.14)"
      },
      {
        "date": "2026-07-29",
        "symbol": "300750",
        "action": "BUY",
        "score": 0.455788,
        "raw_score": 0.455788,
        "target_weight": 0.125171,
        "contributions": {
          "momentum": 0.769604,
          "ma_cross": 0.370934,
          "volume_spike": -0.048169,
          "low_volatility": 0.001522
        },
        "raw_values": {
          "momentum": 0.769604,
          "ma_cross": 0.529906,
          "volume_spike": -0.120423,
          "low_volatility": 0.005073
        },
        "coverage": 1.0,
        "reason": "综合得分 +0.456（BUY），阈值 ±0.20；主导因子 momentum(+0.77)、ma_cross(+0.37)"
      },
      {
        "date": "2026-07-29",
        "symbol": "688981",
        "action": "HOLD",
        "score": -0.063986,
        "raw_score": -0.063986,
        "target_weight": null,
        "contributions": {
          "momentum": -0.235083,
          "ma_cross": -0.045486,
          "volume_spike": 0.034014,
          "low_volatility": 0.092988
        },
        "raw_values": {
          "momentum": -0.235083,
          "ma_cross": -0.06498,
          "volume_spike": 0.085035,
          "low_volatility": 0.30996
        },
        "coverage": 1.0,
        "reason": "综合得分 -0.064（HOLD），阈值 ±0.20；主导因子 momentum(-0.24)、low_volatility(+0.09)"
      },
      {
        "date": "2026-07-29",
        "symbol": "601318",
        "action": "BUY",
        "score": 0.561464,
        "raw_score": 0.561464,
        "target_weight": 0.139701,
        "contributions": {
          "momentum": 0.870177,
          "ma_cross": 0.34901,
          "volume_spike": 0.019836,
          "low_volatility": 0.108491
        },
        "raw_values": {
          "momentum": 0.870177,
          "ma_cross": 0.498585,
          "volume_spike": 0.049591,
          "low_volatility": 0.361638
        },
        "coverage": 1.0,
        "reason": "综合得分 +0.561（BUY），阈值 ±0.20；主导因子 momentum(+0.87)、ma_cross(+0.35)"
      },
      {
        "date": "2026-07-29",
        "symbol": "002594",
        "action": "HOLD",
        "score": 0.171418,
        "raw_score": 0.171418,
        "target_weight": null,
        "contributions": {
          "momentum": 0.244714,
          "ma_cross": 0.208413,
          "volume_spike": 0.007608,
          "low_volatility": -0.049332
        },
        "raw_values": {
          "momentum": 0.244714,
          "ma_cross": 0.297733,
          "volume_spike": 0.019021,
          "low_volatility": -0.164439
        },
        "coverage": 1.0,
        "reason": "综合得分 +0.171（HOLD），阈值 ±0.20；主导因子 momentum(+0.24)、ma_cross(+0.21)"
      }
    ]
  }
};
