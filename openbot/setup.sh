#!/bin/bash
# Runs inside a task container. Payload is at /opt/openbot (app/, profile/, home/).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
pkgs="xvfb xauth libgtk-3-0 libnss3 libgbm1 libxss1 libxshmfence1 libdrm2 libxkbcommon0
      libatk-bridge2.0-0 libcups2 libsecret-1-0 libxtst6 libxrandr2 libxcomposite1
      libxdamage1 libxfixes3 libpango-1.0-0 libcairo2 libnotify4 fonts-liberation ca-certificates"
if apt-cache show libasound2t64 >/dev/null 2>&1; then pkgs="$pkgs libasound2t64"; else pkgs="$pkgs libasound2"; fi
# Debian 11's security repo now 404s on deb.debian.org and security.debian.org (archive.debian.org has it).
# Fall back to a temporary source list for OpenBot's own dependencies only; the task's apt sources
# are untouched, and the final plain update leaves the same package index as every other trial.
if ! apt-get install -y -qq --no-install-recommends $pkgs >/dev/null; then
  { grep -rhE '^deb ' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null || true; } \
    | sed 's#deb.debian.org/debian-security#archive.debian.org/debian-security#' > /tmp/openbot-sources.list
  alt="-o Dir::Etc::sourcelist=/tmp/openbot-sources.list -o Dir::Etc::sourceparts=-"
  apt-get update -qq $alt
  apt-get install -y -qq --no-install-recommends $alt $pkgs >/dev/null
  rm -f /tmp/openbot-sources.list
  apt-get update -qq
fi

mkdir -p /root/.config /root/OpenBot
rm -rf /root/.config/OpenBot
cp -a /opt/openbot/profile /root/.config/OpenBot
cp -a /opt/openbot/home/OpenBot/. /root/OpenBot/
