from dhanhq import dhanhq
import pandas as pd, numpy as np
from arch import arch_model

dhan = dhanhq("CLIENT_ID", "ACCESS_TOKEN")
r = dhan.historical_daily_data("13", "IDX_I", "INDEX",
                               "2021-01-01", "2026-10-03")
close = pd.DataFrame(r["data"])["close"]

ret = 100 * np.log(close).diff().dropna()
res = arch_model(ret, vol="GARCH", p=1, q=1, dist="t").fit(disp="off")
vol = res.forecast(horizon=1).variance.iloc[-1, 0] ** 0.5

risk = 10000                      # per trade risk (₹)
stop_pct = 1.5 * vol / 100        # dynamic stop
print(f"Vol: {vol:.2f}%  Position: ₹{risk/stop_pct:,.0f}")
