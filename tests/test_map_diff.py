import tempfile
import unittest
from pathlib import Path

from mapuche.demangle import demangle_map_name
from mapuche.parser import generate_diff_table, parse_map_file


def _write_map(directory, name, size, symbols):
    # The parser discards the first line that starts with "." after the map header.
    body = ['Linker script and memory map', '', '.discard', f'.iram0.text     0x40380000     {size}']
    address = 0x40380000
    for symbol, symbol_size in symbols:
        body.append(f' .text.{symbol}  0x{address:08x}     {symbol_size} lib/libfoo.a(foo.c.obj)')
        body.append(f'                0x{address:08x}                {symbol}')
        address += int(symbol_size, 16)
    path = Path(directory) / name
    path.write_text('\n'.join(body) + '\n')
    return path


class MapDiffTest(unittest.TestCase):
    def test_equal_totals_do_not_remove_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_map(tmp, 'same.map', '0x10', [('foo', '0x10')])
            tree = generate_diff_table(path, path)
        self.assertIsNone(tree.parent)
        self.assertEqual(tree.value.name, 'Total')
        self.assertEqual(tree.value.diff, 0)
        self.assertEqual(tree.children, [])

    def test_size_change_keeps_both_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_map(tmp, 'old.map', '0x10', [('foo', '0x10')])
            new = _write_map(tmp, 'new.map', '0x18', [('foo', '0x18')])
            tree = generate_diff_table(new, old)
        self.assertEqual(tree.value.diff, 8)
        self.assertTrue(tree.children)
        section = tree.children[0]
        self.assertEqual(section.value.size_a, 0x18)
        self.assertEqual(section.value.size_b, 0x10)
        self.assertEqual(section.value.address_a, 0x40380000)
        self.assertEqual(section.value.address_b, 0x40380000)


class LooseObjectTest(unittest.TestCase):
    def test_object_path_does_not_insert_a_nameless_node(self):
        body = [
            'Linker script and memory map',
            '',
            '.discard',
            '.xtensa.info    0x00000000       0x38',
            ' .xtensa.info   0x00000000       0x38 CMakeFiles/hello_world.elf.dir/project_elf_src_esp32s3.c.obj',
            ' .xtensa.info   0x00000038        0x0 esp-idf/libfoo.a(bar.c.obj)',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'app.map'
            path.write_text('\n'.join(body) + '\n')
            tree = parse_map_file(path)
        section = tree.find_child_by_name('.xtensa.info')
        obj = section.find_child_by_name('project_elf_src_esp32s3.c.obj')
        self.assertIsNotNone(obj)
        self.assertIsNone(obj.find_child_by_name(None))
        self.assertEqual([child.value.name for child in obj.children], ['.xtensa.info'])
        archive = section.find_child_by_name('libfoo.a')
        member = archive.find_child_by_name('bar.c.obj')
        self.assertEqual([child.value.name for child in member.children], ['.xtensa.info'])
        self.assertEqual(demangle_map_name(None), '')


if __name__ == '__main__':
    unittest.main()
