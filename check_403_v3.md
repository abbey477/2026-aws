# OECD CRC PDF download - 403 fix notes (v3)

Date: 18 Oct 2026
Host: iaasn00708623 (UAT), user `refdatas`

## Problem
The job that downloads the OECD Country Risk Classification PDF started failing with **HTTP 403**. It worked before, and nothing changed on our side.

## Root cause
OECD redesigned their website and **moved the PDF**. The old URL is now blocked by Cloudflare (403). It never returns the PDF, whatever user agent is used.

## Test results (check_403_v2.sh, proxy server-proxy.jpmchase.net:11443)

| URL | UA | Result |
|-----|----|--------|
| OLD | Mozilla/5.0 | 403 (Cloudflare) |
| OLD | Chrome | 403 (Cloudflare) |
| **NEW (www)** | **Mozilla/5.0** | **OK - real PDF (367,789 bytes)** |
| NEW (www) | Chrome | OK - real PDF |
| NEW (no www) | both | 407 from proxy (curl error 56) |

Earlier test (check_403.sh): proxy `proxy.jpmchase.net:10443` (from DB config) is **unreachable** from this host (curl error 7).

## Fix
Change only the URL in the app config.

**Old:**
```
http://www.oecd.org/trade/topics/export-credits/documents/cre-crc-current-english.pdf
```

**New:**
```
https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/country-risk-classification/cre-crc-current-english.pdf
```

Keep:
- Proxy: `http://server-proxy.jpmchase.net:11443`
- User agent: `Mozilla/5.0`
- Must be `https` and `www.` (no-www is blocked by the proxy with a 407)

Working command:
```bash
curl -L -x "http://server-proxy.jpmchase.net:11443" -A "Mozilla/5.0" \
  -o cre-crc-current-english.pdf \
  "https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/country-risk-classification/cre-crc-current-english.pdf"
```

## Steps
1. Find where the URL is stored:
   ```bash
   grep -r "cre-crc-current-english" /apps/rdr 2>/dev/null
   ```
   Also check the DB config table.
2. Replace the old URL with the new one.
3. Re-run the job in UAT and confirm the PDF downloads. The file should start with `%PDF-`.
4. Apply the same change in PROD.

## Follow-ups
- The DB config proxy `proxy.jpmchase.net:10443` is unreachable from this host. Review it or point it to `server-proxy.jpmchase.net:11443`.
- OECD may move the file again. Add a check that the downloaded file starts with `%PDF-` so a silent failure (an HTML page saved as a PDF) is caught.

## Source
New file location: https://oecd.org/content/dam/oecd/en/topics/policy-sub-issues/country-risk-classification/cre-crc-current-english.pdf
