from rich.align import Align
from rich.style import Style
from rich.text import Text
from rich.color import Color

def get_indent(entry):
    indent = ''
    p = entry.parent
    if p == None:
        return ''
    while p.level > 0:
        if p.is_last_child():
            indent = f'    {indent}'
        else:
            indent = f'│   {indent}'
        p = p.parent
    if entry.is_last_child():
        indent += '└── '
    elif entry.level > 0:
        indent += '├── '
    else:
        indent += ''
    return indent

# Same washes as the assembler diff: green when the section shrank, red when it grew.
_REDUCED_TEXT = Style(color='green')
_INCREASED_TEXT = Style(color='red')
_REDUCED_ROW = Style(color='green', bgcolor='#1c3326')
_INCREASED_ROW = Style(color='red', bgcolor='#3a2428')

def _diff_kind(node):
    diff = node.value.diff
    if diff < 0:
        return 'reduced'
    if diff > 0:
        return 'increased'
    return None

def text_style(node):
    kind = _diff_kind(node)
    if kind == 'reduced':
        return _REDUCED_TEXT
    if kind == 'increased':
        return _INCREASED_TEXT
    return None

def row_style(node):
    kind = _diff_kind(node)
    if kind == 'reduced':
        return _REDUCED_ROW
    if kind == 'increased':
        return _INCREASED_ROW
    return None

def _text(value, style):
    if style is None:
        return Text(str(value))
    return Text(str(value), style=style)

def _right(value, style):
    return Align.right(_text(value, style))

def get_stylized_table_row(entry, name=None):
    values = entry.value.get_tuple()
    if name is None:
        name = values[0]
    style = text_style(entry)
    name_cell = f'{get_indent(entry)}{name}'
    if style is not None:
        name_cell = Text(name_cell, style=style)
    address = f'{values[1]:#010x}' if values[1] != 0 else ''
    row = (name_cell, _text(address, style), _right(values[2], style), *values[3:])
    if len(row) == 5:
        row = (*row[0:3], _right(values[3], style), _text(f'{values[4]: >7.2f}', style))
    return row

def get_stylized_table_header(header):
    header = (*header[0:2], Align.right(Text(header[2])), *header[3:])
    if len(header) == 5:
        header = (*header[0:3], Align.right(Text(str(header[3]))), Align.right(Text(str(header[4]))))
    return header

def get_stylized_row_label(node):
    if len(node.children) == 0 or node.is_root():
        label = '▒'
    elif node.expand:
        label = '-'
    else:
        label = '+'
    style = text_style(node)
    if style is None:
        return label
    return Text(label, style=style)
