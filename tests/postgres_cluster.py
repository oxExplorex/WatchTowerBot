"""Disposable local PostgreSQL, never the configured application database."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import socket
import subprocess


def find_postgres_bin():
    executable = shutil.which("initdb")
    if executable:
        return Path(executable).parent
    root = Path("C:/Program Files/PostgreSQL")
    if root.exists():
        candidates = sorted(root.glob("*/bin/initdb.exe"), key=lambda path: tuple(
            int(part) for part in path.parent.parent.name.split(".") if part.isdigit()), reverse=True)
        if candidates:
            return candidates[0].parent
    raise RuntimeError("PostgreSQL test binaries not found; pass --postgres-bin")


@contextmanager
def temporary_postgres(root, binary_dir=None):
    root = Path(root).resolve()
    binary = Path(binary_dir).resolve() if binary_dir else find_postgres_bin()
    cluster = root / "cluster"
    if cluster.exists():
        raise RuntimeError("Refusing to reuse a PostgreSQL test cluster")
    root.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if (binary / "initdb.exe").is_file() else ""
    executable = lambda name: str(binary / (name + suffix))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    def run(name, args):
        # A background postgres can inherit PIPE handles on Windows and prevent
        # communicate() from reaching EOF even after pg_ctl has exited.
        output = root / f"{name}.log"
        with output.open("wb") as stream:
            result = subprocess.run([executable(name), *args], stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError(f"Test PostgreSQL {name} failed: {output.read_text(encoding='utf-8', errors='replace')[-4000:]}")

    run("initdb", ["-D", str(cluster), "-U", "watchtower_test", "-A", "trust", "--no-locale", "--encoding=UTF8"])
    started = False
    try:
        # This cluster holds synthetic data only, listens on loopback and has its
        # own dynamic port. No installed service or application config is used.
        run("pg_ctl", ["-D", str(cluster), "-l", str(root / "server.log"), "-w", "-t", "30", "start",
                       "-o", f"-h 127.0.0.1 -p {port} -c max_connections=30"])
        started = True
        yield {"host": "127.0.0.1", "port": port, "user": "watchtower_test", "password": "", "database": "postgres"}
    finally:
        if started or (cluster / "postmaster.pid").exists():
            # This exact directory was created above; never stop an installed PG.
            run("pg_ctl", ["-D", str(cluster), "-w", "-t", "30", "stop", "-m", "fast"])
