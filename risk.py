
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from logger import logger


class RiskManager:

    def __init__(self, cfg):
        self.cfg = cfg
        self.timezone = ZoneInfo(cfg.timezone)

        os.makedirs("data", exist_ok=True)

        self.state_file = cfg.risk_state_file

        self.state = {
            "day": "",
            "daily_loss": 0.0,
            "trades": 0
        }

        self._load_state()
        self._reset_if_new_day()

    def _today(self):
        return datetime.now(self.timezone).date().isoformat()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(
                    self.state_file,
                    "r",
                    encoding="utf-8"
                ) as f:
                    self.state = json.load(f)
            except (ValueError, OSError):
                logger.exception("Не удалось загрузить риск-состояние")

    def _save_state(self):
        tmp = self.state_file + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

        os.replace(tmp, self.state_file)

    def _reset_if_new_day(self):
        today = self._today()

        if self.state.get("day") != today:
            self.state = {
                "day": today,
                "daily_loss": 0.0,
                "trades": 0
            }

            self._save_state()
            logger.info("Новый торговый день. Счётчик убытка сброшен.")

    @property
    def daily_loss(self):
        self._reset_if_new_day()
        return float(self.state["daily_loss"])

    def is_stopped(self):
        self._reset_if_new_day()

        stopped = (
            self.daily_loss >= self.cfg.daily_loss_limit
        )

        if stopped:
            logger.warning(
                "RISK MANAGER: дневной лимит достигнут: %.2f RUB",
                self.daily_loss
            )

        return stopped

    def calculate_position(self, available_cash, price):
        """
        max_position = min(
            available_capital,
            daily_limit / (SL% * N)
        )

        Результат округляется вниз до целых биржевых лотов.
        """

        risk_budget = (
            self.cfg.daily_loss_limit
            / (
                self.cfg.stop_loss_pct
                * self.cfg.attempts_per_day
            )
        )

        max_position = min(
            available_cash,
            risk_budget
        )

        lot_cost = (
            price * self.cfg.lot_size_shares
        )

        if lot_cost <= 0:
            return 0

        lots = int(max_position // lot_cost)

        return max(0, lots)

    def check_entry(self, price, lots):
        """
        Проверяем потенциальный убыток по SL.
        """

        self._reset_if_new_day()

        if self.is_stopped():
            logger.warning("Вход запрещён: дневной лимит")
            return False

        if lots <= 0:
            logger.warning("Вход запрещён: недостаточно капитала")
            return False

        position_shares = (
            lots * self.cfg.lot_size_shares
        )

        potential_loss = (
            price
            * position_shares
            * self.cfg.stop_loss_pct
        )

        # Резервируем также приблизительную комиссию
        # на вход и выход.
        estimated_costs = (
            2
            * price
            * position_shares
            * (
                self.cfg.commission_pct
                + self.cfg.slippage_pct
            )
        )

        total_risk = potential_loss + estimated_costs

        allowed = (
            self.daily_loss + total_risk
            <= self.cfg.daily_loss_limit
        )

        if not allowed:
            logger.warning(
                "RISK BLOCK | daily_loss=%.2f "
                "potential_loss=%.2f total=%.2f",
                self.daily_loss,
                potential_loss,
                total_risk
            )

        return allowed

    def record_trade(self, pnl):
        """
        Учитываем только реализованные убытки.
        Прибыль не компенсирует ранее полученный убыток.
        """

        self._reset_if_new_day()

        if pnl < 0:
            self.state["daily_loss"] += abs(pnl)

        self.state["trades"] += 1

        self._save_state()

        logger.info(
            "DAILY LOSS: %.2f / %.2f RUB",
            self.daily_loss,
            self.cfg.daily_loss_limit
        )

        if self.is_stopped():
            logger.warning(
                "RISK MANAGER ACTIVATED: торговля остановлена"
            )
