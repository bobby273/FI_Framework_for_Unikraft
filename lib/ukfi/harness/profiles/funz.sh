#!/bin/bash
# $1 = build dir, $2 = dump  -> conteggi per funzione di 9pfs_vnops.c
B="$1"; SRC=/srv/unikraft/unikraft/lib/9pfs/9pfs_vnops.c
find "$B" -name '*.gcda' -delete
cd "$B" && gcov-tool merge-stream < "$2" >/dev/null 2>&1
cd "$B/lib9pfs" 2>/dev/null || exit 0
gcov 9pfs_vnops.gcda >/dev/null 2>&1
grep -nE "^static int uk_9pfs_[a-z_]+\(" "$SRC" | sed 's/:static int /:/;s/(.*//' > /tmp/fn.$$
awk -F: 'NR==FNR{l[NR]=$1; n[NR]=$2; c=NR; next}
  { gsub(/^ +/,"",$1); if ($1 ~ /^[0-9]+$/) cnt[$2+0]=$1 }
  END{ for(i=1;i<=c;i++){ s=l[i]; e=(i<c?l[i+1]-1:99999); m=0;
        for(ln=s; ln<=e; ln++) if(cnt[ln]>m) m=cnt[ln];
        if(m>0) printf "%d\t%s\n", m, n[i] } }' /tmp/fn.$$ 9pfs_vnops.c.gcov | sort -rn
rm -f /tmp/fn.$$
