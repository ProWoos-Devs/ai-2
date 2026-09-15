"""The ISA gate itself, on tiny shared objects assembled here: it must reject
what the oldest target cannot execute and accept what it can. Skipped where
no toolchain is installed."""
import shutil
import subprocess

import pytest

GATE = "packaging/ai2-llama-cpp/isa-check.sh"

pytestmark = pytest.mark.skipif(not (shutil.which("gcc") and shutil.which("objdump")),
                                reason="needs gcc and objdump")


def _so(tmp_path, name, insn):
    s = tmp_path / f"{name}.s"
    s.write_text(f".text\n.globl f\nf:\n  {insn}\n  ret\n")
    so = tmp_path / f"{name}.so"
    subprocess.run(["gcc", "-shared", "-nostdlib", "-o", str(so), str(s)], check=True)
    return so


def _gate(mode, path):
    return subprocess.run(["bash", GATE, mode, str(path)], capture_output=True, text=True)


@pytest.mark.parametrize("insn, baseline_ok, noavx_ok", [
    ("paddb %xmm1, %xmm0", True, True),                # SSE2: every target
    ("pshufb %xmm1, %xmm0", False, True),              # SSSE3: not on the A4-3305M (gap closed 2026-09-15)
    ("pmaddubsw %xmm1, %xmm0", False, True),           # SSSE3
    ("pinsrq $1, %rax, %xmm0", False, True),           # SSE4.1: the instruction that SIGILLed in 2026-08
    ("crc32q %rax, %rbx", False, True),                # SSE4.2
    ("vpaddb %xmm1, %xmm2, %xmm0", False, False),      # AVX
])
def test_gate_modes(tmp_path, insn, baseline_ok, noavx_ok):
    so = _so(tmp_path, "t", insn)
    assert (_gate("baseline", so).returncode == 0) is baseline_ok, _gate("baseline", so).stdout
    assert (_gate("noavx", so).returncode == 0) is noavx_ok, _gate("noavx", so).stdout
