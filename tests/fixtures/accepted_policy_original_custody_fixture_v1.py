"""Genuine process custody around an artificial engine CLI, never Docker authority.

The native payload must come from the fixture's real coordinator. This producer
does not interpret, repair, project, or reseal it. Only the external engine CLI
command boundary is doubled; custody writers, transfer, and cold readers are real.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from types import SimpleNamespace

import checkpoint_gstreamer_publication_runtime_v3 as runtime
import publication_operational_container_custody_v1 as container_custody
import publication_operational_process_custody_v1 as process_custody
from publication_operational_request_domain_v1 import canonical_json_v1
from publication_operational_runtime_context_v1 import _materialize_operational_file_v1


ENGINE_SOURCE = r'''
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <stdlib.h>
struct reply { const char *key; const char *value; };
/* FIXTURE_REPLY_TABLES */
static const char *cid = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static void pause_fixture(void) { struct timespec delay = {0, 120000000}; nanosleep(&delay, NULL); }
static int reply_for(const struct reply *rows, const char *key) {
    for (int i = 0; rows[i].key; i++) {
        if (strcmp(rows[i].key, key) == 0) { puts(rows[i].value); return 0; }
    }
    fprintf(stderr, "Unknown artificial fixture image: %s\n", key); return 51;
}
int main(int argc, char **argv) {
    int first = 1;
    if (argc > 1 && strncmp(argv[1], "--host=", 7) == 0) first++;
    if (argc <= first) return 12;
    if (strcmp(argv[first], "--version") == 0) { puts("Artificial fixture engine CLI, not Docker"); return 0; }
    if (strcmp(argv[first], "info") == 0) { pause_fixture(); puts(DAEMON_ID); return 0; }
    if (strcmp(argv[first], "image") == 0 && argc > first + 2 && strcmp(argv[first+1], "inspect") == 0) {
        pause_fixture(); return reply_for(image_replies, argv[argc-1]);
    }
    if (strcmp(argv[first], "container") == 0 && argc > first + 2) {
        char saved_cid[80], name[100], label[80], created[100], image[100]; int running;
        FILE *state = fopen(STATE_FILE, "r");
        if (!state) { pause_fixture(); fprintf(stderr,"Error response from daemon: No such container: %s\n",argv[argc-1]); return 1; }
        if (fscanf(state,"%79s %99s %79s %99s %99s %d",saved_cid,name,label,created,image,&running) != 6) return 8;
        fclose(state);
        if (strcmp(argv[first+1], "stop") == 0) {
            if (strcmp(argv[argc-1], saved_cid) != 0) return 9;
            state=fopen(STATE_FILE,"w"); if (!state) return 30;
            fprintf(state,"%s %s %s %s %s 0\n",saved_cid,name,label,created,image); fclose(state);
            pause_fixture(); puts(saved_cid); return 0;
        }
        if (strcmp(argv[argc-1], saved_cid) != 0 && strcmp(argv[argc-1], name) != 0) return 10;
        pause_fixture();
        printf("{\"Id\":\"%s\",\"Name\":\"/%s\",\"Image\":\"%s\",\"Created\":\"%s\",\"Running\":%s,\"OOMKilled\":false,\"ExitCode\":0,\"Pid\":%d,\"StartedAt\":\"%s\",\"FinishedAt\":\"%s\",\"Operation\":\"%s\"}\n",saved_cid,name,image,created,running?"true":"false",running?getpid():0,created,created,label); return 0;
    }
    if (strcmp(argv[first], "run") == 0) {
        for (int i=first+1;i<argc;i++) {
            if (strstr(argv[i], "/deploy/openvino/checkpoint/probe_openvino_devices.py")) {
                for (int j=first+1;j<argc;j++) {
                    for (int k=0; probe_replies[k].key;k++) {
                        if (strcmp(argv[j], probe_replies[k].key) == 0) { pause_fixture(); puts(probe_replies[k].value); return 0; }
                    }
                }
                return 52;
            }
        }
        const char *cidfile=NULL,*name=NULL,*label=NULL,*payload=NULL,*output=NULL,*image=NULL;
        for (int i=first+1;i+1<argc;i++) {
            if(strcmp(argv[i],"--cidfile")==0) cidfile=argv[i+1];
            if(strcmp(argv[i],"--name")==0) name=argv[i+1];
            if(strcmp(argv[i],"--label")==0) { const char *eq=strchr(argv[i+1],'='); if(eq) label=eq+1; }
            if(strcmp(argv[i],"--fixture-native-payload")==0) payload=argv[i+1];
            if(strcmp(argv[i],"--fixture-native-output")==0) output=argv[i+1];
            if(strcmp(argv[i],"--fixture-image")==0) image=argv[i+1];
        }
        if(!cidfile||!name||!label||!payload||!output||!image) return 11;
        if (access(STATE_FILE, F_OK) == 0) return 53;
        struct timespec now; clock_gettime(CLOCK_REALTIME,&now); struct tm utc; gmtime_r(&now.tv_sec,&utc);
        char seconds[64],created[100]; strftime(seconds,sizeof(seconds),"%Y-%m-%dT%H:%M:%S",&utc);
        snprintf(created,sizeof(created),"%s.%09ldZ",seconds,now.tv_nsec);
        FILE *f=fopen(cidfile,"w"); if(!f) return 31; fprintf(f,"%s\n",cid); fclose(f);
        f=fopen(STATE_FILE,"w"); if(!f) return 32;
        fprintf(f,"%s %s %s %s %s 1\n",cid,name,label,created,image); fclose(f);
        FILE *reader=fopen(payload,"rb"), *writer=fopen(output,"wb");
        if(!reader||!writer) return 33;
        unsigned char buffer[65536]; size_t size;
        while((size=fread(buffer,1,sizeof(buffer),reader)) > 0) {
            if(fwrite(buffer,1,size,writer) != size) return 34;
        }
        if(ferror(reader)) return 35;
        fclose(reader); if(fclose(writer) != 0) return 36;
        pause_fixture(); puts("original artificial fixture measurement");
        if(unlink(STATE_FILE) != 0) return 37;
        return 0;
    }
    return 12;
}
'''


def _descriptor(path):
    raw = path.read_bytes()
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@dataclass(frozen=True)
class HeldFixtureEngineV1:
    engine: SimpleNamespace
    engine_descriptor: dict
    engine_socket: dict
    state_path: Path


def _reply_table(name, mapping, *, inspection):
    rows = []
    for key, value in sorted((mapping or {}).items()):
        if type(key) is not str or not key.isascii() or type(value) is not dict:
            raise ValueError("fixture image/probe reply requires ASCII key and object")
        raw = canonical_json_v1([value] if inspection else value).decode("ascii")
        rows.append("    {" + json.dumps(key) + ", " + json.dumps(raw) + "},")
    return "static const struct reply " + name + "[] = {\n" + "\n".join(rows) + "\n    {NULL, NULL}\n};"


@contextmanager
def prepare_original_fixture_engine_v1(*, project_root, output_dir,
        image_inspections=None, device_probes=None, socket_path=None):
    """Hold one immutable local ELF/socket for every artificial fixture operation."""
    root = Path(project_root).resolve(strict=True)
    output = Path(output_dir)
    if output.resolve(strict=False) != output or not output.is_relative_to(root):
        raise ValueError("fixture engine output must be physical and inside project")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    immutable, mutable = output / "immutable", output / "mutable"
    immutable.mkdir(mode=0o700)
    mutable.mkdir(mode=0o700)
    state_path = mutable / "state"
    source = immutable / "engine.c"
    replies = _reply_table("image_replies", image_inspections, inspection=True) + "\n" + _reply_table("probe_replies", device_probes, inspection=False)
    source.write_text(ENGINE_SOURCE.replace("/* FIXTURE_REPLY_TABLES */", replies), encoding="ascii")
    executable = immutable / "engine"
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("genuine fixture ELF requires C compiler")
    subprocess.run([compiler, "-O0", "-std=c11", '-DSTATE_FILE=' + json.dumps(str(state_path)),
        '-DDAEMON_ID=' + json.dumps('"fixture-daemon-1"'), str(source), "-o", str(executable)],
        check=True, capture_output=True)
    fd = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        path = Path(socket_path) if socket_path is not None else output / "engine.sock"
        if path.resolve(strict=False) != path or path.exists() or path.is_symlink():
            raise ValueError("fixture engine socket must be fresh and canonical")
        sock.bind(str(path))
        info = path.lstat()
        descriptor = _descriptor(executable)
        engine = SimpleNamespace(path=executable, fd=fd, size=descriptor["size_bytes"],
            sha256=descriptor["sha256"], proc_path=f"/proc/self/fd/{fd}")
        yield HeldFixtureEngineV1(engine=engine, engine_descriptor=descriptor,
            engine_socket={"path": str(path), "device": info.st_dev, "inode": info.st_ino,
                "owner_uid": info.st_uid, "owner_gid": info.st_gid}, state_path=state_path)
    finally:
        sock.close()
        os.close(fd)


def capture_original_fixture_operation_v1(*, project_root, operation_id,
        original_operation_descriptor, native_context_descriptor, expected_container_image,
        native_domain_payload, engine, engine_socket, scratch_dir, native_domain_output,
        process_receipt_output, container_receipt_output, timeout_s=5):
    """Capture one actual child and stock native transfer, then run both cold readers."""
    root = Path(project_root).resolve(strict=True)
    scratch, native, process, container = map(Path,
        (scratch_dir, native_domain_output, process_receipt_output, container_receipt_output))
    if type(native_domain_payload) is not bytes or not native_domain_payload or len(native_domain_payload) > 64 * 1024 * 1024:
        raise ValueError("complete bounded coordinator-produced native bytes required")
    for path in (scratch, native, process, container):
        if path.resolve(strict=False) != path or not path.is_relative_to(root) or path.exists():
            raise ValueError("fixture reserved outputs must be fresh physical project paths")
    if native.name != "native_operational_requests.v1.jsonl" or process.name != "original_engine_process_capture.v1.json" or container != process.parent / "container-custody/original_container_custody.v1.json":
        raise ValueError("fixture output paths differ from stock custody layout")
    context_path = Path(native_context_descriptor["path"])
    context_relative = context_path.relative_to(root).as_posix()
    scratch.mkdir(mode=0o700, parents=True, exist_ok=False)
    operational = scratch / "operational"
    operational.mkdir(mode=0o700)
    payload = scratch / "coordinator-native-payload.jsonl"
    payload.write_bytes(native_domain_payload)
    arguments = ("run", "--rm", "--mount", f"type=bind,src={root},dst=/workspace/project,readonly",
        "--mount", f"type=bind,src={operational},dst=/opt/vast/operational",
        expected_container_image["image_id"], "--operational-request-context", f"/workspace/project/{context_relative}",
        "--operational-output-dir", "/opt/vast/operational", "--fixture-native-payload", str(payload),
        "--fixture-native-output", str(operational / native.name), "--fixture-image", expected_container_image["image_id"])
    with process_custody.capture_original_engine_processes_v1(project_root=root,
            output_dir=process.parent, operation_id=operation_id,
            original_operation_descriptor=original_operation_descriptor,
            native_context_descriptor=native_context_descriptor, container_image=expected_container_image) as capture:
        with process_custody.original_engine_phase_v1("measurement"), container_custody.measurement_container_custody_v1(
                engine, engine_socket, arguments) as owned:
            result = runtime._invoke_engine(engine, engine_socket, owned.argv, timeout_s)
            owned.completed(result.returncode)
            if result.returncode != 0:
                raise RuntimeError("original artificial fixture CLI failed")
        _materialize_operational_file_v1(root, operational, native.parent)
    expected = dict(project_root=root, operation_id=operation_id,
        original_operation_descriptor=original_operation_descriptor,
        native_context_descriptor=native_context_descriptor, expected_container_image=expected_container_image)
    process_validation = process_custody.original_process_validator_v1(receipt_path=process,
        expected_descriptor=capture.receipt_descriptor, **expected)
    container_validation = container_custody.original_container_validator_v1(receipt_path=container,
        expected_descriptor=capture.container_receipt_descriptor, process_receipt_path=process,
        expected_process_descriptor=capture.receipt_descriptor, **expected)
    native_descriptor = _descriptor(native)
    return {"native_domain": native_descriptor, "native_domain_descriptor": native_descriptor,
        "process_receipt": capture.receipt_descriptor, "container_receipt": capture.container_receipt_descriptor,
        "process_validation": process_validation, "container_validation": container_validation,
        "real_docker_qualification": False}
