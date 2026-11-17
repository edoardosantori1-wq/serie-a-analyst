# Serie A Analyst

Sistema personale di analisi statistica della Serie A con quote Eurobet.

- `orchestra.py` — automazione oraria (GitHub Actions): calendario, notizie, uscita del report, formazioni ufficiali.
- `aggiorna.py` — aggiornamento manuale completo dal proprio computer.
- `modello.py` — modello Poisson/Dixon-Coles e backtest.
- `predizioni.py` — probabilità, pronostici, triple, marcatori; registro storico in `dati/storico.sqlite`.
- `genera_sito.py` — costruisce `sito/index.html`.
- `dati/quote_combo.csv` — quote combo reali per la calibrazione (si modifica da GitHub).

Fonti: football-data.org, football-data.co.uk, OddsPapi (Eurobet), StrikerAPI, feed RSS delle testate sportive.
Le chiavi API sono nei GitHub Secrets, mai nei file. Uso personale, scommesse virtuali. 18+.
