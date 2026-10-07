#!/usr/bin/env bash
# Start Minecraft with the mod for one build target and check it reaches the
# title screen with the Friends button (the mod prints "[Jace Friends] ... ready").
#   ci/smoke.sh 1.21.1-fabric
set -u
node="$1"
loader="${node##*-}"
# skip the first-launch accessibility screen so the title screen comes up directly
# (loaders differ on whether the game runs in run/ or versions/<node>/run/)
for dir in run "versions/$node/run"; do
  mkdir -p "$dir"
  printf 'onboardAccessibility:false\nnarrator:0\nsoundCategory_master:0.0\n' > "$dir/options.txt"
done
task="runClient"
log="smoke-$node.log"
# own process group, so we can close the game (and only the game) afterwards
setsid xvfb-run -a -s "-screen 0 1280x720x24 +extension GLX +render -noreset" ./gradlew ":$node:$task" --no-daemon > "$log" 2>&1 &
pid=$!
result=timeout
for _ in $(seq 1 180); do              # up to 15 minutes (first run downloads assets)
  sleep 5
  if grep -q "\[Jace Friends\] .* ready on Minecraft" "$log"; then result=ok; break; fi
  if grep -qE "Minecraft Crash Report|Crash report saved|Exception in thread \"Render thread\"|BUILD FAILED|FAILURE:" "$log"; then result=crash; break; fi
  if ! kill -0 $pid 2>/dev/null; then result=exited; break; fi
done
grep -E "\[Jace Friends\]|Loading [0-9]+ mods|jacefriends|ERROR|Exception" "$log" | grep -v "^\s*at " | head -25
echo "SMOKE $node: $result"
kill -- -"$pid" 2>/dev/null       # the whole group: gradle, the game and Xvfb
sleep 2
kill -9 -- -"$pid" 2>/dev/null
[ "$result" = ok ]
