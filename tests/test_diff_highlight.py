import tempfile
import unittest
from pathlib import Path

from rich.color import Color
from textual.widgets import Checkbox, DataTable

from mapuche.mapuche import TableApp, fully_reduced


def _write_map(directory, name, text_size, data_size):
    body = [
        'Linker script and memory map',
        '',
        '.discard',
        f'.text           0x40380000     {text_size}',
        f' .text.foo      0x40380000     {text_size} lib/libfoo.a(foo.c.obj)',
        '                0x40380000                foo',
        f'.data           0x3fc80000     {data_size}',
        f' .data.bar      0x3fc80000     {data_size} lib/libfoo.a(bar.c.obj)',
        '                0x3fc80000                bar',
    ]
    path = Path(directory) / name
    path.write_text('\n'.join(body) + '\n')
    return path


def _write_mixed(directory, name, section_size, foo_size, bar_size, bar_address):
    body = [
        'Linker script and memory map',
        '',
        '.discard',
        f'.iram0.text     0x40380000     {section_size}',
        f' .text.foo      0x40380000     {foo_size} lib/libfoo.a(foo.c.obj)',
        '                0x40380000                foo',
        f' .text.bar      0x{bar_address:08x}     {bar_size} lib/libfoo.a(foo.c.obj)',
        f'                0x{bar_address:08x}                bar',
    ]
    path = Path(directory) / name
    path.write_text('\n'.join(body) + '\n')
    return path


def _row_names(table):
    names = []
    for key in table.rows:
        cell = table.get_row(key)[0]
        names.append(getattr(cell, 'plain', str(cell)))
    return names


def _plain_name(cell_text):
    if '── ' in cell_text:
        return cell_text.split('── ', 1)[1]
    return cell_text


def _expand_all(node):
    node.expand = bool(node.children)
    for child in node.children:
        _expand_all(child)


def _visible_names(app):
    _expand_all(app.table_data)
    names = ['Total']
    for cells, _node in app.collect_rows(app.table_data):
        names.append(_plain_name(getattr(cells[0], 'plain', str(cells[0]))))
    return names


def _paint(table):
    # Widget.render_lines runs the NO_COLOR filter and drops these colors.
    width = table.size.width
    base = table.rich_style
    return [
        table._render_line(y, 0, width, base)
        for y in range(table.header_height + table.row_count)
    ]


def _line_with(strips, needle):
    for strip in strips:
        text = ''.join(segment.text for segment in strip)
        if needle in text:
            return strip
    return None


def _has_fg(strip, name):
    for segment in strip:
        color = segment.style.color if segment.style else None
        if color is not None and color.name == name and segment.text.strip():
            return True
    return False


def _has_bg(strip, hex_color):
    want = Color.parse(hex_color).triplet
    for segment in strip:
        color = segment.style.bgcolor if segment.style else None
        if color is not None and color.triplet == want:
            return True
    return False


class DiffHighlightTest(unittest.IsolatedAsyncioTestCase):
    async def test_reduced_is_green_and_growth_is_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_map(tmp, 'old.map', '0x20', '0x10')
            new = _write_map(tmp, 'new.map', '0x10', '0x20')
            app = TableApp(new, old)
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                table = app.query_one(DataTable)
                names = _row_names(table)
                self.assertTrue(any('.text' in name and '.data' not in name for name in names))
                self.assertTrue(any('.data' in name for name in names))

                strips = _paint(table)
                text_row = _line_with(strips, '.text')
                data_row = _line_with(strips, '.data')
                total_row = _line_with(strips, 'Total')
                self.assertIsNotNone(text_row)
                self.assertIsNotNone(data_row)
                self.assertTrue(_has_fg(text_row, 'green'), _dump(text_row))
                self.assertTrue(_has_bg(text_row, '#1c3326'), _dump(text_row))
                self.assertTrue(_has_fg(data_row, 'red'), _dump(data_row))
                self.assertTrue(_has_bg(data_row, '#3a2428'), _dump(data_row))
                self.assertFalse(_has_fg(total_row, 'green'))
                self.assertFalse(_has_fg(total_row, 'red'))

                await pilot.press('down')
                await pilot.pause()
                selected = _line_with(_paint(table), '.text')
                self.assertTrue(_has_fg(selected, 'green'), _dump(selected))

                boxes = list(app.query(Checkbox))
                self.assertEqual(
                    [str(box.label) for box in boxes],
                    ['Debug sections', 'C++ demangle', 'Hide reduced'],
                )
                self.assertFalse(boxes[-1].value)
                descriptions = [item.binding.description for item in app.screen.active_bindings.values()]
                self.assertNotIn('hide reduced', descriptions)

                await pilot.click('#hide_reduced')
                await pilot.pause()
                hidden = _row_names(table)
                self.assertTrue(app.hide_reduced)
                self.assertFalse(any('.text' in name and '.data' not in name for name in hidden))
                self.assertTrue(any('.data' in name for name in hidden))

                await pilot.click('#hide_reduced')
                await pilot.pause()
                shown = _row_names(table)
                self.assertFalse(app.hide_reduced)
                self.assertTrue(any('.text' in name and '.data' not in name for name in shown))

    async def test_single_map_has_no_hide_reduced_checkbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_map(tmp, 'app.map', '0x10', '0x10')
            app = TableApp(path)
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                labels = [str(box.label) for box in app.query(Checkbox)]
                self.assertEqual(labels, ['Debug sections', 'C++ demangle'])
                strips = _paint(app.query_one(DataTable))
                text_row = _line_with(strips, '.text')
                self.assertFalse(_has_fg(text_row, 'green'))
                self.assertFalse(_has_fg(text_row, 'red'))


class HideReducedTreeTest(unittest.TestCase):
    def test_shrunk_parent_stays_when_a_child_grew(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write_mixed(tmp, 'old.map', '0x30', '0x20', '0x10', 0x40380020)
            new = _write_mixed(tmp, 'new.map', '0x20', '0x08', '0x18', 0x40380008)
            app = TableApp(new, old)
        section = app.table_data.find_child_by_name('.iram0.text')
        self.assertLess(section.value.diff, 0)
        self.assertFalse(fully_reduced(section))
        foo = _find(section, 'foo')
        bar = _find(section, 'bar')
        self.assertTrue(fully_reduced(foo))
        self.assertFalse(fully_reduced(bar))

        app.hide_reduced = True
        names = _visible_names(app)
        self.assertIn('.iram0.text', names)
        self.assertIn('.text.bar', names)
        self.assertIn('bar', names)
        self.assertNotIn('.text.foo', names)
        self.assertNotIn('foo', names)


def _find(node, name):
    if node.value.name == name:
        return node
    for child in node.children:
        found = _find(child, name)
        if found is not None:
            return found
    return None


def _dump(strip):
    parts = []
    for segment in strip:
        color = segment.style.color.name if segment.style and segment.style.color else None
        bgcolor = segment.style.bgcolor.name if segment.style and segment.style.bgcolor else None
        if segment.text.strip():
            parts.append(f'{segment.text!r} fg={color} bg={bgcolor}')
    return ' '.join(parts)


if __name__ == '__main__':
    unittest.main()
