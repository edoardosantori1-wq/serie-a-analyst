#!/usr/bin/env python3
"""Genera dati/pronostici.json per la prossima giornata e registra le previsioni in dati/storico.sqlite.
Solo libreria standard. Metodo (validato con backtest, vedi BACKTEST in fondo):
 1. Dalle quote Eurobet 1X2 e Over/Under 2.5 senza margine si ricava la coppia di gol attesi (lambda casa,
    lambda ospite) di una Poisson con correzione Dixon-Coles che le riproduce.
 2. Il modello proprio (attacco/difesa con pesi temporali) corregge il totale gol con peso W_GOL;
    sull'1X2 il peso del modello e' W_1X2 (0 = il backtest dice che il mercato e' piu' preciso).
 3. Dalla matrice dei risultati si derivano tutti i mercati, i risultati esatti, l'EV contro le quote Eurobet,
    le triple, le singole e le partite da evitare. Nessun ritocco manuale delle probabilita'.
"""
import json, os, math, sqlite3, itertools, re
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
import modello as MD

BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati")
ROME = ZoneInfo("Europe/Rome")
# Modello "AI" (solo dati) e pesi rispetto al mercato: scelti in automatico da taratura.py (dati/taratura.json).
# Valori di riserva se la taratura non c'e' ancora (stessi risultati del test locale 2025/26 + 2026/27).
RHO = -0.08
TAR = {}
try: TAR = json.load(open(os.path.join(D, "taratura.json")))
except Exception: pass
PAR_1X2 = TAR.get("par_1x2") or dict(xi=0.002, k=4.0, alpha=0.5)   # chi vince: forza di lungo periodo
PAR_GOL = TAR.get("par_gol") or dict(xi=0.02, k=8.0, alpha=0.8)    # gol: forma recente, soprattutto xG
# MODALITA "AI": il pronostico nasce SOLO dall'analisi delle squadre (scelta dell'utente); le quote servono
# solo dopo, per dire se conviene giocarlo (stella) e per il valore delle triple. "MISTO": pesi del test.
MODALITA = os.environ.get("MODALITA", "AI")
if MODALITA == "AI":
    W_1X2, W_GOL = 1.0, 1.0
else:
    W_1X2 = TAR.get("w_1x2", 0.0); W_GOL = TAR.get("w_gol", 0.5)
XI, K, ALPHA = PAR_GOL["xi"], PAR_GOL["k"], PAR_GOL["alpha"]
PROMOSSE = ("Frosinone", "Monza", "Venezia")
# Quota combo stimata = 1 / (prob. di mercato dal risultato esatto x (1 + margine 1X2 Eurobet x FATTORE)).
# 1.0 = stesso margine dell'1X2. Va ricalibrato confrontando le stime con le quote combo reali.
FATTORE_MARGINE_COMBO = 1.0
_CAL = {}
try: _CAL = json.load(open(os.path.join(D, "calibrazione.json")))
except Exception: pass
if _CAL.get("n", 0) >= 5:
    FATTORE_MARGINE_COMBO = _CAL["fattore"]
SING_EV, SING_EDGE = 0.05, 0.04
CALIBRATA = _CAL.get("n", 0) >= 5   # True quando ci sono almeno 5 quote combo reali per misurare il margine      # criteri delle migliori singole

def predicato(k):
    """Condizione sul risultato finale (i gol casa, j gol ospite) che rende vincente la selezione k."""
    base = {"1": lambda i, j: i > j, "X": lambda i, j: i == j, "2": lambda i, j: i < j, "1X": lambda i, j: i >= j,
            "X2": lambda i, j: i <= j, "12": lambda i, j: i != j, "DNB1": lambda i, j: i >= j, "DNB2": lambda i, j: i <= j,
            "GG": lambda i, j: i > 0 and j > 0, "NG": lambda i, j: i == 0 or j == 0}
    if k in base: return base[k]
    m = re.fullmatch(r"([OU])(\d\.5)", k)
    if m: t = float(m.group(2)); return (lambda i, j: i + j > t) if m.group(1) == "O" else (lambda i, j: i + j < t)
    m = re.fullmatch(r"([HA])_O(\d\.5)", k)
    if m: t = float(m.group(2)); return (lambda i, j: i > t) if m.group(1) == "H" else (lambda i, j: j > t)
    if k.startswith("C:"): return MD.EVENTI_COMBO.get(k[2:])
    return None

def esito_ok(n, p1, p2):
    """Combo da 'opinione' (vale per pronostici e triple): mai 12 nelle combo; se una squadra e' favorita
    (>=50%) solo il suo segno secco; doppia chance (1X/X2) o X solo nelle partite equilibrate."""
    es = n.split(" + ")[0]
    if es == "12": return False
    if p1 >= 0.50: return es == "1"
    if p2 >= 0.50: return es == "2"
    return True

def ridondante(n, pp, tutte):
    """Combo a 3 condizioni in cui una condizione non aggiunge quasi nulla (es. 1 + No Goal + Under 4.5):
    abbassa solo la quota. Si scarta se togliendo una condizione la probabilita' cambia meno del 10%."""
    parti = n.split(" + ")
    if len(parti) < 3: return False
    for x in parti[1:]:
        ridotta = " + ".join(y for y in parti if y != x)
        if ridotta in tutte and pp > 0.90 * tutte[ridotta]: return True
    return False

def compatibili(chiavi):
    """True se esiste almeno un risultato finale che fa vincere tutte le selezioni della stessa partita."""
    f = [predicato(k) for k in chiavi]
    if any(x is None for x in f): return False
    return any(all(x(i, j) for x in f) for i in range(8) for j in range(8))

def pronostico(sel):
    """Un pronostico per partita, dall'analisi dell'AI: tra le giocate che l'AI ritiene probabili (>= 55%) con
    quota >= 1.30, prima quelle con la stella (quota sbagliata a favore), poi quella con l'EV migliore."""
    c = [s for s in sel if not s["ht"] and s["p"] >= 0.55 and s["quota"] >= 1.30]
    v = [s for s in c if s["cat"] == "value"]
    if v: return max(v, key=lambda s: s["ev"])
    if not c: return None
    # prudenza sulle quote stimate finche' la calibrazione non misura il margine reale delle combo
    pen = 0.0 if CALIBRATA else 0.04
    return max(c, key=lambda s: (s["ev"] - (pen if s.get("fonte") == "stimata" else 0), s["p"]))

def categoria(s):
    """Classificazione richiesta dalla specifica: evento molto probabile / value bet / alto rischio / senza valore."""
    # value (stella): quota Eurobet reale, EV >= +5% sul modello, 4 punti oltre la prob. implicita
    # E Eurobet paga almeno il 2% piu' della quota equa di Pinnacle (senza Pinnacle niente stella)
    # In modalita' AI la stella nasce dall'analisi: basta che l'AI veda almeno +5% di EV e 4 punti di vantaggio.
    if (s.get("fonte") != "stimata" and s["ev"] >= SING_EV and s["p"] - s["p_impl"] >= SING_EDGE
            and (MODALITA == "AI" or (s.get("p_pin") and s["quota"] * s["p_pin"] - 1 >= 0.02))): return "value"
    if s["p"] >= 0.70: return "probabile"
    if s["p"] < 0.35: return "alto rischio"
    return "senza valore"

def J(n):
    try: return json.load(open(os.path.join(D, n)))
    except Exception: return None

CANON = ["Inter","Lazio","Milan","Roma","Juventus","Napoli","Atalanta","Fiorentina","Bologna","Torino","Como","Cagliari",
         "Lecce","Parma","Venezia","Udinese","Sassuolo","Genoa","Frosinone","Monza","Empoli","Verona","Pisa","Cremonese",
         "Salernitana","Sampdoria","Spezia","Palermo","Bari","Pescara","Modena","Catanzaro","Cesena","Reggiana","Brescia",
         "Benevento","Crotone","Spal","Chievo"]
def canon(name):
    n = (name or "").lower()
    if "inter" in n: return "Inter"
    for c in CANON:
        if {"Juventus": "juve"}.get(c, c.lower()) in n: return c

# --------------------------------------------------------------- quote Eurobet
MK = {str(m["marketId"]): m for m in (J("oddspapi_mercati.json") or [])}
def mid_of(mtype, hc=0.0, per="fulltime"):
    for k, m in MK.items():
        if m["marketType"] == mtype and m["period"] == per and abs(m["handicap"] - hc) < 1e-9 and not m["playerProp"]: return k
def oname(mid, oid):
    for o in MK[mid]["outcomes"]:
        if str(o["outcomeId"]) == str(oid): return o["outcomeName"]
# (nostra chiave, tipo mercato, linea, periodo, nome esito su OddsPapi, etichetta leggibile)
SEL = [("1","1x2",0,"fulltime","1","1 (casa)"),("X","1x2",0,"fulltime","X","X (pareggio)"),("2","1x2",0,"fulltime","2","2 (ospite)"),
       ("1X","doublechance",0,"fulltime","1X","Doppia chance 1X"),("12","doublechance",0,"fulltime","12","Doppia chance 12"),
       ("X2","doublechance",0,"fulltime","2X","Doppia chance X2"),("DNB1","drawnobet",0,"fulltime","1","Draw No Bet 1"),
       ("DNB2","drawnobet",0,"fulltime","2","Draw No Bet 2"),("GG","bothteamsscore",0,"fulltime","Yes","Goal"),
       ("NG","bothteamsscore",0,"fulltime","No","No Goal")]
for t in (0.5, 1.5, 2.5, 3.5):
    SEL += [(f"O{t}","totals",t,"fulltime","Over",f"Over {t}"),(f"U{t}","totals",t,"fulltime","Under",f"Under {t}")]
for t in (0.5, 1.5):
    SEL += [(f"H_O{t}","teamtotals-team1",t,"fulltime","Over",f"Gol casa Over {t}"),(f"A_O{t}","teamtotals-team2",t,"fulltime","Over",f"Gol ospite Over {t}")]
SEL += [("HT1","1x2",0,"p1","1","1 primo tempo"),("HTX","1x2",0,"p1","X","X primo tempo"),("HT2","1x2",0,"p1","2","2 primo tempo"),
        ("HT_O0.5","totals",0.5,"p1","Over","Over 0.5 primo tempo"),("HT_O1.5","totals",1.5,"p1","Over","Over 1.5 primo tempo")]
LABEL = {s[0]: s[5] for s in SEL}
FAMIGLIA = {"1":"1X2","X":"1X2","2":"1X2","1X":"DC","12":"DC","X2":"DC","DNB1":"DNB","DNB2":"DNB","GG":"GGNG","NG":"GGNG"}

def quote_eurobet():
    return quote_bookmaker("eurobet.it")

def quote_bookmaker(slug):
    out = {}
    for fx in (J("oddspapi_quote.json") or []):
        eb = (fx.get("bookmakerOdds") or {}).get(slug)
        if not eb or eb.get("suspended"): continue
        key = (canon(fx.get("participant1Name")), canon(fx.get("participant2Name")))
        mk = eb.get("markets", {}); q = {}; ts = {}
        for key_s, mtype, hc, per, on, _ in SEL:
            mid = mid_of(mtype, hc, per)
            if not mid or mid not in mk: continue
            for oid, o in mk[mid]["outcomes"].items():
                if oname(mid, oid) == on:
                    p = o["players"]["0"]
                    if p.get("active", True) and p.get("price"):
                        q[key_s] = p["price"]; ts[key_s] = p.get("changedAt")
        cs = {}
        cmid = mid_of("correctscore", 0.0, "fulltime")
        if cmid and cmid in mk:
            for oid, o in mk[cmid]["outcomes"].items():
                pz = o["players"]["0"]
                nm = oname(cmid, oid)
                if pz.get("price") and pz.get("active", True) and nm and ":" in nm:
                    i, j = nm.split(":"); cs[(int(i), int(j))] = pz["price"]
        out[key] = dict(q=q, ts=ts, fixtureId=fx.get("fixtureId"), cs=cs)
    return out

def prob_pinnacle(q):
    """Probabilita' senza margine dalle quote Pinnacle (il riferimento piu' preciso del mercato).
    Doppia chance e Draw No Bet si ricavano dall'1X2 Pinnacle."""
    out = {}
    def nv(keys):
        if all(k in q for k in keys):
            inv = [1/q[k] for k in keys]; s = sum(inv)
            for k, v in zip(keys, inv): out[k] = v / s
    nv(["1", "X", "2"]); nv(["GG", "NG"])
    for t in (0.5, 1.5, 2.5, 3.5): nv([f"O{t}", f"U{t}"])
    if all(k in out for k in ("1", "X", "2")):
        out["1X"] = out["1"] + out["X"]; out["X2"] = out["X"] + out["2"]; out["12"] = out["1"] + out["2"]
        out["DNB1"] = out["1"] / (out["1"] + out["2"]); out["DNB2"] = 1 - out["DNB1"]
    return out

def combo_da_esatti(cs, margine):
    """Probabilita' di mercato delle combo ricavate dal risultato esatto Eurobet (senza margine) e quota stimata
    = quota equa ridotta del margine Eurobet. Ritorna {nome: (p_mercato, quota_stimata)}."""
    if len(cs) < 25: return {}
    # metodo "power": p_i = (1/q_i)^k con k tale che la somma faccia 1. A differenza della normalizzazione
    # proporzionale, toglie piu' margine ai risultati improbabili (dove i bookmaker lo caricano di piu').
    lo, hi = 1.0, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if sum((1/v)**k for v in cs.values()) > 1: lo = k
        else: hi = k
    P = {key: (1/v)**k for key, v in cs.items()}; s = sum(P.values()); P = {key: v/s for key, v in P.items()}
    out = {}
    for n, f in MD.EVENTI_COMBO.items():
        pm = sum(v for (i, j), v in P.items() if f(i, j))
        if pm > 0.02: out[n] = (pm, round(1/(pm*(1+margine)), 2))
    return out

# ------------------------------------------- lambda che riproducono il mercato
def fit_market(p1, px, p2, po25):
    def err(lh, la):
        M = MD.matrice(lh, la, RHO); a = b = c = o = 0.0
        for i, row in enumerate(M):
            for j, v in enumerate(row):
                if i > j: a += v
                elif i == j: b += v
                else: c += v
                if i + j > 2: o += v
        e = (a-p1)**2 + (b-px)**2 + (c-p2)**2
        if po25 is not None: e += (o-po25)**2
        return e
    best = (9, 1.4, 1.1)
    for lh in [x/10 for x in range(2, 40)]:
        for la in [x/10 for x in range(2, 35)]:
            e = err(lh, la)
            if e < best[0]: best = (e, lh, la)
    _, lh, la = best; step = 0.025
    for _ in range(40):
        cand = [(err(lh+dx, la+dy), lh+dx, la+dy) for dx in (-step,0,step) for dy in (-step,0,step) if lh+dx>0.05 and la+dy>0.05]
        e, nlh, nla = min(cand)
        if (nlh, nla) == (lh, la): step /= 2
        lh, la = nlh, nla
        if step < 1e-4: break
    return lh, la, best[0]

def quote_combo_manuali():
    """dati/quote_combo.csv: partita;combo;prob_stimata;quota_minima;quota_eurobet;rilevata
    Le quote sono inserite dall'utente dal sito Eurobet (fonte: manuale)."""
    import csv
    out = {}; path = os.path.join(D, "quote_combo.csv")
    if not os.path.exists(path): return out
    mt = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat(timespec="seconds")
    for r in csv.DictReader(open(path, encoding="utf-8-sig"), delimiter=";"):
        q = (r.get("quota_eurobet") or "").replace(",", ".").strip()
        try: q = float(q)
        except ValueError: continue
        if q <= 1: continue
        out[((r.get("partita") or "").strip(), (r.get("combo") or "").strip())] = (q, (r.get("rilevata") or "").strip() or mt)
    return out

def scrivi_modello_combo(out, manuali, triple=None, marcatori=None):
    if not any(r.get("selezioni") for r in out):
        print("Modulo quote combo: quote Eurobet della giornata non ancora disponibili, file lasciato com'e'"); return
    """Modulo da compilare: SOLO le combo che il sistema usa davvero (pronostico della partita + triple
    del sabato e della domenica), cosi' le quote che contano sono verificate. Le quote gia' inserite restano."""
    import csv
    usate = {}
    for r in out:
        p = r.get("pronostico")
        if p and p["k"].startswith("C:"): usate[(f'{r["casa"]}-{r["ospite"]}', p["k"][2:])] = p["p"]
    for g in (triple or {}).values():
        for t in g.values():
            for c in (t or {}).get("selezioni", []):
                if c["k"].startswith("C:"): usate[(c["match"], c["k"][2:])] = c["p"]
    for x in (marcatori or {}).get("lista", []):            # i 4 marcatori: quota Tandem+ da leggere su Eurobet
        usate[(x["match"], f"Tandem+ {x['nome']}")] = x["p"]
    ordine = {f'{r["casa"]}-{r["ospite"]}': n for n, r in enumerate(out)}
    path = os.path.join(D, "quote_combo.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["partita", "combo", "prob_stimata", "quota_minima", "quota_eurobet", "rilevata"])
        for k, pp in sorted(usate.items(), key=lambda x: (ordine.get(x[0][0], 99), x[0][1])):
            q, ts = manuali.get(k, ("", ""))
            w.writerow([k[0], k[1], f"{pp*100:.1f}%", f"{1/pp:.2f}".replace(".", ","), str(q).replace(".", ",") if q else "", ts])
        # quote gia' inserite per combo non piu' usate: si tengono (servono comunque alla calibrazione)
        for k, (q, ts) in manuali.items():
            if k not in usate and k[0] in ordine:
                w.writerow([k[0], k[1], "", "", str(q).replace(".", ","), ts])

# --------------------------------------------------- assenze (API-Football /injuries)
def _assenze_tutte():
    """Giocatori che potrebbero non giocare (infortuni, squalifiche), da API-Football. Mai inventati:
    se la fonte non risponde o il piano gratuito non copre la stagione, l'AI non applica correzioni."""
    d = J("apif_infortuni.json")
    if not d: return {}, "assenze non scaricate"
    if d.get("errors"): return {}, "assenze non disponibili: " + json.dumps(d["errors"], ensure_ascii=False)[:160]
    out = {}
    for x in d.get("response", []):
        team = canon((x.get("team") or {}).get("name")); pl = x.get("player") or {}; fx = x.get("fixture") or {}
        if team and pl.get("name") and fx.get("date"):
            out.setdefault(team, []).append(dict(nome=pl["name"], tipo=pl.get("type") or "", motivo=pl.get("reason") or "", data=fx["date"]))
    return out, None
ASSENZE, ASSENZE_STATO = _assenze_tutte()

def assenti(team, inizio):
    t0 = datetime.fromisoformat(inizio.replace("Z", "+00:00")); viste = set(); out = []
    for x in ASSENZE.get(team, []):
        try: t = datetime.fromisoformat(x["data"].replace("Z", "+00:00"))
        except ValueError: continue
        if abs((t - t0).total_seconds()) <= 36*3600 and x["nome"] not in viste:
            viste.add(x["nome"]); out.append(dict(x, dubbio=("questionable" in x["tipo"].lower())))
    return out

def _stesso_giocatore(nome_api, nome_xg):
    a, b = _norm(nome_api), _norm(nome_xg)
    if not a or not b or a[-1] not in b: return False          # stesso cognome
    return len(a) == 1 or len(a[0]) > 1 or a[0][0] == b[0][0]   # e stessa iniziale del nome, se indicata

def effetto_assenze(team, lista):
    """Quanto pesa ogni assente nell'attacco: quota dei suoi xG su quelli della squadra. Chi lo sostituisce
    recupera circa meta' della produzione (assunzione dichiarata); un dubbio pesa meta'. Riduzione massima 25%.
    I difensori assenti non sono misurabili con gli xG: non correggono il calcolo."""
    L = (J("striker_xg_giocatori.json") or {}).get("data", {}).get("leaders", [])
    TSx = {canon(t["display_name"]): t for t in (J("striker_team_stats.json") or {}).get("data", {}).get("teams", [])}
    AB = {t["abbrev"]: canon(t["display_name"]) for t in (J("striker_team_stats.json") or {}).get("data", {}).get("teams", [])}
    ts = TSx.get(team); tot = (ts or {}).get("xg_for", 0) * (ts or {}).get("games", 0)
    persa = 0.0
    for x in lista:
        p = next((p for p in L if AB.get(p["team"]) == team and _stesso_giocatore(x["nome"], p["name"])), None)
        x["quota_xg"] = round(float(p["value"]) / tot, 3) if p and tot else 0.0
        persa += x["quota_xg"] * 0.5 * (0.5 if x["dubbio"] else 1.0)
    return max(0.75, 1 - persa)

def main():
    now = datetime.now(timezone.utc)
    pro = [m for m in (J("fdorg_prossime.json") or {}).get("matches", []) if m.get("status") in ("SCHEDULED", "TIMED")]
    pro.sort(key=lambda m: m["utcDate"]); md = pro[0]["matchday"] if pro else None
    partite = [m for m in pro if m["matchday"] == md]
    # storico per il modello proprio
    storico = []
    for f in sorted(os.listdir(D)):
        if f.startswith("storico_") and f.endswith(".csv"): storico += MD.leggi_csv(os.path.join(D, f))
    storico += MD.leggi_csv(os.path.join(D, "fdcouk_corrente.csv"))
    for m in storico: m["h"], m["a"] = canon(m["h"]), canon(m["a"])
    storico = [m for m in storico if m["h"] and m["a"]]
    storico.sort(key=lambda m: m["date"])
    par1 = MD.fit(storico, now.date(), xi=PAR_1X2["xi"], k=PAR_1X2["k"], alpha=PAR_1X2["alpha"], promoted=PROMOSSE, xi_liv=PAR_1X2.get("xi_liv", 0.02))
    parg = MD.fit(storico, now.date(), xi=PAR_GOL["xi"], k=PAR_GOL["k"], alpha=PAR_GOL["alpha"], promoted=PROMOSSE, xi_liv=PAR_GOL.get("xi_liv", 0.02))
    par = parg
    Q = quote_eurobet(); PIN = quote_bookmaker("pinnacle"); out = []; MAN = quote_combo_manuali()
    for m in partite:
        h, a = canon(m["homeTeam"]["name"]), canon(m["awayTeam"]["name"])
        dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(ROME)
        qq = Q.get((h, a), {}); q = qq.get("q", {})
        # previsione AI: chi e' piu' forte (supremazia) dal modello 1X2, quanti gol dal modello sulla forma recente
        l1h, l1a = MD.lambdas(par1, h, a); lgh, lga = MD.lambdas(parg, h, a)
        sup_m, tot_m = l1h - l1a, lgh + lga
        lhm, lam = max((tot_m + sup_m)/2, 0.05), max((tot_m - sup_m)/2, 0.05)
        # assenze: l'attacco della squadra perde la quota di xG dei giocatori indisponibili
        ass_h, ass_a = assenti(h, m["utcDate"]), assenti(a, m["utcDate"])
        fh, fa = effetto_assenze(h, ass_h), effetto_assenze(a, ass_a)
        lhm, lam = lhm * fh, lam * fa
        mk_mod, ris_mod = MD.mercati(MD.matrice(lhm, lam, RHO))
        rec = dict(id=m["id"], data=m["utcDate"], giorno=dt.strftime("%Y-%m-%d"), wd=dt.weekday(), casa=h, ospite=a,
                   lam_modello=[round(lhm, 2), round(lam, 2)], p_modello={k: round(mk_mod[k], 4) for k in ("1","X","2","O2.5","U2.5","GG","NG","O1.5","U3.5")},
                   risultato_modello=ris_mod[0][1], assenze={h: ass_h, a: ass_a}, effetto_assenze=[round(fh, 3), round(fa, 3)])
        if all(k in q for k in ("1", "X", "2")):
            pk = MD.no_vig([q["1"], q["X"], q["2"]]); marg = sum(1/q[k] for k in ("1","X","2")) - 1
            po = MD.no_vig([q["O2.5"], q["U2.5"]])[0] if "O2.5" in q and "U2.5" in q else None
            lh, la, fit_err = fit_market(*pk, po)
            # correzione del modello: totale gol (W_GOL) e supremazia (W_1X2)
            tot = (1-W_GOL)*(lh+la) + W_GOL*(lhm+lam)
            sup = (1-W_1X2)*(lh-la) + W_1X2*(lhm-lam)
            lhf, laf = max((tot+sup)/2, 0.05), max((tot-sup)/2, 0.05)
            M = MD.matrice(lhf, laf, RHO); mk, ris = MD.mercati(M); mk.update(MD.primo_tempo(lhf, laf))
            rec.update(lam=[round(lhf, 2), round(laf, 2)], margine_1x2=round(marg, 4), p_mercato=dict(zip("1X2", [round(x, 4) for x in pk]), **({"O2.5": round(po, 4)} if po else {}),
                                     **({"GG": round(MD.no_vig([q["GG"], q["NG"]])[0], 4)} if "GG" in q and "NG" in q else {})),
                       fit_err=round(fit_err, 6), quote_ts=max([t for t in qq["ts"].values() if t] or [None]))
            rec["risultati"] = [(s, round(p, 4)) for p, s in ris[:3]]
            rec["combo"] = [(n, round(pp, 4)) for n, pp in sorted(MD.combo(M), key=lambda x: -x[1]) if 0.15 <= pp <= 0.90]
            sel = []
            for k, lab in LABEL.items():
                if k in mk and k in q:
                    p = mk[k]; o = q[k]; ev = p*o - 1
                    sel.append(dict(k=k, label=lab, p=round(p, 4), quota=o, p_impl=round(1/o, 4), ev=round(ev, 4),
                                    ht=k.startswith("HT")))
            CE = combo_da_esatti(qq.get("cs", {}), marg * FATTORE_MARGINE_COMBO)
            tutte = dict(MD.combo(M))
            rec["combo_mercato"] = {n: [round(v[0], 4), v[1]] for n, v in CE.items()}
            rec["combo"] = [(n, pp) for n, pp in rec["combo"] if esito_ok(n, mk["1"], mk["2"]) and not ridondante(n, pp, tutte)]
            for n, pp in rec["combo"]:
                k = (f"{h}-{a}", n)
                if k in MAN:
                    o, ts = MAN[k]
                    sel.append(dict(k="C:" + n, label=n, p=round(pp, 4), quota=o, p_impl=round(1/o, 4), ev=round(pp*o-1, 4),
                                    ht=False, fonte="manuale", rilevata=ts))
                elif n in CE:
                    o = CE[n][1]
                    sel.append(dict(k="C:" + n, label=n, p=round(pp, 4), quota=o, p_impl=round(1/o, 4), ev=round(pp*o-1, 4),
                                    ht=False, fonte="stimata", p_mercato=round(CE[n][0], 4)))
            ppin = prob_pinnacle(PIN.get((h, a), {}).get("q", {}))
            rec["p_pin"] = {k: round(ppin[k], 4) for k in ("1", "X", "2", "O2.5", "GG") if k in ppin}
            for s in sel:
                if s["k"] in ppin: s["p_pin"] = round(ppin[s["k"]], 4)
                s["cat"] = categoria(s)
            rec["selezioni"] = sel
            rec["pronostico"] = pronostico(sel)
            rec["p"] = {k: round(v, 4) for k, v in mk.items() if not k.endswith("_O1.5") or True}
            # avvisi
            avv = []
            dis = max(abs(mk_mod[s]-pk[i]) for i, s in enumerate("1X2"))
            if dis > 0.12: avv.append(f"modello e mercato divergono di {dis*100:.0f} punti sull'1X2")
            if rec["quote_ts"]:
                age = (now - datetime.fromisoformat(rec["quote_ts"].replace("Z", "+00:00"))).days
                if age >= 4: avv.append(f"quote ferme da {age} giorni: verificare sul sito")
            if marg > 0.075: avv.append(f"margine Eurobet alto ({marg*100:.1f}%)")
            rec["avvisi"] = avv
        else:
            rec["avvisi"] = ["quote Eurobet NON VERIFICATE: nessuna probabilità finale calcolata"]
        rec["contesto"] = contesto(h, a, m["utcDate"])
        out.append(rec)

    # ------------------------------------------------------------ triple, singole
    def cand(day_wd, pmin, evmin):
        c = []
        for r in out:
            if r["wd"] != day_wd or "selezioni" not in r: continue
            for s in r["selezioni"]:
                if s["ht"] or s["p"] < pmin or s["ev"] < evmin or s["quota"] < 1.12: continue
                c.append(dict(s, match=f'{r["casa"]}-{r["ospite"]}', mid=r["id"]))
        return c
    TIPI = [("semplice", 0.66, -0.07, 1.80, 2.80), ("media", 0.42, -0.08, 3.00, 5.50), ("aggressiva", 0.25, -0.12, 6.00, 15.0)]
    def giudizio(ev, combo):
        reali = all(c.get("fonte") != "stimata" for c in combo)
        if ev >= 0.10 and reali and all(c.get("cat") == "value" for c in combo): return "Valore positivo"
        if ev >= -0.08: return "Neutra: nessun vantaggio significativo"
        return "EV negativo: solo test virtuale"
    triple = {}
    for nome_g, wd in (("sabato", 5), ("domenica", 6)):
        usate = set(); triple[nome_g] = {}
        for tipo, pmin, evmin0, qlo, qhi in TIPI:
          best = None
          for evmin in (evmin0, evmin0 - 0.10, -1.0):  # se non si trova nulla, si allarga il filtro EV (la tripla esce sempre)
            if best: break
            cs = [c for c in cand(wd, pmin, evmin) if (c["mid"], c["k"]) not in usate]
            if tipo == "aggressiva":     # solo combo (2 o 3 condizioni), quota 1.80-4.00 ciascuna
                cs = [c for c in cs if c["k"].startswith("C:") and 1.80 <= c["quota"] <= 4.00]
            for combo in itertools.combinations(cs, 3):
                if len({c["mid"] for c in combo}) < 3: continue
                # compatibilita' con le altre triple dello stesso giorno: giocandole tutte, devono poter vincere tutte
                if any(not compatibili([k for (m2, k) in usate if m2 == c["mid"]] + [c["k"]]) for c in combo): continue
                qt = math.prod(c["quota"] for c in combo)
                if not (qlo <= qt <= qhi): continue
                pj = math.prod(c["p"] for c in combo); ev = pj*qt - 1
                if tipo == "aggressiva" and qt > 15: continue
                pen = 0.0 if CALIBRATA else 0.04 * sum(1 for c in combo if c.get("fonte") == "stimata")
                score = (pj - pen/4, ev - pen) if tipo == "semplice" else (ev - pen, pj)
                if best is None or score > best[0]: best = (score, combo, qt, pj, ev)
            if best:
                _, combo, qt, pj, ev = best
                for c in combo: usate.add((c["mid"], c["k"]))
                triple[nome_g][tipo] = dict(selezioni=list(combo), quota=round(qt, 2), p=round(pj, 4), ev=round(ev, 4), giudizio=giudizio(ev, combo))
            else:
                triple[nome_g][tipo] = None
    # Singole: solo quote reali (no stimate), EV >= +5%, vantaggio >= 4 punti sulla prob. implicita, prob >= 30%
    singole = sorted([dict(s, match=f'{r["casa"]}-{r["ospite"]}', giorno=r["giorno"]) for r in out for s in r.get("selezioni", [])
                      if not s["ht"] and s.get("fonte") != "stimata" and s["ev"] >= SING_EV and s["p"] - s["p_impl"] >= SING_EDGE
                      and s["p"] >= 0.30], key=lambda s: -s["ev"])
    viste = set(); sing = []
    for s in singole:
        if s["match"] in viste: continue
        viste.add(s["match"]); sing.append(s)
        if len(sing) == 5: break
    marcatori = stima_marcatori(out, Q, MAN)
    evitare = [dict(match=f'{r["casa"]}-{r["ospite"]}', motivi=r["avvisi"]) for r in out if r.get("avvisi")]
    res = dict(generato=now.isoformat(timespec="seconds"), giornata=md, partite=out, triple=triple, singole=sing, evitare=evitare, marcatori=marcatori,
               assenze_stato=ASSENZE_STATO, metodo=dict(modalita=MODALITA, W_1X2=W_1X2, W_GOL=W_GOL, par_1x2=PAR_1X2, par_gol=PAR_GOL, rho=RHO, backtest=BACKTEST,
                           taratura={k: TAR.get(k) for k in ("generato", "stagioni", "taratura", "verifica_stagione_corrente", "roi_verifica", "nota")} if TAR else None))
    # confronto stime vs quote reali inserite (per ricalibrare FATTORE_MARGINE_COMBO)
    conf = []
    for r in out:
        for n, (pm, qs) in (r.get("combo_mercato") or {}).items():
            k = (f'{r["casa"]}-{r["ospite"]}', n)
            if k in MAN: conf.append(dict(partita=k[0], combo=n, stimata=qs, reale=MAN[k][0], scarto=round(MAN[k][0]/qs-1, 4)))
    res["calibrazione_combo"] = dict(confronti=conf, scarto_medio=round(sum(c["scarto"] for c in conf)/len(conf), 4) if conf else None)
    # margine reale delle combo: per ogni quota inserita, margine effettivo = 1/(p_mercato x quota_reale) - 1,
    # rapportato al margine 1X2 della stessa partita; il fattore e' la mediana di tutti i confronti raccolti
    storico_cal = _CAL.get("confronti", [])
    chiavi = {(c["partita"], c["combo"]) for c in storico_cal}
    for r in out:
        for n, (pm, qs) in (r.get("combo_mercato") or {}).items():
            k = (f'{r["casa"]}-{r["ospite"]}', n)
            if k in MAN and k not in chiavi and r.get("margine_1x2"):
                m_eff = 1 / (pm * MAN[k][0]) - 1
                storico_cal.append(dict(partita=k[0], combo=n, quota_reale=MAN[k][0], p_mercato=round(pm, 4),
                                        margine_combo=round(m_eff, 4), margine_1x2=r["margine_1x2"], rapporto=round(m_eff / r["margine_1x2"], 3)))
    if storico_cal:
        rr = sorted(c["rapporto"] for c in storico_cal)
        fatt = rr[len(rr)//2] if len(rr) % 2 else (rr[len(rr)//2 - 1] + rr[len(rr)//2]) / 2
        json.dump(dict(n=len(storico_cal), fattore=round(max(0.5, min(fatt, 4.0)), 3), confronti=storico_cal),
                  open(os.path.join(D, "calibrazione.json"), "w"), ensure_ascii=False, indent=1)
    if os.environ.get("SOLO_MODULO") == "1":
        scrivi_modello_combo(out, MAN, triple, marcatori); print("Modulo quote combo preparato per la giornata", md); return
    json.dump(res, open(os.path.join(D, "pronostici.json"), "w"), ensure_ascii=False, indent=1)
    scrivi_modello_combo(out, MAN, triple, marcatori)
    if os.environ.get("REGISTRA", "1") == "0":
        print("Avvio di prova: previsioni non registrate nello storico."); return
    try:
        registra(res, now)
    except sqlite3.Error as e:
        print(f"ATTENZIONE: storico non aggiornato ({e})")
    print(f"Pronostici giornata {md}: {len(out)} partite, singole {len(sing)}, triple sab {sum(1 for v in triple['sabato'].values() if v)}/3, dom {sum(1 for v in triple['domenica'].values() if v)}/3")

def contesto(h, a, start):
    """Segnalazioni informative (non entrano nel calcolo)."""
    out = []
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    gioc = (J("fdorg_giocate.json") or {}).get("matches", [])
    eur = (J("fdorg_coppe.json") or {}).get("matches", [])
    for team in (h, a):
        ult = [datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")) for m in gioc + eur
               if team in (canon(m["homeTeam"]["name"]), canon(m["awayTeam"]["name"]))
               and datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")) < t0]
        if ult:
            gg = (t0 - max(ult)).total_seconds() / 86400
            if gg < 4: out.append(f"{team}: solo {gg:.0f} giorni di riposo")
        prox = [m for m in eur if team in (canon(m["homeTeam"]["name"]), canon(m["awayTeam"]["name"]))
                and 0 < (datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")) - t0).days <= 4]
        if prox: out.append(f"{team}: impegno europeo nei 4 giorni successivi (possibile turnover)")
    for ev in (J("allenatori_cambi.json") or []):
        if ev["squadra"] in (h, a):
            gg = (t0 - datetime.fromisoformat(ev["rilevato"])).days
            if gg <= 35: out.append(f"{ev['squadra']}: nuovo allenatore {ev['nuovo']} (al posto di {ev['vecchio']}, rilevato {gg} giorni fa)")
    return out

import unicodedata
def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("-", " ").replace(".", "")
    return [t for t in s.replace(",", " ").split() if t]
PALO = 0.18   # pali/traverse per gol segnato in Serie A (ordine di grandezza): il Tandem+ vince anche con palo o traversa
def stima_marcatori(out, Q, man=None):
    """P(segna) = 1 - exp(-lambda). lambda = xG/90 del giocatore (ristretto verso la media del ruolo) x minuti attesi/90
    x (gol attesi della squadra in questa partita / xG medio stagionale della squadra). Minuti attesi = minuti stagionali /
    partite della squadra: incorpora rotazioni e assenze passate, NON la titolarita' di questa partita (ignota fino alle formazioni)."""
    L = (J("striker_xg_giocatori.json") or {}).get("data", {}).get("leaders", [])
    if not L: return dict(stato="mancano gli xG dei giocatori (StrikerAPI): eseguire aggiorna.py", lista=[])
    TS = {canon(t["display_name"]): t for t in (J("striker_team_stats.json") or {}).get("data", {}).get("teams", [])}
    AB = {t["abbrev"]: canon(t["display_name"]) for t in (J("striker_team_stats.json") or {}).get("data", {}).get("teams", [])}
    LU = J("formazioni.json") or {}
    eb_raw = {}
    amid = next((k for k, m in MK.items() if m["marketType"] == "players-anytimegoalscorer"), None)
    for fx in (J("oddspapi_quote.json") or []):
        eb = (fx.get("bookmakerOdds") or {}).get("eurobet.it")
        if not eb or not amid or amid not in eb.get("markets", {}): continue
        key = (canon(fx.get("participant1Name")), canon(fx.get("participant2Name")))
        eb_raw[key] = [(p["playerName"], p["price"]) for o in eb["markets"][amid]["outcomes"].values() for p in o["players"].values() if p.get("playerName") and p.get("price")]
    righe = []
    for r in out:
        if "lam" not in r: continue
        for side, team, opp, lam in ((0, r["casa"], r["ospite"], r["lam"][0]), (1, r["ospite"], r["casa"], r["lam"][1])):
            ts = TS.get(team); 
            if not ts or not ts.get("xg_for"): continue
            fatt = lam / ts["xg_for"]
            for p in L:
                if AB.get(p["team"]) != team or not p.get("minutes"): continue
                xg = float(p["value"]); mins = p["minutes"]; gteam = ts["games"]
                pos = (p.get("position") or "").lower()
                prior = 0.35 if ("forward" in pos or "striker" in pos or "wing" in pos) else (0.06 if ("back" in pos or "defender" in pos) else 0.14)
                xg90 = (xg + prior * 270/90) / (mins + 270) * 90   # shrink verso la media del ruolo (270 minuti)
                mexp = min(mins / gteam, 90)
                tit = None
                lu = LU.get(str(r["id"]), {}).get(team)
                if lu and lu.get("ufficiale"):
                    tit = any(set(_norm(p["name"])) & set(_norm(n)) for n in lu.get("titolari", []))
                    mexp = 80 if tit else 15
                ass = next((x for x in (r.get("assenze") or {}).get(team, []) if _stesso_giocatore(x["nome"], p["name"])), None)
                if ass and not ass["dubbio"] and not tit: continue          # indisponibile: non puo' segnare
                if ass and ass["dubbio"] and tit is None: mexp *= 0.5
                lp = xg90 * mexp / 90 * fatt; pr = 1 - math.exp(-lp)
                # Tandem+ (come lo gioca l'utente): vince se segna lui O chi entra al suo posto O se colpisce palo/traversa.
                # Se il giocatore non scende in campo la giocata e' rimborsata: si ragiona sui minuti quando gioca.
                mgioca = 80 if tit else (15 if tit is False else min(mins / max(p.get("games") or gteam, 1), 90))
                sub = prior * (90 - mgioca) / 90 if mgioca >= 60 else 0.0      # il sostituto conta solo per chi parte titolare
                lt = (xg90 * mgioca / 90 + sub) * fatt * (1 + PALO); pt_ = 1 - math.exp(-lt)
                pgioca = 1 - math.exp(-xg90 * mgioca / 90 * fatt)     # P(segna) quando gioca: base del rapporto con la quota
                quota = None
                pt = _norm(p["name"]); cand_q = []
                for n, pz in eb_raw.get((r["casa"], r["ospite"]), []):
                    nt = _norm(n)
                    if nt and pt and nt[0] in pt:
                        cand_q.append((len(nt) == 1 or any(x[0] == nt[-1][0] for x in pt), pz))
                exact = [c for c in cand_q if c[0]]
                if exact: quota = exact[0][1]
                elif len(cand_q) == 1: quota = cand_q[0][1]   # cognome unico nella partita
                # quota Tandem+: inserita a mano dall'utente (modulo combo) oppure stimata dalla quota "segna sempre" Eurobet
                # mantenendo lo stesso margine: quota_t = quota x P(segna)/P(Tandem+)
                match = f'{r["casa"]}-{r["ospite"]}'
                qm = (man or {}).get((match, f"Tandem+ {p['name']}"))
                if qm: qt, fonte = qm[0], "reale"
                elif quota: qt, fonte = round(max(1.05, quota * pgioca / pt_), 2), "stimata"
                else: qt, fonte = None, None
                righe.append(dict(nome=p["name"], squadra=team, avversario=opp, match=match, mid=r["id"],
                                  xg=xg, minuti=mins, partite=p["games"], xg90=round(xg90, 3), min_attesi=round(mexp), titolare=tit,
                                  p_segna=round(pr, 4), quota_segna=quota, p=round(pt_, 4), quota=qt, fonte=fonte,
                                  ev=round(pt_*qt-1, 4) if qt else None))
    righe.sort(key=lambda x: -x["p"])
    top = []
    for x in righe:
        if x["min_attesi"] < 55: continue          # titolarita' troppo incerta
        if not x["quota"]: continue                # senza quota Eurobet "segna sempre": probabile assente (infortunio, squalifica)
        top.append(x)
        if len(top) == 4: break
    comb = None
    if len(top) == 4 and all(x["quota"] for x in top):
        q = math.prod(x["quota"] for x in top); pj = math.prod(x["p"] for x in top)
        comb = dict(quota=round(q, 2), p=round(pj, 4), ev=round(pj*q-1, 4), stessa_partita=len({x["mid"] for x in top}) < 4)
    altri = [x for x in righe if x not in top and x["quota"]][:16]
    return dict(stato="ok", lista=top, altri=altri, combinazione=comb)

def registra(res, now):
    """Storico permanente: si inserisce solo prima del calcio d'inizio, mai si modifica."""
    db = sqlite3.connect(os.path.join(D, "storico.sqlite"))
    db.execute("""CREATE TABLE IF NOT EXISTS previsioni(id INTEGER PRIMARY KEY, creato TEXT, giornata INT, match_id INT, partita TEXT,
                  inizio TEXT, mercato TEXT, quota REAL, p_modello REAL, ev REAL, tipo TEXT, gruppo TEXT, esito INT, profitto REAL)""")
    if "quota_chiusura" not in [c[1] for c in db.execute("PRAGMA table_info(previsioni)")]:
        db.execute("ALTER TABLE previsioni ADD COLUMN quota_chiusura REAL")
    def ins(r_mid, partita, inizio, s, tipo, gruppo):
        if inizio <= now.isoformat(): return
        if db.execute("SELECT 1 FROM previsioni WHERE match_id=? AND mercato=? AND tipo=? AND gruppo=?", (r_mid, s["k"], tipo, gruppo)).fetchone(): return
        db.execute("INSERT INTO previsioni(creato,giornata,match_id,partita,inizio,mercato,quota,p_modello,ev,tipo,gruppo) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (now.isoformat(timespec="seconds"), res["giornata"], r_mid, partita, inizio, s["k"], s["quota"], s["p"], s["ev"], tipo, gruppo))
    start = {r["id"]: r["data"] for r in res["partite"]}
    for g, tt in res["triple"].items():
        for tipo, t in tt.items():
            if t:
                for s in t["selezioni"]: ins(s["mid"], s["match"], start[s["mid"]].replace("Z", "+00:00"), s, f"tripla_{tipo}", g)
    for r in res["partite"]:
        if r.get("pronostico"):
            ins(r["id"], f'{r["casa"]}-{r["ospite"]}', r["data"].replace("Z", "+00:00"), r["pronostico"], "pronostico", "")
    for s in res["singole"]:
        mid = next(r["id"] for r in res["partite"] if f'{r["casa"]}-{r["ospite"]}' == s["match"])
        ins(mid, s["match"], start[mid].replace("Z", "+00:00"), s, "singola", "")
    for x in res.get("marcatori", {}).get("lista", []):
        if x.get("quota"):
            ins(x["mid"], x["match"], start[x["mid"]].replace("Z", "+00:00"), dict(k="SCORER:"+x["nome"], quota=x["quota"], p=x["p"], ev=x["ev"]), "marcatore", "")
    # confronto interno AI vs Pinnacle (non pubblicato): probabilita' all'uscita, verificate a fine partita
    db.execute("""CREATE TABLE IF NOT EXISTS confronto(match_id INT, partita TEXT, inizio TEXT, mercato TEXT, p_ai REAL, p_pin REAL,
                  PRIMARY KEY(match_id, mercato))""")
    for r in res["partite"]:
        if r["data"].replace("Z", "+00:00") <= now.isoformat(): continue
        for k, v in (r.get("p_pin") or {}).items():
            if k in (r.get("p_modello") or {}):
                db.execute("INSERT OR IGNORE INTO confronto VALUES(?,?,?,?,?,?)", (r["id"], f'{r["casa"]}-{r["ospite"]}', r["data"], k, r["p_modello"][k], v))
    db.commit(); db.close()

BACKTEST = dict(partite=365, periodo="2025/26 (dalla 10a giornata) + 2026/27 (giornate 1-11)", riferimento="quote medie di chiusura (football-data.co.uk)",
                logloss_1x2_modello=0.9878, logloss_1x2_mercato=0.9577, logloss_ou_mercato=0.7053, logloss_ou_mix25=0.7041)

if __name__ == "__main__":
    main()
