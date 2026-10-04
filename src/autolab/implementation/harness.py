"""Timeout, explicit environment, isolated cwd and bounded pipe capture."""
import asyncio
import hashlib
import json
import os
import signal
import sys
from pathlib import Path
from .models import CheckReport
from .validation import static_checks


def sanitized_environment():
    # Allowlist, never copy the parent's environment. No provider credentials,
    # proxy settings, Python startup hooks, home directory or PATH inheritance.
    return {'PYTHONHASHSEED': '0', 'LANG': 'C', 'LC_ALL': 'C'}


def framework_source_hash():
    root=Path(__file__).parent
    files={name:(root/name).read_text() for name in ('harness.py','worker.py','validation.py','contract.py')}
    return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()


async def run_checks(files, plan, contract, workspace, *, timeout_seconds=15):
    static = static_checks(files, plan, contract)
    if not static.static_pass: return static  # Unsafe code never reaches a process.
    worker = Path(__file__).with_name('worker.py')
    payload = json.dumps({'files': files, 'contract': contract.model_dump(mode='json'),
        'framework_source_sha256':framework_source_hash()}).encode()
    process = await asyncio.create_subprocess_exec(sys.executable, '-I', '-S', str(worker),
        cwd=workspace, env=sanitized_environment(), start_new_session=True,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    async def capture(stream):
        chunks = []; size = 0
        while chunk := await stream.read(4096):
            size += len(chunk)
            if size > 8192: raise RuntimeError('Worker output exceeded bound')
            chunks.append(chunk)
        return b''.join(chunks)
    async def communicate():
        process.stdin.write(payload)
        await process.stdin.drain()
        process.stdin.close()
        out, err = await asyncio.gather(capture(process.stdout), capture(process.stderr))
        await process.wait()
        return out, err
    timed_out = False
    try:
        out, err = await asyncio.wait_for(communicate(), timeout_seconds)
        output = out.decode(errors='replace')[:4000]
        detail = json.loads(output)
        passed = (process.returncode == 0 and detail.get('status') == 'PASS'
            and detail.get('environment_sanitized') is True and detail.get('network_policy') == 'offline'
            and detail.get('scientific_run') is False)
    except (TimeoutError, RuntimeError, ValueError, asyncio.CancelledError) as exc:
        timed_out = isinstance(exc, TimeoutError)
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        if isinstance(exc, asyncio.CancelledError): raise
        output = 'Worker timeout' if timed_out else 'Worker output/protocol failure'
        detail = {}; passed = False
    return CheckReport(static_pass=True, tests_pass=passed, test_count=detail.get('framework_count', 0),
        generated_count=detail.get('generated_count', 0), exit_status=process.returncode,
        timed_out=timed_out, output=output, findings=[] if passed else [output])
