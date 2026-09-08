"""Small durable runtime records and process-safe, reentrant mutation locks."""
from __future__ import annotations

import contextlib
import hashlib
import functools
import json
import os
from pathlib import Path
import threading
import time
import tempfile
import uuid
from .atomic_files import replace

_locks = {}
_guard = threading.Lock()
_held = threading.local()


@contextlib.contextmanager
def locked(root, name='campaign', timeout=60):
    key = os.path.normcase(str(Path(root).resolve()))+'|'+name
    with _guard:
        mutex = _locks.setdefault(key, threading.RLock())
    with mutex:
        depths = getattr(_held, 'depths', None)
        if depths is None:
            depths = _held.depths = {}
        if depths.get(key):
            depths[key] += 1
            try:
                yield
            finally:
                depths[key] -= 1
            return
        if os.name=='nt':
            # Named OS mutexes leave no files in a read-only/unstarted cohort,
            # and disappear when the last process handle closes (including crash).
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
            kernel.CreateMutexW.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            kernel.WaitForSingleObject.restype=wintypes.DWORD
            kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.CreateMutexW(None,False,'Local\\EDHGauntlet-'+hashlib.sha256(key.encode()).hexdigest())
            if not handle:raise ctypes.WinError(ctypes.get_last_error())
            acquired=False
            try:
                outcome=kernel.WaitForSingleObject(handle,int(timeout*1000))
                if outcome==258:raise TimeoutError('Runtime mutation lock busy: '+key)
                if outcome not in {0,128}:raise ctypes.WinError(ctypes.get_last_error())
                acquired=True;depths[key]=1
                yield
            finally:
                depths.pop(key,None)
                if acquired:kernel.ReleaseMutex(handle)
                kernel.CloseHandle(handle)
            return
        path=Path(tempfile.gettempdir())/'edh-gauntlet-locks'/(hashlib.sha256(key.encode()).hexdigest()+'.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            start = time.monotonic()
            while True:
                try:
                    stream.seek(0)
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() - start >= timeout:
                        raise TimeoutError(f'Runtime mutation lock busy: {path}')
                    time.sleep(.05)
            depths[key] = 1
            try:
                yield
            finally:
                depths.pop(key, None)
                stream.seek(0)
                fcntl.flock(stream, fcntl.LOCK_UN)


def serialized(function):
    @functools.wraps(function)
    def wrapped(root, *args, **kwargs):
        with locked(root):
            return function(root, *args, **kwargs)
    return wrapped


def read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write(path, value):
    """Unique temporaries avoid collisions between independent publication lanes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def identity(value):
    from .pilot_handoff import fingerprint
    return fingerprint(value)


def checked_id(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise SystemExit('Invalid runtime record identity.')
    return value


def put(directory, value):
    digest = identity(value)
    path = Path(directory) / (digest + '.json')
    if not path.exists():
        write(path, value)
    elif read(path) != value:
        raise SystemExit('Immutable runtime record changed.')
    return digest


def get(directory, digest):
    value = read(Path(directory) / (checked_id(digest) + '.json'))
    if value is None or identity(value) != digest:
        raise SystemExit('Runtime record missing or corrupted.')
    return value
