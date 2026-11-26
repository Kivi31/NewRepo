from config import config
from broker import MockBroker
from strategy import generate_signal


def run_backtest(candles=None):
    if candles is None:
        candles = MockBroker().get_history(500)

    cash = config.INITIAL_CAPITAL
    daily_loss = 0.0
    trades_today = 0
    current_day = None

    position = None
    trades = []
    equity_curve = []

    broker = MockBroker()

    def close_position(reference_price, reason):
        nonlocal cash, daily_loss, position

        sell = broker.place_market_order(
            "SELL",
            position["lots"],
            float(reference_price)
        )

        pnl = (
            (sell["price"] - position["entry_price"])
            * sell["quantity"]
            - position["buy_commission"]
            - sell["commission"]
        )

        cash += pnl

        if pnl < 0:
            daily_loss += abs(pnl)

        trades.append({
            "pnl": pnl,
            "reason": reason
        })

        print(f"{reason}: {pnl:.2f} ₽")
        position = None

    for i in range(config.SLOW_MA + 1, len(candles)):
        row = candles.iloc[i]
        previous_row = candles.iloc[i - 1]

        # Определяем торговую дату
        day = candles.index[i].date()

        if current_day is None:
            current_day = day

        elif day != current_day:
            # Не переносим позицию на следующий день
            if position is not None:
                close_position(
                    previous_row["close"],
                    "END OF DAY"
                )

            current_day = day
            daily_loss = 0.0
            trades_today = 0

        # Проверяем открытую позицию
        if position is not None:
            if row["low"] <= position["stop"]:
                close_position(
                    position["stop"],
                    "STOP LOSS"
                )

            elif row["high"] >= position["target"]:
                close_position(
                    position["target"],
                    "TAKE PROFIT"
                )

        # Если позиции нет — ищем вход
        if position is None:
            if daily_loss >= config.DAILY_LOSS_LIMIT:
                equity_curve.append(cash)
                continue

            if trades_today >= config.MAX_TRADES_PER_DAY:
                equity_curve.append(cash)
                continue

            signal = generate_signal(candles.iloc[:i + 1])

            if signal == "BUY":
                price = float(row["close"])
                lot_cost = price * config.LOT_SIZE

                risk_per_lot = (
                    lot_cost * config.STOP_LOSS_PCT
                    + lot_cost * 2 * (
                        config.COMMISSION_PCT
                        + config.SLIPPAGE_PCT
                    )
                )

                if risk_per_lot <= 0:
                    equity_curve.append(cash)
                    continue

                available_risk = (
                    config.DAILY_LOSS_LIMIT - daily_loss
                )

                lots_by_cash = int(cash // lot_cost)
                lots_by_risk = int(
                    available_risk // risk_per_lot
                )

                lots = max(
                    0,
                    min(lots_by_cash, lots_by_risk)
                )

                if lots > 0:
                    buy = broker.place_market_order(
                        "BUY",
                        lots,
                        price
                    )

                    entry = buy["price"]

                    position = {
                        "lots": lots,
                        "entry_price": entry,
                        "buy_commission": buy["commission"],
                        "stop": entry * (
                            1 - config.STOP_LOSS_PCT
                        ),
                        "target": entry * (
                            1 + config.TAKE_PROFIT_PCT
                        )
                    }

                    trades_today += 1

        equity_curve.append(cash)

    # Закрываем последнюю позицию
    if position is not None:
        close_position(
            candles.iloc[-1]["close"],
            "FINAL CLOSE"
        )

    total_profit = cash - config.INITIAL_CAPITAL

    wins = sum(1 for trade in trades if trade["pnl"] > 0)
    losses = sum(1 for trade in trades if trade["pnl"] < 0)

    win_rate = (
        wins / len(trades) * 100
        if trades else 0
    )

    print("\n========== BACKTEST ==========")
    print(f"Начальный капитал: {config.INITIAL_CAPITAL:.2f} ₽")
    print(f"Конечный капитал: {cash:.2f} ₽")
    print(f"Финансовый результат: {total_profit:.2f} ₽")
    print(f"Всего сделок: {len(trades)}")
    print(f"Прибыльных: {wins}")
    print(f"Убыточных: {losses}")
    print(f"Доля прибыльных: {win_rate:.2f}%")
    print("==============================")

    return {
        "initial_capital": config.INITIAL_CAPITAL,
        "final_capital": cash,
        "profit": total_profit,
        "trades": trades,
        "win_rate": win_rate
    }


if __name__ == "__main__":
    run_backtest()
