"""Once-only packaged GI decoder research. Never imported by publication code."""
import argparse
from collections import Counter
import hashlib
import os
from pathlib import Path
import queue
import select
import shutil
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_protocol import (AdmissionGate, CHANNEL_MAX, COUNT, EVENT_MAX, Evidence,
    LineReader, METADATA_MAX, MISSING, PAYLOAD_MAX, Pin, RAW_MAX, ResearchError, canonical,
    compare_outputs, decoder_timings, active_rgb_digest, owner, physical_descriptor, read_line,
    post_receipt_deadline, require, strict_object, verify_seal)

FIXED_ORDER = [('front_gate', 'default'), ('front_gate', 'zero'),
    ('underbody', 'zero'), ('underbody', 'default')]
PIPELINE = ('appsrc name=source is-live=true format=time do-timestamp=false block=true '
    'max-buffers=1 max-bytes=0 max-time=0 leaky-type=none '
    'caps="video/x-h264,stream-format=byte-stream,alignment=au" ! h264parse ! '
    'video/x-h264,stream-format=byte-stream,alignment=au ! identity name=ingress ! '
    'nvh264dec name=decoder ! videoconvert ! video/x-raw,format=RGB ! '
    'appsink name=output sync=false async=false drop=false max-buffers=1 emit-signals=false')


def memory_facts(buffer):
    rows = []
    require(buffer.n_memory() <= 32, 'buffer memory count cap')
    for i in range(buffer.n_memory()):
        memory = buffer.peek_memory(i)
        rows.append({'system_memory': bool(memory.is_type('SystemMemory')),
            'cuda_memory': bool(memory.is_type('CUDAMemory'))})
    return rows


def caps_facts(caps):
    require(caps is not None and caps.get_size() <= 8, 'caps absent or excessively large')
    text = caps.to_string()
    features = [caps.get_features(i).to_string() for i in range(caps.get_size())]
    require(len(text.encode()) <= 4096 and sum(len(x.encode()) for x in features) <= 4096,
        'caps byte cap')
    return {'caps': text, 'caps_features': features}


class Guest:
    def __init__(self, plan_path, output):
        self.begun = time.monotonic()
        self.overall_deadline = self.begun + 600
        self.phase_deadline = self.begun + 120
        self.plan_pin = Pin(plan_path, maximum=METADATA_MAX, deadline=self.phase_deadline)
        self.plan = verify_seal(strict_object(os.pread(self.plan_pin.fd, METADATA_MAX, 0), METADATA_MAX))
        require(self.plan['artifact_kind'] == 'vast_decoder_research_plan_v1' and
            self.plan['planning_commit'] == 'b1ad01c09b4e21f542f971b9dc794548245719b0', 'unreviewed research plan')
        require(self.plan['fixed_order'] == [list(x) for x in FIXED_ORDER], 'fixed four-run order differs')
        require(type(self.plan['guest_prelaunch_budget_s']) in (float,int) and
            0 < self.plan['guest_prelaunch_budget_s'] <= 120, 'guest shared-prelaunch budget invalid')
        self.phase_deadline = self.begun + self.plan['guest_prelaunch_budget_s']
        self.output = Path(output)
        require(self.output.is_dir() and not list(self.output.iterdir()), 'guest output is not fresh')
        self.metadata = Evidence(self.output / 'metadata', METADATA_MAX // 2)
        self.active_source = None
        self.active_abort = None
        self.pins = [self.plan_pin]
        self.packages = {}
        self.media = {}
        self.runs = []
        self.Gst = self.GstVideo = None

    def pin(self, path, expected=None):
        resolved = str(Path(path).resolve(strict=True))
        if resolved not in self.packages:
            pin = Pin(resolved, expected, deadline=self.phase_deadline)
            self.pins.append(pin)
            self.packages[resolved] = pin
        elif expected is not None:
            require(self.packages[resolved].descriptor['sha256'] == expected['sha256'], 'pin expected SHA differs')
        return self.packages[resolved]

    def loaded_pins(self):
        paths = set()
        for line in Path('/proc/self/maps').read_text().splitlines():
            fields = line.split()
            if len(fields) >= 6 and fields[-1].startswith('/') and any(s in fields[-1]
                    for s in ('libgst', 'libglib', 'libgobject', 'libgirepository', '_gi.',
                        'libcuda', 'libnvcuvid', 'libnvidia')):
                paths.add(fields[-1])
        for path in sorted(paths):
            self.pin(path)
        return [self.packages[path].descriptor for path in sorted(self.packages)]

    def drain(self, fd, evidence, name, aborted, failure):
        try:
            while True:
                require(not aborted.is_set() and time.monotonic() < self.overall_deadline,
                    'original log pipe deadline/abort')
                if not select.select([fd], [], [], 0.1)[0]:
                    continue
                block = os.read(fd, 65536)
                if not block:
                    break
                evidence.append(name, block)
        except BaseException as exc:
            failure(exc)
        finally:
            os.close(fd)

    def preflight(self):
        deadline = min(self.phase_deadline, self.overall_deadline)
        source_expected = self.plan['source_binary']
        self.source_pin = self.pin('/usr/local/bin/vast_checkpoint_source', source_expected)
        self.pin('/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0/libgstnvcodec.so', self.plan['nvcodec_plugin'])
        for clip in self.plan['sources']:
            pin = self.pin('/opt/vast/media/' + clip['role'] + '.mp4', clip['media'])
            self.media[clip['role']] = pin
            require(time.monotonic() < deadline, 'prelaunch full-media pin deadline')
        # Same fresh GPU-aware registry procedure as stock; no frozen CPU registry substitute.
        self.registry = Path('/tmp/decoder-research-registry.bin')
        require(not self.registry.exists(), 'research registry already exists')
        environment = os.environ.copy()
        environment['GST_REGISTRY'] = str(self.registry)
        environment.pop('GST_REGISTRY_UPDATE', None)
        inspect_pin = self.pin(shutil.which('gst-inspect-1.0'))
        out = self.metadata.open('registry.stdout', CHANNEL_MAX)
        err = self.metadata.open('registry.stderr', CHANNEL_MAX)
        abort = threading.Event()
        failures = []
        def failure(exc):
            failures.append(str(exc)); abort.set()
        process = subprocess.Popen([str(inspect_pin.path), 'nvh264dec'],
            executable=f'/proc/self/fd/{inspect_pin.fd}', pass_fds=(inspect_pin.fd,),
            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        threads = []
        try:
            self.metadata.event('registry_process_started', child=owner(process.pid),
                controller=owner(os.getpid()), argv=[str(inspect_pin.path), 'nvh264dec'])
            for stream, name in ((process.stdout, out), (process.stderr, err)):
                fd = os.dup(stream.fileno())
                thread = threading.Thread(target=self.drain, args=(fd, self.metadata, name, abort, failure), daemon=True)
                thread.start(); threads.append(thread)
            while process.poll() is None:
                require(not abort.is_set() and time.monotonic() < min(deadline, self.begun + 60),
                    'registry refresh failure/deadline')
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            try:
                process.wait(timeout=5)
            finally:
                for stream in (process.stdout, process.stderr):
                    stream.close()
                for thread in threads:
                    thread.join(timeout=2)
        self.metadata.event('registry_process_terminal', returncode=process.returncode, failures=failures)
        require(process.returncode == 0 and not failures and all(not t.is_alive() for t in threads),
            'original registry refresh did not complete')
        require(self.registry.is_file() and self.registry.stat().st_size <= 16 * 1024 * 1024,
            'registry absent/oversized')
        self.pin(self.registry)
        os.environ['GST_REGISTRY'] = str(self.registry)
        os.environ['GST_REGISTRY_UPDATE'] = 'no'
        import gi
        gi.require_version('Gst', '1.0'); gi.require_version('GstApp', '1.0'); gi.require_version('GstVideo', '1.0')
        from gi.repository import Gst, GstApp, GstVideo
        Gst.init(None)
        require(list(Gst.version()) == [1, 28, 2, 0] and gi.__version__ == '3.50.0', 'actual packaged GI/Gst version differs')
        self.Gst, self.GstVideo = Gst, GstVideo
        self.pin(gi.__file__)
        import gi._gi
        self.pin(gi._gi.__file__)
        for namespace in ('Gst', 'GstApp', 'GstVideo'):
            self.pin('/opt/intel/dlstreamer/gstreamer/lib/girepository-1.0/' + namespace + '-1.0.typelib')
        for module in tuple(sys.modules.values()):
            path = getattr(module, '__file__', None)
            if path and '/gi/overrides/' in path:
                self.pin(path)
        factory = Gst.ElementFactory.find('nvh264dec')
        require(factory is not None, 'original reviewed decoder unavailable')
        plugin = factory.get_plugin()
        require(plugin.get_version() == '1.28.2' and Path(plugin.get_filename()).resolve() ==
            Path(self.plan['nvcodec_plugin']['path']), 'actual decoder plugin differs')
        self.loaded_pins()
        self.metadata.document('prelaunch.v1.json', {'artifact_kind': 'vast_decoder_research_guest_prelaunch_v1',
            'plan': self.plan_pin.descriptor, 'controller': owner(os.getpid()), 'gi_version': gi.__version__,
            'gst_version': list(Gst.version()), 'plugin_path': plugin.get_filename(), 'packages': self.loaded_pins(),
            'media': {key: pin.descriptor for key, pin in self.media.items()},
            'elapsed_s': time.monotonic() - self.begun, 'accepted': False, 'publication_ready': False})
        require(time.monotonic() < deadline, 'prelaunch deadline exceeded')

    def run(self, index, clip, setting):
        Gst, GstVideo = self.Gst, self.GstVideo
        run_start = time.monotonic()
        deadline = min(run_start + 120, self.overall_deadline)
        startup_deadline = min(run_start + 45, deadline - 15)
        self.phase_deadline = startup_deadline
        evidence = Evidence(self.output / f'run-{index:02d}-{clip["role"]}-{setting}')
        abort = threading.Event()
        self.active_abort = abort
        errors = []
        gate = None
        pipeline = None
        process = None
        threads = []
        fds = []
        media_pin = self.media[clip['role']]
        outputs, entries, exits = [], {}, {}
        eos_sink = []
        feeder_done = threading.Event()
        binary_done = threading.Event()
        source_eof = []
        status_ready = threading.Event()
        statuses = []
        packets = queue.Queue(maxsize=COUNT)
        command_lock = threading.RLock()
        def failure(exc):
            with command_lock:
                errors.append(str(exc)); abort.set()
                if gate is not None:
                    gate.fail(exc)
        def thread_call(function):
            try:
                function()
            except BaseException as exc:
                failure(exc)
        def spawn(function):
            thread = threading.Thread(target=thread_call, args=(function,), daemon=True)
            thread.start(); threads.append(thread)
        try:
            evidence.document('run-started.v1.json', {'artifact_kind': 'vast_decoder_research_run_started_v1',
                'run': index, 'clip': clip['role'], 'setting': setting,
                'started_monotonic_ns': int(run_start*1_000_000_000), 'started_realtime_ns': time.time_ns(),
                'guest_elapsed_at_start_s':run_start-self.begun,
                'controller': owner(os.getpid()), 'accepted': False})
            pipeline = Gst.parse_launch(PIPELINE)
            appsrc, decoder, appsink = [pipeline.get_by_name(name) for name in ('source', 'decoder', 'output')]
            prop = decoder.find_property('max-display-delay')
            require(prop is not None and prop.minimum == -1 and prop.maximum == 16 and int(prop.flags)&3 == 3,
                'reviewed writable decoder property range differs')
            default = decoder.get_property('max-display-delay')
            if setting == 'zero':
                decoder.set_property('max-display-delay', 0)
                require(decoder.get_property('max-display-delay') == 0, 'zero decoder property readback differs')
            evidence.event('pipeline_created', text=PIPELINE, setting=setting,
                property_default_readback=default, property_readback=decoder.get_property('max-display-delay'),
                default_was_unset=setting == 'default', packages=self.loaded_pins())
            def probe(pad, info, phase):
                observed = time.monotonic_ns()
                try:
                    if info.type & Gst.PadProbeType.BUFFER:
                        buffer = info.get_buffer()
                        require(buffer is not None and buffer.pts != Gst.CLOCK_TIME_NONE, 'decoder probe missing PTS')
                        pts = int(buffer.pts)
                        facts = caps_facts(pad.get_current_caps())
                        target = entries if phase == 'sink' else exits
                        require(pts not in target and len(target) < COUNT, 'duplicate/extra decoder probe PTS')
                        target[pts] = observed
                        evidence.event('decoder_' + phase, observed, pts=pts, dts=int(buffer.dts),
                            duration=int(buffer.duration), memory=memory_facts(buffer), **facts)
                    elif info.type & Gst.PadProbeType.EVENT_DOWNSTREAM:
                        event = info.get_event()
                        if event.type == Gst.EventType.EOS:
                            if phase == 'sink':
                                require(not eos_sink, 'duplicate actual decoder-sink EOS')
                                eos_sink.append(observed)
                            evidence.event('decoder_' + phase + '_eos_observed', observed)
                        elif event.type == Gst.EventType.CAPS:
                            evidence.event('decoder_' + phase + '_caps', observed, **caps_facts(event.parse_caps()))
                except BaseException as exc:
                    failure(exc)
                return Gst.PadProbeReturn.OK
            for phase in ('sink', 'src'):
                decoder.get_static_pad(phase).add_probe(Gst.PadProbeType.BUFFER |
                    Gst.PadProbeType.EVENT_DOWNSTREAM, probe, phase)
            require(pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE,
                'decoder pipeline failed PLAYING')
            bus = pipeline.get_bus()
            media_pin.verify()
            registry_copy = Path('/tmp') / f'decoder-research-source-{index}.registry.bin'
            require(not registry_copy.exists(), 'source registry copy already exists')
            shutil.copyfile(self.registry, registry_copy)
            require(physical_descriptor(registry_copy)['sha256'] == self.packages[str(self.registry)].descriptor['sha256'],
                'source registry copy mismatch')
            self.pin(registry_copy)
            run_id = f'research-decoder-{index:02d}'
            worker_id = f'research-source-{clip["role"]}-{index:02d}'
            ad_r, ad_w = os.pipe(); ack_r, ack_w = os.pipe(); ctl_r, ctl_w = os.pipe()
            st_r, st_w = os.pipe(); au_r, au_w = os.pipe()
            fds.extend((ad_r, ad_w, ack_r, ack_w, ctl_r, ctl_w, st_r, st_w, au_r, au_w))
            source = clip['stock_source_parameters']
            argv = [str(self.source_pin.path), '--source-path', f'/proc/self/fd/{media_pin.fd}',
                '--dataset-id', clip['dataset_id'], '--source-sha256', source['source_sha256'],
                '--checkpoint-container', source['source_container'], '--checkpoint-codec', source['source_codec'],
                '--source-duration-ns', str(source['source_duration_ns']), '--playback-timestamp-scale', '600',
                '--source-replay', 'continuous', '--logical-stream-id', str(clip['stream_id'])]
            environment = os.environ.copy()
            environment.update(GST_REGISTRY=str(registry_copy), GST_REGISTRY_UPDATE='no',
                VAST_CHECKPOINT_WORKER_ID=worker_id, VAST_CHECKPOINT_RUN_ID=run_id,
                VAST_CHECKPOINT_ADMISSION_EVENT_FD=str(ad_w), VAST_CHECKPOINT_ADMISSION_ACK_FD=str(ack_r),
                VAST_CHECKPOINT_CONTROL_FD=str(ctl_r), VAST_CHECKPOINT_STATUS_FD=str(st_w),
                VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON=canonical({'research-decoder': au_w}).decode(),
                VAST_CHECKPOINT_DATASET_ID=clip['dataset_id'], VAST_CHECKPOINT_SOURCE_SHA256=source['source_sha256'],
                VAST_CHECKPOINT_STREAM_ID=str(clip['stream_id']),
                VAST_CHECKPOINT_SOURCE_CONTAINER=source['source_container'], VAST_CHECKPOINT_SOURCE_CODEC=source['source_codec'],
                VAST_CHECKPOINT_SOURCE_DURATION_NS=str(source['source_duration_ns']),
                VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE='600', VAST_CHECKPOINT_SOURCE_REPLAY='continuous',
                VAST_CHECKPOINT_ADMISSION_MODE='native_common_source_coordinator')
            raw_ad = evidence.open('source-admission.raw', CHANNEL_MAX)
            raw_st = evidence.open('source-status.raw', CHANNEL_MAX)
            raw_ack = evidence.open('source-ack.raw', CHANNEL_MAX)
            raw_ctl = evidence.open('source-control.raw', CHANNEL_MAX)
            raw_au = evidence.open('source-transport.raw', RAW_MAX)
            stdout = evidence.open('source.stdout', CHANNEL_MAX)
            stderr = evidence.open('source.stderr', CHANNEL_MAX)
            process = subprocess.Popen(argv, executable=f'/proc/self/fd/{self.source_pin.fd}',
                env=environment, pass_fds=(ad_w, ack_r, ctl_r, st_w, au_w, media_pin.fd, self.source_pin.fd),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            self.active_source = process
            evidence.event('source_process_started', child=owner(process.pid), controller=owner(os.getpid()),
                argv=argv, source_binary=self.source_pin.descriptor, media=media_pin.descriptor,
                environment={key: value for key, value in environment.items() if key.startswith('VAST_CHECKPOINT_') or key.startswith('GST_REGISTRY')})
            for fd in (ad_w, ack_r, ctl_r, st_w, au_w):
                os.close(fd); fds.remove(fd)
            for stream, name in ((process.stdout, stdout), (process.stderr, stderr)):
                fd = os.dup(stream.fileno())
                spawn(lambda fd=fd, name=name: self.drain(fd, evidence, name, abort, failure))
            def status_reader():
                reader=LineReader(st_r,deadline-15,abort,lambda block:evidence.append(raw_st,block),
                    capacity=lambda:evidence.files[raw_st][1]-evidence.files[raw_st][0])
                while raw := reader.read():
                    parts = raw.decode('ascii').strip().split()
                    require(len(parts) == 4 and parts[0] == '1' and parts[2] == worker_id,
                        'source status identity/shape differs')
                    require(parts[1] in ('READY', 'STARTED', 'ADMISSION_STOPPED', 'DRAINED', 'CENSORED'),
                        'unknown source status')
                    value = int(parts[3])
                    statuses.append(parts[1])
                    evidence.event('source_status', status=parts[1], original_timestamp=value)
                    if parts[1] == 'READY':
                        status_ready.set()
            spawn(status_reader)
            while not status_ready.wait(0.05):
                require(not abort.is_set() and process.poll() is None and time.monotonic() < startup_deadline,
                    'source READY startup failure/deadline')
            require(time.monotonic() < startup_deadline, 'source READY arrived beyond45s startup')
            source_libraries = []
            maps_raw = Path(f'/proc/{process.pid}/maps').read_bytes()
            require(len(maps_raw) <= CHANNEL_MAX, 'source process maps cap')
            for line in maps_raw.decode().splitlines():
                fields = line.split()
                if len(fields) >= 6 and fields[-1].startswith('/') and any(s in fields[-1]
                        for s in ('libgst', 'libglib', 'libgobject')):
                    source_libraries.append(self.pin(fields[-1]).descriptor)
            evidence.event('actual_source_loaded_libraries', libraries=source_libraries)
            mono = time.monotonic_ns()
            realtime = time.time_ns()
            future_mono = mono + 2_000_000_000
            wall_start = (realtime + 2_000_000_000) // 1_000_000
            wall_end = wall_start + 31500
            contract = {'source_process_id': worker_id, 'run_id': run_id, 'dataset_id': clip['dataset_id'],
                'stream_id': clip['stream_id'], 'source_sha256': source['source_sha256'],
                'source_duration_ns': source['source_duration_ns'], 'window_start_ms': wall_start, 'window_end_ms': wall_end}
            gate = AdmissionGate(contract)
            def send(fd, raw, name, kind):
                with command_lock:
                    require(not abort.is_set(), 'command blocked by original failure')
                    evidence.event(kind + '_intent', raw_ascii=raw.decode('ascii'))
                    require(os.write(fd, raw) == len(raw), 'source command partial write')
                    observed = time.monotonic_ns()
                    evidence.append(name, raw, sync=True)
                    evidence.event(kind + '_sent', observed, raw_ascii=raw.decode('ascii'))
            def admissions():
                reader=LineReader(ad_r,deadline-15,abort,lambda block:evidence.append(raw_ad,block),
                    capacity=lambda:evidence.files[raw_ad][1]-evidence.files[raw_ad][0])
                while raw := reader.read():
                    os.fsync(evidence.streams[raw_ad])
                    event = strict_object(raw)
                    gate.declare(event, deadline - 15, abort)
                    evidence.event('admission_declaration', original=event)
                    send(ack_w, f'1 ACK {event["sequence"]}\n'.encode(), raw_ack, 'ack')
                    if event['sequence'] == COUNT:
                        send(ctl_w, f'1 STOP {wall_end}\n'.encode(), raw_ctl, 'stop')
            def binary_reader():
                while True:
                    packet = gate.receive(au_r, deadline - 15, abort, evidence, raw_au)
                    if packet is None:
                        eof_observed = time.monotonic_ns()
                        source_eof.append(time.monotonic())
                        evidence.event('source_transport_eof',eof_observed)
                        evidence.document('source-transport-eof.v1.json', {
                            'artifact_kind':'vast_decoder_research_source_transport_eof_v1', 'run':index,
                            'observed_monotonic_ns':eof_observed,
                            'guest_elapsed_at_eof_s':source_eof[0]-self.begun,'accepted':False})
                        break
                    observed = time.monotonic_ns()
                    evidence.event('transport_validated', observed,
                        **{key: value for key, value in packet.items() if key != 'payload'})
                    packets.put_nowait(packet)
                    gate.mark_validated(packet)  # Unlock ACK(n+1) before any blocking decoder call.
                require(len(gate.validated) == len(gate.declared) == COUNT, 'source EOF lacks exact32 original packets')
                binary_done.set()
            def feeder():
                while True:
                    require(not abort.is_set() and time.monotonic() < deadline - 15, 'feeder deadline/failure')
                    try:
                        packet = packets.get(timeout=0.1)
                    except queue.Empty:
                        if binary_done.is_set():
                            break
                        continue
                    buffer = Gst.Buffer.new_allocate(None, packet['payload_size_bytes'], None)
                    require(buffer is not None, 'appsrc buffer allocation failed')
                    require(buffer.fill(0, packet['payload']) == packet['payload_size_bytes'], 'appsrc payload copy failed')
                    buffer.pts = packet['transport_pts_ns']
                    buffer.dts = Gst.CLOCK_TIME_NONE if packet['access_unit_dts_ns'] == MISSING else packet['access_unit_dts_ns']
                    buffer.duration = packet['duration_ns']
                    if not packet['keyframe']:
                        buffer.set_flags(Gst.BufferFlags.DELTA_UNIT)
                    observed = time.monotonic_ns()
                    flow = appsrc.emit('push-buffer', buffer)
                    after = time.monotonic_ns()
                    require(flow == Gst.FlowReturn.OK, 'appsrc rejected original packet')
                    evidence.event('appsrc_submission', observed, sequence=packet['sequence'], pts=int(buffer.pts),
                        push_return_monotonic_ns=after, blocking_ns=after-observed, fifo_depth=packets.qsize())
                eos_requested = time.monotonic_ns()
                require(appsrc.emit('end-of-stream') == Gst.FlowReturn.OK, 'appsrc EOS rejected')
                evidence.event('appsrc_eos_requested', eos_requested,
                    limitation='request is not actual decoder-sink EOS observation')
                feeder_done.set()
            def rgb_reader():
                while not abort.is_set():
                    sample = appsink.emit('try-pull-sample', 100_000_000)
                    if sample is None:
                        if appsink.is_eos():
                            return
                        require(time.monotonic() < deadline - 15, 'RGB reader deadline')
                        continue
                    hold_start = time.monotonic_ns()
                    caps = sample.get_caps()
                    facts = caps_facts(caps)
                    structure = caps.get_structure(0)
                    width = structure.get_value('width'); height = structure.get_value('height')
                    fmt = structure.get_string('format')
                    require(fmt == 'RGB' and width == clip['encoded_geometry']['width'] and
                        height == clip['encoded_geometry']['height'], 'actual RGB caps/geometry differ')
                    buffer = sample.get_buffer()
                    require(buffer.get_size() <= PAYLOAD_MAX and buffer.pts != Gst.CLOCK_TIME_NONE, 'RGB size/PTS cap')
                    video = GstVideo.VideoInfo.new_from_caps(caps)
                    require(video is not None and video.finfo.format == GstVideo.VideoFormat.RGB,
                        'negotiated RGB VideoInfo unavailable')
                    meta = GstVideo.buffer_get_video_meta(buffer)
                    if meta is not None:
                        require(meta.n_planes == 1 and meta.width == width and meta.height == height and
                            meta.format == GstVideo.VideoFormat.RGB,
                            'actual RGB VideoMeta differs')
                        stride, offset = int(meta.stride[0]), int(meta.offset[0])
                    else:
                        stride, offset = int(video.stride[0]), int(video.offset[0])
                    mapped, info = buffer.map(Gst.MapFlags.READ)
                    require(mapped, 'RGB map failed')
                    try:
                        digest = active_rgb_digest(info.data, width, height, stride, offset)
                    finally:
                        buffer.unmap(info)
                        info = None
                    output_pts = int(buffer.pts)
                    sample = buffer = meta = None
                    hold_end = time.monotonic_ns()
                    row = {'pts': output_pts, 'width': width, 'height': height, 'format': fmt,
                        'stride': stride, 'offset': offset, 'pixel_sha256': digest,
                        'sample_hold_start_ns': hold_start, 'sample_hold_end_ns': hold_end,
                        'hold_hash_ns': hold_end-hold_start, 'output_ordinal': len(outputs)+1, **facts}
                    require(len(outputs) < COUNT and row['pts'] not in {r['pts'] for r in outputs},
                        'duplicate/extra RGB output')
                    outputs.append(row)
                    evidence.event('rgb_output', hold_start, **row)
            spawn(admissions); spawn(binary_reader); spawn(feeder); spawn(rgb_reader)
            require(time.monotonic() < startup_deadline, 'startup source/library pins exceeded45s before START')
            send(ctl_w, f'1 START {future_mono} {wall_start} {wall_end} {wall_end+10000}\n'.encode(), raw_ctl, 'start')
            require(time.monotonic() < startup_deadline, 'original START completed beyond45s startup')
            evidence.document('startup-completed.v1.json', {'artifact_kind': 'vast_decoder_research_startup_v1',
                'run': index, 'elapsed_s': time.monotonic()-run_start, 'accepted': False})
            self.phase_deadline = deadline-15
            evidence.event('clock_domains', guest_monotonic_ns=mono, guest_realtime_ns=realtime,
                source_admission_quantization_ns=1_000_000, primary='decoder sink/src monotonic only',
                secondary_admission_to_output_omitted=True)
            eos_deadline = None
            bus_eos = False
            while not bus_eos:
                require(not abort.is_set() and time.monotonic() < deadline - 15, 'original run failure/deadline')
                if source_eof and eos_deadline is None:
                    eos_deadline = min(source_eof[0]+10, deadline-15)
                if eos_deadline is not None:
                    require(time.monotonic() < eos_deadline, 'decoder EOS/drain deadline')
                message = bus.timed_pop_filtered(100_000_000, Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if message is None:
                    continue
                if message.type == Gst.MessageType.ERROR:
                    error, debug = message.parse_error()
                    raise ResearchError('actual decoder bus error: ' + str(error) + ' ' + str(debug)[:1024])
                bus_eos = True
                evidence.event('pipeline_bus_eos')
            for thread in threads:
                thread.join(timeout=max(0, min(2, deadline-15-time.monotonic())))
            require(all(not t.is_alive() for t in threads), 'original readers/feeder did not complete')
            require(process.wait(timeout=max(0.01,min(2,deadline-15-time.monotonic()))) == 0,
                'original source returned failure')
            require(not errors and binary_done.is_set() and feeder_done.is_set() and
                statuses == ['READY','STARTED','ADMISSION_STOPPED','DRAINED'], 'original source lifecycle incomplete')
            expected_pts = [gate.validated[i]['transport_pts_ns'] for i in range(1,COUNT+1)]
            require(len(set(expected_pts)) == COUNT and Counter(entries.keys()) == Counter(expected_pts) and
                Counter(exits.keys()) == Counter(expected_pts), 'decoder input/output PTS multiset differs')
            require(len(outputs) == COUNT and Counter(row['pts'] for row in outputs) == Counter(expected_pts),
                'RGB complete PTS multiset differs')
            require(len(eos_sink) == 1, 'actual decoder sink EOS absent')
            require(source_eof and time.monotonic()-source_eof[0]<=10,'complete sourceEOF/feeder/decoder drain exceeded10s')
            evidence.document('decoder-drain-completed.v1.json', {
                'artifact_kind':'vast_decoder_research_decoder_drain_v1','run':index,
                'source_eof_monotonic_ns':int(source_eof[0]*1_000_000_000),
                'completed_monotonic_ns':time.monotonic_ns(), 'actual_decoder_sink_eos_ns':eos_sink[0],
                'elapsed_from_source_eof_s':time.monotonic()-source_eof[0],'accepted':False})
            timings = decoder_timings(entries,exits,[gate.validated[i] for i in range(1,COUNT+1)],eos_sink)
            result = {'clip': clip['role'], 'setting': setting, 'outputs': outputs, 'timings': timings,
                'packets': [gate.validated[i] for i in range(1,COUNT+1)],
                'input_pts_decode_order': expected_pts, 'actual_decoder_sink_eos_ns': eos_sink[0],
                'central_steady_state_sufficient': all(not row['after_actual_decoder_sink_eos']
                    for row in timings if row['cohort']=='central'), 'actual_admissions': len(gate.declared),
                'actual_packets': len(gate.validated), 'raw_bytes': gate.reserved_raw_bytes,
                'maximum_actual_au_payload_bytes': max(row['payload_size_bytes'] for row in gate.validated.values()),
                'pipeline': PIPELINE, 'property_default_readback': default,
                'property_readback': decoder.get_property('max-display-delay')}
            result_desc = evidence.document('observations.v1.json', dict(result,
                artifact_kind='vast_decoder_research_observations_v1', accepted=False, publication_ready=False))
        except BaseException as exc:
            failure(exc)
            result = None
            result_desc = None
        finally:
            cleanup_start = time.monotonic()
            self.phase_deadline = min(deadline,cleanup_start+15)
            abort.set()
            if gate is not None:
                gate.fail('original run cleanup')
            cleanup_errors = []
            # Signal exact owned source before a potentially blocking GI state transition.
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                except BaseException as exc:
                    cleanup_errors.append(str(exc))
            if process is not None:
                try:
                    process.wait(timeout=max(0.01, 5-(time.monotonic()-cleanup_start)))
                except BaseException as exc:
                    cleanup_errors.append(str(exc))
            if pipeline is not None:
                # Outer exact-CID120s owner also bounds an unreturning library state call.
                try:
                    require(pipeline.set_state(Gst.State.NULL) != Gst.StateChangeReturn.FAILURE,
                        'original pipeline cleanup state failure')
                except BaseException as exc:
                    cleanup_errors.append(str(exc))
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            for stream in (() if process is None else (process.stdout, process.stderr)):
                stream.close()
            for thread in threads:
                thread.join(timeout=max(0, min(1, 15-(time.monotonic()-cleanup_start))))
            if any(t.is_alive() for t in threads):
                cleanup_errors.append('original thread remained alive')
            self.active_source = self.active_abort = None
            try:
                media_pin.deadline=self.phase_deadline
                media_pin.verify(rehash=True)
                self.loaded_pins()
                for pin in self.pins:
                    pin.verify()
            except BaseException as exc:
                cleanup_errors.append(str(exc))
            try:
                evidence.close()  # Raw logs/packets must finish before the receipt-last seal.
            except BaseException as exc:
                cleanup_errors.append(str(exc))
            if time.monotonic()-cleanup_start > 15:
                cleanup_errors.append('owned cleanup15s exceeded including final input pinning')
            leaves=[]
            try:
                for path in sorted(evidence.directory.iterdir()):
                    pin=Pin(path,maximum=RAW_MAX,deadline=self.phase_deadline)
                    try:leaves.append(pin.descriptor)
                    finally:pin.close()
            except BaseException as exc:
                cleanup_errors.append('closed original leaf hashing: '+str(exc))
            if time.monotonic()-cleanup_start > 15:
                cleanup_errors.append('owned cleanup15s exceeded including raw-leaf seals')
            successful = result is not None and not errors and not cleanup_errors and time.monotonic() <= deadline
            terminal = evidence.document('terminal.v1.json', {'artifact_kind': 'vast_decoder_research_run_terminal_v1',
                'run': index, 'clip': clip['role'], 'setting': setting, 'controller': owner(os.getpid()),
                'source_returncode': None if process is None else process.returncode, 'errors': errors,
                'cleanup_errors': cleanup_errors, 'run_successful': successful, 'observations': result_desc,
                'closed_original_leaves':leaves,
                'elapsed_s': time.monotonic()-run_start, 'package_pin_count': len(self.packages),
                'accepted': False, 'publication_ready': False, 'native_pair_count': 0,
                'model_or_parity_evidence': False, 'benchmark_arm_count': 0}, final=True)
            evidence.close()
            within_deadline,_=post_receipt_deadline(evidence,terminal,run_start,deadline,'run',cleanup_start+15)
            successful=successful and within_deadline
        require(successful, 'original research run failed; no retry or subsequent setting allowed')
        self.runs.append({'terminal': terminal, 'observations': result_desc})
        return result

    def execute(self):
        result = None
        failure = None
        try:
            self.preflight()
            completed = []
            by_role = {source['role']: source for source in self.plan['sources']}
            for index, (role, setting) in enumerate(FIXED_ORDER, 1):
                completed.append(self.run(index, by_role[role], setting))
            for left, right in ((completed[0],completed[1]), (completed[2],completed[3])):
                require(left['input_pts_decode_order'] == right['input_pts_decode_order'], 'paired source prefix differs')
                require(left['packets'] == right['packets'], 'paired original AU bytes/transport fields differ')
                compare_outputs(left['outputs'], right['outputs'], left['input_pts_decode_order'])
            for pin in self.pins:
                pin.deadline=self.overall_deadline-1
                pin.verify(rehash=True)
            package_receipt = self.metadata.document('final-package-pins.v1.json', {
                'artifact_kind':'vast_decoder_research_final_package_pins_v1',
                'pins':[pin.descriptor for pin in self.pins], 'all_before_after_verified':True,
                'accepted':False,'publication_ready':False})
            require(time.monotonic() < self.overall_deadline, 'whole guest600s deadline exceeded')
            paired = [{'clip': completed[a]['clip'], 'sequence': i+1,
                'default_residence_ns': completed[a]['timings'][i]['residence_ns'],
                'zero_residence_ns': completed[b]['timings'][i]['residence_ns'],
                'zero_minus_default_ns': completed[b]['timings'][i]['residence_ns']-completed[a]['timings'][i]['residence_ns'],
                'cohort': completed[a]['timings'][i]['cohort'],
                'steady_state_pair': not (completed[a]['timings'][i]['after_actual_decoder_sink_eos'] or
                    completed[b]['timings'][i]['after_actual_decoder_sink_eos'])}
                for a,b in ((0,1),(3,2)) for i in range(COUNT)]
            paired_receipt = self.metadata.document('paired-timing.v1.json', {
                'artifact_kind':'vast_decoder_research_paired_timing_v1','observations':paired,
                'accepted':False,'publication_ready':False})
            result = {'research_correctness_preserved': True, 'runs': self.runs, 'final_package_pins':package_receipt,
                'central_steady_state_sufficient_by_run': [run['central_steady_state_sufficient'] for run in completed],
                'paired_timings': paired_receipt,
                'limitations': ['sink/src wall residence is not decoder utilization',
                    'hashing and one-buffer queues can add backpressure',
                    'source realtime ms and planned offsets are not subtracted from decoder monotonic ns',
                    'four fixed prefixes do not establish six-stream100ms feasibility or model throughput']}
        except BaseException as exc:
            failure = str(exc)
        finally:
            try:
                if time.monotonic()>=self.overall_deadline-1:
                    result=None
                    if failure is None:failure='original guest finalization reserve exhausted'
                receipt = self.metadata.document('research-terminal.v1.json', {
                    'artifact_kind': 'vast_decoder_research_guest_terminal_v1', 'plan': self.plan_pin.descriptor,
                    'result': result, 'failure': failure, 'runs_completed': len(self.runs),
                    'elapsed_s': time.monotonic()-self.begun, 'accepted': False, 'publication_ready': False,
                    'benchmark_arm_count': 0, 'native_pair_count': 0, 'qualification_count': 0,
                    'model_or_parity_evidence': False}, final=True)
            finally:
                self.metadata.close()
                for pin in reversed(self.pins):
                    pin.close()
            within_deadline,late_receipt=post_receipt_deadline(
                self.metadata,receipt,self.begun,self.overall_deadline,'guest')
            if not within_deadline:result=None
            print(canonical({'receipt': receipt, 'successful': result is not None,
                'receipt_time_limit_failure':late_receipt}).decode(), flush=True)
        return 0 if result is not None else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    guest = Guest(args.plan, args.output_dir)
    def interrupted(signum, frame):
        if guest.active_abort is not None:
            guest.active_abort.set()
        raise ResearchError('original guest interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    return guest.execute()


if __name__ == '__main__':
    sys.exit(main())
