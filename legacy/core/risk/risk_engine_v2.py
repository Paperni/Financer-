"""
Risk Engine v2: portfolio-level risk gates for new entries.
"""

from __future__ import annotations

from typing import Any

import portfolio as pf


class RiskEngineV2:
    def __init__(self, risk_cfg: dict[str, Any] | None = None):
        cfg = risk_cfg or {}
        self.max_positions_per_sector = int(cfg.get("max_positions_per_sector", 3))
        self.daily_loss_halt_pct = float(cfg.get("daily_loss_halt_pct", 0.03))
        self.max_open_risk_pct_of_equity = float(cfg.get("max_open_risk_pct_of_equity", 0.10))
        self.max_new_position_risk_pct_of_equity = float(
            cfg.get("max_new_position_risk_pct_of_equity", 0.025)
        )
        self.max_position_notional_pct = float(cfg.get("max_position_notional_pct", 0.10))

    def _today_realized_pnl(self, wallet: dict[str, Any]) -> float:
        today = pf.now_et().date()
        realized = 0.0
        for trade in wallet.get("history", []):
            if trade.get("Action") != "SELL":
                continue
            try:
                ts = trade.get("Time", "")
                if not ts:
                    continue
                if ts.startswith(str(today)):
                    realized += float(trade.get("PnL", 0))
            except Exception:
                continue
        return realized

    def _estimate_open_risk(self, wallet: dict[str, Any]) -> float:
        open_risk = 0.0
        for pos in wallet.get("holdings", {}).values():
            if pos.get("is_baseline"):
                continue
            qty = float(pos.get("qty", 0))
            entry = float(pos.get("entry_price", 0))
            sl = float(pos.get("sl", entry))
            risk_per_share = max(0.0, entry - sl)
            open_risk += qty * risk_per_share
        return open_risk

    def can_open_new_positions(self, wallet: dict[str, Any]) -> tuple[bool, str]:
        initial = float(wallet.get("initial_capital", 100000.0))
        realized_today = self._today_realized_pnl(wallet)
        if realized_today <= -initial * self.daily_loss_halt_pct:
            return (
                False,
                f"Risk halt: daily loss {realized_today:,.0f} exceeds "
                f"{self.daily_loss_halt_pct:.1%} limit",
            )

        equity = max(1.0, float(pf.calc_equity(wallet)))
        open_risk = self._estimate_open_risk(wallet)
        if open_risk > equity * self.max_open_risk_pct_of_equity:
            return (
                False,
                f"Risk halt: open risk {open_risk:,.0f} exceeds "
                f"{self.max_open_risk_pct_of_equity:.1%} of equity",
            )

        return True, "OK"

    def can_take_entry(
        self,
        wallet: dict[str, Any],
        candidate_sector: str,
        sector_count: dict[str, int],
        price: float,
        atr: float | None,
    ) -> tuple[bool, str]:
        if (
            candidate_sector
            and candidate_sector != "Unknown"
            and sector_count.get(candidate_sector, 0) >= self.max_positions_per_sector
        ):
            return (
                False,
                f"Sector cap reached ({candidate_sector} >= {self.max_positions_per_sector})",
            )

        equity = max(1.0, float(pf.calc_equity(wallet)))
        stop_distance = float(atr) * pf.ATR_STOP_MULTIPLIER if atr else float(price) * pf.FALLBACK_STOP_PCT
        est_notional = equity * self.max_position_notional_pct
        est_qty = int(est_notional / max(0.01, float(price)))
        est_new_risk = est_qty * max(0.0, stop_distance)
        if est_new_risk > equity * self.max_new_position_risk_pct_of_equity:
            return (
                False,
                f"Entry risk too high ({est_new_risk:,.0f} > "
                f"{self.max_new_position_risk_pct_of_equity:.1%} of equity)",
            )

        return True, "OK"
