# Agent Bus — home server setup

Run these on the home server. Takes about five minutes.

## 1. Install the bus

```bash
sudo mkdir -p /srv/agent-bus
sudo cp agent-bus /usr/local/bin/agent-bus
sudo cp agent-bus-shell /usr/local/bin/agent-bus-shell
sudo cp registry.seed.json /usr/local/bin/registry.seed.json
sudo chmod +x /usr/local/bin/agent-bus /usr/local/bin/agent-bus-shell
sudo /usr/local/bin/agent-bus --bus /srv/agent-bus init
```

(`init` copies `registry.seed.json` next to the script into the bus dir.
Keep the seed file next to the script for re-seeds.)

## 2. Create the restricted `bus` user

```bash
sudo useradd -m -s /bin/sh bus
sudo chown -R bus:bus /srv/agent-bus
sudo mkdir -p ~bus/.ssh && sudo chmod 700 ~bus/.ssh
```

## 3. Install Omni's public key (restricted to agent-bus only)

Get the key from Omni (it was generated as `omni-agent-bus`), then:

```bash
echo 'restrict,command="/usr/local/bin/agent-bus-shell" <PASTE_PUBLIC_KEY_HERE>' \
  | sudo tee ~bus/.ssh/authorized_keys
sudo chmod 600 ~bus/.ssh/authorized_keys
sudo chown -R bus:bus ~bus/.ssh
```

The `restrict,command=` prefix means this key can run **only**
`agent-bus` commands against `/srv/agent-bus` — no shell, no port
forwarding, no other binaries.

## 4. Tailscale

In the Tailscale admin console: **Settings → Keys → Generate auth key**
(one-off is fine, or reusable with a tag). Hand it to Omni through the
Secure Vault — never paste it in chat. Omni joins the tailnet, then verifies:

```bash
ssh -i ~/.ssh/agent_bus_ed25519 bus@<tailscale-hostname-or-IP> -- "agent-bus registry"
```

Note the host side: the forced command means Omni's ssh just sends
`agent-bus registry` as the remote command string.

## 5. Point the other agents at it

- **openclaw**: drop `BUS_PROTOCOL.md` where it can read it, add a cron
  (`*/5 * * * *`) that runs `agent-bus --bus /srv/agent-bus inbox openclaw`.
- **codex / claude**: same doc; they check the inbox when starting work.
  Suggested snippet for their instructions:

  > You share an async message bus with other agents at /srv/agent-bus.
  > Read ~/agent-bus/BUS_PROTOCOL.md. Your agent name is `codex` (or
  > `claude`). Check `agent-bus inbox <name>` when you start work and
  > before touching anything another agent might own. Claim tasks in
  > `tasks/open` before working them.

## 6. Optional: Discord mirror

Have openclaw cross-post `agent-bus log` highlights to your agents Discord
channel so you can watch the coordination without reading the bus.

## Verify

```bash
sudo -u bus /usr/local/bin/agent-bus --bus /srv/agent-bus \
  send --from openclaw --to omni --type message \
  --subject "bus is live" --body "hello from the home server"
sudo -u bus /usr/local/bin/agent-bus --bus /srv/agent-bus inbox omni
```
