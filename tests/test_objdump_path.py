import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mapuche.asm import (
    detect_objdump,
    find_objdump_in,
    load_disassembly,
    resolve_user_objdump,
    run_objdump,
    scan_map_file,
    toolchain_bin_dir,
)


class ObjdumpPathTest(unittest.TestCase):
    def test_scan_uses_libc_a_not_libesp_libc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            libc = root / 'picolibc' / 'libc.a'
            libc.parent.mkdir()
            libc.write_text('archive')
            elf = root / 'app.elf'
            elf.write_bytes(b'')
            map_file = root / 'app.map'
            map_file.write_text(
                'OUTPUT(app.elf elf)\n'
                f'{root}/tool/bin/../picolibc/libc.a\n'
                f'{root}/esp_libc/libesp_libc.a\n'
            )
            found_elf, found_libc = scan_map_file(map_file)
        self.assertEqual(found_elf, elf.resolve())
        self.assertTrue(str(found_libc).endswith('/picolibc/libc.a'))
        self.assertNotIn('libesp_libc.a', found_libc)

    def test_missing_elf_is_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            map_file = Path(tmp) / 'app.map'
            map_file.write_text('OUTPUT(missing.elf)\n')
            elf, libc = scan_map_file(map_file)
        self.assertIsNone(elf)
        self.assertIsNone(libc)

    def test_toolchain_bin_dir_is_the_first_bin_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'tool' / 'bin'
            bin_dir.mkdir(parents=True)
            libc = f'{tmp}/tool/bin/../picolibc/rv32/libc.a'
            self.assertEqual(toolchain_bin_dir(libc), bin_dir)
        self.assertIsNone(toolchain_bin_dir('/no/such/bin/../libc.a'))
        self.assertIsNone(toolchain_bin_dir(None))

    def test_prefixed_objdump_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'tool' / 'bin'
            bin_dir.mkdir(parents=True)
            (bin_dir / 'objdump').write_text('')
            prefixed = bin_dir / 'riscv32-esp-elf-objdump'
            prefixed.write_text('')
            self.assertEqual(find_objdump_in(bin_dir), prefixed)
            self.assertEqual(detect_objdump([f'{tmp}/tool/bin/../libc.a']), prefixed)

    def test_user_path_may_be_a_binary_or_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'my-objdump'
            binary.write_text('')
            self.assertEqual(resolve_user_objdump(str(binary)), binary)
            self.assertEqual(resolve_user_objdump(tmp), binary)
        self.assertIsNone(resolve_user_objdump(''))
        self.assertIsNone(resolve_user_objdump('/no/such/objdump'))

    def test_source_flag_selects_objdump_s_and_is_cached(self):
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))

            class Proc:
                returncode = 0
                stdout = '1000 <foo>:\n1000:\tnop\n'
                stderr = ''

            return Proc()

        with patch('mapuche.asm.subprocess.run', fake_run):
            cache = {}
            first = load_disassembly('objdump', 'app.elf', True, False, cache)
            again = load_disassembly('objdump', 'app.elf', True, False, cache)
            sourced = load_disassembly('objdump', 'app.elf', True, True, cache)
        self.assertIs(first, again)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('-S', calls[0])
        self.assertNotIn('--no-show-raw-insn', calls[0])
        self.assertIn('-C', calls[0])
        self.assertIn('-S', calls[1])
        self.assertTrue(any(kind == 'i' for _addr, _seq, kind, _rest in sourced))

    def test_bad_objdump_is_an_error(self):
        def fake_run(cmd, **_kwargs):
            class Proc:
                returncode = 1
                stdout = 'app.elf:     file format elf32-littleriscv\n'
                stderr = "can't disassemble for architecture UNKNOWN!"

            return Proc()

        with patch('mapuche.asm.subprocess.run', fake_run):
            with self.assertRaises(RuntimeError) as caught:
                run_objdump('objdump', 'app.elf', False)
        self.assertIn('UNKNOWN', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
