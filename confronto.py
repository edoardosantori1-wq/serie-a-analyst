#!/usr/bin/env python3
"""Check interno: l'AI contro Pinnacle (il bookmaker con le quote piu' precise). Non va sul sito.
Per ogni partita giocata confronta le probabilita' date all'uscita del report (1, X, 2, Over 2.5, Goal)
con il risultato: log loss e Brier (piu' bassi = piu' precisi). Scrive dati/confronto_interno.json."""
import json, math, os, sqlite3
from datetime import datetime, timezone
BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati")
def J(n):
    try: return json.load(open(os.path.join(D, n)))
    except Exception: return None
ris = {m["id"]: (m["score"]["fullTime"]["home"], m["score"]["fullTime"]["away"])
       for m in (J("fdorg_giocate.json") or {}).get("matches", []) if m.get("score", {}).get("fullTime", {}).get("home") is not None}
db = sqlite3.connect(os.path.join(D, "storico.sqlite"))
try: righe = db.execute("SELECT match_id, partita, mercato, p_ai, p_pin FROM confronto").fetchall()
except sqlite3.Error: righe = []
db.close()
def esito(k, i, j):
    return {"1": i > j, "X": i == j, "2": i < j, "O2.5": i + j > 2, "GG": i > 0 and j > 0}[k]
fam = {"1x2": ("1", "X", "2"), "gol": ("O2.5", "GG")}
out = {}
for nome, ks in fam.items():
    ll = {"ai": 0.0, "pinnacle": 0.0}; br = {"ai": 0.0, "pinnacle": 0.0}; n = 0
    for mid, partita, k, pa, pp in righe:
        if k not in ks or mid not in ris: continue
        y = esito(k, *ris[mid]); n += 1
        for chi, p in (("ai", pa), ("pinnacle", pp)):
            p = min(max(p, 1e-6), 1 - 1e-6)
            ll[chi] -= math.log(p if y else 1 - p); br[chi] += (p - y) ** 2
    out[nome] = dict(previsioni=n, logloss={c: round(v / n, 4) for c, v in ll.items()} if n else None,
                     brier={c: round(v / n, 4) for c, v in br.items()} if n else None,
                     piu_precisa=(("AI" if ll["ai"] < ll["pinnacle"] else "Pinnacle") if n else None))
out["partite"] = len({r[0] for r in righe if r[0] in ris})
out["aggiornato"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
json.dump(out, open(os.path.join(D, "confronto_interno.json"), "w"), ensure_ascii=False, indent=1)
print("Confronto interno AI vs Pinnacle:", json.dumps(out))
