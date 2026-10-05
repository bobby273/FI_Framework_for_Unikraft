#!/usr/bin/env python3
"""Controlla un .jsonl di risultati: verifica meccanica, non scientifica.

Non giudica SE il guasto ha prodotto l'esito giusto -- quello e' il
risultato della campagna. Verifica che la catena del runner abbia
funzionato: righe complete, nessuna non classificata, baseline pulite,
e soprattutto che ogni run iniettata abbia davvero fatto scattare il
guasto. Se fault_fired e' falso, l'arming non ha funzionato e i
risultati non valgono nulla, qualunque cosa dicano gli oracoli.

uso:  python3 verifica.py results/prova.jsonl [12]
"""
import json, sys, os, collections

percorso = sys.argv[1]
attese = int(sys.argv[2]) if len(sys.argv) > 2 else None

if not os.path.exists(percorso):
    print(f"{percorso} non esiste: il runner non ha prodotto risultati.")
    print("Guarda il traceback del runner, o i log in <app_dir>/logs/.")
    sys.exit(2)

righe, rotte = [], 0
with open(percorso) as f:
    for n, line in enumerate(f, 1):
        try:
            righe.append(json.loads(line))
        except ValueError:
            rotte += 1
            print(f"  riga {n} illeggibile (troncata?)")

print(f"righe valide: {len(righe)}" + (f" / {attese} attese" if attese else ""))
if rotte:
    print(f"righe rotte:  {rotte}")

problemi = []
if attese is not None and len(righe) != attese:
    problemi.append(f"numero di righe {len(righe)} invece di {attese}")

campi = ["id", "round", "kind", "oracle", "outcome", "ready_ms",
         "duration_s", "qemu_exit", "timed_out", "fault_fired"]
for r in righe:
    mancanti = [c for c in campi if c not in r]
    if mancanti:
        problemi.append(f"{r.get('id','?')}: campi mancanti {mancanti}")
        break

# --- l'assertion che conta: il guasto e' scattato? ---
for r in righe:
    if r.get("kind") == "injected" and not r.get("fault_fired"):
        problemi.append(f"{r.get('id')} r{r.get('round')}: fault_fired FALSO "
                        f"-> sito non armato o -append sbagliato")

# --- le baseline devono essere pulite ---
for r in righe:
    if r.get("kind") == "baseline" and r.get("oracle") != "gold_run":
        problemi.append(f"{r.get('id')} r{r.get('round')}: baseline classificata "
                        f"{r.get('oracle')} invece di gold_run")

# --- nessuna run deve finire nel catch-all ---
for r in righe:
    if r.get("oracle") in ("unclassified_run", "no_signal_run"):
        problemi.append(f"{r.get('id')} r{r.get('round')}: {r.get('oracle')}")

print("\nesiti per oracolo:")
for k, n in collections.Counter(r.get("oracle") for r in righe).most_common():
    print(f"  {n:4}  {k}")

print("\ntempi a pronto (ms):",
      sorted(r["ready_ms"] for r in righe if r.get("ready_ms") is not None))
print("durate client (s):  ",
      sorted(round(r["duration_s"], 2) for r in righe if r.get("duration_s") is not None))
print("exit code qemu:     ",
      dict(collections.Counter(r.get("qemu_exit") for r in righe)))

print()
if problemi:
    print(f"PROBLEMI ({len(problemi)}):")
    for p in problemi:
        print("  -", p)
    sys.exit(1)
print("nessun problema meccanico: la catena ha funzionato")
