import time
import unittest
from pathlib import Path
from unittest.mock import patch

from textual import work
from textual.app import App
from textual.widgets import Checkbox
from textual.widgets._toast import Toast

from mapuche.asm import AsmSpan, format_asm_view, parse_objdump, view_from_records
from mapuche.mapuche import AsmScreen, DiffDocument, TableApp


def _view(show_addresses, show_source):
    old = '1000 <foo>:\n1000:\tli\ta0,100\n1004:\tret\n'
    new = '2000 <foo>:\n2000:\tli\ta0,120\n2004:\tret\n'
    if show_source:
        old = '1000 <foo>:\nvoid foo(void)\n{\n' + old.split('\n', 1)[1]
        new = '2000 <foo>:\nvoid foo(int n)\n{\n' + new.split('\n', 1)[1]
    span = AsmSpan(0x2000, 8, 0x1000, 8)
    records = [parse_objdump(new), parse_objdump(old)]
    return view_from_records(records, [span], 'build/now.map', 'build_old/then.map', True, show_addresses, show_source)


class Host(App):
    def __init__(self):
        super().__init__()
        self.calls = []

    @work(thread=True, exclusive=True, group='asm-rebuild', exit_on_error=False)
    def rebuild_asm_view(self, _targets, show_addresses, show_source):
        self.calls.append((show_addresses, show_source))
        return _view(show_addresses, show_source)


class AsmScreenTest(unittest.IsolatedAsyncioTestCase):
    async def test_checkboxes_reload_the_diff(self):
        app = Host()
        async with app.run_test(size=(120, 24)) as pilot:
            await app.push_screen(AsmScreen('foo', _view(False, False), [], size_diff=12))
            await pilot.pause()
            screen = app.screen
            self.assertIsInstance(screen, AsmScreen)
            headers = [str(widget.content) for widget in screen.query('.diff-header')]
            self.assertEqual(headers, ['ORIGINAL', 'CHANGED  +12'])
            labels = [str(box.label) for box in screen.query(Checkbox)]
            self.assertEqual(labels, ['show addresses', 'show source code'])
            self.assertEqual(screen.query_one('#asm-frame').border_title, 'DIFF VIEWER')

            left = screen.query_one('#original-doc', DiffDocument)
            right = screen.query_one('#changed-doc', DiffDocument)
            self.assertIs(left.peer, right)
            self.assertNotIn('1000', left.lines[-1].plain)

            screen.query_one('#asm-addresses', Checkbox).value = True
            await self._wait(pilot, lambda: any('1000' in line.plain for line in left.lines))
            self.assertTrue(any('ret' in line.plain and '1004' in line.plain for line in left.lines))
            self.assertEqual(app.calls[-1], (True, False))

            before = len(left.lines)
            screen.query_one('#asm-source', Checkbox).value = True
            await self._wait(pilot, lambda: any('italic' in str(span.style) for line in left.lines for span in line.spans))
            self.assertGreater(len(left.lines), before)
            self.assertEqual(app.calls[-1], (True, True))
            self.assertTrue(screen.query_one('#asm-addresses', Checkbox).value)

            left.scroll_to(y=1, animate=False, immediate=True)
            await pilot.pause()
            self.assertEqual(round(left.scroll_y), round(right.scroll_y))

    async def test_single_map_uses_one_pane(self):
        app = Host()
        view = format_asm_view('<foo>:\nret\n', '', 'only.map', '', False)
        async with app.run_test(size=(80, 20)) as pilot:
            await app.push_screen(AsmScreen('app_main', view, []))
            await pilot.pause()
            screen = app.screen
            self.assertEqual(screen.query_one('#asm-frame').border_title, 'app_main')
            doc = screen.query_one('#single-doc', DiffDocument)
            self.assertIn('ret', doc.lines[-1].plain)
            self.assertEqual(len(list(screen.query('#original-doc'))), 0)

    async def _wait(self, pilot, ready):
        for _ in range(40):
            if ready():
                return
            await pilot.pause(0.05)
        self.fail('diff view did not update')


class CancelledAsmOpenTest(unittest.IsolatedAsyncioTestCase):
    async def test_second_request_does_not_crash(self):
        new = 'test/build_new/test_cxx_exception.map'
        old = 'test/build_old/test_cxx_exception.map'
        app = TableApp(new, old)
        app.objdump_path = Path('/bin/true')
        app._objdump_probed = True

        def slow_view(*_args, **_kwargs):
            time.sleep(0.4)
            return format_asm_view('ret\n', 'nop\n', 'build/a.map', 'build_old/b.map', True)

        with patch('mapuche.mapuche.load_disassembly', return_value=[]), patch('mapuche.mapuche.view_from_records', slow_view):
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                await pilot.press('a')
                await pilot.pause(0.05)
                await pilot.press('a')
                for _ in range(40):
                    if isinstance(app.screen, AsmScreen):
                        break
                    await pilot.pause(0.05)
                self.assertIsInstance(app.screen, AsmScreen)
                self.assertEqual(app.objdump_path, Path('/bin/true'))
                await pilot.pause()
                notices = [toast.render().plain for toast in app.screen.query(Toast)]
                self.assertFalse(any('disassembling' in text for text in notices))


if __name__ == '__main__':
    unittest.main()
