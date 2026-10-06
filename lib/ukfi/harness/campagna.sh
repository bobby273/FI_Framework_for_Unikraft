#!/bin/bash
# Esegue le due campagne in sequenza: redis, poi nginx.
# Ogni campagna fa di per se' i due round del protocollo (enumerate_runs),
# quindi UNA passata e' il protocollo completo. Per ripetere, rilancia
# questo script con PASSATE=2 (la passata successiva riparte da un
# .jsonl vuoto: il precedente viene archiviato, cosi' il resume del
# runner resta valido dentro una passata senza far saltare la seguente).
#
# uso:  nohup bash campagna.sh > /dev/null 2>&1 &
# poi:  tail -f results/campagna-*.log

set -u
H=/srv/unikraft/unikraft/lib/ukfi/harness
cd "$H" || exit 1
mkdir -p results logs

STAMP=$(date +%Y%m%d-%H%M%S)
MASTER="$H/results/campagna-$STAMP.log"
# tetto di sicurezza per campagna: oltre questo qualcosa e' appeso
CAP=10800
PASSATE=${PASSATE:-1}

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$MASTER"; }

# La prima run di una campagna paga la cache di pagina fredda: misurato
# 25,1 s di benchmark contro i 3,7-8,4 delle successive, abbastanza per
# toccare il bordo della finestra di gcov e falsare la baseline.
# Qui se ne fa una a vuoto, scartata, prima di ogni campagna.
riscaldamento() {
    local camp="$1" y="$H/campaigns/$1.yaml"
    # i parametri si leggono dal YAML della campagna, incluso il template
    # di -append della baseline: cosi' il riscaldamento avvia esattamente
    # cio' che avviera' il runner, invece di una riga indovinata.
    eval "$(python3 - "$y" <<'PY'
import yaml, sys, shlex
r = yaml.safe_load(open(sys.argv[1]))["run"]
ap = r["append"]["baseline"].replace("<ms>", "8000")
for k, val in (("APP", r["app_dir"]),
               ("KERNEL", r["app_dir"] + "/" + r["kernel"]),
               ("ROOTFS", r["app_dir"] + "/" + r["rootfs"]),
               ("FWD", r["hostfwd"]),
               ("TAG", r["mount_tag"]),
               ("APPEND", ap)):
    print(f"{k}={shlex.quote(str(val))}")
PY
)"
    # Il riscaldamento e' anche il collaudo della macchina: un avvio sano
    # con gcov_after_ms=8000 chiude in ~10 s. Se ci mette piu' di 40 s il
    # guest sta girando ordini di grandezza sotto il normale -- succede
    # con scritture arretrate sul disco dopo una ricompilazione, e ogni
    # riga sulla console seriale si blocca. In quello stato la campagna
    # produce solo run scadute, quindi si aspetta invece di partire.
    local tentativo t0 t
    for tentativo in 1 2 3; do
        say "riscaldamento $camp: avvio a vuoto (tentativo $tentativo)"
        t0=$(date +%s)
        timeout 90 qemu-system-x86_64 -kernel "$KERNEL" -nographic -m 256M -accel kvm -cpu host \
            -netdev "user,id=n0,hostfwd=$FWD" -device virtio-net-pci,netdev=n0 \
            -fsdev "local,id=myid,path=$ROOTFS,security_model=none" \
            -device "virtio-9p-pci,fsdev=myid,mount_tag=$TAG,disable-modern=on,disable-legacy=off" \
            -append "$APPEND" < /dev/null > /dev/null 2>&1
        t=$(( $(date +%s) - t0 ))
        if [ "$t" -le 40 ]; then
            say "riscaldamento $camp: ok in ${t}s, macchina pronta"
            return 0
        fi
        say "riscaldamento $camp: ${t}s, troppo lento -- sync e attesa di 180 s"
        sync
        sleep 180
    done
    say "riscaldamento $camp: ancora lento dopo 3 tentativi, campagna SALTATA"
    return 1
}

say "avvio orchestrazione, pid $$, passate=$PASSATE"
say "attese per passata: redis ~180 run x 25 s (~75 min), nginx ~170 x 35 s (~100 min)"

for passata in $(seq 1 "$PASSATE"); do
    for camp in redis nginx; do

        out="$H/results/$camp.jsonl"

        # un file lasciato da una passata precedente va archiviato,
        # altrimenti il resume salterebbe tutta questa passata
        if [ -e "$out" ]; then
            mv "$out" "$H/results/$camp-orfano-$STAMP.jsonl"
            say "archiviato un $camp.jsonl preesistente"
        fi

        if ! riscaldamento "$camp"; then
            continue
        fi

        say "=== passata $passata / $camp : inizio"
        timeout "$CAP" python3 "$H/runner.py" "$camp.yaml" >> "$MASTER" 2>&1
        rc=$?

        if [ -e "$out" ]; then
            righe=$(wc -l < "$out")
            mv "$out" "$H/results/$camp-p$passata.jsonl"
        else
            righe=0
            say "ATTENZIONE: nessun file di risultati prodotto"
        fi
        say "=== passata $passata / $camp : fine  exit=$rc  righe=$righe"

        # nessun QEMU residuo deve restare appeso fra una campagna e l'altra:
        # terrebbe occupata la porta e falserebbe le misure di durata.
        # il [q] evita che pkill riconosca la propria riga di comando.
        pkill -f "[q]emu-system-x86_64 -kernel" 2>/dev/null && say "ucciso un qemu residuo"
        sleep 5
    done
done

say "fine orchestrazione"
say "risultati:"
ls -la "$H"/results/*.jsonl 2>/dev/null | tee -a "$MASTER"
