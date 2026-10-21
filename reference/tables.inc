#define ReadDWord(offset) (*((DWORD*)(rom+offset)))
const long p_layout[4] = {0x868D24, 0x868888, 0x8689B3, 0x808199 };
const long p_scenes[4] = {0x868D93, 0x8688F7, 0x868A22, 0x808257 };
const long p_blocks[4] = {0x868E02, 0x868966, 0x868A91, NULL };
const long p_maps  [4] = {0x868E71, 0x8689D5, 0x868B00, 0x8081B3 };
const long p_collis[4] = {0x868EE0, 0x868A44, 0x868B6F, NULL };
/*const*/ long p_checkp[4] = {0x86A780, 0x86A4C5, 0x86A8E4, NULL };
const long p_palett[4] = {0x868133, 0x86817A, 0x868180, NULL };
const long p_font  [4] = {0x86F744, 0x86FA4C, 0x86F77D, NULL };
const long p_unknow[4] = {0x86A1D5,     NULL,     NULL, NULL }; // Unknow
const long p_gfxcfg[4] = {0x86F56F, 0x86F831, 0x86F3C3, 0x80B75B };
const long p_gfxpos[4] = {0x86F6F7,	0x86F9FF, 0x86F730, 0x81E391 };
const long p_events[4] = {0x8582C2, 0x29D3D1, 0x3CCE4B, 0x80C18B };
const long p_borders[4]= {0x86E4E2, 0x82EBE9, 0x83DE43, NULL };
const long p_locks[4]  = {0x86ECD0, 0x82FAE4, 0x83F2CC, NULL };
//const long p_properties[3] = {0x80F8F3, 0x80FB8E, 0x86E28E};
const long p_properties[4] = { NULL, NULL, 0x86E28E, NULL };
const long p_spriteAssembly[4] = { 0x8D8000, 0x8D8000, 0x8D8000, NULL };
const long p_spriteOffset[4] = { 0x86A5E4, 0x86A34D, 0x86E28E, NULL }; //r&f edited
const long p_objOffset[4] = { 0x86DE9B, 0x86A34D, NULL, NULL };

// all graphics
const long p_gfxobj[4] = {0x86ACEE, 0X2AB2D4, 0x888623, NULL }; //mmx2: 0xAAB2D4 fastrom, r&f edited
const long p_gfxpal[4] = {0x86ACF1, 0X2AB2D7, 0x888626, NULL }; 
// TODO: sprite
// TODO: misc object

// capsule
const long p_capsulepos[4] = {NULL,0x86D6F1,NULL, NULL };

const long p_blayout[4] = {0x868F4F, 0x868AB3, 0x868BDE, NULL };
const long p_bscenes[4] = {0x868FBE, 0x868B22, 0x868C4D, NULL };
const long p_bblocks[4] = {0x86902D, 0x868B91, 0x868CBC, NULL };
