#!/usr/bin/env python3
"""Motore statistico Serie A Analyst - solo libreria standard.

Modello: Poisson indipendente a forza d'attacco/difesa (Maher) con correzione Dixon-Coles
per i punteggi bassi, pesi temporali esponenziali, segnale offensivo = mix di gol ed xG
(quando disponibili), shrinkage verso la media (pseudo-partite) e prior per le neopromosse.
Le probabilita' finali sono una media pesata tra modello e mercato (probabilita' senza margine):
il peso e' scelto dal backtest per minimizzare la log loss.
"""
import csv, math, os
from datetime import date

MAXG = 10

def leggi_csv(path):
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if not r.get("FTHG"):
            continue
        d, m, y = r["Date"].split("/")
        y = int(y) + (2000 if len(y) == 2 else 0)
        f = lambda k: float(r[k]) if r.get(k) not in (None, "") else None
        out.append(dict(date=date(y, int(m), int(d)), h=r["HomeTeam"], a=r["AwayTeam"],
                        hg=int(r["FTHG"]), ag=int(r["FTAG"]), hxg=f("HxG"), axg=f("AxG"),
                        oH=f("AvgCH"), oD=f("AvgCD"), oA=f("AvgCA"), oO=f("AvgC>2.5"), oU=f("AvgC<2.5")))
    out.sort(key=lambda r: r["date"])
    return out

def fit(matches, ref_date, xi=0.004, k=4.0, alpha=0.6, promoted=(), prom_prior=(0.80, 1.20), iters=60):
    """Restituisce (mu, home, att, dif). matches: lista con date < ref_date."""
    teams = sorted({m["h"] for m in matches} | {m["a"] for m in matches} | set(promoted))
    prior = {t: (prom_prior if t in promoted else (1.0, 1.0)) for t in teams}
    att = {t: prior[t][0] for t in teams}; dif = {t: prior[t][1] for t in teams}
    W = []
    for m in matches:
        w = math.exp(-xi * (ref_date - m["date"]).days)
        sh = m["hg"] if m["hxg"] is None else alpha * m["hxg"] + (1 - alpha) * m["hg"]
        sa = m["ag"] if m["axg"] is None else alpha * m["axg"] + (1 - alpha) * m["ag"]
        W.append((w, m["h"], m["a"], sh, sa))
    sw = sum(w for w, *_ in W) or 1
    mu = sum(w * (sh + sa) for w, _, _, sh, sa in W) / (2 * sw)
    home = 1.1
    for _ in range(iters):
        num = {t: k * prior[t][0] for t in teams}; den = {t: k for t in teams}
        for w, h, a, sh, sa in W:
            num[h] += w * sh; den[h] += w * mu * home * dif[a]
            num[a] += w * sa; den[a] += w * mu * dif[h]
        att = {t: num[t] / den[t] for t in teams}
        num = {t: k * prior[t][1] for t in teams}; den = {t: k for t in teams}
        for w, h, a, sh, sa in W:
            num[a] += w * sh; den[a] += w * mu * home * att[h]
            num[h] += w * sa; den[h] += w * mu * att[a]
        dif = {t: num[t] / den[t] for t in teams}
        g = math.exp(sum(math.log(att[t]) for t in teams) / len(teams))
        att = {t: v / g for t, v in att.items()}; dif = {t: v * g for t, v in dif.items()}
        hn = sum(w * sh for w, h, a, sh, sa in W); hd = sum(w * mu * att[h] * dif[a] for w, h, a, sh, sa in W)
        home = hn / hd if hd else 1.1
        an = sum(w * sa for w, h, a, sh, sa in W); ad = sum(w * att[a] * dif[h] for w, h, a, sh, sa in W)
        mu = an / ad if ad else mu
    return dict(mu=mu, home=home, att=att, dif=dif)

def lambdas(par, h, a):
    att, dif = par["att"], par["dif"]
    lh = par["mu"] * par["home"] * att.get(h, 0.85) * dif.get(a, 1.15)
    la = par["mu"] * att.get(a, 0.85) * dif.get(h, 1.15)
    return lh, la

def pois(l, n): return math.exp(-l) * l ** n / math.factorial(n)

def matrice(lh, la, rho=-0.08):
    M = [[pois(lh, i) * pois(la, j) for j in range(MAXG + 1)] for i in range(MAXG + 1)]
    M[0][0] *= max(1 - lh * la * rho, 0); M[0][1] *= 1 + lh * rho
    M[1][0] *= 1 + la * rho; M[1][1] *= 1 - rho
    s = sum(map(sum, M)); return [[v / s for v in row] for row in M]

def mercati(M):
    R = range(MAXG + 1)
    p = lambda f: sum(M[i][j] for i in R for j in R if f(i, j))
    out = {"1": p(lambda i, j: i > j), "X": p(lambda i, j: i == j), "2": p(lambda i, j: i < j),
           "GG": p(lambda i, j: i > 0 and j > 0)}
    out["NG"] = 1 - out["GG"]
    for t in (0.5, 1.5, 2.5, 3.5):
        out[f"O{t}"] = p(lambda i, j: i + j > t); out[f"U{t}"] = 1 - out[f"O{t}"]
    for t in (0.5, 1.5):
        out[f"H_O{t}"] = p(lambda i, j: i > t); out[f"A_O{t}"] = p(lambda i, j: j > t)
    out["1X"] = out["1"] + out["X"]; out["X2"] = out["X"] + out["2"]; out["12"] = out["1"] + out["2"]
    out["DNB1"] = out["1"] / (out["1"] + out["2"]); out["DNB2"] = 1 - out["DNB1"]
    out["1X_O1.5"] = p(lambda i, j: i >= j and i + j > 1.5)
    out["X2_U3.5"] = p(lambda i, j: i <= j and i + j < 3.5)
    ris = sorted(((M[i][j], f"{i}-{j}") for i in R for j in R), reverse=True)
    return out, ris

ESITI = {"1": lambda i, j: i > j, "X": lambda i, j: i == j, "2": lambda i, j: i < j,
         "1X": lambda i, j: i >= j, "X2": lambda i, j: i <= j, "12": lambda i, j: i != j}
GOL = {"Over 1.5": lambda i, j: i + j >= 2, "Under 3.5": lambda i, j: i + j <= 3, "Over 2.5": lambda i, j: i + j >= 3,
       "Under 2.5": lambda i, j: i + j <= 2, "Goal": lambda i, j: i > 0 and j > 0, "No Goal": lambda i, j: i == 0 or j == 0}
def combo(M):
    """Probabilita' congiunte esito + gol calcolate sulla matrice: la correlazione e' inclusa."""
    R = range(MAXG + 1); out = []
    for e, fe in ESITI.items():
        for g, fg in GOL.items():
            p = sum(M[i][j] for i in R for j in R if fe(i, j) and fg(i, j))
            out.append((f"{e} + {g}", p))
    return out

def primo_tempo(lh, la, quota=0.45):
    """Gol del primo tempo ~ 45% dei gol totali in Serie A (assunzione dichiarata)."""
    M = matrice(lh * quota, la * quota, rho=0.0)
    R = range(MAXG + 1); p = lambda f: sum(M[i][j] for i in R for j in R if f(i, j))
    return {"HT1": p(lambda i, j: i > j), "HTX": p(lambda i, j: i == j), "HT2": p(lambda i, j: i < j),
            "HT_O0.5": p(lambda i, j: i + j > 0.5), "HT_O1.5": p(lambda i, j: i + j > 1.5)}

def no_vig(qs):
    inv = [1 / q for q in qs]; s = sum(inv); return [x / s for x in inv]

def blend(pm, pk, w):
    """w = peso del modello; pk = probabilita' di mercato senza margine."""
    return [w * a + (1 - w) * b for a, b in zip(pm, pk)]

# ------------------------------------------------------------------ backtest
def backtest(seasons, promoted_by_season, xi, k, alpha, start_round_frac=0.25, rho=-0.08):
    """Walk-forward: per ogni data di partita, fit sui dati precedenti. Ritorna metriche."""
    res = []
    allm = []
    for sname, ms in seasons:
        n0 = int(len(ms) * start_round_frac) if not allm else 30
        for idx, m in enumerate(ms):
            if idx >= n0 and m["oH"]:
                hist = [x for x in allm + ms[:idx] if x["date"] < m["date"]]
                res.append((m, hist, promoted_by_season.get(sname, ())))
        allm += ms
    cache = {}; out = []
    for m, hist, prom in res:
        key = (m["date"], len(hist))
        if key not in cache:
            cache[key] = fit(hist, m["date"], xi=xi, k=k, alpha=alpha, promoted=prom)
        par = cache[key]
        lh, la = lambdas(par, m["h"], m["a"])
        mk, _ = mercati(matrice(lh, la, rho))
        y = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
        pk = no_vig([m["oH"], m["oD"], m["oA"]])
        ou = no_vig([m["oO"], m["oU"]]) if m["oO"] else None
        out.append(dict(m=m, pm=[mk["1"], mk["X"], mk["2"]], pk=pk, y=y, pmo=mk["O2.5"],
                        pko=ou[0] if ou else None, yo=int(m["hg"] + m["ag"] > 2.5)))
    return out

def metriche(rows, w):
    ll = br = llo = bro = 0; n = no = 0
    for r in rows:
        p = blend(r["pm"], r["pk"], w)
        ll -= math.log(max(p[r["y"]], 1e-9)); br += sum((p[i] - (i == r["y"])) ** 2 for i in range(3)); n += 1
        if r["pko"] is not None:
            q = w * r["pmo"] + (1 - w) * r["pko"]
            llo -= r["yo"] * math.log(q) + (1 - r["yo"]) * math.log(1 - q); bro += (q - r["yo"]) ** 2; no += 1
    return dict(n=n, logloss_1x2=ll / n, brier_1x2=br / n, logloss_ou=llo / max(no, 1), brier_ou=bro / max(no, 1))
