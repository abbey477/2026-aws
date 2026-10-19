#!/usr/bin/env bash
# check_403_v2.sh - test the OLD vs NEW OECD Country Risk Classification PDF URLs
# through the working proxy, with plain and Chrome user agents.
# Usage: bash check_403_v2.sh

PROXY="http://server-proxy.jpmchase.net:11443"

URLS=(
  "OLD|https://www.oecd.org/trade/topics/export-credits/documents/cre-crc-current-english.pdf"
  "NEW|https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/country-risk-classification/cre-crc-current-english.pdf"
  "NEW-nowww|https://oecd.org/content/dam/oecd/en/topics/policy-sub-issues/country-risk-classification/cre-crc-current-english.pdf"
)

UAS=(
  "Mozilla/5.0"
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TMP=$(mktemp -d)
n=0
WORKING=""

echo "Proxy: $PROXY"
printf "\n%-3s %-10s %-3s %-7s %-6s %-12s %s\n" "#" "URL" "UA" "CONNECT" "HTTP" "SERVER" "RESULT"
printf '%.0s-' {1..80}; echo

for entry in "${URLS[@]}"; do
  label=${entry%%|*}; u=${entry#*|}
  for i in "${!UAS[@]}"; do
    n=$((n+1))
    out="$TMP/out$n"; hdr="$TMP/hdr$n"

    res=$(curl -s -L --max-time 30 -x "$PROXY" -A "${UAS[$i]}" \
            -H "Accept: application/pdf,*/*" \
            -D "$hdr" -o "$out" \
            -w "%{http_connect} %{http_code}" "$u" 2>/dev/null)
    rc=$?
    connect=${res% *}; code=${res#* }
    server=$(grep -i '^server:' "$hdr" 2>/dev/null | tail -1 | cut -d' ' -f2- | tr -d '\r' | cut -c1-12)

    if [ $rc -ne 0 ]; then
      result="curl error $rc"
    elif [ "$(head -c 5 "$out" 2>/dev/null)" = "%PDF-" ]; then
      result="OK - real PDF ($(stat -c %s "$out") bytes)"
      if [ -z "$WORKING" ]; then
        WORKING="curl -L -x \"$PROXY\" -A \"${UAS[$i]}\" -o cre-crc-current-english.pdf \"$u\""
        cp "$out" ./cre-crc-current-english.pdf
      fi
    elif [ "$code" = "403" ]; then
      result="403 blocked by site/CDN"
    else
      result="not a PDF (web page?)"
    fi

    printf "%-3s %-10s %-3s %-7s %-6s %-12s %s\n" \
      "$n" "$label" "$((i+1))" "$connect" "$code" "${server:--}" "$result"
  done
done

echo
if [ -n "$WORKING" ]; then
  echo "SUCCESS - PDF saved to: $(pwd)/cre-crc-current-english.pdf"
  echo "Use this in the app:"
  echo "  $WORKING"
else
  echo "NOTHING WORKED - see RESULT column above."
fi
echo
echo "UA 1 = plain 'Mozilla/5.0', UA 2 = full Chrome string"
echo "Headers and bodies saved in: $TMP"
