bool MMXCore::ExpandROM() {
	bool ok = true;
	DWORD a = 0;

	switch (nmmx.type) {
	case 0: {
		ok &= header->romSize == 0xB;
		ok &= romSize == 0x180000;
		break;
	}
	case 1: {
		ok &= header->romSize == 0xB;
		ok &= (romSize == 0x180000) || (romSize == 0x200000 && !memcmp(nmmx.rom + 0x100000, nmmx.rom + 0x180000, 0x80000));
		break;
	}
	case 2: {
		ok &= header->romSize == 0xB;
		ok &= romSize == 0x200000;
		break;
	}
	case 3: {
		ok &= header->romSize == 0xC;
		ok &= romSize == 0x400000;
		break;
	}
	default: {
		ok = false;
		break;
	}
	}

	if (nmmx.type < 3) {
		if (ok) {
			// make the ROM bigger
			// Add 1MB
			memset(rom + romSize, 0xFF, 0x100000);
			char *arg1 = (char*)(rom + romSize + 0x8000 - expandedROMHeaderSize);
			strcpy_s(arg1, RSIZE_MAX, expandedROMString);
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0xE, &expandedROMVersion, 2);
			WORD v;
			v = 0x800;
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0x10, &v, 2);
			v = 0x800;
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0x12, &v, 2);
			v = 0x10;
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0x14, &v, 2);
			// sceneUsed already stored in the ROM
		}

		unsigned currentOffset = romSize;

		if (ok) {
			// relocate the layout for each level
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				WORD pLevel = i * 3;
				auto levelLayout = snes2pc(SReadDWord(p_layout[type] + pLevel));
				LPBYTE layout = rom + levelLayout;

				unsigned count;
				for (count = 3; layout[count] != 0xFF; ++count);
				count++;

				if (count <= 0x800) {
					memcpy(rom + currentOffset + i * 0x800, layout, count);
				}
				else {
					ok = false;
					break;
				}
			}
			currentOffset += 0x10 * 0x800;
		}

		if (ok) {
			// relocate the background layout for each level
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				WORD pLevel = i * 3;
				auto levelLayout = snes2pc(SReadDWord(p_blayout[type] + pLevel));
				LPBYTE layout = rom + levelLayout;

				unsigned count;
				for (count = 3; layout[count] != 0xFF; ++count);
				count++;

				if (count <= 0x800) {
					memcpy(rom + currentOffset + i * 0x800, layout, count);
				}
				else {
					ok = false;
					break;
				}
			}
			currentOffset += 0x10 * 0x800;
		}

		if (ok) {
			// copy events.  fix addresses in ROM
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				DWORD pEvents = snes2pc(SReadWord(p_events[type] + i * 2) | (eventBank << 16));
				LPBYTE pevent = rom + pEvents;
				LPBYTE peventBase = pevent;

				unsigned count = 0;

				unsigned blockId = 0xFF;
				unsigned nextBlockId = *pevent++;
				count++;

				while (blockId != nextBlockId && blockId < 0x100) {
					bool eventDone = true;

					blockId = nextBlockId;
					do {
						eventDone = (*LPWORD(pevent + 5) & 0x8000 ? true : false);

						pevent += 7;
						count += 7;
					} while (!eventDone);

					// get the next id
					nextBlockId = *pevent++;
					count++;
				}

				if (count <= 0x800) {
					memcpy(rom + currentOffset + i * 0x800, peventBase, count);
				}
				else {
					ok = false;
					break;
				}
			}

			currentOffset += 0x10 * 0x800;
		}

		if (ok) {
			// relocate the scenes
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				WORD pLevel = i * 3;
				auto sceneLayout = snes2pc(SReadDWord(p_scenes[type] + pLevel));
				LPBYTE layout = rom + sceneLayout;

				auto levelLayout = snes2pc(SReadDWord(p_layout[type] + pLevel));
				unsigned s = *(rom + levelLayout + 2);

				// copy the existing scene data
				memcpy(rom + currentOffset + i * 0x80 * 0x80, layout, s * 0x80);
				memset(rom + currentOffset + i * 0x80 * 0x80 + s * 0x80, 0x00, 0x80 * 0x80 - s * 0x80);
			}
			currentOffset += 0x10 * 0x80 * 0x80;
		}

		if (ok) {
			if (nmmx.type == 0) {
				if ((*LPWORD(rom + snes2pc(0x80DB92)) != 0x85A9 || *LPWORD(rom + snes2pc(0x80DBD9)) != 0x85A9 || *LPWORD(rom + snes2pc(0x80DD4C)) != 0x85A9)
					&& (*LPWORD(rom + snes2pc(0x80DB7C)) != 0x85A9 || *LPWORD(rom + snes2pc(0x80DBC3)) != 0x85A9 || *LPWORD(rom + snes2pc(0x80DD36)) != 0x85A9)) {
					ok = false;
				}
			}
			else if (nmmx.type == 1) {
				if (*LPWORD(rom + snes2pc(0x80DB96)) != 0x29A9 || *LPWORD(rom + snes2pc(0x80DBDD)) != 0x29A9 || *LPWORD(rom + snes2pc(0x80DD44)) != 0x29A9) {
					ok = false;
				}
			}
			else if (nmmx.type == 2) {
				// FIXME: X3 has a problem where banks >= 0xC0 don't have RAM shadowed into the lower offsets
				// so LDs to ROM intermixed with STs to RAM fail.  This is a problem for the events but not the layout
				if (*LPWORD(rom + snes2pc(0x80DD80)) != 0x3CA9 || *LPWORD(rom + snes2pc(0x80DDC7)) != 0x3CA9 || *LPWORD(rom + snes2pc(0x80DF2E)) != 0x3CA9) {
					ok = false;
				}
			}
			else {
				ok = false;
			}
		}

		if (ok) {
			DWORD pEvents = snes2pc(SReadWord(p_events[type] + 0x300) | (eventBank << 16));
			LPBYTE pevent = rom + pEvents;

			//for (unsigned i = 0x0; i < 0x2000; i++) {
			//	if (*(pevent + i) != 0xFF) {
			//		ok = false;
			//		break;
			//	}
			//}

			DWORD pFunc = snes2pc(0x80FF00);
			LPBYTE func = rom + pFunc;
			for (unsigned i = 0x0; i < 0x90; i++) {
				if (*(func + i) != 0xFF) {
					ok = false;
					break;
				}
			}

		}

		if (ok) {
			expandedROM = true;

			// remove copy protection crap
			if (nmmx.type == 0) {
				// reset upgrades
				*LPBYTE(rom + snes2pc(0x81824E)) = 0x00;
				// reset checkpoint
				*LPBYTE(rom + snes2pc(0x849FC7)) = 0x00;
				// 1UP drop reset stage
				*LPBYTE(rom + snes2pc(0x84A41F)) = 0x00;

				//*LPBYTE(rom + snes2pc(0x84A47F)) = 0xEA;
				//*LPBYTE(rom + snes2pc(0x84A480)) = 0xEA;
				//*LPBYTE(rom + snes2pc(0x84A3CC)) = 0x80;
			}
			else if (nmmx.type == 1) {
			}
			else if (nmmx.type == 2) {
			}

			// remove old events
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				DWORD pEvents = snes2pc(SReadWord(p_events[type] + i * 2) | (eventBank << 16));
				LPBYTE pevent = rom + pEvents;
				LPBYTE peventBase = pevent;

				unsigned count = 0;

				unsigned blockId = 0xFF;
				unsigned nextBlockId = *pevent++;
				*(pevent - 1) = 0xFF;
				count++;

				while (blockId != nextBlockId && blockId < 0x100) {
					bool eventDone = true;

					blockId = nextBlockId;
					do {
						eventDone = (*LPWORD(pevent + 5) & 0x8000 ? true : false);

						memset(pevent, 0xFF, 7);
						pevent += 7;
						count += 7;
					} while (!eventDone);

					// get the next id
					nextBlockId = *pevent++;
					*(pevent - 1) = 0xFF;
					count++;
				}
			}

			// layout
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				DWORD addr = pc2snes(nmmx.romSize + i * 0x800);

				auto levelLayout = snes2pc(SReadDWord(p_layout[type] + i * 3));
				unsigned s = *(rom + levelLayout + 2);
				// overwrite the layout data
				for (LPBYTE l = rom + levelLayout + 3; *l != 0xFF; l++) *l = 0xFF;

				memcpy(rom + snes2pc(p_layout[type] + i * 3), &addr, 3);
			}

			// background layout
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				DWORD addr = pc2snes(nmmx.romSize + 0x8000 + i * 0x800);

				auto levelLayout = snes2pc(SReadDWord(p_blayout[type] + i * 3));
				unsigned s = *(rom + levelLayout + 2);
				// overwrite the layout data
				for (LPBYTE l = rom + levelLayout + 3; *l != 0xFF; l++) *l = 0xFF;

				memcpy(rom + snes2pc(p_blayout[type] + i * 3), &addr, 3);
			}

			// scenes
			DWORD bank = pc2snes(nmmx.romSize + 2 * 0x8000 + 0 * 0x800);
			if (nmmx.type == 0) {
				eventBank = bank >> 16;
				DWORD offsetAddr = pc2snes(nmmx.romSize +  3 * 0x8000 - 2 * 0x10);
				if ((*LPWORD(rom + snes2pc(0x80DB92)) == 0x85A9 || *LPWORD(rom + snes2pc(0x80DBD9)) == 0x85A9 || *LPWORD(rom + snes2pc(0x80DD4C)) == 0x85A9)) {
					// 1.0
					*LPWORD(rom + snes2pc(0x80DB92)) = 0xA9 | (eventBank << 8);
					*LPWORD(rom + snes2pc(0x80DBD9)) = 0xA9 | (eventBank << 8);
					*LPWORD(rom + snes2pc(0x80DD4C)) = 0xA9 | (eventBank << 8);
					*LPWORD(rom + snes2pc(0x80DB9E)) = offsetAddr & 0xFFFF;
				}
				else {
					// 1.1
					*LPWORD(rom + snes2pc(0x80DB7C)) = 0xA9 | (eventBank << 8);
					*LPWORD(rom + snes2pc(0x80DBC3)) = 0xA9 | (eventBank << 8);
					*LPWORD(rom + snes2pc(0x80DD36)) = 0xA9 | (eventBank << 8);
					*LPWORD(rom + snes2pc(0x80DB88)) = offsetAddr & 0xFFFF;
				}
			}
			else if (nmmx.type == 1) {
				eventBank = bank >> 16;
				*LPWORD(rom + snes2pc(0x80DB96)) = 0xA9 | (eventBank << 8);
				*LPWORD(rom + snes2pc(0x80DBDD)) = 0xA9 | (eventBank << 8);
				*LPWORD(rom + snes2pc(0x80DD44)) = 0xA9 | (eventBank << 8);

				DWORD offsetAddr = pc2snes(nmmx.romSize + 3 * 0x8000 - 2 * 0x10);
				*LPWORD(rom + snes2pc(0x80DBA2)) = offsetAddr & 0xFFFF;
			}
			else if (nmmx.type == 2) {
				eventBank = bank >> 16;
				*LPWORD(rom + snes2pc(0x80DD80)) = 0xA9 | (eventBank << 8);
				*LPWORD(rom + snes2pc(0x80DDC7)) = 0xA9 | (eventBank << 8);

				DWORD offsetAddr = pc2snes(nmmx.romSize + 3 * 0x8000 - 2 * 0x10);
				*LPWORD(rom + snes2pc(0x80DD8C)) = offsetAddr & 0xFFFF;

				// swap LD and PLB so LD uses correct bank
				*LPWORD(rom + snes2pc(0x80DD83)) = 0xAEAD;
				*LPWORD(rom + snes2pc(0x80DD85)) = 0xAB1F;

				// store the bank in the 3rd B for long LD
				*LPWORD(rom + snes2pc(0x80DF2E)) = 0xA9 | (eventBank << 8);
				*LPWORD(rom + snes2pc(0x80DF30)) = 0x1A85;

				// NOP the push/pull of the bank register 
				*LPBYTE(rom + snes2pc(0x80DF43)) = 0xEA;
				*LPBYTE(rom + snes2pc(0x80DF4C)) = 0xEA;

				// change all the offset LDs to long LDs
				*LPBYTE(rom + snes2pc(0x80DF34)) = 0xA7;
				*LPBYTE(rom + snes2pc(0x80DF50)) = 0xB7;
				*LPBYTE(rom + snes2pc(0x80DF56)) = 0xB7;
				*LPBYTE(rom + snes2pc(0x80DF5C)) = 0xB7;
				*LPBYTE(rom + snes2pc(0x80DF62)) = 0xB7;
				*LPBYTE(rom + snes2pc(0x80DF68)) = 0xB7;
				*LPBYTE(rom + snes2pc(0x80DF6E)) = 0xB7;
			}

			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				DWORD addr = pc2snes(nmmx.romSize +  3 * 0x8000 + i * 0x800);
				DWORD offsetAddr = pc2snes(nmmx.romSize + 3 * 0x8000 - 2 * 0x10);
				memcpy(rom + snes2pc(offsetAddr + i * 2), &addr, 2);
			}

			// scenes
			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				WORD pLevel = i * 3;
				auto sceneLayout = snes2pc(SReadDWord(p_scenes[type] + pLevel));
				LPBYTE layout = rom + sceneLayout;

				auto levelLayout = snes2pc(SReadDWord(p_layout[type] + pLevel));
				unsigned s = *(rom + levelLayout + 2);

				// overwrite the scene data
				memset(layout, 0xFF, s * 0x80);

				DWORD addr = pc2snes(nmmx.romSize + 3 * 0x8000 + i * 0x80 * 0x80);
				memcpy(rom + snes2pc(p_scenes[type] + i * 3), &addr, 3);
				*(rom + levelLayout + 2) = 0x40;
			}

			// checkpoints
			checkpointBank = (nmmx.type == 0) ? 0x93 : ((p_events[type]) >> 16);
			// copy the current checkpoints table
			DWORD pEvents = snes2pc((nmmx.type == 0 ? 0x93AD00 : p_events[type]) + 0x300);
			LPBYTE pnewBase = rom + pEvents;
			BYTE pointers[0x10 + 0x10 * 0x20];

			// fix the level base pointers
			for (unsigned j = 0; j < 0x10; j++) {
				*LPWORD(pointers + j * 2) = (0x10 + j * 0x10) * 2;
			}

			std::set<unsigned> offsetSet;

			WORD checkpointBaseOffset = ((nmmx.type == 0 ? 0xAD00 : (p_events[type] & 0xFFFF)) + 0x300 - (p_checkp[type] & 0xFFFF));

			for (unsigned i = 0; i < nmmx.numLevels; ++i) {
				WORD levelValue = SReadWord(p_checkp[type] + i * 2);
				unsigned levelOffset = snes2pc(p_checkp[type] + levelValue);
				LPWORD pLevel = LPWORD(rom + levelOffset);

				WORD endValue = (nmmx.type == 0) ? 0x0072 : (nmmx.type == 1) ? 0x0098 : 0x0088;
				for (unsigned j = 0; j < nmmx.numLevels; j++) {
					WORD tempValue = SReadWord(p_checkp[type] + j * 2);
					if (levelValue < tempValue && tempValue < endValue) {
						endValue = tempValue;
					}
				}

				unsigned endOffset = snes2pc(p_checkp[type] + endValue);
				LPWORD pEnd = LPWORD(rom + endOffset);

				unsigned count = 0;
				while (pLevel < pEnd && count < 0x10) {
					WORD checkpointValue = *pLevel++;

					offsetSet.insert(checkpointValue);
					*LPWORD(pointers + (0x10 + i * 0x10 + count) * 2) = checkpointBaseOffset + checkpointValue;

					count++;
				}
				// set remaining counts as last
				memset(pointers + (0x10 + i * 0x10 + count) * 2, 0xFF, (0x10 - count) * 2);
			}
			// copy existing checkpoints
			memcpy(pnewBase, rom + snes2pc(p_checkp[type]), (nmmx.type == 0) ? 0x56E : (nmmx.type == 1) ? 0x9B1 : 0x728);
			// copy new pointer table in
			unsigned checkpointTableBase = snes2pc(p_checkp[type]);
			memcpy(nmmx.rom + checkpointTableBase, pointers, sizeof(pointers));

			if (type == 0) {
				// write new base function
				memcpy(nmmx.rom + snes2pc(0x80FF00), nmmx.rom + snes2pc(0x80E68E), 0x22);
				memset(nmmx.rom + snes2pc(0x80E68E), 0xFF, 0x22);
				// set new bank
				*LPWORD(rom + snes2pc(0x80FF22)) = 0xA9 | (checkpointBank << 8);
				*LPBYTE(rom + snes2pc(0x80FF24)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF25)) = 0xAB;
				// add back RTS
				*LPBYTE(rom + snes2pc(0x80FF26)) = 0x60;
				// change all instances of JMP
				*LPWORD(rom + snes2pc(0x809DA4)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E602)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E679)) = 0xFF00;
				//*LPWORD(rom + snes2pc(0x80E681)) = 0xFF00;

				// revert bank + RTL

				// fix other functions
				//1
				// revert bank + JMP + RTS
				*LPWORD(rom + snes2pc(0x80FF27)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80FF29)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF2A)) = 0xAB;
				// JSR
				*LPBYTE(rom + snes2pc(0x80FF2B)) = 0x20;
				*LPWORD(rom + snes2pc(0x80FF2C)) = 0xB117;
				// RTS
				*LPBYTE(rom + snes2pc(0x80FF2E)) = 0x60;
				// FIX JMP
				*LPWORD(rom + snes2pc(0x809DD1)) = 0xFF27;

				//2
				// revert bank + JMP + RTS
				*LPBYTE(rom + snes2pc(0x80FF2F)) = 0xE2;
				*LPBYTE(rom + snes2pc(0x80FF30)) = 0x20;
				*LPWORD(rom + snes2pc(0x80FF31)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80FF33)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF34)) = 0xAB;
				*LPBYTE(rom + snes2pc(0x80FF35)) = 0xC2;
				*LPBYTE(rom + snes2pc(0x80FF36)) = 0x20;
				// JSL
				*LPDWORD(rom + snes2pc(0x80FF37)) = 0x0180E322;
				// RTS
				*LPBYTE(rom + snes2pc(0x80FF3B)) = 0x60;
				// FIX JMP
				*LPDWORD(rom + snes2pc(0x80E66D)) = 0xEAFF2F20;

				//3
				*LPBYTE(rom + snes2pc(0x80E68C)) = 0xE2;
				*LPBYTE(rom + snes2pc(0x80E68D)) = 0x20;
				*LPWORD(rom + snes2pc(0x80E68E)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80E690)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80E691)) = 0xAB;
				*LPBYTE(rom + snes2pc(0x80E692)) = 0xC2;
				*LPBYTE(rom + snes2pc(0x80E693)) = 0x20;
				// PLP + RTL
				*LPBYTE(rom + snes2pc(0x80E694)) = 0x28;
				*LPBYTE(rom + snes2pc(0x80E695)) = 0x6B;
			}
			else if (type == 1) {
				// write new base function
				memcpy(nmmx.rom + snes2pc(0x80FF00), nmmx.rom + snes2pc(0x80E690), 0x22);
				memset(nmmx.rom + snes2pc(0x80E690), 0xFF, 0x22);
				// set new bank
				*LPWORD(rom + snes2pc(0x80FF22)) = 0xA9 | (checkpointBank << 8);
				*LPBYTE(rom + snes2pc(0x80FF24)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF25)) = 0xAB;
				// add back RTS
				*LPBYTE(rom + snes2pc(0x80FF26)) = 0x60;
				// change all instances of JMP
				*LPWORD(rom + snes2pc(0x809D79)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E5ED)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E661)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E681)) = 0xFF00;

				// revert bank + RTL

				// fix other functions
				//1
				// revert bank + JMP + RTS
				*LPWORD(rom + snes2pc(0x80FF27)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80FF29)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF2A)) = 0xAB;
				// JSR
				*LPBYTE(rom + snes2pc(0x80FF2B)) = 0x20;
				*LPWORD(rom + snes2pc(0x80FF2C)) = 0xADD3;
				// RTS
				*LPBYTE(rom + snes2pc(0x80FF2E)) = 0x60;
				// FIX JMP
				*LPWORD(rom + snes2pc(0x809DA7)) = 0xFF27;

				//2
				// revert bank + JMP + RTS
				*LPBYTE(rom + snes2pc(0x80FF2F)) = 0xE2;
				*LPBYTE(rom + snes2pc(0x80FF30)) = 0x20;
				*LPWORD(rom + snes2pc(0x80FF31)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80FF33)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF34)) = 0xAB;
				*LPBYTE(rom + snes2pc(0x80FF35)) = 0xC2;
				*LPBYTE(rom + snes2pc(0x80FF36)) = 0x20;
				// JSL
				*LPDWORD(rom + snes2pc(0x80FF37)) = 0x01820B22;
				// RTS
				*LPBYTE(rom + snes2pc(0x80FF3B)) = 0x60;
				// FIX JMP
				*LPDWORD(rom + snes2pc(0x80E655)) = 0xEAFF2F20;

				//3
				*LPWORD(rom + snes2pc(0x80E679)) = 0x80 | (0x13 << 8);

				//4
				*LPBYTE(rom + snes2pc(0x80E68E)) = 0xE2;
				*LPBYTE(rom + snes2pc(0x80E68F)) = 0x20;
				*LPWORD(rom + snes2pc(0x80E690)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80E692)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80E693)) = 0xAB;
				*LPBYTE(rom + snes2pc(0x80E694)) = 0xC2;
				*LPBYTE(rom + snes2pc(0x80E695)) = 0x20;
				// PLP + RTL
				*LPBYTE(rom + snes2pc(0x80E696)) = 0x28;
				*LPBYTE(rom + snes2pc(0x80E697)) = 0x6B;
			}
			else if (type == 2) {
				// write new base function
				memcpy(nmmx.rom + snes2pc(0x80FF00), nmmx.rom + snes2pc(0x80E601), 0x22);
				memset(nmmx.rom + snes2pc(0x80E601), 0xFF, 0x22);
				// set new bank
				*LPWORD(rom + snes2pc(0x80FF22)) = 0xA9 | (checkpointBank << 8);
				*LPBYTE(rom + snes2pc(0x80FF24)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF25)) = 0xAB;
				// add back RTS
				*LPBYTE(rom + snes2pc(0x80FF26)) = 0x60;
				// change all instances of JMP
				*LPWORD(rom + snes2pc(0x80A1E5)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E558)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E5D2)) = 0xFF00;
				*LPWORD(rom + snes2pc(0x80E5F2)) = 0xFF00;

				// revert bank + RTL

				// fix other functions
				//1
				// revert bank + JMP + RTS
				*LPWORD(rom + snes2pc(0x80FF27)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80FF29)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF2A)) = 0xAB;
				// JSR
				*LPBYTE(rom + snes2pc(0x80FF2B)) = 0x20;
				*LPWORD(rom + snes2pc(0x80FF2C)) = 0xB297;
				// RTS
				*LPBYTE(rom + snes2pc(0x80FF2E)) = 0x60;
				// FIX JMP
				*LPWORD(rom + snes2pc(0x80A213)) = 0xFF27;

				//2
				// revert bank + JMP + RTS
				*LPBYTE(rom + snes2pc(0x80FF2F)) = 0xE2;
				*LPBYTE(rom + snes2pc(0x80FF30)) = 0x20;
				*LPWORD(rom + snes2pc(0x80FF31)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80FF33)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80FF34)) = 0xAB;
				*LPBYTE(rom + snes2pc(0x80FF35)) = 0xC2;
				*LPBYTE(rom + snes2pc(0x80FF36)) = 0x20;
				// JSL
				*LPDWORD(rom + snes2pc(0x80FF37)) = 0x01827C22;
				// RTS
				*LPBYTE(rom + snes2pc(0x80FF3B)) = 0x60;
				// FIX JMP
				*LPDWORD(rom + snes2pc(0x80E5C6)) = 0xEAFF2F20;

				//3
				*LPWORD(rom + snes2pc(0x80E5EA)) = 0x80 | (0x13 << 8);

				//4
				*LPBYTE(rom + snes2pc(0x80E5FF)) = 0xE2;
				*LPBYTE(rom + snes2pc(0x80E600)) = 0x20;
				*LPWORD(rom + snes2pc(0x80E601)) = 0xA9 | (0x06 << 8);
				*LPBYTE(rom + snes2pc(0x80E603)) = 0x48;
				*LPBYTE(rom + snes2pc(0x80E604)) = 0xAB;
				*LPBYTE(rom + snes2pc(0x80E605)) = 0xC2;
				*LPBYTE(rom + snes2pc(0x80E606)) = 0x20;
				// PLP + RTL
				*LPBYTE(rom + snes2pc(0x80E607)) = 0x28;
				*LPBYTE(rom + snes2pc(0x80E608)) = 0x6B;
			}

			// <camera locks>
			// format of new camera lock:
			// AA BB CC DD EE FF GG HH
			// A = right
			// B = left
			// C = bottom
			// D = top
			// E = right lock
			// F = left lock
			// G = bottom lock
			// H = top lock
			lockBank = pc2snes(currentOffset) >> 16;
			memset(nmmx.rom + currentOffset, 0x0, 0x8000);
			// copy the border lock to new flattened format
			std::map<DWORD, DWORD> nextAddress;
			for (unsigned i = 0; i < numLevels; i++) {
				DWORD pB = SReadWord(p_borders[type] + i * 2) | ((p_borders[type] >> 16) << 16);
				DWORD pBNext = SReadWord(p_borders[type] + (i + 1) * 2) | ((p_borders[type] >> 16) << 16);

				if (nextAddress.count(pB)) {
					pBNext = nextAddress[pB];
				}
				else if (nextAddress.count(pBNext)) {
					pBNext = pB + (type == 0 ? 0x0 : type == 1 ? 0x0 : 0x20);
				}
				nextAddress[pB] = pBNext;

				for (unsigned j = 0; j < (pBNext - pB) / 2; j++) {
					DWORD borderAddress = SReadWord(pB + j * 2) | ((p_borders[type] >> 16) << 16);
					LPBYTE b = rom + SNESCore::snes2pc(borderAddress);

					for (unsigned k = 0; k < 4; k++) {
						*LPWORD(rom + currentOffset + i * 0x800 + j * 0x20 + k * 2) = *LPWORD(b);
						b += 2;
					}

					unsigned newOffset = 0;
					while (*b) {
						// load and save lock in proper spot
						unsigned lockOffset = *b;
						unsigned offset = (lockOffset - 1) << 2;

						WORD camOffset = *LPWORD(nmmx.rom + nmmx.pLocks + offset + 0x0);
						WORD camValue = *LPWORD(nmmx.rom + nmmx.pLocks + offset + 0x2);

						*LPWORD(rom + currentOffset + i * 0x800 + j * 0x20 + 0x8 + newOffset) = camOffset;
						newOffset += 2;
						*LPWORD(rom + currentOffset + i * 0x800 + j * 0x20 + 0x8 + newOffset) = camValue;
						newOffset += 2;

						b++;
					}
					for (; newOffset < 0x18; newOffset += 2) {
						*LPWORD(rom + currentOffset + i * 0x800 + j * 0x20 + 0x8 + newOffset) = 0x0;
					}

				}
			}
			currentOffset += 0x8000;
			// write new code
			// fix jump table
			*LPWORD(rom + snes2pc(type == 0 ? 0x81F6B6 : type == 1 ? 0x82EB2D : 0x83DD87)) -= 0x2; // TYPE

			a = type == 0 ? 0x81F6C4 : type == 1 ? 0x82EB3B : 0x83DD95; // TYPE
			// 1 ASL
			*LPBYTE(rom + snes2pc(a++)) = 0x0A;
			// 1 ASL
			*LPBYTE(rom + snes2pc(a++)) = 0x0A;
			// 1 ASL
			*LPBYTE(rom + snes2pc(a++)) = 0x0A;
			// 1 ASL
			*LPBYTE(rom + snes2pc(a++)) = 0x0A;
			// 2 STA 0
			*LPBYTE(rom + snes2pc(a++)) = 0x8D;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			// 3 LDA $1F7A
			*LPBYTE(rom + snes2pc(a++)) = 0xAD;
			*LPWORD(rom + snes2pc(a++)) = type == 0 ? 0x1F7A : type == 1 ? 0x1FAD : 0x1FAE; // TYPE
			a++;
			// 3 AND #FF
			*LPBYTE(rom + snes2pc(a++)) = 0x29;
			*LPBYTE(rom + snes2pc(a++)) = 0xFF;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			// 1 XBA
			*LPBYTE(rom + snes2pc(a++)) = 0xEB;
			// 1 ASL
			*LPBYTE(rom + snes2pc(a++)) = 0x0A;
			// 1 ASL
			*LPBYTE(rom + snes2pc(a++)) = 0x0A;
			// 1 ASL
			*LPBYTE(rom + snes2pc(a++)) = 0x0A;
			// 3 ADC 0
			*LPBYTE(rom + snes2pc(a++)) = 0x6D;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			// 2 STA D,4
			*LPBYTE(rom + snes2pc(a++)) = 0x85;
			*LPBYTE(rom + snes2pc(a++)) = 0x04;

			// 2 REP #30
			*LPBYTE(rom + snes2pc(a++)) = 0xC2;
			*LPBYTE(rom + snes2pc(a++)) = 0x20 | 0x10;
			// 2 LDX D,4
			*LPBYTE(rom + snes2pc(a++)) = 0xA6;
			*LPBYTE(rom + snes2pc(a++)) = 0x04;
			// 3 LDA $0BAD
			*LPBYTE(rom + snes2pc(a++)) = 0xAD;
			*LPWORD(rom + snes2pc(a++)) = type == 0 ? 0x0BAD : type == 1 ? 0x9DD : 0x9DD; // TYPE
			a++;
			// 4 CMP BANK:8000,X
			*LPBYTE(rom + snes2pc(a++)) = 0xDF;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			// 2 BCS
			*LPBYTE(rom + snes2pc(a++)) = 0xB0;
			*LPBYTE(rom + snes2pc(a++)) = 0x2F; // FIXME
			// 4 CMP BANK:8002,X
			*LPBYTE(rom + snes2pc(a++)) = 0xDF;
			*LPBYTE(rom + snes2pc(a++)) = 0x02;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			// 2 BCC
			*LPBYTE(rom + snes2pc(a++)) = 0x90;
			*LPBYTE(rom + snes2pc(a++)) = 0x29; // FIXME
			// 3 LDA $0BB0
			*LPBYTE(rom + snes2pc(a++)) = 0xAD;
			*LPWORD(rom + snes2pc(a++)) = type == 0 ? 0x0BB0 : type == 1 ? 0x9E0 : 0x9E0; // TYPE
			a++;
			// 4 CMP BANK:8004,X
			*LPBYTE(rom + snes2pc(a++)) = 0xDF;
			*LPBYTE(rom + snes2pc(a++)) = 0x04;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			// 2 BCS
			*LPBYTE(rom + snes2pc(a++)) = 0xB0;
			*LPBYTE(rom + snes2pc(a++)) = 0x20; // FIXME
			// 4 CMP BANK:8006,X
			*LPBYTE(rom + snes2pc(a++)) = 0xDF;
			*LPBYTE(rom + snes2pc(a++)) = 0x06;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			// 2 BCC
			*LPBYTE(rom + snes2pc(a++)) = 0x90;
			*LPBYTE(rom + snes2pc(a++)) = 0x1A; // FIXME
			// 3 LDA #2
			*LPBYTE(rom + snes2pc(a++)) = 0xA9;
			*LPBYTE(rom + snes2pc(a++)) = 0x02;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			// 3 STA $1E52
			*LPBYTE(rom + snes2pc(a++)) = 0x8D;
			*LPWORD(rom + snes2pc(a++)) = type == 0 ? 0x1E52 : type == 1 ? 0x1E62 : 0x1E62; // TYPE
			a++;

			//// 3 JMP FFD0
			//*LPBYTE(rom + snes2pc(a++)) = 0x4C;
			//*LPBYTE(rom + snes2pc(a++)) = 0xD0;
			//*LPBYTE(rom + snes2pc(a++)) = 0xFF;
			//// 2 SEP #30,$20
			//*LPBYTE(rom + snes2pc(a++)) = 0xE2;
			//*LPBYTE(rom + snes2pc(a++)) = 0x20 | 0x10;
			//// 1 RTS
			//*LPBYTE(rom + snes2pc(a++)) = 0x60;
			//// @ FFD0
			//a = 0x81FFD0;

			// 4 LDA BANK:8008,X
			*LPBYTE(rom + snes2pc(a++)) = 0xBF;
			*LPBYTE(rom + snes2pc(a++)) = 0x08;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			// 2 BEQ
			*LPBYTE(rom + snes2pc(a++)) = 0xF0;
			*LPBYTE(rom + snes2pc(a++)) = 0x0E; // FIXME
			// 1 TAY
			*LPBYTE(rom + snes2pc(a++)) = 0xA8;
			// 1 INX
			*LPBYTE(rom + snes2pc(a++)) = 0xE8;
			// 1 INX
			*LPBYTE(rom + snes2pc(a++)) = 0xE8;
			// 4 LDA BANK:8008,X
			*LPBYTE(rom + snes2pc(a++)) = 0xBF;
			*LPBYTE(rom + snes2pc(a++)) = 0x08;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			// 1 INX
			*LPBYTE(rom + snes2pc(a++)) = 0xE8;
			// 1 INX
			*LPBYTE(rom + snes2pc(a++)) = 0xE8;
			// 3 STA addr,Y
			*LPBYTE(rom + snes2pc(a++)) = 0x99;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			// 2 BRA
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = 0xEC; // FIXME

			// 2 SEP #20,#10
			*LPBYTE(rom + snes2pc(a++)) = 0xE2;
			*LPBYTE(rom + snes2pc(a++)) = 0x20 | 0x10;
			// 1 RTS
			*LPBYTE(rom + snes2pc(a++)) = 0x60;

			// fix the event ending functions
			*LPWORD(rom + snes2pc(type == 0 ? 0x81F6B1 : type == 1 ? 0x82EB27 : 0x83DD81)) -= 0x4; // TYPE
			a = type == 0 ? 0x81F722 : type == 1 ? 0x82EB99 : 0x83DDF3; // TYPE
			memmove(rom + SNESCore::snes2pc(a - 1), rom + SNESCore::snes2pc(a - 0), 0x41);
			memmove(rom + SNESCore::snes2pc(a - 2), rom + SNESCore::snes2pc(a - 1), 0x36);
			memmove(rom + SNESCore::snes2pc(a - 3), rom + SNESCore::snes2pc(a - 2), 0x20);
			memmove(rom + SNESCore::snes2pc(a - 4), rom + SNESCore::snes2pc(a - 3), 0x15);
			a += 0x0F; // 0x81F731;
			*LPBYTE(rom + snes2pc(a++)) = 0xBF;
			*LPBYTE(rom + snes2pc(a++)) = 0x00;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			a += 0x08; // 0x81F73D;
			*LPBYTE(rom + snes2pc(a++)) = 0xBF;
			*LPBYTE(rom + snes2pc(a++)) = 0x02;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			a += 0x13; //  0x81F754;
			*LPBYTE(rom + snes2pc(a++)) = 0xBF;
			*LPBYTE(rom + snes2pc(a++)) = 0x04;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			a += 0x08; // 0x81F760;
			*LPBYTE(rom + snes2pc(a++)) = 0xBF;
			*LPBYTE(rom + snes2pc(a++)) = 0x06;
			*LPBYTE(rom + snes2pc(a++)) = 0x80;
			*LPBYTE(rom + snes2pc(a++)) = lockBank;
			// fix branches 0x64
			*LPBYTE(rom + snes2pc(a - 0x2C)) += 0x3; // 0x81F738
			*LPBYTE(rom + snes2pc(a - 0x28)) += 0x1; // 0x81F73C
			*LPBYTE(rom + snes2pc(a - 0x20)) += 0x2; // 0x81F744
			*LPBYTE(rom + snes2pc(a - 0x09)) += 0x1; // 0x81F75B
			*LPBYTE(rom + snes2pc(a - 0x05)) += 0x1; // 0x81F75F

			header->romSize++;
			romSize += 0x100000;
			expandedLayoutSize = 0x800;
			expandedEventSize = 0x800;
			expandedCheckpointSize = 0x10;
			expandedLayoutScenes = 0x40;
			expandedVersion = expandedROMVersion;
		}
	}
	else {
		if (ok) {
			// make the ROM bigger
			// Add 1MB
			memset(rom + romSize, 0xFF, 0x200000);
			char *myarg1 = (char*)(rom + romSize + 0x8000 - expandedROMHeaderSize);
			strcpy_s(myarg1, sizeof(myarg1), expandedROMString);
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0xE, &expandedROMVersion, 2);
			WORD v;
			v = 0x800;
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0x10, &v, 2);
			v = 0x800;
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0x12, &v, 2);
			v = 0x10;
			memcpy(rom + romSize + 0x8000 - expandedROMHeaderSize + 0x14, &v, 2);
			// sceneUsed already stored in the ROM

			// copy startup code
			memcpy(rom + romSize + 0x8000, rom + 0x8000, 0x8000);
		}

		unsigned currentOffset = romSize + 0x10000;

		if (ok) {
			expandedROM = true;

			header->romSize++;
			header->mapMode |= 0x4;
			romSize += 0x200000;
			expandedLayoutSize = 0x800;
			expandedEventSize = 0x800;
			expandedCheckpointSize = 0x0;
			expandedLayoutScenes = 0x40;
			expandedVersion = expandedROMVersion;
		}
	}

	return ok;
}
