import os, io, json, time, requests, numpy as np, pandas as pd, yfinance as yf

BASE = ["https://niftyindices.com/IndexConstituent/",
        "https://www.niftyindices.com/IndexConstituent/",
        "https://nsearchives.nseindia.com/content/indices/",
        "https://archives.nseindia.com/content/indices/"]
FNAME = "ind_nifty500list.csv"
STATE = "momentum_holdings.json"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 Chrome/120 Safari/537.36",
       "Accept": "text/csv,*/*"}
N = 50              # kitne stocks
EXIT_RANK = 75      # rank isse neeche jaye tab hi nikalo
MIN_VALUE = 5e7     # roz ki trading min Rs 5 crore
CAPITAL = 100000    # total paisa (Rs), apne hisaab se badlo

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
    send("Momentum 50: Nifty 500 ki list nahi mili. "
         "ind_nifty500list.csv repo me upload karo.")
    raise SystemExit
syms = [str(s).strip() for s in df["Symbol"]]

px = yf.download([s + ".NS" for s in syms] + ["^NSEI"], period="2y",
                 threads=True, progress=False)
close, volu = px["Close"], px["Volume"]

nc = close["^NSEI"].dropna()
regime = "upar (healthy)" if nc.iloc[-1] > nc.rolling(200).mean().iloc[-1] \
    else "NEECHE (weak)"

close = close.drop(columns=["^NSEI"]).dropna(axis=1, how="all")
volu = volu[close.columns]

last = close.iloc[-1]
r6 = last / close.iloc[-127] - 1
r12 = last / close.iloc[-253] - 1
vol = close.pct_change().tail(252).std() * np.sqrt(252)
s6, s12 = r6 / vol, r12 / vol
z = 0.5 * (s6 - s6.mean()) / s6.std() + 0.5 * (s12 - s12.mean()) / s12.std()
score = z.where(z < 0, 1 + z)
score = score.where(z >= 0, 1 / (1 - z))

enough = close.iloc[-253:].notna().sum() >= 250
liquid = (close * volu).tail(20).mean() >= MIN_VALUE
ok = (enough & liquid & score.notna())
ranked = score[ok].sort_values(ascending=False)
rank = {c.replace(".NS", ""): i + 1 for i, c in enumerate(ranked.index)}

prev = json.load(open(STATE)) if os.path.exists(STATE) else []
keep = [s for s in prev if s in rank and rank[s] <= EXIT_RANK]
for c in ranked.index:
    s = c.replace(".NS", "")
    if len(keep) >= N:
        break
    if s not in keep:
        keep.append(s)
new = sorted(keep, key=lambda s: rank[s])
ins = [s for s in new if s not in prev]
outs = [s for s in prev if s not in new]
json.dump(new, open(STATE, "w"))

def f(s):
    c = s + ".NS"
    return f"6M {r6[c]*100:+.0f}% | 12M {r12[c]*100:+.0f}%"

out = [f"Momentum 50 (Nifty 500 se, {len(ranked)} stocks scan)\n"
       f"Nifty 200DMA ke {regime}\n"
       f"Har stock me lagbhag Rs {CAPITAL/N:,.0f} ({100/N:.0f}%)"]

if not prev:
    out.append("Pehli baar: neeche poori list hai, sab IN maano.")
else:
    out.append("IN (naye): " + (", ".join(ins) if ins else "koi nahi"))
    out.append("OUT (nikle): " + (", ".join(outs) if outs else "koi nahi"))

out.append("PORTFOLIO (rank ke hisaab se)\n" +
           "\n".join(f"{i+1}. {s} (rank {rank[s]}) {f(s)}"
                     for i, s in enumerate(new)))
out.append("Asli fund March aur September me badalta hai. "
           "Beech ke mahine ka message sirf preview hai.\n"
           "Momentum tez palat sakta hai (market girne par). "
           "Sirf educational jaankari, financial advice nahi.")
send("\n\n".join(out))
