#!/bin/bash
# install_test.sh — multi-user installation test for agent-bus.
# Requires root. Creates a scratch group/users, runs the documented SETUP.md
# permission flow, and verifies:
#   - local agent users can complete the full workflow without sudo
#   - unrelated users cannot mutate (or even read) the bus
#   - new files/dirs keep group-only access
# Cleans up everything it creates. Idempotent-ish: fails if names collide.
set -u
BUS_SRC="$(cd "$(dirname "$0")/.." && pwd)/agent-bus"
BUS_BIN=/usr/local/bin/agent-bus-test
BUS_DIR=/srv/agent-bus-test
GROUP=agent-bus-test
USERS="bus-test agent1-test agent2-test"
OUTSIDER=outsider-test

pass=0; fail=0
ok()   { pass=$((pass+1)); echo "PASS: $1"; }
bad()  { fail=$((fail+1)); echo "FAIL: $1"; }
asu()  { su -s /bin/sh "$1" -c "$2"; }  # asu <user> <command>

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

cleanup() {
  rm -rf "$BUS_DIR" "$BUS_BIN"
  for u in $USERS $OUTSIDER; do userdel -r "$u" 2>/dev/null; done
  groupdel "$GROUP" 2>/dev/null
  echo "--- cleaned up"
}
trap cleanup EXIT

# --- setup per SETUP.md ---
groupadd "$GROUP"
for u in $USERS; do useradd -m -s /bin/sh "$u"; usermod -aG "$GROUP" "$u"; done
useradd -m -s /bin/sh "$OUTSIDER"
mkdir -p "$BUS_DIR"
cp "$BUS_SRC" "$BUS_BIN" && chmod 755 "$BUS_BIN"
cp "$(dirname "$BUS_SRC")/registry.seed.json" /usr/local/bin/registry.seed.json
chmod 644 /usr/local/bin/registry.seed.json
AGENT_BUS_GROUP="$GROUP" "$BUS_BIN" --bus "$BUS_DIR" init >/dev/null

# --- full workflow as local agents, no sudo ---
TID=$(asu agent1-test "AGENT_BUS_GROUP=$GROUP $BUS_BIN --bus $BUS_DIR propose --from omni --subject hello" | python3 -c "import json,sys; print(json.load(sys.stdin)['proposed'])")
[ -n "$TID" ] && ok "agent1 proposed $TID" || bad "agent1 propose"

asu agent1-test "AGENT_BUS_GROUP=$GROUP $BUS_BIN --bus $BUS_DIR send --from omni --to codex --subject hi --body yo" >/dev/null \
  && ok "agent1 sent message" || bad "agent1 send"

MID=$(asu agent2-test "AGENT_BUS_GROUP=$GROUP $BUS_BIN --bus $BUS_DIR inbox codex" | head -1 | awk '{print $1}')
[ -n "$MID" ] && ok "agent2 read codex inbox" || bad "agent2 inbox"

asu agent2-test "AGENT_BUS_GROUP=$GROUP $BUS_BIN --bus $BUS_DIR claim codex $TID" >/dev/null \
  && ok "agent2 claimed task" || bad "agent2 claim"

asu agent2-test "AGENT_BUS_GROUP=$GROUP $BUS_BIN --bus $BUS_DIR finish codex $TID --note done" >/dev/null \
  && ok "agent2 finished task" || bad "agent2 finish"

asu agent2-test "AGENT_BUS_GROUP=$GROUP $BUS_BIN --bus $BUS_DIR ack codex $MID" >/dev/null \
  && ok "agent2 acked message" || bad "agent2 ack"

asu agent1-test "AGENT_BUS_GROUP=$GROUP $BUS_BIN --bus $BUS_DIR log --from omni --event t" >/dev/null \
  && ok "agent1 wrote log" || bad "agent1 log"

# --- outsider cannot mutate or read ---
if asu "$OUTSIDER" "$BUS_BIN --bus $BUS_DIR send --from omni --to codex --subject x" >/dev/null 2>&1; then
  bad "outsider was able to send"
else
  ok "outsider cannot send"
fi
if asu "$OUTSIDER" "$BUS_BIN --bus $BUS_DIR inbox codex" >/dev/null 2>&1; then
  bad "outsider was able to read inbox"
else
  ok "outsider cannot read inbox"
fi

# --- modes ---
mode=$(stat -c %a "$BUS_DIR/inbox/omni")
[ "$mode" = 2770 ] && ok "inbox dir is 2770" || bad "inbox dir mode=$mode"
fmode=$(stat -c %a "$BUS_DIR"/inbox/codex/archive/*.json | head -1)
[ "$fmode" = 660 ] && ok "acked message file is 660" || bad "message file mode=$fmode"
grp=$(stat -c %G "$BUS_DIR/tasks/done/$TID.json")
[ "$grp" = "$GROUP" ] && ok "task file group is $GROUP" || bad "task file group=$grp"

echo "--- $pass passed, $fail failed"
[ "$fail" = 0 ]
