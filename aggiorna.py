#!/usr/bin/env python3
"""Scarica i dati della prossima giornata, calcola i pronostici e rigenera il sito.
Uso:  python3 aggiorna.py           (usa la cache dove possibile)
      python3 aggiorna.py --forza   (riscarica tutto)
Costo tipico: 1 richiesta OddsPapi; StrikerAPI ~20 crediti (+50 la prima volta per le ultime formazioni,
+5 per ogni formazione ufficiale, addebitati solo quando il club l'ha pubblicata)."""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta
BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati"); os.makedirs(D, exist_ok=True)
FORZA = "--forza" in sys.argv
ENV = {}
for n in (".env", "chiavi.env"):
    p = os.path.join(BASE, n)
    if os.path.exists(p):
        for l in open(p):
            if "=" in l and not l.startswith("#"): k, v = l.strip().split("=", 1); ENV[k] = v
META_P = os.path.join(D, "meta.json"); META = json.load(open(META_P)) if os.path.exists(META_P) else {}
NOW = datetime.now(timezone.utc)
def fresco(fname, ore):
    t = META.get(fname)
    return (not FORZA) and t and os.path.exists(os.path.join(D, fname)) and NOW - datetime.fromisoformat(t) < timedelta(hours=ore)
def get(fname, url, headers=(), method="GET", body=None, cache_ore=0):
    if cache_ore and fresco(fname, cache_ore):
        print(f"{fname:34s} in cache"); return True
    out = os.path.join(D, fname); tmp = out + ".tmp"
    cmd = ["curl", "-sS", "-L", "--max-time", "60", "-o", tmp, "-w", "%{http_code}", "-X", method]
    for h in headers: cmd += ["-H", h]
    if body is not None: cmd += ["-H", "Content-Type: application/json", "--data", json.dumps(body)]
    r = subprocess.run(cmd + [url], capture_output=True, text=True); code = r.stdout.strip()
    if code == "200":
        os.replace(tmp, out); META[fname] = NOW.isoformat(timespec="seconds"); print(f"{fname:34s} OK"); return True
    if os.path.exists(tmp): os.remove(tmp)
    print(f"{fname:34s} ERRORE {code or r.stderr.strip()[:80]} (tengo i dati precedenti)"); return False
def J(n):
    try: return json.load(open(os.path.join(D, n)))
    except Exception: return None

FD = [f"X-Auth-Token: {ENV.get('FOOTBALLDATA_KEY','')}"]
get("fdorg_prossime.json", "https://api.football-data.org/v4/competitions/SA/matches?status=SCHEDULED,TIMED,POSTPONED", FD)
get("fdorg_giocate.json", "https://api.football-data.org/v4/competitions/SA/matches?status=FINISHED", FD)
s = NOW.year if NOW.month >= 7 else NOW.year - 1
get("fdcouk_corrente.csv", f"https://www.football-data.co.uk/mmz4281/{s%100:02d}{(s+1)%100:02d}/I1.csv", cache_ore=6)
for y in (s-1,):   # stagione precedente per il modello (una volta sola)
    if not os.path.exists(os.path.join(D, f"storico_{y%100:02d}{(y+1)%100:02d}.csv")):
        get(f"storico_{y%100:02d}{(y+1)%100:02d}.csv", f"https://www.football-data.co.uk/mmz4281/{y%100:02d}{(y+1)%100:02d}/I1.csv")
# allenatori (rilevazione cambi) e coppe europee per giorni di riposo/turnover
if get("fdorg_squadre.json", "https://api.football-data.org/v4/competitions/SA/teams", FD, cache_ore=20):
    snap_p = os.path.join(D, "allenatori.json"); old = J("allenatori.json") or {}
    cur = {t["name"]: (t.get("coach") or {}).get("name") for t in (J("fdorg_squadre.json") or {}).get("teams", [])}
    cambi = J("allenatori_cambi.json") or []
    sys.path.insert(0, BASE); from predizioni import canon
    for team, coach in cur.items():
        if old.get(team) and coach and old[team] != coach:
            cambi.append(dict(squadra=canon(team), vecchio=old[team], nuovo=coach, rilevato=NOW.isoformat(timespec="seconds")))
            print(f"  >> CAMBIO ALLENATORE: {team}: {old[team]} -> {coach}")
    json.dump(cur, open(snap_p, "w"), ensure_ascii=False, indent=1); json.dump(cambi, open(os.path.join(D, "allenatori_cambi.json"), "w"), ensure_ascii=False, indent=1)
d1 = (NOW - timedelta(days=10)).strftime("%Y-%m-%d"); d2 = (NOW + timedelta(days=14)).strftime("%Y-%m-%d")
get("fdorg_coppe.json", f"https://api.football-data.org/v4/matches?competitions=CL&dateFrom={d1}&dateTo={d2}", FD, cache_ore=12)
OK = ENV.get("ODDSPAPI_KEY", ""); OP = "https://api.oddspapi.io/v4"
if not os.path.exists(os.path.join(D, "oddspapi_mercati.json")):
    get("oddspapi_mercati.json", f"{OP}/markets?sportId=10&apiKey={OK}")
get("oddspapi_quote.json", f"{OP}/odds-by-tournaments?tournamentIds=23&bookmakers=eurobet.it&verbosity=3&apiKey={OK}", cache_ore=3)

SH = [f"Authorization: Bearer {ENV.get('STRIKER_KEY','')}"]; SB = "https://mcp.strikerapi.com/v1"
L = {"league": "seriea", "season": s}
get("striker_teams.json", f"{SB}/list_teams", SH, "POST", L, cache_ore=24*30)
get("striker_team_stats.json", f"{SB}/get_team_stats", SH, "POST", L, cache_ore=12)
get("striker_elo.json", f"{SB}/get_ratings", SH, "POST", L, cache_ore=12)
get("striker_xg_giocatori.json", f"{SB}/get_leaders", SH, "POST", dict(L, stat="xg", limit=100, min_games=2), cache_ore=12)
get("striker_gol_giocatori.json", f"{SB}/get_leaders", SH, "POST", dict(L, stat="goals", limit=40, min_games=1), cache_ore=12)
get("striker_schedule.json", f"{SB}/get_schedule", SH, "POST", dict(L, days=10), cache_ore=3)
frm = (NOW - timedelta(days=12)).strftime("%Y-%m-%d"); to = NOW.strftime("%Y-%m-%d")
get("striker_giocate_recenti.json", f"{SB}/list_games", SH, "POST", dict(L, stage="league", **{"from": frm, "to": to}, limit=20), cache_ore=6)

# ultime formazioni schierate: una partita per squadra (la piu' recente), con cache permanente per game_id
LD = os.path.join(D, "lineups"); os.makedirs(LD, exist_ok=True)
gr = (J("striker_giocate_recenti.json") or {}).get("data", {})
games = gr.get("games", gr if isinstance(gr, list) else [])
viste = set()
for g in games:   # newest first
    hm, aw = g.get("home", {}).get("abbrev"), g.get("away", {}).get("abbrev")
    if g.get("status") not in ("final", "post", "finished", "full_time", "ft") and g.get("result") is None: continue
    if hm in viste and aw in viste: continue
    viste |= {hm, aw}
    f = os.path.join("lineups", f"{g['game_id']}.json")
    if not os.path.exists(os.path.join(D, f)):
        get(f, f"{SB}/get_lineups", SH, "POST", {"game_id": str(g["game_id"]), "league": "seriea"})
# formazioni ufficiali: partite che iniziano entro 75 minuti (o gia' iniziate da poco)
sc = (J("striker_schedule.json") or {}).get("data", {}).get("games", [])
for g in sc:
    t = datetime.fromisoformat(g["starts_at"].replace("Z", "+00:00"))
    f = os.path.join("lineups", f"ufficiale_{g['game_id']}.json")
    if timedelta(minutes=-30) <= t - NOW <= timedelta(minutes=75):
        prev = J(f)
        if not prev or not (prev.get("data") or {}).get("lineups"):
            get(f, f"{SB}/get_lineups", SH, "POST", {"game_id": str(g["game_id"]), "league": "seriea"})
# notizie: feed RSS pubblici (solo titolo, fonte, link)
FEED = {"ANSA": "https://www.ansa.it/sito/notizie/sport/calcio/calcio_rss.xml",
        "Gazzetta": "https://www.gazzetta.it/rss/serie-a.xml",
        "Corriere dello Sport": "https://www.corrieredellosport.it/rss/calcio/serie-a",
        "Sky Sport": "https://sport.sky.it/rss/calcio.xml",
        "Calciomercato.com": "https://www.calciomercato.com/feed",
        "TuttoMercatoWeb": "https://www.tuttomercatoweb.com/rss"}
os.makedirs(os.path.join(D, "news"), exist_ok=True)
for nome, url in FEED.items():
    get(os.path.join("news", nome.replace(" ", "_").replace(".", "") + ".xml"), url, ("User-Agent: Mozilla/5.0 SerieA-Analyst",), cache_ore=1)
json.dump(META, open(META_P, "w"), indent=1)
print("\nCalcolo i pronostici...")
subprocess.run([sys.executable, os.path.join(BASE, "predizioni.py")])
print("Genero il sito...")
subprocess.run([sys.executable, os.path.join(BASE, "genera_sito.py")])
