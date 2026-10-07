import unittest

from mapuche.asm import AsmSpan, format_asm_view, parse_objdump, view_from_records

_DELETE = '7a3038'
_INSERT = '1f6b3a'


def _hits(text, needle):
    return [(span.start, text.plain[span.start:span.end]) for span in text.spans if needle in str(span.style)]


def _hit_text(text, needle):
    return [piece for _start, piece in _hits(text, needle)]


def _row(view, contains):
    for left, right in zip(view.left_lines, view.right_lines):
        if contains in left.plain and contains in right.plain:
            return left, right
    raise AssertionError(f'no row containing {contains!r}')


class ParseObjdumpTest(unittest.TestCase):
    def test_source_sticks_to_the_next_instruction(self):
        text = """
foo.elf:     file format elf32-littleriscv

Disassembly of section .text:

1000 <foo>:
}

void foo(void)
{
1000:\tli\ta0,100
    return n;
1004:\tret

Disassembly of section .flash.text:
"""
        kinds = [(kind, rest) for _addr, _seq, kind, rest in parse_objdump(text)]
        self.assertEqual(kinds, [
            ('h', 'foo'),
            ('s', '}'),
            ('s', ''),
            ('s', 'void foo(void)'),
            ('s', '{'),
            ('i', 'li\ta0,100'),
            ('s', '    return n;'),
            ('i', 'ret'),
        ])

    def test_header_stays_before_source_at_the_same_address(self):
        text = "1000 <foo>:\nvoid foo(void)\n1000:\tnop\n"
        records = parse_objdump(text)
        self.assertEqual([record[2] for record in records], ['h', 's', 'i'])
        self.assertTrue(all(record[0] == 0x1000 for record in records))


class AsmDiffViewTest(unittest.TestCase):
    def test_token_change_and_inserted_line_stay_aligned(self):
        old = "<foo>:\nli a0, 100\njal ra, <puts>\nret\n"
        new = "<foo>:\nli a0, 120\naddi a0, a0, 1\njal ra, <printf>\nret\n"
        view = format_asm_view(new, old, 'now.map', 'then.map', True)
        self.assertTrue(view.side_by_side)
        self.assertEqual(len(view.left_lines), len(view.right_lines))
        self.assertEqual(view.left_file, 'then.map')
        self.assertEqual(view.right_file, 'now.map')

        left, right = _row(view, 'li')
        self.assertEqual(_hit_text(left, _DELETE), ['100'])
        self.assertEqual(_hit_text(right, _INSERT), ['120'])

        left, right = _row(view, 'jal')
        self.assertEqual(_hit_text(left, _DELETE), ['puts'])
        self.assertEqual(_hit_text(right, _INSERT), ['printf'])
        self.assertIn('  3 ', left.plain)
        self.assertIn('  4 ', right.plain)

        added = [
            (left, right)
            for left, right in zip(view.left_lines, view.right_lines)
            if 'addi' in right.plain
        ]
        self.assertEqual(len(added), 1)
        left, right = added[0]
        self.assertEqual(left.plain.strip(), '')
        self.assertEqual(view.right_styles[view.right_lines.index(right)].bgcolor.name, '#1c3326')
        self.assertFalse(view.left_styles[view.left_lines.index(left)].bgcolor)

        left, right = _row(view, 'ret')
        self.assertEqual(_hit_text(left, _DELETE), [])
        self.assertEqual(_hit_text(right, _INSERT), [])

    def test_hex_offset_is_one_token(self):
        old = "bltu a0, s0, <foo+0x2c>\n"
        new = "bltu a0, s0, <foo+0x2e>\n"
        view = format_asm_view(new, old, 'n', 'o', True)
        left, right = view.left_lines[0], view.right_lines[0]
        self.assertEqual(_hit_text(left, _DELETE), ['0x2c'])
        self.assertEqual(_hit_text(right, _INSERT), ['0x2e'])

    def test_only_the_changed_number_is_marked(self):
        view = format_asm_view('The price is $120.\n', 'The price is $100.\n', 'n', 'o', True)
        left, right = view.left_lines[0], view.right_lines[0]
        self.assertEqual(_hit_text(left, _DELETE), ['100'])
        self.assertEqual(_hit_text(right, _INSERT), ['120'])
        self.assertNotIn('$', _hit_text(left, _DELETE))

    def test_single_map_is_one_pane(self):
        view = format_asm_view('<foo>:\nret\n', '', 'only.map', '', False)
        self.assertFalse(view.side_by_side)
        self.assertEqual(view.right_lines, [])
        self.assertIn('<foo>:', view.left_lines[0].plain)

    def test_coded_instruction_is_shown_beside_the_mnemonic(self):
        old = '1000 <foo>:\n1000:\t1141                \taddi\tsp,sp,-16\n1004:\t8082                \tret\n'
        new = '1000 <foo>:\n1000:\t0141                \taddi\tsp,sp,-16\n1004:\t8082                \tret\n'
        span = AsmSpan(0x1000, 8, 0x1000, 8)
        view = view_from_records([parse_objdump(new), parse_objdump(old)], [span], 'n', 'o', True, False, False)
        left, right = _row(view, 'addi')
        self.assertIn('1141', left.plain)
        self.assertIn('0141', right.plain)
        self.assertEqual(_hit_text(left, _DELETE), ['1141'])
        self.assertEqual(_hit_text(right, _INSERT), ['0141'])
        self.assertNotIn('addi', _hit_text(left, _DELETE))
        ret_left, ret_right = _row(view, 'ret')
        self.assertIn('8082', ret_left.plain)
        self.assertEqual(_hit_text(ret_left, _DELETE), [])
        self.assertEqual(_hit_text(ret_right, _INSERT), [])

    def test_xtensa_narrow_and_wide_encodings_share_a_column(self):
        text = (
            '40000000 <ipc_task>:\n'
            '40000000:\t004136              \tentry\ta1, 32\n'
            '40000003:\t8b3c                \tmovi.n\ta11, 56\n'
        )
        span = AsmSpan(0x40000000, 5, 0, 0)
        view = view_from_records([parse_objdump(text)], [span], 'n', '', False, False, False)
        entry = next(line.plain for line in view.left_lines if 'entry' in line.plain)
        movi = next(line.plain for line in view.left_lines if 'movi.n' in line.plain)
        self.assertEqual(entry.index('004136'), movi.index('8b3c'))
        self.assertEqual(entry.index('entry'), movi.index('movi.n'))
        self.assertIn('a1, 32', entry)
        self.assertIn('a11, 56', movi)

    def test_addresses_color_only_the_address_column(self):
        old = "1000 <foo>:\n1000:\tret\n"
        new = "2000 <foo>:\n2000:\tret\n"
        span = AsmSpan(0x2000, 4, 0x1000, 4)
        records = [parse_objdump(new), parse_objdump(old)]
        hidden = view_from_records(records, [span], 'n', 'o', True, False, False)
        shown = view_from_records(records, [span], 'n', 'o', True, True, False)
        self.assertNotIn('1000', hidden.left_lines[-1].plain)
        left, right = shown.left_lines[-1], shown.right_lines[-1]
        self.assertIn('ret', left.plain)
        self.assertEqual(_hits(left, _DELETE), [(5, '1000')])
        self.assertEqual(_hits(right, _INSERT), [(5, '2000')])
        self.assertTrue(shown.match)

    def test_source_is_optional_and_diffed_by_word(self):
        old = "1000 <foo>:\nvoid foo(void)\n{\n1000:\tli\ta0,100\n"
        new = "1000 <foo>:\nvoid foo(int n)\n{\n1000:\tli\ta0,100\n"
        span = AsmSpan(0x1000, 4, 0x1000, 4)
        records = [parse_objdump(new), parse_objdump(old)]
        hidden = view_from_records(records, [span], 'n', 'o', True, False, False)
        shown = view_from_records(records, [span], 'n', 'o', True, False, True)
        self.assertTrue(all('void' not in line.plain for line in hidden.left_lines))
        left, right = _row(shown, 'void foo')
        self.assertTrue(any('italic' in str(span.style) for span in left.spans))
        self.assertEqual(_hit_text(left, _DELETE), ['void'])
        self.assertEqual(_hit_text(right, _INSERT), ['int', 'n'])
        self.assertNotIn('foo', _hit_text(left, _DELETE))
        brace = next(line for line in shown.left_lines if line.plain.rstrip().endswith('{'))
        self.assertEqual(_hit_text(brace, _DELETE), [])


if __name__ == '__main__':
    unittest.main()
