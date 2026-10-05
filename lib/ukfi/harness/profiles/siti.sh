#!/bin/bash
# siti.sh <build_dir> <dump> -> conteggio di esecuzione della riga di ogni hook,
# cioe' esattamente il valore di site->inv che fi_nop confronta.
B="$1"; D="$2"
find "$B" -name '*.gcda' -delete
(cd "$B" && gcov-tool merge-stream < "$D" >/dev/null 2>&1)
(cd "$B/lib9pfs" && gcov 9pfs_vnops.gcda 9pfs_vfsops.gcda >/dev/null 2>&1)

get() { # $1=file.gcov  $2=riga
    awk -F: -v want="$2" '{ gsub(/^ +/,"",$1); gsub(/^ +/,"",$2);
        if ($2+0 == want) { print ($1=="-" ? "n/d" : ($1=="#####" ? "0" : $1)); exit } }' "$1"
}
V="$B/lib9pfs/9pfs_vnops.c.gcov"; F="$B/lib9pfs/9pfs_vfsops.c.gcov"
printf "%-9s %s\n" mount    "$(get "$F" 181)"
printf "%-9s %s\n" unmount  "$(get "$F" 265)"
printf "%-9s %s\n" open     "$(get "$V" 209)"
printf "%-9s %s\n" close    "$(get "$V" 259)"
printf "%-9s %s\n" lookup   "$(get "$V" 286)"
printf "%-9s %s\n" inactive "$(get "$V" 395)"
printf "%-9s %s\n" read     "$(get "$V" 624)"
printf "%-9s %s\n" write    "$(get "$V" 678)"
printf "%-9s %s\n" getattr  "$(get "$V" 761)"
printf "%-9s %s\n" fsync    "$(get "$V" 956)"
