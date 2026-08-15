#!/bin/bash
# ISA gate for AI-2 CPU-variant binaries. Disassembles every ELF under DIR and
# fails if it contains instructions the variant's target CPU cannot execute.
#
#   isa-check.sh <variant> <dir>
#     baseline  pure SSE2 (+popcnt): no SSE4.1, no SSE4.2, no AVX/FMA/F16C
#     noavx     up to SSE4.2:        no AVX/FMA/F16C
#     avx2      no gate (AVX-512 is still rejected, we never target it)
#
# Why: ggml assumes SSE4.2 and gcc emitted pinsrq (SSE4.1) even in plain C++,
# so a "no-AVX" build SIGILLed on the 2011 A4-3305M. This scan caught it before
# it reached a user; run it in the PKGBUILD check() so it can never regress.
set -euo pipefail

variant=${1:?variant}
dir=${2:?dir}

# AT&T mnemonics as printed by objdump. Word-anchored, so 'pinsrq' will not
# match inside longer names and 'popcnt' (allowed) is not listed.
SSE41='pinsr[bdq]|pextr[bdq]|pblendw|pblendvb|blendp[sd]|blendvp[sd]|pmulld|pmuldq|roundp[sd]|rounds[sd]|ptest|pmovsx[bwd][wdq]|pmovzx[bwd][wdq]|pmins[bd]|pmaxs[bd]|pminu[wd]|pmaxu[wd]|packusdw|phminposuw|dpp[sd]|mpsadbw|insertps|extractps|movntdqa|pcmpeqq'
SSE42='pcmpgtq|pcmpestri|pcmpestrm|pcmpistri|pcmpistrm|crc32[bwlq]?'
# Every VEX/EVEX-encoded instruction is spelled with a leading 'v' in AT&T
# syntax (vmovaps, vpxor, vfmadd..., vcvtph2ps, vzeroupper). Exclude the
# handful of legacy 'v'-mnemonics that are not AVX.
AVX='v[a-z0-9]+'
AVX_EXCLUDE='^(verr|verw|vmcall|vmclear|vmlaunch|vmptrld|vmptrst|vmread|vmresume|vmwrite|vmxoff|vmxon|vmfunc)$'
AVX512='(zmm|\{k[0-7]\}|\{z\})'

case "$variant" in
  baseline) forbidden="$SSE41|$SSE42|$AVX" ;;
  noavx)    forbidden="$AVX" ;;
  avx2)     forbidden='' ;;
  *) echo "isa-check: unknown variant '$variant'" >&2; exit 2 ;;
esac

status=0
while IFS= read -r -d '' f; do
  # skip non-ELF files cheaply
  head -c4 "$f" 2>/dev/null | grep -q $'\x7fELF' || continue
  # objdump -d output: addr:\tbytes\tmnemonic operands. Take the mnemonic column.
  disasm=$(objdump -d --no-show-raw-insn "$f" 2>/dev/null | awk -F'\t' 'NF>=2 {split($2,a," "); print a[1]}' | sort -u)
  hits=""
  if [ -n "$forbidden" ]; then
    hits=$(printf '%s\n' "$disasm" | grep -Ex "$forbidden" | grep -Evx "$AVX_EXCLUDE" || true)
  fi
  hits512=$(objdump -d --no-show-raw-insn "$f" 2>/dev/null | grep -Ec "$AVX512" || true)
  if [ -n "$hits" ] || [ "${hits512:-0}" -gt 0 ]; then
    echo "isa-check FAIL [$variant] $f"
    [ -n "$hits" ] && printf '   %s\n' $hits
    [ "${hits512:-0}" -gt 0 ] && echo "   avx-512 register/mask usage: $hits512 lines"
    status=1
  else
    echo "isa-check ok   [$variant] $f"
  fi
done < <(find "$dir" -type f \( -perm -u+x -o -name '*.so*' \) -print0)

exit $status
