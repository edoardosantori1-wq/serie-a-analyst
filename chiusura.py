#!/usr/bin/env python3
"""Registra la quota Eurobet di chiusura (rilevata poco prima del calcio d'inizio) per le previsioni nello storico.
Serve a misurare se le quote prese all'uscita del report erano migliori di quelle finali ("quote battute").
Le combo con quota stimata sono escluse: il confronto ha senso solo tra quote reali."""
import os, sqlite3
from datetime import datetime, timezone, timedelta
import predizioni as P

D = P.D

def main():
    dbp = os.path.join(D, "storico.sqlite")
    if not os.path.exists(dbp): return
    db = sqlite3.connect(dbp)
    if "quota_chiusura" not in [c[1] for c in db.execute("PRAGMA table_info(previsioni)")]:
        db.execute("ALTER TABLE previsioni ADD COLUMN quota_chiusura REAL")
    now = datetime.now(timezone.utc)
    Q = P.quote_eurobet()
    # quote marcatori Eurobet per partita
    amid = next((k for k, m in P.MK.items() if m["marketType"] == "players-anytimegoalscorer"), None)
    marc = {}
    for fx in (P.J("oddspapi_quote.json") or []):
        eb = (fx.get("bookmakerOdds") or {}).get("eurobet.it")
        if not eb or not amid or amid not in eb.get("markets", {}): continue
        key = f'{P.canon(fx.get("participant1Name"))}-{P.canon(fx.get("participant2Name"))}'
        marc[key] = [(p["playerName"], p["price"]) for o in eb["markets"][amid]["outcomes"].values()
                     for p in o["players"].values() if p.get("playerName") and p.get("price")]
    n = 0
    for rid, partita, inizio, mercato in db.execute(
            "SELECT id, partita, inizio, mercato FROM previsioni WHERE quota_chiusura IS NULL").fetchall():
        t = datetime.fromisoformat(inizio)
        if not (timedelta(minutes=-30) <= t - now <= timedelta(minutes=120)): continue
        h, a = partita.split("-", 1)
        q = None
        if mercato.startswith("SCORER:"):
            pt = P._norm(mercato[7:])
            for nome, pz in marc.get(partita, []):
                nt = P._norm(nome)
                if nt and pt and nt[0] in pt: q = pz; break
        elif not mercato.startswith("C:"):
            q = (Q.get((h, a)) or {}).get("q", {}).get(mercato)
        if q:
            db.execute("UPDATE previsioni SET quota_chiusura=? WHERE id=?", (q, rid)); n += 1
    db.commit(); db.close()
    print(f"Quote di chiusura registrate: {n}")

if __name__ == "__main__":
    main()
