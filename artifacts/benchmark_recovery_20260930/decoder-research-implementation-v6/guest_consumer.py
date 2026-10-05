"""Once-only packaged GI decoder research. Never imported by publication code."""
import argparse
from collections import Counter
import hashlib
import math
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
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_protocol import (AdmissionGate, CHANNEL_MAX, COUNT, EVENT_MAX, Evidence,
    LineReader, METADATA_MAX, MISSING, PAYLOAD_MAX, Pin, RAW_MAX, ResearchError, canonical,
    compare_outputs, decoder_timings, active_rgb_digest, owner, physical_descriptor, read_line,
    post_receipt_deadline, require, seal, strict_object, verify_seal)
from research_protocol import read_process_maps, mapped_library_rows, parse_process_maps, verify_mapped_file, _pin_stat, buffer_abi

PLANNING_COMMIT = '3aa35c3b2eedc05d22cf16ba37d470143d080f6b'

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
    def __init__(self, plan_path, output, mode):
        self.begun = time.monotonic()
        self.overall_deadline = self.begun + 600
        self.phase_deadline = self.begun + 120
        self.mode = mode
        self.pins = []
        try:
            require(mode in ('metadata-only', 'research'), 'explicit guest mode required')
            self.plan_pin = Pin(plan_path, maximum=METADATA_MAX, deadline=self.phase_deadline)
            self.pins.append(self.plan_pin)
            self.plan = verify_seal(strict_object(os.pread(self.plan_pin.fd, METADATA_MAX, 0), METADATA_MAX))
            require(self.plan['artifact_kind'] == 'vast_decoder_research_plan_v1' and
                self.plan['planning_commit'] == PLANNING_COMMIT, 'unreviewed research plan')
            require(self.plan['mode'] == mode, 'guest sealed mode differs')
            for key in ('source_commit', 'current_checkout_commit'):
                require(type(self.plan[key]) is str and len(self.plan[key]) == 40 and
                    all(x in '0123456789abcdef' for x in self.plan[key]), 'guest source binding invalid')
            for key in ('review_repository_root', 'project_root'):
                require(type(self.plan[key]) is str and Path(self.plan[key]).is_absolute(), 'guest root binding invalid')
            require(self.plan['fixed_order'] == [list(x) for x in FIXED_ORDER], 'fixed four-run order differs')
            budget = self.plan['guest_prelaunch_budget_s']
            require(type(budget) in (float,int) and math.isfinite(budget) and
                0 < budget <= 120, 'guest shared-prelaunch budget invalid')
            self.phase_deadline = self.begun + budget
            self.plan_pin.deadline = self.phase_deadline
            code = Path(__file__).resolve().parent
            descriptors = self.plan['code']
            require(type(descriptors) is list and len(descriptors) == 3 and
                {Path(d['path']).name for d in descriptors} ==
                {'controller.py', 'guest_consumer.py', 'research_protocol.py'}, 'guest mounted code set differs')
            for descriptor in descriptors:
                self.pins.append(Pin(code/Path(descriptor['path']).name, descriptor, deadline=self.phase_deadline))
            require(type(self.plan['planning_files']) is list and len(self.plan['planning_files']) == 4,
                'guest reviewed planning set differs')
            self.output = Path(output)
            require(self.output.is_dir() and not list(self.output.iterdir()), 'guest output is not fresh')
            self.metadata = Evidence(self.output / 'metadata', METADATA_MAX // 2)
        except BaseException as exc:
            for pin in reversed(self.pins):
                try:
                    pin.close()
                except BaseException as close_error:
                    exc.add_note('guest partial acquisition retirement: '+str(close_error))
            raise
        self.active_source = None
        self.active_abort = None
        self.packages = {}
        self.mapping_snapshot_count = 0
        self.last_mapped_inputs = None
        self.mapped_library_collections = []
        self.media = {}
        self.runs = []
        self.Gst = self.GstVideo = None
        self.failure_stage = 'preflight_inputs'

    def pin(self, path, expected=None, *, mapped_identity=None):
        resolved = str(Path(path).resolve(strict=True))
        if resolved not in self.packages:
            try:
                pin = Pin(resolved, expected, deadline=self.phase_deadline, mapped_identity=mapped_identity,
                    observation_check=getattr(self, '_mapped_observation_check', None))
            except BaseException as exc:
                facts = getattr(exc, 'pin_rejection', None)
                if facts is not None:
                    facts['loaded_map_requested_path'] = os.fspath(path)
                raise
            self.pins.append(pin)
            self.packages[resolved] = pin
        else:
            pin = self.packages[resolved]
            pin.deadline = self.phase_deadline
            pin.verify(rehash=True)
            info = os.fstat(pin.fd)
            if mapped_identity is None:
                require(info.st_nlink == 1, 'pin is not a bounded single-link regular file')
            else:
                try:
                    pin.mapping_observation = verify_mapped_file(pin.fd, pin.path, mapped_identity,
                        self.phase_deadline, getattr(self, '_mapped_observation_check', None))
                    pin.verify(rehash=False)
                except BaseException as exc:
                    exc.pin_rejection = {'requested_path': os.fspath(path), 'resolved_path': resolved,
                        'pin_stage': 'cached_mapped_identity_join', 'mapped_identity': mapped_identity,
                        'fstat': _pin_stat(info), 'backing_observation': getattr(exc, 'backing_observation', None)}
                    raise
            if expected is not None:
                require(pin.descriptor['sha256'] == expected['sha256'], 'pin expected SHA differs')
                require(type(expected.get('size_bytes')) is int and
                    pin.descriptor['size_bytes'] == expected['size_bytes'], 'pin expected size differs')
        return self.packages[resolved]

    def mapped_library_pins(self, pid, selectors, expected_owner=None):
        self.last_mapped_inputs = None
        before = owner(pid, alive=True)
        require(expected_owner is None or before == expected_owner, 'original mapped owner differs')
        raw = read_process_maps(pid)
        parse_process_maps(raw)
        identities, rows = mapped_library_rows(raw, selectors)
        self.mapping_snapshot_count += 1
        number = self.mapping_snapshot_count
        snapshot = self.metadata.document(f'mapped-inputs-{self.mapping_snapshot_count:02d}.v1.json', {
            'artifact_kind': 'vast_decoder_research_original_mapped_inputs_v1', 'process': before,
            'observation_complete': False,
            'proc_path': f'/proc/{pid}/maps', 'observed_at_ns': time.time_ns(),
            'snapshot_size_bytes': len(raw), 'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
            'selectors': selectors, 'selected_original_rows': rows,
            'limitation': 'original backing-file identity, not mapped memory bytes',
            'accepted': False, 'publication_ready': False})
        libraries = []
        observations = []
        def self_probe_check(probe_raw, probe_row):
            _, during = mapped_library_rows(probe_raw, selectors)
            matches = [r for r in during if r['address_start'] == probe_row['address_start'] and
                r['address_end'] == probe_row['address_end']]
            require(len(matches) == 1, 'temporary self bridge range is not unique')
            during.remove(matches[0])
            require(during == rows, 'original selected self mappings changed during bridge')
            return during
        self._mapped_observation_check = self_probe_check if pid == os.getpid() else None
        try:
            for path in sorted(identities):
                try:
                    pin = self.pin(path, mapped_identity=identities[path])
                    libraries.append(pin.descriptor)
                    observations.append({'descriptor': pin.descriptor, 'mapping_observation': pin.mapping_observation})
                except BaseException as exc:
                    facts = getattr(exc, 'pin_rejection', None)
                    if facts is not None:
                        facts['mapping_snapshot'] = snapshot
                        facts['original_mapping_row'] = next(row for row in rows if row['path'] == path)
                    raise
        finally:
            self._mapped_observation_check = None
        after_raw = read_process_maps(pid)
        parse_process_maps(after_raw)
        _, after_rows = mapped_library_rows(after_raw, selectors)
        after = owner(pid, alive=True)
        require(before == after, 'original mapped owner changed')
        require(rows == after_rows, 'original selected mapping multiset changed')
        require(time.monotonic() < self.phase_deadline, 'original mapped collection deadline exceeded')
        final = self.metadata.document(f'mapped-inputs-{number:02d}-closed.v1.json', {
            'artifact_kind': 'vast_decoder_research_original_mapped_inputs_v1', 'observation_complete': True,
            'process': before, 'owner_before': before, 'owner_after': after,
            'proc_path': f'/proc/{pid}/maps', 'selectors': selectors,
            'snapshot_size_bytes': len(raw), 'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
            'snapshot_after_size_bytes': len(after_raw), 'snapshot_after_sha256': hashlib.sha256(after_raw).hexdigest(),
            'selected_original_rows': rows, 'selected_rows_before': rows, 'selected_rows_after': after_rows,
            'pin_observations': observations, 'before_snapshot': snapshot,
            'limitation': 'selected original rows retained; full unselected raw maps unavailable; not mapped memory bytes',
            'accepted': False, 'publication_ready': False})
        self.last_mapped_inputs = final
        if not hasattr(self, 'mapped_library_collections'):
            self.mapped_library_collections = []
        self.mapped_library_collections.append(final)
        return libraries

    def loaded_pins(self):
        self.mapped_library_pins(os.getpid(), ('libgst', 'libglib', 'libgobject', 'libgirepository', '_gi.',
            'libcuda', 'libnvcuvid', 'libnvidia'))
        return [self.packages[path].descriptor for path in sorted(self.packages)]

    def drain(self, fd, evidence, name, aborted, failure, retirement_failure=None):
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
            try:
                os.close(fd)
            except BaseException as exc:
                (failure if retirement_failure is None else retirement_failure)(exc)

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
        self.failure_stage = 'registry_refresh'
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
        fds = []
        primary = None
        cleanup_errors = []
        def retirement_failure(exc):
            cleanup_errors.append(type(exc).__name__+': '+str(exc))
            failure(exc)
        try:
            self.metadata.event('registry_process_started', child=owner(process.pid),
                controller=owner(os.getpid()), argv=[str(inspect_pin.path), 'nvh264dec'])
            for stream, name in ((process.stdout, out), (process.stderr, err)):
                fd = os.dup(stream.fileno())
                fds.append(fd)
                thread = threading.Thread(target=self.drain,
                    args=(fd, self.metadata, name, abort, failure, retirement_failure), daemon=True)
                thread.start(); threads.append(thread)
                fds.remove(fd)
            while process.poll() is None:
                require(not abort.is_set() and time.monotonic() < min(deadline, self.begun + 60),
                    'registry refresh failure/deadline')
                time.sleep(0.05)
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
            except BaseException as exc:
                retirement_failure(exc)
            try:
                process.wait(timeout=5)
            except BaseException as exc:
                retirement_failure(exc)
            while fds:
                fd = fds.pop()
                try:
                    os.close(fd)
                except BaseException as exc:
                    retirement_failure(exc)
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except BaseException as exc:
                    retirement_failure(exc)
            for thread in threads:
                try:
                    thread.join(timeout=2)
                except BaseException as exc:
                    retirement_failure(exc)
            if cleanup_errors:
                if primary is not None:
                    primary.add_note('registry owned cleanup failures: '+ '; '.join(cleanup_errors))
                try:
                    self.metadata.event('registry_owned_cleanup_failures', errors=cleanup_errors)
                except BaseException as exc:
                    if primary is not None:
                        primary.add_note('registry cleanup evidence unavailable: '+str(exc))
                    else:
                        failure(exc)
        self.metadata.event('registry_process_terminal', returncode=process.returncode, failures=failures)
        require(process.returncode == 0 and not failures and all(not t.is_alive() for t in threads),
            'original registry refresh did not complete')
        require(self.registry.is_file() and self.registry.stat().st_size <= 16 * 1024 * 1024,
            'registry absent/oversized')
        self.pin(self.registry)
        os.environ['GST_REGISTRY'] = str(self.registry)
        os.environ['GST_REGISTRY_UPDATE'] = 'no'
        self.failure_stage = 'gi_import'
        import gi
        self.failure_stage = 'gi_require_versions'
        gi.require_version('Gst', '1.0'); gi.require_version('GstApp', '1.0'); gi.require_version('GstVideo', '1.0')
        self.failure_stage = 'gi_repository_import'
        from gi.repository import Gst, GstApp, GstVideo
        import gi._gi
        self.initialize_gst(Gst,gi)
        self.failure_stage = 'package_version_checks'
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
        self.failure_stage = 'decoder_factory_metadata'
        factory = Gst.ElementFactory.find('nvh264dec')
        require(factory is not None, 'original reviewed decoder unavailable')
        self.failure_stage = 'decoder_plugin_metadata'
        plugin = factory.get_plugin()
        require(plugin.get_version() == '1.28.2' and Path(plugin.get_filename()).resolve() ==
            Path(self.plan['nvcodec_plugin']['path']), 'actual decoder plugin differs')
        self.loaded_pins()
        self.metadata.document('prelaunch.v1.json', {'artifact_kind': 'vast_decoder_research_guest_prelaunch_v1',
            'plan': self.plan_pin.descriptor, 'controller': owner(os.getpid()), 'gi_version': gi.__version__,
            'gst_version': list(Gst.version()), 'buffer_abi': buffer_abi(),
            'plugin_path': plugin.get_filename(), 'packages': self.loaded_pins(),
            'media': {key: pin.descriptor for key, pin in self.media.items()},
            'mapped_library_collections': self.mapped_library_collections,
            'elapsed_s': time.monotonic() - self.begun, 'accepted': False, 'publication_ready': False})
        require(time.monotonic() < deadline, 'prelaunch deadline exceeded')

    def initialize_gst(self,Gst,gi):
        self.failure_stage = 'gst_initialization_metadata'
        initializer = Gst.init
        doc = getattr(initializer,'__doc__',None)
        require(doc is None or (type(doc) is str and len(doc.encode('utf8'))<=4096),
            'actual initialization callable documentation cap')
        code = getattr(initializer,'__code__',None)
        callable_module = getattr(initializer,'__module__',None)
        source_paths = [getattr(sys.modules.get(callable_module),'__file__',None),
            getattr(sys.modules.get('gi.overrides.Gst'),'__file__',None),
            None if code is None else code.co_filename]
        actual_sources = []
        for path in dict.fromkeys(source_paths):
            if path is not None and Path(path).is_file():actual_sources.append(self.pin(path).descriptor)
        metadata = {'artifact_kind':'vast_decoder_research_initialization_metadata_v1',
            'callable_type_module':type(initializer).__module__,
            'callable_type_name':type(initializer).__qualname__, 'callable_module':callable_module,
            'callable_qualname':getattr(initializer,'__qualname__',None),'callable_doc':doc,
            'code_filename':None if code is None else code.co_filename,
            'code_firstlineno':None if code is None else code.co_firstlineno,
            'actual_loaded_override_sources':actual_sources,
            'gi_package':self.pin(gi.__file__).descriptor,'gi_extension':self.pin(gi._gi.__file__).descriptor,
            'gst_typelib':self.pin('/opt/intel/dlstreamer/gstreamer/lib/girepository-1.0/Gst-1.0.typelib').descriptor,
            'intended_arguments':[], 'accepted':False,'publication_ready':False}
        self.metadata.document('initialization-metadata.v1.json',metadata)
        self.failure_stage = 'gst_init_empty_list'
        self.metadata.event('gst_initialization_before',intended_arguments=[])
        Gst.init([])  # One explicit supported invocation; no fallback or repeated initialization.
        self.failure_stage = 'gst_initialized_check'
        initialized = Gst.is_initialized()
        self.metadata.event('gst_initialization_after',actual_initialized=initialized)
        require(initialized is True,'actual GStreamer initialization did not complete')

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
        cleanup_errors = []
        def owned_pipe():
            pair = os.pipe()
            fds.extend(pair)
            return pair
        def retire_pipe(fd):
            # One close obligation: a failed close must not target a reused FD later.
            fds.remove(fd)
            try:
                os.close(fd)
            except BaseException as exc:
                cleanup_errors.append('owned pipe FD retirement: '+type(exc).__name__+': '+str(exc))
                return exc
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
        run_stage = 'run_started'
        inner_failure = inner_failure_capture_error = None
        inner_capture_attempted = False
        def failure(exc):
            nonlocal inner_failure, inner_failure_capture_error, inner_capture_attempted
            with command_lock:
                errors.append(str(exc)); abort.set()
                if gate is not None:
                    gate.fail(exc)
                if not inner_capture_attempted:
                    inner_capture_attempted = True  # The first original failure survives later cleanup/callbacks.
                    try:
                        inner_failure = self.record_inner_failure(evidence, exc, run_stage, index, clip['role'], setting)
                    except BaseException as capture_error:
                        inner_failure_capture_error = str(capture_error)
                        errors.append('original inner failure capture: ' + str(capture_error))
        def thread_call(function):
            try:
                function()
            except BaseException as exc:
                failure(exc)
        def spawn(function):
            thread = threading.Thread(target=thread_call, args=(function,), daemon=True)
            thread.start(); threads.append(thread)
        def drain_retirement_failure(exc):
            cleanup_errors.append('owned log pipe FD retirement: '+type(exc).__name__+': '+str(exc))
            failure(exc)
        try:
            evidence.document('run-started.v1.json', {'artifact_kind': 'vast_decoder_research_run_started_v1',
                'run': index, 'clip': clip['role'], 'setting': setting,
                'started_monotonic_ns': int(run_start*1_000_000_000), 'started_realtime_ns': time.time_ns(),
                'guest_elapsed_at_start_s':run_start-self.begun,
                'controller': owner(os.getpid()), 'accepted': False})
            run_stage = 'pipeline_parse_launch'
            pipeline = Gst.parse_launch(PIPELINE)
            appsrc, decoder, appsink = [pipeline.get_by_name(name) for name in ('source', 'decoder', 'output')]
            run_stage = 'pipeline_property_metadata'
            prop = decoder.find_property('max-display-delay')
            require(prop is not None and prop.minimum == -1 and prop.maximum == 16 and int(prop.flags)&3 == 3,
                'reviewed writable decoder property range differs')
            default = decoder.get_property('max-display-delay')
            if setting == 'zero':
                decoder.set_property('max-display-delay', 0)
                require(decoder.get_property('max-display-delay') == 0, 'zero decoder property readback differs')
            run_stage = 'pipeline_created.loaded_pins'
            evidence.event('pipeline_created', text=PIPELINE, setting=setting,
                property_default_readback=default, property_readback=decoder.get_property('max-display-delay'),
                default_was_unset=setting == 'default', packages=self.loaded_pins(),
                mapped_inputs=self.last_mapped_inputs)
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
            run_stage = 'decoder_probe_setup'
            for phase in ('sink', 'src'):
                decoder.get_static_pad(phase).add_probe(Gst.PadProbeType.BUFFER |
                    Gst.PadProbeType.EVENT_DOWNSTREAM, probe, phase)
            run_stage = 'pipeline_playing'
            require(pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE,
                'decoder pipeline failed PLAYING')
            bus = pipeline.get_bus()
            run_stage = 'source_launch_preparation'
            media_pin.verify()
            registry_copy = Path('/tmp') / f'decoder-research-source-{index}.registry.bin'
            require(not registry_copy.exists(), 'source registry copy already exists')
            shutil.copyfile(self.registry, registry_copy)
            require(physical_descriptor(registry_copy)['sha256'] == self.packages[str(self.registry)].descriptor['sha256'],
                'source registry copy mismatch')
            self.pin(registry_copy)
            run_id = f'research-decoder-{index:02d}'
            worker_id = f'research-source-{clip["role"]}-{index:02d}'
            ad_r, ad_w = owned_pipe(); ack_r, ack_w = owned_pipe(); ctl_r, ctl_w = owned_pipe()
            st_r, st_w = owned_pipe(); au_r, au_w = owned_pipe()
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
            run_stage = 'source_process_start'
            process = subprocess.Popen(argv, executable=f'/proc/self/fd/{self.source_pin.fd}',
                env=environment, pass_fds=(ad_w, ack_r, ctl_r, st_w, au_w, media_pin.fd, self.source_pin.fd),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            self.active_source = process
            source_owner = owner(process.pid)
            evidence.event('source_process_started', child=source_owner, controller=owner(os.getpid()),
                argv=argv, source_binary=self.source_pin.descriptor, media=media_pin.descriptor,
                environment={key: value for key, value in environment.items() if key.startswith('VAST_CHECKPOINT_') or key.startswith('GST_REGISTRY')})
            for fd in (ad_w, ack_r, ctl_r, st_w, au_w):
                close_error = retire_pipe(fd)
                if close_error is not None:
                    raise close_error
            for stream, name in ((process.stdout, stdout), (process.stderr, stderr)):
                fd = os.dup(stream.fileno())
                fds.append(fd)
                spawn(lambda fd=fd, name=name: self.drain(fd, evidence, name, abort, failure,
                    drain_retirement_failure))
                fds.remove(fd)  # Transfer the single close obligation only after thread start.
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
            run_stage = 'source_startup'
            while not status_ready.wait(0.05):
                require(not abort.is_set() and process.poll() is None and time.monotonic() < startup_deadline,
                    'source READY startup failure/deadline')
            require(time.monotonic() < startup_deadline, 'source READY arrived beyond45s startup')
            source_libraries = self.mapped_library_pins(process.pid, ('libgst', 'libglib', 'libgobject'), source_owner)
            evidence.event('actual_source_loaded_libraries', libraries=source_libraries,
                mapped_inputs=self.last_mapped_inputs)
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
            run_stage = 'source_admission_and_decoder_drain'
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
            run_stage = 'original_result_validation'
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
            while fds:
                retire_pipe(fds[-1])
            for role, stream in (() if process is None else
                    (('stdout', process.stdout), ('stderr', process.stderr))):
                try:
                    stream.close()
                except BaseException as exc:
                    cleanup_errors.append('owned source '+role+' stream retirement: '+
                        type(exc).__name__+': '+str(exc))
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
                'original_inner_failure': inner_failure, 'inner_failure_capture_error': inner_failure_capture_error,
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

    def record_inner_failure(self, evidence, exc, stage, index, role, setting):
        record = {'artifact_kind': 'vast_decoder_research_original_inner_failure_v1',
            'run': index, 'clip': role, 'setting': setting, 'stage': stage,
            'exception_type': type(exc).__module__ + '.' + type(exc).__qualname__, 'message': str(exc),
            'pin_rejection': getattr(exc, 'pin_rejection', None),
            'traceback': ''.join(traceback.format_exception(exc)), 'accepted': False, 'publication_ready': False}
        require(len(canonical(seal(record))) + 1 <= EVENT_MAX, 'original inner failure record16KiB cap exceeded')
        return evidence.document('original-inner-failure.v1.json', record)

    def execute(self):
        result = None
        operation_completed = False
        failure = None
        failure_type = failure_trace = failure_trace_error = None
        primary_exc = original_primary_failure = primary_failure_capture_error = None
        metadata_close_error = pin_close_error = close_failure = close_failure_capture_error = None
        mode = getattr(self, 'mode', None)
        final_deadline = self.phase_deadline if mode == 'metadata-only' else self.overall_deadline
        try:
            require(mode in ('metadata-only', 'research') and self.plan.get('mode') == mode,
                'explicit sealed guest mode required')
            self.preflight()
            completed = []
            if mode == 'metadata-only':
                require(not self.runs and getattr(self, 'active_source', None) is None and
                    all(path.name == 'metadata' for path in self.output.iterdir()),
                    'metadata preflight created an original source or run namespace')
                self.failure_stage = 'metadata_final_pins'
            if mode == 'research':
                by_role = {source['role']: source for source in self.plan['sources']}
                for index, (role, setting) in enumerate(FIXED_ORDER, 1):
                    self.failure_stage = 'original_run_'+str(index)
                    completed.append(self.run(index, by_role[role], setting))
                require(len(completed) == len(self.runs) == 4, 'research exact-four completion differs')
                self.failure_stage = 'paired_observations_and_final_pins'
                for left, right in ((completed[0],completed[1]), (completed[2],completed[3])):
                    require(left['input_pts_decode_order'] == right['input_pts_decode_order'], 'paired source prefix differs')
                    require(left['packets'] == right['packets'], 'paired original AU bytes/transport fields differ')
                    compare_outputs(left['outputs'], right['outputs'], left['input_pts_decode_order'])
            for pin in self.pins:
                pin.deadline=final_deadline-1
                pin.verify(rehash=True)
            package_receipt = self.metadata.document('final-package-pins.v1.json', {
                'artifact_kind':'vast_decoder_research_final_package_pins_v1',
                'pins':[pin.descriptor for pin in self.pins], 'all_before_after_verified':True,
                'mapped_library_collections':getattr(self, 'mapped_library_collections', []),
                'accepted':False,'publication_ready':False})
            require(time.monotonic() < final_deadline, 'guest shared phase deadline exceeded')
            if mode == 'research':
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
            operation_completed = True
        except BaseException as exc:
            primary_exc = exc
            result = None
            failure = str(exc)
            failure_type = type(exc).__module__+'.'+type(exc).__qualname__
            try:
                original_primary_failure = self.record_inner_failure(
                    self.metadata, exc, self.failure_stage, None, None, None)
            except BaseException as capture_error:
                primary_failure_capture_error = str(capture_error)
            try:
                raw=''.join(traceback.format_exception(exc)).encode('utf8')
                require(len(raw)<=EVENT_MAX,'original failure traceback16KiB cap exceeded')
                name=self.metadata.open('original-failure-traceback.txt',EVENT_MAX)
                self.metadata.append(name,raw,sync=True)
                failure_trace=physical_descriptor(self.metadata.directory/name)
            except BaseException as trace_error:
                failure_trace_error=str(trace_error)
        finally:
            try:
                if time.monotonic()>=final_deadline-1:
                    result=None
                    operation_completed=False
                    if failure is None:failure='original guest finalization reserve exhausted'
                leaf = 'metadata-preflight-terminal.v1.json' if mode == 'metadata-only' else 'research-terminal.v1.json'
                kind = 'vast_decoder_research_metadata_preflight_terminal_v1' if mode == 'metadata-only' else 'vast_decoder_research_guest_terminal_v1'
                receipt = self.metadata.document(leaf, {
                    'artifact_kind': kind, 'plan': self.plan_pin.descriptor,
                    'mode': mode, 'planning_commit': self.plan.get('planning_commit'),
                    'source_commit': self.plan.get('source_commit'),
                    'current_checkout_commit': self.plan.get('current_checkout_commit'),
                    'review_repository_root':self.plan.get('review_repository_root'),
                    'project_root':self.plan.get('project_root'),
                    'operation_completed':operation_completed,
                    'metadata_preflight_completed':mode == 'metadata-only' and operation_completed,
                    'research_complete':mode == 'research' and result is not None,
                    'provisional_until_owner_final_close':True,
                    'result': result, 'failure': failure, 'runs_completed': len(self.runs),
                    'failure_stage':None if failure is None else self.failure_stage,
                    'failure_type':failure_type,'failure_traceback':failure_trace,
                    'failure_traceback_error':failure_trace_error,
                    'original_primary_failure':original_primary_failure,
                    'primary_failure_capture_error':primary_failure_capture_error,
                    'elapsed_s': time.monotonic()-self.begun, 'accepted': False, 'publication_ready': False,
                    'benchmark_arm_count': 0, 'native_pair_count': 0, 'qualification_count': 0,
                    'model_or_parity_evidence': False}, final=True)
            except BaseException as final_error:
                if primary_exc is not None:
                    primary_exc.add_note('guest terminal persistence failed: '+str(final_error))
                    raise primary_exc from final_error
                raise
            finally:
                try:
                    self.metadata.close()
                except BaseException as close_error:
                    metadata_close_error = str(close_error)
                    result = None
                    operation_completed = False
                    if primary_exc is not None:
                        primary_exc.add_note('guest metadata close failed: '+metadata_close_error)
                finally:
                    for pin in reversed(self.pins):
                        try:
                            pin.close()
                        except BaseException as close_error:
                            if pin_close_error is None:pin_close_error = str(close_error)
                            result = None
                            operation_completed = False
                            if primary_exc is not None:
                                primary_exc.add_note('guest pin close failed: '+str(close_error))
            if metadata_close_error is not None or pin_close_error is not None:
                try:
                    record = {'artifact_kind':'vast_decoder_research_guest_close_failure_v1',
                        'provisional_terminal':receipt, 'original_failure':failure,
                        'original_failure_type':failure_type, 'original_primary_failure':original_primary_failure,
                        'metadata_close_error':metadata_close_error, 'pin_close_error':pin_close_error,
                        'accepted':False, 'publication_ready':False}
                    require(len(canonical(seal(record)))+1<=EVENT_MAX,'guest close failure record16KiB cap exceeded')
                    close_failure = self.metadata.document('guest-close-failure.v1.json',record,final=True)
                except BaseException as capture_error:
                    close_failure_capture_error = str(capture_error)
                finally:
                    try:
                        self.metadata.close()
                    except BaseException as capture_error:
                        if close_failure_capture_error is None:close_failure_capture_error = str(capture_error)
            try:
                within_deadline,late_receipt=post_receipt_deadline(
                    self.metadata,receipt,self.begun,final_deadline,'guest')
            except BaseException as late_error:
                if primary_exc is not None:
                    primary_exc.add_note('guest after-close receipt failed: '+str(late_error))
                    raise primary_exc from late_error
                raise
            if not within_deadline:
                result=None
                operation_completed=False
            successful = operation_completed and (mode == 'metadata-only' or result is not None)
            print(canonical({'receipt': receipt, 'successful': successful,
                'receipt_time_limit_failure':late_receipt, 'close_failure':close_failure,
                'metadata_close_error':metadata_close_error, 'pin_close_error':pin_close_error,
                'close_failure_capture_error':close_failure_capture_error}).decode(), flush=True)
        return 0 if successful else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--mode', required=True, choices=('metadata-only','research'))
    args = parser.parse_args()
    guest = Guest(args.plan, args.output_dir, args.mode)
    def interrupted(signum, frame):
        if guest.active_abort is not None:
            guest.active_abort.set()
        raise ResearchError('original guest interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    return guest.execute()


if __name__ == '__main__':
    sys.exit(main())
