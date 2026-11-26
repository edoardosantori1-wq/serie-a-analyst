#!/usr/bin/env python3
"""Mercati statistici: calci d'angolo, tiri in porta, cartellini. Solo libreria standard.

Per ogni statistica lo stesso schema del modello dei gol: ogni squadra ha una forza "a favore" (quanti corner,
tiri in porta, cartellini produce) e "contro" (quanti ne concede/provoca all'avversario), stimate dalle partite
con peso maggiore alle recenti e il livello medio del campionato su peso rapido. Il conteggio di ogni squadra
segue una Binomiale Negativa (i corner sono piu' "dispersi" di una Poisson); la dispersione e' stimata sui dati.

Test onesto (walk-forward settimanale, stagioni passate): per ogni statistica si confronta la log loss
dell'Over/Under sulla linea principale con un riferimento "ingenuo" (solo media del campionato).
Il risultato del test e' scritto nel file e mostrato nel sito: se il modello non batte il riferimento, lo diciamo.

Quote di confronto: Pinnacle (corner totali). Per tiri in porta e cartellini non riceviamo quote: si mostra la
quota giusta del modello, da confrontare a mano con il bookmaker.
Dati: football-data.co.uk (HC/AC corner, HST/AST tiri in porta, HY/AY/HR/AR cartellini). L'arbitro non e' nei
dati: per i cartellini l'affidabilita' e' piu' bassa (dichiarato nel sito).
Scrive dati/statistiche.json.
"""
import csv, json, math, os, sys
from datetime import date, datetime, timedelta, timezone
import modello as MD

BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati")
STAT = {   # nome: (colonna casa, colonna ospite, linee O/U totali, linea del test, etichetta)
    "corner": (("HC",), ("AC",), [7.5, 8.5, 9.5, 10.5, 11.5], 9.5, "Calci d'angolo"),
    "tiri_porta": (("HST",), ("AST",), [6.5, 7.5, 8.5, 9.5, 10.5], 8.5, "Tiri in porta"),
    "cartellini": (("HY", "HR"), ("AY", "AR"), [2.5, 3.5, 4.5, 5.5, 6.5], 4.5, "Cartellini"),
}
GRID = [(0.003, 6.0), (0.008, 6.0), (0.015, 6.0)]
GRID_R = [5, 8, 12, 20, 40, 1000]   # dispersione Binomiale Negativa (1000 ~ Poisson)
XI_LIV = 0.02
MAXN = 40

def leggi(path, ch, ca):
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        try:
            d, m, y = r["Date"].split("/"); y = int(y) + (2000 if len(y) == 2 else 0)
            vh = sum(float(r[c]) for c in ch); va = sum(float(r[c]) for c in ca)
        except (KeyError, ValueError, TypeError): continue
        out.append(dict(date=date(y, int(m), int(d)), h=r["HomeTeam"], a=r["AwayTeam"], hg=vh, ag=va, hxg=None, axg=None))
    return out

def stagioni(nome, canon=None):
    ch, ca = STAT[nome][0], STAT[nome][1]; out = []
    files = sorted(f for f in os.listdir(D) if f.startswith("storico_") and f.endswith(".csv")) + ["fdcouk_corrente.csv"]
    for f in files:
        if not os.path.exists(os.path.join(D, f)): continue
        ms = leggi(os.path.join(D, f), ch, ca)
        if canon:
            for m in ms: m["h"], m["a"] = canon(m["h"]), canon(m["a"])
            ms = [m for m in ms if m["h"] and m["a"]]
        ms.sort(key=lambda m: m["date"])
        if ms: out.append((f[8:12] if f.startswith("storico_") else "corrente", ms))
    return out

def nb_pmf(mu, r):
    """Binomiale Negativa con media mu e dispersione r (varianza = mu + mu^2/r)."""
    mu = max(mu, 1e-6); p = r / (r + mu); out = [p ** r]
    for n in range(1, MAXN + 1): out.append(out[-1] * (n - 1 + r) / n * (1 - p))
    s = sum(out); return [x / s for x in out]

def totale(mh, ma, r):
    ph, pa = nb_pmf(mh, r), nb_pmf(ma, r); t = [0.0] * (2 * MAXN + 1)
    for i, x in enumerate(ph):
        for j, y in enumerate(pa): t[i + j] += x * y
    return t

def p_over(dist, linea): return sum(p for n, p in enumerate(dist) if n > linea)

def previsioni(seas, xi, k):
    """Walk-forward settimanale: medie attese casa/ospite per ogni partita, solo con dati precedenti."""
    rows, prima, teams_prev = [], [], set()
    for nome, ms in seas:
        teams = {m["h"] for m in ms} | {m["a"] for m in ms}
        prom = tuple(teams - teams_prev) if teams_prev else (); teams_prev = teams
        start = ms[0]["date"] + timedelta(days=28 if prima else 90); cache = {}
        for idx, m in enumerate(ms):
            if m["date"] < start: continue
            wk = m["date"].isocalendar()[:2]
            if wk not in cache:
                ref = m["date"] - timedelta(days=m["date"].weekday())
                hist = [x for x in prima + ms[:idx] if x["date"] < ref]
                par = MD.fit(hist, ref, xi=xi, k=k, alpha=0.0, promoted=prom, prom_prior=(1.0, 1.0), iters=25, xi_liv=XI_LIV)
                rec = [x for x in hist if (ref - x["date"]).days <= 120] or hist
                liv = sum(x["hg"] + x["ag"] for x in rec) / len(rec)
                cache[wk] = (par, liv)
            par, liv = cache[wk]
            mh, ma = MD.lambdas(par, m["h"], m["a"])
            rows.append(dict(s=nome, mh=mh, ma=ma, liv=liv, y=m["hg"] + m["ag"]))
        prima = prima + ms
    return rows

def ll(rows, r, linea, ingenuo=False):
    tot = 0.0
    for x in rows:
        if ingenuo: d = totale(x["liv"] / 2, x["liv"] / 2, r)
        else: d = totale(x["mh"], x["ma"], r)
        po = min(max(p_over(d, linea), 1e-6), 1 - 1e-6); y = x["y"] > linea
        tot -= math.log(po if y else 1 - po)
    return tot / max(len(rows), 1)

def taratura(nome, canon):
    seas = stagioni(nome, canon)
    linea = STAT[nome][3]; best = None
    for xi, k in GRID:
        rows = previsioni(seas, xi, k)
        tun = [x for x in rows if x["s"] != "corrente"]; ver = [x for x in rows if x["s"] == "corrente"]
        for r in GRID_R:
            v = ll(tun, r, linea)
            if best is None or v < best[0]: best = (v, xi, k, r, tun, ver)
    v, xi, k, r, tun, ver = best
    r_ing = min(GRID_R, key=lambda rr: ll(tun, rr, linea, True))
    calib = []
    for lo, hi in ((0, .4), (.4, .5), (.5, .6), (.6, 1.01)):
        sel = [(p_over(totale(x["mh"], x["ma"], r), linea), x["y"] > linea) for x in tun + ver]
        sel = [(p, y) for p, y in sel if lo <= p < hi]
        if sel: calib.append(dict(fascia=f"{int(lo*100)}-{min(int(hi*100),100)}%", partite=len(sel),
                                  prevista=round(sum(p for p, _ in sel) / len(sel), 3), reale=round(sum(y for _, y in sel) / len(sel), 3)))
    return dict(xi=xi, k=k, r=r, linea_test=linea,
                test=dict(partite=len(tun), logloss_modello=round(v, 4), logloss_ingenuo=round(ll(tun, r_ing, linea, True), 4)),
                verifica_stagione_corrente=dict(partite=len(ver), logloss_modello=round(ll(ver, r, linea), 4),
                                                logloss_ingenuo=round(ll(ver, r_ing, linea, True), 4)) if ver else None,
                calibrazione=calib)

def quote_pinnacle_corner(P):
    """{(casa, ospite): {linea: (quota over, quota under)}} dalle quote Pinnacle salvate (corner totali)."""
    out = {}
    for fx in (P.J("oddspapi_quote.json") or []):
        mk = ((fx.get("bookmakerOdds") or {}).get("pinnacle") or {}).get("markets") or {}
        key = (P.canon(fx.get("participant1Name")), P.canon(fx.get("participant2Name")))
        for mid, m in mk.items():
            info = P.MK.get(str(mid))
            if not info or info.get("marketType") != "totals-corners" or info.get("period") != "fulltime": continue
            q = {}
            for oid, o in (m.get("outcomes") or {}).items():
                pz = (o.get("players") or {}).get("0") or {}
                if pz.get("price") and pz.get("active", True): q[P.oname(str(mid), oid)] = pz["price"]
            if "Over" in q and "Under" in q: out.setdefault(key, {})[float(info["handicap"])] = (q["Over"], q["Under"])
    return out

def main():
    import predizioni as P
    tar_p = os.path.join(D, "statistiche_taratura.json")
    tar = None
    if os.path.exists(tar_p):
        tar = json.load(open(tar_p))
        if (datetime.now(timezone.utc) - datetime.fromisoformat(tar["generato"])).days >= 7 or "--taratura" in sys.argv: tar = None
    if tar is None:                                  # taratura settimanale (qualche minuto)
        tar = dict(generato=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   stat={n: taratura(n, P.canon) for n in STAT})
        json.dump(tar, open(tar_p, "w"), ensure_ascii=False, indent=1)
        for n, t in tar["stat"].items(): print("Taratura", n, json.dumps(t["test"]), json.dumps(t["verifica_stagione_corrente"]))
    now = datetime.now(timezone.utc)
    pro = [m for m in (P.J("fdorg_prossime.json") or {}).get("matches", []) if m.get("status") in ("SCHEDULED", "TIMED")]
    pro.sort(key=lambda m: m["utcDate"]); md = pro[0]["matchday"] if pro else None
    partite = [m for m in pro if m["matchday"] == md]
    pin = quote_pinnacle_corner(P)
    fits = {}
    for n in STAT:
        t = tar["stat"][n]; ms = [m for _, x in stagioni(n, P.canon) for m in x]
        fits[n] = MD.fit(ms, now.date(), xi=t["xi"], k=t["k"], alpha=0.0, promoted=P.PROMOSSE, prom_prior=(1.0, 1.0), xi_liv=XI_LIV)
    out = []
    for m in partite:
        h, a = P.canon(m["homeTeam"]["name"]), P.canon(m["awayTeam"]["name"])
        rec = dict(id=m["id"], inizio=m["utcDate"], casa=h, ospite=a, stat={})
        for n, (_, _, linee, _, et) in STAT.items():
            r = tar["stat"][n]["r"]; mh, ma = MD.lambdas(fits[n], h, a); dist = totale(mh, ma, r)
            righe = []
            for L in linee:
                po = p_over(dist, L)
                riga = dict(linea=L, p_over=round(po, 4), giusta_over=round(1 / po, 2) if po > 0.02 else None,
                            giusta_under=round(1 / (1 - po), 2) if po < 0.98 else None)
                pq = (pin.get((h, a)) or {}).get(L) if n == "corner" else None
                if pq:
                    io, iu = 1 / pq[0], 1 / pq[1]; pp = io / (io + iu)
                    riga.update(pin_over=pq[0], pin_under=pq[1], p_pin=round(pp, 4))
                righe.append(riga)
            rec["stat"][n] = dict(etichetta=et, casa=round(mh, 2), ospite=round(ma, 2), totale=round(mh + ma, 2), linee=righe)
        # suggerimento: la linea corner dove modello e Pinnacle sono piu' lontani (solo se il modello ha passato il test)
        out.append(rec)
    affid = {n: (t["test"]["logloss_modello"] < t["test"]["logloss_ingenuo"]) for n, t in tar["stat"].items()}
    res = dict(aggiornato=now.isoformat(timespec="seconds"), giornata=md, partite=out, affidabile=affid,
               test={n: dict(t["test"], verifica=t["verifica_stagione_corrente"], calibrazione=t["calibrazione"]) for n, t in tar["stat"].items()})
    json.dump(res, open(os.path.join(D, "statistiche.json"), "w"), ensure_ascii=False, indent=1)
    print(f"Statistiche: giornata {md}, {len(out)} partite; modello migliore del riferimento: {affid}")

if __name__ == "__main__":
    main()
