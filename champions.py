#!/usr/bin/env python3
"""Champions League: pronostici, analisi, triple (3 per giorno di gioco) e marcatori (4 per giornata).

Le squadre vengono da campionati diversi, quindi la forza NON si stima dai soli gol come in Serie A:
  - chi e' piu' forte: Elo di ClubElo (api.clubelo.com, gratuito), che confronta club di tutti i campionati europei;
    vantaggio campo HFA punti Elo. Elo -> risultato atteso (vittoria + meta' pareggio) della squadra di casa;
  - quanti gol: media gol della Champions di questa stagione, corretta con attacco e difesa delle due squadre
    nei loro campionati (gol fatti/subiti a partita rispetto alla media del loro campionato, football-data.org);
  - si cercano i gol attesi delle due squadre che rispettano sia il totale sia il risultato atteso dall'Elo,
    poi la stessa matrice dei risultati (Poisson con correzione Dixon-Coles) usata per la Serie A.
Le quote (Eurobet, Pinnacle) arrivano da OddsPapi; le combo hanno quota stimata dal risultato esatto Eurobet,
calibrata con le quote reali raccolte per la Serie A. Nessun dato inventato: se manca l'Elo o la quota, si salta.
Scrive dati/champions.json e, all'uscita ufficiale, registra le previsioni nello storico (tipo cl_*).
"""
import csv, difflib, io, itertools, json, math, os, re, sqlite3, unicodedata
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import modello as MD
import predizioni as P

D = P.D; ROME = ZoneInfo("Europe/Rome"); RHO = -0.08
HFA = 65                 # vantaggio campo in punti Elo (valore tipico per le coppe europee)
GOL_BASE = 3.0           # media gol di riserva, se non ci sono ancora partite di Champions giocate
CAMPIONATI = ["PL", "PD", "BL1", "SA", "FL1", "DED", "PPL"]   # campionati gratuiti su football-data.org
J = P.J

STOP = {"fc", "cf", "ac", "afc", "sc", "as", "ss", "ssc", "club", "de", "calcio", "futbol", "football", "cd", "the", "1",
        "sv", "fk", "sk", "kv", "rc", "cp", "sl", "bc", "ud", "ca", "cfc", "1899", "1909", "1846", "1900", "04", "05"}
ALIAS = {"internazionale": "inter", "munchen": "bayern", "munich": "bayern", "saint germain": "psg", "paris sg": "psg",
         "paris saint germain": "psg", "manchester city": "man city", "manchester united": "man united", "atletico": "atletico",
         "tottenham hotspur": "tottenham", "borussia dortmund": "dortmund", "bayer 04 leverkusen": "leverkusen",
         "sporting clube de portugal": "sporting", "sport lisboa e benfica": "benfica"}

def nn(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("-", " ").replace(".", " ")
    for a, b in ALIAS.items():
        if a in s: s = s.replace(a, b)
    return [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in STOP]

def sim(a, b):
    ta, tb = set(nn(a)), set(nn(b))
    if not ta or not tb: return 0.0
    jac = len(ta & tb) / len(ta | tb)
    return max(jac, difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() * 0.9)

AREA = {"England": "ENG", "Spain": "ESP", "Germany": "GER", "Italy": "ITA", "France": "FRA", "Portugal": "POR", "Netherlands": "NED",
        "Belgium": "BEL", "Scotland": "SCO", "Austria": "AUT", "Switzerland": "SUI", "Turkey": "TUR", "Türkiye": "TUR", "Greece": "GRE",
        "Czech Republic": "CZE", "Czechia": "CZE", "Croatia": "CRO", "Serbia": "SRB", "Ukraine": "UKR", "Denmark": "DEN", "Norway": "NOR",
        "Sweden": "SWE", "Poland": "POL", "Cyprus": "CYP", "Azerbaijan": "AZE", "Kazakhstan": "KAZ", "Slovakia": "SVK", "Hungary": "HUN",
        "Romania": "ROM", "Bulgaria": "BUL", "Israel": "ISR", "Slovenia": "SVN", "Moldova": "MDA", "Belarus": "BLR"}

def elo_tabella():
    try:
        rows = list(csv.DictReader(open(os.path.join(D, "clubelo.csv"), encoding="utf-8")))
    except Exception:
        return []
    return [dict(club=r["Club"], paese=r.get("Country"), elo=float(r["Elo"])) for r in rows if r.get("Elo")]

def trova_elo(tab, nome, area):
    paese = AREA.get(area or "")
    cand = [r for r in tab if r["paese"] == paese] or tab
    best = max(cand, key=lambda r: sim(nome, r["club"]), default=None)
    if best and sim(nome, best["club"]) >= 0.45: return best
    return None

def forze_campionato():
    """Per ogni squadra (id football-data.org): attacco e difesa rispetto alla media del suo campionato."""
    out = {}
    for c in CAMPIONATI:
        st = (J(f"fdorg_tab_{c}.json") or {}).get("standings") or []
        tab = next((s["table"] for s in st if s.get("type") == "TOTAL"), None)
        if not tab: continue
        gp = sum(t["playedGames"] for t in tab) or 1
        media = sum(t["goalsFor"] for t in tab) / gp
        for t in tab:
            g = t["playedGames"]
            if g < 3 or media <= 0: continue
            k = 4   # avvicina alla media: poche partite = meno fiducia
            att = (t["goalsFor"] / g * g + media * k) / (g + k) / media
            dif = (t["goalsAgainst"] / g * g + media * k) / (g + k) / media
            out[t["team"]["id"]] = dict(att=min(max(att, 0.6), 1.6), dif=min(max(dif, 0.6), 1.6), gf=t["goalsFor"] / g, camp=c)
    return out

def lambdas_elo(elo_h, elo_a, tot):
    """Gol attesi (casa, ospite) con totale 'tot' e risultato atteso Elo della squadra di casa."""
    we = 1 / (10 ** (-(elo_h + HFA - elo_a) / 400) + 1)
    lo, hi = -tot + 0.1, tot - 0.1
    for _ in range(50):
        s = (lo + hi) / 2
        mk, _ = MD.mercati(MD.matrice((tot + s) / 2, (tot - s) / 2, RHO))
        if mk["1"] + 0.5 * mk["X"] < we: lo = s
        else: hi = s
    s = (lo + hi) / 2
    return (tot + s) / 2, (tot - s) / 2, we

# ------------------------------------------------------------------ quote
def quote_fixture(fx, slug):
    eb = (fx.get("bookmakerOdds") or {}).get(slug)
    if not eb or eb.get("suspended"): return None
    mk = eb.get("markets", {}); q = {}
    for key_s, mtype, hc, per, on, _ in P.SEL:
        mid = P.mid_of(mtype, hc, per)
        if not mid or mid not in mk: continue
        for oid, o in mk[mid]["outcomes"].items():
            if P.oname(mid, oid) == on:
                p = (o.get("players") or {}).get("0") or {}
                if p.get("active", True) and p.get("price"): q[key_s] = p["price"]
    cs = {}
    cmid = P.mid_of("correctscore", 0.0, "fulltime")
    if cmid and cmid in mk:
        for oid, o in mk[cmid]["outcomes"].items():
            pz = (o.get("players") or {}).get("0") or {}; nm = P.oname(cmid, oid)
            if pz.get("price") and pz.get("active", True) and nm and ":" in nm:
                i, j = nm.split(":"); cs[(int(i), int(j))] = pz["price"]
    marc = []
    amid = next((k for k, m in P.MK.items() if m["marketType"] == "players-anytimegoalscorer"), None)
    if amid and amid in mk:
        marc = [(p["playerName"], p["price"]) for o in mk[amid]["outcomes"].values() for p in o["players"].values()
                if p.get("playerName") and p.get("price")]
    return dict(q=q, cs=cs, marc=marc)

def abbina_quote(partite, fixtures):
    """Partita football-data.org -> fixture OddsPapi: stesso orario (+-90 min) e nomi piu' simili."""
    out = {}
    for m in partite:
        t0 = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        best, bs = None, 0
        for fx in fixtures:
            try: t = datetime.fromisoformat(fx["startTime"].replace("Z", "+00:00"))
            except Exception: continue
            if abs((t - t0).total_seconds()) > 5400: continue
            s = sim(m["homeTeam"]["name"], fx.get("participant1Name", "")) + sim(m["awayTeam"]["name"], fx.get("participant2Name", ""))
            if s > bs: best, bs = fx, s
        if best and bs >= 0.8: out[m["id"]] = best
    return out

# ------------------------------------------------------------------ assenze (API-Football, Champions)
def assenze_cl():
    d = J("apif_cl_infortuni.json")
    if not d or d.get("errors"): return []
    return [dict(team=(x.get("team") or {}).get("name"), nome=(x.get("player") or {}).get("name"),
                 tipo=(x.get("player") or {}).get("type") or "", motivo=(x.get("player") or {}).get("reason") or "",
                 data=(x.get("fixture") or {}).get("date")) for x in d.get("response", [])]

def assenti_di(ASS, team, inizio):
    t0 = datetime.fromisoformat(inizio.replace("Z", "+00:00")); out = []; visti = set()
    for x in ASS:
        if not x["nome"] or x["nome"] in visti or sim(team, x["team"] or "") < 0.5: continue
        try: t = datetime.fromisoformat(x["data"].replace("Z", "+00:00"))
        except Exception: continue
        if abs((t - t0).total_seconds()) <= 36 * 3600:
            visti.add(x["nome"]); out.append(dict(nome=x["nome"], motivo=x["motivo"], dubbio="questionable" in x["tipo"].lower()))
    return out

def stesso(a, b):
    ta, tb = P._norm(a), P._norm(b)
    if not ta or not tb or ta[-1] not in tb and tb[-1] not in ta: return False
    return True

# ------------------------------------------------------------------ main
def main():
    now = datetime.now(timezone.utc)
    allm = (J("fdorg_cl.json") or {}).get("matches", [])
    pro = sorted([m for m in allm if m.get("status") in ("SCHEDULED", "TIMED") and m["homeTeam"].get("id") and m["awayTeam"].get("id")],
                 key=lambda m: m["utcDate"])
    if not pro:
        json.dump(dict(generato=now.isoformat(timespec="seconds"), stato="nessuna partita di Champions in programma", partite=[]),
                  open(os.path.join(D, "champions.json"), "w"), ensure_ascii=False); print("Champions: nessuna partita in programma"); return
    t_first = datetime.fromisoformat(pro[0]["utcDate"].replace("Z", "+00:00"))
    partite = [m for m in pro if datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")) <= t_first + timedelta(days=3)]
    md = partite[0].get("matchday"); fase = partite[0].get("stage") or ""
    giocate = [m for m in allm if m.get("status") == "FINISHED" and m.get("score", {}).get("fullTime", {}).get("home") is not None]
    gol_cl = [m["score"]["fullTime"]["home"] + m["score"]["fullTime"]["away"] for m in giocate]
    base = (sum(gol_cl) + GOL_BASE * 20) / (len(gol_cl) + 20) if gol_cl else GOL_BASE   # media gol Champions, stabilizzata
    TEAMS = {t["id"]: t for t in (J("fdorg_cl_teams.json") or {}).get("teams", [])}
    ELO = elo_tabella(); FORZE = forze_campionato(); ASS = assenze_cl()
    fixtures = J("oddspapi_cl.json") or []
    if isinstance(fixtures, dict): fixtures = fixtures.get("data") or []
    ABB = abbina_quote(partite, fixtures)
    out = []
    for m in partite:
        h, a = m["homeTeam"], m["awayTeam"]
        th, ta = TEAMS.get(h["id"], {}), TEAMS.get(a["id"], {})
        nh, na = h.get("shortName") or h["name"], a.get("shortName") or a["name"]
        dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(ROME)
        eh, ea = trova_elo(ELO, h["name"], (th.get("area") or {}).get("name")), trova_elo(ELO, a["name"], (ta.get("area") or {}).get("name"))
        rec = dict(id=m["id"], data=m["utcDate"], giorno=dt.strftime("%Y-%m-%d"), casa=nh, ospite=na, crest=[h.get("crest"), a.get("crest")],
                   tla=[h.get("tla") or nh[:3].upper(), a.get("tla") or na[:3].upper()],
                   assenze={nh: assenti_di(ASS, h["name"], m["utcDate"]), na: assenti_di(ASS, a["name"], m["utcDate"])})
        if not eh or not ea:
            rec["avvisi"] = ["forza Elo non trovata per una delle due squadre: nessun pronostico"]; out.append(rec); continue
        fh, fa = FORZE.get(h["id"], {}), FORZE.get(a["id"], {})
        tot = base * ((fh.get("att", 1) * fa.get("dif", 1)) + (fa.get("att", 1) * fh.get("dif", 1))) / 2
        lh, la, we = lambdas_elo(eh["elo"], ea["elo"], tot)
        M = MD.matrice(lh, la, RHO); mk, ris = MD.mercati(M); mk.update(MD.primo_tempo(lh, la))
        rec.update(elo=[round(eh["elo"]), round(ea["elo"])], elo_club=[eh["club"], ea["club"]], lam=[round(lh, 2), round(la, 2)],
                   risultato_modello=ris[0][1], p={k: round(v, 4) for k, v in mk.items()},
                   campionato=[fh.get("camp"), fa.get("camp")])
        fx = ABB.get(m["id"])
        qe = quote_fixture(fx, "eurobet.it") if fx else None
        qp = quote_fixture(fx, "pinnacle") if fx else None
        if not qe or not all(k in qe["q"] for k in ("1", "X", "2")):
            rec["avvisi"] = ["quote Eurobet NON VERIFICATE: nessun pronostico"]; out.append(rec); continue
        q = qe["q"]; pk = MD.no_vig([q["1"], q["X"], q["2"]]); marg = sum(1 / q[k] for k in ("1", "X", "2")) - 1
        rec["p_mercato"] = dict(zip("1X2", [round(x, 4) for x in pk]))
        if "O2.5" in q and "U2.5" in q: rec["p_mercato"]["O2.5"] = round(MD.no_vig([q["O2.5"], q["U2.5"]])[0], 4)
        if "GG" in q and "NG" in q: rec["p_mercato"]["GG"] = round(MD.no_vig([q["GG"], q["NG"]])[0], 4)
        ppin = P.prob_pinnacle(qp["q"]) if qp else {}
        sel = []
        for k, lab in P.LABEL.items():
            if k in mk and k in q:
                p = mk[k]; o = q[k]
                sel.append(dict(k=k, label=lab, p=round(p, 4), quota=o, p_impl=round(1 / o, 4), ev=round(p * o - 1, 4), ht=k.startswith("HT")))
        tutte = dict(MD.combo(M))
        CE = P.combo_da_esatti(qe.get("cs", {}), marg * P.FATTORE_MARGINE_COMBO)
        for n, pp in sorted(tutte.items(), key=lambda x: -x[1]):
            if not (0.15 <= pp <= 0.90) or not P.esito_ok(n, mk["1"], mk["2"]) or P.ridondante(n, pp, tutte) or n not in CE: continue
            o = CE[n][1]
            sel.append(dict(k="C:" + n, label=n, p=round(pp, 4), quota=o, p_impl=round(1 / o, 4), ev=round(pp * o - 1, 4), ht=False,
                            fonte="stimata", p_mercato=round(CE[n][0], 4)))
        for s in sel:
            if s["k"] in ppin: s["p_pin"] = round(ppin[s["k"]], 4)
            s["cat"] = P.categoria(s)
        rec["p_pin"] = {k: round(ppin[k], 4) for k in ("1", "X", "2", "O2.5", "GG") if k in ppin}
        rec["selezioni"] = sel; rec["pronostico"] = P.pronostico(sel); rec["avvisi"] = []
        rec["_marc"] = qe.get("marc", [])
        out.append(rec)

    # ------------------------------------------------ triple: 3 per giorno di gioco (semplice, media, aggressiva)
    TIPI = [("semplice", 0.66, -0.07, 1.80, 2.80), ("media", 0.42, -0.08, 3.00, 5.50), ("aggressiva", 0.25, -0.12, 6.00, 15.0)]
    triple = {}
    for giorno in sorted({r["giorno"] for r in out if r.get("selezioni")}):
        rr = [r for r in out if r["giorno"] == giorno and r.get("selezioni")]
        if len(rr) < 3: continue
        usate = set(); triple[giorno] = {}
        for tipo, pmin, evmin0, qlo, qhi in TIPI:
            best = None
            for evmin in (evmin0, evmin0 - 0.10, -1.0):
                if best: break
                cs = [dict(s, match=f'{r["casa"]}-{r["ospite"]}', mid=r["id"]) for r in rr for s in r["selezioni"]
                      if not s["ht"] and s["p"] >= pmin and s["ev"] >= evmin and s["quota"] >= 1.12 and (r["id"], s["k"]) not in usate]
                if tipo == "aggressiva": cs = [c for c in cs if c["k"].startswith("C:") and 1.80 <= c["quota"] <= 4.00]
                cs = sorted(cs, key=lambda c: -c["p"])[:60]
                for combo in itertools.combinations(cs, 3):
                    if len({c["mid"] for c in combo}) < 3: continue
                    if any(not P.compatibili([k for (m2, k) in usate if m2 == c["mid"]] + [c["k"]]) for c in combo): continue
                    qt = math.prod(c["quota"] for c in combo)
                    if not (qlo <= qt <= qhi): continue
                    pj = math.prod(c["p"] for c in combo); ev = pj * qt - 1
                    pen = 0.0 if P.CALIBRATA else 0.04 * sum(1 for c in combo if c.get("fonte") == "stimata")
                    score = (pj - pen / 4, ev - pen) if tipo == "semplice" else (ev - pen, pj)
                    if best is None or score > best[0]: best = (score, combo, qt, pj, ev)
            if best:
                _, combo, qt, pj, ev = best
                for c in combo: usate.add((c["mid"], c["k"]))
                triple[giorno][tipo] = dict(selezioni=list(combo), quota=round(qt, 2), p=round(pj, 4), ev=round(ev, 4))
            else:
                triple[giorno][tipo] = None

    # ------------------------------------------------ marcatori: 4 per giornata
    gioc = {}
    for f in ["fdorg_cl_marcatori.json"] + [f"fdorg_marc_{c}.json" for c in CAMPIONATI]:
        for s in (J(f) or {}).get("scorers", []):
            pid = (s.get("player") or {}).get("id")
            if not pid: continue
            g = gioc.setdefault(pid, dict(nome=s["player"]["name"], team=(s.get("team") or {}).get("id"), gol=0, partite=0))
            g["gol"] += s.get("goals") or 0; g["partite"] += s.get("playedMatches") or 0
    righe = []
    for r in out:
        if not r.get("lam") or not r.get("selezioni"): continue
        m = next(x for x in partite if x["id"] == r["id"])
        for side, tid, team, opp in ((0, m["homeTeam"]["id"], r["casa"], r["ospite"]), (1, m["awayTeam"]["id"], r["ospite"], r["casa"])):
            media_sq = FORZE.get(tid, {}).get("gf") or (base / 2)
            fatt = r["lam"][side] / media_sq
            for g in gioc.values():
                if g["team"] != tid or g["partite"] < 3: continue
                rate = (g["gol"] + 0.25 * 3) / (g["partite"] + 3)            # gol a partita, avvicinati alla media (0,25)
                if any(stesso(x["nome"], g["nome"]) and not x["dubbio"] for x in r["assenze"].get(team, [])): continue
                pr = 1 - math.exp(-rate * fatt)
                quota = next((pz for n, pz in r.get("_marc", []) if stesso(n, g["nome"])), None)
                if not quota: continue                                          # senza quota Eurobet: probabile assente
                righe.append(dict(nome=g["nome"], squadra=team, avversario=opp, match=f'{r["casa"]}-{r["ospite"]}', mid=r["id"],
                                  gol=g["gol"], partite=g["partite"], p=round(pr, 4), quota=quota, ev=round(pr * quota - 1, 4)))
    righe.sort(key=lambda x: -x["p"])
    visti = set(); righe = [x for x in righe if not (x["nome"] in visti or visti.add(x["nome"]))]
    marcatori = righe[:4]
    for r in out: r.pop("_marc", None)
    res = dict(generato=now.isoformat(timespec="seconds"), giornata=md, fase=fase, partite=out, triple=triple,
               marcatori=dict(lista=marcatori, altri=righe[4:14]), gol_medi_cl=round(base, 2), hfa=HFA)
    json.dump(res, open(os.path.join(D, "champions.json"), "w"), ensure_ascii=False, indent=1)
    # istantanea dei marcatori di Champions: serve a verificare chi ha segnato (confronto prima/dopo)
    snap = {str((s.get("player") or {}).get("id")): dict(nome=s["player"]["name"], gol=s.get("goals") or 0)
            for s in (J("fdorg_cl_marcatori.json") or {}).get("scorers", [])}
    if os.environ.get("REGISTRA", "1") != "0":
        json.dump(dict(creato=now.isoformat(timespec="seconds"), giocatori=snap,
                       completa=len(snap) < 100), open(os.path.join(D, "cl_marcatori_prima.json"), "w"), ensure_ascii=False)
        registra(res, now)
    print(f"Champions giornata {md}: {len(out)} partite, {sum(1 for r in out if r.get('pronostico'))} pronostici, "
          f"triple {sum(1 for g in triple.values() for t in g.values() if t)}, marcatori {len(marcatori)}")

def registra(res, now):
    db = sqlite3.connect(os.path.join(D, "storico.sqlite"))
    db.execute("""CREATE TABLE IF NOT EXISTS previsioni(id INTEGER PRIMARY KEY, creato TEXT, giornata INT, match_id INT, partita TEXT,
                  inizio TEXT, mercato TEXT, quota REAL, p_modello REAL, ev REAL, tipo TEXT, gruppo TEXT, esito INT, profitto REAL)""")
    if "quota_chiusura" not in [c[1] for c in db.execute("PRAGMA table_info(previsioni)")]:
        db.execute("ALTER TABLE previsioni ADD COLUMN quota_chiusura REAL")
    g = 100 + (res["giornata"] or 0)          # giornate Champions: 101, 102, ... (separate dalla Serie A)
    start = {r["id"]: r["data"] for r in res["partite"]}
    def ins(mid, partita, s, tipo, gruppo):
        if start[mid].replace("Z", "+00:00") <= now.isoformat(): return
        if db.execute("SELECT 1 FROM previsioni WHERE match_id=? AND mercato=? AND tipo=? AND gruppo=?", (mid, s["k"], tipo, gruppo)).fetchone(): return
        db.execute("INSERT INTO previsioni(creato,giornata,match_id,partita,inizio,mercato,quota,p_modello,ev,tipo,gruppo) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (now.isoformat(timespec="seconds"), g, mid, partita, start[mid], s["k"], s["quota"], s["p"], s["ev"], tipo, gruppo))
    for r in res["partite"]:
        if r.get("pronostico"): ins(r["id"], f'{r["casa"]}-{r["ospite"]}', r["pronostico"], "cl_pronostico", "")
    for giorno, tt in res["triple"].items():
        for tipo, t in tt.items():
            if t:
                for s in t["selezioni"]: ins(s["mid"], s["match"], s, f"cl_tripla_{tipo}", giorno)
    for x in res["marcatori"]["lista"]:
        ins(x["mid"], x["match"], dict(k="SCORER:" + x["nome"], quota=x["quota"], p=x["p"], ev=x["ev"]), "cl_marcatore", "")
    db.commit(); db.close()

if __name__ == "__main__":
    main()
