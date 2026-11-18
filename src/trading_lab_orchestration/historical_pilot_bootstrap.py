"""Trusted streaming entry point for the sealed 5.5B worker."""

import base64
import errno
import io
import resource
import socket
import subprocess
import sys
import tarfile


def main():
    try:
        with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM):
            raise RuntimeError("VM-to-host socket creation must be blocked")
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM, errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT):
            raise
    archive = base64.b64decode(sys.stdin.buffer.read(24 * 1024 * 1024), validate=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as sources:
        sources.extractall("/work", filter="data")
    command = sys.argv[2:]
    if command != ["-m", "trading_lab_orchestration.historical_pilot_guest"]:
        raise ValueError("Unexpected streaming worker")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/work",
        "TMPDIR": "/work",
        "PYTHONPATH": "/work/src",
        "PYTHONNOUSERSITE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "LC_ALL": "C.UTF-8",
    }
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024, 512 * 1024))
    # Stdout goes to the original supervised pipe. Keep the legacy file-size limit
    # for ordinary files and send diagnostic stderr on its own bounded host pipe.
    return subprocess.run(
        [sys.executable, "-B", *command],
        cwd="/work",
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=float(sys.argv[1]),
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
