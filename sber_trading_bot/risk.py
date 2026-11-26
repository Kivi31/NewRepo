
import json
from pathlib import Path
from datetime import date

from config import config


class RiskManager:
    def __init__(self):
        self.cash = config.INITIAL_CAPITAL
        self.daily_loss = 0.0
        self.trades_today = 0
        self.current_date = date.today()
        self.state_file = Path("risk_state.json")

        self.load_state()

    def load_state(self):
        """Загружает состояние дневного лимита."""
        if not self.state_file.exists():
            return

        try:
            state = json.loads(self.state_file.read_text())
            saved_date = date.fromisoformat(state["date"])

            if saved_date == self.current_date:
                self.daily_loss = float(state["daily_loss"])
                self.trades_today = int(state["trades_today"])

        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            print("Предупреждение: не удалось загрузить состояние риска")

    def save_state(self):
        """Сохраняет дневной убыток и число сделок."""
        state = {
            "date": self.current_date.isoformat(),
            "daily_loss": self.daily_loss,
            "trades_today": self.trades_today,
        }

        self.state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=4)
        )

    def update_day(self):
        """Сбрасывает дневные показатели при смене даты."""
        today = date.today()

        if today != self.current_date:
            self.current_date = today
            self.daily_loss = 0.0
            self.trades_today = 0
            self.save_state()

    def can_trade(self):
        """Проверяет, разрешена ли новая сделка."""
        self.update_day()

        if self.daily_loss >= config.DAILY_LOSS_LIMIT:
            print("Торговля остановлена: достигнут дневной лимит убытка")
            return False

        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            print("Достигнут лимит сделок на сегодня")
            return False

        return True

    def calculate_position_size(self, price):
        """
        Рассчитывает количество лотов с учётом:
        - доступных денег;
        - риска на стоп-лосс;
        - дневного лимита убытка.

        Важно: LOT_SIZE — число акций в одном лоте.
        """
        if price <= 0:
            return 0

        if not self.can_trade():
            return 0

        lot_cost = price * config.LOT_SIZE

        risk_per_lot = (
            lot_cost * config.STOP_LOSS_PCT
            + lot_cost * 2 * (
                config.COMMISSION_PCT + config.SLIPPAGE_PCT
            )
        )

        available_risk = (
            config.DAILY_LOSS_LIMIT - self.daily_loss
        )

        if risk_per_lot <= 0:
            return 0

        lots_by_cash = int(self.cash // lot_cost)
        lots_by_risk = int(available_risk // risk_per_lot)

        return max(0, min(lots_by_cash, lots_by_risk))

    def register_trade(self):
        """Регистрирует новую сделку."""
        self.update_day()
        self.trades_today += 1
        self.save_state()

    def register_pnl(self, pnl):
        """Учитывает результат закрытой сделки."""
        self.update_day()

        if pnl < 0:
            self.daily_loss += abs(pnl)

        self.cash += pnl
        self.save_state()

        if self.daily_loss >= config.DAILY_LOSS_LIMIT:
            print("Дневной лимит убытка достигнут!")
