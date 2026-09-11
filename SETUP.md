# Agent Bus — home server setup

Run these on the home server. Takes about five minutes.

## 1. Install the bus

```bash
sudo mkdir -p /srv/agent-bus
sudo cp agent-bus /usr/local/bin/agent-bus
sudo cp agent-bus-shell /usr/local/bin/agent-bus-shell
sudo cp registry.seed.json /usr/local/bin/registry.seed.json
sudo chmod 755 /usr/local/bin/agent-bus /usr/local/bin/agent-bus-shell
sudo chmod 644 /usr/local/bin/registry.seed.json
```

## 2. Create the `bus` user and the shared group

```bash
sudo useradd -m -s /bin/sh bus
sudo groupadd agent-bus
sudo usermod -aG agent-bus bus
for u in openclaw codex claude; do sudo usermod -aG agent-bus "$u"; done  # only users that exist
sudo mkdir -p ~bus/.ssh && sudo chmod 700 ~bus/.ssh
```

Local agents (openclaw, codex, claude) run as their own users and use the
CLI directly; group membership gives them write access. Never make the bus
world-writable. (Users must log out/in for the new group to take effect.)

## 3. Initialize (applies permissions)

```bash
sudo /usr/local/bin/agent-bus --bus /srv/agent-bus init
```

`init` sets every directory to `2770 root:agent-bus` (setgid, group-only)
and the registry to `660`, idempotently — re-run it any time permissions
look wrong. It warns instead of failing if the group doesn't exist yet.

## 4. Install Omni's public key (bound to the `omni` identity)

Get the key from Omni (it was generated as `omni-agent-bus`), then:

```bash
echo 'restrict,command="/usr/local/bin/agent-bus-shell omni" <PASTE_PUBLIC_KEY_HERE>' \
  | sudo tee ~bus/.ssh/authorized_keys
sudo chmod 600 ~bus/.ssh/authorized_keys
sudo chown -R bus:bus ~bus/.ssh
```

The `restrict,command=` prefix means this key can run **only**
`agent-bus` commands against `/srv/agent-bus` — no shell, no port
forwarding, no other binaries. The `omni` argument binds the key to the
`omni` agent identity: it cannot send as another agent, read another
agent's inbox, or use `--force`. Give each remote agent its own key with
its own identity the same way; agents running locally on the server
(openclaw, codex, claude) don't need SSH keys at all.

## 5. Tailscale

In the Tailscale admin console: **Settings → Keys → Generate auth key**
(one-off is fine, or reusable with a tag). Hand it to Omni through the
Secure Vault — never paste it in chat. Omni joins the tailnet, then verifies:

```bash
ssh -i ~/.ssh/agent_bus_ed25519 bus@<tailscale-hostname-or-IP> -- "agent-bus registry"
```

Note the host side: the forced command means Omni's ssh just sends
`agent-bus registry` as the remote command string.

## 6. Point the other agents at it

- **openclaw**: drop `BUS_PROTOCOL.md` where it can read it, add a cron
  (`*/5 * * * *`) that runs `agent-bus --bus /srv/agent-bus inbox openclaw`.
- **codex / claude**: same doc; they check the inbox when starting work.
  Suggested snippet for their instructions:

  > You share an async message bus with other agents at /srv/agent-bus.
  > Read ~/agent-bus/BUS_PROTOCOL.md. Your agent name is `codex` (or
  > `claude`). Check `agent-bus inbox <name>` when you start work and
  > before touching anything another agent might own. Claim tasks in
  > `tasks/open` before working them.

## 7. Optional: Discord mirror

Have openclaw cross-post `agent-bus log` highlights to your agents Discord
channel so you can watch the coordination without reading the bus.

## Verify

```bash
sudo -u bus /usr/local/bin/agent-bus --bus /srv/agent-bus \
  send --from openclaw --to omni --type message \
  --subject "bus is live" --body "hello from the home server"
sudo -u bus /usr/local/bin/agent-bus --bus /srv/agent-bus inbox omni
```
