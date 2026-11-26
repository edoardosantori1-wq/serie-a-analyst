#!/usr/bin/env python3
"""Value bet tra i bookmaker italiani (licenza ADM), con Pinnacle come riferimento della quota "giusta".

Per ogni partita della giornata e ogni mercato principale (1X2, doppia chance, Goal/No Goal, Over/Under):
  - probabilita' "giusta" = quote Pinnacle senza margine (il bookmaker piu' preciso: non ci si gioca, fa da termometro);
  - si cerca il bookmaker italiano che paga di piu' quell'esito;
  - e' un errore di quota (value bet) se  quota x probabilita' giusta - 1  >= 3%
  - DOPPIA CONFERMA: anche il nostro modello (analisi delle squadre) deve dire che la quota conviene
    (quota x probabilita' del modello >= 1). Se modello e Pinnacle non sono d'accordo, la giocata si scarta.
Al massimo una giocata per partita (la migliore): giocate sulla stessa partita sono legate tra loro.
Puntata suggerita: frazione di Kelly (1/4), poi divisa in proporzione sul budget che l'utente imposta nel sito.
Ogni value bet viene registrata nello storico (tipo 'value') alla quota trovata, e verificata a fine partita.
Scrive dati/valuebet.json. Nessuna quota inventata: se Pinnacle o i bookmaker non quotano un mercato, si salta.
"""
import json, os, sqlite3
from datetime import datetime, timezone, timedelta
import predizioni as P

D = P.D
BOOKS = {"eurobet.it": "Eurobet", "sisal.it": "Sisal", "snai.it": "Snai", "goldbet.it": "Goldbet",
         "lottomatica.it": "Lottomatica", "bet365.it": "bet365", "betflag.it": "BetFlag", "planetwin365.it": "Planetwin365",
         "admiralbet.it": "AdmiralBet", "netbet.it": "NetBet", "888sport.it": "888sport", "pokerstars.it": "PokerStars",
         "leovegas.it": "LeoVegas", "quigioco.it": "Quigioco"}
MERCATI = ["1", "X", "2", "1X", "X2", "12", "GG", "NG", "O1.5", "U1.5", "O2.5", "U2.5", "O3.5", "U3.5"]
EV_MIN = 0.03        # almeno +3% rispetto alla quota giusta
QUOTA_MAX = 5.0      # niente quote troppo alte: lì gli "errori" sono spesso solo rumore
KELLY = 0.25         # un quarto di Kelly: puntate prudenti

def main():
    now = datetime.now(timezone.utc)
    raw = P.J("oddspapi_quote.json") or []
    inizio = {(P.canon(f.get("participant1Name")), P.canon(f.get("participant2Name"))): f.get("startTime") for f in raw}
    pin = P.quote_bookmaker("pinnacle")
    libri = {slug: P.quote_bookmaker(slug) for slug in BOOKS}
    presenti = [BOOKS[s] for s, q in libri.items() if q]
    prossime = {(P.canon(m["homeTeam"]["name"]), P.canon(m["awayTeam"]["name"])): m
                for m in (P.J("fdorg_prossime.json") or {}).get("matches", [])}
    # probabilita' del nostro modello (pronostici.json della giornata, scritto da predizioni.py)
    pmod = {(P.canon(r["casa"]), P.canon(r["ospite"])): (r.get("p") or {}) for r in (P.J("pronostici.json") or {}).get("partite", [])}
    giocate, scartate = [], 0
    for key, pq in pin.items():
        st = inizio.get(key)
        if not st: continue
        t = datetime.fromisoformat(st.replace("Z", "+00:00"))
        if not (now < t <= now + timedelta(days=8)): continue
        pp = P.prob_pinnacle(pq.get("q", {}))
        migliore = None
        for k in MERCATI:
            if k not in pp: continue
            offerte = {BOOKS[s]: q[key]["q"][k] for s, q in libri.items() if key in q and k in q[key]["q"]}
            if not offerte: continue
            book, quota = max(offerte.items(), key=lambda x: x[1])
            ev = quota * pp[k] - 1
            pm = (pmod.get(key) or {}).get(k)
            if ev >= EV_MIN and quota <= QUOTA_MAX and (pm is None or quota * pm < 1):
                scartate += 1; continue                       # il modello non conferma (o manca): si scarta
            if ev >= EV_MIN and quota <= QUOTA_MAX and (not migliore or ev > migliore["ev"]):
                kelly = (quota * pp[k] - 1) / (quota - 1)
                migliore = dict(partita=f"{key[0]}-{key[1]}", casa=key[0], ospite=key[1],
                                inizio=(prossime.get(key) or {}).get("utcDate") or st.replace(".000Z", "Z"), mercato=k,
                                label=P.LABEL.get(k, k), book=book, quota=quota, p=round(pp[k], 4), ev=round(ev, 4),
                                kelly=round(kelly * KELLY, 4), quota_giusta=round(1 / pp[k], 2),
                                p_modello=round(pm, 4), ev_modello=round(quota * pm - 1, 4), quota_modello=round(1 / pm, 2),
                                altre=dict(sorted(offerte.items(), key=lambda x: -x[1])[:5]),
                                match_id=(prossime.get(key) or {}).get("id"), giornata=(prossime.get(key) or {}).get("matchday"))
        if migliore: giocate.append(migliore)
    giocate.sort(key=lambda g: g["inizio"])
    out = dict(aggiornato=now.isoformat(timespec="seconds"), bookmaker=presenti, ev_min=EV_MIN, kelly=KELLY, giocate=giocate, scartate_senza_conferma=scartate)
    json.dump(out, open(os.path.join(D, "valuebet.json"), "w"), ensure_ascii=False, indent=1)
    # registro nello storico (una volta sola per partita e mercato, alla prima quota trovata)
    if os.environ.get("REGISTRA", "1") != "0" and giocate:
        db = sqlite3.connect(os.path.join(D, "storico.sqlite"))
        db.execute("""CREATE TABLE IF NOT EXISTS previsioni(id INTEGER PRIMARY KEY, creato TEXT, giornata INT, match_id INT, partita TEXT,
                      inizio TEXT, mercato TEXT, quota REAL, p_modello REAL, ev REAL, tipo TEXT, gruppo TEXT, esito INT, profitto REAL)""")
        if "quota_chiusura" not in [c[1] for c in db.execute("PRAGMA table_info(previsioni)")]:
            db.execute("ALTER TABLE previsioni ADD COLUMN quota_chiusura REAL")
        for g in giocate:
            if not g["match_id"]: continue
            if db.execute("SELECT 1 FROM previsioni WHERE match_id=? AND mercato=? AND tipo='value'", (g["match_id"], g["mercato"])).fetchone():
                continue
            db.execute("INSERT INTO previsioni(creato,giornata,match_id,partita,inizio,mercato,quota,p_modello,ev,tipo,gruppo) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (now.isoformat(timespec="seconds"), g["giornata"], g["match_id"], g["partita"], g["inizio"], g["mercato"],
                        g["quota"], g["p"], g["ev"], "value", g["book"]))
        db.commit(); db.close()
    print(f"Value bet: {len(giocate)} con doppia conferma ({scartate} scartate perche' il modello non conferma), su {len(presenti)} bookmaker italiani con quote ({', '.join(presenti) or 'nessuno'})")

if __name__ == "__main__":
    main()
