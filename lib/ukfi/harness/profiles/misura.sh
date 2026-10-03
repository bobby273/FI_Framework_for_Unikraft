#!/bin/bash
# $1 = build dir, $2 = dump, $3 = output
B="$1"
find "$B" -name '*.gcda' -delete
cd "$B" && gcov-tool merge-stream < "$2" >/dev/null 2>&1
: > "$3"
find "$B" -name '*.gcda' | while read g; do
    d=$(dirname "$g"); n=$(basename "$g")
    (cd "$d" && gcov -n "$n" 2>/dev/null) | awk -v key="${g#$B/}" '
        /^Lines executed:/ {
            split($0,a,":"); split(a[2],b,"%"); pct=b[1]+0; n=$NF+0
            printf "%s %d %d\n", key, int(pct*n/100+0.5), n; exit
        }' >> "$3"
done
