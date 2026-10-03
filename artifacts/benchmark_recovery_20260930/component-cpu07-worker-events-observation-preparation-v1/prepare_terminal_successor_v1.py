"""Source-only terminal-event successor; this does not execute an engine query."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
old_path = HERE / 'observe_original_primary_worker_events_v4.py'
old = old_path.read_bytes()
assert hashlib.sha256(old).hexdigest() == 'dfe892ea547de7fa8c4a1f24b2da0d9299ab2cad6deb8ef7212c6b7117583d5a'
text = old.decode('ascii')
changes = []

def change(before, after, reason):
    global text
    assert text.count(before) == 1, reason
    text = text.replace(before, after)
    changes.append({'before': before, 'after': after, 'reason': reason})

change("OUT=HERE/'original-observation-attempt01'", "OUT=HERE/'original-terminal-events-observation-attempt01'", 'Exclusive new output namespace; original failed query remains untouched.')
change("for name in (\"vast-gst-analytics-f5a8e4aa391f4df1-vehicle-type-cpu\",): ARGV+=['--filter','container='+name]", "OBSERVED_CID='893b2b02a18906c5d7f840e2515e8f2fb8253c396cf4c2a3756efd1513f166aa'\nTERMINAL_ACTIONS=('die','oom','kill','destroy')\nARGV+=['--filter','container='+OBSERVED_CID]\nfor action in TERMINAL_ACTIONS:ARGV+=['--filter','event='+action]", 'One physically recovered original CID; terminal events only, same original interval/caps.')
change(" _,self_pin=hold(Path(__file__),limit=65536)", " prefix_fd,prefix_pin=hold(HERE/'original-observation-attempt01/stdout.raw','9deb990e0bb431026ca5781c8cbf4c3d3898545806a9c9dd5052280e45e05978',8192)\n assert prefix_pin['size_bytes']==8192\n prefix=os.pread(prefix_fd,8193,0);assert len(prefix)==8192\n prefix_lines=prefix.split(b'\\n');assert len(prefix_lines)==25 and len(prefix_lines[-1])==20\n primary_name='vast-gst-analytics-f5a8e4aa391f4df1-vehicle-type-cpu'\n for line in prefix_lines[:-1]:\n  v=json.loads(line);assert v['type']=='container' and v['id']==OBSERVED_CID and v['name']==primary_name\n  assert v['image']==NAMES[primary_name]['image_id'] and type(v['time_ns']) is int and START_NS<=v['time_ns']<=END_NS\n _,self_pin=hold(Path(__file__),limit=65536)", 'Hold/recheck original partial-prefix bytes and independently bind the recovered CID/name/image; do not infer terminal fate from that prefix.')
change("  'input_descriptors':inputs,'observer_source':self_pin,'names':NAMES,'start_ns':START_NS,'end_ns':END_NS,", "  'input_descriptors':inputs,'observer_source':self_pin,'original_partial_prefix':prefix_pin,'observed_cid':OBSERVED_CID,'terminal_action_filters':TERMINAL_ACTIONS,'names':NAMES,'start_ns':START_NS,'end_ns':END_NS,", 'Actual dispatch records recovered-CID provenance and exact filters.')
change("  'scope':'one read-only primary vehicle_type/cpu historical event query; original daemon-ID retained; single query does not independently reobserve current daemon ID'})", "  'scope':'one read-only original vehicle_type/cpu CID terminal-events historical query; original daemon-ID retained; single query does not independently reobserve current daemon ID'})", 'Accurate narrower scope; no contemporaneous authority claim.')
change("  if child.returncode!=0:raise ValueError('original event query returned'+str(child.returncode))\n finally:", "  if child.returncode!=0:raise ValueError('original event query returned'+str(child.returncode))\n except BaseException as exc:latch(exc)\n finally:", 'Latch the first body failure before cleanup; cleanup errors remain additional, without changing cleanup or deadlines.')
change("     assert v['type']=='container' and v['name']=='vast-gst-analytics-f5a8e4aa391f4df1-vehicle-type-cpu' and re.fullmatch('[0-9a-f]{64}',v['id'])", "     assert v['type']=='container' and v['name']=='vast-gst-analytics-f5a8e4aa391f4df1-vehicle-type-cpu' and v['id']==OBSERVED_CID and v['action'] in TERMINAL_ACTIONS", 'Every complete returned event must match exact original CID/name and a requested terminal action.')
new = text.encode('ascii')
old_ast = ast.parse(old)
new_ast = ast.parse(new)
old_functions = {node.name: ast.dump(node, include_attributes=False) for node in old_ast.body if isinstance(node, ast.FunctionDef)}
new_functions = {node.name: ast.dump(node, include_attributes=False) for node in new_ast.body if isinstance(node, ast.FunctionDef)}
assert old_functions == new_functions
compile(new_ast, 'prepared-terminal-successor', 'exec')
new_path = HERE / 'observe_original_primary_worker_terminal_events_v5.py'
with new_path.open('xb') as output:
    output.write(new)

def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

prep = {'schema_version': 1, 'state': 'prepared_unexecuted_pending_independent_source_peer_and_root_grant', 'engine_commands_executed_by_preparation': 0, 'source': pin(new_path), 'original_source': pin(old_path), 'original_query_report': pin(HERE / 'original-observation-attempt01/execution.v1.json'), 'original_raw_prefix': pin(HERE / 'original-observation-attempt01/stdout.raw'), 'original_query_outer_capture': pin(HERE / 'original-observation-outer-attempt01/capture.v1.json'), 'original_metadata_closure': pin(HERE / 'original-observation-closure-review.v1.json'), 'original_later_process_closure': pin(HERE / 'original-observation-later-process-closure.v1.json'), 'changes': changes, 'all_function_asts_identical': sorted(old_functions), 'bounds_unchanged': {'command_seconds': 2, 'stdout_bytes': 8192, 'stderr_bytes': 1024, 'records': 32, 'whole_work_seconds': 30, 'cleanup_seconds': 10}, 'future_output': str(HERE / 'original-terminal-events-observation-attempt01'), 'future_outer_output': str(HERE / 'original-terminal-events-observation-outer-attempt01'), 'observed_container_id': '893b2b02a18906c5d7f840e2515e8f2fb8253c396cf4c2a3756efd1513f166aa', 'same_original_name': 'vast-gst-analytics-f5a8e4aa391f4df1-vehicle-type-cpu', 'same_original_image': 'sha256:ce138982695ea6d8218a9137bb858090a782e83e687be8fc252a32dc0bd9d5f9', 'same_original_interval_ns': [1790823221323071118, 1790823586186876374], 'filters': ['type=container', 'container=893b2b02a18906c5d7f840e2515e8f2fb8253c396cf4c2a3756efd1513f166aa', 'event=die', 'event=oom', 'event=kill', 'event=destroy'], 'future_actual_owners': None, 'future_actual_result': None, 'acceptance': False, 'limitations': ['Original first query failed; its prefix cannot prove absent death/OOM.', 'Later query remains subject to daemon last256-event retention and unchanged caps.', 'Current daemon ID is not independently queried; exact original CLI bytes/socket and original ID provenance stay explicit.', 'No image/model/worker/protocol/budget changes or authority renewal occur.']}
raw = (json.dumps(prep, sort_keys=True, indent=2) + '\n').encode('ascii')
path = HERE / 'preparation.v4.json'
with path.open('xb') as output:
    output.write(raw)
print(json.dumps({'source': pin(new_path), 'preparation': pin(path), 'function_count': len(old_functions)}))
