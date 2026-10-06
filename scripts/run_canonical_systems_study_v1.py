#!/usr/bin/env python3
"""Prepare and run the reviewed finite 24-arm study on existing native paths."""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import struct
import sys
import stat
import subprocess
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical_systems_study_plan_v1 import build_study_plan, validate_study_plan, stream_schedule, actual_clock_domain_label
from publication_physical_io_v1 import PhysicalRootCustodyV1
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1

PARENTS = {
    "front_gate": (33088368, "4a5f619b8ab0b19945cea37603d6203a77cb28aae61d09d299eaea60bb9fd4ca", 1920, 1080, "yuv420p"),
    "underbody": (2465052990, "31bee18de7cd08d6012d093a5774e17e1a702998f85f44b87f1d4971fa9c9a2d", 1700, 236, "yuvj422p"),
}
FFMPEG_SHA = "ed16af623947494a72e284b6eb8ff225f2da22b38b5d5069c2fd4b4ba3384e41"
FFPROBE_SHA = "272f6ebc634a63d9c8b4ca68e964119d980f25154e5aa2c35e5487da48e9a58f"
MAX_MEDIA = 512 * 1024**2
MAX_RAW_ARM = 1024**3  # Amendment7: measured worst arm ~445 MiB.
MAX_RAW_CAMPAIGN = 24 * 1024**3  # Amendment7: measured ~7 GiB for 32 arms.
MAX_STUDY_ROLE_BYTES = 192 * 1024**2  # Amendment7: decoded role/study journal bound.


def require(ok, message):
    if not ok:
        raise ValueError(message)


def preparation_clock(args):
    """Retain the first bootstrap operation's observed original kernel clock."""
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    try: namespace = actual_clock_domain_label()
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ValueError("original preparation clock domain is unproven: "+str(error)) from error
    supplied = tuple(getattr(args, name, None) for name in (
        "preparation_started_monotonic_ns", "preparation_boot_id", "preparation_time_namespace"))
    now = time.monotonic_ns()
    if all(value is None for value in supplied):
        started = now
    else:
        require(all(value is not None for value in supplied), "original preparation clock requires its full domain")
        started, expected_boot, expected_namespace = supplied
        require(type(started) is int and 0 < started <= now and
                expected_boot == boot and expected_namespace == namespace,
                "original preparation clock stamp or actual domain is invalid")
    deadline = started + 14_400_000_000_000
    require(now < deadline, "original preparation clock has expired")
    return {"clock": "CLOCK_MONOTONIC", "boot_id": boot, "time_namespace": namespace,
        "started_monotonic_ns": started, "deadline_monotonic_ns": deadline}


def epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def descriptor(path, *, maximum=MAX_MEDIA, deadline=None):
    path = Path(path)
    require(path.is_absolute() and str(path) == os.path.normpath(str(path)), "noncanonical study input path")
    with PhysicalRootCustodyV1.open(path.parent, label="finite study input parent") as custody:
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum,
                "study input is not a bounded single-link regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            custody.verify()
            digest, offset = hashlib.sha256(), 0
            while offset < before.st_size:
                require(deadline is None or time.monotonic() < deadline, "original phase input read deadline exceeded")
                chunk = os.pread(fd, min(1024**2, before.st_size-offset), offset)
                require(bool(chunk), "study original input is truncated")
                digest.update(chunk); offset += len(chunk)
            require(deadline is None or time.monotonic() < deadline, "original phase input read closed late")
            custody.verify()
            require(epoch(before) == epoch(os.fstat(fd)) == epoch(path.lstat()), "study original input drifted")
            return {"path": str(path), "size_bytes": offset, "sha256": digest.hexdigest()}
        finally:
            os.close(fd)


def write_study_results(out, completed):
    """The final original campaign result document."""
    return write_json(Path(out)/"study-results.original.json", completed, maximum=64*1024**2)  # Amendment7 addendum.


def write_json(path, value, *, maximum=16*1024**2):
    raw = canonical_json_v1(value)+b"\n"
    require(len(raw) <= maximum, "study control exceeds metadata bound")
    with Path(path).open("xb") as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def reserve_space(output, deadline):
    require(time.monotonic()<deadline,"original phase reservation deadline")
    path=Path(output)/"phase-space.reserve"
    with path.open("xb") as stream:
        try:
            os.posix_fallocate(stream.fileno(),0,20*1024**3)
            stream.flush();os.fsync(stream.fileno())
            require(time.monotonic()<deadline,"original space allocation is late")
        except BaseException:
            info=os.fstat(stream.fileno())
            if epoch(path.lstat())==epoch(info):path.unlink()
            raise
    return path,epoch(path.lstat())


def release_space(path, identity):
    require(epoch(Path(path).lstat())==identity,"owned space reservation identity drifted")
    Path(path).unlink()


class Commands:
    """Only the driver's actual owned children and the original absolute clock."""
    def __init__(self, output, deadline, *, deadline_monotonic_ns=None):
        self.output, self.deadline, self.records = Path(output), deadline, []
        self.deadline_monotonic_ns = int(deadline*1e9) if deadline_monotonic_ns is None else deadline_monotonic_ns
        require(type(self.deadline_monotonic_ns) is int and self.deadline_monotonic_ns > 0 and
            (deadline_monotonic_ns is None or deadline == self.deadline_monotonic_ns/1e9), "original command clock endpoint mismatch")
        self.children = []
        self.containers = []
        self.closing_deadline = None

    def describe(self, path, *, maximum=MAX_MEDIA):
        return descriptor(path,maximum=maximum,deadline=self.deadline)

    def remaining(self):
        remaining = (self.deadline if self.closing_deadline is None else self.closing_deadline)-time.monotonic()
        require(remaining > (15.0 if self.closing_deadline is None else 0.0), "original study phase lacks its finite closing reserve")
        return remaining

    def launch(self, command, *, env=None, stdin=None, stdout=None):
        self.remaining()
        index = len(self.records)
        out, err = self.output / f"command-{index:03d}.stdout.raw", self.output / f"command-{index:03d}.stderr.raw"
        output = error = None
        primary = None
        try:
            output = out.open("xb") if stdout is None else None
            error = err.open("xb")
            child = subprocess.Popen(list(map(str, command)), stdin=stdin or subprocess.DEVNULL,
                stdout=output if stdout is None else stdout, stderr=error, env=env, start_new_session=True)
            self.children.append(child)
            record = {"argv": list(map(str, command)), "pid": child.pid, "pgid": child.pid,
                "started_monotonic_ns": time.monotonic_ns(), "stdout_path": str(out) if output is not None else None,
                "stderr_path": str(err)}
            self.records.append(record)
        except BaseException as error_value:
            primary = error_value; raise
        finally:
            failures=[]
            for stream in (output,error):
                if stream is not None:
                    try:stream.close()
                    except BaseException as failure:failures.append(failure)
            if failures:
                if primary is not None:
                    for failure in failures:primary.add_note(str(failure)[:1024])
                else:raise failures[0]
        return child, record

    def wait(self, child, record, *, maximum=1024**2, maximum_files=(), accept_nonzero=False):
        paths = [(record["stderr_path"], maximum)] + [(p, maximum) for p in [record["stdout_path"]] if p]
        paths += list(maximum_files)
        while child.poll() is None:
            self.remaining()
            require(time.monotonic()<record.get("deadline",self.deadline), "owned command original bound expired")
            require(all(not os.path.exists(p) or os.stat(p).st_size <= cap for p, cap in paths),
                    "owned study command exceeded its physical output cap")
            time.sleep(min(0.02, self.remaining()))
        child.wait(timeout=self.remaining())
        require(all(not os.path.exists(p) or os.stat(p).st_size <= cap for p, cap in paths),
                "closed owned study command exceeded its physical output cap")
        record.update(returncode=child.returncode, closed_monotonic_ns=time.monotonic_ns())
        if record.get("container") is not None:
            self.close_container(record["container"], positive=child.returncode == 0)
        require(accept_nonzero or child.returncode == 0, "owned study command failed: " + str(record["argv"]))
        self.remaining()
        return Path(record["stdout_path"]).read_bytes() if record["stdout_path"] is not None else b""

    def run(self, command, *, env=None, maximum=1024**2, maximum_files=()):
        child, record = self.launch(command, env=env)
        return self.wait(child, record, maximum=maximum, maximum_files=maximum_files)

    def close_container(self, row, *, positive=False):
        if row["closed"]: return
        path = Path(row["cid_path"])
        if not path.exists():
            require(not positive, "successful selected container lacks original CID")
            return
        cid = path.read_text().strip()
        require(re.fullmatch(r"[0-9a-f]{64}", cid), "original owned CID is malformed")
        observed = json.loads(self.run([row["engine"], "inspect", cid]))
        require(type(observed) is list and len(observed) == 1, "owned container state is ambiguous")
        state = observed[0]
        require(state["Id"] == cid and state["Name"] == "/"+row["name"] and state["Image"] == row["image"],
                "selected container original ownership drifted")
        if state["State"]["Running"]:
            require(not positive, "positive native frontend left owned container running")
            self.run([row["engine"], "stop", "--time", "1", cid])
            state = json.loads(self.run([row["engine"], "inspect", cid]))[0]
        require(not state["State"]["Running"] and (not positive or state["State"]["ExitCode"] == 0),
                "selected container did not terminate positively")
        self.run([row["engine"], "rm", cid])
        require(self.run([row["engine"], "ps", "--all", "--filter", "id="+cid, "--format", "{{.ID}}"]).strip() == b"" and
            self.run([row["engine"], "ps", "--all", "--filter", "name=^/"+row["name"]+"$", "--format", "{{.ID}}"]).strip() == b"",
            "owned container CID/name remains after nonforce removal")
        row.update(cid=cid, original_terminal_state=state["State"], closed=True, removal="nonforce")

    def retire(self, primary=None):
        # A single shared original remaining clock, never one timeout per child.
        errors = []
        deadline = min(self.deadline, time.monotonic()+15.0)
        self.closing_deadline = deadline
        for child in self.children:
            if child.poll() is None:
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                except BaseException as error: errors.append(error)
        grace = min(deadline, time.monotonic()+2.0)
        for child in self.children:
            if child.poll() is None:
                try: child.wait(timeout=max(0, grace-time.monotonic()))
                except subprocess.TimeoutExpired: pass
                except BaseException as error: errors.append(error)
        for child in self.children:
            if child.poll() is None:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                except BaseException as error: errors.append(error)
            try: child.wait(timeout=max(0, deadline-time.monotonic()))
            except BaseException as error: errors.append(error)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    try: stream.close()
                    except BaseException as error: errors.append(error)
        for row in self.containers:
            if not row["closed"]:
                try: self.close_container(row)
                except BaseException as error: errors.append(error)
        # Engine cleanup may itself launch children; retire those under the SAME
        # already running closing endpoint even when an inspect/stop command fails.
        for child in self.children:
            if child.poll() is None:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                except BaseException as error: errors.append(error)
                try: child.wait(timeout=max(0, deadline-time.monotonic()))
                except BaseException as error: errors.append(error)
        if errors:
            message = ";".join(type(error).__name__+":"+str(error) for error in errors)[:4096]
            if primary is None: raise ValueError("owned study command retirement failed: "+message)
            primary.add_note("owned study command retirement failed: "+message)


def pipe_read(fd, size, commands):
    data = bytearray()
    while len(data) < size:
        commands.remaining()
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_READ)
            require(bool(selector.select(commands.remaining())), "original pipe deadline expired")
        try: chunk = os.read(fd, size-len(data))
        except BlockingIOError: continue
        require(bool(chunk), "original study frame/transport is truncated")
        data.extend(chunk)
    return bytes(data)


def pipe_write(fd, payload, commands):
    offset = 0
    while offset < len(payload):
        commands.remaining()
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_WRITE)
            require(bool(selector.select(commands.remaining())), "original pipe write deadline expired")
        try: count = os.write(fd, payload[offset:])
        except BlockingIOError: continue
        require(count > 0, "original study transport made no progress")
        offset += count


def normalization_filter(recording):
    base = "scale=w=iw:h=ih:flags=bilinear+accurate_rnd+bitexact:threads=1:"
    if recording == "front_gate":
        return base+"in_color_matrix=bt709:out_color_matrix=bt709:in_range=tv:out_range=tv:in_h_chr_pos=0:in_v_chr_pos=128:out_h_chr_pos=0:out_v_chr_pos=128,format=pix_fmts=yuv420p"
    require(recording == "underbody", "unknown original recording")
    return base+"in_color_matrix=bt601:out_color_matrix=bt601:in_range=pc:out_range=pc:in_h_chr_pos=128:in_v_chr_pos=0,format=pix_fmts=bgr24,"+base+"in_color_matrix=bt709:out_color_matrix=bt709:in_range=pc:out_range=tv:out_h_chr_pos=0:out_v_chr_pos=128,format=pix_fmts=yuv420p"


def encode_command(width, height, destination):
    return ["/usr/bin/ffmpeg", "-v", "error", "-nostdin", "-f", "rawvideo", "-pixel_format", "yuv420p",
        "-video_size", f"{width}x{height}", "-framerate", "30/1", "-i", "pipe:0", "-an", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-threads:v", "1", "-g", "1",
        "-keyint_min", "1", "-sc_threshold", "0", "-bf", "0", "-x264-params", "open-gop=0:threads=1:lookahead-threads=1:force-cfr=1",
        "-frames:v", "442", "-fps_mode", "cfr", "-enc_time_base:v", "1:30", "-video_track_timescale", "600",
        "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-chroma_sample_location", "left", "-n", str(destination)]


def encode_recording(commands, name, prefix, destination):
    _, _, width, height, _ = PARENTS[name]
    decode = ["/usr/bin/ffmpeg", "-v", "error", "-nostdin", "-filter_threads", "1", "-threads:v", "1",
        "-i", str(prefix), "-map", "0:v:0", "-an", "-vf", normalization_filter(name),
        "-frames:v", "442", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1"]
    encode = encode_command(width, height, destination)
    source, source_record = commands.launch(decode, stdout=subprocess.PIPE)
    sink, sink_record = commands.launch(encode, stdin=subprocess.PIPE)
    os.set_blocking(source.stdout.fileno(), False); os.set_blocking(sink.stdin.fileno(), False)
    rows, y_size, uv_size = [], width*height, width*height//4
    try:
        for ordinal in range(442):
            frame = pipe_read(source.stdout.fileno(), y_size+2*uv_size, commands)
            rows.append({"ordinal": ordinal, "width": width, "height": height, "output_format": "yuv420p",
                "range": "limited", "matrix": "bt709", "chroma_location": "left",
                "y_sha256": hashlib.sha256(frame[:y_size]).hexdigest(),
                "u_sha256": hashlib.sha256(frame[y_size:y_size+uv_size]).hexdigest(),
                "v_sha256": hashlib.sha256(frame[y_size+uv_size:]).hexdigest()})
            pipe_write(sink.stdin.fileno(), frame, commands)
            require(not destination.exists() or destination.stat().st_size <= MAX_MEDIA, "derived output exceeded media cap")
        sink.stdin.close()
        commands.wait(source, source_record)
        require(os.read(source.stdout.fileno(), 1) == b"", "normalizer produced a context-only extra frame")
        source.stdout.close()
        commands.wait(sink, sink_record, maximum_files=((str(destination), MAX_MEDIA),))
    finally:
        for stream in (source.stdout, sink.stdin):
            if stream is not None and not stream.closed: stream.close()
    return rows


def validate_derived_probe(value, name):
    _, _, width, height, _ = PARENTS[name]
    require(type(value) is dict and len(value.get("streams", [])) == 1, "derived stream coverage")
    stream = value["streams"][0]
    require(stream.get("codec_name") == "h264" and stream.get("width") == width and stream.get("height") == height and
        stream.get("pix_fmt") == "yuv420p" and stream.get("has_b_frames") == 0 and
        stream.get("r_frame_rate") == "30/1" and stream.get("avg_frame_rate") == "30/1" and
        stream.get("time_base") == "1/600" and 0 < stream.get("level", 0) <= 51 and
        stream.get("color_range") == "tv" and stream.get("color_space") == "bt709" and
        stream.get("color_transfer") == "bt709" and stream.get("color_primaries") == "bt709" and
        stream.get("chroma_location") == "left", "derived actual stream/color/VUI/level mismatch")
    packets = value.get("packets", [])
    require(len(packets) == 442, "derived packet count is not exactly442")
    for ordinal, packet in enumerate(packets):
        require(packet.get("pts") == packet.get("dts") == 20*ordinal and packet.get("duration") == 20 and
                "K" in packet.get("flags", ""), "derived actual packet clock/all-I shape mismatch")


def selected_source_pins(root, commands):
    from publication_image_build_v1 import _read_allowlist
    lists=("deploy/native_gst_probe/publication/openvino-source-allowlist.txt",
        "deploy/native_gst_probe/publication/openvino-dependency-allowlist.txt",
        "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt",
        "deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt",
        "deploy/gstreamer_custom/publication/runtime-build-context-allowlist.txt")
    names=set(lists)|{"scripts/run_canonical_systems_study_v1.py","scripts/reduce_canonical_systems_study_v1.py",
        "scripts/canonical_systems_study_plan_v1.py","deploy/native_gst_probe/Dockerfile.openvino",
        "deploy/gstreamer_custom/publication/Dockerfile","scripts/build_gstreamer_custom_publication_runtime_v3.sh"}
    for path in lists:names.update(_read_allowlist(root,path))
    pins=[]
    for name in sorted(names):
        require(commands.remaining()>0,"original source guard deadline")
        path=root/name;ref=commands.describe(path,maximum=64*1024**2)
        pins.append({"descriptor":ref,"epochs":list(epoch(path.lstat()))})
    return pins


def verify_source_pins(pins, commands):
    for pin in pins:
        ref=pin["descriptor"];path=Path(ref["path"])
        require(epoch(path.lstat())==tuple(pin["epochs"]) and commands.describe(path,maximum=64*1024**2)==ref,
            "selected prepared source/control bytes or epochs changed")


def selected_build(commands, root, output, token, engine):
    from publication_image_build_v1 import build_finite_study_native_image_v1
    work = Path(tempfile.mkdtemp(prefix="vast-finite-study-native-"))
    def runner(command, env=None):
        return commands.run(command, env=env, maximum=16*1024**2).decode()
    for reference in [f"{base}:{token}{suffix}" for base in ("vast/finite-study-native","vast/finite-study-gstreamer") for suffix in ("","-determinism-a","-determinism-b")]:
        require(not commands.run([engine,"image","ls","--filter","reference="+reference,"--format","{{.ID}}"] ).strip(),"private study image reference already occupied")
    native = build_finite_study_native_image_v1(project_root=root, work_root=work, docker=engine,
        target_reference=f"vast/finite-study-native:{token}", command_runner=runner)
    image = native["images"][0]
    environment = {**os.environ, "VAST_OPENVINO_NATIVE_PROBE_IMAGE": image["target_reference"],
        "VAST_OPENVINO_NATIVE_PROBE_IMAGE_ID": image["image_id"],
        "VAST_GSTREAMER_RUNTIME_IMAGE": f"vast/finite-study-gstreamer:{token}"}
    raw = commands.run(["/bin/bash", str(root/"scripts/build_gstreamer_custom_publication_runtime_v3.sh")],
                       env=environment, maximum=16*1024**2)
    fields = dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line and line.split("=", 1)[0] in {
        "image_ref", "image_id", "base_image_id", "runtime_source_sha256", "native_probe_source_sha256",
        "dependency_set_sha256", "embedded_set_sha256", "build_context_inputs_sha256"})
    require(set(fields) == {"image_ref", "image_id", "base_image_id", "runtime_source_sha256", "native_probe_source_sha256",
        "dependency_set_sha256", "embedded_set_sha256", "build_context_inputs_sha256"} and
        fields["base_image_id"] == image["image_id"] and fields["image_ref"] == environment["VAST_GSTREAMER_RUNTIME_IMAGE"],
        "actual selected GStreamer two-build receipt is incomplete")
    return {"native": native, "gstreamer": fields}


def _native(commands, engine, image, root, output, arguments, *, stdin=None, stdout=None,
        entrypoint="/usr/local/bin/vast_native_gst_probe", mounts=(), environment=None):
    token = hashlib.sha256((str(output)+str(len(commands.records))).encode()).hexdigest()[:24]
    name, cid_path = "vast-finite-"+token, commands.output/("native-"+token+".cid")
    absent = commands.run([engine, "ps", "--all", "--filter", "name=^/"+name+"$", "--format", "{{.ID}}"])
    require(absent.strip() == b"" and not os.path.lexists(cid_path), "owned selected native container name occupied")
    container = {"name": name, "cid_path": str(cid_path), "engine": engine, "image": image, "closed": False}
    commands.containers.append(container)
    command = [engine, "run", "--name", name, "--cidfile", str(cid_path),
        "--label", "vast.finite-study="+token, "--network", "none", "--gpus", "all", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=67108864,mode=1777",
        "--mount", f"type=bind,src={root},dst={root},readonly",
        "--mount", f"type=bind,src={output},dst={output}", "--entrypoint", entrypoint]
    for mount in mounts: command += ["--mount",mount]
    environment = {"VAST_CHECKPOINT_PREPARATION_CLOCK_BOOT_ID":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "VAST_CHECKPOINT_PREPARATION_CLOCK_TIME_NAMESPACE":actual_clock_domain_label(),**(environment or {})}
    for key,value in environment.items(): command += ["--env",key+"="+value]
    command.append(image)
    if stdin is not None: command.insert(2, "-i")
    child, record = commands.launch([*command, *map(str, arguments)], stdin=stdin, stdout=stdout)
    record["container"] = container
    return child, record


def _probe(commands, path, *, original=False, frames=False):
    command = ["/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0"]
    if original: command += ["-read_intervals", "%+#448"]
    command += ["-show_streams", "-show_frames" if frames else "-show_packets", "-show_data_hash", "sha256", "-of", "json", str(path)]
    return json.loads(commands.run(command, maximum=8*1024**2))


def prepare(args):
    clock = preparation_clock(args)
    started = clock["started_monotonic_ns"]/1e9
    output, root = Path(args.output_dir), Path(args.project_root).resolve(strict=True)
    require(output.is_absolute() and output.is_relative_to(root) and not os.path.lexists(output), "preparation requires new owned project namespace")
    output.mkdir(mode=0o700, parents=False)
    commands = Commands(output, clock["deadline_monotonic_ns"]/1e9,
        deadline_monotonic_ns=clock["deadline_monotonic_ns"])
    primary = None
    reservation = None
    reservation_identity = None
    try:
        source_pins=selected_source_pins(root,commands)
        originals, saved_epochs = {}, {}
        for name in PARENTS:
            path = Path(getattr(args, name))
            expected_size, expected_sha, _, _, _ = PARENTS[name]
            originals[name] = commands.describe(path, maximum=4*1024**3)
            require((originals[name]["size_bytes"], originals[name]["sha256"]) == (expected_size, expected_sha), "original AVI identity mismatch")
            saved_epochs[str(path)] = epoch(path.lstat())
        tools = {name: commands.describe(Path("/usr/bin")/name) for name in ("ffmpeg", "ffprobe")}
        require(tools["ffmpeg"]["sha256"] == FFMPEG_SHA and tools["ffprobe"]["sha256"] == FFPROBE_SHA,
                "current frozen software executables changed")
        require(shutil.disk_usage(output).free >= 20*1024**3 + 4*MAX_MEDIA + 2*MAX_MEDIA + MAX_RAW_CAMPAIGN,
                "finite preparation space/reservation is insufficient")
        reservation, reservation_identity = reserve_space(output, commands.deadline)
        for tool in tools:
            commands.run([tools[tool]["path"], "-version"])
        dependencies = {}
        for tool in tools.values():
            raw = commands.run(["/usr/bin/ldd", tool["path"]]).decode()
            require("not found" not in raw, "software loaded dependency unavailable")
            for name in re.findall(r"(?:=>\s*)?(/[A-Za-z0-9_./+:-]+)\s+\(", raw):
                real = str(Path(name).resolve(strict=True))
                dependencies[real] = commands.describe(Path(real), maximum=64*1024**2)
        software_epochs = {r["path"]:epoch(Path(r["path"]).lstat()) for r in [*tools.values(),*dependencies.values()]}
        images = selected_build(commands, root, output, hashlib.sha256(str(output).encode()).hexdigest()[:24], args.engine)
        recordings = {}
        for name, original in originals.items():
            prefix = output / (name+".context.avi")
            commands.run(["/usr/bin/ffmpeg", "-v", "error", "-nostdin", "-i", original["path"],
                "-map", "0:v:0", "-c:v", "copy", "-an", "-frames:v", "448", "-n", str(prefix)],
                maximum_files=((str(prefix), MAX_MEDIA),))
            parent_packets, prefix_packets = _probe(commands, original["path"], original=True), _probe(commands, prefix)
            packets = parent_packets["packets"]
            require(442 <= len(packets) <= 448 and len(prefix_packets["packets"]) == len(packets) and
                all(a["data_hash"] == b["data_hash"] for a, b in zip(packets, prefix_packets["packets"])),
                "bounded original coded context is not byte-identical to its packet prefix")
            frames = _probe(commands, original["path"], original=True, frames=True)["frames"]
            _, _, width, height, fmt = PARENTS[name]
            require(len(frames) >= 442 and all(frame.get("pix_fmt") == fmt and frame.get("width") == width and
                frame.get("height") == height and not frame.get("interlaced_frame", 0) for frame in frames[:442]),
                "actual original display domain/format/geometry is unsupported")
            if name == "underbody":
                require(all(frame.get("color_range") == "pc" and frame.get("color_space") == "bt470bg" and
                    frame.get("chroma_location") == "center" for frame in frames[:442]), "original underbody color tuple drifted")
            first, second = output/(name+".derived.mp4"), output/(name+".determinism.mp4")
            normalized = encode_recording(commands, name, prefix, first)
            repeated = encode_recording(commands, name, prefix, second)
            require(normalized == repeated and commands.describe(first) == {**commands.describe(second), "path": str(first)},
                    "two fixed normalized encodes differ")
            second_descriptor = commands.describe(second)
            second.unlink()  # Owned xb encoder output, after exact deterministic identity join.
            probe = _probe(commands, first)
            validate_derived_probe(probe, name)
            vui = commands.run(["/usr/bin/ffmpeg", "-v", "verbose", "-nostdin", "-i", str(first),
                "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "trace_headers", "-frames:v", "1", "-f", "null", "-"])
            trace = Path(commands.records[-1]["stderr_path"]).read_text()
            validate_vui_trace(trace)
            normal = write_json(output/(name+".normalization.json"), {"parent": original, "context": commands.describe(prefix),
                "recipe": normalization_filter(name), "original_packets": packets, "original_frames": frames[:442], "frames": normalized,
                "derived_probe": probe, "deterministic_second": second_descriptor, "vui_trace": commands.describe(Path(commands.records[-1]["stderr_path"])), "software": tools, "dependencies": list(dependencies.values())})
            inv_path = output/(name+".inventory.original.jsonl")
            child, record = _native(commands, args.engine, images["gstreamer"]["image_id"], root, output,
                ["--checkpoint-study-au-inventory", first, width, height, commands.deadline_monotonic_ns],
                entrypoint="/usr/local/bin/vast_checkpoint_source")
            inventory_raw = commands.wait(child, record, maximum=8*1024**2)
            with inv_path.open("xb") as stream: stream.write(inventory_raw)
            units = inventory_rows(inventory_raw, commands.describe(first)["sha256"])
            reference = reference_gate(commands, args.engine, images["gstreamer"]["image_id"], root, output, name, first, units)
            recordings[name] = {"descriptor": commands.describe(first), "access_units": units, "width": width, "height": height,
                "parent_descriptor": original, "context_descriptor": commands.describe(prefix), "normalization_descriptor": normal,
                "inventory_descriptor": commands.describe(inv_path), "reference_descriptor": reference}
        intake = {"dataset_id": "finite-kpp-original-442-v1", "recordings": recordings}
        with model_material(args) as material:
            selected = material_document(material, images, tools, dependencies)
            plan = build_study_plan(intake, selected)
            stop_gate = offered_prefix_stop_gate(commands, args, root, output, plan, images)
            control = prepare_contexts(root, output, plan, material)
            material["verify_barrier"]()
        require(all(epoch(Path(path).lstat()) == before for path, before in saved_epochs.items()), "original AVI epochs changed during preparation")
        require(all(epoch(Path(r["path"]).lstat())==software_epochs[r["path"]] and commands.describe(Path(r["path"]),maximum=64*1024**2)==r for r in [*tools.values(),*dependencies.values()]),"reviewed software/dependencies changed during preparation")
        verify_source_pins(source_pins,commands)
        commands.remaining()
        receipt = {"schema_version": 1, "kind": "finite-component-study-prepared-v1", "plan": plan,
            "control": control, "source_pins":source_pins, "images": images, "tools": tools, "dependencies": list(dependencies.values()),
            "offered_prefix_stop_gate": stop_gate, "original_epochs": saved_epochs, "commands": commands.records,
            "started_monotonic_ns": clock["started_monotonic_ns"], "preparation_clock": clock,
            "preparation_elapsed_s": time.monotonic()-started, "accepted": False, "publication_ready": False}
        commands.retire()
        release_space(reservation, reservation_identity)
        receipt["owned_command_and_container_closure"] = True
        result = write_json(output/"study-plan.original.json", receipt)
        require(time.monotonic() < commands.deadline, "prepared receipt closed late")
        return result
    except BaseException as error:
        primary = error
        write_json(output/"failed.original.json", {"first_error": type(error).__name__+":"+str(error), "commands": commands.records})
        raise
    finally:
        if commands.closing_deadline is None: commands.retire(primary)
        if reservation is not None and reservation.exists():
            release_space(reservation, reservation_identity)


def jsonl_rows(raw, *, maximum=MAX_STUDY_ROLE_BYTES):
    require(len(raw) <= maximum and raw.endswith(b"\n"), "original JSONL cap/terminal newline")
    rows = []
    for line in raw.splitlines():
        require(0 < len(line) <= 2048, "original study JSONL row cap")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, "duplicate original JSON key")
                result[key] = value
            return result
        value = json.loads(line, object_pairs_hook=unique)
        require(type(value) is dict, "original study row must be an object")
        rows.append(value)
    return rows


def inventory_rows(raw, input_sha):
    rows = jsonl_rows(raw)
    require(len(rows) == 444 and rows[0] == {"schema_version": 1, "type": "header",
        "kind": "checkpoint_study_au_inventory_v1", "input_sha256": input_sha}, "original AU header/count mismatch")
    require(rows[-1] == {"schema_version": 1, "type": "terminal", "success": True, "accepted": False,
        "provisional_until_capture_return": True, "actual_eos": True, "au_count": 442}, "AU original EOS terminal mismatch")
    fields = {"ordinal", "pts_ns", "dts_ns", "duration_ns", "payload_sha256", "payload_size_bytes"}
    units = []
    for ordinal, row in enumerate(rows[1:-1]):
        require(set(row) == fields | {"schema_version", "type", "keyframe"} and row["schema_version"] == 1 and
            row["type"] == "au" and row["keyframe"] is True and row["ordinal"] == ordinal and
            all(type(row[k]) is int and 0 <= row[k] < 2**64 for k in fields-{"payload_sha256"}) and
            row["duration_ns"] > 0 and 0 < row["payload_size_bytes"] <= 16*1024**2 and
            row["pts_ns"] == row["dts_ns"] and re.fullmatch("[0-9a-f]{64}", row["payload_sha256"]),
            "actual selected AU shape/bounds changed")
        units.append({k: row[k] for k in fields})
    return units


def validate_vui_trace(trace):
    fields = {}
    for key in ("vui_parameters_present_flag", "timing_info_present_flag", "num_units_in_tick", "time_scale", "fixed_frame_rate_flag", "level_idc"):
        values = [int(v) for v in re.findall(r"\b"+key+r"\s+[^\r\n]*?=\s*(\d+)\b", trace)]
        require(bool(values) and len(set(values)) == 1, "actual SPS/VUI field absent or changed: "+key)
        fields[key] = values[0]
    require(fields["vui_parameters_present_flag"] == fields["timing_info_present_flag"] == fields["fixed_frame_rate_flag"] == 1 and
        fields["num_units_in_tick"] > 0 and fields["time_scale"] == 60*fields["num_units_in_tick"] and
        0 < fields["level_idc"] <= 51, "actual SPS/VUI is not frozen30fps/auto<=5.1")
    return fields


def reference_rows(path, *, completion, count, input_sha, width, height, deadline):
    ref = descriptor(path, maximum=8*1024**2,deadline=deadline)
    rows = jsonl_rows(Path(path).read_bytes(), maximum=8*1024**2)
    require(len(rows) == count+2 and rows[0].get("kind") == "checkpoint_study_reference_v1" and
        rows[0].get("completion_kind") == completion and rows[0].get("expected_count") == count and
        rows[0].get("input_sha256") == input_sha, "actual reference header/count/source mismatch")
    terminal = rows[-1]
    require(terminal == {"schema_version": 1, "type": "terminal", "success": True, "accepted": False,
        "provisional_until_owner_final_close": True, "actual_eos": True, "decoded_count": count,
        "completion_kind": completion}, "actual reference EOS terminal mismatch")
    prefix = rows[0]["prefix"]
    for ordinal, frame in enumerate(rows[1:-1]):
        require(frame.get("type") == "frame" and frame.get("ordinal") == ordinal and
            frame.get("width") == width and frame.get("height") == height and
            frame.get("active_y_bytes") == width*height and frame.get("active_u_bytes") == frame.get("active_v_bytes") == width*height//4 and
            frame.get("rgb_bytes") == 3*width*height and frame.get("nv12_caps") == prefix["nv12_caps"] and
            frame.get("rgb_caps") == prefix["rgb_caps"] and
            all(type(frame.get(k)) is str and re.fullmatch("[0-9a-f]{64}", frame[k]) for k in
                ("y_sha256", "u_sha256", "v_sha256", "nv12_sha256", "i420_sha256", "rgb_sha256")),
            "actual reference active-plane/caps/domain mismatch")
    require(descriptor(path, maximum=8*1024**2) == ref, "closed original reference drifted")
    return rows, ref


def reference_gate(commands, engine, image, root, output, name, media, units):
    _, _, width, height, _ = PARENTS[name]
    hardware, software = output/(name+".hardware-reference.original.jsonl"), output/(name+".software-reference.original.jsonl")
    child, record = _native(commands, engine, image, root, output,
        ["--checkpoint-study-reference", media, hardware, width, height, commands.deadline_monotonic_ns, 442])
    commands.wait(child, record, maximum_files=((str(hardware), 8*1024**2),))
    native, native_record = _native(commands, engine, image, root, output,
        ["--checkpoint-study-reference-nv12", software, width, height, commands.deadline_monotonic_ns, 442], stdin=subprocess.PIPE)
    decode, decoded = commands.launch(["/usr/bin/ffmpeg", "-v", "error", "-nostdin", "-threads:v", "1", "-filter_threads", "1",
        "-i", str(media), "-map", "0:v:0", "-an", "-frames:v", "442", "-fps_mode", "passthrough",
        "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1"], stdout=subprocess.PIPE)
    os.set_blocking(native.stdin.fileno(), False); os.set_blocking(decode.stdout.fileno(), False)
    plane = width*height
    try:
        for ordinal in range(442):
            frame = pipe_read(decode.stdout.fileno(), plane*3//2, commands)
            uv = bytearray(plane//2)
            uv[0::2], uv[1::2] = frame[plane:plane*5//4], frame[plane*5//4:]
            pipe_write(native.stdin.fileno(), frame[:plane]+uv, commands)
        native.stdin.close()
        commands.wait(decode, decoded)
        require(os.read(decode.stdout.fileno(), 1) == b"", "software reference has extra frame")
        decode.stdout.close()
        commands.wait(native, native_record, maximum_files=((str(software), 8*1024**2),))
    finally:
        for stream in (native.stdin, decode.stdout):
            if stream is not None and not stream.closed: stream.close()
    hw, hw_ref = reference_rows(hardware, completion="derived_full_eos", count=442,
        input_sha=commands.describe(media)["sha256"], width=width, height=height,deadline=commands.deadline)
    sw, sw_ref = reference_rows(software, completion="independent_nv12_full_eos", count=442,
        input_sha="", width=width, height=height,deadline=commands.deadline)
    require(hw[0]["prefix"] == sw[0]["prefix"] and all(all(a[k] == b[k] for k in
        ("ordinal", "pts_ns", "width", "height", "y_sha256", "u_sha256", "v_sha256", "nv12_sha256", "i420_sha256", "rgb_sha256"))
        for a,b in zip(hw[1:-1], sw[1:-1])), "actual derived software/HW YUV or common Gst RGB mismatch")
    require(all(row["pts_ns"] == unit["pts_ns"] for row, unit in zip(hw[1:-1], units)), "HW reference original inventory PTS mismatch")
    return write_json(output/(name+".reference-gate.json"), {"hardware": hw_ref, "software": sw_ref,
        "active_yuv_bit_exact": True, "common_prefix_rgb_bit_exact": True, "full442_actual_eos": True,
        "prefix": hw[0]["prefix"], "accepted": False, "publication_ready": False})


def model_material(args):
    from publication_gstreamer_component_inputs_v1 import held_finite_study_model_material_v1
    return held_finite_study_model_material_v1(project_root=args.project_root,
        capability_manifest_path=args.capability_manifest, calibration_path=args.calibration,
        model_parity_receipt_path=args.model_parity_receipt, worker_freeze_receipt_path=args.worker_freeze_receipt,
        execution_code_closure_path=args.execution_code_closure, container_engine=args.engine,
        container_engine_socket=args.engine_socket)


def material_document(material, images, tools, dependencies):
    return {"original_model_inputs": material["descriptors"], "worker_projection": material["worker_projection"],
        "images": images, "software": tools, "dependencies": list(dependencies.values()),
        "preprocessing_contract_sha256": hashlib.sha256(canonical_json_v1(material["preprocessing_contract"])).hexdigest(),
        "engine": {"path": str(material["engine_pin"].path), "sha256": material["engine_pin"].sha256},
        "engine_socket": material["engine_socket"], "accepted": False, "full_image_freeze": False}


def prepare_contexts(root, output, plan, material):
    from checkpoint_runtime_plan import build_finite_study_runtime_plan_v1
    from publication_operational_capture_plan_v1 import _native_context, _guardian_context, ROUTES
    from publication_guardian_component_preprocessing_contract_v1 import STUDY_AUTHORITY_KIND_V1, validate_finite_study_guardian_authority_v1
    from publication_guardian_runtime_expectations_v1 import runtime_expectations_from_worker_projection_v1
    controls = output/"contexts"; controls.mkdir(mode=0o700)
    plan_ref = write_json(output/"plan.original.json", plan)
    absolute = lambda ref: {**{k: ref[k] for k in ("path", "size_bytes", "sha256")}, "path": str(root/ref["path"])}
    refs = {key: absolute(value) for key,value in material["descriptors"].items()}
    guardian = {key: refs[key] for key in ("capability_manifest", "model_authority", "execution_code_closure")}
    guardian.update(execution_config=absolute(material["worker_projection"]["execution_config"]),
        native_protocol_source=descriptor(root/"deploy/native_gst_probe/vast_native_gst_probe.cpp"),
        proxy_protocol_source=descriptor(root/"scripts/checkpoint_deepstream_protocol_bridge.py"))
    rows, native = [], {}
    for arm in [*plan["arms"], *plan["pilots"]["initial"], *plan["pilots"]["conditional"]]:
        runtime = build_finite_study_runtime_plan_v1(plan, arm["arm_id"])
        source_ref = write_json(controls/(arm["arm_id"]+".source-plan.json"), runtime)
        run_id = "finite-"+plan["sha256"][:16]+"-"+arm["arm_id"]
        row = {"operation_id": arm["arm_id"], "phase": arm["stage"], "arm_id": arm["arm_id"], "run_id": run_id,
            "system": "gstreamer_custom", "scenario": runtime["scenario"], "codec": "h264", "policy": arm["resource"]+"_only",
            "deadline_ms": 100.0, "warmup_s": 30.0, "measurement_s": 180.0, "drain_timeout_s": 10.0,
            "streams": 6, "branches": 4, "descriptors": {**{k: refs[k] for k in ("capability_manifest", "model_authority", "calibration", "execution_code_closure")},
                "source_plan": source_ref, "policy_request_source": guardian["native_protocol_source"],
                "policy_coordinator_source": descriptor(root/"scripts/checkpoint_native_policy_runtime.py")}, "front_workers_by_route": {}}
        for route in ROUTES:
            branch = route.split(":")[0]
            row["front_workers_by_route"][route] = [{"worker_id": stream["graph_process"]["process_id"] if arm["topology"] == "shared" else
                next(w["process_id"] for w in stream["workers"] if w["branch_id"] == branch), "stream_id": stream["stream_id"]}
                for stream in runtime["streams"]]
        row["original_operation"] = write_json(controls/(arm["arm_id"]+".operation.json"), payload_with_sha256_v1(row))
        rows.append(row)
        native[arm["arm_id"]] = write_json(controls/(arm["arm_id"]+".native-context.json"),
            _native_context(row, "finite-component-study", study_runtime_plan=runtime))
    manifest = write_json(controls/"operations.original.json", payload_with_sha256_v1({"kind": "finite-component-study-operations", "operations": rows}))
    inventory = write_json(controls/"source-plans.original.json", {"source_plans": [r["descriptors"]["source_plan"] for r in rows]})
    contract = write_json(controls/"preprocessing-contract.json", material["preprocessing_contract"])
    projection = material["worker_projection"]
    content_sha = hashlib.sha256(canonical_json_v1(material["preprocessing_contract"])).hexdigest()
    expectations = runtime_expectations_from_worker_projection_v1(execution_config_authority=projection["execution_config"],
        binding_set_authority=projection["binding_set"], worker_authority=projection["workers"],
        policy_contract_sha256=material["capability_manifest"]["policy_contract_sha256"], preprocessing_contract_content_sha256=content_sha)
    variants = {}
    for variant in ("global-client", "branch-channel"):
        pool = output/("pool-"+variant); pool.mkdir(mode=0o700)
        context = _guardian_context(rows, "finite-component-study", guardian, manifest, inventory, pool/"journal", study_plan=plan)
        context_ref = write_json(controls/(variant+".guardian-context.json"), context)
        allowed = [{**{k: r[k] for k in ("operation_id", "arm_id", "run_id", "system", "scenario", "codec", "policy", "deadline_ms")},
            "wire_arm_id": hashlib.sha256(("analytics_execution_arm_v1\n"+r["run_id"]+"\n"+r["policy"]+"\n100.000000").encode()).hexdigest()} for r in rows]
        unsigned = {"kind": "finite-study-preprocessing-binding", "plan": plan_ref, "context": context_ref, "contract": contract,
            "allowed_operations": allowed, "original_model_inputs": refs, "accepted": False}
        binding = payload_with_sha256_v1(unsigned)
        binding_ref = write_json(controls/(variant+".preprocessing-binding.json"), binding)
        authority = {"schema_version": 1, "artifact_kind": STUDY_AUTHORITY_KIND_V1, "allowed_operations": allowed,
            "study_scope": {"kind": "finite-component-study", "plan_sha256": plan["sha256"], "max_frame_id": 441,
                "max_requests_per_arm": 10608, "max_operations": 32}, "component_authority_file_sha256": plan_ref["sha256"],
            "component_authority_identity_sha256": plan["sha256"], "capability_manifest_file_sha256": refs["capability_manifest"]["sha256"],
            "operational_context_file_sha256": context_ref["sha256"], "operational_context_identity_sha256": context["sha256"],
            "preprocessing_contract_content_sha256": content_sha, "preprocessing_contract_file_sha256": contract["sha256"],
            "materialization_receipt_identity_sha256": binding["sha256"], "materialization_receipt_file_sha256": binding_ref["sha256"],
            "policy_contract_sha256": material["capability_manifest"]["policy_contract_sha256"]}
        validate_finite_study_guardian_authority_v1(authority)
        variants[variant] = {"context": context_ref, "authority": write_json(controls/(variant+".authority.json"), authority),
            "binding": binding_ref, "pool": str(pool)}
    execution_ref=write_json(controls/"execution-manifest.original.json",material["execution_manifest"])
    return {"plan": plan_ref, "execution_manifest":execution_ref, "model_manifest":absolute(material["proxy_manifest"]), "operations": rows, "native": native, "variants": variants,
            "preprocessing_contract": contract, "runtime_expectations": expectations}


def transport_prefix(path, *, schedule, admissions, deadline):
    """Parse the closed original 80-byte wire; never manufacture missing rows."""
    original=descriptor(path,maximum=MAX_MEDIA,deadline=deadline); before=epoch(Path(path).lstat())
    rows=[]
    with Path(path).open("rb") as stream:
        def read(n):
            data=bytearray()
            while len(data)<n:
                require(time.monotonic()<deadline,"original transport parse deadline")
                chunk=stream.read(min(65536,n-len(data)))
                require(bool(chunk),"partial original source transport")
                data.extend(chunk)
            return bytes(data)
        while stream.tell()<original["size_bytes"]:
            header=read(80)
            magic,version,flags,seq,cycle,pts,transport,dts,duration,a,k,h,size=struct.unpack(">8sHH6Q3IQ",header)
            require(magic==b"VASTAU01" and version==1 and flags==1 and cycle==0 and
                seq==len(rows)+1 and seq<=442 and 0<a<=8192 and 0<k<=8192 and h==64 and 0<size<=16*1024**2,
                "original source transport header/type/count/cap mismatch")
            admission,key,sha=(read(n).decode() for n in (a,k,h))
            digest=hashlib.sha256();left=size
            while left:
                chunk=read(min(left,65536));digest.update(chunk);left-=len(chunk)
            slot=schedule[seq-1]; accepted=admissions.get(key)
            require(accepted is not None and admission==accepted["admission_id"] and slot["eligible_before_stop"] and
                key==slot["input_frame_key"] and sha==slot["payload_sha256"]==digest.hexdigest() and
                size==slot["payload_size_bytes"] and pts==slot["access_unit_pts_ns"] and
                transport==slot["transport_pts_ns"] and duration==slot["duration_ns"] and
                (None if dts==(1<<64)-1 else dts)==slot.get("transport_dts_ns"), "original source transport/admission/schedule join")
            rows.append({"sequence":seq,"ordinal":seq-1,"input_frame_key":key,"admission_id":admission,
                "payload_sha256":sha,"payload_size_bytes":size,"transport_pts_ns":transport,
                "planned_schedule_offset_ns":slot["schedule_offset_ns"],"eligible_before_stop":True,
                "measurement":slot["measurement"]})
        require(epoch(os.fstat(stream.fileno()))==before==epoch(Path(path).lstat()),"closed source spool drifted")
    require(0<len(rows)<=442,"empty original offered prefix")
    return rows,original,before


def offered_prefix_stop_gate(commands,args,root,output,plan,images):
    gate=output/"offered-prefix-stop";gate.mkdir(mode=0o700)
    plan_ref=write_json(output/"source-gate-plan.original.json",plan)
    scenario=next(a for a in plan["arms"] if a["rate"]=="2" and a["resource"]=="cpu" and a["topology"]=="shared")["scenario"] if "scenario" in plan["arms"][0] else "checkpoint6"
    from checkpoint_runtime_plan import build_finite_study_runtime_plan_v1
    arm=next(a for a in plan["arms"] if a["rate"]=="2" and a["resource"]=="cpu" and a["topology"]=="shared")
    scenario=build_finite_study_runtime_plan_v1(plan,arm["arm_id"])["scenario"]
    child,record=_native(commands,args.engine,images["gstreamer"]["image_id"],root,output,
        ["--config",root/"configs/experiments.yaml","--scenario",scenario,"--finite-study-plan",plan_ref["path"],
         "--finite-study-source-gate","--output-dir",gate,"--source-binary","/usr/local/bin/vast_checkpoint_source",
         "--finite-study-campaign-deadline-ns",commands.deadline_monotonic_ns,
         "--finite-study-expected-boot",Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
         "--finite-study-expected-time-namespace",actual_clock_domain_label()],
         entrypoint="/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3")
    commands.wait(child,record,maximum_files=((str(gate/"0.transport.original.raw"),MAX_MEDIA),(str(gate/"5.transport.original.raw"),MAX_MEDIA)))
    facts=json.loads((gate/"source-stop.original.json").read_bytes())
    require(facts["actual_transport_eof"] and set(facts["returncodes"].values())=={0},"original source STOP/EOF closure failed")
    admissions={r["input_frame_key"]:r for r in jsonl_rows((gate/"admissions.original.jsonl").read_bytes())}
    receipts=[]
    for sid,name in ((0,"front_gate"),(5,"underbody")):
        spool=gate/(str(sid)+".transport.original.raw")
        wire,spool_ref,before=transport_prefix(spool,schedule=stream_schedule(plan,sid,"2"),admissions=admissions,deadline=commands.deadline)
        _,_,width,height,_=PARENTS[name];destination=output/(name+".offered-prefix-reference.original.jsonl")
        with spool.open("rb") as source:
            require(epoch(os.fstat(source.fileno()))==before,"source reference transport changed before original stdin")
            child,record=_native(commands,args.engine,images["gstreamer"]["image_id"],root,output,
                ["--checkpoint-study-reference-transport",destination,width,height,commands.deadline_monotonic_ns,len(wire)],stdin=source)
            commands.wait(child,record,maximum_files=((str(destination),8*1024**2),))
            require(epoch(os.fstat(source.fileno()))==before==epoch(spool.lstat()),"source reference transport drifted")
        actual,ref=reference_rows(destination,completion="offered_prefix_transport_eof",count=len(wire),input_sha="",width=width,height=height,deadline=commands.deadline)
        full=jsonl_rows((output/(name+".hardware-reference.original.jsonl")).read_bytes())
        require(actual[0]["prefix"]==full[0]["prefix"] and all(row["pts_ns"]==slot["transport_pts_ns"] and
            all(row[key]==full[index+1][key] for key in ("y_sha256","u_sha256","v_sha256","rgb_sha256"))
            for index,(row,slot) in enumerate(zip(actual[1:-1],wire))),"real STOP prefix color/PTS/reference mismatch")
        receipts.append({"stream_id":sid,"transport":spool_ref,"wire_rows":wire,"reference":ref,
            "actual_source_stop_eof":True,"actual_reference_eos":True})
        require(epoch(spool.lstat())==before,"owned source spool pathname rebound before unlink");spool.unlink()
    return write_json(output/"source-stop-reference-gate.json",{"original_lifecycle":descriptor(gate/"source-stop.original.json",deadline=commands.deadline),
        "central_admissions":descriptor(gate/"admissions.original.jsonl",deadline=commands.deadline),"streams":receipts,
        "actual_full_prefix_stop_gate":True,"accepted":False})


def read_json_descriptor(ref, *, deadline, maximum=16*1024**2):
    require(descriptor(Path(ref["path"]),maximum=maximum,deadline=deadline)==ref,"original control descriptor changed")
    value=json.loads(Path(ref["path"]).read_bytes())
    require(descriptor(Path(ref["path"]),maximum=maximum,deadline=deadline)==ref,"original control changed during decode")
    return value


def write_rows(path,rows):
    total=0
    with Path(path).open("xb") as stream:
        for row in rows:
            raw=canonical_json_v1(row)+b"\n";total+=len(raw)
            require(total<=MAX_STUDY_ROLE_BYTES and len(raw)<=1024**2,"decoded original role cap")
            require(stream.write(raw)==len(raw),"short original decoded role write")
        stream.flush();os.fsync(stream.fileno())
    return descriptor(Path(path),maximum=MAX_STUDY_ROLE_BYTES)


def owned_subprocess_runner(commands,engine):
    """The sidecar command runner over the driver's owned command records."""
    def runner(command,**kwargs):
        command=[str(engine) if command[0]=="docker" else command[0],*command[1:]]
        timeout=float(kwargs.get("timeout",120))
        child,record=commands.launch(command,env=kwargs.get("env"))
        record["deadline"]=min(commands.deadline,time.monotonic()+timeout)
        try:
            raw=commands.wait(child,record,maximum=1024**2,accept_nonzero=True)
        except ValueError:
            # Kill and reap the owned group first; only the per-call bound is a retryable timeout.
            if child.poll() is None:
                try: os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait(timeout=5)
                record.update(returncode=child.returncode,closed_monotonic_ns=time.monotonic_ns(),killed_after_bound=True)
                if record["deadline"]<commands.deadline and time.monotonic()>=record["deadline"]:
                    raise subprocess.TimeoutExpired(command,timeout)
            raise
        err=Path(record["stderr_path"]).read_bytes()
        out,err=(raw.decode(),err.decode()) if kwargs.get("text",False) else (raw,err)
        if kwargs.get("check",False) and child.returncode!=0:
            raise subprocess.CalledProcessError(child.returncode,command,out,err)
        return subprocess.CompletedProcess(command,child.returncode,out,err)
    return runner


def start_pool(commands,root,prepared,material,variant):
    from checkpoint_gstreamer_analytics_sidecar import (DockerWorkerProcessFactory,GStreamerAnalyticsProductionService,
        PRODUCTION_MAX_CONNECTIONS_MINIMUM,PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM,PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM)
    data=prepared["control"]["variants"][variant]
    pool=Path(data["pool"]);runtime=pool/"runtime";evidence=pool/"evidence"
    require(not os.path.lexists(runtime) and not os.path.lexists(evidence),"study held pool namespace already consumed")
    runtime.mkdir(mode=0o700)
    context=read_json_descriptor(data["context"],deadline=commands.deadline)
    authority=read_json_descriptor(data["authority"],deadline=commands.deadline)
    binding_root=(root/material["worker_projection"]["binding_set"]["index"]["path"]).parent
    runner=owned_subprocess_runner(commands,material["engine_pin"].path)
    def popen(command,**kwargs):
        commands.remaining();command=[str(material["engine_pin"].path),*command[1:]]
        child=subprocess.Popen(command,**kwargs,start_new_session=True)
        commands.children.append(child)
        commands.records.append({"argv":command,"pid":child.pid,"pgid":child.pid,"role":"original_worker_frontend",
            "started_monotonic_ns":time.monotonic_ns(),"stdout_path":None,"stderr_path":None})
        return child
    factory=DockerWorkerProcessFactory(project_root=root,binding_set_root=binding_root,runtime_dir=runtime,
        command_runner=runner,popen_factory=popen)
    service=GStreamerAnalyticsProductionService(execution_config=material["execution_config"],binding_set_dir=binding_root,
        policy_capability_manifest=material["capability_manifest"],preprocessing_contract=material["preprocessing_contract"],
        preprocessing_authority=authority,production_runtime_expectations=prepared["control"]["runtime_expectations"],
        runtime_dir=runtime,front_socket=runtime/"analytics.sock",evidence_root=evidence,process_factory=factory,
        max_connections=PRODUCTION_MAX_CONNECTIONS_MINIMUM,max_requests_per_connection=PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM,
        max_total_requests=PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM,startup_timeout_s=min(120,commands.remaining()-15),
        shutdown_timeout_s=min(10,commands.remaining()-5),operational_context={"output_dir":context["output_dir"],
            "headers_by_route":{tuple(key.split(":")):value for key,value in context["headers_by_route"].items()}})
    service.set_study_deadline_v1(commands.deadline)
    actual=service.start()
    try:
        return service,actual,service.study_worker_clock_domains_v1()
    except BaseException as error:
        try:stop_pool(commands,service,actual,commands.output,variant)
        except BaseException as cleanup:error.add_note("started study pool retirement: "+str(cleanup)[:2048])
        raise


def stop_pool(commands,service,authority,output,variant):
    from checkpoint_gstreamer_analytics_sidecar import request_publication_sidecar_guardian_stop_v1
    previous=commands.closing_deadline
    commands.closing_deadline=min(commands.deadline,time.monotonic()+15.0)
    try:
        primary=None;acknowledgement=None;closure=None
        try:
            commands.remaining()
            acknowledgement=request_publication_sidecar_guardian_stop_v1(authority,timeout_s=min(2,commands.remaining()))
        except BaseException as error:
            primary=error
        try:
            closure=service.stop()
        except BaseException as error:
            if primary is None:primary=error
            else:primary.add_note("original held pool shutdown: "+str(error)[:2048])
        if primary is not None:raise primary
        require(closure["status"]=="clean_stop_nonpublication" and closure["failure"] is None and not closure["cleanup_errors"],
            "original held eight-worker pool failed retirement")
        return write_json(output/(variant+".pool-closure.original.json"),{"acknowledgement":acknowledgement,"lifecycle":closure,"operational_group":service.operational_group})
    finally:commands.closing_deadline=previous


def verify_guardian_ranges(pool_ref, ranges, commands):
    closed=read_json_descriptor(pool_ref,deadline=commands.deadline)
    group=read_json_descriptor(closed["operational_group"],deadline=commands.deadline)
    journals={row["path"]:row for row in group["journals"]}
    for observed in ranges:
        ref=journals[observed["original_journal_path"]]
        require(descriptor(Path(ref["path"]),maximum=64*1024**2,deadline=commands.deadline)==
            {key:ref[key] for key in ("path","size_bytes","sha256")},"closed held journal descriptor drifted")
        with Path(ref["path"]).open("rb") as stream:
            size=observed["original_prefix_size_bytes"];offset=0;digest=hashlib.sha256()
            before=epoch(os.fstat(stream.fileno()))
            while offset<size:
                commands.remaining();chunk=os.pread(stream.fileno(),min(1024**2,size-offset),offset)
                require(bool(chunk),"closed held journal lost an original arm prefix")
                digest.update(chunk);offset+=len(chunk)
            require(digest.hexdigest()==observed["original_prefix_sha256"] and
                before==epoch(os.fstat(stream.fileno()))==epoch(Path(ref["path"]).lstat()),"original arm prefix differs from closed held journal")


def native_client_waits(wait_rows):
    """Join each native client begin/released pair into one wait observation."""
    paired={};waits=[]
    for row in wait_rows:
        key=(row["clock_domain"]["pid"],row["request_id"])
        phase=row["phase"];require(phase not in paired.setdefault(key,{}),"duplicate original native wait phase")
        paired[key][phase]=row
    for pair in paired.values():
        # Native persists begin after acquisition with attempt only; released carries the actual acquisition.
        require(set(pair)=={"begin","released"} and all(pair["begin"].get(k) is None for k in ("acquired_ns","reply_ns","released_ns"))
            and pair["released"].get("acquired_ns") is not None and pair["released"].get("released_ns") is not None,
            "native wait lacks a genuine begin/released pair; failed/UNKNOWN arm")
        row=pair["released"]
        require(all(pair["begin"][k]==row[k] for k in ("request_id","attempt_ns","clock_domain","input_frame_key","worker_id","branch","stream_id")),
            "native wait two-row identity drift")
        waits.append({**row,"kind":"native_client"})
    return waits


def decode_guardian_rows(decoded,arm,run_id,wire_arm_id,clock_proof,bridge_domain):
    """Decoded guardian rows of one arm plus their bridge/worker wait observations."""
    guardians=[];waits=[]
    for row in decoded:
        identity=row["identity"]
        require(identity["run_id"]==run_id and identity["arm_id"]==wire_arm_id,"original guardian wire arm/run mismatch")
        # Explicit decoded alias to the logical plan ID; original identity retained.
        header=row["original_header"]
        # The held journal header stays in the retained range file; rows keep its chain anchor and route.
        guardians.append({**{k:v for k,v in row.items() if k!="original_header"},"original_header_sha256":header["sha256"],
            "original_route":header["route"],"original_wire_identity":identity,"identity":{**identity,"arm_id":arm["arm_id"]}})
        timing=row["terminal"].get("timings")
        if timing is not None:
            interval=timing["bridge_route"];require(interval["pid"]==os.getpid(),"bridge timing owner differs from actual service owner")
            waits.append({"kind":"bridge_route","request_id":identity["request_id"],"attempt_ns":interval["begin_ns"],
                "acquired_ns":interval["acquired_ns"],"reply_ns":interval["reply_ns"],"released_ns":interval["end_ns"],"clock_domain":bridge_domain})
            worker=timing["worker"]
            if worker is not None:
                capability=row["original_header"]["worker_capability"]
                waits.append({"kind":"worker","request_id":identity["request_id"],
                    **dict(zip(("received_ns","inference_started_ns","inference_finished_ns","completed_ns"),
                        (worker[k] for k in ("worker_received_monotonic_ns","inference_started_monotonic_ns","inference_finished_monotonic_ns","worker_completed_monotonic_ns")))),
                    "clock_domain":{"clock":"CLOCK_MONOTONIC","pid":None,
                        "boot_id":clock_proof["native_environment"]["VAST_CHECKPOINT_WORKER_CLOCK_BOOT_ID"],
                        "time_namespace":clock_proof["native_environment"]["VAST_CHECKPOINT_WORKER_CLOCK_TIME_NAMESPACE"]},
                    "actual_route_clock_observation":next(observation for observation in clock_proof["observations"] if observation["route"]==[row["original_header"]["route"]["branch"],row["original_header"]["route"]["resource"]]),
                    "worker_identity":{"worker_id":capability["worker_id"],"capability_sha256":hashlib.sha256(canonical_json_v1(capability)).hexdigest()}})
    return guardians,waits


def decode_arm(commands,plan,arm,facts,output,snapshot,clock_proof,pool_delta,material):
    from publication_operational_request_domain_v1 import iter_native_domain_v1
    from publication_policy_contract import validate_decision_record
    runtime=facts["result"];run_id=facts["run_id"];original_client_mode=facts["final_variant"]
    require(original_client_mode in ("global-client","branch-channel"),"original native client mode is foreign")
    variant=original_client_mode
    require(variant==material["active_variant"],"original native client mode differs from held pool")
    from checkpoint_runtime_plan import build_finite_study_runtime_plan_v1
    layout=build_finite_study_runtime_plan_v1(plan,arm["arm_id"])
    def authority(row):
        assessed=validate_decision_record(row["accepted_record"],material["capability_manifest"])
        require(assessed["passed"],"original full native decision authority failed")
    scope={"kind":"finite-component-study","plan_sha256":plan["sha256"],"max_frame_id":441,"max_requests_per_arm":10608,"max_operations":32}
    native=list(iter_native_domain_v1(Path(facts["native_domain"]["path"]),expected_descriptor=facts["native_domain"],
        original_authority_validator=authority,study_scope=scope))
    original_protocol=jsonl_rows((output/"native-protocol.original.jsonl").read_bytes())
    for terminal in runtime["branch_terminal_records"]:
        if terminal["terminal_status"]=="drop":
            matched=[row for row in original_protocol if row.get("event_kind")=="branch_drop" and
                row.get("input_frame_key")==terminal["input_frame_key"] and row.get("branch_id")==terminal["branch_id"] and
                row.get("worker_id")==terminal["worker_id"]] if "worker_id" in terminal else [row for row in original_protocol if
                    row.get("event_kind")=="branch_drop" and row.get("input_frame_key")==terminal["input_frame_key"] and row.get("branch_id")==terminal["branch_id"]]
            require(len(matched)==1,"original native drop raw protocol join is ambiguous")
            native.append({"branch_terminal":terminal,"original_event":matched[0],"resource":arm["resource"],
                "original_raw_descriptor":descriptor(output/"native-protocol.original.jsonl",maximum=128*1024**2,deadline=commands.deadline)})
    guardians=[];waits=[]
    bridge_domain={"clock":"CLOCK_MONOTONIC","boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "time_namespace":actual_clock_domain_label(),"pid":os.getpid()}
    wire_arm_id=next(r for r in material["active_allowed"] if r["run_id"]==run_id)["wire_arm_id"]
    guardians,guardian_waits=decode_guardian_rows(snapshot["decoded"],arm,run_id,wire_arm_id,clock_proof,bridge_domain)
    waits.extend(guardian_waits)
    source_events=[];accounting_bytes=0;wait_rows=[]
    for path in sorted((output/"study").glob("*.jsonl")):
        ref=descriptor(path,maximum=MAX_STUDY_ROLE_BYTES,deadline=commands.deadline);accounting_bytes+=ref["size_bytes"]
        rows=jsonl_rows(path.read_bytes())
        for row in rows:
            if row.get("kind")=="client":wait_rows.append(row)
            else:source_events.append(row)
    require(accounting_bytes<=MAX_STUDY_ROLE_BYTES,"aggregate actual source/native accounting+waits arm cap")
    waits.extend(native_client_waits(wait_rows))
    recipients={str(s["stream_id"]):({w["branch_id"]:w["process_id"] for w in s["workers"]} if arm["topology"]=="baseline" else
        {"shared":s["graph_process"]["process_id"]}) for s in layout["streams"]}
    actual_clock={**facts["clock_domain"],"clock":"CLOCK_REALTIME"}
    require(actual_clock["boot_id"]==bridge_domain["boot_id"] and actual_clock["time_namespace"]==bridge_domain["time_namespace"],"actual native/service clock proof mismatch")
    from checkpoint_gstreamer_runtime import load_analytics_model_bindings,native_policy_identity_environment
    bindings=load_analytics_model_bindings(Path(material["root"])/material["proxy_manifest"]["path"],required_branches=plan["branches"])
    identities=native_policy_identity_environment(system="gstreamer_custom",capability_manifest=material["capability_manifest"])
    drops={branch:{"detector":identities["VAST_CHECKPOINT_ANALYTICS_DROP_DETECTOR_"+branch],
        "backend":"openvino-dlstreamer:"+bindings[branch]["factory"]} for branch in plan["branches"]}
    closure={"arm_id":arm["arm_id"],"run_id":run_id,"plan_sha256":plan["sha256"],"bundle_sha256":plan["bundle_sha256"],
        "final_variant":variant,"original_client_mode":original_client_mode,"source_window_closed":all(v[-2:]==["ADMISSION_STOPPED","DRAINED"] for v in runtime["lifecycle_statuses"].values()),
        "drain_deadline_reached":False,"source_streams_closed":sorted(s["stream_id"] for s in layout["source_coordinators"] if s["process_id"] in runtime["source_process_ids"]),
        "source_clock_domain":actual_clock,"native_clock_domain":actual_clock,"recipient_bindings":recipients,
        "infra_errors":[],"close_errors":[],"runtime_ledger":runtime["terminal_ingress_rows"],"runtime_frame_terminals":runtime["runtime_frame_terminals"],
        "native_drop_bindings":drops,"lifecycle_statuses":runtime["lifecycle_statuses"],
        "window_start_timestamp_ms":runtime["window_start_timestamp_ms"],"window_end_timestamp_ms":runtime["window_end_timestamp_ms"],
        "drain_end_timestamp_ms":runtime["drain_end_timestamp_ms"],"pool_delta":pool_delta,"clock_proof":clock_proof,"guardian_original_ranges":snapshot["ranges"]}
    admissions=jsonl_rows((output/"admissions.original.jsonl").read_bytes())
    roles={"admissions":admissions,"source_events":source_events,"native_terminals":native,"guardian_events":guardians,"waits":waits,"closure":closure}
    refs={kind:[write_rows(output/(kind+".decoded.jsonl"),rows)] for kind,rows in roles.items() if kind!="closure"}
    refs["closure"]=write_json(output/"closure.original.json",closure)
    return roles,refs


def execute_arm(commands,args,root,prepared,plan,arm,service,clock_proof,material):
    from publication_policy_qualification_runtime_inputs_v2 import DETECT_BIN
    commands.remaining();material["verify_barrier"]();verify_source_pins(prepared["source_pins"],commands)
    operation=next(row for row in prepared["control"]["operations"] if row["arm_id"]==arm["arm_id"])
    out=commands.output/arm["arm_id"];out.mkdir(mode=0o700)
    boundary=service.activate_study_arm_v1(arm["arm_id"])
    variant="branch-channel" if args._variant=="branch-channel" else "global-client"
    control=prepared["control"]
    arguments=["--config",root/"configs/experiments.yaml","--scenario",operation["scenario"],"--finite-study-plan",control["plan"]["path"],
        "--finite-study-arm",arm["arm_id"],"--finite-study-client-mode","branch" if variant=="branch-channel" else "global-client",
        "--finite-study-campaign-deadline-ns",commands.deadline_monotonic_ns,"--operational-request-context",control["native"][arm["arm_id"]]["path"],
        "--policy-capability-manifest",root/material["descriptors"]["capability_manifest"]["path"],"--policy-calibration",root/material["descriptors"]["calibration"]["path"],
        "--analytics-execution-manifest",control["execution_manifest"]["path"],"--analytics-model-manifest",control["model_manifest"]["path"],
        "--analytics-execution-socket",service.front_socket,"--analytics-preprocessing-contract-sha256",hashlib.sha256(canonical_json_v1(material["preprocessing_contract"])).hexdigest(),
        "--binary","/usr/local/bin/vast_native_gst_probe","--source-binary","/usr/local/bin/vast_checkpoint_source",
        "--detect-bin",DETECT_BIN,"--output-dir",out,"--run-id",operation["run_id"]]
    child,record=_native(commands,args.engine,prepared["images"]["gstreamer"]["image_id"],root,out,arguments,
        entrypoint="/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3",environment=clock_proof["native_environment"])
    commands.wait(child,record,maximum_files=((str(out/"arm.original.json"),256*1024**2),))
    require(all(p.poll() is not None for p in [child]),"previous native frontend did not close")
    delta=service.finish_study_arm_v1(arm["arm_id"])
    capture=out/"guardian-ranges";capture.mkdir(mode=0o700)
    snapshot=service.capture_study_arm_v1(operation["run_id"],capture,deadline=commands.deadline)
    facts=json.loads((out/"arm.original.json").read_bytes())
    material["active_variant"]=args._variant
    material["active_allowed"]=read_json_descriptor(control["variants"][variant]["authority"],deadline=commands.deadline)["allowed_operations"]
    roles,refs=decode_arm(commands,plan,arm,facts,out,snapshot,clock_proof,delta,material)
    material.setdefault("guardian_ranges",{}).setdefault(args._variant,[]).extend(snapshot["ranges"])
    total=sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    require(total<=MAX_RAW_ARM,"actual arm raw aggregate exceeded original cap")
    material["verify_barrier"]();commands.remaining()
    return roles,refs


def pilot_select_branch(pilots):
    require(len(pilots)==4 and all(p["reduction"]["raw_reconciliation_complete"] for p in pilots),
        "original pilots have incomplete raw reconciliation")
    shared=[p["reduction"]["waits"]["native_client"] for p in pilots if p["arm"]["topology"]=="shared"]
    require(len(shared)==2,"pilot topology population drifted")
    return any(row["wait_ns"]["n"]>=30 and row["median_wait_fraction"] is not None and
        row["median_wait_fraction"]>=.10 for row in shared)


def run(args):
    from reduce_canonical_systems_study_v1 import reduce_arm,reduce_closed_study
    started=time.monotonic();out=Path(args.output_dir);root=Path(args.project_root).resolve(strict=True)
    require(out.is_absolute() and out.is_relative_to(root) and not os.path.lexists(out),"campaign requires exclusive project namespace")
    out.mkdir(mode=0o700)
    commands=Commands(out,started+14400.0);primary=None;service=None;authority=None;variant="global-client";pool_closures=[]
    reservation=reservation_identity=None
    try:
        prepared=read_json_descriptor({"path":str(Path(args.prepared)),"size_bytes":args.prepared_size_bytes,"sha256":args.prepared_sha256},deadline=commands.deadline)
        require(prepared["kind"]=="finite-component-study-prepared-v1" and prepared["owned_command_and_container_closure"],"actual preparation did not close")
        plan=prepared["plan"];validate_study_plan(plan)
        verify_source_pins(prepared["source_pins"],commands)
        require(shutil.disk_usage(out).free>=20*1024**3+MAX_RAW_CAMPAIGN,"campaign space/reservation is insufficient")
        reservation,reservation_identity=reserve_space(out,commands.deadline)
        with model_material(args) as material:
            require(material_document(material,prepared["images"],prepared["tools"],{r["path"]:r for r in prepared["dependencies"]})==plan["selected_material"],"original prepared model/image/tool material drifted")
            for path,saved in prepared["original_epochs"].items():require(epoch(Path(path).lstat())==tuple(saved),"original AVI held boundary drifted")
            service,authority,proof=start_pool(commands,root,prepared,material,variant)
            args._variant=variant;pilots=[]
            for arm in plan["pilots"]["initial"]:
                roles,refs=execute_arm(commands,args,root,prepared,plan,arm,service,proof,material)
                pilots.append({"arm":arm,"raw":refs,"reduction":reduce_arm(plan,arm["arm_id"],roles,deadline=commands.deadline)})
            switch=pilot_select_branch(pilots)
            if switch:
                pool_ref=stop_pool(commands,service,authority,out,variant)
                verify_guardian_ranges(pool_ref,material.get("guardian_ranges",{}).get(variant,[]),commands)
                pool_closures.append(pool_ref);service=None
                variant="branch-channel";args._variant=variant
                service,authority,proof=start_pool(commands,root,prepared,material,variant)
                for arm in plan["pilots"]["conditional"]:
                    roles,refs=execute_arm(commands,args,root,prepared,plan,arm,service,proof,material)
                    pilots.append({"arm":arm,"raw":refs,"reduction":reduce_arm(plan,arm["arm_id"],roles,deadline=commands.deadline)})
            require(all(p["reduction"]["raw_reconciliation_complete"] for p in pilots),"conditional pilots have incomplete raw reconciliation")
            effects={}
            for arm in plan["arms"]:
                _,effects[arm["arm_id"]]=execute_arm(commands,args,root,prepared,plan,arm,service,proof,material)
                require(sum(path.stat().st_size for path in out.rglob("*") if path.is_file() and path!=reservation)<=MAX_RAW_CAMPAIGN,"actual campaign raw aggregate exceeded original cap")
            pool_ref=stop_pool(commands,service,authority,out,variant)
            verify_guardian_ranges(pool_ref,material.get("guardian_ranges",{}).get(variant,[]),commands)
            pool_closures.append(pool_ref);service=None
            binding={"kind":"finite-component-study-closed-inputs","plan":prepared["control"]["plan"],"plan_sha256":plan["sha256"],
                "bundle_sha256":plan["bundle_sha256"],"final_variant":variant,"arms":effects}
            binding_ref=write_json(out/"closed-inputs.original.json",binding)
            reduced=reduce_closed_study(binding,deadline=commands.deadline)
            material["verify_barrier"]();verify_source_pins(prepared["source_pins"],commands)
            require(reduced["raw_effect_matrix_complete"],"original 24-arm raw matrix is incomplete")
            commands.retire();require(time.monotonic()<commands.deadline,"original campaign closure is late")
            completed={"kind":"finite-component-study-completed-v1","plan_sha256":plan["sha256"],
                "binding":binding_ref,"final_variant":variant,"pilots":pilots,"pool_closures":pool_closures,"reduction":reduced,
                "canonical_study_complete":True,"legacy_full_run_eligible":False,"qualification_eligible":False,"q4_eligible":False,
                "publication_eligible":False,"started_monotonic_ns":int(started*1e9),"elapsed_s":time.monotonic()-started,"commands":commands.records}
        release_space(reservation,reservation_identity);reservation=None
        result=write_study_results(out,completed)
        require(time.monotonic()<commands.deadline,"original final result closed late")
        return result
    except BaseException as error:
        primary=error
        if service is not None:
            try:stop_pool(commands,service,authority,out,variant)
            except BaseException as cleanup:error.add_note(str(cleanup)[:4096])
        write_json(out/"failed.original.json",{"kind":"finite-study-failed-original-v1","first_error":type(error).__name__+":"+str(error),
            "notes":getattr(error,"__notes__",[]),"commands":commands.records,"canonical_study_complete":False})
        raise
    finally:
        if commands.closing_deadline is None:commands.retire(primary)
        if reservation is not None:release_space(reservation,reservation_identity)


def study(args):
    clock=preparation_clock(args)
    root=Path(args.project_root).resolve(strict=True);parent=Path(args.output_dir)
    require(parent.is_absolute() and parent.is_relative_to(root) and not os.path.lexists(parent),"study requires one exclusive parent namespace")
    parent.mkdir(mode=0o700)
    preparation=copy.copy(args);preparation.operation="prepare";preparation.output_dir=parent/"prepare"
    preparation.preparation_started_monotonic_ns=clock["started_monotonic_ns"]
    preparation.preparation_boot_id=clock["boot_id"]
    preparation.preparation_time_namespace=clock["time_namespace"]
    prepared=prepare(preparation)
    campaign=copy.copy(args);campaign.operation="run";campaign.output_dir=parent/"run"
    campaign.prepared=Path(prepared["path"]);campaign.prepared_size_bytes=prepared["size_bytes"];campaign.prepared_sha256=prepared["sha256"]
    return run(campaign)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="operation",required=True)
    for operation in ("prepare","run","study"):
        current=sub.add_parser(operation)
        current.add_argument("--project-root",required=True,type=Path)
        current.add_argument("--output-dir",required=True,type=Path)
        current.add_argument("--engine",required=True)
        current.add_argument("--engine-socket",required=True)
        for option in ("capability-manifest","calibration","model-parity-receipt","worker-freeze-receipt","execution-code-closure"):
            current.add_argument("--"+option,required=True)
        if operation in ("prepare","study"):
            current.add_argument("--front-gate",required=True,type=Path);current.add_argument("--underbody",required=True,type=Path)
            current.add_argument("--preparation-started-monotonic-ns",type=int)
            current.add_argument("--preparation-boot-id")
            current.add_argument("--preparation-time-namespace")
        else:
            current.add_argument("--prepared",required=True,type=Path)
            current.add_argument("--prepared-size-bytes",required=True,type=int)
            current.add_argument("--prepared-sha256",required=True)
    args=parser.parse_args(argv)
    require(os.name=="posix","finite study requires existing POSIX production route")
    result={"prepare":prepare,"run":run,"study":study}[args.operation](args)
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
