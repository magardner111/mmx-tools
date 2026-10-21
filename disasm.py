"""
Minimal 65816 disassembler for LoROM SNES code.

Tracks the M (accumulator) and X (index) width flags through REP/SEP so
immediate operands get the right size. Linear sweep from a start address;
stops at RTS/RTL/RTI/JMP/BRA unless follow=True.

usage: python3 disasm.py <snes_addr_hex> [count] [--m8] [--x8]
"""
import sys
from mmx1 import MMX1, snes2pc

# (mnemonic, mode) for opcodes 0x00-0xFF
_T = """
BRK s|ORA dxi|COP s|ORA sr|TSB d|ORA d|ASL d|ORA dil|PHP i|ORA #m|ASL A|PHD i|TSB a|ORA a|ASL a|ORA al
BPL r|ORA diy|ORA di|ORA sriy|TRB d|ORA dx|ASL dx|ORA dily|CLC i|ORA ay|INC A|TCS i|TRB a|ORA ax|ASL ax|ORA alx
JSR a|AND dxi|JSL al|AND sr|BIT d|AND d|ROL d|AND dil|PLP i|AND #m|ROL A|PLD i|BIT a|AND a|ROL a|AND al
BMI r|AND diy|AND di|AND sriy|BIT dx|AND dx|ROL dx|AND dily|SEC i|AND ay|DEC A|TSC i|BIT ax|AND ax|ROL ax|AND alx
RTI i|EOR dxi|WDM b|EOR sr|MVP bm|EOR d|LSR d|EOR dil|PHA i|EOR #m|LSR A|PHK i|JMP a|EOR a|LSR a|EOR al
BVC r|EOR diy|EOR di|EOR sriy|MVN bm|EOR dx|LSR dx|EOR dily|CLI i|EOR ay|PHY i|TCD i|JML al|EOR ax|LSR ax|EOR alx
RTS i|ADC dxi|PER rl|ADC sr|STZ d|ADC d|ROR d|ADC dil|PLA i|ADC #m|ROR A|RTL i|JMP ai|ADC a|ROR a|ADC al
BVS r|ADC diy|ADC di|ADC sriy|STZ dx|ADC dx|ROR dx|ADC dily|SEI i|ADC ay|PLY i|TDC i|JMP axi|ADC ax|ROR ax|ADC alx
BRA r|STA dxi|BRL rl|STA sr|STY d|STA d|STX d|STA dil|DEY i|BIT #m|TXA i|PHB i|STY a|STA a|STX a|STA al
BCC r|STA diy|STA di|STA sriy|STY dx|STA dx|STX dy|STA dily|TYA i|STA ay|TXS i|TXY i|STZ a|STA ax|STZ ax|STA alx
LDY #x|LDA dxi|LDX #x|LDA sr|LDY d|LDA d|LDX d|LDA dil|TAY i|LDA #m|TAX i|PLB i|LDY a|LDA a|LDX a|LDA al
BCS r|LDA diy|LDA di|LDA sriy|LDY dx|LDA dx|LDX dy|LDA dily|CLV i|LDA ay|TSX i|TYX i|LDY ax|LDA ax|LDX ay|LDA alx
CPY #x|CMP dxi|REP b|CMP sr|CPY d|CMP d|DEC d|CMP dil|INY i|CMP #m|DEX i|WAI i|CPY a|CMP a|DEC a|CMP al
BNE r|CMP diy|CMP di|CMP sriy|PEI d|CMP dx|DEC dx|CMP dily|CLD i|CMP ay|PHX i|STP i|JML ail|CMP ax|DEC ax|CMP alx
CPX #x|SBC dxi|SEP b|SBC sr|CPX d|SBC d|INC d|SBC dil|INX i|SBC #m|NOP i|XBA i|CPX a|SBC a|INC a|SBC al
BEQ r|SBC diy|SBC di|SBC sriy|PEA a|SBC dx|INC dx|SBC dily|SED i|SBC ay|PLX i|XCE i|JSR axi|SBC ax|INC ax|SBC alx
"""
OPS = []
for line in _T.strip().splitlines():
    for cell in line.split("|"):
        OPS.append(tuple(cell.split()))
assert len(OPS) == 256

FMT = {
    "i": ("", 0), "A": ("A", 0), "s": ("#${0:02X}", 1), "b": ("#${0:02X}", 1),
    "d": ("${0:02X}", 1), "dx": ("${0:02X},X", 1), "dy": ("${0:02X},Y", 1),
    "di": ("(${0:02X})", 1), "dxi": ("(${0:02X},X)", 1), "diy": ("(${0:02X}),Y", 1),
    "dil": ("[${0:02X}]", 1), "dily": ("[${0:02X}],Y", 1),
    "sr": ("${0:02X},S", 1), "sriy": ("(${0:02X},S),Y", 1),
    "a": ("${0:04X}", 2), "ax": ("${0:04X},X", 2), "ay": ("${0:04X},Y", 2),
    "ai": ("(${0:04X})", 2), "axi": ("(${0:04X},X)", 2), "ail": ("[${0:04X}]", 2),
    "al": ("${0:06X}", 3), "alx": ("${0:06X},X", 3),
    "r": (None, 1), "rl": (None, 2), "bm": (None, 2),
}
ENDS = {"RTS", "RTL", "RTI", "JMP", "JML", "BRA", "BRL", "STP"}

# Routines that return with known register widths (m8, x8). The object allocators end with
# A 8-bit and X 16-bit (X = the new object's address).
RETURN_WIDTHS = {0x828321: (True, False), 0x82833E: (True, False), 0x828358: (True, False),
                 0x8282B9: (True, False), 0x8282D3: (True, False)}


def disasm(rom, addr, count=200, m8=False, x8=False, stop=True):
    """Yield (snes_addr, bytes, text, info) — info has 'target' for branches/jumps."""
    for _ in range(count):
        pc = snes2pc(addr)
        op = rom[pc]
        mn, mode = OPS[op]
        if mode == "#m": n = 1 if m8 else 2
        elif mode == "#x": n = 1 if x8 else 2
        else: n = FMT[mode][1]
        raw = rom[pc:pc + 1 + n]
        val = int.from_bytes(raw[1:], "little") if n else 0
        info = {}
        if mode in ("#m", "#x"):
            txt = f"#${val:0{2*n}X}"
        elif mode == "r":
            t = (addr & 0xFF0000) | ((addr + 2 + (val - 256 if val > 127 else val)) & 0xFFFF)
            txt = f"${t & 0xFFFF:04X}"; info["target"] = t
        elif mode == "rl":
            t = (addr & 0xFF0000) | ((addr + 3 + (val - 65536 if val > 32767 else val)) & 0xFFFF)
            txt = f"${t & 0xFFFF:04X}"; info["target"] = t
        elif mode == "bm":
            txt = f"${raw[1]:02X},${raw[2]:02X}"
        else:
            txt = FMT[mode][0].format(val)
            if mn in ("JSR", "JMP") and mode == "a":
                info["target"] = (addr & 0xFF0000) | val
            if mn in ("JSL", "JML") and mode == "al":
                info["target"] = val
            if mode in ("axi", "ai", "ail"):
                info["table"] = (addr & 0xFF0000) | val
        if mn == "REP":
            if val & 0x20: m8 = False
            if val & 0x10: x8 = False
        if mn == "SEP":
            if val & 0x20: m8 = True
            if val & 0x10: x8 = True
        info.update(m8=m8, x8=x8)
        yield addr, bytes(raw), f"{mn} {txt}".strip(), info
        if mn in ("JSL", "JSR") and info.get("target") in RETURN_WIDTHS:
            m8, x8 = RETURN_WIDTHS[info["target"]]
        addr = (addr & 0xFF0000) | ((addr + 1 + n) & 0xFFFF)
        if stop and mn in ENDS:
            return


def show(rom, addr, count=200, m8=False, x8=False, stop=True):
    for a, raw, txt, info in disasm(rom, addr, count, m8, x8, stop):
        print(f"{a:06X}  {raw.hex(' '):<12} {txt}")


if __name__ == "__main__":
    g = MMX1("../Mega Man X (USA) (Rev 1).sfc")
    a = int(sys.argv[1], 16)
    n = int(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else 200
    show(g.rom, a, n, "--m8" in sys.argv, "--x8" in sys.argv)
