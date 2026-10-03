import hashlib
import importlib.util
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_savant_native_module as native_target  # noqa: E402
from checkpoint_savant_native_module import (  # noqa: E402
    BASELINE_TOPOLOGY,
    BRANCHES,
    SHARED_TOPOLOGY,
    SavantAdmissionIngressFilter,
    SavantNativeModuleBinding,
    SavantNativeModuleError,
    SavantNativeRouteBufferPlugin,
    build_native_frame_identity,
    build_native_module_artifact,
    build_native_module_matrix,
    SavantEngineeringCanaryRuntime,
    register_native_runtime,
    unregister_native_runtime,
)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def descriptor(topology: str, stream_id: int = 3, branch: str = "damage") -> dict:
    module_id = (
        f"savant-stream-{stream_id}-branch-{branch}"
        if topology == BASELINE_TOPOLOGY
        else f"savant-stream-{stream_id}-shared-video-dag"
    )
    branches = [branch] if topology == BASELINE_TOPOLOGY else list(BRANCHES)
    value = {
        "schema_version": 1,
        "artifact_kind": "savant_checkpoint_module_descriptor",
        "claim_status": "engineering_savant_module_descriptor_nonpublication",
        "system": "savant",
        "module_id": module_id,
        "topology_kind": topology,
        "stream_id": stream_id,
        "branches": branches,
        "source_process_id": f"source-stream-{stream_id}",
        "source_sha256": "a" * 64,
        "codec": "h264",
        "dataset": "kpp_iss_publication_v3_h264",
        "policy": "heft",
        "deadline_ms": 33.3,
        "module_config_path": f"/opt/vast/checkpoint/generated/{module_id}.yml",
        "module_config_status": "missing_not_built",
        "bridge_class": "checkpoint_savant_protocol_bridge:SavantProtocolBridge",
        "inherited_fd_contract": {
            "admission": "VAST_CHECKPOINT_ADMISSION_DATA_FD",
            "control": "VAST_CHECKPOINT_CONTROL_FD",
            "event": "VAST_CHECKPOINT_EVENT_FD",
            "policy": "VAST_CHECKPOINT_POLICY_FD",
            "status": "VAST_CHECKPOINT_STATUS_FD",
        },
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }
    if topology == BASELINE_TOPOLOGY:
        value["physical_pipeline"] = []
    else:
        value["shared_prefix"] = []
        value["routes"] = []
    value["descriptor_sha256"] = hashlib.sha256(canonical(value).encode()).hexdigest()
    return value


def source(stream_id: int = 3) -> dict:
    return {
        "stream_id": stream_id,
        "source_id": f"kpp_plate_avi-stream-{stream_id}",
        "source_sha256": "a" * 64,
        "source_codec": "h264",
        "source_duration_ns": 10_000_000_000,
        "width": 1920,
        "height": 1080,
    }


class FakeFrame:
    def __init__(self, binding: SavantNativeModuleBinding) -> None:
        self.source_id = binding.source_id
        self.codec = "h264"
        self.width = binding.width
        self.height = binding.height
        self.framerate = "600/1"
        self.pts = 7_000_000
        self.time_base = (1, 1_000_000_000)
        self.content = ("zeromq", None)
        self._tags = {
            "vast.admission_id": "admission-7",
            "vast.input_frame_key": (
                f"{binding.dataset_id}:{binding.stream_id}:"
                f"{binding.source_sha256}:2:5000000"
            ),
            "vast.payload_sha256": "b" * 64,
            "vast.access_unit_pts_ns": 5_000_000,
            "vast.transport_pts_ns": self.pts,
            "vast.source_cycle": 2,
            "vast.sequence": 7,
            "vast.event_provenance": "native_common_source_coordinator",
        }

    def get_attribute(self, namespace: str, name: str):
        if namespace != "default" or name not in self._tags:
            return None
        return SimpleNamespace(values=[self._tags[name]])


class FakeRuntime:
    def __init__(self) -> None:
        self.admitted = []

    def admit_video_frame(self, frame, binding) -> None:
        self.admitted.append((frame, binding))


class FakeBufferRouteRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.routes = []

    def observe_route_buffer(self, buffer, binding, branch, *, sample, caps) -> None:
        self.routes.append((buffer, binding, branch, sample, caps))


class NativeModuleTests(unittest.TestCase):
    def test_checkpoint_factory_uses_device_memory_without_changing_upstream_factory(self) -> None:
        # Reproduce Savant 0.5.17's factory dispatch, including its hard-coded
        # unified-memory default, without needing a GPU in the unit suite.
        @dataclass
        class ElementConfig:
            element: str
            name: str
            properties: dict

        class UpstreamFactory:
            def create(self, element):
                if element.element == "nvvideoconvert":
                    return self.create_nvvideoconvert(element)
                return dict(element.properties)

            @staticmethod
            def create_nvvideoconvert(element):
                return {"nvbuf-memory-type": 3, **element.properties}

        class UpstreamPipeline:
            _element_factory = UpstreamFactory()

        modules = {}
        for name in (
            "savant", "savant.config", "savant.config.schema", "savant.deepstream",
            "savant.deepstream.pipeline", "savant.deepstream.element_factory",
            "savant.gstreamer", "savant.gstreamer.utils",
        ):
            module = ModuleType(name)
            module.__path__ = []
            modules[name] = module
        modules["savant.config.schema"].PipelineElement = ElementConfig
        modules["savant.config.schema"].PyFuncElement = ElementConfig
        modules["savant.deepstream.pipeline"].NvDsPipeline = UpstreamPipeline
        modules["savant.deepstream.element_factory"].NvDsElementFactory = UpstreamFactory
        modules["savant.gstreamer"].Gst = SimpleNamespace()
        modules["savant.gstreamer.utils"].gst_post_stream_failed_error = mock.Mock()
        name = "vast_savant_allocator_boundary_fixture"
        spec = importlib.util.spec_from_file_location(name, native_target.__file__)
        target = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {**modules, name: target}):
            spec.loader.exec_module(target)
            factory = target.SavantCheckpointNvDsPipeline._element_factory
            for properties in ({}, {"nvbuf-memory-type": 3, "output-buffers": 12}):
                with self.subTest(properties=properties):
                    original = dict(properties)
                    converter = ElementConfig("nvvideoconvert", "source-or-rgb-converter", properties)
                    result = factory.create(converter)
                    self.assertEqual(result["nvbuf-memory-type"], 2)
                    self.assertEqual(converter.properties, original)
                    if "output-buffers" in original:
                        self.assertEqual(result["output-buffers"], 12)
            self.assertEqual(factory.create(ElementConfig("queue", "route", {"leaky": "upstream"})),
                             {"leaky": "upstream"})
            self.assertEqual(UpstreamPipeline._element_factory.create(
                ElementConfig("nvvideoconvert", "unrelated-pipeline", {})), {"nvbuf-memory-type": 3})

    def test_savant_pyfunc_reloads_preserve_registered_runtime_and_binding_type(self) -> None:
        # Savant 0.5.17 utils.modules_cache.import_module executes a fresh
        # module for each PyFunc, then replaces sys.modules[spec.name].
        # Exercise that loader boundary, not a normal cached Python import.
        for topology in (BASELINE_TOPOLOGY, SHARED_TOPOLOGY):
            with self.subTest(topology=topology), mock.patch.dict(sys.modules):
                artifact = build_native_module_artifact(descriptor(topology), source())
                binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
                runtime = FakeRuntime()
                register_native_runtime(binding.descriptor_sha256, runtime)
                last_ingress = None
                try:
                    pipeline = artifact["module_config"]["pipeline"]
                    configurations = (
                        pipeline["source"]["ingress_frame_filter"],
                        pipeline["elements"][0],
                    )
                    for _ in range(3):
                        for configuration in configurations:
                            spec = importlib.util.find_spec(configuration["module"])
                            loaded = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(loaded)
                            sys.modules[spec.name] = loaded
                            plugin = getattr(loaded, configuration["class_name"])(
                                **configuration["kwargs"]
                            )
                            if configuration["class_name"] == "SavantAdmissionIngressFilter":
                                self.assertTrue(plugin(FakeFrame(binding)))
                                last_ingress = plugin
                            self.assertIs(type(plugin.binding), type(binding))
                            self.assertEqual(plugin.binding, binding)
                    self.assertEqual(len(runtime.admitted), 3)
                    self.assertIs(native_target._runtime(binding), runtime)
                    with self.assertRaisesRegex(SavantNativeModuleError, "registered twice"):
                        register_native_runtime(binding.descriptor_sha256, FakeRuntime())
                finally:
                    unregister_native_runtime(binding.descriptor_sha256, runtime)
                with self.assertRaisesRegex(SavantNativeModuleError, "not registered"):
                    last_ingress(FakeFrame(binding))

    def test_native_resolution_does_not_inherit_eight_pixel_geometry_requirement(self) -> None:
        for topology in (BASELINE_TOPOLOGY, SHARED_TOPOLOGY):
            with self.subTest(topology=topology):
                native_source = {**source(), "width": 1700, "height": 1900}
                artifact = build_native_module_artifact(descriptor(topology), native_source)
                self.assertEqual(
                    artifact["module_config"]["parameters"]["frame"],
                    {"width": 1700, "height": 1900, "geometry_base": 1},
                )

    def test_post_demux_rgb_routes_do_not_use_nvmm_only_savant_pyfunc(self) -> None:
        class Pad:
            def __init__(self):
                self.probes = []

            def link(self, other):
                return 0

            def add_probe(self, *args):
                self.probes.append(args)
                return len(self.probes)

        class Element:
            def __init__(self, config):
                self.config = config
                self.downstream = None
                self.signals = []
                self.pads = {}

            def link(self, other):
                # The official Savant pyfunc template accepts only NVMM/RGBA.
                if (self.config.element == "capsfilter"
                        and other.config.element in {"queue", "vastcheckpointbranchqueue"}
                        and other.downstream is not None
                        and other.downstream.config.element == "pyfunc"):
                    return False
                self.downstream = other
                return True

            def get_static_pad(self, name):
                return self.pads.setdefault(name, Pad())

            def request_pad_simple(self, name):
                return Pad()

            def sync_state_with_parent(self):
                pass

            def connect(self, *args):
                self.signals.append(args)

            def set_property(self, *args):
                pass

        def element_config(element, **kwargs):
            return SimpleNamespace(element=element, **kwargs)

        for topology in (BASELINE_TOPOLOGY, SHARED_TOPOLOGY):
            with self.subTest(topology=topology):
                artifact = build_native_module_artifact(descriptor(topology), source())
                pipeline = object.__new__(native_target.SavantCheckpointNvDsPipeline)
                pipeline.checkpoint_binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
                pipeline.checkpoint_topology = artifact["module_config"]["parameters"]["checkpoint_native_topology"]
                pipeline._video_pipeline = object()
                pipeline._batch_size = 1
                pipeline._check_pipeline_is_running = mock.Mock()
                pipeline._link_demuxer_src_pad = mock.Mock()
                elements = []

                def add(config, *, link=False):
                    self.assertFalse(link)
                    element = Element(config)
                    elements.append(element)
                    return element

                pipeline.add_element = add
                source_info = SimpleNamespace(after_demuxer=[])
                with mock.patch.object(native_target._NvDsPipeline, "_add_source_output", create=True, return_value=Pad()), \
                     mock.patch.object(native_target, "PipelineElement", element_config), \
                     mock.patch.object(native_target, "PyFuncElement", lambda **kwargs: element_config("pyfunc", **kwargs)), \
                     mock.patch.object(native_target, "Gst", SimpleNamespace(
                         PadLinkReturn=SimpleNamespace(OK=0), PadProbeType=SimpleNamespace(BUFFER=16))):
                    pipeline._add_source_output(source_info)
                terminals = [element for element in elements
                             if element.config.name in {
                                 route["terminal_name"]
                                 for route in pipeline.checkpoint_topology["routes"]}]
                self.assertEqual(len(terminals), len(pipeline.checkpoint_binding.branches))
                self.assertTrue(all(element.config.element == "identity" for element in terminals))
                self.assertTrue(all(element.signals[0][0] == "handoff" for element in terminals))
                queues = [element for element in elements if element.config.name in {
                    route["queue_name"] for route in pipeline.checkpoint_topology["routes"]}]
                self.assertEqual(len(queues), len(pipeline.checkpoint_binding.branches))
                for queue in queues:
                    self.assertEqual(queue.config.element, "vastcheckpointbranchqueue")
                    self.assertEqual(queue.config.properties, {"max-size-buffers": 1})
                    self.assertEqual([signal[0] for signal in queue.signals], ["buffer-dropped"])
                    probes = queue.get_static_pad("sink").probes
                    self.assertEqual(len(probes), 1 if topology == SHARED_TOPOLOGY else 0)
                    if probes:
                        self.assertEqual(probes[0][0], 16)
                        self.assertEqual(probes[0][1], pipeline._on_queue_buffer_probe)
                        self.assertEqual(probes[0][2:], ((queue, queue.config.name.removeprefix("vast_savant_route_queue_")),))

    def test_queue_probe_passes_real_buffer_and_caps_before_queue_decision(self) -> None:
        artifact = build_native_module_artifact(descriptor(SHARED_TOPOLOGY), source())
        pipeline = object.__new__(native_target.SavantCheckpointNvDsPipeline)
        pipeline.checkpoint_binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        runtime, queue, buffer, caps = mock.Mock(), object(), object(), object()
        pad = SimpleNamespace(get_current_caps=lambda: caps)
        info = SimpleNamespace(get_buffer=lambda: buffer)
        with mock.patch.object(native_target, "_runtime", return_value=runtime), \
             mock.patch.object(native_target, "Gst", SimpleNamespace(PadProbeReturn=SimpleNamespace(OK=1, DROP=0))), \
             mock.patch.object(native_target, "_gst_post_stream_failed_error", create=True) as post:
            self.assertEqual(pipeline._on_queue_buffer_probe(pad, info, (queue, "damage")), 1)
        runtime.observe_queue_buffer.assert_called_once_with(buffer, pipeline.checkpoint_binding, "damage", caps=caps)
        post.assert_not_called()

    def test_queue_probe_failure_posts_error_and_prevents_buffer_delivery(self) -> None:
        artifact = build_native_module_artifact(descriptor(SHARED_TOPOLOGY), source())
        pipeline = object.__new__(native_target.SavantCheckpointNvDsPipeline)
        pipeline.checkpoint_binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        runtime, queue = mock.Mock(), object()
        runtime.observe_queue_buffer.side_effect = RuntimeError("fanout recorder failed")
        pad = SimpleNamespace(get_current_caps=lambda: object())
        for buffer in (object(), None):
            with self.subTest(buffer=buffer), \
                 mock.patch.object(native_target, "_runtime", return_value=runtime), \
                 mock.patch.object(native_target, "Gst", SimpleNamespace(PadProbeReturn=SimpleNamespace(OK=1, DROP=0))), \
                 mock.patch.object(native_target, "_gst_post_stream_failed_error", create=True) as post:
                info = SimpleNamespace(get_buffer=lambda: buffer)
                self.assertEqual(pipeline._on_queue_buffer_probe(pad, info, (queue, "damage")), 0)
            post.assert_called_once()
            self.assertIs(post.call_args.kwargs["gst_element"], queue)

    def test_native_queue_drop_callback_uses_the_reported_pts(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        pipeline = object.__new__(native_target.SavantCheckpointNvDsPipeline)
        pipeline.checkpoint_binding = binding
        runtime = mock.Mock()
        queue = SimpleNamespace(get_name=lambda: "vast_savant_route_queue_damage")
        with mock.patch.object(native_target, "_runtime", return_value=runtime), \
             mock.patch.object(native_target, "_gst_post_stream_failed_error", create=True) as post:
            self.assertIs(pipeline._on_queue_buffer_dropped(queue, 123, "damage"), True)
        runtime.queue_dropped.assert_called_once_with(
            branch="damage", queue_name="vast_savant_route_queue_damage",
            transport_pts_ns=123, binding=binding,
        )
        post.assert_not_called()

    def test_native_queue_drop_callback_failure_is_not_acknowledged(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        pipeline = object.__new__(native_target.SavantCheckpointNvDsPipeline)
        pipeline.checkpoint_binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        runtime = mock.Mock()
        runtime.queue_dropped.side_effect = RuntimeError("unknown dropped identity")
        queue = SimpleNamespace(get_name=lambda: "vast_savant_route_queue_damage")
        with mock.patch.object(native_target, "_runtime", return_value=runtime), \
             mock.patch.object(native_target, "_gst_post_stream_failed_error", create=True) as post:
            self.assertIs(pipeline._on_queue_buffer_dropped(queue, 123, "damage"), False)
        post.assert_called_once()
        self.assertIs(post.call_args.kwargs["gst_element"], queue)
        self.assertIn("unknown dropped identity", post.call_args.kwargs["debug"])

    def test_rgb_route_callback_failure_posts_native_stream_error(self) -> None:
        pipeline = object.__new__(native_target.SavantCheckpointNvDsPipeline)
        terminal = mock.Mock()
        terminal.process_buffer.side_effect = RuntimeError("route failed")
        element, buffer = object(), object()
        with mock.patch.object(native_target, "_gst_post_stream_failed_error", create=True) as post:
            pipeline._on_rgb_route_handoff(element, buffer, terminal)
        terminal.process_buffer.assert_called_once_with(buffer)
        post.assert_called_once()
        self.assertIs(post.call_args.kwargs["gst_element"], element)
        self.assertIn("route failed", post.call_args.kwargs["debug"])

    def test_rgb_route_callback_passes_the_real_buffer_once(self) -> None:
        pipeline = object.__new__(native_target.SavantCheckpointNvDsPipeline)
        terminal = mock.Mock()
        element, buffer = object(), object()
        with mock.patch.object(native_target, "_gst_post_stream_failed_error", create=True) as post:
            pipeline._on_rgb_route_handoff(element, buffer, terminal)
        terminal.process_buffer.assert_called_once_with(buffer)
        post.assert_not_called()

    def test_canary_runtime_stays_nonpublication_and_records_native_identity(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        frame = FakeFrame(binding)
        native = SimpleNamespace(source_id=3, frame_num=41, buf_pts=frame.pts)
        frame_meta = SimpleNamespace(video_frame=frame, frame_meta=native)
        runtime = SavantEngineeringCanaryRuntime()
        runtime.admit_video_frame(frame, binding)
        runtime.bind_decoder("nvv4l2decoder", 0)
        buffer = SimpleNamespace(pts=123)
        runtime.observe_prefix(buffer, frame_meta, binding)
        runtime.observe_route(buffer, frame_meta, binding, "damage")
        receipt = runtime.receipt()
        self.assertEqual(receipt["decoded_frames"], 1)
        self.assertEqual(receipt["branch_terminals"], 1)
        self.assertFalse(receipt["publication_ready"])
        self.assertFalse(receipt["accepted_measurement_evidence_emitted"])

    def test_baseline_config_is_real_zeromq_nvds_one_branch_and_nonpublication(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        config = artifact["module_config"]
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        self.assertEqual(config["pipeline"]["source"]["element"], "zeromq_source_bin")
        self.assertNotIn("appsrc", canonical(config))
        self.assertEqual(config["pipeline"]["source"]["properties"]["socket"], binding.module_socket)
        self.assertEqual(config["pipeline"]["source"]["properties"]["source-timeout"], 60)
        self.assertEqual(
            config["pipeline"]["pipeline_class"],
            "checkpoint_savant_native_module.SavantCheckpointNvDsPipeline",
        )
        topology = config["parameters"]["checkpoint_native_topology"]
        self.assertEqual(topology["route_count"], 1)
        self.assertEqual(topology["routes"][0]["branch"], "damage")
        self.assertEqual(topology["routes"][0]["max_size_buffers"], 1)
        self.assertEqual(topology["routes"][0]["drop_policy"], "drop_newest")
        self.assertEqual(
            [item["element"] for item in config["pipeline"]["elements"]],
            ["pyfunc"],
        )
        self.assertFalse(artifact["publication_ready"])
        self.assertFalse(artifact["accepted_measurement_evidence_emitted"])

    def test_post_demux_terminal_uses_buffer_pts_without_removed_nvds_batch_meta(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        runtime = FakeBufferRouteRuntime()
        register_native_runtime(binding.descriptor_sha256, runtime)
        try:
            plugin = SavantNativeRouteBufferPlugin(
                binding_json=artifact["binding_json"], branch="damage"
            )
            buffer = SimpleNamespace(pts=7_000_000)
            caps = object()
            pad = SimpleNamespace(get_current_caps=lambda: caps)
            plugin.gst_element = SimpleNamespace(
                get_static_pad=lambda name: pad if name == "sink" else None
            )
            sample = object()
            sample_factory = SimpleNamespace(
                new=lambda actual_buffer, actual_caps, segment, info: (
                    sample
                    if (actual_buffer, actual_caps, segment, info)
                    == (buffer, caps, None, None)
                    else None
                )
            )
            with mock.patch.object(
                native_target, "Gst", SimpleNamespace(Sample=sample_factory)
            ):
                plugin.process_buffer(buffer)
            self.assertEqual(
                runtime.routes, [(buffer, binding, "damage", sample, caps)]
            )
        finally:
            unregister_native_runtime(binding.descriptor_sha256, runtime)

    def test_shared_config_declares_native_tee_and_four_exact_routes(self) -> None:
        artifact = build_native_module_artifact(descriptor(SHARED_TOPOLOGY), source())
        topology = artifact["module_config"]["parameters"]["checkpoint_native_topology"]
        self.assertEqual(
            topology["shared_prefix"],
            ["zeromq_source_bin", "savant_rs_video_decode_bin:nvv4l2decoder", "nvstreammux", "nvvideoconvert", "capsfilter:video/x-raw,format=RGB", "tee"],
        )
        self.assertEqual(topology["route_count"], 4)
        self.assertEqual(tuple(route["branch"] for route in topology["routes"]), BRANCHES)
        self.assertTrue(all(route["max_size_buffers"] == 1 for route in topology["routes"]))
        self.assertTrue(all(route["drop_policy"] == "drop_newest" for route in topology["routes"]))
        self.assertTrue(all(route["fanout_name"].startswith("vast_savant_route_fanout_") for route in topology["routes"]))

    def test_matrix_preserves_twenty_four_and_six_process_identities(self) -> None:
        baseline = [descriptor(BASELINE_TOPOLOGY, stream, branch) for stream in range(6) for branch in BRANCHES]
        shared = [descriptor(SHARED_TOPOLOGY, stream) for stream in range(6)]
        sources = {stream: source(stream) for stream in range(6)}
        baseline_matrix = build_native_module_matrix(baseline, sources)
        shared_matrix = build_native_module_matrix(shared, sources)
        self.assertEqual(len(baseline_matrix), 24)
        self.assertEqual(len(shared_matrix), 6)
        self.assertEqual(
            {row["module_id"] for row in baseline_matrix},
            {row["module_id"] for row in baseline},
        )
        self.assertEqual(
            {row["module_id"] for row in shared_matrix},
            {row["module_id"] for row in shared},
        )
        self.assertTrue(all(not row["publication_ready"] for row in baseline_matrix + shared_matrix))

    def test_ingress_filter_requires_external_zeromq_and_exact_eight_tags(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        runtime = FakeRuntime()
        register_native_runtime(binding.descriptor_sha256, runtime)
        try:
            frame = FakeFrame(binding)
            self.assertTrue(SavantAdmissionIngressFilter(binding_json=artifact["binding_json"])(frame))
            self.assertEqual(runtime.admitted, [(frame, binding)])
            frame.content = ("internal", None)
            with self.assertRaisesRegex(SavantNativeModuleError, "external zeromq"):
                SavantAdmissionIngressFilter(binding_json=artifact["binding_json"])(frame)
        finally:
            unregister_native_runtime(binding.descriptor_sha256, runtime)

    def test_native_identity_uses_actual_nvds_values_and_exact_admission_tags(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        video_frame = FakeFrame(binding)
        native = SimpleNamespace(source_id=3, frame_num=41, buf_pts=video_frame.pts)
        frame_meta = SimpleNamespace(
            video_frame=video_frame,
            frame_meta=native,
            get_tag=lambda name: video_frame._tags[name],
        )
        identity = build_native_frame_identity(
            binding=binding,
            frame_meta=frame_meta,
            decoder_factory="nvv4l2decoder",
            decoder_gpu_id=0,
            mux_gst_buffer_pts_ns=123,
        )
        self.assertEqual(identity["module_id"], binding.module_id)
        self.assertEqual(identity["module_frame_id"], 6)
        self.assertEqual(identity["frame_id"], 6)
        self.assertEqual(identity["nvds_source_id"], 3)
        self.assertEqual(identity["nvds_frame_num"], 41)
        self.assertEqual(identity["nvds_buf_pts_ns"], video_frame.pts)
        self.assertEqual(identity["mux_gst_buffer_pts_ns"], 123)
        native.source_id = 0
        with self.assertRaisesRegex(SavantNativeModuleError, "source_id"):
            build_native_frame_identity(
                binding=binding,
                frame_meta=frame_meta,
                decoder_factory="nvv4l2decoder",
                decoder_gpu_id=0,
                mux_gst_buffer_pts_ns=123,
            )


if __name__ == "__main__":
    unittest.main()
