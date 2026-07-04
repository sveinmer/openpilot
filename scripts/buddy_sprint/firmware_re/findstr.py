#!/usr/bin/env python3
"""Finn hvilken funksjon som refererer en gitt streng i aarch64-binær."""
import sys
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM

path, needle = sys.argv[1], sys.argv[2].encode()
elf = ELFFile(open(path, "rb"))
secs = [(x.header.sh_addr, x.header.sh_addr + x.data_size, x.data(), x.name)
        for x in elf.iter_sections() if x.header.sh_addr]
# finn strengadresse
straddr = None
for lo, hi, d, nm in secs:
    i = d.find(needle)
    if i >= 0:
        straddr = lo + i
        print(f"# streng @ 0x{straddr:x} i {nm}")
        break
if straddr is None:
    sys.exit("streng ikke funnet")

symtab = elf.get_section_by_name(".symtab")
funcs = sorted((s.entry.st_value, s.entry.st_size, s.name)
               for s in symtab.iter_symbols()
               if s.entry.st_info.type == "STT_FUNC" and s.entry.st_value and s.entry.st_size)
def read(a, n):
    for lo, hi, d, nm in secs:
        if lo <= a < hi:
            return d[a-lo:a-lo+n]
    return b""
md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN); md.detail = True
for faddr, fsize, fname in funcs:
    code = read(faddr, fsize)
    if not code:
        continue
    adrp = {}
    for insn in md.disasm(code, faddr):
        ops = insn.operands
        if insn.mnemonic == "adrp" and len(ops) == 2:
            adrp[insn.reg_name(ops[0].reg)] = ops[1].imm
        elif insn.mnemonic == "add" and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
            base = adrp.get(insn.reg_name(ops[1].reg))
            if base is not None and base + ops[2].imm == straddr:
                print(f"  {fname} @0x{faddr:x}  refererer strengen @0x{insn.address:x}")
