import numpy as np
import pandas as pd

from config import config


class MockBroker:
    """Имитация брокера без реальных торговых операций."""

    def __init__(self):
        self.position = None

    def get_history(self, count=300):
        """Создаёт искусственные свечи SBER для тестирования."""
        rng = np.random.default_rng(42)

        dates = pd.date_range(
            start="2026-11-20 10:00",
            periods=count,
            freq="5min"
        )

        changes = rng.normal(0, 0.0015, count)

        # Добавляем участки роста и снижения для проверки стратегии
        changes[60:110] += 0.0008
        changes[110:160] -= 0.0007
        changes[160:230] += 0.0010

        close = 312 * np.exp(np.cumsum(changes))
        open_price = np.concatenate(([close[0]], close[:-1]))

        high = np.maximum(open_price, close) * (
            1 + rng.uniform(0, 0.001, count)
        )
        low = np.minimum(open_price, close) * (
            1 - rng.uniform(0, 0.001, count)
        )

        volume = rng.integers(1000, 5000, count)

        # Несколько свечей с повышенным объёмом
        volume[80:85] *= 3
        volume[180:185] *= 3

        return pd.DataFrame({
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume
        }, index=dates)

    def place_market_order(self, side, lots, reference_price):
        """Имитирует исполнение рыночного ордера."""

        if side not in ("BUY", "SELL"):
            raise ValueError("Допустимы только BUY и SELL")

        if lots <= 0 or reference_price <= 0:
            raise ValueError("Некорректный объём или цена")

        quantity = lots * config.LOT_SIZE

        if side == "BUY":
            fill_price = reference_price * (
                1 + config.SLIPPAGE_PCT
            )
        else:
            fill_price = reference_price * (
                1 - config.SLIPPAGE_PCT
            )

        commission = (
            fill_price * quantity * config.COMMISSION_PCT
        )

        result = {
            "side": side,
            "lots": lots,
            "quantity": quantity,
            "price": fill_price,
            "commission": commission
        }

        print(
            f"{side}: {lots} лот. "
            f"Цена: {fill_price:.2f} ₽"
        )

        return result
