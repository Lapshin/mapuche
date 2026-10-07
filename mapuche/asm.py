import difflib
import os
import re
import struct
import subprocess
from pathlib import Path

from rich.style import Style
from rich.text import Text

_OUTPUT = re.compile(r'^OUTPUT\((\S+)')
# Archive member must be exactly libc.a. libesp_libc.a also ends in "libc.a".
_LIBC = re.compile(r'((?:/|[A-Za-z]:/)[^\s()]*/libc\.a)')
_HEADER = re.compile(r'^([0-9a-fA-F]+)\s+<(.*)>:\s*$')
_INSN = re.compile(r'^([0-9a-fA-F]+):\s*(.*)$')
_ADDR_COMMENT = re.compile(r'(?:0x)?[0-9a-fA-F]{4,}\s+(<.*>)')
_SKIP_SECTION = ('rodata', 'literal', '.data', 'bss', '.str', 'eh_frame', 'comment', 'debug')


class AsmSpan:
    def __init__(self, address, size, peer_address, peer_size):
        self.address = address or 0
        self.size = size or 0
        self.peer_address = peer_address or 0
        self.peer_size = peer_size or 0


def scan_map_file(map_file):
    """Return (elf Path or None, libc.a path or None) from a linker map."""
    elf_name = None
    libc = None
    with open(map_file, 'r', errors='replace') as f:
        for line in f:
            stripped = line.lstrip()
            if elf_name is None and stripped.startswith('OUTPUT('):
                match = _OUTPUT.match(stripped)
                if match:
                    elf_name = match.group(1)
            if libc is None and 'libc.a' in line:
                match = _LIBC.search(line.replace('\\', '/'))
                if match:
                    libc = match.group(1)
            if elf_name and libc:
                break
    elf = None
    if elf_name:
        path = Path(elf_name)
        if not path.is_absolute():
            path = Path(map_file).resolve().parent / path
        if path.is_file():
            elf = path
    return elf, libc


def toolchain_bin_dir(libc_path):
    """Toolchain bin directory recorded in a libc.a path, if that directory exists."""
    if not libc_path:
        return None
    parts = libc_path.replace('\\', '/').split('/')
    if 'bin' not in parts:
        return None
    bin_dir = Path('/'.join(parts[:parts.index('bin') + 1]))
    if bin_dir.is_dir():
        return bin_dir
    return None


def find_objdump_in(bin_dir):
    if bin_dir is None or not Path(bin_dir).is_dir():
        return None
    files = [path for path in Path(bin_dir).glob('*objdump') if path.is_file()]
    if not files:
        return None
    prefixed = [path for path in files if path.name.endswith('-objdump')]
    chosen = sorted(prefixed or files)
    return chosen[0]


def detect_objdump(libc_paths):
    for libc in libc_paths:
        found = find_objdump_in(toolchain_bin_dir(libc))
        if found is not None:
            return found
    return None


def resolve_user_objdump(text):
    """Resolve a user-supplied objdump binary or a directory that contains one."""
    raw = (text or '').strip().strip('"').strip("'")
    if not raw:
        return None
    path = Path(os.path.expanduser(raw))
    if path.is_dir():
        return find_objdump_in(path)
    if path.is_file():
        return path
    return None


def _output_section(node):
    current = node
    while current.parent is not None and not current.parent.is_root():
        current = current.parent
    return current


def _in_code_section(node):
    name = _output_section(node).value.name.lower()
    if any(part in name for part in ('rodata', '.data', 'bss', 'debug', 'comment', 'eh_frame', 'appdesc', 'heap')):
        return False
    return 'text' in name or 'vector' in name


def _is_symbol(node):
    # Linker symbols are leaves under an input section. Libraries and object
    # files also lack a leading dot, but they are containers.
    name = node.value.name
    parent = node.parent
    if not name or node.children or name.startswith('.') or name.startswith('*'):
        return False
    return parent is not None and parent.value.name.startswith('.')


def _is_function_section(node):
    name = node.value.name
    if not name.startswith('.') or node.children:
        return False
    if any(part in name for part in _SKIP_SECTION):
        return False
    return True


def _span_for(node, diff):
    if diff:
        return AsmSpan(
            node.value.address_a,
            node.value.size_a,
            node.value.address_b,
            node.value.size_b,
        )
    return AsmSpan(node.value.address, node.value.size, 0, 0)


def collect_asm_targets(node, diff):
    targets = []
    _collect(node, diff, targets)
    return _unique_spans(targets)


class HexSpan:
    def __init__(self, name, section, address, size, peer_address, peer_size):
        self.name = name or ''
        self.section = section or ''
        self.address = address or 0
        self.size = size or 0
        self.peer_address = peer_address or 0
        self.peer_size = peer_size or 0


def _unique_spans(targets):
    unique = []
    seen = set()
    for span in targets:
        key = (span.address, span.size, span.peer_address, span.peer_size)
        if key in seen:
            continue
        if span.size <= 0 and span.peer_size <= 0:
            continue
        seen.add(key)
        unique.append(span)
    return unique


def _located_span(node, diff):
    if diff:
        address, size = node.value.address_a, node.value.size_a
        peer_address, peer_size = node.value.address_b, node.value.size_b
    else:
        address, size = node.value.address, node.value.size
        peer_address, peer_size = 0, 0
    name = node.value.name or ''
    # Address 0 still names a real section (.comment, .xtensa.info). Containers
    # such as libraries keep address 0 and must be walked instead.
    if not (size or peer_size):
        return None
    if not (address or peer_address or name.startswith('.')):
        return None
    if not (name.startswith('.') or _is_symbol(node)):
        return None
    section = _output_section(node).value.name or name
    return HexSpan(name, section, address, size, peer_address, peer_size)


def collect_hex_targets(node, diff):
    """Byte ranges for a data row. Code sections stay on the assembler path."""
    targets = []
    _collect_hex(node, diff, targets)
    return _unique_spans(targets)


def _collect_hex(node, diff, out):
    if node.is_root():
        for child in node.children:
            _collect_hex(child, diff, out)
        return
    if _in_code_section(node):
        return
    span = _located_span(node, diff)
    if span is not None:
        out.append(span)
        return
    for child in node.children:
        _collect_hex(child, diff, out)


class _ElfSection:
    def __init__(self, name, kind, addr, offset, size):
        self.name = name
        self.kind = kind
        self.addr = addr
        self.offset = offset
        self.size = size


class ElfImage:
    def __init__(self, path):
        self.blob = Path(path).read_bytes()
        self.sections = _elf_sections(self.blob)

    def read(self, address, size, section_name=''):
        if size <= 0:
            return b''
        section = _elf_section_for(self.sections, address, section_name)
        if section is None:
            return b''
        start = address - section.addr if address and section.addr else 0
        if start < 0 or start >= section.size:
            return b''
        take = min(size, section.size - start)
        if section.kind == 8:
            return b'\x00' * take
        file_at = section.offset + start
        return self.blob[file_at:file_at + take]


def _elf_sections(blob):
    if len(blob) < 52 or blob[:4] != b'\x7fELF':
        return []
    endian = '<' if blob[5] == 1 else '>'
    kind = blob[4]
    if kind == 1:
        shoff = struct.unpack_from(endian + 'I', blob, 32)[0]
        shentsize, shnum, shstrndx = struct.unpack_from(endian + 'HHH', blob, 46)
        layout = (12, 16, 20, 'I')
    elif kind == 2:
        if len(blob) < 64:
            return []
        shoff = struct.unpack_from(endian + 'Q', blob, 40)[0]
        shentsize, shnum, shstrndx = struct.unpack_from(endian + 'HHH', blob, 58)
        layout = (16, 24, 32, 'Q')
    else:
        return []
    if not shoff or not shnum or shstrndx >= shnum:
        return []
    addr_at, off_at, size_at, word = layout

    def words(index):
        base = shoff + index * shentsize
        if base + shentsize > len(blob):
            return None
        name, typ = struct.unpack_from(endian + 'II', blob, base)
        addr = struct.unpack_from(endian + word, blob, base + addr_at)[0]
        offset = struct.unpack_from(endian + word, blob, base + off_at)[0]
        size = struct.unpack_from(endian + word, blob, base + size_at)[0]
        return name, typ, addr, offset, size

    string_header = words(shstrndx)
    if string_header is None:
        return []
    strings = blob[string_header[3]:string_header[3] + string_header[4]]
    sections = []
    for index in range(shnum):
        header = words(index)
        if header is None or header[1] == 0:
            continue
        name_at, typ, addr, offset, size = header
        name = strings[name_at:].split(b'\x00', 1)[0].decode('ascii', 'replace') if name_at < len(strings) else ''
        sections.append(_ElfSection(name, typ, addr, offset, size))
    return sections


def _elf_section_for(sections, address, section_name):
    if address:
        hits = [section for section in sections if section.size and section.addr <= address < section.addr + section.size]
        if hits:
            hits.sort(key=lambda section: (section.size, section.name != section_name))
            return hits[0]
    for section in sections:
        if section_name and section.name == section_name and section.size:
            return section
    return None


def _collect(node, diff, out):
    if node.is_root():
        for child in node.children:
            _collect(child, diff, out)
        return
    if not _in_code_section(node):
        return
    symbols = [child for child in node.children if _is_symbol(child)]
    if symbols:
        for child in symbols:
            _collect(child, diff, out)
        for child in node.children:
            if child not in symbols:
                _collect(child, diff, out)
        return
    if _is_symbol(node) or _is_function_section(node):
        out.append(_span_for(node, diff))
        return
    for child in node.children:
        _collect(child, diff, out)


def run_objdump(objdump, elf, demangle, source=False):
    cmd = [str(objdump), '-d', '-w']
    if source:
        cmd.append('-S')
    if demangle:
        cmd.append('-C')
    cmd.append(str(elf))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=120)
    except OSError as exc:
        raise RuntimeError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('objdump timed out') from exc
    if proc.returncode != 0 and not _INSN.search(proc.stdout):
        message = proc.stderr.strip() or proc.stdout.strip() or f'objdump failed ({proc.returncode})'
        raise RuntimeError(message)
    return proc.stdout


def _is_banner(line):
    return 'file format ' in line or line.startswith('Disassembly of section ')


def parse_objdump(text):
    """Return (address, sequence, kind, rest) rows.

    kind is ``h`` (symbol header), ``s`` (source line from ``-S``), or ``i`` (instruction).
    Source lines take the address of the following instruction and keep file order.
    """
    records = []
    pending = []
    sequence = 0

    def add(addr, kind, rest):
        nonlocal sequence
        records.append((addr, sequence, kind, rest))
        sequence += 1

    def take_source(addr):
        while pending and not pending[0].strip():
            pending.pop(0)
        while pending and not pending[-1].strip():
            pending.pop()
        for line in pending:
            add(addr, 's', line)
        pending.clear()

    for line in text.splitlines():
        if _is_banner(line):
            pending.clear()
            continue
        header = _HEADER.match(line)
        if header:
            add(int(header.group(1), 16), 'h', header.group(2))
            continue
        insn = _INSN.match(line)
        if insn:
            addr = int(insn.group(1), 16)
            take_source(addr)
            add(addr, 'i', insn.group(2).rstrip())
            continue
        pending.append(line)
    records.sort(key=lambda record: (record[0], record[1]))
    return records


def load_disassembly(objdump, elf, demangle, source, cache):
    key = (str(objdump), str(elf), bool(demangle), bool(source))
    cached = cache.get(key)
    if cached is not None:
        return cached
    records = parse_objdump(run_objdump(objdump, elf, demangle, source))
    cache[key] = records
    return records


def _normalize_insn(text):
    return _ADDR_COMMENT.sub(r'\1', text).rstrip()


# objdump pads the encoding with spaces, then a tab, then the mnemonic.
# RISC-V is 4 or 8 hex digits. Xtensa 24-bit instructions are 6.
# `1141                \taddi\tsp,sp,-16`
# `004136              \tentry\ta1, 32`
_CODED = re.compile(r'^((?:[0-9a-fA-F]{2}){2,4})[ ]+\t?(.*)$')


def _peel_coded(text):
    """Split an objdump instruction tail into (encoding or None, mnemonic text)."""
    match = _CODED.match(text)
    if not match:
        return None, text
    rest = match.group(2).lstrip()
    if not rest or not (rest[0].isalpha() or rest[0] == '.'):
        return None, text
    return match.group(1).lower(), rest


def _split_insn(text):
    code, sep, comment = text.partition(' # ')
    code = code.strip()
    comment = comment.strip() if sep else ''
    pieces = code.split(None, 1)
    if not pieces:
        return None
    operands = _space_commas(pieces[1]) if len(pieces) > 1 else ''
    return pieces[0], operands, comment


def _items_in_range(records, start, size, show_source):
    if size <= 0 or not records:
        return []
    end = start + size
    items = []
    for addr, _sequence, kind, rest in records:
        if addr < start:
            continue
        if addr >= end:
            break
        if kind == 'h':
            items.append(('label', f'<{rest}>:', addr))
        elif kind == 's':
            if show_source:
                items.append(('source', rest))
        else:
            coded, insn_text = _peel_coded(rest)
            parsed = _split_insn(_normalize_insn(insn_text))
            if parsed is None:
                continue
            mnemonic, operands, comment = parsed
            items.append(('insn', mnemonic, operands, comment, addr, coded))
    return items


def render_items(records, spans, peer, show_source):
    if not records:
        return []
    items = []
    for span in spans:
        start = span.peer_address if peer else span.address
        size = span.peer_size if peer else span.size
        chunk = _items_in_range(records, start, size, show_source)
        if not chunk:
            continue
        if items:
            items.append(('blank',))
        items.extend(chunk)
    return items


_LABEL = re.compile(r'^<.+>:$')
_OPERAND = re.compile(
    r'<[^>]*>|0x[0-9a-fA-F]+|-?\d+|'
    r'\b(?:x(?:[12]?\d|3[01])|zero|ra|sp|gp|tp|fp|t[0-6]|s(?:1[01]|[0-9])|a[0-7]|'
    r'ft(?:1[01]|[0-9])|fs(?:1[01]|[0-9])|fa[0-7]|f(?:[0-9]|[12]\d|3[01]))\b|'
    r'.'
)
_REG = re.compile(
    r'x(?:[12]?\d|3[01])|zero|ra|sp|gp|tp|fp|t[0-6]|s(?:1[01]|[0-9])|a[0-7]|'
    r'ft(?:1[01]|[0-9])|fs(?:1[01]|[0-9])|fa[0-7]|f(?:[0-9]|[12]\d|3[01])'
)
_NUM = re.compile(r'0x[0-9a-fA-F]+|-?\d+')
_LINE_DELETE = 'on #3a2428'
_LINE_INSERT = 'on #1c3326'
_LINE_MODIFY = 'on #2a261c'
_INLINE_DELETE = 'on #7a3038'
_INLINE_INSERT = 'on #1f6b3a'
_EXT_DELETE = Style(bgcolor='#3a2428')
_EXT_INSERT = Style(bgcolor='#1c3326')
_EXT_MODIFY = Style(bgcolor='#2a261c')
_EXT_NONE = Style()


def _space_commas(operands):
    parts = []
    buf = []
    depth = 0
    for char in operands:
        if char == '<':
            depth += 1
        elif char == '>':
            depth = max(0, depth - 1)
        if char == ',' and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
            continue
        buf.append(char)
    parts.append(''.join(buf).strip())
    return ', '.join(part for part in parts if part != '')


def _program(text):
    items = []
    for line in text.splitlines():
        if not line.strip():
            items.append(('blank',))
            continue
        if _LABEL.match(line):
            items.append(('label', line))
            continue
        parsed = _split_insn(line)
        if parsed is None:
            items.append(('blank',))
            continue
        mnemonic, operands, comment = parsed
        items.append(('insn', mnemonic, operands, comment, None, None))
    return items


def _metrics(items):
    width = 8
    for item in items:
        if item[0] == 'insn':
            width = max(width, len(item[1]))
    width = min(width, 16)
    comment_at = 0
    for item in items:
        if item[0] == 'insn' and item[3]:
            comment_at = max(comment_at, 2 + width + len(item[2]) + 2)
    if comment_at:
        comment_at = min(comment_at, 56)
    return width, comment_at


def _item_addr(item):
    kind = item[0]
    if kind == 'insn' and len(item) > 4:
        return item[4]
    if kind == 'label' and len(item) > 2:
        return item[2]
    return None


def _item_coded(item):
    if item[0] == 'insn' and len(item) > 5:
        return item[5]
    return None


def _render_item(item, width, comment_at):
    text = Text(no_wrap=True)
    kind = item[0]
    if kind == 'blank':
        return text
    if kind == 'label':
        text.append(item[1], style='bold bright_magenta')
        return text
    if kind == 'source':
        text.append(item[1], style='italic')
        return text
    mnemonic, operands, comment = item[1], item[2], item[3]
    text.append('  ')
    text.append(f'{mnemonic:<{width}}' if operands or comment else mnemonic, style='bold cyan')
    _append_operands(text, operands)
    if comment:
        pad = max(2, comment_at - len(text.plain)) if comment_at else 2
        text.append(' ' * pad)
        _append_comment(text, comment)
    return text


class AsmView:
    def __init__(self, side_by_side, left_lines, left_styles, right_lines, right_styles, left_file, right_file, match):
        self.side_by_side = side_by_side
        self.left_lines = left_lines
        self.left_styles = left_styles
        self.right_lines = right_lines
        self.right_styles = right_styles
        self.left_file = left_file
        self.right_file = right_file
        self.match = match


def _compose_line(number, content, num_w, addr, addr_w, coded, coded_w):
    text = Text(no_wrap=True)
    shown = '' if number is None else str(number)
    text.append(f'{shown:>{num_w}}  ', style='dim')
    if addr_w:
        cell = ' ' * addr_w if addr is None else f'{addr:0{addr_w}x}'
        text.append(cell, style='dim')
        text.append('  ')
    if coded_w:
        cell = ' ' * coded_w if not coded else f'{coded:<{coded_w}}'
        text.append(cell, style='#8b93a7')
        text.append('  ')
    if content is not None:
        text.append_text(content)
    return text


def _addr_width(addrs):
    width = 0
    for addr in addrs:
        if addr is not None:
            width = max(width, len(f'{addr:x}'))
    return width


def _coded_width(coded):
    width = 0
    for value in coded:
        if value:
            width = max(width, len(value))
    return width


def _column_start(num_w, addr_w):
    start = num_w + 2
    if addr_w:
        start += addr_w + 2
    return start


_WORD = re.compile(r'0x[0-9a-fA-F]+|-?\d+|\s+|[A-Za-z_][\w]*(?:\.[\w]+)*|.')


def _token_spans(text, word_re=_WORD):
    return [(match.group(0), match.start(), match.end()) for match in word_re.finditer(text)]


def _inline_ranges(left_plain, right_plain, word_re=_WORD):
    left = _token_spans(left_plain, word_re)
    right = _token_spans(right_plain, word_re)
    left_ranges = []
    right_ranges = []
    matcher = difflib.SequenceMatcher(
        a=[token for token, _start, _end in left],
        b=[token for token, _start, _end in right],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        if tag in ('delete', 'replace'):
            for token, start, end in left[i1:i2]:
                if token.strip():
                    left_ranges.append((start, end))
        if tag in ('insert', 'replace'):
            for token, start, end in right[j1:j2]:
                if token.strip():
                    right_ranges.append((start, end))
    return left_ranges, right_ranges


def _paint_address(left_text, right_text, left_addr, right_addr, num_w, addr_w):
    if not addr_w or left_addr is None or right_addr is None or left_addr == right_addr:
        return
    start = num_w + 2
    end = start + addr_w
    left_text.stylize(_INLINE_DELETE, start, end)
    right_text.stylize(_INLINE_INSERT, start, end)


def _paint_coded(left_text, right_text, left_coded, right_coded, num_w, addr_w, coded_w):
    if not coded_w or not left_coded or not right_coded or left_coded == right_coded:
        return
    start = _column_start(num_w, addr_w)
    end = start + coded_w
    left_text.stylize(_INLINE_DELETE, start, end)
    right_text.stylize(_INLINE_INSERT, start, end)


def _build_panes(rows, num_w, addr_w, coded_w, word_re=_WORD):
    gutter_w = _column_start(num_w, addr_w)
    if coded_w:
        gutter_w += coded_w + 2
    left_lines = []
    left_styles = []
    right_lines = []
    right_styles = []
    for kind, left_no, left, left_addr, left_coded, right_no, right, right_addr, right_coded in rows:
        left_text = _compose_line(left_no, left, num_w, left_addr, addr_w, left_coded, coded_w)
        right_text = _compose_line(right_no, right, num_w, right_addr, addr_w, right_coded, coded_w)
        left_style = _EXT_NONE
        right_style = _EXT_NONE
        if kind == 'delete':
            left_text.stylize(_LINE_DELETE)
            left_style = _EXT_DELETE
        elif kind == 'insert':
            right_text.stylize(_LINE_INSERT)
            right_style = _EXT_INSERT
        elif kind == 'modify':
            left_text.stylize(_LINE_MODIFY)
            right_text.stylize(_LINE_MODIFY)
            left_style = _EXT_MODIFY
            right_style = _EXT_MODIFY
            left_ranges, right_ranges = _inline_ranges(left.plain, right.plain, word_re)
            for start, end in left_ranges:
                left_text.stylize(_INLINE_DELETE, gutter_w + start, gutter_w + end)
            for start, end in right_ranges:
                right_text.stylize(_INLINE_INSERT, gutter_w + start, gutter_w + end)
        _paint_address(left_text, right_text, left_addr, right_addr, num_w, addr_w)
        _paint_coded(left_text, right_text, left_coded, right_coded, num_w, addr_w, coded_w)
        left_lines.append(left_text)
        left_styles.append(left_style)
        right_lines.append(right_text)
        right_styles.append(right_style)
    return left_lines, left_styles, right_lines, right_styles


_PAIR_MIN = 0.5


def _line_ratio(left, right):
    return difflib.SequenceMatcher(a=left.plain, b=right.plain, autojunk=False).ratio()


def _align_replace(old_chunk, new_chunk):
    """Pair similar lines inside a replace hunk. The rest stay delete or insert."""
    n = len(old_chunk)
    m = len(new_chunk)
    # Huge hunks skip the full alignment. Zip only the lines that still look related.
    if n * m > 2500:
        paired = min(n, m)
        ops = []
        for offset in range(paired):
            if _line_ratio(old_chunk[offset], new_chunk[offset]) >= _PAIR_MIN:
                ops.append(('modify', offset, offset))
            else:
                ops.append(('delete', offset, None))
                ops.append(('insert', None, offset))
        for index in range(paired, n):
            ops.append(('delete', index, None))
        for index in range(paired, m):
            ops.append(('insert', None, index))
        return ops
    ratios = [[0.0] * m for _index in range(n)]
    for i in range(n):
        for j in range(m):
            ratios[i][j] = _line_ratio(old_chunk[i], new_chunk[j])
    score = [[0.0] * (m + 1) for _index in range(n + 1)]
    choice = [[0] * (m + 1) for _index in range(n + 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best = -1.0
            how = 0
            if i and score[i - 1][j] > best:
                best = score[i - 1][j]
                how = 2
            if j and score[i][j - 1] > best:
                best = score[i][j - 1]
                how = 3
            if i and j and ratios[i - 1][j - 1] >= _PAIR_MIN:
                paired_score = score[i - 1][j - 1] + ratios[i - 1][j - 1]
                if paired_score >= best:
                    best = paired_score
                    how = 1
            score[i][j] = best
            choice[i][j] = how
    ops = []
    i, j = n, m
    while i or j:
        how = choice[i][j]
        if how == 1:
            i -= 1
            j -= 1
            ops.append(('modify', i, j))
        elif how == 2 or (how == 0 and i):
            i -= 1
            ops.append(('delete', i, None))
        elif how == 3 or j:
            j -= 1
            ops.append(('insert', None, j))
        else:
            break
    ops.reverse()
    return ops


def _row(kind, left_no, left, left_addr, left_coded, right_no, right, right_addr, right_coded):
    return (kind, left_no, left, left_addr, left_coded, right_no, right, right_addr, right_coded)


def _aligned_rows(old_texts, new_texts, old_addrs, new_addrs, old_coded, new_coded):
    old_plain = [text.plain for text in old_texts]
    new_plain = [text.plain for text in new_texts]
    rows = []
    left_no = 0
    right_no = 0
    matcher = difflib.SequenceMatcher(a=old_plain, b=new_plain, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for offset in range(i2 - i1):
                left_no += 1
                right_no += 1
                rows.append(_row(
                    'equal', left_no, old_texts[i1 + offset], old_addrs[i1 + offset], old_coded[i1 + offset],
                    right_no, new_texts[j1 + offset], new_addrs[j1 + offset], new_coded[j1 + offset],
                ))
        elif tag == 'delete':
            for index in range(i1, i2):
                left_no += 1
                rows.append(_row('delete', left_no, old_texts[index], old_addrs[index], old_coded[index], None, None, None, None))
        elif tag == 'insert':
            for index in range(j1, j2):
                right_no += 1
                rows.append(_row('insert', None, None, None, None, right_no, new_texts[index], new_addrs[index], new_coded[index]))
        else:
            old_chunk = old_texts[i1:i2]
            new_chunk = new_texts[j1:j2]
            old_chunk_addrs = old_addrs[i1:i2]
            new_chunk_addrs = new_addrs[j1:j2]
            old_chunk_coded = old_coded[i1:i2]
            new_chunk_coded = new_coded[j1:j2]
            for kind, old_index, new_index in _align_replace(old_chunk, new_chunk):
                if kind == 'modify':
                    left_no += 1
                    right_no += 1
                    rows.append(_row(
                        'modify', left_no, old_chunk[old_index], old_chunk_addrs[old_index], old_chunk_coded[old_index],
                        right_no, new_chunk[new_index], new_chunk_addrs[new_index], new_chunk_coded[new_index],
                    ))
                elif kind == 'delete':
                    left_no += 1
                    rows.append(_row('delete', left_no, old_chunk[old_index], old_chunk_addrs[old_index], old_chunk_coded[old_index], None, None, None, None))
                else:
                    right_no += 1
                    rows.append(_row('insert', None, None, None, None, right_no, new_chunk[new_index], new_chunk_addrs[new_index], new_chunk_coded[new_index]))
    return rows


def _token_style(token):
    if token.startswith('<'):
        return 'bright_magenta'
    if _REG.fullmatch(token):
        return 'yellow'
    if _NUM.fullmatch(token):
        return 'bright_blue'
    return None


def _append_operands(text, operands):
    for match in _OPERAND.finditer(operands):
        token = match.group(0)
        style = _token_style(token)
        if style:
            text.append(token, style=style)
        else:
            text.append(token)


def _append_comment(text, comment):
    text.append('# ', style='dim')
    for match in _OPERAND.finditer(comment):
        token = match.group(0)
        if token.startswith('<'):
            text.append(token, style='bright_magenta')
        else:
            text.append(token, style='dim')


def _pane(items, show_addresses):
    if not items:
        empty = Text('(no assembly)', style='dim', no_wrap=True)
        return [empty], [_EXT_NONE]
    width, comment_at = _metrics(items)
    rendered = [_render_item(item, width, comment_at) for item in items]
    addrs = [_item_addr(item) for item in items]
    coded = [_item_coded(item) for item in items]
    addr_w = _addr_width(addrs) if show_addresses else 0
    coded_w = _coded_width(coded)
    num_w = max(3, len(str(len(rendered))))
    lines = [
        _compose_line(index + 1, line, num_w, addrs[index], addr_w, coded[index], coded_w)
        for index, line in enumerate(rendered)
    ]
    return lines, [_EXT_NONE] * len(lines)


def _same_code(old_items, new_items):
    def key(item):
        if item[0] == 'insn':
            coded = item[5] if len(item) > 5 else None
            return ('insn', item[1], item[2], item[3], coded)
        if item[0] == 'label':
            return ('label', item[1])
        return item
    return [key(item) for item in old_items] == [key(item) for item in new_items]


def _format_sides(new_items, old_items, label_a, label_b, diff_mode, show_addresses):
    if not diff_mode:
        lines, styles = _pane(new_items, show_addresses)
        return AsmView(False, lines, styles, [], [], label_a, '', False)
    if not new_items and not old_items:
        lines, styles = _pane([], False)
        return AsmView(True, lines, styles, list(lines), list(styles), label_b, label_a, True)
    width, comment_at = _metrics(old_items + new_items)
    old_texts = [_render_item(item, width, comment_at) for item in old_items]
    new_texts = [_render_item(item, width, comment_at) for item in new_items]
    old_addrs = [_item_addr(item) for item in old_items]
    new_addrs = [_item_addr(item) for item in new_items]
    old_coded = [_item_coded(item) for item in old_items]
    new_coded = [_item_coded(item) for item in new_items]
    rows = _aligned_rows(old_texts, new_texts, old_addrs, new_addrs, old_coded, new_coded)
    max_no = 0
    for _kind, left_no, _left, _left_addr, _left_coded, right_no, _right, _right_addr, _right_coded in rows:
        max_no = max(max_no, left_no or 0, right_no or 0)
    num_w = max(3, len(str(max_no or 1)))
    addr_w = _addr_width(old_addrs + new_addrs) if show_addresses else 0
    coded_w = _coded_width(old_coded + new_coded)
    left_lines, left_styles, right_lines, right_styles = _build_panes(rows, num_w, addr_w, coded_w)
    return AsmView(
        True,
        left_lines,
        left_styles,
        right_lines,
        right_styles,
        label_b,
        label_a,
        _same_code(old_items, new_items),
    )


def format_asm_view(text_a, text_b, label_a, label_b, diff_mode, show_addresses=False):
    new_items = _program(text_a)
    old_items = _program(text_b) if diff_mode else []
    return _format_sides(new_items, old_items, label_a, label_b, diff_mode, show_addresses)


def view_from_records(record_sets, spans, label_a, label_b, diff_mode, show_addresses, show_source):
    items_a = render_items(record_sets[0] if record_sets else None, spans, False, show_source)
    if not diff_mode:
        return _format_sides(items_a, [], label_a, '', False, show_addresses)
    items_b = render_items(record_sets[1], spans, True, show_source)
    return _format_sides(items_a, items_b, label_a, label_b, True, show_addresses)


def map_label(path):
    file_path = Path(path)
    return f'{file_path.parent.name}/{file_path.name}'


_HEX_WORD = re.compile(r'[0-9a-fA-F]{2}|\s+|.')


class HexBlob:
    def __init__(self, name, address, data, missing, peer_address, peer_data, peer_missing):
        self.name = name or ''
        self.address = address or 0
        self.data = data or b''
        self.missing = missing
        self.peer_address = peer_address or 0
        self.peer_data = peer_data or b''
        self.peer_missing = peer_missing


def load_span_bytes(image, address, size, section):
    if not size:
        return b'', False
    data = image.read(address, size, section)
    if not data:
        return b'', True
    return data, False


def _hex_plain(data):
    slots = [f'{data[index]:02x}' if index < len(data) else '  ' for index in range(16)]
    body = ' '.join(slots[:8]) + '  ' + ' '.join(slots[8:])
    ascii_text = ''.join(chr(byte) if 32 <= byte < 127 else '.' for byte in data).ljust(16)
    return f'{body}  |{ascii_text}|'


def _append_hex_rows(items, name, address, data, missing):
    if not data and not missing:
        return
    if items:
        items.append(('blank',))
    items.append(('label', f'<{name}>:', address))
    if missing:
        items.append(('note', '(not in elf)', address))
        return
    for offset in range(0, len(data), 16):
        items.append(('hex', data[offset:offset + 16], address + offset))


def _hex_rows(blobs, peer):
    items = []
    for blob in blobs:
        if peer:
            _append_hex_rows(items, blob.name, blob.peer_address, blob.peer_data, blob.peer_missing)
        else:
            _append_hex_rows(items, blob.name, blob.address, blob.data, blob.missing)
    return items


def _render_hex_item(item):
    kind = item[0]
    if kind == 'blank':
        return Text(no_wrap=True), None
    if kind == 'label':
        return Text(item[1], style='bold bright_magenta', no_wrap=True), item[2]
    if kind == 'note':
        return Text(item[1], style='italic dim', no_wrap=True), item[2]
    plain = _hex_plain(item[1])
    text = Text(plain, no_wrap=True)
    split = plain.find('|')
    text.stylize('#8b93a7', 0, split)
    text.stylize('dim', split, len(plain))
    return text, item[2]


def _hex_texts(items):
    texts = []
    addrs = []
    for item in items:
        text, addr = _render_hex_item(item)
        texts.append(text)
        addrs.append(addr)
    return texts, addrs


def _compose_hex_lines(items, show_addresses):
    if not items:
        empty = Text('(no data)', style='dim', no_wrap=True)
        return [empty], [_EXT_NONE]
    texts, addrs = _hex_texts(items)
    addr_w = _addr_width(addrs) if show_addresses else 0
    num_w = max(3, len(str(len(texts))))
    lines = [
        _compose_line(index + 1, line, num_w, addrs[index], addr_w, None, 0)
        for index, line in enumerate(texts)
    ]
    return lines, [_EXT_NONE] * len(lines)


def _hex_identity(items):
    identity = []
    for item in items:
        if item[0] == 'hex':
            identity.append(('hex', _hex_plain(item[1])))
        elif item[0] in ('label', 'note'):
            identity.append((item[0], item[1]))
        else:
            identity.append((item[0],))
    return identity


def view_from_hex(blobs, label_a, label_b, diff_mode, show_addresses):
    new_items = _hex_rows(blobs, False)
    if not diff_mode:
        lines, styles = _compose_hex_lines(new_items, show_addresses)
        return AsmView(False, lines, styles, [], [], label_a, '', False)
    old_items = _hex_rows(blobs, True)
    if not new_items and not old_items:
        lines, styles = _compose_hex_lines([], False)
        return AsmView(True, lines, styles, list(lines), list(styles), label_b, label_a, True)
    new_texts, new_addrs = _hex_texts(new_items)
    old_texts, old_addrs = _hex_texts(old_items)
    rows = _aligned_rows(
        old_texts, new_texts, old_addrs, new_addrs, [None] * len(old_texts), [None] * len(new_texts),
    )
    max_no = 0
    for _kind, left_no, _left, _left_addr, _left_coded, right_no, _right, _right_addr, _right_coded in rows:
        max_no = max(max_no, left_no or 0, right_no or 0)
    num_w = max(3, len(str(max_no or 1)))
    addr_w = _addr_width(old_addrs + new_addrs) if show_addresses else 0
    left_lines, left_styles, right_lines, right_styles = _build_panes(rows, num_w, addr_w, 0, _HEX_WORD)
    return AsmView(
        True,
        left_lines,
        left_styles,
        right_lines,
        right_styles,
        label_b,
        label_a,
        _hex_identity(old_items) == _hex_identity(new_items),
    )
