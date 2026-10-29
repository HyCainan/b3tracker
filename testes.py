import time
import yfinance as yf

TICKERS = ["WEGE3", "BBAS3", "SUZB3", "B3SA3", "BBDC4", "EMBJ3", "PETR4"]

for t in TICKERS:
    inicio = time.perf_counter()
    try:
        df = yf.Ticker(f"{t}.SA").history(period="1y", interval="1d", raise_errors=True)
        print(f"{t}: {len(df)} linhas ({(time.perf_counter() - inicio) * 1000:.0f} ms)")
    except Exception as e:
        print(f"{t}: ERRO {type(e).__name__}: {e}")
