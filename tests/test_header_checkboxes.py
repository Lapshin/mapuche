import tempfile
import unittest
from pathlib import Path

from textual.widgets import Checkbox, DataTable, Label

from mapuche.asm import format_asm_view
from mapuche.mapuche import AsmScreen, MyHeader, TableApp


def _write_map(directory):
    body = [
        'Linker script and memory map',
        '',
        '.discard',
        '.debug_info     0x00000000     0x10',
        '.iram0.text     0x40380000     0x10',
        ' .text.foo      0x40380000     0x10 lib/libfoo.a(foo.c.obj)',
        '                0x40380000                _Z3foov',
    ]
    path = Path(directory) / 'app.map'
    path.write_text('\n'.join(body) + '\n')
    return path


def _style_key(box):
    styles = box.styles
    return (
        str(styles.height),
        str(styles.border),
        str(styles.padding),
        str(styles.margin),
    )


def _row_names(table):
    names = []
    for key in table.rows:
        cell = table.get_row(key)[0]
        names.append(getattr(cell, 'plain', str(cell)))
    return names


class HeaderCheckboxTest(unittest.IsolatedAsyncioTestCase):
    async def test_header_uses_diff_viewer_checkboxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp))
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                boxes = list(app.query(Checkbox))
                self.assertEqual(len(app.query('#compare-files')), 0)
                self.assertEqual([str(box.label) for box in boxes], ['Debug sections', 'C++ demangle'])
                self.assertEqual([box.value for box in boxes], [False, True])
                for box in boxes:
                    self.assertIn('▐', box.render().plain)
                    self.assertNotIn('[', box.render().plain)

                view = format_asm_view('ret\n', 'nop\n', 'build/a.map', 'build_old/b.map', True)
                await app.push_screen(AsmScreen('foo', view, []))
                await pilot.pause()
                asm_boxes = list(app.screen.query(Checkbox))
                self.assertEqual(
                    [_style_key(box) for box in boxes],
                    [_style_key(box) for box in asm_boxes],
                )
                self.assertNotEqual(boxes[0].styles.background, asm_boxes[0].styles.background)
                await pilot.press('escape')
                await pilot.pause()

                table = app.query_one(DataTable)
                self.assertFalse(any('.debug_info' in name for name in _row_names(table)))
                await pilot.click('#show_debug')
                await pilot.pause()
                self.assertTrue(app.show_debug)
                self.assertTrue(any('.debug_info' in name for name in _row_names(table)))

                await pilot.click('#cxx_demangle')
                await pilot.pause()
                self.assertFalse(app.cxx_demangle)

    async def test_compare_line_names_the_two_maps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new = root / 'firmware' / 'app.map'
            old = root / 'previous' / 'app.map'
            for path, size in ((new, '0x18'), (old, '0x10')):
                path.parent.mkdir()
                path.write_text(
                    '\n'.join([
                        'Linker script and memory map',
                        '',
                        '.discard',
                        f'.text           0x40380000     {size}',
                        f' .text.foo      0x40380000     {size} lib/libfoo.a(foo.c.obj)',
                        '                0x40380000                foo',
                    ]) + '\n'
                )
            app = TableApp(new, old)
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                header = app.query_one(MyHeader)
                line = app.query_one('#compare-files')
                box = app.query_one('#show_debug', Checkbox)
                self.assertEqual(header.outer_size.height, 4)
                self.assertLess(line.region.y, box.region.y)
                self.assertEqual(app.query_one('#compare-diff', Label).content, 'Diff ==')
                self.assertEqual(app.query_one('#compare-a', Label).content, 'firmware/app.map')
                self.assertEqual(app.query_one('.compare-op', Label).content, '-')
                self.assertEqual(app.query_one('#compare-b', Label).content, 'previous/app.map')
                self.assertEqual(
                    [label.content for label in app.query('.compare-quote')],
                    ['"', '"', '"', '"'],
                )
                self.assertNotIn(str(root), app.query_one('#compare-a', Label).content)
                table = app.query_one(DataTable)
                name = app.query_one('#compare-a', Label)
                closing = list(app.query('.compare-quote'))[1]
                self.assertGreater(line.outer_size.width, table.virtual_size.width)
                self.assertEqual(line.outer_size.width, header.size.width)
                self.assertEqual(closing.region.x, name.region.right)


if __name__ == '__main__':
    unittest.main()
