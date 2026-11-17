#!/usr/bin/env python3
"""Regista dell'automazione (gira ogni ora su GitHub Actions).
- Ogni ora: calendario e notizie (gratis, senza limiti stretti).
- USCITA del report (una volta per giornata): venerdi' alle 09:00 se la giornata si gioca nel weekend,
  altrimenti alle 09:00 del giorno prima della prima partita (turni infrasettimanali).
  In uscita: quote Eurobet, statistiche, xG giocatori, pronostici, triple, marcatori (poi congelati).
- Fino a 75 minuti prima di ogni partita: formazione ufficiale (StrikerAPI, addebitata solo se pubblicata).
- Sempre: rigenera il sito.
Budget mensile stimato: OddsPapi ~1-2 richieste per giornata (limite 250), StrikerAPI ~70 crediti per giornata (limite 500).
Le chiavi si leggono dalle variabili d'ambiente (GitHub Secrets) o dal file .env."""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati"); os.makedirs(D, exist_ok=True)
ROME = ZoneInfo("Europe/Rome"); NOW = datetime.now(timezone.utc)
ENV = dict(os.environ)
for n in (".env", "chiavi.env"):
    p = os.path.join(BASE, n)
    if os.path.exists(p):
        for l in open(p):
            if "=" in l and not l.startswith("#"): k, v = l.strip().split("=", 1); ENV.setdefault(k, v)
META_P = os.path.join(D, "meta.json"); META = json.load(open(META_P)) if os.path.exists(META_P) else {}
STATO_P = os.path.join(D, "stato.json"); STATO = json.load(open(STATO_P)) if os.path.exists(STATO_P) else {}
FORZA = "--uscita" in sys.argv
if STATO.get("versione") != 2:
    for f in ("storico.sqlite", "bilancio.json"):
        if os.path.exists(os.path.join(D, f)): os.remove(os.path.join(D, f))
    STATO = {"versione": 2}
    print("Storico di prova azzerato: il bilancio parte dalla prima uscita ufficiale.")

def J(n):
    try: return json.load(open(os.path.join(D, n)))
    except Exception: return None
def get(fname, url, headers=(), method="GET", body=None):
    out = os.path.join(D, fname); tmp = out + ".tmp"; os.makedirs(os.path.dirname(out), exist_ok=True)
    cmd = ["curl", "-sS", "-L", "--max-time", "60", "-o", tmp, "-w", "%{http_code}", "-X", method, "-H", "User-Agent: Mozilla/5.0 SerieA-Analyst"]
    for h in headers: cmd += ["-H", h]
    if body is not None: cmd += ["-H", "Content-Type: application/json", "--data", json.dumps(body)]
    r = subprocess.run(cmd + [url], capture_output=True, text=True); code = r.stdout.strip()
    if code == "200":
        os.replace(tmp, out); META[fname] = NOW.isoformat(timespec="seconds"); print(f"{fname:40s} OK"); return True
    if os.path.exists(tmp): os.remove(tmp)
    print(f"{fname:40s} ERRORE {code or r.stderr.strip()[:80]}"); return False

FD = [f"X-Auth-Token: {ENV.get('FOOTBALLDATA_KEY','')}"]
SH = [f"Authorization: Bearer {ENV.get('STRIKER_KEY','')}"]; SB = "https://mcp.strikerapi.com/v1"
OK = ENV.get("ODDSPAPI_KEY", ""); OP = "https://api.oddspapi.io/v4"
s = NOW.year if NOW.month >= 7 else NOW.year - 1; L = {"league": "seriea", "season": s}

# 1) calendario (ogni ora)
get("fdorg_prossime.json", "https://api.football-data.org/v4/competitions/SA/matches?status=SCHEDULED,TIMED,POSTPONED", FD)
pro = sorted([m for m in (J("fdorg_prossime.json") or {}).get("matches", []) if m.get("status") in ("SCHEDULED", "TIMED")], key=lambda m: m["utcDate"])
md = pro[0]["matchday"] if pro else None
giornata = [m for m in pro if m["matchday"] == md]
t_first = datetime.fromisoformat(giornata[0]["utcDate"].replace("Z", "+00:00")).astimezone(ROME) if giornata else None
if t_first:
    if t_first.weekday() in (4, 5, 6):   # weekend: venerdi' 09:00
        d = t_first.date() - timedelta(days=t_first.weekday() - 4)
    else:                                  # infrasettimanale: giorno prima
        d = t_first.date() - timedelta(days=1)
    uscita = datetime(d.year, d.month, d.day, 9, 0, tzinfo=ROME)
    print(f"Giornata {md}: prima partita {t_first:%a %d/%m %H:%M}, uscita report {uscita:%a %d/%m %H:%M}")
else:
    uscita = None

# 2) notizie (ogni ora)
FEED = {"ANSA": "https://www.ansa.it/sito/notizie/sport/calcio/calcio_rss.xml",
        "Gazzetta": "https://www.gazzetta.it/rss/serie-a.xml",
        "Corriere dello Sport": "https://www.corrieredellosport.it/rss/calcio/serie-a",
        "Sky Sport": "https://sport.sky.it/rss/calcio.xml",
        "Calciomercato.com": "https://www.calciomercato.com/feed",
        "TuttoMercatoWeb": "https://www.tuttomercatoweb.com/rss"}
for nome, url in FEED.items():
    get(os.path.join("news", nome.replace(" ", "_").replace(".", "") + ".xml"), url)

# 3) uscita del report (una volta per giornata)
fare_uscita = FORZA or (uscita and NOW >= uscita.astimezone(timezone.utc) and STATO.get("uscita_giornata") != md)
if fare_uscita:
    print(">>> USCITA REPORT giornata", md)
    get("fdorg_giocate.json", "https://api.football-data.org/v4/competitions/SA/matches?status=FINISHED", FD)
    get("fdcouk_corrente.csv", f"https://www.football-data.co.uk/mmz4281/{s%100:02d}{(s+1)%100:02d}/I1.csv")
    for y in range(s - 5, s):    # 5 stagioni passate per il modello (scaricate una volta sola)
        prev = f"storico_{y%100:02d}{(y+1)%100:02d}.csv"
        if not os.path.exists(os.path.join(D, prev)):
            get(prev, f"https://www.football-data.co.uk/mmz4281/{y%100:02d}{(y+1)%100:02d}/I1.csv")
    if get("fdorg_squadre.json", "https://api.football-data.org/v4/competitions/SA/teams", FD):
        sys.path.insert(0, BASE); from predizioni import canon
        old = J("allenatori.json") or {}; cambi = J("allenatori_cambi.json") or []
        cur = {t["name"]: (t.get("coach") or {}).get("name") for t in (J("fdorg_squadre.json") or {}).get("teams", [])}
        for team, coach in cur.items():
            if old.get(team) and coach and old[team] != coach:
                cambi.append(dict(squadra=canon(team), vecchio=old[team], nuovo=coach, rilevato=NOW.isoformat(timespec="seconds")))
        json.dump(cur, open(os.path.join(D, "allenatori.json"), "w"), ensure_ascii=False, indent=1)
        json.dump(cambi, open(os.path.join(D, "allenatori_cambi.json"), "w"), ensure_ascii=False, indent=1)
    d1 = (NOW - timedelta(days=10)).strftime("%Y-%m-%d"); d2 = (NOW + timedelta(days=14)).strftime("%Y-%m-%d")
    get("fdorg_coppe.json", f"https://api.football-data.org/v4/matches?competitions=CL&dateFrom={d1}&dateTo={d2}", FD)
    if not os.path.exists(os.path.join(D, "oddspapi_mercati.json")):
        get("oddspapi_mercati.json", f"{OP}/markets?sportId=10&apiKey={OK}")
    get("oddspapi_quote.json", f"{OP}/odds-by-tournaments?tournamentIds=23&bookmakers=eurobet.it,pinnacle&verbosity=3&apiKey={OK}")
    if not os.path.exists(os.path.join(D, "striker_teams.json")): get("striker_teams.json", f"{SB}/list_teams", SH, "POST", L)
    get("striker_team_stats.json", f"{SB}/get_team_stats", SH, "POST", L)
    get("striker_elo.json", f"{SB}/get_ratings", SH, "POST", L)
    get("striker_xg_giocatori.json", f"{SB}/get_leaders", SH, "POST", dict(L, stat="xg", limit=100, min_games=2))
    # Fantacalcio: statistiche di (quasi) tutti i giocatori. StrikerAPI da' al massimo 100 righe per richiesta:
    # si chiedono piu' pagine (offset) e si uniscono; ci si ferma quando non arrivano giocatori nuovi.
    def leaders_tutti(fname, stat, pagine):
        tutti, visti = [], set()
        for n in range(pagine):
            tmpn = f"_tmp_{stat}.json"
            if not get(tmpn, f"{SB}/get_leaders", SH, "POST", dict(L, stat=stat, limit=100, min_games=1, offset=n*100)): break
            righe = ((J(tmpn) or {}).get("data") or {}).get("leaders", [])
            nuovi = [p for p in righe if p.get("player_id") not in visti]
            visti |= {p.get("player_id") for p in nuovi}; tutti += nuovi
            if len(righe) < 100 or not nuovi: break
        try: os.remove(os.path.join(D, f"_tmp_{stat}.json"))
        except OSError: pass
        if tutti:
            json.dump({"data": {"stat": stat, "leaders": tutti}}, open(os.path.join(D, fname), "w"), ensure_ascii=False)
            print(f"{fname:40s} {len(tutti)} giocatori")
    leaders_tutti("striker_xg_tutti.json", "xg", 7)
    leaders_tutti("striker_gol_tutti.json", "goals", 3)
    leaders_tutti("striker_assist.json", "assists", 3)
    leaders_tutti("striker_gialli.json", "yellow_cards", 3)
    leaders_tutti("striker_rossi.json", "red_cards", 1)
    leaders_tutti("striker_parate.json", "saves", 1)
    leaders_tutti("striker_cleansheet.json", "clean_sheets", 1)
    get("striker_schedule.json", f"{SB}/get_schedule", SH, "POST", dict(L, days=10))
    # primo avvio: ultime formazioni schierate (una partita per squadra), poi bastano le ufficiali di ogni giornata
    import glob
    if len(glob.glob(os.path.join(D, "lineups", "*.json"))) < 10:
        frm = (NOW - timedelta(days=12)).strftime("%Y-%m-%d"); to = NOW.strftime("%Y-%m-%d")
        if get("striker_giocate_recenti.json", f"{SB}/list_games", SH, "POST", dict(L, stage="league", limit=20, **{"from": frm, "to": to})):
            viste = set()
            for g in (J("striker_giocate_recenti.json") or {}).get("data", {}).get("games", []):
                hm, aw = g.get("home", {}).get("abbrev"), g.get("away", {}).get("abbrev")
                if g.get("status") != "final" or (hm in viste and aw in viste): continue
                viste |= {hm, aw}
                get(os.path.join("lineups", f"{g['game_id']}.json"), f"{SB}/get_lineups", SH, "POST", {"game_id": str(g["game_id"]), "league": "seriea"})
    # assenze (infortuni e squalifiche) da API-Football, piano gratuito: 1 richiesta
    get("apif_infortuni.json", f"https://v3.football.api-sports.io/injuries?league=135&season={s}", [f"x-apisports-key: {ENV.get('APIFOOTBALL_KEY','')}"])
    # taratura automatica del modello AI (test walk-forward contro il mercato) prima dei pronostici
    subprocess.run([sys.executable, os.path.join(BASE, "taratura.py")], check=False)
    # solo l'uscita ufficiale (programmata) registra le previsioni nello storico e congela la giornata
    env = dict(os.environ, REGISTRA="0" if FORZA else "1")
    subprocess.run([sys.executable, os.path.join(BASE, "predizioni.py")], check=False, env=env)
    if not FORZA:
        STATO["uscita_giornata"] = md; STATO["uscita_ora"] = NOW.isoformat(timespec="seconds")
        # promemoria: il workflow apre una segnalazione su GitHub, che arriva per email
        open(os.path.join(D, "notifica.txt"), "w").write(
            f"Report giornata {md} pubblicato: pronostici, triple e marcatori.\n\nhttps://edoardosantori1-wq.github.io/serie-a-analyst/")

# 3b) martedi' (o 3 giorni prima della giornata): prepara il modulo delle quote combo per la calibrazione
if t_first and STATO.get("modulo_giornata") != md and STATO.get("uscita_giornata") != md and NOW.astimezone(ROME) >= (t_first - timedelta(days=4)).replace(hour=9, minute=0):
    print(">>> MODULO CALIBRAZIONE giornata", md)
    if not os.path.exists(os.path.join(D, "oddspapi_mercati.json")):
        get("oddspapi_mercati.json", f"{OP}/markets?sportId=10&apiKey={OK}")
    get("oddspapi_quote.json", f"{OP}/odds-by-tournaments?tournamentIds=23&bookmakers=eurobet.it,pinnacle&verbosity=3&apiKey={OK}")
    subprocess.run([sys.executable, os.path.join(BASE, "predizioni.py")], check=False, env=dict(os.environ, REGISTRA="0", SOLO_MODULO="1"))
    STATO["modulo_giornata"] = md

# 3c) quota di chiusura: una richiesta OddsPapi per ogni orario di inizio, tra 15 e 75 minuti prima
fatte = set(STATO.get("chiusure", []))
orari = sorted({m["utcDate"] for m in giornata})
for o_ in orari:
    t = datetime.fromisoformat(o_.replace("Z", "+00:00"))
    if o_ not in fatte and timedelta(minutes=10) <= t - NOW <= timedelta(minutes=80) and STATO.get("uscita_giornata") == md:
        get("oddspapi_quote.json", f"{OP}/odds-by-tournaments?tournamentIds=23&bookmakers=eurobet.it,pinnacle&verbosity=3&apiKey={OK}")
        subprocess.run([sys.executable, os.path.join(BASE, "chiusura.py")], check=False)
        fatte.add(o_); STATO["chiusure"] = sorted(fatte)[-40:]
        break

# 4) formazioni ufficiali (finestra di 75 minuti prima del calcio d'inizio)
for g in (J("striker_schedule.json") or {}).get("data", {}).get("games", []):
    t = datetime.fromisoformat(g["starts_at"].replace("Z", "+00:00"))
    f = os.path.join("lineups", f"ufficiale_{g['game_id']}.json")
    if timedelta(minutes=-45) <= t - NOW <= timedelta(minutes=75):
        prev = J(f)
        if not prev or not (prev.get("data") or {}).get("lineups"):
            get(f, f"{SB}/get_lineups", SH, "POST", {"game_id": str(g["game_id"]), "league": "seriea"})

# 5) risultati e verifica dei pronostici (ogni ora; gratis)
if not fare_uscita:
    get("fdorg_giocate.json", "https://api.football-data.org/v4/competitions/SA/matches?status=FINISHED", FD)
try:
    import sqlite3
    sys.path.insert(0, BASE); from predizioni import canon
    db = sqlite3.connect(os.path.join(D, "storico.sqlite"))
    da_fare = db.execute("SELECT DISTINCT match_id, partita FROM previsioni WHERE esito IS NULL AND mercato LIKE 'SCORER:%'").fetchall(); db.close()
    finite = {m["id"] for m in (J("fdorg_giocate.json") or {}).get("matches", [])}
    sched = (J("striker_schedule.json") or {}).get("data", {}).get("games", [])
    for mid, partita in da_fare:
        if mid not in finite or os.path.exists(os.path.join(D, "partite", f"{mid}.json")): continue
        h, a = partita.split("-", 1)
        g = next((g for g in sched if canon(g["home"]["name"]) == h and canon(g["away"]["name"]) == a), None)
        if g: get(os.path.join("partite", f"{mid}.json"), f"{SB}/get_game", SH, "POST", {"game_id": str(g["game_id"]), "league": "seriea"})
except Exception as e:
    print("verifica marcatori:", e)
subprocess.run([sys.executable, os.path.join(BASE, "verifica.py")], check=False)
subprocess.run([sys.executable, os.path.join(BASE, "confronto.py")], check=False)

json.dump(META, open(META_P, "w"), indent=1); json.dump(STATO, open(STATO_P, "w"), indent=1)
subprocess.run([sys.executable, os.path.join(BASE, "genera_sito.py")], check=False)
