#!/bin/bash
# Starts OpenBot headless on a virtual display with CDP on :${CDP_PORT:-9222}. Idempotent.
set -euo pipefail
export DISPLAY=:99
if ! pgrep -x Xvfb >/dev/null; then
  Xvfb :99 -screen 0 1600x1000x24 >/tmp/xvfb.log 2>&1 &
  for _ in $(seq 50); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.2; done
fi
if ! pgrep -f "remote-debugging-port=${CDP_PORT:-9222}" >/dev/null; then
  LD_PRELOAD=/opt/openbot/rootshim.so /opt/openbot/app/openbot --no-sandbox --disable-gpu --disable-dev-shm-usage --ozone-platform=x11 \
    --user-data-dir=/root/.config/OpenBot --password-store=basic \
    --remote-debugging-port=${CDP_PORT:-9222} >/tmp/openbot.log 2>&1 < /dev/null &
  disown
fi
for _ in $(seq 120); do
  if \
     /opt/openbot/profile/provider-runtimes/bun/linux-x64/1.4.4/bin/bun -e \
       "fetch('http://127.0.0.1:${CDP_PORT:-9222}/json/list').then(r=>r.json()).then(l=>process.exit(l.some(t=>t.url.endsWith('/index.html'))?0:1)).catch(()=>process.exit(1))"; then
    echo "openbot ready"; exit 0
  fi
  sleep 1
done
echo "openbot failed to start" >&2; tail -50 /tmp/openbot.log >&2; exit 1
