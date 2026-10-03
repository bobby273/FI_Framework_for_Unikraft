#!/bin/bash
# $1 = dump, $2 = output.  Key = unique path to .gcda , value = lines executed.
B=/srv/unikraft/apps/redis/workdir/build
find "$B" -name '*.gcda' -delete
cd "$B" && gcov-tool merge-stream < "$1" >/dev/null 2>&1
: > "$2"
find "$B" -name '*.gcda' | while read g; do
    d=$(dirname "$g"); n=$(basename "$g")
    #only the first pair File/Lines = the primary source of the unit
    (cd "$d" && gcov -n "$n" 2>/dev/null) | awk -v key="${g#$B/}" '
        /^Lines executed:/ {
            split($0,a,":"); split(a[2],b,"%"); pct=b[1]+0; n=$NF+0
            printf "%s %d %d\n", key, int(pct*n/100+0.5), n; exit
        }' >> "$2"
done
