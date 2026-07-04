#!/usr/bin/env python3
"""Robust xref av global i aarch64 via capstone operand-detaljer.
Sporer adrp-reg -> page, matcher add/ldr*/str* som treffer target-adressen."""
import sys
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_MEM

path, target = sys.argv[1], sys.argv[2]
elf = ELFFile(open(path, "rb"))
symtab = elf.get_section_by_name(".symtab")
funcs, gaddr = [], None
for s in symtab.iter_symbols():
    if s.entry.st_info.type == "STT_FUNC" and s.entry.st_value and s.entry.st_size:
        funcs.append((s.entry.st_value, s.entry.st_size, s.name))
    if s.name == target:
        gaddr = s.entry.st_value
if gaddr is None:
    sys.exit(f"{target} ikke funnet")
print(f"# {target} @ 0x{gaddr:x}")
funcs.sort()
secs = [(x.header.sh_addr, x.header.sh_addr + x.data_size, x.data())
        for x in elf.iter_sections() if x.header.sh_addr]
def read(a, n):
    for lo, hi, d in secs:
        if lo <= a < hi:
            return d[a-lo:a-lo+n]
    return b""
md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN); md.detail = True

for faddr, fsize, fname in funcs:
    code = read(faddr, fsize)
    if not code:
        continue
    adrp = {}      # reg -> page
    reg_addr = {}  # reg -> full resolved address (after add)
    hits = []
    for insn in md.disasm(code, faddr):
        ops = insn.operands
        m = insn.mnemonic
        if m == "adrp" and len(ops) == 2:
            adrp[insn.reg_name(ops[0].reg)] = ops[1].imm
        elif m == "add" and len(ops) == 3 and ops[0].type == ARM64_OP_REG \
                and ops[1].type == ARM64_OP_REG and ops[2].type == ARM64_OP_IMM:
            base = adrp.get(insn.reg_name(ops[1].reg))
            if base is not None:
                full = base + ops[2].imm
                reg_addr[insn.reg_name(ops[0].reg)] = full
                if full == gaddr:
                    hits.append((insn.address, "ADDR ", m, insn.op_str))
        elif m.startswith("ldr") or m.startswith("str"):
            # mem-operand: base reg + disp
            for op in ops:
                if op.type == ARM64_OP_MEM:
                    br = insn.reg_name(op.mem.base) if op.mem.base else None
                    disp = op.mem.disp
                    # to måter: base er adrp-reg (disp=offset) el. base er add-resultat (disp=0)
                    eff = None
                    if br in adrp and adrp[br] + disp == gaddr:
                        eff = adrp[br] + disp
                    elif br in reg_addr and reg_addr[br] + disp == gaddr:
                        eff = reg_addr[br] + disp
                    if eff == gaddr:
                        kind = "WRITE" if m.startswith("str") else "READ "
                        hits.append((insn.address, kind, m, insn.op_str))
    if hits:
        kinds = {h[1].strip() for h in hits}
        print(f"\n{fname} @0x{faddr:x}  [{','.join(sorted(kinds))}]")
        for a, k, mm, o in hits:
            print(f"   {a:x}: {k} {mm} {o}")
