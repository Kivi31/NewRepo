from config import config
from broker import MockBroker
from strategy import generate_signal
from risk import RiskManager


def run_bot():
    print("=" * 45)
    print("SBER TRADING BOT")
    print("Режим:", config.MODE)
    print("Инструмент:", config.SYMBOL)
    print("=" * 45)

    if config.MODE != "MOCK":
        raise RuntimeError(
            "Этот вариант программы поддерживает только MOCK"
        )

    broker = MockBroker()
    risk = RiskManager()

    candles = broker.get_history(config.HISTORY_BARS)

    position = None
    completed_trades = 0

    for i in range(config.SLOW_MA + 1, len(candles)):
        history = candles.iloc[:i + 1]
        candle = candles.iloc[i]

        # Если позиция открыта — проверяем стоп и тейк
        if position is not None:
            exit_price = None
            reason = None

            if candle["low"] <= position["stop"]:
                exit_price = position["stop"]
                reason = "STOP LOSS"

            elif candle["high"] >= position["target"]:
                exit_price = position["target"]
                reason = "TAKE PROFIT"

            if exit_price is not None:
                order = broker.place_market_order(
                    "SELL",
                    position["lots"],
                    exit_price
                )

                pnl = (
                    (order["price"] - position["entry_price"])
                    * order["quantity"]
                    - position["buy_commission"]
                    - order["commission"]
                )

                risk.register_pnl(pnl)
                completed_trades += 1

                print(
                    f"{reason}: результат {pnl:.2f} ₽"
                )

                position = None

            continue

        # Проверяем дневные ограничения
        if not risk.can_trade():
            break

        signal = generate_signal(history)

        if signal != "BUY":
            continue

        price = float(candle["close"])

        lots = risk.calculate_position_size(price)

        if lots <= 0:
            print("Недостаточно средств или лимита риска")
            continue

        order = broker.place_market_order(
            "BUY",
            lots,
            price
        )

        risk.register_trade()

        entry_price = order["price"]

        position = {
            "lots": lots,
            "entry_price": entry_price,
            "buy_commission": order["commission"],
            "stop": entry_price * (
                1 - config.STOP_LOSS_PCT
            ),
            "target": entry_price * (
                1 + config.TAKE_PROFIT_PCT
            )
        }

        print(
            f"Открыта LONG-позиция: "
            f"{lots} лот., цена {entry_price:.2f} ₽"
        )

    # Закрываем позицию в конце теста
    if position is not None:
        last_price = float(candles.iloc[-1]["close"])

        order = broker.place_market_order(
            "SELL",
            position["lots"],
            last_price
        )

        pnl = (
            (order["price"] - position["entry_price"])
            * order["quantity"]
            - position["buy_commission"]
            - order["commission"]
        )

        risk.register_pnl(pnl)
        completed_trades += 1

        print(f"Закрытие в конце теста: {pnl:.2f} ₽")

    print("\n========== ИТОГ ==========")
    print(f"Завершено сделок: {completed_trades}")
    print(f"Капитал: {risk.cash:.2f} ₽")
    print(f"Дневной убыток: {risk.daily_loss:.2f} ₽")
    print("==========================")

    return risk.cash


if __name__ == "__main__":
    run_bot()
