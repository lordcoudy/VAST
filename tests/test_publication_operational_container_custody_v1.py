"""Separate exact-container custody regressions; fixtures grant no publication."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import publication_operational_container_custody_v1 as custody
import publication_operational_process_custody_v1 as process_custody
import checkpoint_gstreamer_publication_runtime_v3 as runtime
from publication_operational_runtime_context_v1 import _materialize_operational_file_v1
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1


ENGINE_SOURCE = r'''
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <stdlib.h>
static const char *cid = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static void pause_fixture(void) { struct timespec delay = {0, 120000000}; nanosleep(&delay, NULL); }
int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "info") == 0) { pause_fixture(); puts("\"fixture-daemon-1\""); return 0; }
    if (argc > 2 && strcmp(argv[1], "container") == 0) {
        char saved_cid[80], name[100], label[80], created[100]; int running;
        FILE *state = fopen(STATE_FILE, "r");
        if (!state) { pause_fixture(); fprintf(stderr,"Error response from daemon: No such container: %s\n",argv[argc-1]); return 1; }
        if (fscanf(state,"%79s %99s %79s %99s %d",saved_cid,name,label,created,&running) != 5) return 8;
        fclose(state);
        if (strcmp(argv[2], "stop") == 0) {
            if (strcmp(argv[argc-1], saved_cid) != 0) return 9;
            state=fopen(STATE_FILE,"w"); fprintf(state,"%s %s %s %s 0\n",saved_cid,name,label,created); fclose(state);
            pause_fixture(); puts(saved_cid); return 0;
        }
        if (strcmp(argv[argc-1], saved_cid) != 0 && strcmp(argv[argc-1], name) != 0) return 10;
        pause_fixture();
        printf("{\"Id\":\"%s\",\"Name\":\"/%s\",\"Image\":\"sha256:1111111111111111111111111111111111111111111111111111111111111111\",\"Created\":\"%s\",\"Running\":%s,\"OOMKilled\":false,\"ExitCode\":0,\"Pid\":%d,\"StartedAt\":\"%s\",\"FinishedAt\":\"%s\",\"Operation\":\"%s\"}\n",saved_cid,name,created,running?"true":"false",running?getpid():0,created,created,label); return 0;
    }
    if (argc > 1 && strcmp(argv[1], "run") == 0) {
        const char *cidfile=NULL,*name=NULL,*label=NULL,*mode="success";
        for (int i=2;i+1<argc;i++) {
            if(strcmp(argv[i],"--cidfile")==0) cidfile=argv[i+1];
            if(strcmp(argv[i],"--name")==0) name=argv[i+1];
            if(strcmp(argv[i],"--label")==0) label=strchr(argv[i+1],'=')+1;
            if(strcmp(argv[i],"--fixture-mode")==0) mode=argv[i+1];
        }
        if(!cidfile||!name||!label) return 11;
        struct timespec now; clock_gettime(CLOCK_REALTIME,&now); struct tm utc; gmtime_r(&now.tv_sec,&utc);
        char seconds[64],created[100]; strftime(seconds,sizeof(seconds),"%Y-%m-%dT%H:%M:%S",&utc);
        snprintf(created,sizeof(created),"%s.%09ldZ",seconds,now.tv_nsec);
        FILE *f=fopen(cidfile,"w"); fprintf(f,"%s\n",cid); fclose(f);
        f=fopen(STATE_FILE,"w");fprintf(f,"%s %s %s %s 1\n",cid,name,label,created);fclose(f);
        f=fopen(OPDIR "/native_operational_requests.v1.jsonl","w");
        fputs("{\"fixture_only\":true,\"no_native_content_acceptance\":true}\n",f);fclose(f);
        pause_fixture();
        if(strcmp(mode,"timeout")==0) sleep(30);
        puts("original measurement");
        if(strcmp(mode,"failure")==0) return 7;
        if(strcmp(mode,"retained_success")==0) {
            f=fopen(STATE_FILE,"w");fprintf(f,"%s %s %s %s 0\n",cid,name,label,created);fclose(f);return 0;
        }
        unlink(STATE_FILE); return 0;
    }
    return 12;
}
'''


class ContainerCustodyContractTests(unittest.TestCase):
    def test_inactive_measurement_does_not_change_original_arguments(self):
        arguments = ("run", "--rm", "sha256:" + "a" * 64)
        with mock.patch.object(custody, "current_original_engine_capture_v1", return_value=None):
            with custody.measurement_container_custody_v1(None, None, arguments) as owned:
                self.assertEqual(owned.argv, arguments)
                owned.completed(0)
                self.assertIsNone(owned.receipt_descriptor)

    def test_noncanonical_or_foreign_not_found_is_not_positive_absence(self):
        cid = "a" * 64
        for stderr in (b"permission denied", b"No such container: other", b"", b"engine unavailable"):
            with self.subTest(stderr=stderr):
                self.assertFalse(custody._confirmed_absent(1, b"", stderr, cid))
        self.assertTrue(custody._confirmed_absent(1, b"", ("Error response from daemon: No such container: " + cid + "\n").encode(), cid))
        exact = ("Error response from daemon: No such container: " + cid + "\n").encode()
        self.assertTrue(custody._confirmed_absent(1, b"\n", exact, cid))
        for stdout in (b" ", b"\t", b"\r\n", b"\n\n", b" \n", b"{}\n", b"foreign\n"):
            with self.subTest(stdout=stdout):
                self.assertFalse(custody._confirmed_absent(1, stdout, exact, cid))
        for code in (0, 2, -9, True):
            self.assertFalse(custody._confirmed_absent(code, b"\n", exact, cid))
        for stderr in (exact + b"\n", exact.replace(cid.encode(), b"other"), b"permission denied\n"):
            self.assertFalse(custody._confirmed_absent(1, b"\n", stderr, cid))

    def test_cid_is_exact_original_regular_single_link_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            original = root / "measurement.cid"
            original.write_bytes(b"a" * 64 + b"\n")
            self.assertEqual(custody._read_cid(original)[0], "a" * 64)
            original.write_bytes(b"a" * 64 + b"\nforeign")
            with self.assertRaises(ValueError):
                custody._read_cid(original)
            original.unlink()
            target = root / "other.cid"
            target.write_bytes(b"a" * 64)
            original.symlink_to(target)
            with self.assertRaises(ValueError):
                custody._read_cid(original)


@unittest.skipUnless(sys.platform == "linux" and shutil.which("cc"), "genuine held ELF fixture requires Linux C compiler")
class OriginalContainerCompositionTests(unittest.TestCase):
    """A local ELF models daemon replies; it is explicitly no real-Docker proof."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.operational = self.root / "operational"
        self.operational.mkdir(mode=0o700)
        self.state = self.root / "fixture.state"
        source = self.root / "fixture-engine.c"
        source.write_text(ENGINE_SOURCE)
        executable = self.root / "fixture-engine"
        subprocess.run([shutil.which("cc"), "-O0", "-std=c11", '-DSTATE_FILE="' + str(self.state) + '"',
            '-DOPDIR="' + str(self.operational) + '"',
            str(source), "-o", str(executable)], check=True, capture_output=True)
        self.fd = os.open(executable, os.O_RDONLY)
        self.addCleanup(os.close, self.fd)
        raw = executable.read_bytes()
        self.engine = SimpleNamespace(path=executable, fd=self.fd, size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), proc_path=f"/proc/self/fd/{self.fd}")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.sock.close)
        path = self.root / "engine.sock"
        self.sock.bind(str(path))
        info = path.lstat()
        self.socket = {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
            "owner_uid": info.st_uid, "owner_gid": info.st_gid}
        self.context = self.write("context.json", {"fixture_only": True, "operation_id": "original-1"})
        self.image = {"image_id": "sha256:" + "1" * 64, "repository_digest": "fixture/image@sha256:" + "2" * 64,
            "inspect_projection_sha256": "3" * 64, "base_image_id": "sha256:" + "4" * 64}
        self.native_target = self.root / "native"
        self.original = self.write("original.json", payload_with_sha256_v1({"schema_version": 1,
            "artifact_kind": "vast_original_native_operation_input_v1", "operation": {
                "fixture_only": True, "operation_id": "original-1", "system": "gstreamer_custom"},
            "container_image": self.image, "outputs": {"measurement_dir": str(self.root / "measurement"),
                "native_domain": str(self.native_target / "native_operational_requests.v1.jsonl"),
                "process_receipt": str(self.root / "process/original_engine_process_capture.v1.json"),
                "container_receipt": str(self.root / "process/container-custody/original_container_custody.v1.json")}}))

    def write(self, name, value):
        path = self.root / name
        raw = canonical_json_v1(value) + b"\n"
        path.write_bytes(raw)
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def capture(self):
        return process_custody.capture_original_engine_processes_v1(project_root=self.root,
            output_dir=self.root / "process", operation_id="original-1", original_operation_descriptor=self.original,
            native_context_descriptor=self.context, container_image=self.image)

    def measure(self, mode="success", timeout=5):
        arguments = ("run", "--rm", "--mount", f"type=bind,src={self.root},dst=/workspace/project,readonly",
            "--mount", f"type=bind,src={self.operational},dst=/opt/vast/operational",
            self.image["image_id"], "--operational-request-context", "/workspace/project/context.json",
            "--operational-output-dir", "/opt/vast/operational", "--fixture-mode", mode)
        with process_custody.original_engine_phase_v1("measurement"), custody.measurement_container_custody_v1(
                self.engine, self.socket, arguments) as owned:
            result = runtime._invoke_engine(self.engine, self.socket, owned.argv, timeout)
            owned.completed(result.returncode)
        if result.returncode == 0:
            _materialize_operational_file_v1(self.root, self.operational, self.native_target)

    def validate(self, capture):
        return custody.original_container_validator_v1(project_root=self.root,
            receipt_path=capture.container_receipt_descriptor["path"], expected_descriptor=capture.container_receipt_descriptor,
            process_receipt_path=capture.receipt_descriptor["path"], expected_process_descriptor=capture.receipt_descriptor,
            operation_id="original-1", original_operation_descriptor=self.original,
            native_context_descriptor=self.context, expected_container_image=self.image)

    def test_actual_process_and_original_cid_receipts_compose_through_cold_readers(self):
        with self.capture() as capture:
            self.measure()
        result = self.validate(capture)
        self.assertEqual(result["container_id"], "a" * 64)
        self.assertTrue(result["container_quiescence_verified"])
        self.assertIsNone(result["container_state"])
        self.assertIsNone(result["oom_killed"])
        self.assertFalse(self.state.exists())
        receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        self.assertEqual(receipt["measurement_returncode"], 0)
        self.assertEqual(len(receipt["commands"]), 4)
        witnesses = result["validated_inputs"]
        self.assertEqual(len({row["descriptor"]["path"] for row in witnesses}), len(witnesses))
        container_files = set(Path(capture.container_receipt_descriptor["path"]).parent.iterdir())
        self.assertTrue(container_files.issubset({Path(row["descriptor"]["path"]) for row in witnesses}))
        for row in witnesses:
            info = Path(row["descriptor"]["path"]).lstat()
            self.assertEqual(row["epoch"], [info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns])

    def test_actual_retained_terminal_and_resealed_invalid_times_are_checked(self):
        with self.capture() as capture:
            self.measure("retained_success")
        result = self.validate(capture)
        self.assertFalse(result["container_state"]["Running"])
        self.assertEqual(result["container_state"]["Pid"], 0)
        receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        command = json.loads(Path(receipt["commands"][2]["path"]).read_bytes())
        original_output = json.loads(Path(command["stdout"]["path"]).read_bytes())
        original_state = json.loads(original_output["content"])
        cases = ({"StartedAt": "0001-01-01T00:00:00Z", "FinishedAt": "0001-01-01T00:00:00Z"},
            {"FinishedAt": "1970-01-01T00:00:00Z"}, {"FinishedAt": "2999-01-01T00:00:00Z"}, {"Pid": 1})
        for changes in cases:
            with self.subTest(changes=changes):
                state = {**original_state, **changes}
                output = {**original_output, "content": canonical_json_v1(state).decode() + "\n"}
                output["size_bytes"] = len(output["content"].encode())
                output["content_sha256"] = hashlib.sha256(output["content"].encode()).hexdigest()
                command["stdout"] = self.rewrite(command["stdout"], output)
                receipt["commands"][2] = self.rewrite(receipt["commands"][2], command)
                capture.container_receipt_descriptor = self.rewrite(capture.container_receipt_descriptor, receipt)
                with self.assertRaisesRegex(ValueError, "terminal timestamp order|failed or remains running"):
                    self.validate(capture)

    def test_actual_gva_three_field_image_is_preserved_without_fabricated_base(self):
        self.image = {key: value for key, value in self.image.items() if key != "base_image_id"}
        value = json.loads(Path(self.original["path"]).read_bytes())
        value["container_image"] = self.image
        value["operation"]["system"] = "openvino_gva"
        self.original = self.write("original.json", payload_with_sha256_v1(value))
        with self.capture() as capture:
            self.measure()
        result = self.validate(capture)
        self.assertTrue(result["container_quiescence_verified"])
        receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        self.assertEqual(receipt["container_image"], self.image)
        self.assertEqual(set(receipt["container_image"]), {"image_id", "repository_digest", "inspect_projection_sha256"})

    def rewrite(self, descriptor, value):
        path = Path(descriptor["path"])
        path.chmod(0o644)
        raw = canonical_json_v1(payload_with_sha256_v1(value)) + b"\n"
        path.write_bytes(raw)
        path.chmod(0o444)
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def test_resealed_foreign_absence_cannot_grant_quiescence(self):
        with self.capture() as capture:
            self.measure()
        original_receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        terminal = json.loads(Path(original_receipt["commands"][2]["path"]).read_bytes())
        output = json.loads(Path(terminal["stderr"]["path"]).read_bytes())
        output["content"] = output["content"].replace("a" * 64, "b" * 64)
        output["size_bytes"] = len(output["content"].encode())
        output["content_sha256"] = hashlib.sha256(output["content"].encode()).hexdigest()
        terminal["stderr"] = self.rewrite(terminal["stderr"], output)
        original_receipt["commands"][2] = self.rewrite(original_receipt["commands"][2], terminal)
        capture.container_receipt_descriptor = self.rewrite(capture.container_receipt_descriptor, original_receipt)
        with self.assertRaisesRegex(ValueError, "terminal unavailable"):
            self.validate(capture)

    def test_resealed_foreign_daemon_identity_cannot_grant_quiescence(self):
        with self.capture() as capture:
            self.measure()
        receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        command = json.loads(Path(receipt["commands"][0]["path"]).read_bytes())
        output = json.loads(Path(command["stdout"]["path"]).read_bytes())
        output["content"] = '"foreign-daemon"\n'
        output["size_bytes"] = len(output["content"].encode())
        output["content_sha256"] = hashlib.sha256(output["content"].encode()).hexdigest()
        command["stdout"] = self.rewrite(command["stdout"], output)
        receipt["commands"][0] = self.rewrite(receipt["commands"][0], command)
        capture.container_receipt_descriptor = self.rewrite(capture.container_receipt_descriptor, receipt)
        with self.assertRaisesRegex(ValueError, "daemon identity mismatch"):
            self.validate(capture)

    def test_resealed_foreign_reserved_label_is_rejected_against_original_launch(self):
        with self.capture() as capture:
            self.measure()
        receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        reservation = json.loads(Path(receipt["reservation"]["path"]).read_bytes())
        reservation["label"] = "b" * 64
        receipt["reservation"] = self.rewrite(receipt["reservation"], reservation)
        capture.container_receipt_descriptor = self.rewrite(capture.container_receipt_descriptor, receipt)
        with self.assertRaisesRegex(ValueError, "label or time mismatch"):
            self.validate(capture)

    def test_uncounted_container_fact_is_rejected(self):
        with self.capture() as capture:
            self.measure()
        (self.root / "process/container-custody/foreign.json").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "uncounted facts"):
            self.validate(capture)

    def test_nonzero_and_timeout_stop_only_original_surviving_cid_and_never_accept(self):
        for mode, timeout in (("failure", 5), ("timeout", .2)):
            with self.subTest(mode=mode):
                if (self.root / "process").exists():
                    self.temp.cleanup()
                    self.setUp()
                with self.assertRaises((ValueError, runtime.NativePublicationTransientErrorV3)):
                    with self.capture() as capture:
                        self.measure(mode, timeout)
                self.assertEqual(self.state.read_text().split()[-1], "0")
                receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
                self.assertEqual(receipt["status"], "failed_original_container_custody")
                stops = [json.loads(Path(row["path"]).read_bytes()) for row in receipt["commands"]]
                stops = [row for row in stops if row["role"] == "stop_original_cid"]
                self.assertEqual(len(stops), 1)
                self.assertEqual(stops[0]["argv"][1:], ["container", "stop", "--time", "5", "a" * 64])
                with self.assertRaises(ValueError):
                    self.validate(capture)

    def test_start_persistence_failure_recovers_owned_name_and_cleans_original_cid(self):
        original_write = process_custody._write
        def fail_launch(io, path, value, maximum):
            if value["artifact_kind"] == "vast_original_engine_process_launch_v1":
                deadline = time.monotonic() + 5
                while not self.state.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                (self.root / "process/container-custody/measurement.cid").unlink()
                raise OSError("fixture launch persistence failed")
            return original_write(io, path, value, maximum)
        with mock.patch.object(process_custody, "_write", side_effect=fail_launch):
            with self.assertRaisesRegex(OSError, "fixture launch persistence failed"):
                with self.capture() as capture:
                    self.measure("timeout", 5)
        self.assertEqual(self.state.read_text().split()[-1], "0")
        receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        self.assertEqual(receipt["cid_source"], "reserved_name_observation")
        self.assertEqual(receipt["container_id"], "a" * 64)
        self.assertEqual(receipt["status"], "failed_original_container_custody")

    def test_malformed_original_cid_remains_failure_and_cleans_only_validated_owned_name(self):
        actual_completed = custody._ContainerCustody.completed
        def corrupt_cid(owned, returncode):
            owned.cidfile.write_bytes(b"invalid original CID")
            actual_completed(owned, returncode)
        with mock.patch.object(custody._ContainerCustody, "completed", new=corrupt_cid):
            with self.assertRaises(ValueError):
                with self.capture() as capture:
                    self.measure("failure", 5)
        self.assertEqual(self.state.read_text().split()[-1], "0")
        receipt = json.loads(Path(capture.container_receipt_descriptor["path"]).read_bytes())
        self.assertEqual(receipt["cid_source"], "reserved_name_observation")
        self.assertEqual(receipt["status"], "failed_original_container_custody")
        self.assertIsNone(receipt["cidfile"])


if __name__ == "__main__":
    unittest.main()
