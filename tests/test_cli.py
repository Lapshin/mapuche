import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from mapuche.mapuche import package_version, parse_args


class CliTest(unittest.TestCase):
    def test_version(self):
        stdout = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(stdout):
                parse_args(['--version'])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(stdout.getvalue(), f'mapuche {package_version()}\n')

    def test_help(self):
        stdout = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(stdout):
                parse_args(['--help'])
        self.assertEqual(ctx.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn('usage: mapuche', text)
        self.assertIn('--version', text)
        self.assertIn('elf.map', text)
        self.assertIn('elf_for_diff.map', text)

    def test_parse_map_files(self):
        one = parse_args(['app.map'])
        self.assertEqual(one.map_file, 'app.map')
        self.assertIsNone(one.diff_map_file)

        two = parse_args(['app.map', 'old.map'])
        self.assertEqual(two.map_file, 'app.map')
        self.assertEqual(two.diff_map_file, 'old.map')

    def test_missing_map_file(self):
        stderr = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stderr(stderr):
                parse_args([])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn('elf.map', stderr.getvalue())
