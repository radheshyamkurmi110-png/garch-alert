import os, requests, numpy as np, yfinance as yf
from arch import arch_model

d = yf.download("^NSEI", period="5y", progress=False)["Close"].squeeze().dropna()
vix = yf.download("^INDIAVIX", period="5d", progress=False)["Close"].squeeze().dropna().iloc[-1]

ret = 100 * np.log(d).diff().dropna()
res = arch_model(ret, vol="GARCH", p=1, q=1, dist="t").fit(disp="off")
vol = res.forecast(horizon=1).variance.iloc[-1, 0] ** 0.5
ann = vol * np.sqrt(252)

risk = 10000
stop = 1.5 * vol / 100
size = risk / stop
view = ("Options mehengi: selling edge" if vix > ann
        else "Options sasti: buying edge")

msg = (f"Nifty close: {d.iloc[-1]:.0f}\n"
       f"GARCH kal ka vol: {vol:.2f}% (annual {ann:.1f}%)\n"
       f"India VIX: {vix:.1f}\n{view}\n"
       f"Stop: {1.5*vol:.2f}% | Position: Rs {size:,.0f} (risk Rs {risk})")

requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
              data={"chat_id": os.environ["TG_CHAT"], "text": msg})
