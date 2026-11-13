set -u
D=/home/s-a-balashov/work/vast-pr9-gate2-fresh-nesting-check-01
G=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/scripts/accepted_policy_containment_guard_v1.py
[ -e $D ] && { echo "exists"; exit 3; }
mkdir -m 700 $D
echo "uid=$(id -u) start=$(date -u +%FT%TZ)"
PY="import subprocess,sys
r=subprocess.run(['C:/Windows/System32/wsl.exe','-u','s-a-balashov','--exec','/usr/bin/true']);print('true_rc',r.returncode,flush=True)
p=subprocess.Popen(['C:/Windows/System32/wsl.exe','-u','s-a-balashov','--exec','/usr/bin/sleep','20']);print('sleep_wsl_pid',p.pid,flush=True);p.wait();print('sleep_rc',p.returncode,flush=True)"
/usr/bin/python3 -I -B $G --phase nesting --record $D/nesting.json --interval 0.5 -- /mnt/c/Python314/python.exe -I -c "$PY" > $D/client.out 2> $D/client.err &
GP=$!
sleep 7
echo "before_stop: $(ps -eo pid,etimes,args | grep -E '/usr/bin/sleep 20|sleep 20$' | grep -v grep | tr '\n' ';')"
kill -TERM $GP; wait $GP; echo "guard_rc=$?"
sleep 1
echo "after_stop_linux: $(ps -eo pid,etimes,args | grep -E 'sleep 20$' | grep -v grep | tr '\n' ';')"
echo "after_stop_windows: $(/mnt/c/Windows/System32/tasklist.exe /FI 'IMAGENAME eq python.exe' /FO CSV /NH 2>/dev/null | tr -d '\r' | tr '\n' ';')"
sleep 15
echo "after_25s_linux: $(ps -eo pid,etimes,args | grep -E 'sleep 20$' | grep -v grep | tr '\n' ';')"
echo "--- client.out"; cat $D/client.out; echo "--- client.err"; head -c 600 $D/client.err; echo
echo "--- record ($(stat -c %s $D/nesting.json) B)"; cat $D/nesting.json
