#!/usr/bin/env python3
"""Taratura automatica del modello "AI" (solo dati) - eseguita da orchestra.py all'uscita del report.

Il modello stima la forza di attacco e difesa di ogni squadra dai dati delle partite: gol, xG ufficiali
(stagione in corso) o xG stimati dai tiri (stagioni passate), con le partite recenti che pesano di piu'
(il "momento" della squadra). Qui si sceglie, in modo automatico e con un test onesto:
  - quanto velocemente "dimenticare" il passato (xi), quanto pesare xG rispetto ai gol (alpha);
  - quanto fidarsi del modello rispetto al mercato, separatamente per 1X2 e per i gol.
Test walk-forward: ogni settimana il modello e' stimato SOLO con le partite precedenti e confrontato con
le quote medie di chiusura (football-data.co.uk). Parametri scelti sulle stagioni passate, poi verificati
sulla stagione in corso, che il modello non ha mai usato per la scelta.
Scrive dati/taratura.json. Solo libreria standard.
"""
import json, math, os, itertools
from datetime import datetime, timezone, timedelta
import modello as MD

BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati")
GRID_XI = [0.002, 0.005, 0.01, 0.02]
GRID_ALPHA = [0.0, 0.5, 0.8, 1.0]
GRID_K = [4.0, 8.0]
GRID_W = [0.0, 0.25, 0.5, 0.75]   # max 75%: infortuni e formazioni li conosce solo il mercato
RHO = -0.08
XI_LIV = 0.02   # livello gol del campionato su peso rapido (emivita ~35 giorni): corregge il cambio di ritmo 2026/27

def stagioni():
    """[(nome, partite)] in ordine cronologico: storico_YYZZ.csv + fdcouk_corrente.csv (stagione in corso)."""
    out = []
    for f in sorted(os.listdir(D)):
        if f.startswith("storico_") and f.endswith(".csv"):
            out.append((f[8:12], MD.leggi_csv(os.path.join(D, f))))
    cur = os.path.join(D, "fdcouk_corrente.csv")
    if os.path.exists(cur):
        out.append(("corrente", MD.leggi_csv(cur)))
    return [(n, ms) for n, ms in out if ms]

def previsioni(seas, xi, k, alpha, xi_liv=0.0):
    """Walk-forward settimanale. Ritorna righe con prob. modello e mercato per 1X2 e Over 2.5."""
    rows, prima = [], []
    teams_prev = set()
    for i, (nome, ms) in enumerate(seas):
        teams = {m["h"] for m in ms} | {m["a"] for m in ms}
        prom = tuple(teams - teams_prev) if teams_prev else ()
        teams_prev = teams
        start = ms[0]["date"] + timedelta(days=28 if prima else 90)   # prima stagione: serve un po' di storia
        cache = {}
        for idx, m in enumerate(ms):
            if m["date"] < start or not m["oH"]:
                continue
            wk = m["date"].isocalendar()[:2]
            if wk not in cache:
                ref = m["date"] - timedelta(days=m["date"].weekday())
                hist = [x for x in prima + ms[:idx] if x["date"] < ref]
                cache[wk] = MD.fit(hist, ref, xi=xi, k=k, alpha=alpha, promoted=prom, iters=30, xi_liv=xi_liv)
            lh, la = MD.lambdas(cache[wk], m["h"], m["a"])
            mk, _ = MD.mercati(MD.matrice(lh, la, RHO))
            pk = MD.no_vig([m["oH"], m["oD"], m["oA"]])
            po = MD.no_vig([m["oO"], m["oU"]])[0] if m["oO"] and m["oU"] else None
            rows.append(dict(s=nome, m=m, pm=[mk["1"], mk["X"], mk["2"]], pk=pk, pmo=mk["O2.5"], pko=po,
                             y=0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2),
                             yo=int(m["hg"] + m["ag"] > 2)))
        prima = prima + ms
    return rows

def ll1x2(rows, w):
    return sum(-math.log(max(w*r["pm"][r["y"]] + (1-w)*r["pk"][r["y"]], 1e-9)) for r in rows) / max(len(rows), 1)

def llou(rows, w):
    rr = [r for r in rows if r["pko"] is not None]
    f = lambda r: w*r["pmo"] + (1-w)*r["pko"]
    return sum(-(r["yo"]*math.log(f(r)) + (1-r["yo"])*math.log(1-f(r))) for r in rr) / max(len(rr), 1)

def roi(rows, w1, wg, soglia=0.05):
    """Giocate virtuali dove la prob. finale supera la quota B365 prepartita di almeno il 5% di EV."""
    out = {"1x2": [0, 0.0], "gol": [0, 0.0]}
    for r in rows:
        m = r["m"]; p = [w1*a + (1-w1)*b for a, b in zip(r["pm"], r["pk"])]
        for i, o in enumerate((m.get("bH"), m.get("bD"), m.get("bA"))):
            if o and w1 > 0 and p[i]*o - 1 >= soglia:
                out["1x2"][0] += 1; out["1x2"][1] += (o-1) if r["y"] == i else -1
        if r["pko"] is not None and wg > 0:
            q = wg*r["pmo"] + (1-wg)*r["pko"]
            for pp, o, y in ((q, m.get("bO"), r["yo"]), (1-q, m.get("bU"), 1-r["yo"])):
                if o and pp*o - 1 >= soglia:
                    out["gol"][0] += 1; out["gol"][1] += (o-1) if y else -1
    return {k: dict(giocate=n, roi=round(v/n, 4) if n else None) for k, (n, v) in out.items()}

def main():
    seas = stagioni()
    if len(seas) < 2:
        print("Taratura: servono almeno 2 stagioni di dati"); return
    corrente = seas[-1][0]
    ris = []
    for xi, k, alpha in itertools.product(GRID_XI, GRID_K, GRID_ALPHA):
        rows = previsioni(seas, xi, k, alpha, XI_LIV)
        tun = [r for r in rows if r["s"] != corrente]; ver = [r for r in rows if r["s"] == corrente]
        if len(tun) < 100: tun = rows          # poche stagioni: si usa tutto (segnalato nel report)
        ris.append(dict(xi=xi, k=k, alpha=alpha, rows=rows, tun=tun, ver=ver,
                        ll1=ll1x2(tun, 1.0), llg=llou(tun, 1.0)))
    b1 = min(ris, key=lambda r: r["ll1"]); bg = min(ris, key=lambda r: r["llg"])
    w1 = min(GRID_W, key=lambda w: ll1x2(b1["tun"], w)); wg = min(GRID_W, key=lambda w: llou(bg["tun"], w))
    def blocco(rows1, rowsg):
        return dict(partite=len(rows1),
                    logloss_1x2=dict(modello=round(ll1x2(rows1, 1), 4), mercato=round(ll1x2(rows1, 0), 4), finale=round(ll1x2(rows1, w1), 4)),
                    logloss_gol=dict(modello=round(llou(rowsg, 1), 4), mercato=round(llou(rowsg, 0), 4), finale=round(llou(rowsg, wg), 4)))
    # ROI: le righe 1X2 e gol vengono da due configurazioni diverse; si uniscono per partita
    def unisci(r1, rg):
        idx = {(r["m"]["date"], r["m"]["h"]): r for r in rg}
        return [dict(r, pmo=idx[(r["m"]["date"], r["m"]["h"])]["pmo"]) for r in r1 if (r["m"]["date"], r["m"]["h"]) in idx]
    out = dict(
        generato=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        stagioni=[n for n, _ in seas],
        par_1x2=dict(xi=b1["xi"], k=b1["k"], alpha=b1["alpha"], xi_liv=XI_LIV),
        par_gol=dict(xi=bg["xi"], k=bg["k"], alpha=bg["alpha"], xi_liv=XI_LIV),
        w_1x2=w1, w_gol=wg,
        taratura=blocco(b1["tun"], bg["tun"]),
        verifica_stagione_corrente=blocco(b1["ver"], bg["ver"]) if b1["ver"] else None,
        roi_verifica=roi(unisci(b1["ver"], bg["ver"]), w1, wg) if b1["ver"] else None,
        nota="Parametri scelti sulle stagioni passate; la stagione in corso e' usata solo come verifica." if b1["tun"] is not b1["rows"]
             else "Poche stagioni disponibili: scelta e verifica sugli stessi dati (risultato ottimistico).")
    json.dump(out, open(os.path.join(D, "taratura.json"), "w"), ensure_ascii=False, indent=1)
    print("Taratura:", json.dumps({k: out[k] for k in ("par_1x2", "par_gol", "w_1x2", "w_gol")}))
    print("Verifica stagione in corso:", json.dumps(out["verifica_stagione_corrente"]), json.dumps(out["roi_verifica"]))

if __name__ == "__main__":
    main()
