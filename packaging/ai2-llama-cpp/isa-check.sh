#!/bin/bash
# ISA gate for AI-2 CPU-variant binaries. Disassembles every ELF under DIR and
# fails if it contains instructions the variant's target CPU cannot execute.
#
#   isa-check.sh <variant> <dir-or-file>
#     baseline  pure SSE2 (+popcnt): no SSE4.1, no SSE4.2, no AVX/FMA/F16C
#     noavx     up to SSE4.2:        no AVX/FMA/F16C
#     avx2      no gate (AVX-512 is still rejected, we never target it)
#   isa-check.sh ctors <file>
#     the load-safety gate for a dlopen'ed CPU variant: every constructor in
#     its .init_array is disassembled and must be clean for the pure-SSE2
#     machine, and the module may carry no IFUNC symbol and no IRELATIVE
#     relocation (those run at load time too). ggml's loader dlopens EVERY
#     variant before it can ask for its score, so an AVX variant runs its
#     static initializers on a non-AVX machine (llama.cpp PR 11780 was that
#     crash: a static __m128i in llamafile/sgemm.cpp). Direct calls made by a
#     constructor are not followed; that is the gate's limit.
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

ctors_check() {
  # $1: an ELF shared object. Prints one line per constructor, fails on the
  # first forbidden mnemonic, IFUNC symbol or IRELATIVE relocation.
  local f=$1 forbidden="$SSE41|$SSE42|$AVX" status=0
  local sec addr size lo hi n=0
  if readelf -sW "$f" | grep -q ' IFUNC '; then
    echo "ctors FAIL $f: IFUNC symbols (resolved at load time)"; status=1
  fi
  if readelf -rW "$f" | grep -q 'R_X86_64_IRELATIV'; then
    echo "ctors FAIL $f: IRELATIVE relocations (resolvers run at load time)"; status=1
  fi
  sec=$(readelf -SW "$f" | awk '$0 ~ /\.init_array/ { sub(/.*\.init_array[ ]+[A-Z_]+[ ]+/, ""); print $1, $3 }')
  if [ -z "$sec" ]; then
    echo "ctors ok   $f: no .init_array"; return $status
  fi
  addr=$((16#${sec%% *})); size=$((16#${sec##* }))
  # The entries, one 8-byte little-endian word each, from the section's raw
  # bytes. Modern binutils store the target address in place and compress
  # the relocation into .relr.dyn; an older link stores 0 and keeps the
  # address as the addend of a R_X86_64_RELATIVE entry in .rela.dyn.
  local words; words=$(readelf -x .init_array "$f" | awk '/^ *0x/ {for (i = 2; i <= 5 && i <= NF; i++) if ($i ~ /^[0-9a-f]{8}$/) printf "%s ", $i}')
  local i=0 w1 w2 target
  set -- $words
  while [ $# -ge 2 ]; do
    w1=$1; w2=$2; shift 2
    # bytes are printed in memory order: little-endian, so reverse each word's byte pairs
    target=$(( 16#$(echo "$w1$w2" | sed 's/\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)\(..\)/\8\7\6\5\4\3\2\1/') ))
    if [ "$target" -eq 0 ]; then
      local off; off=$(printf '%016x' $((addr + i * 8)))
      target=$(( 16#$(readelf -rW "$f" | awk -v o="$off" '$1 == o && /R_X86_64_RELATIVE/ {print $NF; exit}') ))
    fi
    i=$((i + 1)); n=$((n + 1))
    # the symbol that contains the address, and its size, from the symbol table
    local sym; sym=$(nm -nS --defined-only "$f" 2>/dev/null | awk -v a="$target" '
      { s = strtonum("0x" $1); z = (NF >= 4) ? strtonum("0x" $2) : 0; name = $NF
        if (s <= a && a < s + z) { print name, s, z; exit } }')
    local name start len mnems
    if [ -n "$sym" ]; then
      name=${sym%% *}; start=$(echo "$sym" | awk '{print $2}'); len=$(echo "$sym" | awk '{print $3}')
      mnems=$(objdump -d --no-show-raw-insn --start-address="$start" --stop-address=$((start + len)) "$f" \
        | awk -F'\t' 'NF>=2 {split($2,a," "); print a[1]}')
    else
      # stripped (no local symbols): read from the address to the first
      # unconditional transfer out (ret, or the tail jmp that ends the
      # toolchain's frame_dummy), at most 4 KiB. Conservative: a constructor
      # that branches around is over-read into what follows it.
      name="0x$(printf %x "$target")"; len="?"
      mnems=$(objdump -d --no-show-raw-insn --start-address="$target" --stop-address=$((target + 4096)) "$f" \
        | awk -F'\t' 'NF>=2 && !done {split($2,a," "); print a[1]; if (a[1] ~ /^(ret|jmp)/) done=1}')
    fi
    local hits; hits=$(printf '%s\n' "$mnems" | sort -u | grep -Ex "$forbidden" | grep -Evx "$AVX_EXCLUDE" || true)
    if [ -n "$hits" ]; then
      echo "ctors FAIL $f: constructor $name uses: $(echo $hits)"; status=1
    else
      echo "ctors ok   $f: constructor $name ($len bytes, $(printf '%s\n' "$mnems" | grep -c .) instructions) clean for the SSE2 machine"
    fi
  done
  echo "ctors      $f: $n constructor(s)"
  return $status
}

case "$variant" in
  baseline) forbidden="$SSE41|$SSE42|$AVX" ;;
  noavx)    forbidden="$AVX" ;;
  avx2)     forbidden='' ;;
  ctors)    ctors_check "$dir"; exit $? ;;
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
