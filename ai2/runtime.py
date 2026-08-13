"""Runtime Engine, locates the CPU-variant llama.cpp build and drives it.

Today the binaries are placed manually (proven on RMM-PC in ~/llama). Once the
signed AI-2 pacman repo exists, install_runtime() will pull the right variant
package (llama.cpp-baseline / -noavx / -avx2) for hw.cpu_variant; the finder
below already prefers a per-variant path so that transition is a drop-in.
"""

from __future__ import annotations

import glob
import os
import subprocess

# Searched in order; first dir containing a llama-bench wins.
def _runtime_candidates(variant: str) -> list[str]:
    return [
        os.environ.get("AI2_RUNTIME_DIR", ""),
        f"/usr/lib/ai2/runtimes/llama.cpp-{variant}",
        "/opt/ai2/llama",
        os.path.expanduser("~/llama"),
    ]


def find_runtime(variant: str) -> str | None:
    for d in _runtime_candidates(variant):
        if d and os.path.isfile(os.path.join(d, "llama-bench")):
            return d
    return None


# Searched in order; smallest gguf is used as the benchmark's fixed workload.
_MODEL_DIRS = [
    os.environ.get("AI2_MODEL_DIR", ""),
    "/var/lib/ai2/models",
    os.path.expanduser("~/models"),
]


def find_test_model() -> str | None:
    env = os.environ.get("AI2_TEST_MODEL")
    if env and os.path.isfile(env):
        return env
    ggufs: list[str] = []
    for d in _MODEL_DIRS:
        if d and os.path.isdir(d):
            ggufs += glob.glob(os.path.join(d, "*.gguf"))
    if not ggufs:
        return None
    return min(ggufs, key=os.path.getsize)


def run_llama_bench(runtime_dir: str, model: str, threads: int,
                    pp: int = 32, ng: int = 32, timeout: int = 600) -> str:
    """Run llama-bench and return its stdout (markdown table). Raises on failure."""
    env = dict(os.environ, LD_LIBRARY_PATH=runtime_dir)
    cmd = [
        os.path.join(runtime_dir, "llama-bench"),
        "-m", model, "-p", str(pp), "-n", str(ng),
        "-r", "1", "-t", str(threads), "-o", "md",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"llama-bench failed (exit {proc.returncode}): "
                           f"{proc.stderr.strip()[:300]}")
    return proc.stdout
