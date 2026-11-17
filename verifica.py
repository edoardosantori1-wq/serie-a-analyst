#!/usr/bin/env python3
"""Verifica dei pronostici dopo le partite e bilancio (puntata virtuale di 1 unita' per giocata).
Legge dati/storico.sqlite (le previsioni non vengono mai modificate: si aggiungono solo esito e profitto)
e i risultati finali di football-data.org; scrive dati/bilancio.json per il sito."""
import json, os, sqlite3, re, unicodedata
from datetime import datetime, timezone
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
        e, g = mercato[2:].split(" + ", 1)
        if e in ESITI and g in GOL: return int(ESITI[e](i, j) and GOL[g](i, j))
    return None

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z]+", s) if t]

def marcatori_partita(match_id):
    """Nomi dei marcatori (esclusi autogol) dal dettaglio partita salvato in dati/partite/<id>.json, se presente."""
    j = J(os.path.join("partite", f"{match_id}.json"))
    if not j: return None
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

def main():
    dbp = os.path.join(D, "storico.sqlite")
    if not os.path.exists(dbp):
        json.dump(dict(aggiornato=None, giocate=[]), open(os.path.join(D, "bilancio.json"), "w")); return
    db = sqlite3.connect(dbp)
    fin = {m["id"]: (m["score"]["fullTime"]["home"], m["score"]["fullTime"]["away"])
           for m in (J("fdorg_giocate.json") or {}).get("matches", []) if m.get("score", {}).get("fullTime", {}).get("home") is not None}
    for rid, mid, mercato, quota in db.execute("SELECT id, match_id, mercato, quota FROM previsioni WHERE esito IS NULL").fetchall():
        if mid not in fin: continue
        i, j = fin[mid]
        if mercato.startswith("SCORER:"):
            nomi = marcatori_partita(mid)
            if nomi is None: continue          # dettaglio non ancora scaricato
            pt = _norm(mercato[7:])
            e = int(any(pt and pt[-1] in _norm(n) for n in nomi))
        else:
            e = esito(mercato, i, j)
        if e is None and mercato in ("DNB1", "DNB2"):
            db.execute("UPDATE previsioni SET esito=?, profitto=? WHERE id=?", (2, 0.0, rid)); continue   # 2 = rimborsata
        if e is None: continue
        db.execute("UPDATE previsioni SET esito=?, profitto=? WHERE id=?", (e, round(quota - 1, 3) if e else -1.0, rid))
    db.commit()
    rows = [dict(zip(("creato", "giornata", "match_id", "partita", "inizio", "mercato", "quota", "p", "ev", "tipo", "gruppo", "esito", "profitto"), r))
            for r in db.execute("SELECT creato, giornata, match_id, partita, inizio, mercato, quota, p_modello, ev, tipo, gruppo, esito, profitto FROM previsioni ORDER BY inizio")]
    db.close()
    # le triple si valutano come schedina unica: vinta solo se vincono tutte e tre (rimborso = quota 1)
    giocate = []
    triple = {}
    for r in rows:
        r["risultato"] = "{}-{}".format(*fin[r["match_id"]]) if r["match_id"] in fin else None
        if r["tipo"].startswith("tripla_"):
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
        giocate.append(dict(cat=tipo, giornata=g, desc=f"{tipo.replace('tripla_', 'Tripla ')} {gr}", mercato=" · ".join(f'{s["partita"]}: {s["mercato"]}' for s in sel),
                            quota=round(q_tot, 2), p=None, esito=e, profitto=prof, inizio=max(s["inizio"] for s in sel),
                            dettaglio=[dict(partita=s["partita"], mercato=s["mercato"], esito=s["esito"], risultato=s["risultato"]) for s in sel]))
    giocate.sort(key=lambda x: x["inizio"], reverse=True)
    def riepilogo(lst):
        chiuse = [x for x in lst if x["esito"] in (0, 1)]
        v = sum(1 for x in chiuse if x["esito"] == 1); prof = sum(x["profitto"] or 0 for x in lst if x["esito"] in (0, 1, 2))
        n = len([x for x in lst if x["esito"] in (0, 1, 2)])
        return dict(giocate=n, vinte=v, perse=len(chiuse) - v, aperte=len([x for x in lst if x["esito"] is None]),
                    hit=round(v / len(chiuse), 4) if chiuse else None, unita=round(prof, 2), roi=round(prof / n, 4) if n else None)
    CAT = [("pronostico", "Pronostici partita"), ("tripla_semplice", "Triple semplici"), ("tripla_media", "Triple medie"),
           ("tripla_aggressiva", "Triple aggressive"), ("marcatore", "Marcatori"), ("singola", "Singole")]
    out = dict(aggiornato=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               totale=riepilogo(giocate), categorie=[dict(cat=c, nome=n, **riepilogo([x for x in giocate if x["cat"] == c])) for c, n in CAT],
               giornate=[dict(giornata=g, **riepilogo([x for x in giocate if x["giornata"] == g])) for g in sorted({x["giornata"] for x in giocate}, reverse=True)],
               giocate=giocate[:120])
    json.dump(out, open(os.path.join(D, "bilancio.json"), "w"), ensure_ascii=False, indent=1)
    print(f"Bilancio: {out['totale']}")

if __name__ == "__main__":
    main()
