import os, io, time, requests, pandas as pd, numpy as np, yfinance as yf

RISK = 5000        # ek trade me max risk (Rs), apne hisaab se badlo
TOP = 10
MAX_PER_SECTOR = 2

BASE = ["https://niftyindices.com/IndexConstituent/",
        "https://www.niftyindices.com/IndexConstituent/",
        "https://nsearchives.nseindia.com/content/indices/",
        "https://archives.nseindia.com/content/indices/"]
FILES = {"N50": "ind_nifty50list.csv",
         "NXT50": "ind_niftynext50list.csv",
         "MID150": "ind_niftymidcap150list.csv"}
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 Chrome/120 Safari/537.36",
       "Accept": "text/csv,*/*"}

def send(text):
    requests.post(
        f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TG_CHAT"], "text": text[:4000]})

def load(fname):
    for attempt in range(2):
        for b in BASE:
            try:
                r = requests.get(b + fname, headers=HDR, timeout=30)
                if r.ok and "Symbol" in r.text:
                    return pd.read_csv(io.StringIO(r.text))
            except Exception:
                pass
        time.sleep(3)
    if os.path.exists(fname):
        return pd.read_csv(fname)
    return None

U, missing = {}, []
for tag, fn in FILES.items():
    df = load(fn)
    if df is None:
        missing.append(tag)
        continue
    for _, row in df.iterrows():
        U[str(row["Symbol"]).strip()] = (tag, str(row.get("Industry", "")))

if not U:
    send("Screener: NSE se stock list nahi mili. CSV files repo me upload karo.")
    raise SystemExit

tickers = [s + ".NS" for s in U] + ["^NSEI"]
px = yf.download(tickers, period="1y", group_by="ticker",
                 threads=True, progress=False)

# ---- market regime ----
nc = px["^NSEI"]["Close"].dropna()
n_last = float(nc.iloc[-1])
n200 = float(nc.rolling(200).mean().iloc[-1])
regime_ok = n_last > n200
nr3 = n_last / float(nc.iloc[-63]) - 1
nr6 = n_last / float(nc.iloc[-126]) - 1

def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]))

def atr(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])

def tech(sym):
    try:
        df = px[sym + ".NS"][["High", "Low", "Close", "Volume"]].dropna()
    except Exception:
        return None
    if len(df) < 200:
        return None
    c = df["Close"]
    last = float(c.iloc[-1])
    d50 = float(c.rolling(50).mean().iloc[-1])
    d200 = float(c.rolling(200).mean().iloc[-1])
    hi = float(c.max())
    val20 = float((c * df["Volume"]).tail(20).mean())
    r3 = last / float(c.iloc[-63]) - 1
    r6 = last / float(c.iloc[-126]) - 1
    ok = (last > d50 > d200) and (last / hi >= 0.85) and (val20 >= 10e7)
    rs = (r3 + r6) / 2 - (nr3 + nr6) / 2
    return dict(ok=ok and rs > 0, last=last, d50=d50, hi=hi, r3=r3, r6=r6,
                rs=rs, rsi=rsi(c), atr=atr(df))

T = {}
for s in U:
    t = tech(s)
    if t and t["ok"]:
        T[s] = t

ranked = sorted(T, key=lambda s: T[s]["rs"])
for i, s in enumerate(ranked):
    T[s]["mom"] = i / (len(ranked) - 1) if len(ranked) > 1 else 1.0

def fund_score(sym, industry):
    try:
        i = yf.Ticker(sym + ".NS").info
    except Exception:
        return None
    roe, mar = i.get("returnOnEquity"), i.get("profitMargins")
    rg, eg = i.get("revenueGrowth"), i.get("earningsGrowth")
    pe, de = i.get("trailingPE"), i.get("debtToEquity")
    if sum(x is not None for x in (roe, mar, rg, eg, pe)) < 3:
        return None
    fin = "financial" in industry.lower()
    q = 0
    q += 10 if roe is not None and roe > 0.15 else 0
    q += 10 if mar is not None and mar > 0.10 else 0
    q += 10 if fin or (de is not None and de < 100) else 0
    g = 0
    g += 15 if rg is not None and rg > 0.10 else 0
    g += 15 if eg is not None and eg > 0.15 else 0
    v = 0
    if pe is not None and pe > 0:
        v = 20 if pe < 25 else 12 if pe < 40 else 5 if pe < 60 else 0
    return dict(q=q, g=g, v=v, pe=pe, roe=roe)

rows = []
for s in T:
    time.sleep(0.5)
    f = fund_score(s, U[s][1])
    if not f:
        continue
    t = T[s]
    m = round(20 * t["mom"])
    total = f["q"] + f["g"] + f["v"] + m
    if f["q"] >= 20 and f["g"] >= 15 and total >= 60:
        rows.append((total, s, f, m))

rows.sort(key=lambda x: -x[0])

picked, cnt = [], {}
for total, s, f, m in rows:
    ind = U[s][1]
    if cnt.get(ind, 0) >= MAX_PER_SECTOR:
        continue
    cnt[ind] = cnt.get(ind, 0) + 1
    picked.append((total, s, f, m))
    if len(picked) == TOP:
        break

head = ["Stock Picker (%d stocks scan)" % len(U)]
if missing:
    head.append("List nahi mili: " + ", ".join(missing))
head.append("Market: Nifty 200DMA ke " +
            ("upar (healthy)" if regime_ok else
             "NEECHE (weak): naye trade kam ya half size"))
lines = ["\n".join(head)]

if not picked:
    lines.append("Aaj koi stock sab filter pass nahi hua. Wait karo.")

for k, (total, s, f, m) in enumerate(picked, 1):
    t = U[s][0], T[s]
    tg, x = t
    a = x["atr"]
    stop = x["last"] - 2 * a
    target = x["last"] + 4 * a
    qty = int(RISK / (2 * a)) if a > 0 else 0
    ext = x["last"] / x["d50"] - 1
    status = ("Extended: pullback ka wait" if ext > 0.15 or x["rsi"] > 75
              else "Entry zone OK")
    pe = f"{f['pe']:.0f}" if f["pe"] else "NA"
    roe = f"{f['roe']*100:.0f}%" if f["roe"] else "NA"
    lines.append(
        f"{k}. {s} [{tg}] Score {total}/100\n"
        f"Q{f['q']} G{f['g']} V{f['v']} M{m} | PE {pe} | ROE {roe}\n"
        f"Price {x['last']:.0f} | 3M {x['r3']*100:+.0f}% | 6M {x['r6']*100:+.0f}%"
        f" | high se {(1-x['last']/x['hi'])*100:.0f}% neeche\n"
        f"{status} (RSI {x['rsi']:.0f})\n"
        f"Stop {stop:.0f} | Target {target:.0f} | Qty {qty} (risk Rs {RISK})")

lines.append("Sirf shortlist hai. Chart, news aur result date dekh ke hi lo.")
send("\n\n".join(lines))
