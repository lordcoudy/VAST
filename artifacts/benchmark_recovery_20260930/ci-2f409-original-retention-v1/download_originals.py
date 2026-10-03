"""One read-only capture of four fixed original GitHub artifacts; no URL retention."""
import hashlib, json, os, pathlib, subprocess, time, urllib.request, urllib.parse, zipfile

ROOT = pathlib.Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = ROOT / 'artifacts/benchmark_recovery_20260930/ci-2f409-original-retention-v1'
ROWS = (
    (36735694943, 'cpu', 11109155148, 1894786, '91dc59e7be790e0515259c424d5ae8ab956f6c931b7df383897a7f225ae36a33'),
    (36735694943, 'host', 11107495522, 281293, 'a021419046a785db38936d379837406c848008b044b826963d75b5c6ed283d8a'),
)

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(newurl).hostname != 'api.github.com':
            result.remove_header('Authorization')
        return result

began = time.monotonic_ns()
environment = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
credential = subprocess.run(['/mnt/c/Program Files/Git/cmd/git.exe', 'credential', 'fill'],
    input=b'protocol=https\nhost=github.com\n\n', stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL, env=environment, timeout=20, check=True)
fields = dict(line.split(b'=', 1) for line in credential.stdout.splitlines() if b'=' in line)
token = fields[b'password'].decode('utf-8')
del credential, fields
opener = urllib.request.build_opener(Redirect())
captured = []
for run, kind, artifact, expected_size, expected_sha in ROWS:
    directory = OUT / (str(run) + '-' + kind)
    directory.mkdir(exist_ok=False)
    destination = directory / 'original-artifact.zip'
    try:
        request = urllib.request.Request('https://api.github.com/repos/lordcoudy/VAST/actions/artifacts/' + str(artifact) + '/zip',
            headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'VAST-readonly-original-CI-capture',
                     'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        count, digest = 0, hashlib.sha256()
        with opener.open(request, timeout=45) as response, destination.open('xb') as stream:
            while block := response.read(65536):
                count += len(block)
                if count > 8 * 1024 * 1024:
                    raise ValueError('artifact byte cap')
                stream.write(block); digest.update(block)
            stream.flush(); os.fsync(stream.fileno())
        if count != expected_size or digest.hexdigest() != expected_sha:
            raise ValueError('original provider size or SHA drift')
        decoded, inventory = 0, []
        with zipfile.ZipFile(destination) as archive:
            if len(archive.infolist()) > 4096:
                raise ValueError('ZIP member cap')
            names = set()
            for item in archive.infolist():
                name = pathlib.PurePosixPath(item.filename)
                if item.filename in names or name.is_absolute() or '\\' in item.filename or '..' in name.parts or ':' in item.filename:
                    raise ValueError('unsafe or duplicate ZIP path')
                names.add(item.filename); decoded += item.file_size
                if decoded > 32 * 1024 * 1024:
                    raise ValueError('decoded ZIP cap')
                member_hash = hashlib.sha256()
                with archive.open(item) as member:
                    while block := member.read(65536):
                        member_hash.update(block)
                inventory.append({'name': item.filename, 'size_bytes': item.file_size, 'sha256': member_hash.hexdigest(), 'crc32': item.CRC})
        row = {'run_id': run, 'kind': kind, 'artifact_id': artifact, 'path': str(destination.relative_to(ROOT)),
               'size_bytes': count, 'sha256': digest.hexdigest(), 'provider_digest_matched': True,
               'zip_members': len(inventory), 'decoded_size_bytes': decoded, 'all_member_crc_verified': True, 'members': inventory}
        captured.append(row)
        with (directory / 'zip-readonly-inventory.v1.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(row, stream, sort_keys=True, separators=(',', ':')); stream.write('\n')
    except BaseException as error:
        with (directory / 'capture-failure.v1.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump({'failed': True, 'exception_type': type(error).__name__, 'http_status': getattr(error, 'code', None),
                       'run_id': run, 'artifact_id': artifact, 'temporary_url_saved': False}, stream)
        raise SystemExit(1) from None
del token
with (OUT / 'download-terminal.v1.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump({'read_only': True, 'originals': [{'run_id': r['run_id'], 'kind': r['kind'], 'artifact_id': r['artifact_id'],
       'size_bytes': r['size_bytes'], 'sha256': r['sha256']} for r in captured], 'elapsed_s': (time.monotonic_ns()-began)/1e9,
       'temporary_url_saved': False, 'workflow_action': None, 'full_ci_successful': False}, stream, sort_keys=True)
    stream.write('\n')
print(json.dumps({'captured_original_zips': len(captured), 'crc_verified': True}))
