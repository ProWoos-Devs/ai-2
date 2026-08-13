from ai2.detect import Hardware, nominal_gib, parse_cpuinfo, parse_meminfo_mib

CPUINFO = """\
processor\t: 0
model name\t: Intel(R) Core(TM) i5-3320M CPU @ 2.60GHz
flags\t\t: fpu vme sse sse2 ssse3 sse4_1 sse4_2 avx fma lm
processor\t: 1
model name\t: Intel(R) Core(TM) i5-3320M CPU @ 2.60GHz
flags\t\t: fpu vme sse sse2 ssse3 sse4_1 sse4_2 avx fma lm
"""

# Real flags observed on the RMM-PC test machine (AMD A4-3305M, 2011 Llano):
# SSE2 + SSE4a + popcnt, but NO sse4_1 and NO avx.
LLANO_CPUINFO = """\
model name\t: AMD A4-3305M APU with Radeon(tm) HD Graphics
flags\t\t: fpu vme de sse sse2 ht popcnt sse4a misalignsse
"""


def test_parse_cpuinfo():
    model, flags = parse_cpuinfo(CPUINFO)
    assert model == "Intel(R) Core(TM) i5-3320M CPU @ 2.60GHz"
    assert flags == {"avx", "fma", "sse4_1", "sse4_2"}
    assert "avx2" not in flags


def test_cpu_variant_three_way():
    # avx2 machine
    assert Hardware(flags={"avx", "avx2", "fma", "sse4_1", "sse4_2"}).cpu_variant == "avx2"
    # Ivy Bridge i5: SSE4.1/4.2 + AVX but no AVX2 -> noavx
    assert Hardware(flags={"avx", "fma", "sse4_1", "sse4_2"}).cpu_variant == "noavx"
    # SSE4.1 only, no AVX -> noavx
    assert Hardware(flags={"sse4_1", "sse4_2"}).cpu_variant == "noavx"
    # The real Llano case: no sse4_1, no avx -> baseline (SSE2)
    _, llano_flags = parse_cpuinfo(LLANO_CPUINFO)
    assert "sse4_1" not in llano_flags
    assert Hardware(flags=llano_flags).cpu_variant == "baseline"


def test_parse_meminfo():
    assert parse_meminfo_mib("MemTotal:        1980000 kB\nMemFree: 1 kB\n") == 1933


def test_nominal_rounding():
    assert nominal_gib(1933) == 2      # 2 GB machine reporting less
    assert nominal_gib(3800) == 4
    assert nominal_gib(15380) == 16    # 16 GB machine with reserved memory
    assert nominal_gib(31900) == 32
    assert nominal_gib(300000) == 292  # beyond the table, floor of real GiB
