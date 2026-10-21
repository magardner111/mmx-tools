// Compiles MegaEdX's MMXCore::ExpandROM() unmodified on macOS for differential testing.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <set>
#include <map>
typedef uint8_t BYTE; typedef uint16_t WORD; typedef uint32_t DWORD;
typedef BYTE* LPBYTE; typedef WORD* LPWORD; typedef DWORD* LPDWORD;
#define RSIZE_MAX 0x7fffffff
static int strcpy_s(char *d, size_t, const char *s) { strcpy(d, s); return 0; }
template<size_t N> static int strcpy_s(char (&d)[N], const char *s) { strcpy(d, s); return 0; }

struct SNESHeader { char title[21]; BYTE mapMode, cartType, romSize, ramSize, country, license, version; WORD checksumx, checksum; };

static DWORD snes2pc_(int a) { return ((a & 0x007F0000) >> 1) + (a & 0x7FFF); }
static DWORD pc2snes_(int p) { return 0x800000L + ((p & 0x3F8000) << 1) + 0x8000L + (p & 0x7FFF); }
struct SNESCore { static DWORD snes2pc(int a) { return snes2pc_(a); } static DWORD pc2snes(int p) { return pc2snes_(p); } };

#include "tables.inc"

struct MMXCore {
    BYTE *rom; unsigned romSize; BYTE type = 0; unsigned numLevels = 13;
    SNESHeader *header;
    unsigned eventBank, checkpointBank, lockBank;
    bool expandedROM = false;
    unsigned expandedVersion = 0, expandedLayoutSize = 0, expandedEventSize = 0, expandedCheckpointSize = 0, expandedLayoutScenes = 0;
    DWORD pLocks;
    static const char expandedROMString[]; static const WORD expandedROMVersion; static const unsigned expandedROMHeaderSize;
    static DWORD snes2pc(int a) { return snes2pc_(a); } static DWORD pc2snes(int p) { return pc2snes_(p); }
    bool ExpandROM();
};
const char MMXCore::expandedROMString[] = "EXPANDED ROM ";
const WORD MMXCore::expandedROMVersion = 4;
const unsigned MMXCore::expandedROMHeaderSize = 0x40;
MMXCore nmmx;
#define SReadWord(o) (*((WORD*)(rom+snes2pc(o))))
#define SReadDWord(o) (*((DWORD*)(rom+snes2pc(o))))

#include "expandrom_body.inc"

int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    nmmx.rom = (BYTE*)calloc(0x800000, 1); fread(nmmx.rom, 1, n, f); fclose(f);
    nmmx.romSize = n; nmmx.header = (SNESHeader*)(nmmx.rom + 0x7FC0);
    nmmx.eventBank = p_events[0] >> 16; nmmx.checkpointBank = p_checkp[0] >> 16; nmmx.lockBank = p_borders[0] >> 16;
    nmmx.pLocks = snes2pc_(p_locks[0]);
    bool ok = nmmx.ExpandROM();
    fprintf(stderr, "ExpandROM ok=%d size=%#x\n", ok, nmmx.romSize);
    f = fopen(argv[2], "wb"); fwrite(nmmx.rom, 1, nmmx.romSize, f); fclose(f);
    return ok ? 0 : 1;
}
