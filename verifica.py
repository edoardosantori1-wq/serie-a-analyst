#!/usr/bin/env python3
"""Verifica dei pronostici dopo le partite e bilancio (puntata virtuale di 1 unita' per giocata).
Legge dati/storico.sqlite (le previsioni non vengono mai modificate: si aggiungono solo esito e profitto)
e i risultati finali di football-data.org; scrive dati/bilancio.json per il sito."""
import json, os, sqlite3, re, unicodedata
from datetime import datetime, timezone, timedelta
BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati")

def J(n):
    try: return json.load(open(os.path.join(D, n)))
    except Exception: return None

ESITI = {"1": lambda i, j: i > j, "X": lambda i, j: i == j, "2": lambda i, j: i < j,
         "1X": lambda i, j: i >= j, "X2": lambda i, j: i <= j, "12": lambda i, j: i != j}
GOL = {"Over 1.5": lambda i, j: i + j >= 2, "Under 3.5": lambda i, j: i + j <= 3, "Over 2.5": lambda i, j: i + j >= 3,
       "Under 2.5": lambda i, j: i + j <= 2, "Goal": lambda i, j: i > 0 and j > 0, "No Goal": lambda i, j: i == 0 or j == 0}

def esito(mercato, i, j):
    """1 vinta, 0 persa, None rimborsata (Draw No Bet con pareggio) o non valutabile."""
    if mercato in ESITI: return int(ESITI[mercato](i, j))
    if mercato == "DNB1": return None if i == j else int(i > j)
    if mercato == "DNB2": return None if i == j else int(j > i)
    if mercato == "GG": return int(i > 0 and j > 0)
    if mercato == "NG": return int(i == 0 or j == 0)
    m = re.fullmatch(r"([OU])(\d\.5)", mercato)
    if m: t = float(m.group(2)); return int(i + j > t) if m.group(1) == "O" else int(i + j < t)
    m = re.fullmatch(r"([HA])_O(\d\.5)", mercato)
    if m: t = float(m.group(2)); return int((i if m.group(1) == "H" else j) > t)
    if mercato.startswith("C:"):
        parti = mercato[2:].split(" + ")
        GG2 = {"Goal": i > 0 and j > 0, "No Goal": i == 0 or j == 0}
        def cond(c):
            if c in ESITI: return ESITI[c](i, j)
            if c in GG2: return GG2[c]
            mm = re.fullmatch(r"(Over|Under) (\d\.5)", c)
            if mm: return (i + j > float(mm.group(2))) if mm.group(1) == "Over" else (i + j < float(mm.group(2)))
            return None
        vals = [cond(c) for c in parti]
        if None not in vals: return int(all(vals))
    return None

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z]+", s) if t]

def segnato_cl(nome, inizio):
    """Champions: chi ha segnato si ricava confrontando la classifica marcatori (football-data.org) prima e dopo la giornata.
    1 = ha segnato, 0 = non ha segnato, None = non verificabile con certezza (la giocata resta aperta)."""
    prima = J("cl_marcatori_prima.json") or {}; dopo = (J("fdorg_cl_marcatori.json") or {}).get("scorers", [])
    if not prima or not dopo: return None
    agg = (J("meta.json") or {}).get("fdorg_cl_marcatori.json")
    fine = datetime.fromisoformat(inizio.replace("Z", "+00:00")) + timedelta(hours=3)
    if not agg or datetime.fromisoformat(agg) < fine: return None      # classifica marcatori non ancora aggiornata
    pt = _norm(nome)
    def gol(lista):
        for x in lista:
            if pt and pt[-1] in _norm(x["nome"]): return x["gol"]
        return None
    g0 = gol(prima.get("giocatori", {}).values())
    g1 = gol([dict(nome=s["player"]["name"], gol=s.get("goals") or 0) for s in dopo])
    if g1 is not None and (g0 or 0) < g1: return 1
    if g1 is not None and g0 is not None and g1 == g0: return 0
    if g1 is None and len(dopo) < 100: return 0       # lista completa e lui non c'e': non ha segnato
    return None

def marcatori_partita(match_id, gol_totali=None):
    """Nomi dei marcatori (esclusi autogol) dal dettaglio partita salvato in dati/partite/<id>.json, se presente."""
    j = J(os.path.join("partite", f"{match_id}.json"))
    if not j: return None
    data = j.get("data", j) if isinstance(j, dict) else {}
    ev = data.get("key_events") if isinstance(data, dict) else None
    if isinstance(ev, list):
        # formato StrikerAPI get_game: key_events [{type: "goal", player, own_goal, ...}] + players [{name, goals}]
        gol = [e for e in ev if str(e.get("type", "")).lower() == "goal" and not e.get("shootout")]
        nomi = [e.get("player") for e in gol if not e.get("own_goal") and e.get("player")]
        nomi += [p.get("name") for p in data.get("players", []) if (p.get("goals") or 0) > 0 and p.get("name")]
        # dettaglio incompleto (scaricato troppo presto): i gol registrati non tornano col risultato finale
        if gol_totali is not None and len(gol) < gol_totali:
            try: os.remove(os.path.join(D, "partite", f"{match_id}.json"))     # verra' riscaricato
            except OSError: pass
            return None
        return nomi
    nomi = []
    def walk(o):
        if isinstance(o, dict):
            tipo = str(o.get("type") or o.get("event_type") or o.get("kind") or "").lower()
            if "goal" in tipo and "own" not in tipo:
                for k in ("player", "scorer", "player_name", "name"):
                    v = o.get(k)
                    if isinstance(v, dict): v = v.get("name")
                    if isinstance(v, str): nomi.append(v); break
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(j)
    return nomi

# ------------------------------------------------------------ confronto con Pengwin (giocate inserite a mano)
def giocata_key(t):
    """Testo della giocata (come la scrive il tipster) -> chiave dei nostri mercati. None se non riconosciuta."""
    t = re.sub(r"\s+", " ", (t or "").strip().upper().replace(",", "."))
    if not t: return None
    if "+" in t:
        parti = []
        for p in [x.strip() for x in t.split("+")]:
            k = giocata_key(p)
            if k in ESITI: parti.append(k)
            elif k == "GG": parti.append("Goal")
            elif k == "NG": parti.append("No Goal")
            elif k and re.fullmatch(r"[OU]\d\.5", k): parti.append(("Over " if k[0] == "O" else "Under ") + k[1:])
            else: return None
        return "C:" + " + ".join(parti)
    alias = {"2X": "X2", "X1": "1X", "21": "12", "GOAL": "GG", "GOL": "GG", "GG": "GG", "SI GOAL": "GG", "NO GOAL": "NG",
             "NOGOAL": "NG", "NO GOL": "NG", "NG": "NG", "1": "1", "X": "X", "2": "2", "1X": "1X", "X2": "X2", "12": "12"}
    if t in alias: return alias[t]
    m = re.fullmatch(r"(OVER|UNDER|OV|UN|O|U) ?(\d)(?:\.5)?", t)
    if m: return ("O" if m.group(1).startswith("O") else "U") + m.group(2) + ".5"
    return None

def pengwin(fin_matches):
    """dati/pengwin.csv: schedina;data;partita;giocata;quota;esito  (separatore ;)
    Righe con lo stesso numero di schedina = una multipla. esito (V/P/R) serve solo per mercati che il
    sistema non sa valutare (es. angoli); altrimenti l'esito si calcola dal risultato finale."""
    import csv
    path = os.path.join(D, "pengwin.csv")
    if not os.path.exists(path): return []
    try:
        from predizioni import canon
    except Exception:
        canon = lambda x: x
    righe = list(csv.DictReader(open(path, encoding="utf-8-sig"), delimiter=";"))
    sched = {}
    for n, r in enumerate(righe):
        sid = (r.get("schedina") or "").strip() or f"_{n}"
        sched.setdefault(sid, []).append(r)
    out = []
    for sid, sel in sched.items():
        esiti, quota, inizio, dett = [], 1.0, "", []
        for r in sel:
            try: q = float((r.get("quota") or "").replace(",", "."))
            except ValueError: q = 1.0
            quota *= q
            d = (r.get("data") or "").strip()
            try: dd = datetime.strptime(d, "%d/%m/%Y") if "/" in d else datetime.strptime(d[:10], "%Y-%m-%d")
            except ValueError: dd = None
            inizio = max(inizio, dd.strftime("%Y-%m-%d") if dd else "")
            man = (r.get("esito") or "").strip().upper()[:1]
            e = {"V": 1, "P": 0, "R": 2}.get(man)
            ris = None
            if e is None:
                pp = re.split(r"\s*[-–]\s*", r.get("partita") or "", maxsplit=1)
                h = canon(pp[0].strip()); a = canon(pp[1].strip()) if len(pp) > 1 else None
                k = giocata_key(r.get("giocata"))
                m = next((m for m in fin_matches if canon(m["homeTeam"]["name"]) == h and canon(m["awayTeam"]["name"]) == a
                          and (dd is None or abs((datetime.fromisoformat(m["utcDate"][:10]) - dd).days) <= 3)), None)
                if m and k:
                    i, j = m["score"]["fullTime"]["home"], m["score"]["fullTime"]["away"]; ris = f"{i}-{j}"
                    e = esito(k, i, j)
            esiti.append(e)
            dett.append(dict(partita=r.get("partita"), mercato=r.get("giocata"), esito=e, risultato=ris))
        if any(x == 0 for x in esiti): e, prof = 0, -1.0
        elif all(x in (1, 2) for x in esiti):
            q = 1.0
            for r, x in zip(sel, esiti):
                if x == 1: q *= float((r.get("quota") or "1").replace(",", "."))
            e, prof = (2, 0.0) if all(x == 2 for x in esiti) else (1, round(q - 1, 3))
        else: e, prof = None, None
        out.append(dict(cat="pengwin", desc=" · ".join(f'{d["partita"]}: {d["mercato"]}' for d in dett), quota=round(quota, 2),
                        esito=e, profitto=prof, inizio=inizio, dettaglio=dett if len(dett) > 1 else None,
                        risultato=dett[0]["risultato"] if len(dett) == 1 else None, mercato=dett[0]["mercato"] if len(dett) == 1 else "multipla"))
    out.sort(key=lambda x: x["inizio"], reverse=True)
    return out

def main():
    dbp = os.path.join(D, "storico.sqlite")
    if not os.path.exists(dbp):
        json.dump(dict(aggiornato=None, giocate=[]), open(os.path.join(D, "bilancio.json"), "w")); return
    db = sqlite3.connect(dbp)
    tutte_m = (J("fdorg_giocate.json") or {}).get("matches", []) + (J("fdorg_cl.json") or {}).get("matches", [])
    fin = {m["id"]: (m["score"]["fullTime"]["home"], m["score"]["fullTime"]["away"])
           for m in tutte_m if m.get("status") == "FINISHED" and m.get("score", {}).get("fullTime", {}).get("home") is not None}
    cl_ids = {m["id"] for m in (J("fdorg_cl.json") or {}).get("matches", [])}
    for rid, mid, mercato in db.execute("SELECT id, match_id, mercato FROM previsioni WHERE esito=0 AND mercato LIKE 'SCORER:%'").fetchall():
        if mid in fin and mid not in cl_ids:
            nomi = marcatori_partita(mid, sum(fin[mid]))
            pt = _norm(mercato[7:])
            if nomi is None:
                db.execute("UPDATE previsioni SET esito=NULL, profitto=NULL WHERE id=?", (rid,))      # da riverificare
            elif any(pt and pt[-1] in _norm(n) for n in nomi):
                db.execute("UPDATE previsioni SET esito=NULL, profitto=NULL WHERE id=?", (rid,))      # aveva segnato: si ricalcola
    for rid, mid, mercato, quota, inizio in db.execute("SELECT id, match_id, mercato, quota, inizio FROM previsioni WHERE esito IS NULL").fetchall():
        if mid not in fin: continue
        i, j = fin[mid]
        if mercato.startswith("SCORER:") and mid in cl_ids:
            e = segnato_cl(mercato[7:], inizio)
            if e is None: continue
        elif mercato.startswith("SCORER:"):
            nomi = marcatori_partita(mid, i + j)
            if nomi is None: continue          # dettaglio non ancora scaricato o incompleto
            pt = _norm(mercato[7:])
            e = int(any(pt and pt[-1] in _norm(n) for n in nomi))
        else:
            e = esito(mercato, i, j)
        if e is None and mercato in ("DNB1", "DNB2"):
            db.execute("UPDATE previsioni SET esito=?, profitto=? WHERE id=?", (2, 0.0, rid)); continue   # 2 = rimborsata
        if e is None: continue
        db.execute("UPDATE previsioni SET esito=?, profitto=? WHERE id=?", (e, round(quota - 1, 3) if e else -1.0, rid))
    db.commit()
    if "quota_chiusura" not in [c[1] for c in db.execute("PRAGMA table_info(previsioni)")]:
        db.execute("ALTER TABLE previsioni ADD COLUMN quota_chiusura REAL")
    rows = [dict(zip(("creato", "giornata", "match_id", "partita", "inizio", "mercato", "quota", "p", "ev", "tipo", "gruppo", "esito", "profitto", "chiusura"), r))
            for r in db.execute("SELECT creato, giornata, match_id, partita, inizio, mercato, quota, p_modello, ev, tipo, gruppo, esito, profitto, quota_chiusura FROM previsioni ORDER BY inizio")]
    db.close()
    # le triple si valutano come schedina unica: vinta solo se vincono tutte e tre (rimborso = quota 1)
    giocate = []
    triple = {}
    for r in rows:
        r["risultato"] = "{}-{}".format(*fin[r["match_id"]]) if r["match_id"] in fin else None
        if "tripla_" in r["tipo"]:
            triple.setdefault((r["giornata"], r["tipo"], r["gruppo"]), []).append(r)
        else:
            giocate.append(dict(cat=r["tipo"], giornata=r["giornata"], desc=r["partita"], mercato=r["mercato"], quota=r["quota"], p=r["p"],
                                esito=r["esito"], profitto=r["profitto"], inizio=r["inizio"], risultato=r["risultato"]))
    for (g, tipo, gr), sel in triple.items():
        if any(s["esito"] == 0 for s in sel): e, prof = 0, -1.0
        elif all(s["esito"] in (1, 2) for s in sel):
            q = 1.0
            for s in sel: q *= s["quota"] if s["esito"] == 1 else 1.0
            e, prof = 1, round(q - 1, 3)
        else: e, prof = None, None
        q_tot = 1.0
        for s in sel: q_tot *= s["quota"]
        giocate.append(dict(cat=tipo, giornata=g, desc=("Champions · " if tipo.startswith("cl_") else "") + f"{tipo.replace('cl_', '').replace('tripla_', 'Tripla ')} {gr}", mercato=" · ".join(f'{s["partita"]}: {s["mercato"]}' for s in sel),
                            quota=round(q_tot, 2), p=None, esito=e, profitto=prof, inizio=max(s["inizio"] for s in sel),
                            dettaglio=[dict(partita=s["partita"], mercato=s["mercato"], esito=s["esito"], risultato=s["risultato"]) for s in sel]))
    giocate.sort(key=lambda x: x["inizio"], reverse=True)
    # quote battute: per ogni selezione distinta (partita + mercato) con quota reale di chiusura
    sel = {}
    for r in rows:
        if r["chiusura"]: sel[(r["match_id"], r["mercato"])] = (r["quota"], r["chiusura"], r["giornata"])
    def clv(items):
        if not items: return None
        battute = sum(1 for q, c, _ in items if q > c + 1e-9); pari = sum(1 for q, c, _ in items if abs(q - c) < 1e-9)
        return dict(n=len(items), battute=battute, pari=pari, peggiori=len(items) - battute - pari,
                    medio=round(sum(q / c - 1 for q, c, _ in items) / len(items), 4))
    def riepilogo(lst):
        chiuse = [x for x in lst if x["esito"] in (0, 1)]
        v = sum(1 for x in chiuse if x["esito"] == 1); prof = sum(x["profitto"] or 0 for x in lst if x["esito"] in (0, 1, 2))
        n = len([x for x in lst if x["esito"] in (0, 1, 2)])
        return dict(giocate=n, vinte=v, perse=len(chiuse) - v, aperte=len([x for x in lst if x["esito"] is None]),
                    hit=round(v / len(chiuse), 4) if chiuse else None, unita=round(prof, 2), roi=round(prof / n, 4) if n else None)
    CAT = [("pronostico", "Pronostici partita"), ("tripla_semplice", "Triple semplici"), ("tripla_media", "Triple medie"),
           ("tripla_aggressiva", "Triple aggressive"), ("marcatore", "Marcatori"), ("singola", "Singole"), ("value", "Value bet"),
           ("cl_pronostico", "Champions · pronostici"), ("cl_tripla_semplice", "Champions · triple semplici"), ("cl_tripla_media", "Champions · triple medie"),
           ("cl_tripla_aggressiva", "Champions · triple aggressive"), ("cl_marcatore", "Champions · marcatori")]
    out = dict(aggiornato=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               totale=riepilogo(giocate), categorie=[dict(cat=c, nome=n, **riepilogo([x for x in giocate if x["cat"] == c])) for c, n in CAT],
               giornate=[dict(giornata=g, **riepilogo([x for x in giocate if x["giornata"] == g])) for g in sorted({x["giornata"] for x in giocate}, reverse=True)],
               giocate=giocate[:400], clv=clv(list(sel.values())),
               clv_giornate={g: clv([x for x in sel.values() if x[2] == g]) for g in sorted({x[2] for x in sel.values()})})
    PG = pengwin((J("fdorg_giocate.json") or {}).get("matches", []))
    if PG:
        dal = min(x["inizio"] for x in PG if x["inizio"]) if any(x["inizio"] for x in PG) else ""
        noi = [x for x in giocate if (x["inizio"] or "")[:10] >= dal]
        # test interno: NON va nel bilancio del sito, ma in un file a parte
        json.dump(dict(aggiornato=datetime.now(timezone.utc).isoformat(timespec="seconds"), dal=dal, pengwin=riepilogo(PG),
                       noi_pronostici=riepilogo([x for x in noi if x["cat"] == "pronostico"]), noi_tutto=riepilogo(noi), giocate_pengwin=PG),
                  open(os.path.join(D, "confronto_pengwin.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(out, open(os.path.join(D, "bilancio.json"), "w"), ensure_ascii=False, indent=1)
    print(f"Bilancio: {out['totale']}")

if __name__ == "__main__":
    main()
