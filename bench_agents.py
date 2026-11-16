import os
import tarfile
from pathlib import Path

import yaml

from harbor.agents.installed.base import BaseInstalledAgent
from harbor.agents.installed.hermes import Hermes

OPENBOT_DIR = Path(__file__).parent / "openbot"
OPENBOT_TAR = OPENBOT_DIR / "payload.tar"
HERMES_TAR = Path(__file__).parent / "hermes" / "payload.tar"


async def restore_livedin_state(agent, environment):
    """Lived-in track: unpack the profile the previous task left behind (see livedin.py)."""
    state = os.environ.get("LIVEDIN_STATE")
    if not state or not Path(state).exists():
        return
    await environment.upload_file(state, "/tmp/livedin-state.tar")
    await agent.exec_as_root(environment, command="tar -xf /tmp/livedin-state.tar -C / && rm /tmp/livedin-state.tar")


async def frame_instruction(instruction, environment):
    """Identical framing for every harness: OpenBot's agent starts in its own workspace,
    not the task WORKDIR, and 13/89 TB2 instructions use relative paths."""
    result = await environment.exec(command="pwd")
    workdir = (result.stdout or "").strip() or "/app"
    return f"Working directory for this task: {workdir}\n\n{instruction}"


class HermesHigh(Hermes):
    """Stock Harbor hermes agent with agent.reasoning_effort pinned to high.

    deepseek-v4.1-flash-1017 on OpenRouter accepts none/low/high/max only (no medium),
    and high matches what OpenBot's Pi runtime sends for its "High" setting.
    """

    # Harbor 0.25.0 probes with `hermes version`; v0.23.x only has `hermes --version`.
    def get_version_command(self):
        return 'export PATH="$HOME/.local/bin:$PATH"; hermes --version'

    async def install(self, environment):
        """Unpack a pre-built v0.23.1 install (same installer + `hermes pm repair` Harbor runs,
        done once) instead of installing from the network in every container. Its data root
        /tmp/hermes is the installer's pristine one: no memories or sessions, and no skills until
        Hermes copies in its 44 bundled ones on first start."""
        try:
            await self.ensure_system_dependencies(
                environment, ("curl", "git", "ripgrep", "xz")
            )
        except Exception:
            # Debian 11's security repo 404s on deb.debian.org (same fallback as openbot/setup.sh):
            # a temporary source list for these harness dependencies only; task sources untouched.
            await self.exec_as_root(
                environment,
                command=(
                    "set -euo pipefail; "
                    "{ grep -rhE '^deb ' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null || true; } "
                    "| sed 's#deb.debian.org/debian-security#archive.debian.org/debian-security#' > /tmp/hermes-sources.list; "
                    'alt="-o Dir::Etc::sourcelist=/tmp/hermes-sources.list -o Dir::Etc::sourceparts=-"; '
                    "apt-get update -qq $alt && "
                    "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $alt curl git ripgrep xz-utils >/dev/null; "
                    "rm -f /tmp/hermes-sources.list; apt-get update -qq"
                ),
            )
        await environment.upload_file(HERMES_TAR, "/tmp/hermes-payload.tar")
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; tar -xf /tmp/hermes-payload.tar -C / && rm /tmp/hermes-payload.tar && "
                'export PATH="$HOME/.local/bin:$PATH" HERMES_HOME=/tmp/hermes && hermes --version'
            ),
        )
        await restore_livedin_state(self, environment)

    async def run(self, instruction, environment, context):
        try:
            await super().run(await frame_instruction(instruction, environment), environment, context)
        finally:
            # Hermes adds each API call's tokens to state.db; on a timeout the session export is
            # empty, so this copy is where compare.py gets the timed-out trial's usage.
            await self.exec_as_root(
                environment,
                command="cp /tmp/hermes/state.db* /logs/agent/ 2>/dev/null; true",
            )

    @staticmethod
    def _build_config_yaml(model, max_turns=None, *, connection=None):
        config = yaml.safe_load(
            Hermes._build_config_yaml(model, max_turns, connection=connection)
        )
        config.setdefault("agent", {})["reasoning_effort"] = "high"
        # Harbor turns memory off; Hermes's stock default is on, and the Lived-in track needs it.
        config["memory"] = {"memory_enabled": True, "user_profile_enabled": True}
        # The "No thanks" a user picks at the first-run telemetry prompt (as on the OpenBot account),
        # recorded the way Hermes records it, so the prompt can't swallow the Lived-in /refine.
        config["telemetry"] = {"shared_metrics": {"enabled": False, "send": False, "offer_version": 2}}
        return yaml.dump(config, default_flow_style=False)


class OpenBotTB(BaseInstalledAgent):
    """OpenBot 0.65.0 desktop app (TB-Bench agent: OpenRouter via Pi 1.5.2, effort High),
    run on Xvfb inside the task container and driven through its UI over CDP.
    Model and effort live in the packaged profile, not in Harbor's -m flag."""

    @staticmethod
    def name():
        return "openbot"

    def version(self):
        return "0.65.0+pi-1.5.2"

    async def install(self, environment):
        if not OPENBOT_TAR.exists():
            with tarfile.open(OPENBOT_TAR, "w") as tar:
                tar.add(OPENBOT_DIR / "payload", arcname=".")
        await environment.upload_file(OPENBOT_TAR, "/tmp/openbot-payload.tar")
        for f in ("setup.sh", "launch.sh", "driver.js", "learn.js"):
            await environment.upload_file(OPENBOT_DIR / f, f"/tmp/openbot-{f}")
        await self.exec_as_root(
            environment,
            command=(
                "set -euo pipefail; mkdir -p /opt/openbot && "
                "tar -xf /tmp/openbot-payload.tar -C /opt/openbot && rm /tmp/openbot-payload.tar && "
                "for f in setup.sh launch.sh driver.js learn.js; do mv /tmp/openbot-$f /opt/openbot/$f; done && "
                "bash /opt/openbot/setup.sh"
            ),
        )
        await restore_livedin_state(self, environment)

    async def run(self, instruction, environment, context):
        prompt = await frame_instruction(instruction, environment)
        local = self.logs_dir / "instruction.txt"
        local.write_text(prompt)
        await environment.upload_file(local, "/tmp/openbot-instruction.txt")
        await self.exec_as_root(environment, command="bash /opt/openbot/launch.sh")
        try:
            result = await self.exec_as_root(
                environment,
                command=(
                    "set -o pipefail; "
                    "/opt/openbot/profile/provider-runtimes/bun/linux-x64/1.4.4/bin/bun /opt/openbot/driver.js "
                    "/tmp/openbot-instruction.txt /logs/agent/openbot-transcript.txt "
                    "2>&1 | tee /logs/agent/driver.txt"
                ),
            )
        finally:
            await self.exec_as_root(
                environment,
                command=(
                    "pgrep -f 'driver[.]js /tmp/openbot-instruction' >/dev/null && { pkill -f 'driver[.]js /tmp/openbot-instruction'; "
                    "/opt/openbot/profile/provider-runtimes/bun/linux-x64/1.4.4/bin/bun /opt/openbot/driver.js --stop "
                    "/logs/agent/openbot-transcript.txt >> /logs/agent/driver.txt 2>&1; }; "
                    "cp /tmp/openbot.log /logs/agent/openbot-app.log 2>/dev/null; "
                    "cp /root/.config/OpenBot/openbot.db* /logs/agent/ 2>/dev/null; true"
                ),
            )
            # Lived-in track: the learning pass runs here, after the task's usage is copied out, in
            # the same app session as the task. OpenBot counts a thread's turns in memory only, so
            # archiving the thread after a restart finds nothing to review.
            if os.environ.get("LIVEDIN_STATE"):
                await self.exec_as_root(
                    environment,
                    command=(
                        "/opt/openbot/profile/provider-runtimes/bun/linux-x64/1.4.4/bin/bun /opt/openbot/learn.js "
                        "> /logs/agent/learn.txt 2>&1; true"
                    ),
                )
        return result
