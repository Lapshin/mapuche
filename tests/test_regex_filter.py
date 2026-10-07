import re
import tempfile
import unittest
from pathlib import Path

from textual.widgets import Checkbox, DataTable, Input, Label

from mapuche.mapuche import TableApp


def _write_map(directory, name='app.map', symbol='foo'):
    body = [
        'Linker script and memory map',
        '',
        '.discard',
        '.debug_info     0x00000000     0x10',
        '.text           0x40380000     0x10',
        ' .text.foo      0x40380000     0x10 lib/libfoo.a(foo.c.obj)',
        f'                0x40380000                {symbol}',
        '.data           0x3fc80000     0x10',
        ' .data.bar      0x3fc80000     0x10 lib/libfoo.a(bar.c.obj)',
        '                0x3fc80000                bar',
    ]
    path = Path(directory) / name
    path.write_text('\n'.join(body) + '\n')
    return path


def _write_sized(directory, name, text_size, data_size):
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


def _plain(cell):
    text = getattr(cell, 'plain', str(cell))
    if '── ' in text:
        return text.split('── ', 1)[1]
    return text


def _shown(app):
    names = ['Total']
    for cells, _node in app.collect_rows(app.table_data):
        names.append(_plain(cells[0]))
    return names


class RegexFilterTreeTest(unittest.TestCase):
    def test_symbol_match_opens_ancestors_and_hides_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp))
            app._name_filter = re.compile(r'^foo$')
            app._sync_filter_expansion()
            names = _shown(app)
            self.assertIn('foo', names)
            self.assertIn('.text', names)
            self.assertIn('libfoo.a', names)
            self.assertIn('foo.c.obj', names)
            self.assertIn('.text.foo', names)
            self.assertNotIn('.data', names)
            self.assertNotIn('bar', names)
            self.assertNotIn('.debug_info', names)

            app._name_filter = None
            app._sync_filter_expansion()
            self.assertFalse(app.table_data.find_child_by_name('.text').expand)
            closed = _shown(app)
            self.assertIn('.text', closed)
            self.assertNotIn('foo', closed)
            self.assertIn('.data', closed)

    def test_section_match_stays_collapsed_until_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp))
            app._name_filter = re.compile(r'^\.text$')
            app._sync_filter_expansion()
            section = app.table_data.find_child_by_name('.text')
            self.assertFalse(section.expand)
            self.assertEqual(_shown(app), ['Total', '.text'])

            section.expand = True
            opened = _shown(app)
            self.assertIn('libfoo.a', opened)
            self.assertNotIn('foo', opened)
            self.assertNotIn('.data', opened)

    def test_user_expanded_section_survives_clearing_the_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp))
            section = app.table_data.find_child_by_name('.text')
            section.expand = True
            app._name_filter = re.compile(r'^bar$')
            app._sync_filter_expansion()
            app._name_filter = None
            app._sync_filter_expansion()
            self.assertTrue(section.expand)
            self.assertIn('libfoo.a', _shown(app))

    def test_demangled_and_mangled_names_both_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp, symbol='_Z3foov'))
            app._name_filter = re.compile(r'foo\(\)')
            app._sync_filter_expansion()
            self.assertIn('foo()', _shown(app))

            app._name_filter = re.compile(r'_Z3foov')
            app._sync_filter_expansion()
            self.assertIn('foo()', _shown(app))

            app._name_filter = re.compile(r'foo\(\)')
            app.cxx_demangle = False
            app._sync_filter_expansion()
            hidden = _shown(app)
            self.assertNotIn('_Z3foov', hidden)
            self.assertNotIn('foo()', hidden)

            app._name_filter = re.compile(r'_Z3foov')
            app._sync_filter_expansion()
            self.assertIn('_Z3foov', _shown(app))

    def test_object_path_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp))
            app._name_filter = re.compile(r'libfoo\.a\(foo\.c\.obj\)')
            app._sync_filter_expansion()
            names = _shown(app)
            self.assertIn('.text.foo', names)
            self.assertNotIn('foo', names)
            self.assertNotIn('.data', names)

    def test_hidden_debug_section_stays_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp))
            app._name_filter = re.compile('debug')
            app._sync_filter_expansion()
            self.assertNotIn('.debug_info', _shown(app))

            app.show_debug = True
            app.hide_show_debug_sections()
            app._sync_filter_expansion()
            self.assertIn('.debug_info', _shown(app))

    def test_hide_reduced_wins_over_the_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            # .text shrank, .data grew. The pattern matches both; hide-reduced drops .text.
            old = _write_sized(tmp, 'old.map', '0x20', '0x08')
            new = _write_sized(tmp, 'new.map', '0x08', '0x20')
            app = TableApp(new, old)
            app.hide_reduced = True
            app._name_filter = re.compile(r'\.')
            app._sync_filter_expansion()
            names = _shown(app)
            self.assertNotIn('.text', names)
            self.assertIn('.data', names)


class RegexFilterUiTest(unittest.IsolatedAsyncioTestCase):
    async def test_slash_filters_and_escape_returns_to_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = TableApp(_write_map(tmp))
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                self.assertIsInstance(app.focused, DataTable)
                header = app.query_one('#header-bar')
                box = app.query_one('#name-filter', Input)
                icon = app.query_one('#filter-icon', Label)
                boxes = list(app.query(Checkbox))
                self.assertEqual(header.parent.size.height, 2)
                self.assertEqual(box.size.height, 1)
                self.assertEqual(box.size.width, 32)
                self.assertEqual(box.max_length, 32)
                self.assertGreaterEqual(box.region.y, boxes[0].region.bottom)
                self.assertEqual(icon.region.y, box.region.y)
                self.assertLess(icon.region.x, box.region.x)
                descriptions = [item.binding.description for item in app.screen.active_bindings.values()]
                self.assertIn('filter', descriptions)

                await pilot.press('slash')
                await pilot.pause()
                self.assertIs(app.focused, box)
                await pilot.press('b', 'a', 'r')
                await pilot.pause()
                table = app.query_one(DataTable)
                names = [_plain(table.get_row(key)[0]) for key in table.rows]
                self.assertTrue(any('bar' in name for name in names))
                self.assertFalse(any(name == '.text' or name.endswith(' .text') for name in names))
                self.assertNotIn('.text', names)

                await pilot.press('escape')
                await pilot.pause()
                self.assertIsInstance(app.focused, DataTable)
                self.assertEqual(box.value, 'bar')

                box.value = '^foo$('
                await pilot.pause()
                self.assertTrue(box.has_class('-invalid'))
                self.assertEqual(box.size.height, 1)
                stale = [_plain(table.get_row(key)[0]) for key in table.rows]
                self.assertTrue(any('bar' in name for name in stale))

                box.value = ''
                await pilot.pause()
                self.assertFalse(box.has_class('-invalid'))
                restored = [_plain(table.get_row(key)[0]) for key in table.rows]
                self.assertIn('.text', restored)
                self.assertIn('.data', restored)

                box.focus()
                await pilot.press('enter')
                await pilot.pause()
                self.assertIsInstance(app.focused, DataTable)

                box.focus()
                await pilot.press(*('y' * 40))
                await pilot.pause()
                self.assertEqual(box.value, 'y' * 32)


if __name__ == '__main__':
    unittest.main()
