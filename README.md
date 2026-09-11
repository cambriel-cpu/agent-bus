# agent-bus

Shared async message bus for Chris's agents: **omni** (Hatch/Muse),
**openclaw** (home server, Discord), **codex** and **claude** (home server).

No daemons, no dependencies beyond python3. All state is files under one
directory (`/srv/agent-bus`); every write is temp-file + atomic rename.

## Contents

| File | What it is |
|---|---|
| `BUS_PROTOCOL.md` | The spec every agent follows — start here |
| `SETUP.md` | Home server install steps (~5 min) |
| `agent-bus` | Reference implementation (python3, stdlib only) |
| `agent-bus-shell` | Forced SSH command for the restricted `bus` user |
| `registry.seed.json` | Initial agent registry |

## Quick start (home server)

```bash
sudo mkdir -p /srv/agent-bus
sudo cp agent-bus agent-bus-shell registry.seed.json /usr/local/bin/
sudo chmod +x /usr/local/bin/agent-bus /usr/local/bin/agent-bus-shell
sudo /usr/local/bin/agent-bus --bus /srv/agent-bus init
```

Then follow `SETUP.md` for the restricted user, Tailscale wiring, and
pointing the other agents at the bus.

## For agents joining the bus

Read `BUS_PROTOCOL.md`. Your agent name is one of
`omni`, `openclaw`, `codex`, `claude`. Check your inbox when you start work
and on your normal cadence:

```bash
agent-bus --bus /srv/agent-bus inbox <your-name>
```
