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

ratio = vix / ann
if ratio > 1.15:
    view = f"Options mehengi ({(ratio-1)*100:.0f}% upar): selling edge"
elif ratio < 0.95:
    view = f"Options sasti ({(1-ratio)*100:.0f}% neeche): buying edge"
else:
    view = "Options fair: koi clear edge nahi"

last = float(d.iloc[-1])
r1 = last * vol / 100
r2 = 2 * r1

msg = (f"Nifty close: {last:.0f}\n"
       f"Agle trading din ka range (close se):\n"
       f"GARCH vol: {vol:.2f}% (annual {ann:.1f}%)\n"
       f"1σ range: {last-r1:.0f} - {last+r1:.0f}\n"
       f"2σ range: {last-r2:.0f} - {last+r2:.0f}\n"
       f"India VIX: {vix:.1f}\n{view}\n"
       f"Stop: {1.5*vol:.2f}% | Position: Rs {size:,.0f} (risk Rs {risk})")

requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
              data={"chat_id": os.environ["TG_CHAT"], "text": msg})
