#!/usr/bin/env python3
"""Genera prova.yaml da redis.yaml, riducendo la matrice a poche run.

Deriva dal file vero invece di duplicarlo, cosi' segnali, oracoli, faults
e protocollo non possono divergere: la prova verifica la stessa
configurazione che girera' nella campagna.

uso:  python3 prova.yaml.gen.py
poi:  python3 ../runner.py prova.yaml
"""
import yaml, os

QUI = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(QUI, "redis.yaml")) as f:
    cfg = yaml.safe_load(f)

cfg["name"] = "redis-prova"

# Un solo sito, la prima invocazione: si raggiunge subito.
# Tutti e quattro i guasti, perche' ognuno esercita un percorso diverso
# del runner:
#   crash -> client esce non-zero, nessun clear_shutdown  (finestra del log)
#   hang  -> client in timeout                            (TimeoutExpired)
#   error -> client completa                              (parse_metrics intero)
#   delay -> sostituzione di fi_period                    (fi_period_override)
cfg["matrix"]["sites"] = {
    "write": {"can_fail": True, "fi_nop": [1]},
}

# due baseline in testa, nessuna intercalata
cfg["protocol"]["baseline"]["count"] = 2
cfg["protocol"]["baseline"]["interleave_every"] = 1000

cfg["protocol"]["results"] = "results/prova.jsonl"

with open(os.path.join(QUI, "prova.yaml"), "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

# conteggio atteso, con i round scritti a mano nel runner
inj = sum(
    len(sp["fi_nop"])
    for s, sp in cfg["matrix"]["sites"].items()
    for fa in cfg["matrix"]["faults"]
    if not (fa == "error" and not sp["can_fail"])
)
per_round = inj + cfg["protocol"]["baseline"]["count"]
print(f"prova.yaml scritto: {inj} iniettate + {cfg['protocol']['baseline']['count']} baseline"
      f" = {per_round} per round, {per_round * 2} in tutto")
