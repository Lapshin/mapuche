import struct
import tempfile
import unittest
from pathlib import Path

from mapuche.asm import ElfImage, HexBlob, collect_asm_targets, collect_hex_targets, view_from_hex
from mapuche.models import MapValue, TreeNode

_DELETE = '7a3038'
_INSERT = '1f6b3a'


def _hit_text(text, needle):
    return [text.plain[span.start:span.end] for span in text.spans if needle in str(span.style)]


def _elf(sections):
    """Minimal ELF32. `sections` is (name, address, bytes or NOBITS size)."""
    cursor = 52
    laid = []
    blobs = []
    for name, addr, payload in sections:
        if isinstance(payload, int):
            laid.append((name, addr, 8, payload, 0))
        else:
            laid.append((name, addr, 1, len(payload), cursor))
            blobs.append(payload)
            cursor += len(payload)
    shstr = b'\x00'
    name_at = {}
    for name, *_rest in laid:
        name_at[name] = len(shstr)
        shstr += name.encode() + b'\x00'
    shstr_name = len(shstr)
    shstr += b'.shstrtab\x00'
    shstr_off = cursor
    cursor += len(shstr)
    shoff = cursor
    shnum = 2 + len(laid)
    shstrndx = 1 + len(laid)

    def shdr(name_off, kind, addr, offset, size):
        return struct.pack('<IIIIIIIIII', name_off, kind, 2, addr, offset, size, 0, 0, 1, 0)

    headers = [shdr(0, 0, 0, 0, 0)]
    for name, addr, kind, size, offset in laid:
        headers.append(shdr(name_at[name], kind, addr, offset, size))
    headers.append(shdr(shstr_name, 3, 0, shstr_off, len(shstr)))
    ident = b'\x7fELF' + bytes([1, 1, 1]) + b'\x00' * 9
    elf_header = struct.pack('<HHIIIIIHHHHHH', 2, 0x5e, 1, 0, 0, shoff, 0, 52, 0, 0, 40, shnum, shstrndx)
    return ident + elf_header + b''.join(blobs) + shstr + b''.join(headers)


class ElfBytesTest(unittest.TestCase):
    def test_reads_progbits_and_bss_zeros(self):
        blob = _elf([
            ('.rodata', 0x2000, b'hello'),
            ('.bss', 0x3000, 8),
            ('.xtensa.info', 0, b'info'),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'app.elf'
            path.write_bytes(blob)
            image = ElfImage(path)
        self.assertEqual(image.read(0x2001, 3, '.rodata'), b'ell')
        self.assertEqual(image.read(0x3002, 4, '.bss'), b'\x00\x00\x00\x00')
        self.assertEqual(image.read(0, 4, '.xtensa.info'), b'info')
        self.assertEqual(image.read(0x4000, 4, '.rodata'), b'')


class HexTargetTest(unittest.TestCase):
    def test_data_section_is_one_range_and_code_is_not(self):
        root = TreeNode(MapValue('Total'))
        text = root.add_child(MapValue('.text', 0x1000, 8))
        text.add_child(MapValue('foo', 0x1000, 8))
        rodata = root.add_child(MapValue('.rodata', 0x2000, 8))
        message = rodata.add_child(MapValue('msg', 0x2000, 4))
        info = root.add_child(MapValue('.xtensa.info', 0, 0x38))

        self.assertEqual(collect_hex_targets(text, False), [])
        self.assertTrue(collect_asm_targets(text, False))
        section = collect_hex_targets(rodata, False)
        self.assertEqual([(span.name, span.address, span.size) for span in section], [('.rodata', 0x2000, 8)])
        symbol = collect_hex_targets(message, False)
        self.assertEqual([(span.name, span.address, span.size, span.section) for span in symbol], [('msg', 0x2000, 4, '.rodata')])
        named = collect_hex_targets(info, False)
        self.assertEqual([(span.name, span.address, span.size) for span in named], [('.xtensa.info', 0, 0x38)])


class HexViewTest(unittest.TestCase):
    def test_only_the_changed_byte_is_marked(self):
        blob = HexBlob('msg', 0x1000, b'hellp', False, 0x1000, b'hello', False)
        view = view_from_hex([blob], 'now.map', 'then.map', True, True)
        self.assertTrue(view.side_by_side)
        self.assertFalse(view.match)
        left = next(line for line in view.left_lines if '6f' in line.plain)
        right = next(line for line in view.right_lines if '70' in line.plain)
        self.assertEqual(_hit_text(left, _DELETE), ['6f', 'o'])
        self.assertEqual(_hit_text(right, _INSERT), ['70', 'p'])
        self.assertNotIn('68', _hit_text(left, _DELETE))
        self.assertIn('<msg>:', view.left_lines[0].plain)

    def test_same_bytes_keep_addresses_out_of_the_byte_diff(self):
        blob = HexBlob('msg', 0x1000, b'ab', False, 0x2000, b'ab', False)
        shown = view_from_hex([blob], 'n', 'o', True, True)
        hidden = view_from_hex([blob], 'n', 'o', True, False)
        self.assertTrue(shown.match)
        left = next(line for line in shown.left_lines if '61' in line.plain)
        self.assertNotIn('61', _hit_text(left, _DELETE))
        self.assertIn('2000', left.plain)
        self.assertNotIn('2000', hidden.left_lines[-1].plain)
        self.assertIn('61', hidden.left_lines[-1].plain)

    def test_single_map_is_one_pane(self):
        blob = HexBlob('msg', 0x1000, b'ab', False, 0, b'', False)
        view = view_from_hex([blob], 'only.map', '', False, False)
        self.assertFalse(view.side_by_side)
        self.assertIn('61 62', view.left_lines[-1].plain)


if __name__ == '__main__':
    unittest.main()
