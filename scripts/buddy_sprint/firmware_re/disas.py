#!/usr/bin/env python3
"""Disassembler tinklaBuddy-funksjoner via symboltabell + capstone (aarch64).
Bruk: disas.py <binær> <symbolnavn> [<symbolnavn> ...]
Løser opp adcv/adrp+add til strengreferanser der mulig."""
import sys
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

path = sys.argv[1]
wanted = sys.argv[2:]
f = open(path, "rb")
elf = ELFFile(f)

# symbol-tabell
syms = {}
symtab = elf.get_section_by_name(".symtab")
for s in symtab.iter_symbols():
    if s.entry.st_info.type == "STT_FUNC" and s.entry.st_value:
        syms[s.name] = (s.entry.st_value, s.entry.st_size)

# seksjoner for adresse->data
sections = []
for sec in elf.iter_sections():
    if sec.header.sh_addr:
        sections.append((sec.header.sh_addr, sec.header.sh_addr + sec.data_size, sec.data(), sec.name))

def read_at(addr, n=64):
    for lo, hi, data, _ in sections:
        if lo <= addr < hi:
            off = addr - lo
            return data[off:off+n]
    return b""

def cstr(addr):
    d = read_at(addr, 200)
    if not d:
        return None
    end = d.find(b"\x00")
    s = d[:end if end >= 0 else len(d)]
    try:
        t = s.decode("utf-8")
        return t if t.isprintable() and len(t) >= 2 else None
    except Exception:
        return None

# adressekart symbol for kall-oppløsning
addr2name = {v[0]: k for k, v in syms.items()}

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True

def disas(name):
    if name not in syms:
        print(f"## {name}: IKKE FUNNET"); return
    addr, size = syms[name]
    if size == 0:
        size = 0x400
    code = read_at(addr, size)
    print(f"\n===== {name}  @0x{addr:x}  ({size} B) =====")
    adrp = {}  # reg -> page base
    for insn in md.disasm(code, addr):
        line = f"  {insn.address:x}: {insn.mnemonic:8} {insn.op_str}"
        note = ""
        # spor adrp+add for strengrefs
        if insn.mnemonic == "adrp":
            try:
                r, imm = insn.op_str.split(", ")
                adrp[r.strip()] = int(imm, 0)
            except Exception:
                pass
        elif insn.mnemonic == "add" and "," in insn.op_str:
            parts = [p.strip() for p in insn.op_str.split(",")]
            if len(parts) == 3 and parts[1] in adrp and parts[2].startswith("#"):
                target = adrp[parts[1]] + int(parts[2][1:], 0)
                s = cstr(target)
                if s is not None:
                    note = f'   ; "{s}"'
        elif insn.mnemonic in ("bl", "b") and insn.op_str.startswith("#"):
            t = int(insn.op_str[1:], 0)
            if t in addr2name:
                note = f"   ; <{addr2name[t]}>"
        print(line + note)

for w in wanted:
    disas(w)
