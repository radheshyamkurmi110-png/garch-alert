import os, io, json, time, datetime as dt, requests
import numpy as np, pandas as pd, yfinance as yf

BASE = ["https://niftyindices.com/IndexConstituent/",
        "https://www.niftyindices.com/IndexConstituent/",
        "https://nsearchives.nseindia.com/content/indices/",
        "https://archives.nseindia.com/content/indices/"]
FILES = {"L1": "ind_nifty50list.csv",
         "L2": "ind_niftynext50list.csv",
         "M": "ind_niftymidcap150list.csv"}
STATE = "blend_holdings.json"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 Chrome/120 Safari/537.36",
       "Accept": "text/csv,*/*"}

N_L, N_M = 35, 15
EXIT_L, EXIT_M = 55, 35
MIN_L, MIN_M = 5e8, 2e8
T_L, T_M = 0.75, 0.25
CAP_L, CAP_M = 0.05, 0.03
MAX_SECTOR = 8
CAPITAL = 100000                       # apna total paisa (Rs)
TARGET, STOP, MAXDAYS = 0.15, 0.08, 60

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

def load(fname):
    for _ in range(2):
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

dfs, missing = {}, []
for k, fn in FILES.items():
    d = load(fn)
    if d is None:
        missing.append(fn)
    else:
        dfs[k] = d
if missing:
    send("Blend: list nahi mili: " + ", ".join(missing) +
         ". Ye CSV files repo me upload karo.")
    raise SystemExit

ind, large, mid = {}, set(), set()
for k in ("L1", "L2"):
    for _, r in dfs[k].iterrows():
        s = str(r["Symbol"]).strip()
        large.add(s)
        ind[s] = str(r.get("Industry", ""))
for _, r in dfs["M"].iterrows():
    s = str(r["Symbol"]).strip()
    if s not in large:
        mid.add(s)
        ind[s] = str(r.get("Industry", ""))

allsyms = sorted(large | mid)
px = yf.download([s + ".NS" for s in allsyms] + ["^NSEI"], period="2y",
                 threads=True, progress=False)
close, volu = px["Close"], px["Volume"]

nc = close["^NSEI"].dropna()
regime = "upar (healthy)" if nc.iloc[-1] > nc.rolling(200).mean().iloc[-1] \
    else "NEECHE (weak): kam stocks ya half size"
close = close.drop(columns=["^NSEI"]).dropna(axis=1, how="all")
volu = volu[close.columns]

last = close.iloc[-1]
r3 = last / close.iloc[-64] - 1
r6 = last / close.iloc[-127] - 1
vol = close.pct_change().tail(252).std() * np.sqrt(252)
s3, s6 = r3 / vol, r6 / vol
z = 0.5 * (s3 - s3.mean()) / s3.std() + 0.5 * (s6 - s6.mean()) / s6.std()
score = pd.Series(np.where(z >= 0, 1 + z, 1 / (1 - z)), index=z.index)

sma50 = close.rolling(50).mean().iloc[-1]
sma200 = close.rolling(200).mean().iloc[-1]
enough = close.iloc[-210:].notna().sum() >= 200
trend = (last > sma200) & (last > sma50) & (last / sma50 < 1.20)
val = (close * volu).tail(20).mean()
base_ok = enough & trend & score.notna()

# ---- purani holdings, entry aur exit alerts ----
prev = json.load(open(STATE)) if os.path.exists(STATE) else {}
pl, pm = prev.get("L", []), prev.get("M", [])
ent = prev.get("entry", {})
cool = set(prev.get("cool", []))
today = dt.date.today()
exited, alerts = set(), []
for s, e in ent.items():
    c = s + ".NS"
    if c not in last.index or pd.isna(last[c]):
        continue
    pnl = float(last[c]) / e["p"] - 1
    days = (today - dt.date.fromisoformat(e["d"])).days
    if pnl >= TARGET:
        why = "TARGET hit: profit book karo"
    elif pnl <= -STOP:
        why = "STOP hit: nikal jao"
    elif days >= MAXDAYS:
        why = "time ho gaya: review ya nikalo"
    else:
        continue
    exited.add(s)
    alerts.append(f"{s}: {pnl*100:+.0f}% ({days} din) {why}")
skip = exited | cool

def cands(bucket, minval):
    cols = [c for c in close.columns
            if c.replace(".NS", "") in bucket and base_ok[c] and val[c] >= minval]
    return score[cols].sort_values(ascending=False)

secn = {}
def pick(ranked, n, exit_rank, prevlist):
    rk = {c.replace(".NS", ""): i + 1 for i, c in enumerate(ranked.index)}
    keep = [s for s in prevlist
            if s in rk and rk[s] <= exit_rank and s not in exited][:n]
    for s in keep:
        secn[ind[s]] = secn.get(ind[s], 0) + 1
    for c in ranked.index:
        if len(keep) >= n:
            break
        s = c.replace(".NS", "")
        if s in keep or s in skip or secn.get(ind[s], 0) >= MAX_SECTOR:
            continue
        keep.append(s)
        secn[ind[s]] = secn.get(ind[s], 0) + 1
    return keep, rk

selL, rkL = pick(cands(large, MIN_L), N_L, EXIT_L, pl)
selM, rkM = pick(cands(mid, MIN_M), N_M, EXIT_M, pm)
sel = selL + selM

for s in sel:
    if s not in ent:
        ent[s] = {"p": float(last[s + ".NS"]), "d": today.isoformat()}
for s in list(ent):
    if s not in sel:
        del ent[s]
json.dump({"L": selL, "M": selM, "entry": ent, "cool": sorted(exited)},
          open(STATE, "w"))

def mcap(s):
    try:
        return float(yf.Ticker(s + ".NS").fast_info["market_cap"])
    except Exception:
        return 1e10

def alloc(sl, target, cap):
    raw = {}
    for s in sl:
        time.sleep(0.3)
        raw[s] = mcap(s) * max(float(score[s + ".NS"]), 0.01)
    tot = sum(raw.values()) or 1
    w = {s: target * v / tot for s, v in raw.items()}
    for _ in range(20):
        over = [s for s, v in w.items() if v > cap + 1e-9]
        if not over:
            break
        rest = {s: v for s, v in w.items() if s not in over}
        free = target - cap * len(over)
        rt = sum(rest.values()) or 1
        w = {**{s: cap for s in over},
             **{s: free * v / rt for s, v in rest.items()}}
    return w

wL, wM = alloc(selL, T_L, CAP_L), alloc(selM, T_M, CAP_M)

def line(s, w, rk):
    c = s + ".NS"
    t = ""
    if s in ent:
        d = (today - dt.date.fromisoformat(ent[s]["d"])).days
        t = f" | P&L {(float(last[c]) / ent[s]['p'] - 1) * 100:+.0f}% ({d}d)"
    return (f"{s} {w[s]*100:.1f}% = Rs {CAPITAL*w[s]:,.0f} (rank {rk[s]}) "
            f"3M {r3[c]*100:+.0f}% 6M {r6[c]*100:+.0f}%{t}")

out = [f"Large+Mid Momentum, 1-2 mahine hold\n"
       f"Nifty 200DMA ke {regime}\n"
       f"Target +{TARGET*100:.0f}% | Stop -{STOP*100:.0f}% | Max {MAXDAYS} din"]
if alerts:
    out.append("EXIT ALERTS\n" + "\n".join(alerts))
if not prev:
    out.append("Pehli baar: neeche poori list hai, sab IN maano.")
else:
    inn = [s for s in sel if s not in pl + pm]
    outs = [s for s in pl + pm if s not in sel and s not in exited]
    out.append("IN (naye): " + (", ".join(inn) if inn else "koi nahi") +
               "\nOUT (rank gira): " + (", ".join(outs) if outs else "koi nahi"))
out.append(f"LARGE CAP ({sum(wL.values())*100:.0f}%)\n" + "\n".join(
    f"{i+1}. {line(s, wL, rkL)}"
    for i, s in enumerate(sorted(selL, key=lambda x: -wL[x]))))
out.append(f"MID CAP ({sum(wM.values())*100:.0f}%)\n" + "\n".join(
    f"{i+1}. {line(s, wM, rkM)}"
    for i, s in enumerate(sorted(selM, key=lambda x: -wM[x]))))
out.append("Entry price bot ka apna hai (jis din list aayi). "
           "Aapka asli price alag ho to apna P&L khud dekho. "
           "Sirf educational jaankari, financial advice nahi.")
send("\n\n".join(out))
