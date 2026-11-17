"""Trusted container entry point, staged separately from the delivery."""

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
    output = "/work/check-output"
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
    with open(output, "w+b") as log:
        result = subprocess.run(
            [sys.executable, "-B", *command],
            cwd="/work",
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=float(sys.argv[1]),
            check=False,
        )
        log.seek(0)
        sys.stdout.buffer.write(log.read(512 * 1024))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
