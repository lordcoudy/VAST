#!/usr/bin/env bash
# 6A.5 parity run 3: custody of runs 1-2, engine pre-check, then the unchanged recipe.
set -euo pipefail
R=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
N=$R/artifacts/qualify_full_benchmark_20261008b
J=$R/.publication-directory-journal-v1
F1=$N/parity.failed-01-desktop-exit
F2=$N/parity.failed-02-orphaned-intent
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
[[ "$(id -u)" == 1000 && -d $F1 && ! -e $F2 && ! -e $F1/journal ]]

# run 1 intents travel with the run 1 directories they describe
mkdir -m 700 $F1/journal
for key in 66a8a6253897b43f37f0da916c59a411f2163053d4db9417b771ab6c037cd948 f141f62bd0c295c03aaa86da696d6d026d171af1f2b514f55fb5f3169db9903a; do
  grep -q '"target":"artifacts/qualify_full_benchmark_20261008b/model_parity_v4/' "$J/$key.json"
  sha256sum "$J/$key.json" >> $F1/journal/intents.moved.sha256
  mv "$J/$key.json" $F1/journal/
done
(cd $F1/journal && sha256sum *.json > intents.after-move.sha256)

# run 2 outputs
mkdir -m 700 $F2
mv $N/model_parity_v4 $N/model_parity_control $N/parity.started.txt $F2/
[[ ! -e $N/parity.rc && ! -e /var/tmp/vast-parity-qfb-20261008b.failed-02 ]]
if [[ -e /var/tmp/vast-parity-qfb-20261008b ]]; then mv /var/tmp/vast-parity-qfb-20261008b /var/tmp/vast-parity-qfb-20261008b.failed-02; fi
if ls $R/configs | grep -q 20261008b; then echo "unexpected run-2 configs" >&2; exit 3; fi

# engine must still be the 6A.2 engine and the new patch must still pass live
"$PY" -B /mnt/c/Users/s-a-balashov/AppData/Local/Temp/claude/E--STUDY-VAST/4546197c-396b-4ec9-b163-4c98d5bc51cd/scratchpad/recheck.py > $N/engine-and-live-verify-before-parity-run3.v1.json
grep -q '"engine_equal": true' $N/engine-and-live-verify-before-parity-run3.v1.json
grep -q '"verify_live_images_new_patch": "PASS"' $N/engine-and-live-verify-before-parity-run3.v1.json

date -u +%FT%TZ > $N/parity.started.txt
set +e
bash $N/run_model_parity.sh
rc=$?
set -e
echo $rc > $N/parity.rc
date -u +%FT%TZ > $N/parity.finished.txt
echo parity_rc=$rc
