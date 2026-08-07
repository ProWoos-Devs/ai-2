from ai2.detect import nominal_gib, parse_cpuinfo, parse_meminfo_mib

CPUINFO = """\
processor\t: 0
model name\t: Intel(R) Core(TM) i5-3320M CPU @ 2.60GHz
flags\t\t: fpu vme sse sse2 ssse3 sse4_1 sse4_2 avx fma lm
processor\t: 1
model name\t: Intel(R) Core(TM) i5-3320M CPU @ 2.60GHz
flags\t\t: fpu vme sse sse2 ssse3 sse4_1 sse4_2 avx fma lm
"""


def test_parse_cpuinfo():
    model, flags = parse_cpuinfo(CPUINFO)
    assert model == "Intel(R) Core(TM) i5-3320M CPU @ 2.60GHz"
    assert flags == {"avx", "fma", "sse4_2"}
    assert "avx2" not in flags


def test_parse_meminfo():
    assert parse_meminfo_mib("MemTotal:        1980000 kB\nMemFree: 1 kB\n") == 1933


def test_nominal_rounding():
    assert nominal_gib(1933) == 2      # 2 GB machine reporting less
    assert nominal_gib(3800) == 4
    assert nominal_gib(15380) == 16    # 16 GB machine with reserved memory
    assert nominal_gib(31900) == 32
    assert nominal_gib(300000) == 292  # beyond the table, floor of real GiB
