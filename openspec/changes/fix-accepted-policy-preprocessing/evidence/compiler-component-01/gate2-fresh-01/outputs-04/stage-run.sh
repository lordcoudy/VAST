# One guarded C or D stage (V9 sections 4 and 6). Usage: stage-run.sh <C1..C6|D> <prior or ->
set -u
STAGE=$1; PRIOR=$2
X=e95a31dbae7d4ba315cee0ee6b4758d2eb7b2028
SIZE=17937; SHA=fd4c6a8faee9619affb419e6be6cf05b709a1fbcb38b79ce0abaa8015fd06c9f
BOOT=1acfa8df-8b76-45d2-8945-57115a0d1f56
B=/home/s-a-balashov/work/vast-fixture-compiler-gate2-$X-01
G=$B.guard
R=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST
[ "$(id -u)" = 1000 ] || { echo "not uid 1000"; exit 3; }
pgrep -u 1000 -x sleep >/dev/null && echo "keepalive_present" || { echo "no keepalive"; exit 3; }
[ "$(cat /proc/sys/kernel/random/boot_id)" = "$BOOT" ] || { echo "boot_changed"; exit 3; }
[ -e $G/$STAGE.json ] && { echo "record exists"; exit 3; }
case $STAGE in
  C1|C2|C3|C4|C5|C6) CMD="/usr/bin/python3 -B $B/tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py $STAGE $X $SIZE $SHA $PRIOR";;
  D) CMD="/usr/bin/python3 -B $B/tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py $X $SIZE $SHA $PRIOR";;
  *) echo "bad stage"; exit 3;;
esac
echo "stage=$STAGE boot=$BOOT start=$(date -u +%FT%TZ)"
/usr/bin/python3 -I -B $R/scripts/accepted_policy_containment_guard_v1.py --phase $STAGE --record $G/$STAGE.json --interval 0.5 -- \
  $CMD > $G/$STAGE.stdout 2> $G/$STAGE.stderr
echo "guard_rc=$? end=$(date -u +%FT%TZ) boot_after=$(cat /proc/sys/kernel/random/boot_id)"
echo "--- stdout $(stat -c %s $G/$STAGE.stdout) B sha=$(sha256sum < $G/$STAGE.stdout | cut -c1-64)"
head -c 2500 $G/$STAGE.stdout; echo
echo "--- stderr $(stat -c %s $G/$STAGE.stderr) B"; tr -d '\000' < $G/$STAGE.stderr | head -c 1500; echo
echo "--- guard record $(stat -c %s $G/$STAGE.json) B"; cat $G/$STAGE.json; echo
O=$B/outputs/$STAGE/outer.invocation.original.json
[ "$STAGE" != D ] && [ -f $O ] && echo "outer=$(stat -c %s $O):$(sha256sum < $O | cut -c1-64)"
