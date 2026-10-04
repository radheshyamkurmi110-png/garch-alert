import os, io, time, datetime as dt, requests, pandas as pd, yfinance as yf

BASE = ["https://niftyindices.com/IndexConstituent/",
        "https://www.niftyindices.com/IndexConstituent/",
        "https://nsearchives.nseindia.com/content/indices/",
        "https://archives.nseindia.com/content/indices/"]
FNAME = "ind_nifty50list.csv"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 Chrome/120 Safari/537.36",
       "Accept": "text/csv,*/*"}
MIN_DD, MAX_DD = 0.15, 0.50   # 52-week high se girawat ki range

def send(text):
    parts, cur = [], ""
    for blk in text.split("\n\n"):
        if len(cur) + len(blk) > 3500:
            parts.append(cur)
            cur = ""
        cur += blk + "\n\n"
    parts.append(cur)
    for p in parts:
        if p.strip():
            requests.post(
                f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
                data={"chat_id": os.environ["TG_CHAT"], "text": p.strip()})

def load():
    for _ in range(2):
        for b in BASE:
            try:
                r = requests.get(b + FNAME, headers=HDR, timeout=30)
                if r.ok and "Symbol" in r.text:
                    return pd.read_csv(io.StringIO(r.text))
            except Exception:
                pass
        time.sleep(3)
    if os.path.exists(FNAME):
        return pd.read_csv(FNAME)
    return None

df = load()
if df is None:
    send("Fallen Quality: Nifty 50 ki list nahi mili. "
         "ind_nifty50list.csv repo me upload karo.")
    raise SystemExit
U = {str(r["Symbol"]).strip(): str(r.get("Industry", ""))
     for _, r in df.iterrows()}

px = yf.download([s + ".NS" for s in U] + ["^NSEI"], period="5y",
                 group_by="ticker", threads=True, progress=False)

nc = px["^NSEI"]["Close"].dropna()
n_last = float(nc.iloc[-1])
n6 = n_last / float(nc.iloc[-126]) - 1
n12 = n_last / float(nc.iloc[-252]) - 1
regime = "upar (healthy)" if n_last > float(nc.rolling(200).mean().iloc[-1]) \
    else "NEECHE (weak)"

def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]))

def tech(sym):
    try:
        c = px[sym + ".NS"]["Close"].dropna()
    except Exception:
        return None
    if len(c) < 300:
        return None
    last = float(c.iloc[-1])
    hi = float(c.tail(252).max())
    return dict(
        last=last, dd=1 - last / hi,
        r6=last / float(c.iloc[-126]) - 1,
        r12=last / float(c.iloc[-252]) - 1,
        d20=float(c.rolling(20).mean().iloc[-1]),
        d50=float(c.rolling(50).mean().iloc[-1]),
        rsi=rsi(c),
        hl=float(c.tail(30).min()) > float(c.iloc[-90:-30].min()))

def hist(sym):
    try:
        f = yf.Ticker(sym + ".NS").financials
        rev = f.loc["Total Revenue"].dropna()
        ni = f.loc["Net Income"].dropna()
        return (len(rev) >= 3 and rev.iloc[0] > rev.iloc[-1],
                len(ni) >= 3 and bool((ni > 0).all()))
    except Exception:
        return (False, False)

def info(sym):
    try:
        return yf.Ticker(sym + ".NS").info
    except Exception:
        return None

rows, gated = [], 0
for s, ind in U.items():
    t = tech(s)
    if not t or not (MIN_DD <= t["dd"] <= MAX_DD):
        continue
    rel = ((t["r6"] - n6) + (t["r12"] - n12)) / 2
    if rel >= 0:
        continue
    gated += 1
    time.sleep(0.5)
    i = info(s)
    if not i:
        continue
    roe, mar = i.get("returnOnEquity"), i.get("profitMargins")
    de, pe, fpe = i.get("debtToEquity"), i.get("trailingPE"), i.get("forwardPE")
    eqg, rg = i.get("earningsQuarterlyGrowth"), i.get("revenueGrowth")
    fin = "financial" in ind.lower()
    ok_rev, ok_ni = hist(s)

    q = 0
    q += 10 if roe and roe > 0.12 else 0
    q += 10 if mar and mar > 0 else 0
    q += 10 if fin or (de is not None and de < 100) else 0
    q += 10 if (ok_rev and ok_ni) else 5 if (ok_rev or ok_ni) else 0

    v = 0
    if pe and pe > 0:
        v = 20 if pe < 20 else 14 if pe < 30 else 7 if pe < 45 else 0
        if fpe and 0 < fpe < pe:
            v = min(20, v + 4)

    b = 10 if t["hl"] else 0
    b += 8 if t["last"] > t["d20"] else 0
    b += 7 if 40 <= t["rsi"] <= 65 else 0

    g = 8 if eqg and eqg > 0 else 0
    g += 7 if rg and rg > 0 else 0

    total = q + v + b + g
    if q >= 20 and total >= 50:
        rows.append(dict(s=s, t=t, q=q, v=v, b=b, g=g, total=total,
                         pe=pe, roe=roe))

bott = sorted([r for r in rows if r["b"] >= 15], key=lambda r: -r["total"])
fall = sorted([r for r in rows if r["b"] < 15], key=lambda r: -r["total"])
rev_date = (dt.date.today() + dt.timedelta(days=90)).strftime("%d %b %Y")

def card(r, plan):
    t = r["t"]
    pe = f"{r['pe']:.0f}" if r["pe"] else "NA"
    roe = f"{r['roe']*100:.0f}%" if r["roe"] else "NA"
    return (f"{r['s']} Score {r['total']}/100 "
            f"(Q{r['q']} V{r['v']} B{r['b']} G{r['g']})\n"
            f"Price {t['last']:.0f} | high se {t['dd']*100:.0f}% neeche | "
            f"6M {t['r6']*100:+.0f}% (Nifty {n6*100:+.0f}%)\n"
            f"PE {pe} | ROE {roe} | RSI {t['rsi']:.0f}\n{plan}")

out = [f"Fallen Quality Finder (Nifty 50)\n"
       f"Nifty 200DMA ke {regime}\n"
       f"Gira + Nifty se kamzor: {gated} stocks, shortlist: {len(rows)}"]

out.append("BOTTOMING (khareedne ke liye dekho)")
if not bott:
    out.append("Abhi koi nahi.")
for r in bott[:5]:
    t = r["t"]
    out.append(card(r,
        f"Plan: 1/3 abhi ~{t['last']:.0f}, 1/3 {t['last']*0.90:.0f} par, "
        f"1/3 jab 50DMA ({t['d50']:.0f}) ke upar close ho\n"
        f"Review: {rev_date} ya 52w low toote tab"))

out.append("STILL FALLING (abhi wait)")
if not fall:
    out.append("Koi nahi.")
for r in fall[:5]:
    out.append(card(r,
        f"Wait: pehla buy tab jab 20DMA ({r['t']['d20']:.0f}) ke upar close ho"))

out.append("Kharidne se pehle har pick par ye 4 sawal:\n"
           "1. Growth kyun ruki? Temporary ya permanent?\n"
           "2. Promoter holding aur management stable hai?\n"
           "3. Debt badh to nahi raha?\n"
           "4. Agle 2-3 saal me growth wapas aane ka kaaran kya hai?\n"
           "Sirf shortlist hai. screener.in par 5-10 saal ke numbers verify karo.")
send("\n\n".join(out))
