set -u
X=e95a31dbae7d4ba315cee0ee6b4758d2eb7b2028
G=/home/s-a-balashov/work/vast-fixture-compiler-gate2-$X-01.guard
R=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST
[ "$(id -u)" = 1000 ] || { echo "not uid 1000"; exit 3; }
pgrep -u 1000 -x sleep >/dev/null && echo "keepalive_present" || { echo "no keepalive"; exit 3; }
[ -e $G ] && { echo "guard dir exists"; exit 3; }
mkdir -m 700 $G
echo "boot=$(cat /proc/sys/kernel/random/boot_id) start=$(date -u +%FT%TZ)"
/usr/bin/python3 -I -B $R/scripts/accepted_policy_containment_guard_v1.py --phase packet --record $G/packet.json --interval 0.5 -- \
  /mnt/c/Python314/python.exe -I -B C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests/fixtures/accepted_policy_fixture_compiler_gate2_fresh_v1.py \
  $X https://github.com/lordcoudy/VAST/pull/9#issuecomment-6950828071 \
  'C:\Users\s-a-balashov\AppData\Local\Temp\vast-gate2-fresh-e95a31dbae7d4ba315cee0ee6b4758d2eb7b2028.manifest.json' \
  43c37fa82e5118277fcce9b71bdc19fbf38d8820ee8a20779184179347036899 > $G/operator.stdout 2> $G/operator.stderr
echo "guard_rc=$? end=$(date -u +%FT%TZ)"
echo "--- operator.stdout"; cat $G/operator.stdout; echo; echo "--- operator.stderr ($(stat -c %s $G/operator.stderr) B)"; tr -d '\000' < $G/operator.stderr | head -c 1500; echo
echo "--- guard record ($(stat -c %s $G/packet.json) B)"; cat $G/packet.json
