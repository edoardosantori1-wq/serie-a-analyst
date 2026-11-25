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
import json, os, subprocess, sys, glob
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
# quote: Eurobet + Pinnacle (riferimento) + bookmaker italiani ADM per le value bet. Una sola richiesta per tutti.
LIBRI = "eurobet.it,pinnacle,sisal.it,snai.it,goldbet.it,lottomatica.it,bet365.it,betflag.it,planetwin365.it,admiralbet.it,netbet.it,888sport.it,pokerstars.it,leovegas.it,quigioco.it"
QURL = f"{OP}/odds-by-tournaments?tournamentIds=23&bookmakers={LIBRI}&verbosity=3&apiKey={OK}"
QURL_BASE = f"{OP}/odds-by-tournaments?tournamentIds=23&bookmakers=eurobet.it,pinnacle&verbosity=3&apiKey={OK}"
def quote_get():
    """Quote con tutti i bookmaker; se la richiesta allargata non va, si torna a Eurobet + Pinnacle."""
    return get("oddspapi_quote.json", QURL) or get("oddspapi_quote.json", QURL_BASE)
s = NOW.year if NOW.month >= 7 else NOW.year - 1; L = {"league": "seriea", "season": s}
# StrikerAPI: piano gratuito 500 crediti al mese. Si tiene il conto dei crediti spesi nel mese e ci si ferma
# prima del limite (margine di sicurezza), cosi' il sistema non resta mai senza crediti a meta' giornata.
COSTO = {"get_lineups": 5, "get_game": 5, "get_team_stats": 5, "get_leaders": 5, "get_ratings": 2, "get_schedule": 2, "list_games": 2, "list_teams": 1}
LIMITE_STRIKER = 470
def sget(fname, tool, body):
    mese = NOW.strftime("%Y-%m"); c = STATO.get("striker_crediti") or {}
    if c.get("mese") != mese: c = {"mese": mese, "usati": 0}
    costo = COSTO.get(tool, 5)
    if c["usati"] + costo > LIMITE_STRIKER:
        print(f"{fname:40s} SALTATO: crediti StrikerAPI del mese quasi finiti ({c['usati']}/500)"); return False
    c["usati"] += costo; STATO["striker_crediti"] = c
    return get(fname, f"{SB}/{tool}", SH, "POST", body)

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
    quote_get()
    if not os.path.exists(os.path.join(D, "striker_teams.json")): sget("striker_teams.json", "list_teams", L)
    sget("striker_team_stats.json", "get_team_stats", L)
    sget("striker_elo.json", "get_ratings", L)
    sget("striker_xg_giocatori.json", "get_leaders", dict(L, stat="xg", limit=100, min_games=2))
    # Fantacalcio: statistiche di (quasi) tutti i giocatori. StrikerAPI da' al massimo 100 righe per richiesta:
    # si chiedono piu' pagine (offset) e si uniscono; ci si ferma quando non arrivano giocatori nuovi.
    def leaders_tutti(fname, stat, pagine):
        tutti, visti = [], set()
        for n in range(pagine):
            tmpn = f"_tmp_{stat}.json"
            if not sget(tmpn, "get_leaders", dict(L, stat=stat, limit=100, min_games=1, offset=n*100)): break
            righe = ((J(tmpn) or {}).get("data") or {}).get("leaders", [])
            nuovi = [p for p in righe if p.get("player_id") not in visti]
            visti |= {p.get("player_id") for p in nuovi}; tutti += nuovi
            if len(righe) < 100 or not nuovi: break
        try: os.remove(os.path.join(D, f"_tmp_{stat}.json"))
        except OSError: pass
        if tutti:
            json.dump({"data": {"stat": stat, "leaders": tutti}}, open(os.path.join(D, fname), "w"), ensure_ascii=False)
            print(f"{fname:40s} {len(tutti)} giocatori")
    # con l'export di Fantacalcio caricato (presenze, gol, assist, cartellini) queste chiamate non servono:
    # si risparmiano circa 100 crediti a giornata
    # (sezione Fantacalcio rimossa: niente statistiche di tutti i giocatori, si risparmiano crediti)
    sget("striker_schedule.json", "get_schedule", dict(L, days=10))
    # primo avvio: ultime formazioni schierate (una partita per squadra), poi bastano le ufficiali di ogni giornata
    import glob
    if len(glob.glob(os.path.join(D, "lineups", "*.json"))) < 10:
        frm = (NOW - timedelta(days=12)).strftime("%Y-%m-%d"); to = NOW.strftime("%Y-%m-%d")
        if sget("striker_giocate_recenti.json", "list_games", dict(L, stage="league", limit=20, **{"from": frm, "to": to})):
            viste = set()
            for g in (J("striker_giocate_recenti.json") or {}).get("data", {}).get("games", []):
                hm, aw = g.get("home", {}).get("abbrev"), g.get("away", {}).get("abbrev")
                if g.get("status") != "final" or (hm in viste and aw in viste): continue
                viste |= {hm, aw}
                sget(os.path.join("lineups", f"{g['game_id']}.json"), "get_lineups", {"game_id": str(g["game_id"]), "league": "seriea"})
    # assenze (infortuni e squalifiche) da API-Football, piano gratuito: 1 richiesta
    get("apif_infortuni.json", f"https://v3.football.api-sports.io/injuries?league=135&season={s}", [f"x-apisports-key: {ENV.get('APIFOOTBALL_KEY','')}"])
    # taratura automatica del modello AI (test walk-forward contro il mercato) prima dei pronostici
    subprocess.run([sys.executable, os.path.join(BASE, "taratura.py")], check=False)
    # solo l'uscita ufficiale (programmata) registra le previsioni nello storico e congela la giornata
    env = dict(os.environ, REGISTRA="0" if FORZA else "1")
    subprocess.run([sys.executable, os.path.join(BASE, "predizioni.py")], check=False, env=env)
    subprocess.run([sys.executable, os.path.join(BASE, "valore.py")], check=False, env=env)
    if not FORZA:
        STATO["uscita_giornata"] = md; STATO["uscita_ora"] = NOW.isoformat(timespec="seconds")
        # promemoria: il workflow apre una segnalazione su GitHub, che arriva per email
        open(os.path.join(D, "notifica.txt"), "w").write(
            f"Report giornata {md} pubblicato: pronostici, triple e marcatori.\n\nhttps://edoardosantori1-wq.github.io/serie-a-analyst/")

# 3b) martedi' (o 3 giorni prima della giornata): prepara il modulo delle quote combo per la calibrazione
def _modulo_vuoto():
    try: return len([l for l in open(os.path.join(D, "quote_combo.csv"), encoding="utf-8-sig").read().splitlines() if l.strip()]) <= 1
    except OSError: return True
_ult = STATO.get("modulo_tentativo")
_riprova = (STATO.get("modulo_giornata") == md and _modulo_vuoto()
            and (not _ult or NOW - datetime.fromisoformat(_ult) >= timedelta(hours=6)))   # quote non ancora pubblicate: si riprova ogni 6 ore
if t_first and (STATO.get("modulo_giornata") != md or _riprova) and STATO.get("uscita_giornata") != md and NOW.astimezone(ROME) >= (t_first - timedelta(days=4)).replace(hour=9, minute=0):
    STATO["modulo_tentativo"] = NOW.isoformat()
    print(">>> MODULO CALIBRAZIONE giornata", md)
    if not os.path.exists(os.path.join(D, "oddspapi_mercati.json")):
        get("oddspapi_mercati.json", f"{OP}/markets?sportId=10&apiKey={OK}")
    quote_get()
    subprocess.run([sys.executable, os.path.join(BASE, "predizioni.py")], check=False, env=dict(os.environ, REGISTRA="0", SOLO_MODULO="1"))
    subprocess.run([sys.executable, os.path.join(BASE, "valore.py")], check=False, env=dict(os.environ, REGISTRA="0"))
    STATO["modulo_giornata"] = md

# 3c) quota di chiusura: una richiesta OddsPapi per ogni orario di inizio, tra 15 e 75 minuti prima
fatte = set(STATO.get("chiusure", []))
orari = sorted({m["utcDate"] for m in giornata})
for o_ in orari:
    t = datetime.fromisoformat(o_.replace("Z", "+00:00"))
    if o_ not in fatte and timedelta(minutes=10) <= t - NOW <= timedelta(minutes=80) and STATO.get("uscita_giornata") == md:
        quote_get()
        subprocess.run([sys.executable, os.path.join(BASE, "chiusura.py")], check=False)
        subprocess.run([sys.executable, os.path.join(BASE, "valore.py")], check=False)   # value bet con quote fresche
        fatte.add(o_); STATO["chiusure"] = sorted(fatte)[-40:]
        break

# 3d) value bet: nei giorni con partite, un controllo delle quote alle 10 del mattino (1 richiesta OddsPapi)
oggi = NOW.astimezone(ROME).date().isoformat()
giorni_partita = {datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(ROME).date().isoformat() for m in giornata}
if (STATO.get("uscita_giornata") == md and oggi in giorni_partita and NOW.astimezone(ROME).hour >= 10
        and oggi not in STATO.get("vb_giorni", [])):
    quote_get()
    subprocess.run([sys.executable, os.path.join(BASE, "valore.py")], check=False)
    STATO["vb_giorni"] = (STATO.get("vb_giorni", []) + [oggi])[-20:]

# 4) formazioni ufficiali (finestra di 75 minuti prima del calcio d'inizio)
for g in (J("striker_schedule.json") or {}).get("data", {}).get("games", []):
    t = datetime.fromisoformat(g["starts_at"].replace("Z", "+00:00"))
    f = os.path.join("lineups", f"ufficiale_{g['game_id']}.json")
    if timedelta(minutes=-45) <= t - NOW <= timedelta(minutes=75):
        prev = J(f)
        tent = STATO.setdefault("tentativi_formazioni", {})
        if (not prev or not (prev.get("data") or {}).get("lineups")) and tent.get(str(g["game_id"]), 0) < 2:   # max 2 tentativi
            tent[str(g["game_id"])] = tent.get(str(g["game_id"]), 0) + 1
            sget(f, "get_lineups", {"game_id": str(g["game_id"]), "league": "seriea"})
if STATO.get("tentativi_formazioni"):
    STATO["tentativi_formazioni"] = dict(list(STATO["tentativi_formazioni"].items())[-60:])

# 6) CHAMPIONS LEAGUE: sezione sospesa (campione di partite troppo piccolo). Per riattivarla: CHAMPIONS_ATTIVA = True
CHAMPIONS_ATTIVA = False
if CHAMPIONS_ATTIVA:
    import time
    def fd_get(fname, url):
        time.sleep(6.5)              # football-data.org gratuito: massimo 10 richieste al minuto
        return get(fname, url, FD)
    FDB = "https://api.football-data.org/v4/competitions"
    oraR = NOW.astimezone(ROME); oggi_r = oraR.date()
    cl = (J("fdorg_cl.json") or {}).get("matches", [])
    giorni_cl = {datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(ROME).date() for m in cl}
    if (STATO.get("cl_cal") != oggi_r.isoformat() and oraR.hour >= 8) or oggi_r in giorni_cl or not cl:
        if fd_get("fdorg_cl.json", f"{FDB}/CL/matches?season={s}"): STATO["cl_cal"] = oggi_r.isoformat()
        cl = (J("fdorg_cl.json") or {}).get("matches", [])
    # marcatori di Champions il mattino dopo ogni giorno di partite (servono a verificare i marcatori giocati)
    if (oggi_r - timedelta(days=1)) in giorni_cl and oraR.hour >= 8 and STATO.get("cl_marc_agg") != oggi_r.isoformat():
        if fd_get("fdorg_cl_marcatori.json", f"{FDB}/CL/scorers?limit=100"): STATO["cl_marc_agg"] = oggi_r.isoformat()
    cl_pro = sorted([m for m in cl if m.get("status") in ("SCHEDULED", "TIMED") and m["homeTeam"].get("id")], key=lambda m: m["utcDate"])
    if cl_pro:
        t_cl = datetime.fromisoformat(cl_pro[0]["utcDate"].replace("Z", "+00:00"))
        turno = cl_pro[0]["utcDate"][:10]
        ora_uscita = (t_cl.astimezone(ROME) - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        if (STATO.get("cl_uscita") != turno and NOW.astimezone(ROME) >= ora_uscita) or (FORZA and t_cl - NOW <= timedelta(days=8)):
            print(">>> USCITA CHAMPIONS", turno)
            if not os.path.exists(os.path.join(D, "fdorg_cl_teams.json")) or STATO.get("cl_teams") != s:
                if fd_get("fdorg_cl_teams.json", f"{FDB}/CL/teams?season={s}"): STATO["cl_teams"] = s
            get("clubelo.csv", f"http://api.clubelo.com/{NOW.date().isoformat()}")
            for c in ["PL", "PD", "BL1", "SA", "FL1", "DED", "PPL"]:
                fd_get(f"fdorg_tab_{c}.json", f"{FDB}/{c}/standings")
                fd_get(f"fdorg_marc_{c}.json", f"{FDB}/{c}/scorers?limit=60")
            fd_get("fdorg_cl_marcatori.json", f"{FDB}/CL/scorers?limit=100")
            tid = STATO.get("cl_tid", 7)
            url_cl = lambda t: f"{OP}/odds-by-tournaments?tournamentIds={t}&bookmakers={LIBRI}&verbosity=3&apiKey={OK}"
            ok_q = get("oddspapi_cl.json", url_cl(tid))
            if not ok_q or not (J("oddspapi_cl.json") or []):
                # id del torneo da verificare: si cerca "Champions League" nell'elenco dei tornei di calcio (1 richiesta, una volta sola)
                if get("oddspapi_tornei.json", f"{OP}/tournaments?sportId=10&apiKey={OK}"):
                    tt = J("oddspapi_tornei.json") or []
                    tt = tt if isinstance(tt, list) else tt.get("data", [])
                    t2 = next((t.get("tournamentId") for t in tt if "champions league" in str(t.get("tournamentName", "")).lower()
                               and "women" not in str(t.get("tournamentName", "")).lower() and "afc" not in str(t.get("tournamentName", "")).lower()), None)
                    if t2 and t2 != tid:
                        STATO["cl_tid"] = t2; get("oddspapi_cl.json", url_cl(t2))
            get("apif_cl_infortuni.json", f"https://v3.football.api-sports.io/injuries?league=2&season={s}", [f"x-apisports-key: {ENV.get('APIFOOTBALL_KEY','')}"])
            subprocess.run([sys.executable, os.path.join(BASE, "champions.py")], check=False, env=dict(os.environ, REGISTRA="0" if FORZA else "1"))
            if not FORZA: STATO["cl_uscita"] = turno

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
        tg = STATO.setdefault("tentativi_partite", {})
        if tg.get(str(mid), 0) >= 4: continue                      # massimo 4 download per partita (crediti)
        tg[str(mid)] = tg.get(str(mid), 0) + 1
        h, a = partita.split("-", 1)
        g = next((g for g in sched if canon(g["home"]["name"]) == h and canon(g["away"]["name"]) == a), None)
        if g: sget(os.path.join("partite", f"{mid}.json"), "get_game", {"game_id": str(g["game_id"]), "league": "seriea"})
except Exception as e:
    print("verifica marcatori:", e)
subprocess.run([sys.executable, os.path.join(BASE, "verifica.py")], check=False)
subprocess.run([sys.executable, os.path.join(BASE, "confronto.py")], check=False)

json.dump(META, open(META_P, "w"), indent=1); json.dump(STATO, open(STATO_P, "w"), indent=1)
subprocess.run([sys.executable, os.path.join(BASE, "genera_sito.py")], check=False)
