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

def get_stylized_table_row(entry):
    row = entry.value.get_tuple()
    row = (f'{get_indent(entry)}{row[0]}', Text(f"{row[1]:#010x}") , Align.right(Text(str(row[2]))), *row[3:])
    if len(row) == 5:
        row = (*row[0:3], Align.right(Text(str(row[3]))), Text(f"{row[4]: >7.2f}"))
    return row

def get_stylized_table_header(header):
    header = (*header[0:2], Align.right(Text(header[2])), *header[3:])
    if len(header) == 5:
        header = (*header[0:3], Align.right(Text(str(header[3]))), Align.right(Text(str(header[4]))))
    return header

def get_stylized_row_label(node):
    if len(node.children) == 0 or node.is_root():
        return '▒'
    if node.expand:
        return '-'
    return '+'
