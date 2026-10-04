"""Bounded process receipts; kill the whole child group on timeout/cancellation."""
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from autolab.implementation.harness import sanitized_environment
from .models import ProcessReceipt


async def execute(payload, config, *, timeout_seconds=None):
    worker = Path(__file__).with_name('worker.py')
    process = await asyncio.create_subprocess_exec(sys.executable,'-I','-S',str(worker),
        cwd=config.working_directory, env=sanitized_environment(), start_new_session=True,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    buffers = {'out':bytearray(),'err':bytearray()}; exceeded = False
    async def capture(stream,key,limit):
        nonlocal exceeded
        while chunk := await stream.read(4096):
            available = max(0,limit-len(buffers[key])); buffers[key].extend(chunk[:available])
            if len(chunk)>available:
                exceeded=True
                raise ValueError('Output limit exceeded')
    async def communicate():
        process.stdin.write(json.dumps(payload,allow_nan=False).encode())
        await process.stdin.drain(); process.stdin.close()
        await asyncio.gather(capture(process.stdout,'out',config.max_output_bytes),
                             capture(process.stderr,'err',config.max_log_bytes))
        await process.wait()
    timed_out = cancelled = False
    task = asyncio.create_task(communicate())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout_seconds or config.timeout_seconds)
    except (TimeoutError,asyncio.CancelledError,ValueError,BrokenPipeError,ConnectionResetError) as exc:
        timed_out=isinstance(exc,TimeoutError); cancelled=isinstance(exc,asyncio.CancelledError)
        if process.returncode is None:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        await process.wait()
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    out=buffers['out'].decode(errors='replace'); err=buffers['err'].decode(errors='replace')
    messages=[]
    for line in out.splitlines():
        try:
            def reject_constant(value): raise ValueError('Nonfinite protocol value')
            msg=json.loads(line,parse_constant=reject_constant)
            if isinstance(msg,dict): messages.append(msg)
        except ValueError: pass  # Retained as bounded diagnostic output, never successful evidence.
    return ProcessReceipt(exit_status=process.returncode,timed_out=timed_out,cancelled=cancelled,
        output_exceeded=exceeded,stdout=out,stderr=err,messages=messages)
