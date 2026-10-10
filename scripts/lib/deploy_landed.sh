# deploy_landed <label> <url> <vercel_output>: 0 when a production deploy really landed.
#
# A URL IS NOT SUCCESS (2026-09-06). Vercel prints the deployment URL before it builds, and a build
# that dies (that day: ENOENT on a file .vercelignore had hidden) still leaves a URL in the output
# with status Error. The hourly job took the URL as proof and reported "prod: ..." while the domain
# kept serving the previous build. So: the output must not carry a build error, and the new
# deployment must answer 200 for the homepage.
#
# ONE DEFINITION FOR BOTH DEPLOY PATHS (2026-10-10). The hourly job carried this check inline and
# the nightly publish did not, so a nightly "success" meant only that a URL was printed. Both jobs
# now stamp the deploy clock they share (var/last_web_deploy.hash) when a deploy lands, so both must
# mean the same thing by "landed". Sourced by scripts/live_deploy_hourly.sh and scripts/live_publish.sh.
deploy_landed() {
  local label="$1" url="$2" output="$3" served
  [ -n "$url" ] || return 1
  if printf '%s\n' "$output" | grep -qE "Error: Command .* exited|Build Failed|status.*Error"; then
    echo "  [$label] deployment $url reported a build error; not treating the URL as success"
    return 1
  fi
  served=$(curl -s -o /dev/null --max-time 30 -w '%{http_code}' "$url/" 2>/dev/null || echo 000)
  if [ "$served" != "200" ]; then
    echo "  [$label] deployment $url answers HTTP $served for /; the build did not complete"
    return 1
  fi
  return 0
}
