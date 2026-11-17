set -u
X=ac8dedeb0a95adce144c0dcdc35fe63253ccca45
G=/home/s-a-balashov/work/vast-fixture-compiler-gate2-$X-01.guard
R=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST
[ "$(id -u)" = 1000 ] || { echo "not uid 1000"; exit 3; }
pgrep -u 1000 -x sleep >/dev/null && echo "keepalive_present" || { echo "no keepalive"; exit 3; }
[ -e $G ] && { echo "guard dir exists"; exit 3; }
mkdir -m 700 $G
echo "boot=$(cat /proc/sys/kernel/random/boot_id) start=$(date -u +%FT%TZ)"
/usr/bin/python3 -I -B $R/scripts/accepted_policy_containment_guard_v1.py --phase packet --record $G/packet.json --interval 0.5 -- \
  /mnt/c/Python314/python.exe -I -B C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests/fixtures/accepted_policy_fixture_compiler_gate2_fresh_v1.py \
  $X https://github.com/lordcoudy/VAST/pull/9#issuecomment-6859227871 \
  'C:\Users\s-a-balashov\AppData\Local\Temp\vast-gate2-fresh-ac8dedeb0a95adce144c0dcdc35fe63253ccca45.manifest.json' \
  92632fc88ffdab81a26edf7a2ef83d35741618d1e6b079736263a8ea33fdeb7d > $G/operator.stdout 2> $G/operator.stderr
echo "guard_rc=$? end=$(date -u +%FT%TZ)"
echo "--- operator.stdout"; cat $G/operator.stdout; echo; echo "--- operator.stderr ($(stat -c %s $G/operator.stderr) B)"; tr -d '\000' < $G/operator.stderr | head -c 1500; echo
echo "--- guard record"; cat $G/packet.json
