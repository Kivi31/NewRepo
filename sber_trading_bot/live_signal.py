
import pandas as pd

from cassandra_broker import CassandraBroker
from strategy import generate_signal


def main():
    broker = CassandraBroker()

    print("Подключаемся к Cassandra...")
    broker.login()

    print("Получаем реальные свечи SBER...")
    data = broker.get_candles(
        security_id="SBER@TQBR",
        timeframe=300,
        count=200
    )

    df = pd.DataFrame(data["history"])

    if len(df) < 50:
        print("Недостаточно свечей для стратегии")
        return

    signal = generate_signal(df)

    print("\n========== РЕЗУЛЬТАТ ==========")
    print("Инструмент: SBER")
    print("Последняя цена:", df["close"].iloc[-1])
    print("Получено свечей:", len(df))
    print("Сигнал стратегии:", signal)
    print("===============================")


if __name__ == "__main__":
    main()
