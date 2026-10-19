#!/usr/bin/env bash
# check_403.sh - try the OECD PDF download through different proxy / URL / user-agent
# combinations and show which ones work.
# Usage: bash check_403.sh

PROXIES=(
  "http://server-proxy.jpmchase.net:11443"   # current hard-coded proxy
  "http://proxy.jpmchase.net:10443"          # proxy from DB config
)

URLS=(
  "http://www.oecd.org/trade/topics/export-credits/documents/cre-crc-current-english.pdf"
  "https://www.oecd.org/trade/topics/export-credits/documents/cre-crc-current-english.pdf"
)

UAS=(
  "Mozilla/5.0"
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TMP=$(mktemp -d)
n=0

printf "\n%-3s %-38s %-6s %-3s %-7s %-6s %-14s %s\n" "#" "PROXY" "SCHEME" "UA" "CONNECT" "HTTP" "SERVER" "RESULT"
printf '%.0s-' {1..100}; echo

for p in "${PROXIES[@]}"; do
  for u in "${URLS[@]}"; do
    for i in "${!UAS[@]}"; do
      n=$((n+1))
      out="$TMP/out$n"; hdr="$TMP/hdr$n"

      res=$(curl -s -L --max-time 30 -x "$p" -A "${UAS[$i]}" \
              -H "Accept: application/pdf,*/*" \
              -D "$hdr" -o "$out" \
              -w "%{http_connect} %{http_code}" "$u" 2>/dev/null)
      rc=$?
      connect=${res% *}; code=${res#* }

      server=$(grep -i '^server:' "$hdr" 2>/dev/null | tail -1 | cut -d' ' -f2- | tr -d '\r' | cut -c1-14)

      if [ $rc -ne 0 ]; then
        result="curl error $rc (proxy unreachable/timeout?)"
      elif [ "$(head -c 5 "$out" 2>/dev/null)" = "%PDF-" ]; then
        result="OK - real PDF ($(stat -c %s "$out") bytes)"
        if [ -z "$WORKING" ]; then
          WORKING="curl -L -x \"$p\" -A \"${UAS[$i]}\" -o cre-crc-current-english.pdf \"$u\""
          cp "$out" ./cre-crc-current-english.pdf
        fi
      elif [ "$connect" != "000" ] && [ "$connect" != "200" ]; then
        result="BLOCKED BY PROXY (CONNECT $connect)"
      elif [ "$code" = "403" ]; then
        result="403 from site/CDN"
      else
        result="not a PDF"
      fi

      printf "%-3s %-38s %-6s %-3s %-7s %-6s %-14s %s\n" \
        "$n" "$p" "${u%%:*}" "$((i+1))" "$connect" "$code" "${server:--}" "$result"
    done
  done
done

echo
if [ -n "$WORKING" ]; then
  echo "SUCCESS - PDF saved to: $(pwd)/cre-crc-current-english.pdf"
  echo "Working command:"
  echo "  $WORKING"
else
  echo "NOTHING WORKED - see RESULT column above for the reason."
fi
echo
echo "UA 1 = plain 'Mozilla/5.0', UA 2 = full Chrome string"
echo "CONNECT 000 = not used (plain http), 200 = proxy let the tunnel through"
echo "Headers and bodies saved in: $TMP"
