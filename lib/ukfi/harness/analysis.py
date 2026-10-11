import collections, json, sys, statistics, os

from collections import Counter

def count(rows, field, title):
    c = Counter(r[field] for r in rows)
    print(f"-> {title}")
    print(f"| {field} | number of executions matching | % of executions matching |")
    print("|---|---:|---:|")
    for k, n in c.most_common():
        print(f"| {k} | {n} | {100*n/len(rows):.0f} %|")

def loadpath(path):
    l=[]
    with open(path) as f:
        l= [json.loads(row) for row in f if row.strip()]
    return l
        

def matrix(rows, f1, f2, title):
    print("-> ", title)
    c = Counter((r[f1], r[f2]) for r in rows)

    faults  = sorted({g for g, _ in c})
    classes  = sorted({o for _, o in c})

    print("| " + f1 + " | " + " | ".join(classes) + " | tot |")
    print("|---|" + "---:|" * (len(classes) + 1))

    for fault in faults:
        cells = [c[(fault, o)] for o in classes]
        print(f"| {fault} | " + " | ".join("·" if n == 0 else str(n) for n in cells ) + f" | {sum(cells)}")

def missed_table(tried, missed):
    print("-> MISSED RUNS")
    tot  = Counter((r["site"], r["nop"]) for r in tried)
    miss = Counter((r["site"], r["nop"]) for r in missed)
    if not miss: 
        print("nessuna run mancata")
        return
    print("| site, operation number | missed | total | % missed |")
    print("|---|---:|---:|---:|---:|")
    for site, nop in sorted(miss, key=lambda k: -miss[k]/tot[k]):
        print(f"| {site}, {nop} | {miss[(site, nop)]} | {tot[(site, nop)]} | {100*miss[(site,nop)]/tot[(site,nop)]:.1f}% |")

def crash_for_cause_table(crashed):
    if crashed:
        teardown_bugs=[]
        without_logs=0
        for crash in crashed:
            path_to_log = "/srv/unikraft/apps/"+str(crash["app"])+"/logs/"+str(crash["id"])+"-r"+str(crash["round"])+".log"
            if not os.path.exists(path_to_log):
                without_logs+=1
                continue
            with open(path_to_log, errors="replace") as log:
                strings_read = log.read()
                if "alloc.c @  198" in strings_read or "metadata->base" in strings_read:
                    teardown_bugs.append(crash)
                
        errors=[]
        delays=[]
        crashes=[]
        hangs=[]
        
        print("\n->  TEARDOWN CRASHES FOR EVERY FAULT INJECTED")
        for t in teardown_bugs:
            if t["fault"] == "crash":
                crashes.append(t)
            elif t["fault"] == "error":
                errors.append(t)
            elif t["fault"] == "delay":
                delays.append(t)
            elif t["fault"] == "hang":
                hangs.append(t)
    
        if len(errors)!=0 or len(delays)!=0 or len(crashes)!=0 or len(hangs)!=0:
            print(f"| Fault injected: | Number of teardown bug crashes | Number of total crashes |")
            print("|---|---:|---:|")
            print(f"| Error | {len(errors)} | {len([c for c in crashed if c["fault"]=="error"])} |")
            print(f"| Crash | {len(crashes)} | {len([c for c in crashed if c["fault"]=="crash"])} |")
            print(f"| Delay | {len(delays)} | {len([c for c in crashed if c["fault"]=="delay"])} |")
            print(f"| Hang | {len(hangs)} | {len([c for c in crashed if c["fault"]=="hang"])} |")
        else:
            print("Could not find the faults associated with the teardown crash")
        print("\nTotal teardown bugs: ", len(teardown_bugs), "\nTeardown bugs on all crashes: ", f"{100*len(teardown_bugs)/len(crashed):.0f}", "%")
        print("Total crashed without log found: ", without_logs)
    else:
        print("No runs endend in a crash to perform a study on")

def reproducibility(rows):
    id_sorted = collections.defaultdict(dict) #dictionary of a dictionary
    fault_associated={}
    for r in rows:
        id_sorted[r["id"]][r["round"]] = r["oracle"]
        fault_associated[r["id"]]=r["fault"]

    stable_outcomes=[]
    instable_outcomes=[]
    incomplete_rounds=[]

    for i, rounds in id_sorted.items():
        if len(rounds) <2:
            incomplete_rounds.append(i)
        elif len(set(rounds.values())) ==1:
            stable_outcomes.append(i)
        else:
            instable_outcomes.append(i)

    print(f"Number of stable outcomes between the rounds: {len(stable_outcomes)}")
    print(f"Number of instable outcomes between the rounds: {len(instable_outcomes)}")
    print(f"Number of incompleted runs: {len(incomplete_rounds)}")

    print("-> DIFFERENT OUTCOMES PER ROUND")
    rounds_seen = sorted({r["round"] for r in rows})

    print("| ID | " + " | ".join(f"round {n}" for n in rounds_seen) + " |")
    print("|---|" + "---:|" * len(rounds_seen))

    for i in sorted(instable_outcomes):
        cells = [id_sorted[i].get(n, "—") for n in rounds_seen]
        print(f"| {i} | " + " | ".join(cells) + " |")


    instable_delays=0
    instable_hangs=0
    instable_crashes=0
    instable_errors=0

    for i in instable_outcomes:
        if fault_associated[i]=="delay":
            instable_delays+=1
        elif fault_associated[i]=="hang":
            instable_hangs+=1
        elif fault_associated[i]=="error":
            instable_errors+=1
        elif fault_associated[i]=="crash":
            instable_crashes+=1

    print(f"Instable crashes: {instable_crashes}\nInstable delays: {instable_delays}\nInstable hangs: {instable_hangs}\nInstable errors: {instable_errors}")


def duration_comparation(rows):
    baselines = [r["duration_s"] for r in rows if r["kind"]=="baseline"]
    delays = [r["duration_s"] for r in rows if r["fault"]=="delay" and r["fault_fired"] and r["duration_s"] is not None]
    print(f"Baseline minimum duration: {min(baselines)}\nDelay runs minimum duration: {min(delays)}")
    print(f"Baseline average duration: {statistics.mean(baselines)}\nDelay runs average duration: {statistics.mean(delays)}")
    print(f"Baseline median duration: {statistics.median(baselines)}\nDelay runs median duration: {statistics.median(delays)}")
    print(f"Baseline maximum duration: {max(baselines)}\nDelay runs maximum duration: {max(delays)}")

def write_comparation(redis_rows, nginx_rows):
    redis_write = [r for r in redis_rows if r["site"]=="write" and r["fault_fired"]]
    nginx_write = [r for r in nginx_rows if r["site"]=="write" and r["fault_fired"]]
    matrix(redis_write + nginx_write, "app", "oracle", "WRITE: REDIS vs NGINX")




def main(args):
    redis=None
    nginx=None
    for path in args:
        if(".json" in path):
            rows = loadpath(path)
            if rows[0]["app"]=="redis": 
                redis = rows
            elif rows[0]["app"]=="nginx":
                nginx = rows
            print("\n\n -- WORKLOAD: ", rows[0]["app"].upper(), "--")
            tried_injecting = [r for r in rows if r["kind"] == "injected"]
            successfully_injected  = [r for r in tried_injecting if r["fault_fired"]]
            baseline  = [r for r in rows if r["kind"] == "baseline"]
            missed_runs = [r for r in tried_injecting if not r["fault_fired"]]
            print(f"Tried injecting: {len(tried_injecting)} faults\nSuccessfully injected: {len(successfully_injected)} faults\nBaselines: {len(baseline)}\nMissed runs: {len(missed_runs)}\nTotal runs: {len(rows)}")
            duration_comparation(rows)
            print("\n ----------------------------------------- \n")
            count(rows, "oracle", "OUTCOME DISTRIBUITION")
            print("\n ----------------------------------------- \n")
            matrix(successfully_injected, "fault", "oracle", "OUTCOMES FOR EACH FAULT")
            print("\n ----------------------------------------- \n")
            matrix(successfully_injected, "site",  "oracle", "OUTCOMES FOR EACH SITE")
            print("\n ----------------------------------------- \n")
            reproducibility(rows)
            print("\n ----------------------------------------- \n")
            missed_table(tried_injecting, missed_runs)
            print("\n ----------------------------------------- \n")
            matrix([r for r in successfully_injected if r["site"] == "write"], "fault", "oracle", "CLOSE UP ANALYSIS FOR FAULTS INJECTED ON WRITE FUNCTION")
            print("\n ----------------------------------------- \n")
            crash_for_cause_table([r for r in rows if r["crash_screen"]])

        else:
            print(f"\nIgnoring not jsonl files: {path} \n")

    if redis !="" and nginx != "":
        write_comparation(redis_rows = redis, nginx_rows = nginx)




if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Error, expected at least one json file. Try executing: python3 analisys.py results/*.jsonl")
    main(sys.argv[1:])

'''
lib/ukfi/harness/analisi.py
Ingressi. Uno o più .jsonl da results/, più i log per esecuzione in <app_dir>/logs/{id}-r{round}.log. Lo stato attuale dei file: redis-p1-margine-100.jsonl (la campagna con il margine al 100%, 180 righe, da conservare come prova della regola), nginx-p1.jsonl (204 righe), e la riesecuzione di Redis ancora da fare.

Campi disponibili in ogni riga. Identità: id, site, fault, nop, period, kind, round. Esito: oracle, outcome. I dieci segnali booleani. Osservazioni grezze: ready_ms, duration_s, qemu_exit, timed_out. Metriche del client, che possono essere null.

Le sette tabelle
DONE 1. Riepilogo — righe totali, baseline, iniettate, con guasto scattato, mancate.

DONE 2. Mancate per (sito, fi_nop) — quante su quante. È la tabella che ha prodotto la regola del margine, e serve rigenerarla dopo la riesecuzione per mostrare che va a zero.

DONE 3. Matrice guasto richiesto × classe osservata — la tabella principale della tesi. Solo righe con fault_fired vero: senza quel filtro le 19 mancate finiscono dentro come not_valid_run e falsano le percentuali.

DONE 4. Crash per causa — per ogni riga con crash_screen, apri il log corrispondente e cerca alloc.c @  198 oppure metadata->base: se c'è è il bug di teardown, altrimenti è il guasto. Raggruppa per tipo di guasto. È il dato che regge il risultato centrale, e richiede i log perché il .jsonl da solo non lo contiene. Se un log manca, contalo a parte invece di scartarlo in silenzio.

5. Riproducibilità — raggruppa per id, confronta oracle fra round 1 e 2. Accordo, disaccordo, ed elenco dei discordanti con i due esiti affiancati.

DONE 6. Esiti per sito — mostra la distinzione fra siti esercitati solo all'avvio e siti in esercizio, che è ciò che spiega i 34 crash_in_boot_fatal_run di Redis.

7. Confronto fra chiamanti su write — le due campagne affiancate, ristrette al solo sito caldo in entrambi. È l'unico confronto diretto difendibile.

8. la mediana delle durate di baseline contro le durate delle run di delay, cioè i numeri dietro client_degraded.

Le cinque trappole
Il filtro fault_fired va messo in tabella 3, 6 e 7. Nella 1 e nella 2 no, perché lì le mancate sono l'oggetto.

duration_s e le metriche possono essere None — client troncato o mai partito. Ogni media, mediana o confronto numerico va protetto, altrimenti si rompe sulle run di crash e hang, che sono metà del dataset.

Le baseline hanno fault a None, quindi le chiavi di raggruppamento devono tollerarlo.

L'appaiamento dei round è per id, non per posizione. Le baseline intercalate spostano gli indici.

I nomi degli oracoli sono fuorvianti fra guasti diversi — un error può uscire come delay_run. Per questo la forma giusta è la matrice a due dimensioni e non il conteggio degli oracoli: quel conteggio, da solo, suggerisce che ci siano stati ritardi dove c'erano errori.

Formato di uscita
Tabelle Markdown su stdout. Si leggono in terminale, si incollano in tesi, e non richiedono dipendenze. Un eventuale --tex dopo, se il relatore lo chiede.

Quando riprendi dopo la compattazione, partiamo dalla tabella 3 e dalla 4: sono le due che reggono il risultato, e la 4 è la sola che richiede di aprire i log.
'''