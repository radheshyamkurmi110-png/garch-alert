import os, io, time, requests, pandas as pd, yfinance as yf

BASE = ["https://niftyindices.com/IndexConstituent/",
        "https://www.niftyindices.com/IndexConstituent/"]
FILES = {"N50": "ind_nifty50list.csv",
         "NXT50": "ind_niftynext50list.csv",
         "MID150": "ind_niftymidcap150list.csv"}
HDR = {"User-Agent": "Mozilla/5.0"}

def load(fname):
    for b in BASE:
        try:
            r = requests.get(b + fname, headers=HDR, timeout=30)
            if r.ok and "Symbol" in r.text:
                return pd.read_csv(io.StringIO(r.text))
        except Exception:
            pass
    if os.path.exists(fname):          # repo me upload ki hui file
        return pd.read_csv(fname)
    return None

U = {}
missing = []
for tag, fn in FILES.items():
    df = load(fn)
    if df is None:
        missing.append(tag)
        continue
    for _, row in df.iterrows():
        U[str(row["Symbol"]).strip()] = (tag, str(row.get("Industry", "")))

def send(text):
    requests.post(
        f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TG_CHAT"], "text": text[:4000]})

if not U:
    send("Screener: NSE se stock list download nahi hui. "
         "CSV files repo me upload karni padengi.")
    raise SystemExit

tickers = [s + ".NS" for s in U]
px = yf.download(tickers, period="1y", group_by="ticker",
                 threads=True, progress=False)

def momentum(sym):
    try:
        c = px[sym + ".NS"]["Close"].dropna()
    except Exception:
        return None
    if len(c) < 200:
        return None
    last = float(c.iloc[-1])
    d50 = float(c.rolling(50).mean().iloc[-1])
    d200 = float(c.rolling(200).mean().iloc[-1])
    r3 = last / float(c.iloc[-63]) - 1
    near = last / float(c.max())
    ok = last > d50 > d200 and r3 > 0.05 and near > 0.85
    return dict(ok=ok, r3=r3, near=near)

def fundamentals(sym, industry):
    try:
        i = yf.Ticker(sym + ".NS").info
    except Exception:
        return None
    rules = [
        (i.get("returnOnEquity"), lambda v: v > 0.15),
        (i.get("trailingPE"), lambda v: 0 < v < 40),
        (i.get("revenueGrowth"), lambda v: v > 0.10),
        (i.get("earningsGrowth"), lambda v: v > 0.10),
        (i.get("profitMargins"), lambda v: v > 0.10),
    ]
    if "financial" not in industry.lower():
        rules.append((i.get("debtToEquity"), lambda v: v < 100))
        rules.append((i.get("currentRatio"), lambda v: v > 1))
    got = tot = 0
    for v, f in rules:
        if v is None:
            continue
        tot += 1
        got += 1 if f(v) else 0
    if tot < 4:
        return None
    return dict(got=got, tot=tot, pe=i.get("trailingPE"))

picks = []
for s, (tag, ind) in U.items():
    m = momentum(s)
    if not m or not m["ok"]:
        continue
    time.sleep(0.5)
    f = fundamentals(s, ind)
    if f and f["got"] / f["tot"] >= 0.7:
        picks.append((s, tag, ind, f, m))

picks.sort(key=lambda x: -x[4]["r3"])

lines = [f"Quality + Momentum ({len(U)} stocks scan)"]
if missing:
    lines.append("List nahi mili: " + ", ".join(missing))
if not picks:
    lines.append("Koi stock dono filter pass nahi hua.")
for s, tag, ind, f, m in picks[:15]:
    pe = f"{f['pe']:.0f}" if f["pe"] else "NA"
    lines.append(f"{s} [{tag}] {f['got']}/{f['tot']} | 3M {m['r3']*100:+.0f}% | "
                 f"high se {(1-m['near'])*100:.0f}% neeche | PE {pe}")
lines.append(f"Total pass: {len(picks)}. Sirf screening hai, khareedne se pehle khud research karo.")
send("\n".join(lines))
