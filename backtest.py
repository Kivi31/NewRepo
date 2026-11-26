
if __name__ == "__main__":
    from config import CONFIG

    cfg = CONFIG

    # Загружаем CSV с историческими свечами.
    df = pd.read_csv("data/sber_history.csv")

    df["timestamp"] = pd.to_datetime(
        df["timestamp"]
    )

    result = backtest(df, cfg)

    print("\n===== BACKTEST RESULTS =====")

    for key, value in result.items():
        if key != "history":
            print(f"{key}: {value}")

    result["history"].to_csv(
        "logs/backtest_trades.csv",
        index=False
    )

    print("\nИстория сделок сохранена.")

