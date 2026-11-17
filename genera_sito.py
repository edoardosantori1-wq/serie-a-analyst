#!/usr/bin/env python3
"""Costruisce sito/index.html da dati/ e dati/pronostici.json. Solo libreria standard.
Niente stemmi ne' foto (marchi e immagini di persone reali): badge con sigla e colori sociali."""
import json, os, csv, html, glob
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
BASE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(BASE, "dati"); OUTD = os.path.join(BASE, "sito")
os.makedirs(OUTD, exist_ok=True); ROME = ZoneInfo("Europe/Rome"); E = html.escape
def J(n):
    try: return json.load(open(os.path.join(D, n)))
    except Exception: return None
from predizioni import canon
P = J("pronostici.json") or {}; META = J("meta.json") or {}
GIORNI = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]
MESI = ["gennaio","febbraio","marzo","aprile","maggio","giugno","luglio","agosto","settembre","ottobre","novembre","dicembre"]
def rome(iso): return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ROME)
def fday(dt): return f"{GIORNI[dt.weekday()]} {dt.day} {MESI[dt.month-1]}"
def fts(iso):
    if not iso: return "—"
    d = rome(iso); return f"{d.day:02d}/{d.month:02d} {d.hour:02d}:{d.minute:02d}"
pc = lambda x: "—" if x is None else f"{x*100:.0f}%"
f2 = lambda x: "—" if x is None else f"{x:.2f}"
def evtxt(ev):
    if ev is None: return '<span class="ev na">—</span>'
    c = "pos" if ev >= 0 else ("neu" if ev >= -0.08 else "neg")
    return f'<span class="ev {c}">{ev*100:+.1f}%</span>'

CATC = {"value": "c-val", "probabile": "c-pro", "alto rischio": "c-ris", "senza valore": "c-nov"}
def cat(s): return ""

def star(s):
    """Stella solo per gli errori di quota a favore: quota reale Eurobet, EV >= +5% e almeno 4 punti oltre la probabilita' implicita."""
    if not s or not s.get("quota") or not s.get("p"): return False
    if s.get("cat"): return s["cat"] == "value"
    return s.get("fonte") != "stimata" and s["p"] * s["quota"] - 1 >= 0.05 and s["p"] - 1 / s["quota"] >= 0.04
def stella(s): return ' <span class="star" title="Errore di quota a favore">★</span>' if star(s) else ""

# ------------------------------------------------------------------ squadre
TEAMS = {}
for t in (J("striker_teams.json") or {}).get("data", {}).get("teams", []):
    c = canon(t["display_name"])
    if c: TEAMS[c] = dict(ab=t["abbrev"][:3], col="#" + (t.get("color") or "444444"), alt="#" + (t.get("alt_color") or "ffffff"), txt="#" + (t.get("text_color") or "ffffff"))
def T(t): return TEAMS.get(t, dict(ab=(t or "?")[:3].upper(), col="#3a3f4b", alt="#ffffff", txt="#ffffff"))
def badge(t, size=""):
    x = T(t); return f'<span class="badge {size}" style="--c:{x["col"]};--a:{x["alt"]};color:{x["txt"]}">{E(x["ab"])}</span>'
def avatar(name, team):
    x = T(team); ini = "".join(w[0] for w in name.replace("-", " ").split()[:2]).upper()
    return f'<span class="avatar" style="--c:{x["col"]};--a:{x["alt"]};color:{x["txt"]}">{E(ini)}</span>'
TS = {canon(t["display_name"]): t for t in (J("striker_team_stats.json") or {}).get("data", {}).get("teams", [])}
ELOD = (J("striker_elo.json") or {}).get("data", {}); ELO = {canon(t["name"]): t["elo"] for t in ELOD.get("ratings", [])}

# ------------------------------------------------------------------ risultati e forma
rows = []
try:
    for r in csv.DictReader(open(os.path.join(D, "fdcouk_corrente.csv"), encoding="utf-8-sig")):
        if not r.get("FTHG"): continue
        d, m, y = r["Date"].split("/"); y = int(y) + (2000 if len(y) == 2 else 0)
        rows.append(dict(date=f"{y}-{m}-{d}", h=canon(r["HomeTeam"]), a=canon(r["AwayTeam"]), hg=int(r["FTHG"]), ag=int(r["FTAG"]),
                         hxg=r.get("HxG"), axg=r.get("AxG")))
except FileNotFoundError: pass
rows.sort(key=lambda r: r["date"])
def forma(team, n=5):
    out = []
    for r in reversed(rows):
        if r["h"] == team: gf, ga, o, ha, xf, xa = r["hg"], r["ag"], r["a"], "C", r["hxg"], r["axg"]
        elif r["a"] == team: gf, ga, o, ha, xf, xa = r["ag"], r["hg"], r["h"], "T", r["axg"], r["hxg"]
        else: continue
        out.append(dict(res="V" if gf > ga else "N" if gf == ga else "P", t=f"{ha} {o} {gf}-{ga}" + (f" · xG {xf}-{xa}" if xf else "")))
        if len(out) == n: break
    return list(reversed(out))
tab = {}
for r in rows:
    for t, gf, ga in ((r["h"], r["hg"], r["ag"]), (r["a"], r["ag"], r["hg"])):
        s = tab.setdefault(t, dict(g=0, v=0, n=0, p=0, gf=0, gs=0)); s["g"] += 1; s["gf"] += gf; s["gs"] += ga
        s["v" if gf > ga else "n" if gf == ga else "p"] += 1
for s in tab.values(): s["pt"] = 3*s["v"] + s["n"]

# ------------------------------------------------------------------ formazioni
def depth(pos):
    p = (pos or "").lower()
    if "goalkeeper" in p: return 0
    if "back" in p or "defender" in p: return 1
    if "defensive" in p: return 2
    if "attacking" in p: return 3.2
    if "midfielder" in p: return 2.5
    if "wing" in p: return 3.6
    return 4
def lateral(pos):
    p = (pos or "").lower()
    if "center left" in p or "left center" in p: return -0.5
    if "center right" in p or "right center" in p: return 0.5
    if "left" in p: return -1
    if "right" in p: return 1
    return 0
LINEUPS = {}   # squadra -> dict(modulo, xi, partita, ufficiale)
for f in sorted(glob.glob(os.path.join(D, "lineups", "*.json"))):
    j = (json.load(open(f)) or {}).get("data") or {}
    g = j.get("game") or {}; uff = os.path.basename(f).startswith("ufficiale_")
    for lu in j.get("lineups") or []:
        team = canon(next((x["name"] for x in (g.get("home"), g.get("away")) if x and x.get("abbrev") == lu.get("abbrev")), lu.get("abbrev")))
        if not team: continue
        xi = lu.get("starting_xi") or []
        if not xi: continue
        prev = LINEUPS.get(team)
        if prev and (prev["ufficiale"] and not uff or (prev["data"] > (g.get("date") or "") and not uff)): continue
        opp = next((x["name"] for x in (g.get("home"), g.get("away")) if x and x.get("abbrev") != lu.get("abbrev")), "")
        LINEUPS[team] = dict(modulo=lu.get("formation") or "", xi=xi, data=g.get("date") or "", ufficiale=uff,
                             vs=canon(opp) or opp, gid=g.get("game_id"))
def pitch(team):
    L = LINEUPS.get(team)
    if not L: return ''
    xi = sorted(L["xi"], key=lambda p: (depth(p.get("position")), lateral(p.get("position"))))
    try: lines = [1] + [int(x) for x in L["modulo"].split("-")]
    except Exception: lines = [1, 4, 4, 2]
    if sum(lines) != len(xi): lines = [1] + [len([p for p in xi[1:] if round(depth(p["position"])) == k]) for k in (1, 2, 3, 4)]
    x = T(team); W, H = 300, 400; dots = []; i = 0; nl = len([l for l in lines if l])
    li = 0
    for cnt in lines:
        if not cnt: continue
        row = sorted(xi[i:i+cnt], key=lambda p: lateral(p.get("position"))); i += cnt
        y = H - 34 - li * (H - 70) / max(nl - 1, 1); li += 1
        for k, p in enumerate(row):
            px = W * (k + 1) / (cnt + 1)
            nm = p["name"].split()[-1] if len(p["name"]) > 11 else p["name"]
            dots.append(f'<g><circle cx="{px:.0f}" cy="{y:.0f}" r="13" fill="{x["col"]}" stroke="{x["alt"]}" stroke-width="2"/>'
                        f'<text x="{px:.0f}" y="{y+4:.0f}" class="jn" fill="{x["txt"]}">{E(str(p.get("jersey","")))}</text>'
                        f'<text x="{px:.0f}" y="{y+27:.0f}" class="pn">{E(nm)}</text></g>')
    tag = "Formazione UFFICIALE" if L["ufficiale"] else f'Ultima formazione schierata (vs {E(L["vs"])}, {L["data"][8:10]}/{L["data"][5:7]})'
    return f'''<div class="pitchwrap"><div class="ptag {'off' if L['ufficiale'] else ''}">{tag} · {E(L['modulo'])}</div>
    <svg viewBox="0 0 {W} {H}" class="pitch" role="img" aria-label="Formazione {E(team)}">
    <rect x="0" y="0" width="{W}" height="{H}" rx="10" class="grass"/>
    <g class="lines"><rect x="8" y="8" width="{W-16}" height="{H-16}" rx="4"/><line x1="8" y1="{H/2}" x2="{W-8}" y2="{H/2}"/>
    <circle cx="{W/2}" cy="{H/2}" r="38"/><rect x="{W/2-70}" y="{H-8-60}" width="140" height="60"/><rect x="{W/2-30}" y="{H-8-22}" width="60" height="22"/>
    <rect x="{W/2-70}" y="8" width="140" height="60"/><rect x="{W/2-30}" y="8" width="60" height="22"/></g>{''.join(dots)}</svg></div>'''

# ------------------------------------------------------------------ partite
PARTITE = P.get("partite", [])
def best_market(r):
    s = [x for x in r.get("selezioni", []) if not x["ht"] and x["p"] >= 0.30]
    return max(s, key=lambda x: x["ev"]) if s else None
def statbar(label, vh, va, fmt=f2, higher_better=True):
    if vh is None or va is None: return ""
    tot = (vh + va) or 1; wh = vh / tot * 100
    bh = (vh >= va) == higher_better
    return f'''<div class="sb"><span class="{'hi' if bh else ''}">{fmt(vh)}</span><div class="sbl">{label}</div><span class="{'hi' if not bh else ''}">{fmt(va)}</span>
    <div class="sbar"><i style="width:{wh:.0f}%"></i></div></div>'''
def combo_rows(r, limit=None):
    c = r.get("combo") or []
    if limit: c = c[:limit]
    cm = r.get("combo_mercato") or {}
    return "".join(f'''<tr data-p="{p:.4f}" data-m="{E(r['casa']+'-'+r['ospite'])}" data-n="{E(n)}"><td class=l>{E(n)}</td><td>{pc(p)}</td><td><b>{1/p:.2f}</b></td>
    <td>{f"{cm[n][1]:.2f}" if n in cm else "—"}</td><td>{evtxt(p*cm[n][1]-1) if n in cm else "—"}</td>
    <td><input class="qin" inputmode="decimal" placeholder="quota" data-k="{r['id']}|{E(n)}" aria-label="Quota Eurobet {E(n)}"></td><td class="evc">—</td></tr>''' for n, p in c)
def combo_html(r):
    if not r.get("combo"): return ''
    return f'''<div class="scroll"><table class="odds combo-t"><thead><tr><th>Combo</th><th>Prob. stimata</th><th>Quota minima</th><th>Quota stimata</th><th>EV stimato</th><th>Quota reale</th><th>EV reale</th></tr></thead>
    <tbody>{combo_rows(r)}</tbody></table></div>'''
def ai_html(r):
    """Previsione AI (solo dati) a confronto con il mercato Eurobet senza margine."""
    ai = r.get("p_modello") or {}; mk = r.get("p_mercato") or {}
    righe = [("1", "1"), ("X", "X"), ("2", "2"), ("Over 2.5", "O2.5"), ("Goal", "GG")]
    def cella(k):
        a, m = ai.get(k), mk.get(k)
        if a is None: return "<td>—</td><td>—</td><td>—</td>"
        d = "" if m is None else (a - m) * 100
        dc = "" if m is None else ('<td class="%s">%+.0f</td>' % ("okc" if d >= 5 else ("koc" if d <= -5 else "muted"), d))
        return f"<td><b>{pc(a)}</b></td><td>{pc(m) if m is not None else '—'}</td>{dc or '<td>—</td>'}"
    rows = "".join(f"<tr><td class=l>{lab}</td>{cella(k)}</tr>" for lab, k in righe)
    lm = r.get("lam_modello") or ["?", "?"]
    ass = r.get("assenze") or {}; eff = r.get("effetto_assenze") or [1, 1]
    blocchi = []
    for i, team in enumerate((r["casa"], r["ospite"])):
        lst = ass.get(team) or []
        if not lst: continue
        nomi = ", ".join(f'{E(x["nome"])} <span class="muted">({"in dubbio" if x.get("dubbio") else E(x.get("motivo") or "assente")})</span>' for x in lst)
        e = (1 - eff[i]) * 100
        blocchi.append(f'<div class="ass"><b>{E(team)}</b>: {nomi}{f" · <b class=koc>attacco −{e:.0f}%</b>" if e >= 1 else ""}</div>')
    stato = P.get("assenze_stato")
    ass_html = "".join(blocchi) or (f'<div class="ass muted">{E(stato)}</div>' if stato else '<div class="ass muted">Nessun assente segnalato</div>')
    return f'''<div class="aibox"><div class="aih"><b>Previsione AI</b> <span class="muted">· solo dati: forza delle squadre, xG e forma recente</span></div>
    <div class="aik"><span><small>Risultato più probabile</small><b>{E(r.get("risultato_modello") or "—")}</b></span><span><small>Gol attesi AI</small><b>{lm[0]} – {lm[1]}</b></span></div>
    <div class="scroll"><table class="tbl ait"><thead><tr><th class=l>Esito</th><th>AI</th><th>Mercato</th><th>Diff.</th></tr></thead><tbody>{rows}</tbody></table></div><div class="assh">Assenti</div>{ass_html}</div>'''
cards = []; day = None
for r in PARTITE:
    dt = rome(r["data"]); h, a = r["casa"], r["ospite"]; th, ta = T(h), T(a)
    if fday(dt) != day:
        day = fday(dt)
    p = r.get("p") or {}; pm = r.get("p_mercato") or {}
    if p:
        bar = f'''<div class="pbar"><i style="width:{p['1']*100:.1f}%;background:{th['col']}"><b>1 · {pc(p['1'])}</b></i><i class="x" style="width:{p['X']*100:.1f}%"><b>X · {pc(p['X'])}</b></i><i style="width:{p['2']*100:.1f}%;background:{ta['col']}"><b>2 · {pc(p['2'])}</b></i></div>
        {ai_html(r)}'''
        kpis = f'''<div class="kpis"><div><small>Gol attesi (finale)</small><b>{r['lam'][0]:.2f} – {r['lam'][1]:.2f}</b></div>
        <div><small>Over 2.5</small><b>{pc(p.get('O2.5'))}</b></div><div><small>Goal</small><b>{pc(p.get('GG'))}</b></div>
        <div><small>Risultati più probabili</small><b>{' · '.join(f"{s} <em>{pc(q)}</em>" for s, q in r.get('risultati', []))}</b></div></div>'''
        pr = r.get("pronostico")
        bmh = (f'''<div class="tip"><div class="tipl">Pronostico</div><div class="tipm"><b>{E(pr["label"])}</b>{stella(pr)}</div>
        <div class="tipn"><span><small>Probabilità</small>{pc(pr["p"])}</span><span><small>Quota</small>{pr["quota"]:.2f}</span></div></div>''') if pr else '<div class="tip none"><div class="tipl">Pronostico</div><div class="tipm"><b>Nessun pronostico</b> · nessuna giocata con probabilità ≥ 55% e quota ≥ 1.30</div></div>'
        sel = sorted(r.get("selezioni", []), key=lambda x: (x["ht"], -x["ev"]))
        odds = "".join(f'<tr class="{"ht" if s["ht"] else ""}"><td>{E(s["label"])}{stella(s)}</td><td>{pc(s["p"])}</td><td><b>{s["quota"]:.2f}</b></td></tr>' for s in sel)
        oddsh = f'''<details class="odds"><summary>Tutte le quote Eurobet ({len(sel)}) · ultima variazione {fts(r.get('quote_ts'))}</summary>
        <table><thead><tr><th>Mercato</th><th>Probabilità</th><th>Quota</th></tr></thead><tbody>{odds}</tbody></table>
        </details>'''
    else:
        bar = kpis = bmh = ""; oddsh = '<p class="warn">Quote Eurobet NON VERIFICATE: nessuna probabilità calcolata.</p>'
    sh, sa = TS.get(h, {}), TS.get(a, {})
    stats = "".join([statbar("Elo", ELO.get(h), ELO.get(a), lambda v: f"{v:.0f}"), statbar("xG fatti / partita", sh.get("xg_for"), sa.get("xg_for")),
                     statbar("xG subiti / partita", sh.get("xg_against"), sa.get("xg_against"), higher_better=False),
                     statbar("Gol fatti / partita", sh.get("goals_for"), sa.get("goals_for")),
                     statbar("Tiri in porta / partita", sh.get("shots_on_target_for"), sa.get("shots_on_target_for")),
                     statbar("Clean sheet", sh.get("clean_sheets"), sa.get("clean_sheets"), lambda v: f"{v:.0f}")])
    fh = "".join(f'<i class="f {x["res"]}" title="{E(x["t"])}">{x["res"]}</i>' for x in forma(h))
    fa = "".join(f'<i class="f {x["res"]}" title="{E(x["t"])}">{x["res"]}</i>' for x in forma(a))
    notes = "".join(f'<li class="ctx">{E(c)}</li>' for c in r.get("contesto", [])) + "".join(f'<li>{E(c)}</li>' for c in r.get("avvisi", []))
    eurl = ""
    cards.append(f'''<article class="match" data-i="{r['id']}" style="--hc:{th['col']};--ac:{ta['col']}">
    <div class="mhead"><div class="team">{badge(h,'lg')}<div><div class="tn">{E(h)}</div><div class="form">{fh}</div></div></div>
    <div class="when"><b>{dt.hour:02d}:{dt.minute:02d}</b><small>{dt.day:02d}/{dt.month:02d}</small></div>
    <div class="team r"><div><div class="tn">{E(a)}</div><div class="form">{fa}</div></div>{badge(a,'lg')}</div></div>
    {bar}{kpis}{bmh}{('<ul class="notes">'+notes+'</ul>') if notes else ''}
    <div class="tabs2"><button class="on" data-t="s">Statistiche</button><button data-t="f">Formazioni</button><button data-t="q">Quote</button></div>
    <div class="pane on" data-p="s"><div class="stats">{stats}</div></div>
    <div class="pane" data-p="f"><div class="pitches"><div><h4>{badge(h)} {E(h)}</h4>{pitch(h)}</div><div><h4>{badge(a)} {E(a)}</h4>{pitch(a)}</div></div>
    </div>
    <div class="pane" data-p="q">{oddsh}</div></article>''')

# ------------------------------------------------------------------ triple
RISCHIO = {"semplice": "Rischio contenuto", "media": "Rischio intermedio", "aggressiva": "Rischio elevato"}
def gclass(g): return "pos" if g.startswith("Valore") else ("neu" if g.startswith("Neutra") else "neg")
def triple_html(nome):
    tt = (P.get("triple") or {}).get(nome, {}); out = []
    for tipo in ("semplice", "media", "aggressiva"):
        t = tt.get(tipo)
        if not t:
            out.append(f'<div class="tcard empty"><h3>Tripla {tipo}</h3><p>Non costruita: non ci sono tre selezioni abbastanza solide in questa fascia di quota. Meglio NO BET che una tripla forzata.</p></div>'); continue
        sel = "".join(f'''<li><div class="tsel"><span class="tm">{badge(s['match'].split('-')[0],'sm')}{badge(s['match'].split('-')[1],'sm')} {E(s['match'].replace('-',' – '))}</span>
        <b>{E(s['label'])}{stella(s)}</b></div><div class="tnum"><span>probabilità <b>{pc(s['p'])}</b></span><span>quota <b>{s['quota']:.2f}</b></span></div></li>''' for s in t["selezioni"])
        out.append(f'''<div class="tcard {tipo}"><div class="th"><h3>Tripla {tipo}</h3><span class="risk">{RISCHIO[tipo]}</span></div><ol>{sel}</ol>
        <div class="ttot"><div><small>Quota totale</small><b>{t['quota']:.2f}</b></div><div><small>Prob. congiunta</small><b>{pc(t['p'])}</b></div>
        </div>
        </div>''')
    return "".join(out)

# ------------------------------------------------------------------ marcatori
MC = P.get("marcatori") or {}
if MC.get("stato") == "ok":
    sc = "".join(f'''<div class="scard" style="--c:{T(x['squadra'])['col']}">{avatar(x['nome'], x['squadra'])}<div class="sn"><b>{E(x['nome'])}{stella(x)}</b>
    <span>{badge(x['squadra'],'sm')} {E(x['squadra'])} vs {E(x['avversario'])}</span></div>
    <div class="sp">{pc(x['p'])}<small>prob. di segnare</small></div>
    <div class="sg"><div><small>Quota Eurobet</small><b>{f"{x['quota']:.2f}" if x['quota'] else 'NON VERIFICATA'}</b></div>
    <div><small>xG/90</small><b>{x['xg90']:.2f}</b></div><div><small>Minuti attesi</small><b>{x['min_attesi']}</b></div></div>
    </div>''' for x in MC.get("lista", []))
    cb = MC.get("combinazione")
    cbh = (f'''<div class="combo"><h3>Combinazione dei 4 marcatori</h3><div class="ttot"><div><small>Quota</small><b>{cb['quota']:.2f}</b></div>
    <div><small>Prob. congiunta</small><b>{cb['p']*100:.1f}%</b></div></div>
    <p class="small">Rischio molto alto: basta un'esclusione o un cambio a sorpresa. {'Alcuni giocatori sono nella stessa partita: eventi correlati.' if cb['stessa_partita'] else 'Quattro partite diverse.'}</p></div>''') if cb else '<p class="muted">Combinazione non calcolabile: manca almeno una quota Eurobet.</p>'
    altri = "".join(f"<tr><td class=l>{badge(x['squadra'],'sm')} {E(x['nome'])}</td><td class=l>{E(x['avversario'])}</td><td>{x['xg90']:.2f}</td><td>{x['min_attesi']}</td><td>{pc(x['p'])}</td><td>{f2(x['quota'])}{stella(x)}</td></tr>" for x in MC.get("altri", []))
    marc_html = f'''<div class="scards">{sc}</div>{cbh}<h3 class="sec">Altri candidati</h3><div class="scroll"><table class="tbl"><thead><tr><th class=l>Giocatore</th><th class=l>Avversario</th><th>xG/90</th><th>Min.</th><th>Prob.</th><th>Quota</th></tr></thead><tbody>{altri}</tbody></table></div>
    '''
else:
    marc_html = f'<p class="warn">{E(MC.get("stato","dati non disponibili"))}</p>'

# ------------------------------------------------------------------ singole / evitare / classifica
sing = P.get("singole", [])
sing_html = "".join(f'''<div class="single">{badge(s['match'].split('-')[0],'sm')}{badge(s['match'].split('-')[1],'sm')}<div><b>{E(s['match'].replace('-',' – '))}</b><span>{E(s['label'])}{cat(s)}</span></div>
<div class="tnum"><span>@ <b>{s['quota']:.2f}</b></span><span>prob. {pc(s['p'])}</span><span>impl. {pc(s['p_impl'])}</span><span>EV {evtxt(s['ev'])}</span></div></div>''' for s in sing) or '<div class="nobet"><div class="nb">NO BET</div>Nessuna selezione supera i criteri: quota Eurobet reale, EV ≥ +5%, almeno 4 punti di vantaggio sulla probabilità implicita, probabilità ≥ 30%.</div>'
if 0 < len(sing) < 3: sing_html += f''
ev_html = "".join(f'<li><b>{E(x["match"].replace("-"," – "))}</b>: {E("; ".join(x["motivi"]))}</li>' for x in P.get("evitare", [])) or "<li>Nessuna partita segnalata.</li>"
cl = sorted(tab.items(), key=lambda kv: (-kv[1]["pt"], -(kv[1]["gf"]-kv[1]["gs"]), -kv[1]["gf"]))
cl_rows = "".join(f'''<tr><td>{i}</td><td class=l>{badge(t,'sm')} {E(t or '?')}</td><td><b>{s['pt']}</b></td><td>{s['g']}</td><td>{s['v']}</td><td>{s['n']}</td><td>{s['p']}</td><td>{s['gf']}</td><td>{s['gs']}</td><td>{s['gf']-s['gs']:+d}</td>
<td>{f2(TS.get(t,{}).get('xg_for'))}</td><td>{f2(TS.get(t,{}).get('xg_against'))}</td><td>{f"{ELO[t]:.0f}" if t in ELO else '—'}</td></tr>''' for i, (t, s) in enumerate(cl, 1))
BT = (P.get("metodo") or {}).get("backtest", {})
def _tar_html():
    TR = (P.get("metodo") or {}).get("taratura") or {}
    V = TR.get("verifica_stagione_corrente") or TR.get("taratura")
    if not V: return ""
    met = P.get("metodo") or {}
    def riga(nome, x, w):
        meglio = x["modello"] < x["mercato"]
        esito = '<b class="okc">l\'AI è più precisa del mercato</b>' if meglio else '<b class="koc">il mercato è più preciso dell\'AI</b>'
        diff = (x["mercato"] - x["modello"]) / x["mercato"] * 100
        return f"<tr><td class=l>{nome}</td><td>{esito}</td><td><b>{diff:+.1f}%</b></td></tr>"
    R = TR.get("roi_verifica") or {}
    gol = R.get("gol") or {}
    roi_txt = (f'<p class="hint">Giocate virtuali sui gol nella stagione in corso, quando la previsione supera la quota: {gol["giocate"]}, ROI {gol["roi"]*100:+.1f}%. Campione ancora piccolo: va confermato giornata dopo giornata.</p>'
               if gol.get("giocate") else "")
    return f'''<h2 class="daytitle">Affidabilità dell'AI</h2><div class="scroll"><table class="tbl"><thead><tr><th class=l>Mercato</th><th>Test su {V["partite"]} partite già giocate</th><th>Precisione AI vs mercato</th></tr></thead>
    <tbody>{riga("Chi vince (1X2)", V["logloss_1x2"], met.get("W_1X2"))}{riga("Gol (Over/Under)", V["logloss_gol"], met.get("W_GOL"))}</tbody></table></div>
    <p class="hint">Ogni settimana l'AI viene rimessa alla prova sulle partite già giocate, usando solo i dati disponibili prima di ciascuna partita, e confrontata con le quote di chiusura. I pronostici sono sempre quelli dell'AI: questo test dice quanto fidarsi, mercato per mercato (sopra zero = AI più precisa).</p>{roi_txt}'''
TAR_HTML = ""   # confronto AI/mercato: solo interno (dati/confronto_interno.json), non sul sito
FONTI = [("Calendario e risultati", "football-data.org", "fdorg_prossime.json"), ("Risultati, tiri, xG partita, quote di chiusura", "football-data.co.uk", "fdcouk_corrente.csv"),
         ("Quote Eurobet", "OddsPapi (eurobet.it)", "oddspapi_quote.json"), ("Statistiche, xG ed Elo di squadra", "StrikerAPI", "striker_team_stats.json"),
         ("xG dei giocatori", "StrikerAPI", "striker_xg_giocatori.json"), ("Formazioni", "StrikerAPI", "striker_giocate_recenti.json"),
         ("Allenatori", "football-data.org", "fdorg_squadre.json")]
fonti = "".join(f"<tr><td class=l>{a}</td><td class=l>{b}</td><td>{fts(META.get(c)) if META.get(c) else '<span class=warn>non scaricato</span>'}</td></tr>" for a, b, c in FONTI)
md = P.get("giornata"); first = rome(PARTITE[0]["data"]) if PARTITE else None; last = rome(PARTITE[-1]["data"]) if PARTITE else None
periodo = f"{first.day} – {last.day} {MESI[last.month-1]} {last.year}" if PARTITE else ""
tot_v = sum(1 for g in (P.get("triple") or {}).values() for t in g.values() if t)
hero_stats = f'''<div class="hs"><div><b>{len(PARTITE)}</b><small>partite</small></div><div><b>{sum(1 for r in PARTITE if r.get("pronostico"))}</b><small>pronostici</small></div><div><b>{tot_v}/6</b><small>triple</small></div>
<div><b>{len(MC.get('lista', []))}</b><small>marcatori</small></div></div>'''

slip_rows = "".join(f'''<tr><td class=l>{badge(r["casa"],"sm")}{badge(r["ospite"],"sm")} {E(r["casa"])} – {E(r["ospite"])} <small class="muted">{rome(r["data"]).strftime("%d/%m %H:%M")}</small></td>
<td class=l><b>{E(r["pronostico"]["label"])}</b>{stella(r["pronostico"])}</td><td>{pc(r["pronostico"]["p"])}</td><td><b>{r["pronostico"]["quota"]:.2f}</b></td></tr>'''
 if r.get("pronostico") else f'<tr><td class=l>{badge(r["casa"],"sm")}{badge(r["ospite"],"sm")} {E(r["casa"])} – {E(r["ospite"])}</td><td class=l colspan=3><span class=muted>Nessun pronostico</span></td></tr>' for r in PARTITE)

# ------------------------------------------------------------------ news (feed RSS: titolo, fonte, link)
import xml.etree.ElementTree as ET, email.utils, re as _re
SQUADRE_PRONO = {t for r in PARTITE for t in (r["casa"], r["ospite"])}
KEY = {t: [t.lower()] for t in SQUADRE_PRONO}
KEY.update({"Inter": ["inter ", "inter,", "inter:", "nerazzurr"], "Milan": ["milan", "rossoner"], "Juventus": ["juve"], "Roma": ["roma ", "roma,", "roma:", "giallorossi"],
            "Napoli": ["napoli", "azzurri di"], "Lazio": ["lazio", "biancocelest"], "Atalanta": ["atalanta", "dea "], "Fiorentina": ["fiorentina", "viola "]})
def teams_in(t):
    tl = " " + t.lower() + " "
    return [s for s in SQUADRE_PRONO if any(k in tl for k in KEY.get(s, [s.lower()]))]
NEWS = []
for f in glob.glob(os.path.join(D, "news", "*.xml")):
    src = os.path.basename(f)[:-4].replace("_", " ").replace("Calciomercatocom", "Calciomercato.com")
    try: root = ET.parse(f).getroot()
    except Exception: continue
    for it in root.iter("item"):
        t = html.unescape(html.unescape((it.findtext("title") or "").strip())); l = (it.findtext("link") or "").strip()
        if not t or not l.startswith("http"): continue
        try: dt = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
        except Exception: dt = None
        if dt and dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        tm = teams_in(t); serie_a = "serie a" in t.lower()
        if not tm and not serie_a: continue
        NEWS.append(dict(t=t, l=l, src=src, dt=dt, tm=tm, prob=bool(_re.search(r"probabil[ie]\s+formazion", t, _re.I)),
                         uff=bool(_re.search(r"formazion[ie]\s+ufficial", t, _re.I))))
seen = set(); news = []
for n in sorted(NEWS, key=lambda n: n["dt"] or datetime(2000, 1, 1, tzinfo=timezone.utc), reverse=True):
    k = _re.sub(r"\W+", "", n["t"].lower())[:60]
    if k in seen: continue
    seen.add(k); news.append(n)
def nitem(n):
    when = n["dt"].astimezone(ROME).strftime("%d/%m %H:%M") if n["dt"] else ""
    return f'<li><a href="{E(n["l"])}" target="_blank" rel="noopener">{E(n["t"])}</a><span>{"".join(badge(t,"sm") for t in n["tm"][:2])} {E(n["src"])} · {when}</span></li>'
form_html = ""
for r in PARTITE:
    h, a = r["casa"], r["ospite"]
    pr_l = [n for n in news if n["prob"] and h in n["tm"] and a in n["tm"]][:3]
    uf_l = [n for n in news if n["uff"] and h in n["tm"] and a in n["tm"]][:2]
    uff_pitch = LINEUPS.get(h, {}).get("ufficiale") and LINEUPS.get(a, {}).get("ufficiale")
    stato = '<span class="cat c-val">ufficiali</span>' if (uff_pitch or uf_l) else ('<span class="cat c-pro">probabili</span>' if pr_l else '<span class="cat c-nov">in attesa</span>')
    links = "".join(nitem(n) for n in (uf_l or pr_l))
    form_html += f'''<div class="fm"><div class="fmh">{badge(h,"sm")}{badge(a,"sm")} <b>{E(h)} – {E(a)}</b> {stato}<span class="muted">{rome(r["data"]).strftime("%d/%m %H:%M")}</span></div>{('<ul class="nl">'+links+'</ul>') if links else ''}</div>'''
# notizie: solo ultimi 3 giorni; le prime 8 in vista, le altre in un menu che si apre
_lim = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=3)
recenti = [n for n in news if n["dt"] and n["dt"] >= _lim] or news[:8]
altre = recenti[8:30]
news_html = f'''<h2 class="daytitle">Ultime notizie</h2><ul class="nl big">{"".join(nitem(n) for n in recenti[:8]) or "<li>Nessuna notizia scaricata.</li>"}</ul>
{f'<details class="info more"><summary>Altre notizie ({len(altre)})</summary><ul class="nl big">{"".join(nitem(n) for n in altre)}</ul></details>' if altre else ''}'''

# ------------------------------------------------------------------ bilancio dei pronostici
BIL = J("bilancio.json") or {}
NOMI_MERC = {"1": "1", "X": "X", "2": "2", "1X": "1X", "12": "12", "X2": "X2", "DNB1": "Draw No Bet 1", "DNB2": "Draw No Bet 2", "GG": "Goal", "NG": "No Goal"}
def nome_merc(m):
    if m.startswith("C:"): return m[2:]
    if m.startswith("SCORER:"): return "Segna: " + m[7:]
    mm = __import__("re").fullmatch(r"([OU])(\d\.5)", m)
    if mm: return ("Over " if mm.group(1) == "O" else "Under ") + mm.group(2)
    return NOMI_MERC.get(m, m)
def esito_html(e):
    return {1: '<span class="ok">✓</span>', 0: '<span class="ko">✗</span>', 2: '<span class="pu">=</span>'}.get(e, '<span class="pe">…</span>')
def kpi(t):
    if not t: return ""
    return f'''<div class="bk"><div><small>Vinte</small><b class="okc">{t["vinte"]}</b></div><div><small>Perse</small><b class="koc">{t["perse"]}</b></div>
    <div><small>% presa</small><b>{pc(t["hit"])}</b></div><div><small>Unità (puntata 1)</small><b class="{'okc' if (t['unita'] or 0) >= 0 else 'koc'}">{t["unita"]:+.2f}</b></div>
    <div><small>ROI</small><b>{"—" if t["roi"] is None else f"{t['roi']*100:+.1f}%"}</b></div><div><small>In attesa</small><b>{t["aperte"]}</b></div></div>'''
if BIL.get("giocate"):
    cat_rows = "".join(f'''<tr><td class=l>{E(c["nome"])}</td><td>{c["giocate"]}</td><td>{c["vinte"]}</td><td>{c["perse"]}</td><td>{pc(c["hit"])}</td>
    <td class="{'okc' if (c['unita'] or 0) >= 0 else 'koc'}">{c["unita"]:+.2f}</td><td>{"—" if c["roi"] is None else f"{c['roi']*100:+.1f}%"}</td><td>{c["aperte"]}</td></tr>''' for c in BIL["categorie"] if c["giocate"] or c["aperte"])
    gio_rows = "".join(f'''<tr><td class=l>Giornata {x["giornata"]}</td><td>{x["vinte"]}/{x["vinte"]+x["perse"]}</td><td>{pc(x["hit"])}</td>
    <td class="{'okc' if (x['unita'] or 0) >= 0 else 'koc'}">{x["unita"]:+.2f}</td><td>{x["aperte"]}</td></tr>''' for x in BIL["giornate"])
    def riga(x):
        prof = "" if x["profitto"] is None else "%+.2f" % x["profitto"]
        if x.get("dettaglio"):
            sub = ""
            for d in x["dettaglio"]:
                ris = ' <span class=muted>(%s)</span>' % d["risultato"] if d.get("risultato") else ""
                sub += '<div class="sub">%s %s · %s%s</div>' % (esito_html(d["esito"]), E(d["partita"].replace("-", " – ")), E(nome_merc(d["mercato"])), ris)
            return '<tr><td class=l><b>%s</b>%s</td><td>%.2f</td><td>%s</td><td>%s</td></tr>' % (E(x["desc"].capitalize()), sub, x["quota"], esito_html(x["esito"]), prof)
        tipo = {"pronostico": "pronostico", "marcatore": "marcatore", "singola": "singola"}.get(x["cat"], "")
        ris = (" · " + x["risultato"]) if x.get("risultato") else ""
        return ('<tr><td class=l>%s · <b>%s</b> <span class=muted>%s%s</span></td><td>%.2f</td><td>%s</td><td>%s</td></tr>'
                % (E(x["desc"].replace("-", " – ")), E(nome_merc(x["mercato"])), tipo, ris, x["quota"], esito_html(x["esito"]), prof))
    C = BIL.get("clv")
    tar_html = TAR_HTML
    # confronto con Pengwin: test interno, non pubblicato (dati/confronto_pengwin.json)
    clv_html = (f'''<h2 class="daytitle">Quote battute</h2><div class="bk bk3"><div><small>Quote migliori della chiusura</small><b class="{'okc' if C['battute'] >= C['peggiori'] else 'koc'}">{C["battute"]} su {C["n"]}</b></div>
    <div><small>Uguali</small><b>{C["pari"]}</b></div><div><small>Differenza media</small><b class="{'okc' if C['medio'] >= 0 else 'koc'}">{C["medio"]*100:+.1f}%</b></div></div>
    <p class="hint">Confronto tra la quota Eurobet all'uscita del report e quella poco prima del fischio d'inizio. Se la quota scende dopo il nostro pronostico, il mercato si è mosso nella nostra direzione: è il segnale più rapido per capire se il sistema vede giusto.</p>''') if C else ""
    bil_html = f'''{tar_html}{clv_html}<h2 class="daytitle">Bilancio complessivo</h2>{kpi(BIL.get("totale"))}
    <h2 class="daytitle">Per tipo di giocata</h2><div class="scroll"><table class="tbl"><thead><tr><th class=l>Tipo</th><th>Giocate</th><th>Vinte</th><th>Perse</th><th>% presa</th><th>Unità</th><th>ROI</th><th>In attesa</th></tr></thead><tbody>{cat_rows}</tbody></table></div>
    <h2 class="daytitle">Per giornata</h2><div class="scroll"><table class="tbl"><thead><tr><th class=l>Giornata</th><th>Prese</th><th>% presa</th><th>Unità</th><th>In attesa</th></tr></thead><tbody>{gio_rows}</tbody></table></div>
    <h2 class="daytitle">Ultime giocate</h2><div class="scroll"><table class="tbl"><thead><tr><th class=l>Giocata</th><th>Quota</th><th>Esito</th><th>Unità</th></tr></thead><tbody>{"".join(riga(x) for x in BIL["giocate"][:60])}</tbody></table></div>'''
else:
    bil_html = '<div class="nobet"><div class="nb">IN ATTESA</div>Il bilancio parte con la prima giornata giocata dopo l\'uscita del report.</div>'

# ------------------------------------------------------------------ web app (icona + manifest)
import zlib, struct, math as _m
def _png(path, n):
    bg, ac, wh = (10, 13, 18), (0, 227, 140), (238, 242, 247)
    rows = []
    c = n / 2; R = n * 0.34; r_in = n * 0.27
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            d = _m.hypot(x - c + 0.5, y - c + 0.5)
            col = bg
            if d <= R: col = ac
            if d <= r_in: col = bg
            # barra centrale (campo da calcio stilizzato)
            if abs(x - c) < n * 0.025 and d <= r_in: col = wh
            if abs(d - n * 0.09) < n * 0.022: col = wh
            row += bytes(col)
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)
for n in (180, 192, 512):
    p = os.path.join(OUTD, f"icona-{n}.png")
    if not os.path.exists(p): _png(p, n)
json.dump({"name": "Serie A Analyst", "short_name": "SA Analyst", "start_url": "./", "scope": "./", "display": "standalone",
           "background_color": "#0a0d12", "theme_color": "#0a0d12", "lang": "it",
           "icons": [{"src": "icona-192.png", "sizes": "192x192", "type": "image/png"}, {"src": "icona-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]},
          open(os.path.join(OUTD, "manifest.json"), "w"), ensure_ascii=False)

# ------------------------------------------------------------------ live (widget ufficiale SofaScore, gratuito)
SOFA = {}
for fx in (J("oddspapi_quote.json") or []):
    sid = (fx.get("externalProviders") or {}).get("sofascoreId")
    if sid: SOFA[(canon(fx.get("participant1Name")), canon(fx.get("participant2Name")))] = str(sid)
sofa_ids = [SOFA[(r["casa"], r["ospite"])] for r in PARTITE if (r["casa"], r["ospite"]) in SOFA]
if sofa_ids:
    ids = ",".join(sofa_ids)
    live_html = f'''<div class="livewrap"><iframe id="sofa-fixtures-embed-{ids}" src="https://widgets.sofascore.com/it/embed/fixtures?eventIds={ids}&showCompetitionLogo=true&widgetTitle=Serie+A&widgetTheme=dark"
    frameborder="0" scrolling="no" style="width:100%;height:{110 + 115*len(sofa_ids)}px;max-width:480px;border:0" title="Risultati live Serie A"></iframe>
    <div class="sofa">Risultati forniti da <a target="_blank" rel="noopener" href="https://sofascore.com/">Sofascore</a></div></div>'''
else:
    live_html = '<p class="warn">Widget non disponibile: identificativi delle partite non trovati.</p>'


# ------------------------------------------------------------------ fantacalcio
import unicodedata as _ud, math as _mf
def _nn(s):
    s = _ud.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("-", " ").replace(".", " ").replace("'", " ")
    return [t for t in s.split() if t]
def _same(a, b):
    a, b = _nn(a), _nn(b)
    if not a or not b: return False
    if set(a) <= set(b) or set(b) <= set(a): return True
    return a[-1] == b[-1] and a[0][0] == b[0][0]
def motivo_it(a):
    """Motivo dell'assenza in italiano (API-Football lo da' in inglese)."""
    if a.get("dubbio"): return "in dubbio" + (f" ({motivo_it(dict(a, dubbio=False))})" if a.get("motivo") else "")
    m = (a.get("motivo") or "").lower()
    for k, v in (("red card", "squalificato (rosso)"), ("yellow", "squalificato (ammonizioni)"), ("suspen", "squalificato"),
                 ("knee", "infortunio al ginocchio"), ("ankle", "infortunio alla caviglia"), ("hamstring", "infortunio muscolare (flessore)"),
                 ("thigh", "infortunio muscolare (coscia)"), ("calf", "infortunio al polpaccio"), ("groin", "infortunio all'inguine"),
                 ("muscle", "infortunio muscolare"), ("back", "infortunio alla schiena"), ("foot", "infortunio al piede"),
                 ("shoulder", "infortunio alla spalla"), ("head", "colpo alla testa"), ("illness", "malattia"), ("virus", "malattia"),
                 ("national", "impegno con la nazionale"), ("injury", "infortunato"), ("knock", "acciaccato")):
        if k in m: return v
    return "indisponibile"
def _leaders(f):
    return (J(f) or {}).get("data", {}).get("leaders", [])
FANTA = []
def _fanta():
    ruolo = {"Goalkeeper": "P", "Defence": "D", "Midfield": "C", "Offence": "A"}
    AB = {t["abbrev"]: canon(t["display_name"]) for t in (J("striker_team_stats.json") or {}).get("data", {}).get("teams", [])}
    XG = _leaders("striker_xg_tutti.json") or _leaders("striker_xg_giocatori.json")
    AS = _leaders("striker_assist.json"); SV = _leaders("striker_parate.json")
    GO = _leaders("striker_gol_tutti.json") or _leaders("striker_gol_giocatori.json")
    YC = _leaders("striker_gialli.json"); RC = _leaders("striker_rossi.json"); CS = _leaders("striker_cleansheet.json")
    def cerca(lista, team, nome):
        return next((p for p in lista if AB.get(p.get("team")) == team and _same(nome, p.get("name"))), None)
    match = {}
    for r in PARTITE:
        if not r.get("lam"): continue
        for i, (t, o) in enumerate(((r["casa"], r["ospite"]), (r["ospite"], r["casa"]))):
            match[t] = dict(opp=o, casa=(i == 0), lt=r["lam"][i], lo=r["lam"][1 - i], data=r["data"],
                            ass=(r.get("assenze") or {}).get(t, []))
    for tm in (J("fdorg_squadre.json") or {}).get("teams", []):
        team = canon(tm.get("name"))
        if team not in match: continue
        mc = match[team]; ts = TS.get(team) or {}; gteam = ts.get("games") or 1; xgf = ts.get("xg_for") or 1.3
        lu = LINEUPS.get(team) or {}
        xi = [p["name"] for p in lu.get("xi", [])]
        for pl in tm.get("squad", []):
            r_ = ruolo.get(pl.get("position"))
            if not r_: continue
            nome = pl["name"]
            sx = cerca(XG, team, nome) or (cerca(SV, team, nome) if r_ == "P" else None)
            mins = (sx or {}).get("minutes") or 0
            mexp = min(mins / gteam, 90)
            # probabilita' di giocare titolare: minuti abituali + titolare nell'ultima formazione nota;
            # con la formazione ufficiale si usa quella; gli assenti segnalati non giocano
            nell_xi = any(_same(nome, n) for n in xi)
            if lu.get("ufficiale") and lu.get("vs") == mc["opp"]:
                pg = 0.95 if nell_xi else 0.10; fonte = "ufficiale"
            elif sx is None and xi:                      # nessun dato minuti: conta solo l'ultima formazione
                pg = 0.85 if nell_xi else 0.10; fonte = "stima"
            elif False:
                pg = 0.95 if nell_xi else 0.10; fonte = "ufficiale"
            else:
                pg = 0.6 * min(0.95, mexp / 80) + 0.4 * (0.90 if nell_xi else 0.05) if xi else min(0.95, mexp / 80); fonte = "stima"
            a = next((x for x in mc["ass"] if _same(x["nome"], nome)), None)
            if a: pg = pg * 0.5 if a.get("dubbio") else 0.0
            # rendimento atteso se gioca (80 minuti), scalato sulla partita: gol attesi squadra / xG medio stagionale
            fatt = mc["lt"] / xgf
            prior_g = {"A": 0.35, "C": 0.14, "D": 0.06, "P": 0.0}[r_]; prior_a = {"A": 0.12, "C": 0.12, "D": 0.06, "P": 0.0}[r_]
            xg = float((sx or {}).get("value") or 0)
            ax = cerca(AS, team, nome); assi = float((ax or {}).get("value") or 0)
            g90 = (xg + prior_g * 3) / (mins + 270) * 90; a90 = (assi + prior_a * 3) / (mins + 270) * 90
            eg = g90 * 80 / 90 * fatt; ea = a90 * 80 / 90 * fatt
            pcs = _mf.exp(-mc["lo"])                       # porta inviolata (Poisson)
            voto = 6 + max(-0.5, min(0.5, 0.25 * (mc["lt"] - mc["lo"])))
            fv = voto + 3 * eg + 1 * ea
            if r_ == "P": fv += -mc["lo"] + 1 * pcs
            if r_ == "D": fv += 0.5 * pcs
            # statistiche reali della stagione (StrikerAPI): presenze, gol, assist, cartellini, porte inviolate
            val = lambda lst: float((cerca(lst, team, nome) or {}).get("value") or 0)
            pres = max([int((x or {}).get("games") or 0) for x in (sx, cerca(GO, team, nome), ax)] + [0])
            gol, gi, ro, cs = val(GO), val(YC), val(RC), val(CS)
            bonus = (3*gol + assi - 0.5*gi - 1*ro + (cs if r_ == "P" else 0)) / pres if pres else None
            FANTA.append(dict(n=nome, t=team, r=r_, o=mc["opp"], c=mc["casa"], pg=round(pg, 2), fv=round(fv, 2),
                              s=round(pg * fv, 2), pgol=round(1 - _mf.exp(-eg), 2), pcs=round(pcs, 2), f=fonte,
                              a=motivo_it(a) if a else "", inf=bool(a and not a.get("dubbio")),
                              st=dict(p=pres, m=int(mins), g=int(gol), as_=int(assi), y=int(gi), rc=int(ro), cs=int(cs),
                                      mg=round(gol/pres, 2) if pres else None, ma=round(assi/pres, 2) if pres else None,
                                      b=round(bonus, 2) if bonus is not None else None)))
# --- statistiche ufficiali Fantacalcio (export dell'utente da fantacalcio.it, caricato in dati/) ---
def leggi_xlsx(path, foglio=1):
    """Lettore xlsx minimo (solo libreria standard): righe del foglio come liste di valori."""
    import zipfile, xml.etree.ElementTree as ETx, re as _r
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    z = zipfile.ZipFile(path); ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ETx.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    righe = []
    for row in ETx.fromstring(z.read(f"xl/worksheets/sheet{foglio}.xml")).iter("{%s}row" % ns["m"]):
        r = {}
        for c in row.findall("m:c", ns):
            col = _r.match(r"[A-Z]+", c.get("r")).group(0); n = 0
            for ch in col: n = n * 26 + ord(ch) - 64
            v = c.find("m:v", ns); t = c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
            elif v is None: val = None
            elif t == "s": val = ss[int(v.text)]
            else:
                try: val = float(v.text); val = int(val) if val.is_integer() else val
                except ValueError: val = v.text
            r[n - 1] = val
        if r: righe.append([r.get(i) for i in range(max(r) + 1)])
    return righe
def _fm(a, b):
    """Stesso giocatore? Gestisce 'Paz N.', 'Martinez L.', 'D. Malen', 'Nico Paz', accenti."""
    def sp(s):
        t = _nn(s); return [x for x in t if len(x) > 1], [x for x in t if len(x) == 1]
    wa, ia = sp(a); wb, ib = sp(b)
    if not wa or not wb: return False
    if not (set(wa) <= set(wb) or set(wb) <= set(wa)): return False
    if ia and not any(w[0] == ia[0] for w in wb if w not in wa): return not [w for w in wb if w not in wa]
    if ib and not any(w[0] == ib[0] for w in wa if w not in wb): return not [w for w in wa if w not in wb]
    return True
FC_FILE = sorted(glob.glob(os.path.join(D, "[Ss]tatistiche_[Ff]antacalcio*.xlsx")))
FC_INFO = ""
def _fanta_fc(path):
    global FC_INFO
    righe = leggi_xlsx(path)
    hdr = next(i for i, r in enumerate(righe) if r and r[0] == "Id")
    H = righe[hdr]; rows = [dict(zip(H, r)) for r in righe[hdr + 1:] if r and r[0] is not None]
    FC_INFO = f"Statistiche Fantacalcio dopo {max(int(r.get('Pv') or 0) for r in rows)} giornate (export caricato)"
    AB = {t["abbrev"]: canon(t["display_name"]) for t in (J("striker_team_stats.json") or {}).get("data", {}).get("teams", [])}
    XG = _leaders("striker_xg_tutti.json") or _leaders("striker_xg_giocatori.json")
    AS = _leaders("striker_assist.json")
    def cerca(lista, team, nome):
        return next((p for p in lista if AB.get(p.get("team")) == team and _fm(nome, p.get("name"))), None)
    match = {}
    for r in PARTITE:
        if not r.get("lam"): continue
        for i, (t, o) in enumerate(((r["casa"], r["ospite"]), (r["ospite"], r["casa"]))):
            match[t] = dict(opp=o, casa=(i == 0), lt=r["lam"][i], lo=r["lam"][1 - i], ass=(r.get("assenze") or {}).get(t, []))
    gsq = {}
    for x in rows:
        t = canon(x.get("Squadra")); gsq[t] = max(gsq.get(t, 0), int(x.get("Pv") or 0))
    for x in rows:
        team = canon(x.get("Squadra")); r_ = x.get("R")
        if team not in match or r_ not in ("P", "D", "C", "A"): continue
        mc = match[team]; ts = TS.get(team) or {}; gteam = ts.get("games") or gsq.get(team) or 1; xgf = ts.get("xg_for") or 1.3
        nome = str(x["Nome"]); pv = int(x.get("Pv") or 0); mv = float(x.get("Mv") or 0); fm = float(x.get("Fm") or 0)
        lu = LINEUPS.get(team) or {}; xi = [p["name"] for p in lu.get("xi", [])]; nell_xi = any(_fm(nome, n) for n in xi)
        sx = cerca(XG, team, nome); mins = (sx or {}).get("minutes") or 0
        reg = min(1.0, pv / gteam) if gteam else 0
        if lu.get("ufficiale") and lu.get("vs") == mc["opp"]:
            pg = 0.95 if nell_xi else 0.10; fonte = "ufficiale"
        else:
            base = min(0.95, (mins / gteam) / 80) if sx else min(0.95, reg * 0.9)
            pg = 0.6 * base + 0.4 * (0.90 if nell_xi else 0.05) if xi else base; fonte = "stima"
        a = next((y for y in mc["ass"] if _fm(y["nome"], nome)), None)
        if a: pg = pg * 0.5 if a.get("dubbio") else 0.0
        # fantavoto atteso = media voto (stabilizzata) + bonus attesi in QUESTA partita
        mvs = (mv * pv + 6 * 3) / (pv + 3) if pv else 6.0
        adj = max(-0.25, min(0.25, 0.12 * (mc["lt"] - mc["lo"])))
        fatt = mc["lt"] / xgf; pcs = _mf.exp(-mc["lo"])
        prior_b = {"A": 0.9, "C": 0.4, "D": 0.2, "P": -1.0}[r_]
        bh = (fm - mv) if pv else prior_b
        bhs = (bh * pv + prior_b * 3) / (pv + 3)
        if r_ == "P":
            bonus = 0.5 * bhs + 0.5 * (-mc["lo"] + pcs); eg = 0.0
        else:
            prior_g = {"A": 0.35, "C": 0.14, "D": 0.06}[r_]; prior_a = {"A": 0.12, "C": 0.12, "D": 0.06}[r_]
            ax = cerca(AS, team, nome); assi = float((ax or {}).get("value") or x.get("Ass") or 0)
            if sx:
                g90 = (float(sx.get("value") or 0) + prior_g * 3) / (mins + 270) * 90; a90 = (assi + prior_a * 3) / (mins + 270) * 90
                eg = g90 * 80 / 90 * fatt; bm = 3 * eg + a90 * 80 / 90 * fatt
                bonus = 0.5 * bhs * fatt + 0.5 * bm
            else:
                eg = max(0.0, (float(x.get("Gf") or 0) + prior_g * 3) / (pv + 3)) * fatt
                bonus = bhs * fatt
        fv = mvs + adj + bonus
        FANTA.append(dict(n=nome, t=team, r=r_, o=mc["opp"], c=mc["casa"], pg=round(pg, 2), fv=round(fv, 2), s=round(pg * fv, 2),
                          pgol=round(1 - _mf.exp(-eg), 2), pcs=round(pcs, 2), f=fonte, a=motivo_it(a) if a else "",
                          inf=bool(a and not a.get("dubbio")),
                          st=dict(fc=1, p=pv, mv=mv, fm=fm, g=int(x.get("Gf") or 0), gs=int(x.get("Gs") or 0), as_=int(x.get("Ass") or 0),
                                  y=int(x.get("Amm") or 0), rc=int(x.get("Esp") or 0), rp=int(x.get("Rp") or 0),
                                  mg=round(int(x.get("Gf") or 0) / pv, 2) if pv else None, ma=round(int(x.get("Ass") or 0) / pv, 2) if pv else None)))

if FC_FILE:
    try: _fanta_fc(FC_FILE[-1])
    except Exception as e: print("Statistiche Fantacalcio non lette:", e); FANTA.clear(); _fanta()
else:
    _fanta()

FANTA_JSON = json.dumps(FANTA, ensure_ascii=False).replace("</", "<\\/")
GG = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
sel_opts = "".join(f'<option value="{r["id"]}">{GG[rome(r["data"]).weekday()]} {rome(r["data"]).strftime("%d/%m %H:%M")} · {E(r["casa"])} – {E(r["ospite"])}</option>' for r in PARTITE)
gtitle = f'<div class="gday"><span class="md">GIORNATA {md or "—"}</span><span>{periodo}</span></div>'

CSS = """
:root{--bg:#0a0d12;--bg2:#11161e;--card:#151b25;--card2:#1b2330;--line:#243042;--ink:#eef2f7;--mut:#8b97a8;--acc:#00e38c;--acc2:#ffd23f;--neg:#ff5468;--neu:#9aa6b8}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#10324a 0,transparent 60%),radial-gradient(900px 500px at -10% 10%,#0d3b2c 0,transparent 55%),var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,-apple-system,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:env(safe-area-inset-top) max(16px,env(safe-area-inset-right)) 80px max(16px,env(safe-area-inset-left))}
.hero{padding:34px 0 18px;display:flex;flex-wrap:wrap;gap:20px;align-items:flex-end;justify-content:space-between}
.brand{font:800 44px/0.95 'Barlow Condensed','Arial Narrow',sans-serif,sans-serif;letter-spacing:.5px;text-transform:uppercase}.brand span{color:var(--acc)}
.brand small{display:block;font:600 15px Inter;letter-spacing:0;text-transform:none;color:var(--mut);margin-top:10px}
.gday{display:flex;align-items:center;gap:10px;margin:4px 0 14px;color:var(--mut);font-size:14px}
.gday .md{display:inline-block;background:var(--acc);color:#04140c;font:800 13px Inter;padding:4px 10px;border-radius:99px;letter-spacing:.5px}
.brand .md{display:inline-block;background:var(--acc);color:#04140c;font:800 13px Inter;padding:4px 10px;border-radius:99px;margin-right:8px;letter-spacing:.5px}
.hs{display:flex;gap:10px}.hs div{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 16px;text-align:center;min-width:84px}
.hs b{display:block;font:800 26px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif}.hs small{color:var(--mut);font-size:12px}
nav{position:sticky;top:0;z-index:5;background:rgba(10,13,18,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);margin:0 -16px 18px;padding:10px 16px;display:flex;gap:6px;overflow-x:auto}
nav a{color:var(--mut);text-decoration:none;font-weight:600;font-size:14px;padding:8px 14px;border-radius:99px;white-space:nowrap}nav a.on{background:var(--ink);color:var(--bg)}
.view{display:none}.view.on{display:block;animation:f .25s}@keyframes f{from{opacity:0;transform:translateY(4px)}}
.banner{background:linear-gradient(90deg,rgba(255,210,63,.12),rgba(255,210,63,.03));border:1px solid rgba(255,210,63,.35);border-radius:14px;padding:12px 16px;font-size:14px;margin-bottom:8px}
h2.day{font:700 15px Inter;text-transform:uppercase;letter-spacing:2px;color:var(--mut);margin:34px 0 12px;display:flex;align-items:center;gap:12px}h2.day:after{content:"";flex:1;height:1px;background:var(--line)}
.match{position:relative;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin-bottom:16px;overflow:hidden}
.match:before{content:"";position:absolute;inset:0 0 auto 0;height:4px;background:linear-gradient(90deg,var(--hc) 0 50%,var(--ac) 50% 100%)}
.mhead{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px}.team{display:flex;align-items:center;gap:12px}.team.r{justify-content:flex-end;text-align:right}
.tn{font:700 24px/1.1 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;text-transform:uppercase;letter-spacing:.3px}
.when{text-align:center}.when b{display:block;font:800 26px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;color:var(--acc)}.when small{color:var(--mut)}
.badge{--c:#333;--a:#fff;display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--c);border:2px solid var(--a);font:800 9px Inter;letter-spacing:.2px;flex:none;margin-right:2px;box-shadow:0 2px 8px rgba(0,0,0,.4)}
.badge.lg{width:56px;height:56px;font-size:14px;border-width:3px}.badge.sm{width:22px;height:22px;font-size:8px}
.form{display:flex;gap:3px;margin-top:5px}.team.r .form{justify-content:flex-end}.f{font:700 10px Inter;font-style:normal;width:18px;height:18px;border-radius:4px;display:grid;place-items:center;cursor:help}
.f.V{background:var(--acc);color:#04140c}.f.N{background:#4a5568}.f.P{background:var(--neg)}
.pbar{display:flex;height:34px;border-radius:10px;overflow:hidden;margin:18px 0 6px;background:var(--card2)}.pbar i{display:flex;align-items:center;justify-content:center;min-width:44px;font-style:normal;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.6)}
.pbar i.x{background:#3a4556}.pbar b{font:700 13px Inter;white-space:nowrap}.pfine{font-size:12px;color:var(--mut)}
.aibox{border:1px solid #243041;border-radius:12px;padding:10px 12px;margin:10px 0;background:#0f151d}.aih{font-size:13px;margin-bottom:6px}
.aik{display:flex;gap:18px;margin-bottom:6px}.aik span{display:flex;flex-direction:column}.aik small{font-size:11px;color:var(--mut)}.aik b{font:700 20px 'Barlow Condensed'}
.ait td,.ait th{padding:4px 8px}.assh{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;margin:8px 0 4px}.ass{font-size:13px;margin:2px 0}
.kpis{display:grid;grid-template-columns:repeat(3,auto) 1fr;gap:10px;margin:14px 0}.kpis div{background:var(--card2);border-radius:12px;padding:8px 12px}.kpis small{display:block;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.8px}
.kpis b{font:700 18px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif}.kpis em{font-style:normal;color:var(--mut);font-size:13px}
.pick{background:linear-gradient(90deg,rgba(0,227,140,.10),transparent);border-left:3px solid var(--acc);padding:9px 12px;border-radius:8px;font-size:14px}.pick .lbl{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.8px;margin-right:6px}
.tagv,.tagn{font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px;margin-left:6px}.tagv{background:var(--acc);color:#04140c}.tagn{background:#2a3445;color:var(--mut)}
.ev{font-weight:700}.ev.pos{color:var(--acc)}.ev.neu{color:var(--acc2)}.ev.neg{color:var(--neg)}.ev.na{color:var(--mut)}
.notes{margin:10px 0 0;padding:0;list-style:none;font-size:13px}.notes li{color:var(--acc2);padding:2px 0}.notes li:before{content:"⚠ "}.notes li.ctx{color:#7cc4ff}.notes li.ctx:before{content:"ℹ "}
.tabs2{display:flex;gap:4px;margin:16px 0 10px;border-bottom:1px solid var(--line)}.tabs2 button{background:none;border:0;color:var(--mut);font:600 14px Inter;padding:8px 12px;cursor:pointer;border-bottom:2px solid transparent}
.tabs2 button.on{color:var(--ink);border-color:var(--acc)}.pane{display:none}.pane.on{display:block}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:6px 28px}@media(max-width:760px){.stats{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}.tn{font-size:18px}.badge.lg{width:42px;height:42px}}
.sb{display:grid;grid-template-columns:52px 1fr 52px;align-items:center;font-size:14px;font-variant-numeric:tabular-nums}.sb span:last-of-type{text-align:right}.sb .hi{color:var(--acc);font-weight:700}
.sbl{text-align:center;color:var(--mut);font-size:12px}.sbar{grid-column:1/-1;height:5px;background:var(--ac);border-radius:9px;overflow:hidden;margin-top:3px}.sbar i{display:block;height:100%;background:var(--hc)}
.pitches{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:640px){.pitches{grid-template-columns:1fr}}.pitches h4{margin:0 0 6px;display:flex;align-items:center;gap:6px}
.pitch{width:100%;max-width:330px;display:block}.grass{fill:#0f5a34}.lines *{fill:none;stroke:rgba(255,255,255,.35);stroke-width:1.5}
.jn{font:800 11px Inter;text-anchor:middle}.pn{font:600 10px Inter;text-anchor:middle;fill:#fff;paint-order:stroke;stroke:#063;stroke-width:3px}
.ptag{font-size:12px;color:var(--acc2);margin-bottom:6px}.ptag.off{color:var(--acc)}
details.odds summary{cursor:pointer;color:var(--mut);font-size:14px;margin-bottom:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}.odds td,.odds th,.tbl td,.tbl th{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;font-size:14px}
.odds td:first-child,.odds th:first-child,.tbl .l{text-align:left}th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.6px}tr.ht td{color:var(--mut)}
.tbl{background:var(--card);border-radius:14px;overflow:hidden}.scroll{overflow-x:auto}
.daytitle{font:800 30px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;text-transform:uppercase;margin:26px 0 12px}
.tgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}@media(max-width:900px){.tgrid{grid-template-columns:1fr}}
.tcard{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;display:flex;flex-direction:column}.tcard.semplice{border-top:4px solid var(--acc)}.tcard.media{border-top:4px solid var(--acc2)}.tcard.aggressiva{border-top:4px solid var(--neg)}
.tcard.empty{opacity:.75;border-style:dashed}.th{display:flex;justify-content:space-between;align-items:center}.tcard h3{margin:0;font:800 22px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;text-transform:uppercase}.risk{font-size:12px;color:var(--mut)}
.tcard ol{list-style:none;padding:0;margin:12px 0;flex:1}.tcard li{padding:10px 0;border-bottom:1px solid var(--line)}.tsel{display:flex;flex-direction:column;gap:3px}.tm{font-size:13px;color:var(--mut);display:flex;align-items:center;gap:4px}
.tnum{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--mut);margin-top:4px}.tnum b{color:var(--ink)}
.ttot{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.ttot div{background:var(--card2);border-radius:10px;padding:8px}.ttot small{display:block;color:var(--mut);font-size:11px}.ttot b{font:800 22px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif}
.verdict{margin-top:10px;text-align:center;font-weight:700;font-size:13px;padding:7px;border-radius:10px}.verdict.pos{background:rgba(0,227,140,.15);color:var(--acc)}.verdict.neu{background:rgba(255,210,63,.12);color:var(--acc2)}.verdict.neg{background:rgba(255,84,104,.12);color:var(--neg)}
.scards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}@media(max-width:900px){.scards{grid-template-columns:1fr 1fr}}@media(max-width:520px){.scards{grid-template-columns:1fr}}
.scard{background:linear-gradient(180deg,color-mix(in srgb,var(--c) 30%,var(--card)) 0,var(--card) 45%);border:1px solid var(--line);border-radius:18px;padding:16px}
.avatar{--c:#333;--a:#fff;width:64px;height:64px;border-radius:50%;display:grid;place-items:center;font:800 24px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;background:var(--c);box-shadow:0 0 0 3px var(--a)}
.sn{margin:10px 0}.sn b{display:block;font:700 20px/1.1 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;text-transform:uppercase}.sn span{font-size:13px;color:var(--mut);display:flex;align-items:center;gap:4px;margin-top:4px}
.sp{font:800 40px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;color:var(--acc)}.sp small{display:block;font:500 12px Inter;color:var(--mut)}
.sg{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0}.sg div{background:var(--card2);border-radius:8px;padding:6px 8px}.sg small{display:block;font-size:11px;color:var(--mut)}
.combo{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:16px 0}.combo h3,.sec{font:800 20px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;text-transform:uppercase;margin:0 0 10px}.sec{margin:24px 0 10px}
.single{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin-bottom:10px}.single>div:nth-child(3){flex:1}.single span{display:block;color:var(--mut);font-size:14px}
.nobet{background:var(--card);border:1px dashed var(--line);border-radius:14px;padding:18px;font-weight:700;text-align:center}
.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin-bottom:14px}.box h3{margin-top:0;font:800 20px 'Barlow Condensed','Arial Narrow',sans-serif-condensed,sans-serif;text-transform:uppercase}
.muted{color:var(--mut)}.small{font-size:12px}.warn{color:var(--acc2)}a{color:var(--acc)}
.qin{width:74px;background:var(--card2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:5px 8px;font:600 14px Inter;text-align:right}.qin:focus{outline:none;border-color:var(--acc)}
.man{align-self:flex-start;font-size:10px;font-weight:700;background:#2b3a55;color:#9cc3ff;padding:2px 6px;border-radius:99px;margin-left:4px}
.est{align-self:flex-start;font-size:10px;font-weight:700;background:#4a3b12;color:#ffd23f;padding:2px 6px;border-radius:99px;margin-left:4px}
.cat{font:700 10px Inter;padding:2px 7px;border-radius:99px;margin-left:6px;vertical-align:middle;text-transform:uppercase;letter-spacing:.4px}
.c-val{background:var(--acc);color:#04140c}.c-pro{background:#1f4b7a;color:#cfe6ff}.c-ris{background:#5a1d27;color:#ffb3bd}.c-nov{background:#2a3445;color:var(--mut)}
.nobet .nb{font:800 44px 'Barlow Condensed','Arial Narrow',sans-serif;color:var(--acc2);letter-spacing:1px}
.copybar{display:flex;gap:10px;align-items:center;margin:14px 0}.copybar button{background:var(--acc);color:#04140c;border:0;border-radius:99px;padding:9px 16px;font:700 14px Inter;cursor:pointer}
.box h3{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.tip{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:14px;background:linear-gradient(90deg,rgba(0,227,140,.14),rgba(0,227,140,.02));border:1px solid rgba(0,227,140,.35);border-radius:14px;padding:12px 16px;margin-top:4px}
.tip.none{background:var(--card2);border-color:var(--line);grid-template-columns:auto 1fr}.tipl{font:800 13px Inter;text-transform:uppercase;letter-spacing:1.5px;color:var(--acc)}.tip.none .tipl{color:var(--mut)}
.tipm b{font:700 22px 'Barlow Condensed','Arial Narrow',sans-serif}.tipn{display:flex;gap:16px}.tipn span{text-align:right;font:800 20px 'Barlow Condensed','Arial Narrow',sans-serif}.tipn small{display:block;font:500 11px Inter;color:var(--mut)}
@media(max-width:640px){.tip{grid-template-columns:1fr}.tipn{justify-content:flex-start}}
.slip td{vertical-align:middle}.ngrid{display:grid;grid-template-columns:1.4fr 1fr;gap:24px}@media(max-width:860px){.ngrid{grid-template-columns:1fr}}
.nl{list-style:none;padding:0;margin:0}.nl li{padding:10px 0;border-bottom:1px solid var(--line)}.nl a{color:var(--ink);text-decoration:none;font-weight:600}.nl a:hover{color:var(--acc)}
.nl span{display:flex;align-items:center;gap:4px;color:var(--mut);font-size:12px;margin-top:3px}.nl.big li{font-size:15px}
.fm{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 14px;margin-bottom:8px}.fmh{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.fmh .muted{margin-left:auto;font-size:12px}
.fm .nl li{padding:6px 0;font-size:13px}
.livewrap{display:flex;flex-direction:column;align-items:center}.sofa{font-size:12px;color:var(--mut);margin-top:6px}.sofa a{color:var(--mut)}
.bk{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}@media(max-width:760px){.bk{grid-template-columns:repeat(3,1fr)}}
.bk div{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px}.bk small{display:block;color:var(--mut);font-size:12px}.bk b{font:800 28px 'Barlow Condensed','Arial Narrow',sans-serif}
.okc{color:var(--acc)}.koc{color:var(--neg)}.ok{color:var(--acc);font-weight:800}.ko{color:var(--neg);font-weight:800}.pu{color:var(--acc2);font-weight:800}.pe{color:var(--mut)}
.sub{font-size:13px;color:var(--mut);margin-top:3px}.bk3{grid-template-columns:repeat(3,1fr)}.hint{font-size:13px;color:var(--mut);margin:8px 0 0}
.legend{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:0 0 14px;font-size:14px}
.star{color:#ffd23f;font-size:1.05em;margin-left:4px}
details.info{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:0 0 14px}details.info summary{cursor:pointer;color:var(--acc);font-weight:600;font-size:14px}
details.info p{font-size:14px;color:var(--ink);margin:8px 0}
.tipn{flex-wrap:wrap}
.subnav{display:none;gap:6px;margin:-8px 0 16px;overflow-x:auto}.subnav.on{display:flex}
.subnav a{color:var(--mut);text-decoration:none;font-weight:600;font-size:13px;padding:6px 12px;border-radius:99px;border:1px solid var(--line);white-space:nowrap}.subnav a.on{color:var(--acc);border-color:var(--acc)}
.pick{display:flex;flex-direction:column;gap:6px;margin:0 0 16px}.pick label,.fmod label{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
.pick select,.fmod select,.fadd input{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:12px;padding:12px 14px;font:600 15px Inter;width:100%}
.fbox{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin:0 0 16px}.fbox .daytitle{margin-top:0}
.fadd{display:flex;gap:8px}.fadd button{background:var(--acc);color:#04130c;border:0;border-radius:12px;padding:0 16px;font:700 14px Inter;cursor:pointer}
.fg{margin:10px 0}.fgt{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.fp{display:inline-flex;align-items:center;gap:6px;background:#0f151d;border:1px solid var(--line);border-radius:99px;padding:4px 6px 4px 4px;margin:0 6px 6px 0;font-size:14px}
.fp small{color:var(--mut)}.fr{background:#1b2531;color:var(--acc);border:0;border-radius:99px;font:700 12px Inter;padding:3px 4px}
.fx{background:none;border:0;color:var(--mut);font-size:18px;cursor:pointer;line-height:1}
.fmod{display:flex;flex-direction:column;gap:6px;margin-bottom:6px}
.fpitch{background:linear-gradient(#0f3d26,#0b2e1d);border:1px solid #1d5a3a;border-radius:16px;padding:12px 6px;display:flex;flex-direction:column;gap:12px}
.frow{display:flex;justify-content:center;gap:5px;flex-wrap:nowrap}
.fc{background:rgba(10,13,18,.82);border-radius:12px;padding:6px 5px;flex:1 1 0;min-width:0;max-width:120px;overflow:hidden;text-align:center;display:flex;flex-direction:column;gap:2px}
.fc b{font-size:12px;line-height:1.15}.fc small{font-size:11px;color:var(--mut)}.fk{display:flex;flex-wrap:wrap;gap:2px 6px;justify-content:center;font-size:10.5px}.fk i{font-style:normal;color:var(--acc);font-weight:700}
.fw{font-style:normal;font-size:10px;color:#ff6b6b}.finf{font-style:normal;font-size:11px;font-weight:700;color:#ff6b6b;background:rgba(255,107,107,.12);border-radius:99px;padding:2px 7px}.finf.dub{color:#ffd23f;background:rgba(255,210,63,.12)}
.fst td,.fst th{padding:6px 8px;white-space:nowrap}
footer{margin-top:50px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}
"""
JS = """
const views=['news','live','giornata','analisi','triple','marcatori','fanta','bilancio','classifica'];
const STUDIO=['giornata','triple','marcatori'];
function show(){const h=location.hash.slice(1);const v=views.includes(h)?h:'news';const st=STUDIO.includes(v);
document.querySelectorAll('.view').forEach(e=>e.classList.toggle('on',e.id===v));
document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('on',a.dataset.g==='studio'?st:a.getAttribute('href')==='#'+v));
const sn=document.getElementById('subnav');if(sn){sn.classList.toggle('on',st);sn.querySelectorAll('a').forEach(a=>a.classList.toggle('on',a.getAttribute('href')==='#'+v));}}
addEventListener('hashchange',()=>{show();scrollTo(0,0)});show();
let S={};try{S=JSON.parse(localStorage.getItem('sa_combo')||'{}')}catch(e){}
function calc(inp){const tr=inp.closest('tr'),p=+tr.dataset.p,q=parseFloat(inp.value.replace(',','.')),c=tr.querySelector('.evc');
if(!(q>1)){c.innerHTML='—';return}const ev=p*q-1;const k=ev>=0?'pos':(ev>=-0.08?'neu':'neg');c.innerHTML=`<span class="ev ${k}">${(ev*100>=0?'+':'')+(ev*100).toFixed(1)}%</span>`;}
document.querySelectorAll('.qin').forEach(i=>{if(S[i.dataset.k])i.value=S[i.dataset.k];calc(i);
i.addEventListener('input',()=>{calc(i);document.querySelectorAll(`.qin[data-k="${CSS.escape(i.dataset.k)}"]`).forEach(o=>{if(o!==i){o.value=i.value;calc(o)}});
S[i.dataset.k]=i.value;try{localStorage.setItem('sa_combo',JSON.stringify(S))}catch(e){}})});
const cb=document.getElementById('copia');if(cb)cb.onclick=async()=>{const seen=new Set();const now=new Date().toISOString().slice(0,16);
const L=['partita;combo;quota_eurobet;rilevata'];document.querySelectorAll('#combo .qin, .pane .qin').forEach(i=>{const q=parseFloat(i.value.replace(',','.'));const tr=i.closest('tr');
const k=tr.dataset.m+'|'+tr.dataset.n;if(q>1&&!seen.has(k)){seen.add(k);L.push(`${tr.dataset.m};${tr.dataset.n};${q.toFixed(2).replace('.',',')};${now}`)}});
const m=document.getElementById('copiamsg');if(L.length<2){m.textContent='Nessuna quota inserita.';return}
try{await navigator.clipboard.writeText(L.join(String.fromCharCode(10)));m.textContent=`Copiate ${L.length-1} quote: incollale nella chat.`}catch(e){m.textContent='Copia non riuscita: seleziona e copia a mano.';}};
document.querySelectorAll('.match').forEach(m=>m.querySelectorAll('.tabs2 button').forEach(b=>b.onclick=()=>{
m.querySelectorAll('.tabs2 button').forEach(x=>x.classList.toggle('on',x===b));m.querySelectorAll('.pane').forEach(p=>p.classList.toggle('on',p.dataset.p===b.dataset.t));}));

const sp=document.getElementById('selp');
if(sp){const f=()=>{document.querySelectorAll('#analisi .match').forEach(a=>a.style.display=a.dataset.i===sp.value?'':'none')};
try{const v=localStorage.getItem('sa_selp');if(v&&[...sp.options].some(o=>o.value===v))sp.value=v}catch(e){}
sp.onchange=()=>{f();try{localStorage.setItem('sa_selp',sp.value)}catch(e){}};f();}
(function(){
const dl=document.getElementById('fdl');if(!dl||typeof FANTA==='undefined')return;
const ORD=['P','D','C','A'],RN={P:'Portieri',D:'Difensori',C:'Centrocampisti',A:'Attaccanti'};
const key=p=>p.n+'|'+p.t,BY={};FANTA.forEach(p=>BY[key(p)]=p);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let rosa=[],mod='4-4-2';try{rosa=JSON.parse(localStorage.getItem('sa_fanta')||'[]');mod=localStorage.getItem('sa_fanta_mod')||mod}catch(e){}
const ms=document.getElementById('fmodulo');ms.value=mod;
dl.innerHTML=FANTA.map(p=>`<option value="${esc(p.n)} (${esc(p.t)})">`).join('');
const save=()=>{try{localStorage.setItem('sa_fanta',JSON.stringify(rosa));localStorage.setItem('sa_fanta_mod',mod)}catch(e){}};
const msg=t=>{document.getElementById('fmsg').textContent=t};
function trova(v){v=v.trim().toLowerCase();if(!v)return null;let p=FANTA.find(p=>(p.n+' ('+p.t+')').toLowerCase()===v);if(p)return p;
const c=FANTA.filter(p=>p.n.toLowerCase().includes(v));return c.length===1?c[0]:(c.length>1?'tanti':null)}
function aggiungi(){const i=document.getElementById('fin');const p=trova(i.value);
if(p==='tanti'){msg('Più giocatori con questo nome: scegli dalla lista.');return}
if(!p){msg('Giocatore non trovato tra le rose di Serie A.');return}
if(rosa.some(x=>x.k===key(p))){msg(p.n+' è già nella rosa.');return}
rosa.push({k:key(p),n:p.n,t:p.t,r:p.r});i.value='';msg('');save();draw()}
document.getElementById('fbtn').onclick=aggiungi;document.getElementById('fin').addEventListener('keydown',e=>{if(e.key==='Enter')aggiungi()});
ms.onchange=()=>{mod=ms.value;save();draw()};
function info(x){const p=BY[x.k];return p?Object.assign({},p,{r:x.r}):{n:x.n,t:x.t,r:x.r,s:0,fv:0,pg:0,o:'',c:true,a:'non convocabile o senza partita',f:''}}
const corto=n=>{const w=n.split(' ');return w.length>1&&n.length>11?w[0][0]+'. '+w.slice(1).join(' '):n};
function chip(p){const w=p.a?`<em class="fw">${p.inf?'🚑 ':''}${esc(p.a)}</em>`:(p.pg<0.5?'<em class="fw">rischia la panchina</em>':'');
return `<div class="fc"><b>${esc(corto(p.n))}</b><small>${esc(p.t)}${p.o?' · '+(p.c?'vs ':'@ ')+esc(p.o):''}</small>
<span class="fk"><i>FV ${p.fv?p.fv.toFixed(1):'—'}</i><i>tit. ${Math.round((p.pg||0)*100)}%${p.f==='ufficiale'?' ✓':''}</i></span>${w}</div>`}
function draw(){
const R=document.getElementById('frosa');
R.innerHTML=rosa.length?ORD.map(r=>{const L=rosa.filter(x=>x.r===r);return L.length?`<div class="fg"><div class="fgt">${RN[r]} (${L.length})</div>${L.map(x=>`<span class="fp">
<select data-k="${esc(x.k)}" class="fr">${ORD.map(o=>`<option${o===x.r?' selected':''}>${o}</option>`).join('')}</select>${esc(x.n)} <small>${esc(x.t)}</small>${(BY[x.k]||{}).a?`<em class="finf${(BY[x.k]||{}).inf?'':' dub'}">${(BY[x.k]||{}).inf?'infortunato':'in dubbio'}</em>`:''}<button data-k="${esc(x.k)}" class="fx" aria-label="Togli">×</button></span>`).join('')}</div>`:''}).join(''):'<p class="hint">Aggiungi i giocatori della tua rosa: restano salvati su questo dispositivo. Il ruolo (P, D, C, A) si può cambiare se nella tua lega è diverso.</p>';
R.querySelectorAll('.fx').forEach(b=>b.onclick=()=>{rosa=rosa.filter(x=>x.k!==b.dataset.k);save();draw()});
R.querySelectorAll('.fr').forEach(s=>s.onchange=()=>{const x=rosa.find(x=>x.k===s.dataset.k);if(x){x.r=s.value;save();draw()}});
const O=document.getElementById('fout');if(!rosa.length){O.innerHTML='';return}
const n=mod.split('-').map(Number),need={P:1,D:n[0],C:n[1],A:n[2]};
const pl=rosa.map(info),tit=[],man=[];
ORD.forEach(r=>{const L=pl.filter(p=>p.r===r).sort((a,b)=>b.s-a.s);tit.push(...L.slice(0,need[r]));if(L.length<need[r])man.push(`${need[r]-L.length} ${RN[r].toLowerCase()}`)});
const panca=pl.filter(p=>!tit.includes(p)).sort((a,b)=>ORD.indexOf(a.r)-ORD.indexOf(b.r)||b.s-a.s);
const riga=r=>`<div class="frow">${tit.filter(p=>p.r===r).map(chip).join('')}</div>`;
const tot=tit.reduce((s,p)=>s+(p.s||0),0);
O.innerHTML=`<h2 class="daytitle">Formazione consigliata · ${mod}</h2>${man.length?`<p class="hint koc">Mancano in rosa: ${man.join(', ')}.</p>`:''}
<div class="fpitch">${['A','C','D','P'].map(riga).join('')}</div><p class="hint">Punteggio atteso dell'undici: <b>${tot.toFixed(1)}</b></p>
<h2 class="daytitle">Statistiche della rosa</h2><div class="scroll"><table class="tbl fst"><thead><tr><th class=l>Giocatore</th><th>R</th><th>Pres</th><th>Media voto</th><th>Fantamedia</th><th>Gol</th><th>Media gol</th><th>Ass</th><th>Media ass</th><th>Amm/Esp</th><th class=l>Stato</th></tr></thead><tbody>
${pl.slice().sort((a,b)=>ORD.indexOf(a.r)-ORD.indexOf(b.r)||b.s-a.s).map(p=>{const s=p.st||{};const f=v=>v==null?'—':v.toFixed(2);
const c=v=>s.p?(v??0):'—';
return `<tr><td class=l>${esc(p.n)} <small class="muted">${esc(p.t)}</small></td><td>${p.r}</td><td>${s.p||'—'}</td><td>${s.mv?s.mv.toFixed(2):'—'}</td><td><b>${s.fm?s.fm.toFixed(2):'—'}</b></td><td>${p.r==='P'&&s.fc?(s.p?'−'+(s.gs||0)+' <small class=muted>subiti</small>':'—'):c(s.g)}</td><td>${p.r==='P'&&s.fc?(s.p?(-(s.gs||0)/s.p).toFixed(2):'—'):f(s.mg)}</td><td>${c(s.as_)}</td><td>${f(s.ma)}</td><td>${s.p?(s.y||0)+'/'+(s.rc||0):'—'}</td><td class=l>${p.a?`<span class="${p.inf?'koc':'warn'}">${p.inf?'🚑 ':''}${esc(p.a)}</span>`:'<span class="okc">disponibile</span>'}</td></tr>`}).join('')}</tbody></table></div>
<p class="hint">${FCI||'Media voto e fantamedia compaiono quando carichi l’export delle statistiche di Fantacalcio nella cartella dati.'}</p>
<h2 class="daytitle">Panchina (in ordine)</h2><div class="scroll"><table class="tbl"><thead><tr><th class=l>Giocatore</th><th>Ruolo</th><th>FV atteso</th><th>Titolare</th></tr></thead><tbody>
${panca.map(p=>`<tr><td class=l>${esc(p.n)} <small class="muted">${esc(p.t)}${p.o?' vs '+esc(p.o):''}${p.a?' · '+esc(p.a):''}</small></td><td>${p.r}</td><td>${p.fv?p.fv.toFixed(1):'—'}</td><td>${Math.round((p.pg||0)*100)}%</td></tr>`).join('')}</tbody></table></div>`}
draw();})();
"""
gen = datetime.now(timezone.utc).isoformat()
PAGE = f"""<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Serie A Analyst</title><link rel="manifest" href="manifest.json"><meta name="theme-color" content="#0a0d12">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="SA Analyst"><link rel="apple-touch-icon" href="icona-180.png"><link rel="icon" type="image/png" href="icona-192.png"><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet"><style>{CSS}</style></head>
<body><div class="wrap"><header class="hero"><div class="brand">Serie A <span>Analyst</span><small>Aggiornato {fts(gen)}</small></div></header>
<nav><a href="#news">News</a><a href="#live">Live</a><a href="#giornata" data-g="studio">Studio</a><a href="#analisi">Analisi</a><a href="#fanta">Fantacalcio</a><a href="#bilancio">Bilancio</a><a href="#classifica">Classifica</a></nav>
<div class="subnav" id="subnav"><a href="#giornata">Pronostici</a><a href="#triple">Triple</a><a href="#marcatori">Marcatori</a></div>
<section class="view" id="news">{news_html}</section>
<section class="view" id="live">{gtitle}<h2 class="daytitle">Risultati live</h2>{live_html}<h2 class="daytitle">Formazioni</h2>{form_html}</section>
<section class="view" id="giornata">{gtitle}<h2 class="daytitle">Schedina della giornata</h2><div class="legend"><span class="star">★</span> <b>Errore di quota a tuo favore</b>: secondo l'analisi dell'AI questo esito è più probabile di quanto lo paga Eurobet. Sono le giocate più interessanti; le altre sono pagate il giusto o meno.</div><div class="scroll"><table class="tbl slip"><thead><tr><th class=l>Partita</th><th class=l>Pronostico</th><th>Probabilità</th><th>Quota</th></tr></thead><tbody>{slip_rows}</tbody></table></div></section>
<section class="view" id="analisi">{gtitle}<div class="pick"><label for="selp">Scegli la partita</label><select id="selp">{sel_opts}</select></div>{''.join(cards)}</section>
<section class="view" id="triple">{gtitle}<div class="legend"><span class="star">★</span> <b>Errore di quota a tuo favore</b>: secondo l'analisi dell'AI questo esito è più probabile di quanto lo paga Eurobet. Sono le giocate più interessanti; le altre sono pagate il giusto o meno.</div><h2 class="daytitle">Sabato</h2><div class="tgrid">{triple_html('sabato')}</div><h2 class="daytitle">Domenica</h2><div class="tgrid">{triple_html('domenica')}</div>
</section>
<section class="view" id="marcatori">{gtitle}{marc_html}</section>
<section class="view" id="fanta">{gtitle}
<div class="fbox"><h2 class="daytitle">La tua rosa</h2>
<div class="fadd"><input id="fin" list="fdl" placeholder="Scrivi il nome di un giocatore…" autocomplete="off"><button id="fbtn">Aggiungi</button></div>
<datalist id="fdl"></datalist><div id="fmsg" class="hint"></div><div id="frosa" class="frosa"></div></div>
<div class="fbox"><div class="fmod"><label for="fmodulo">Modulo</label><select id="fmodulo"><option>3-4-3</option><option>3-5-2</option><option>4-3-3</option><option selected>4-4-2</option><option>4-5-1</option><option>5-3-2</option><option>5-4-1</option></select></div>
<div id="fout"></div></div>
<details class="info"><summary>Come sceglie</summary><p>Per ogni giocatore della tua rosa stima il <b>fantavoto atteso</b> (regole Classic) partendo dalla sua <b>media voto</b> e dai <b>bonus medi</b> (fantamedia − media voto) delle statistiche Fantacalcio, corretti per la partita: forza dell'avversario, casa o trasferta, gol attesi della squadra e, per i portieri, gol che rischia di subire e probabilità di porta inviolata. Stima anche la <b>probabilità che giochi titolare</b>. Contano: i minuti che gioca di solito, se era titolare nell'ultima partita (o la formazione ufficiale, quando esce), gli infortuni e le squalifiche segnalate, i suoi xG e assist, quanti gol dovrebbe segnare la sua squadra contro quell'avversario e quanti rischia di subirne. Il punteggio per scegliere è fantavoto atteso × probabilità di giocare. Il voto in pagella non si può prevedere con precisione: è una stima, e si aggiorna ogni ora (formazioni ufficiali comprese).</p></details>
</section>
<section class="view" id="bilancio">{bil_html}</section>
<section class="view" id="classifica"><div class="scroll"><table class="tbl"><thead><tr><th>#</th><th class=l>Squadra</th><th>Pt</th><th>G</th><th>V</th><th>N</th><th>P</th><th>GF</th><th>GS</th><th>DR</th><th>xG/p</th><th>xGA/p</th><th>Elo</th></tr></thead><tbody>{cl_rows}</tbody></table></div>
</section>
<footer>Strumento personale di analisi. Le quote cambiano: verifica sempre sul sito del bookmaker. Il gioco è vietato ai minori e può causare dipendenza.</footer></div><script>const FANTA={FANTA_JSON};const FCI={json.dumps(FC_INFO)};</script><script>{JS}</script></body></html>"""
open(os.path.join(OUTD, "index.html"), "w").write(PAGE)
print(f"Sito generato: sito/index.html — giornata {md}, {len(PARTITE)} partite, {tot_v}/6 triple, {len(LINEUPS)} formazioni")
