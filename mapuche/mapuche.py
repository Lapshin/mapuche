#!/usr/bin/env python3

if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "mapuche"

import argparse
import re
from importlib.metadata import PackageNotFoundError, version
from itertools import cycle
from textual.app import App, ComposeResult, RenderResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.containers import Horizontal, HorizontalScroll, Container, Vertical
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import DataTable, Footer, Header, Checkbox, Label, Button, Input
from textual.reactive import Reactive
from .demangle import demangle_map_name
from .parser import get_table_header, get_table_data
from .styles import get_stylized_table_header, get_stylized_table_row, get_stylized_row_label, row_style
from textual.containers import ScrollableContainer

from textual.app import RenderResult
from textual.dom import NoScreen
from textual.events import Click, Mount
from textual.reactive import Reactive
from textual.widget import Widget


from textual.coordinate import Coordinate
from textual import events, on, work
from textual.worker import WorkerCancelled, WorkerFailed
from rich.color import Color
from rich.style import Style
from .asm import (
    scan_map_file,
    detect_objdump,
    resolve_user_objdump,
    collect_asm_targets,
    collect_hex_targets,
    ElfImage,
    HexBlob,
    load_disassembly,
    load_span_bytes,
    view_from_hex,
    view_from_records,
    map_label,
)

class ObjdumpPathScreen(ModalScreen):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    DEFAULT_CSS = """
    ObjdumpPathScreen {
        align: center middle;
    }
    #objdump-dialog {
        width: 80;
        max-width: 100%;
        height: auto;
        background: $panel;
        border: thick $accent;
        padding: 1 2;
    }
    #objdump-dialog Label {
        width: 100%;
        height: auto;
    }
    #objdump-path {
        margin: 1 0;
    }
    #objdump-error {
        color: $error;
        height: auto;
    }
    #objdump-buttons {
        height: auto;
        align: right middle;
    }
    #objdump-buttons Button {
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id='objdump-dialog'):
            yield Label('objdump was not found in the toolchain directory from the map file.')
            yield Label('Enter a path to objdump, or to the directory that contains it.')
            yield Input(placeholder='/path/to/riscv32-esp-elf-objdump', id='objdump-path')
            yield Label('', id='objdump-error')
            with Horizontal(id='objdump-buttons'):
                yield Button('OK', id='objdump-ok', variant='primary')
                yield Button('Cancel', id='objdump-cancel')

    def on_mount(self) -> None:
        self.query_one('#objdump-path', Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, '#objdump-cancel')
    def cancel_pressed(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, '#objdump-ok')
    def ok_pressed(self) -> None:
        self._try_accept(self.query_one('#objdump-path', Input).value)

    @on(Input.Submitted, '#objdump-path')
    def path_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._try_accept(event.value)

    def _try_accept(self, text: str) -> None:
        found = resolve_user_objdump(text)
        if found is None:
            self.query_one('#objdump-error', Label).update('objdump not found at that path')
            return
        self.dismiss(found)


class DiffDocument(ScrollView):
    def __init__(self, lines, extend_styles, **kwargs):
        super().__init__(**kwargs)
        self.lines = lines
        self.extend_styles = extend_styles
        self.peer = None
        self._syncing = False
        widest = 1
        for line in lines:
            widest = max(widest, line.cell_len)
        self._widest = widest

    def on_mount(self) -> None:
        self.virtual_size = Size(self._widest, max(len(self.lines), 1))
        super().on_mount()

    def set_content(self, lines, extend_styles) -> None:
        self.lines = lines
        self.extend_styles = extend_styles
        widest = 1
        for line in lines:
            widest = max(widest, line.cell_len)
        self._widest = widest
        self.virtual_size = Size(widest, max(len(lines), 1))
        self.refresh()

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        width = self.scrollable_content_region.width
        row = scroll_y + y
        if width <= 0:
            width = self.size.width
        if row < 0 or row >= len(self.lines):
            return Strip.blank(width, self.rich_style)
        text = self.lines[row]
        style = self.extend_styles[row]
        # Rich omits a style when a line has no spans. Textual's monochrome
        # filter (NO_COLOR) requires every segment style to be a Style.
        blank = Style()
        segments = [
            segment if segment.style is not None else segment._replace(style=blank)
            for segment in text.render(self.app.console)
        ]
        strip = Strip(segments).crop_extend(scroll_x, scroll_x + width, style or blank)
        return strip.apply_style(self.rich_style)

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if self._syncing or self.peer is None:
            return
        if round(self.peer.scroll_y) == round(new_value):
            return
        self.peer._syncing = True
        try:
            self.peer.scroll_to(y=new_value, animate=False, immediate=True)
        finally:
            self.peer._syncing = False


class AsmScreen(ModalScreen):
    BINDINGS = [Binding('escape', 'dismiss', 'Close')]

    DEFAULT_CSS = """
    AsmScreen {
        align: center middle;
    }
    #asm-frame {
        width: 96%;
        height: 96%;
        border: tall $accent;
        background: $surface;
    }
    #diff-panels {
        height: 1fr;
        width: 1fr;
    }
    .diff-col {
        width: 1fr;
        height: 1fr;
    }
    #original-col {
        border-right: solid $foreground 30%;
    }
    .diff-header {
        height: 1;
        padding: 0 1;
        background: $boost;
        text-style: bold;
    }
    #original-col .diff-header {
        color: #ffb4b4;
    }
    #changed-col .diff-header {
        color: #b6f5c6;
    }
    .diff-file {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        overflow: hidden;
    }
    #asm-options {
        height: 1;
        width: 1fr;
        padding: 0 1;
    }
    #asm-options Checkbox {
        height: 1;
        width: auto;
        border: none;
        padding: 0 1;
        background: transparent;
        margin: 0 1 0 0;
    }
    #asm-status {
        width: 1fr;
        height: 1;
        color: $text-muted;
        content-align: right middle;
    }
    DiffDocument {
        height: 1fr;
        width: 100%;
    }
    """

    def __init__(self, title: str, view, targets, size_diff=None, hex_blobs=None, hex_labels=('', '')):
        super().__init__()
        self.asm_title = title if len(title) <= 80 else title[:77] + '...'
        self.asm_view = view
        self.targets = targets
        self.size_diff = size_diff
        self.hex_blobs = hex_blobs
        self.hex_labels = hex_labels
        self._source_loaded = False
        self._refresh_gen = 0

    def compose(self) -> ComposeResult:
        view = self.asm_view
        with Vertical(id='asm-frame'):
            with Horizontal(id='asm-options'):
                yield Checkbox('show addresses', self.hex_blobs is not None, id='asm-addresses')
                if self.hex_blobs is None:
                    yield Checkbox('show source code', id='asm-source')
                yield Label('', id='asm-status')
            if view.side_by_side:
                with Horizontal(id='diff-panels'):
                    with Vertical(id='original-col', classes='diff-col'):
                        yield Label('ORIGINAL', classes='diff-header')
                        yield Label(view.left_file, classes='diff-file')
                        yield DiffDocument(view.left_lines, view.left_styles, id='original-doc')
                    with Vertical(id='changed-col', classes='diff-col'):
                        yield Label(self._changed_label(), classes='diff-header')
                        yield Label(view.right_file, classes='diff-file')
                        yield DiffDocument(view.right_lines, view.right_styles, id='changed-doc')
            else:
                yield DiffDocument(view.left_lines, view.left_styles, id='single-doc')

    def _changed_label(self) -> str:
        if self.size_diff is None:
            return 'CHANGED'
        return f'CHANGED  {self.size_diff:+d}'

    def on_mount(self) -> None:
        self._apply_frame()
        if self.asm_view.side_by_side:
            left = self.query_one('#original-doc', DiffDocument)
            right = self.query_one('#changed-doc', DiffDocument)
            left.peer = right
            right.peer = left
            right.focus()
        else:
            self.query_one('#single-doc', DiffDocument).focus()

    def _apply_frame(self) -> None:
        frame = self.query_one('#asm-frame')
        if self.asm_view.side_by_side:
            frame.border_title = 'DIFF VIEWER'
            if self.asm_view.match:
                note = 'bytes match · ' if self.hex_blobs is not None else 'assemblies match · '
            else:
                note = ''
            frame.border_subtitle = f'{note}{self.asm_title} · esc'
        else:
            frame.border_title = self.asm_title
            frame.border_subtitle = 'esc close'

    def _install_view(self, view) -> None:
        self.asm_view = view
        self._apply_frame()
        if view.side_by_side:
            left = self.query_one('#original-doc', DiffDocument)
            right = self.query_one('#changed-doc', DiffDocument)
            left.set_content(view.left_lines, view.left_styles)
            right.set_content(view.right_lines, view.right_styles)
        else:
            self.query_one('#single-doc', DiffDocument).set_content(view.left_lines, view.left_styles)

    @on(Checkbox.Changed)
    def options_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        self._refresh_options()

    @work(exclusive=True, group='asm-view', exit_on_error=False)
    async def _refresh_options(self) -> None:
        self._refresh_gen += 1
        generation = self._refresh_gen
        show_addresses = self.query_one('#asm-addresses', Checkbox).value
        if self.hex_blobs is not None:
            label_a, label_b = self.hex_labels
            view = view_from_hex(
                self.hex_blobs, label_a, label_b, bool(getattr(self.app, 'map_diff', False)), show_addresses,
            )
            if not self.is_mounted or generation != self._refresh_gen:
                return
            self._install_view(view)
            return
        show_source = self.query_one('#asm-source', Checkbox).value
        status = self.query_one('#asm-status', Label)
        if show_source and not self._source_loaded:
            status.update('loading source…')
        try:
            view = await self.app.rebuild_asm_view(self.targets, show_addresses, show_source).wait()
        except WorkerCancelled:
            return
        except WorkerFailed as exc:
            if self.is_mounted:
                status.update('')
                if show_source:
                    box = self.query_one('#asm-source', Checkbox)
                    with box.prevent(Checkbox.Changed):
                        box.value = False
                self.app.notify(str(exc.error), title='asm', severity='error', timeout=8)
            return
        if not self.is_mounted or generation != self._refresh_gen:
            return
        if show_source:
            self._source_loaded = True
        status.update('')
        self._install_view(view)


class FilterInput(Input):
    """Regex filter. Escape returns to the table and leaves the pattern in place."""

    BINDINGS = [Binding('escape', 'leave_filter', 'Leave filter', show=False)]

    def action_leave_filter(self) -> None:
        self.app.query_one(DataTable).focus()


class MyHeader(ScrollableContainer, can_focus=False, can_focus_children=True):
    DEFAULT_CSS = """
    MyHeader {
        dock: top;
        width: 100%;
        background: $boost;
        color: $text;
        height: 3;
        border-bottom: tall $accent;
    }
    MyHeader.comparing {
        height: 4;
    }
    MyHeader Checkbox {
        height: 1;
        width: auto;
        border: none;
        padding: 0 1;
        background: $primary 22%;
        margin: 0 1 0 0;
    }
    #compare-files {
        height: 1;
        width: 1fr;
        padding: 0 1;
    }
    .compare-name {
        width: auto;
        height: 1;
        color: $text-muted;
    }
    .compare-note, .compare-op, .compare-quote {
        width: auto;
        height: 1;
        color: $text-muted;
    }
    .compare-note {
        padding: 0 1 0 0;
    }
    .compare-op {
        padding: 0 1;
    }
    #header-bar {
        height: 1;
        width: 1fr;
    }
    #filter-row {
        height: 1;
        width: auto;
        margin: 0 0 0 1;
        padding: 0 1;
        background: $accent 14%;
    }
    #filter-icon {
        width: auto;
        height: 1;
        padding: 0 1 0 0;
        content-align: left middle;
        background: $accent 14%;
    }
    #name-filter {
        width: 32;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
        background: $accent 14%;
        color: $text;
    }
    #name-filter:focus, #name-filter.-invalid {
        border: none;
        height: 1;
        padding: 0;
    }
    #name-filter:focus {
        background: $accent 28%;
    }
    #name-filter.-invalid {
        background-tint: $error 30%;
    }
    """

    DEFAULT_CLASSES = ""

    def __init__(
        self,
        *buttons,
        compare=None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        self.buttons = buttons
        self.compare = compare
        if compare:
            classes = f'{classes} comparing' if classes else 'comparing'
        super().__init__(name=name, id=id, classes=classes)

    def compose(self):
        if self.compare:
            label_a, label_b = self.compare
            with Horizontal(id='compare-files'):
                yield Label('Diff ==', id='compare-diff', classes='compare-note')
                yield Label('"', classes='compare-quote')
                yield Label(label_a, id='compare-a', classes='compare-name')
                yield Label('"', classes='compare-quote')
                yield Label('-', classes='compare-op')
                yield Label('"', classes='compare-quote')
                yield Label(label_b, id='compare-b', classes='compare-name')
                yield Label('"', classes='compare-quote')
        with Horizontal(id='header-bar'):
            for button in self.buttons:
                yield button
        with Horizontal(id='filter-row'):
            yield Label('🔍', id='filter-icon')
            yield FilterInput(
                placeholder='regex',
                id='name-filter',
                max_length=32,
            )

class MapTable(DataTable):
    def _get_row_style(self, row_index, base_style):
        style = super()._get_row_style(row_index, base_style)
        if row_index < 0:
            return style
        highlight = row_style(self._row_locations.get_key(row_index).value)
        if highlight is None:
            return style
        return style + highlight


def fully_reduced(node):
    """Subtree that only shrank. A shrunk parent with any growth inside stays."""
    if node.value.diff > 0:
        return False
    for child in node.children:
        if not fully_reduced(child):
            return False
    return node.value.diff < 0 or bool(node.children)


class TableApp(App):
    map_diff = False
    rows = None
    table_header = []
    show_debug = False

    BINDINGS = [
        Binding("right", "right_arrow_key", "expand", False),
        Binding("left", "left_arrow_key", "collapse", False),
        Binding("space", "space_key", "expand/collapse", False),
        Binding("a", "asm_diff", "asm"),
        Binding("slash", "focus_filter", "filter"),
    ]

    DEBUG_SECTIONS = [
        '.comment',
        '.debug_',
    ]

    def __init__(self, map_file, diff_map_file=None):
        self.map_diff = diff_map_file is not None
        self.map_paths = [map_file] if not self.map_diff else [map_file, diff_map_file]
        self.elf_paths = []
        self.libc_paths = []
        for path in self.map_paths:
            elf, libc = scan_map_file(path)
            self.elf_paths.append(elf)
            self.libc_paths.append(libc)
        self.objdump_paths = None
        self._objdump_probed = False
        self._asm_cache = {}
        self._elf_cache = {}
        self.table_data = get_table_data(map_file, diff_map_file)
        self.table_header = get_table_header(self.map_diff)
        self.cxx_demangle = True
        self.show_debug = False
        self.hide_reduced = False
        self._name_filter = None
        self._filter_visible = None
        # Nodes opened only to reveal a match. Cleared when the pattern no longer needs them.
        self._auto_expanded = set()
        self.show_debug_button = Checkbox('Debug sections', value=False, id='show_debug')
        self.demangle_button = Checkbox('C++ demangle', value=True, id='cxx_demangle')
        self.hide_reduced_button = Checkbox('Hide reduced', value=False, id='hide_reduced')
        self.show_debug_button.can_focus = False
        self.demangle_button.can_focus = False
        self.hide_reduced_button.can_focus = False
        self.hide_show_debug_sections()
        super().__init__()

    def compose(self) -> ComposeResult:
        # yield Checkbox("Grumman", True)
        buttons = [self.show_debug_button, self.demangle_button]
        compare = None
        if self.map_diff:
            buttons.append(self.hide_reduced_button)
            compare = (map_label(self.map_paths[0]), map_label(self.map_paths[1]))
        yield MyHeader(*buttons, compare=compare)
        yield MapTable()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        # Cell color has to win on the selected row, or the cursor wipes green/red.
        if self.map_diff:
            table.cursor_foreground_priority = 'renderable'
        table.cursor_type = 'row'
        table.zebra_stripes = True
        table.fixed_rows = 1
        table.add_columns(*get_stylized_table_header(*self.table_header))
        self.reset_table()
        table.focus()

    async def _on_message(self, message: Message) -> None:
        message_class = message.__class__.__name__
        if message_class == 'RowLabelSelected' or message_class == 'RowSelected':
            table = self.query_one(DataTable)
            if message_class == 'RowLabelSelected':
                new_cursor = Coordinate(message.row_index, table.cursor_coordinate.column)
            else:
                new_cursor = Coordinate(message.cursor_row, table.cursor_coordinate.column)
            table.cursor_coordinate = new_cursor
            self.call_after_refresh(self.collapse_expand_node)
        elif message_class == 'HeaderSelected':
            self.table_data.sort(message.column_index)
            self.reset_table()

        await super()._on_message(message)

    def _row_hidden(self, node):
        return node.hidden or (self.hide_reduced and fully_reduced(node))

    def _matches_filter(self, node, pattern, shown):
        if pattern.search(shown):
            return True
        raw = node.value.name
        if isinstance(raw, str) and raw != shown and pattern.search(raw):
            return True
        source = node.value.source
        return isinstance(source, str) and bool(source) and pattern.search(source) is not None

    def _plan_filter(self, pattern):
        """Rows to keep, and ancestors to open so a match is on screen.

        A matching node keeps its descendants, but they stay collapsed until
        the user opens that node. A match under a non-matching parent keeps
        the parent and opens it.
        """
        visible = set()
        to_expand = set()

        def walk(node, ancestor_matched):
            if self._row_hidden(node):
                return False
            shown = self.display_name(node)
            self_match = self._matches_filter(node, pattern, shown)
            under_match = ancestor_matched or self_match
            child_hit = False
            for child in node.children:
                if walk(child, under_match):
                    child_hit = True
            if under_match or child_hit:
                visible.add(node)
            if child_hit and not self_match and not ancestor_matched:
                to_expand.add(node)
            return self_match or child_hit

        for child in self.table_data.children:
            walk(child, False)
        return visible, to_expand

    def _prepare_filter(self):
        if self._name_filter is None:
            self._filter_visible = None
            return
        self._filter_visible, _to_expand = self._plan_filter(self._name_filter)

    def _sync_filter_expansion(self):
        if self._name_filter is None:
            for node in self._auto_expanded:
                node.expand = False
            self._auto_expanded.clear()
            return
        _visible, to_expand = self._plan_filter(self._name_filter)
        for node in list(self._auto_expanded):
            if node not in to_expand:
                node.expand = False
                self._auto_expanded.discard(node)
        for node in to_expand:
            if not node.expand:
                node.expand = True
                self._auto_expanded.add(node)

    def _refresh_for_filter(self):
        self._sync_filter_expansion()
        if self.is_mounted and self.query(DataTable):
            self.reset_table()

    def collect_rows(self, data):
        if data.is_root():
            self._prepare_filter()
        visible = self._filter_visible
        rows = []
        for c in data.children:
            if self._row_hidden(c):
                continue
            if visible is not None and c not in visible:
                continue
            value_tuple = get_stylized_table_row(c, self.display_name(c))
            if not self.map_diff:
                value_tuple = value_tuple[0:3]
            rows.append([value_tuple, c])
            if c.expand:
                rows += self.collect_rows(c)
        return rows

    def reset_table(self):
        total_row = get_stylized_table_row(self.table_data, self.display_name(self.table_data))
        if not self.map_diff:
            total_row = total_row[0:3]
        rows = [(total_row, self.table_data)] + self.collect_rows(self.table_data)
        table = self.query_one(DataTable)
        scroll_x = table.scroll_x
        scroll_y = table.scroll_y
        cursor = table.cursor_coordinate
        # clear() moves the cursor to (0, 0) and scrolls that cell into view
        # after the next refresh, which jumps the table to the top.
        table.clear()
        for i, (r, k) in enumerate(rows):
            table.add_row(*r, key=k, label=get_stylized_row_label(k))
        if cursor.row < table.row_count:
            table.set_reactive(DataTable.cursor_coordinate, cursor)

        def restore_scroll() -> None:
            table.scroll_x = scroll_x
            table.scroll_y = scroll_y
            table.scroll_target_x = scroll_x
            table.scroll_target_y = scroll_y

        table.call_after_refresh(restore_scroll)

    def collapse_expand_node(self, expand=None) -> None:
        table = self.query_one(DataTable)
        cursor_coordinate = table.cursor_coordinate
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value.is_root():
            return
        if expand == None:
            self._auto_expanded.discard(row_key.value)
            row_key.value.set_expand()
        else:
            if expand:
                if table.is_valid_coordinate(table.cursor_coordinate.down()):
                    row_key_next, _ = table.coordinate_to_cell_key(table.cursor_coordinate.down())
                    if row_key.value.level <= row_key_next.value.level:
                        cursor_coordinate = cursor_coordinate.down()
            elif row_key.value.expand != True and not row_key.value.parent.is_root():
                current_level = row_key.value.level
                while cursor_coordinate.row > 0 and current_level <= row_key.value.level:
                    cursor_coordinate = cursor_coordinate.up()
                    row_key, _ = table.coordinate_to_cell_key(cursor_coordinate)
            self._auto_expanded.discard(row_key.value)
            row_key.value.set_expand(expand)
        self.reset_table()
        table.cursor_coordinate = cursor_coordinate

    def action_right_arrow_key(self) -> None:
        self.collapse_expand_node(True)

    def action_left_arrow_key(self) -> None:
        self.collapse_expand_node(False)

    def action_space_key(self) -> None:
        self.collapse_expand_node()

    def action_focus_filter(self) -> None:
        self.query_one('#name-filter', FilterInput).focus()

    def check_action(self, action, parameters):
        if action == 'asm_diff' and not self._elfs_ready():
            return False
        return True

    def _elfs_ready(self):
        return bool(self.elf_paths) and all(elf is not None for elf in self.elf_paths)

    def action_asm_diff(self) -> None:
        self.open_asm_diff()

    @work(exclusive=True, group='asm', exit_on_error=False)
    async def open_asm_diff(self) -> None:
        if not self._elfs_ready():
            self.notify('OUTPUT() ELF from the map file was not found', title='asm', severity='error')
            return
        table = self.query_one(DataTable)
        if not table.is_valid_coordinate(table.cursor_coordinate):
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        node = row_key.value
        targets = collect_asm_targets(node, self.map_diff)
        hex_spans = [] if targets else collect_hex_targets(node, self.map_diff)
        if not targets and not hex_spans:
            self.notify('No code in this row', title='asm')
            return
        if targets:
            objdumps = await self._ensure_objdumps()
            if not objdumps:
                return
        if self.cxx_demangle:
            for span in hex_spans:
                span.name = demangle_map_name(span.name)
        title = self.display_name(node)
        self._asm_open_gen = getattr(self, '_asm_open_gen', 0) + 1
        generation = self._asm_open_gen
        self.clear_notifications()
        self.notify('disassembling…' if targets else 'reading…', title='asm', timeout=30)
        try:
            if targets:
                text = await self._disassemble(objdumps, targets, self.cxx_demangle).wait()
                hex_blobs = None
                hex_labels = ('', '')
            else:
                text, hex_blobs, hex_labels = await self._read_hex(hex_spans).wait()
        except WorkerCancelled:
            # A second `a` cancels this run. Textual's wait() reports that as
            # WorkerCancelled; it is not an objdump failure. Leave the toast
            # for the run that replaced this one.
            return
        except WorkerFailed as exc:
            if generation != self._asm_open_gen:
                return
            if targets:
                self.objdump_paths = None
                self._objdump_probed = True
            self.clear_notifications()
            self.notify(str(exc.error), title='asm', severity='error', timeout=8)
            return
        if generation != self._asm_open_gen:
            return
        size_diff = node.value.diff if self.map_diff else None
        self.clear_notifications()
        self.push_screen(AsmScreen(title, text, targets, size_diff, hex_blobs, hex_labels))

    async def _ensure_objdumps(self):
        """One objdump per opened map. Xtensa and RISC-V maps stay on their own tools."""
        if self.objdump_paths and all(self.objdump_paths):
            return self.objdump_paths
        found = list(self.objdump_paths or [])
        if not self._objdump_probed:
            self._objdump_probed = True
            found = [detect_objdump([libc]) for libc in self.libc_paths]
            if all(found):
                self.objdump_paths = found
                return found
        if len(found) != len(self.libc_paths):
            found = [None] * len(self.libc_paths)
        if any(path is None for path in found):
            chosen = await self.push_screen_wait(ObjdumpPathScreen())
            if not chosen:
                return None
            found = [path or chosen for path in found]
        self.objdump_paths = found
        return found

    def _asm_labels(self):
        label_a = map_label(self.map_paths[0])
        label_b = map_label(self.map_paths[1]) if self.map_diff else ''
        return label_a, label_b

    def _elf_image(self, path):
        image = self._elf_cache.get(path)
        if image is None:
            image = ElfImage(path)
            self._elf_cache[path] = image
        return image

    @work(thread=True, group='asm-objdump', exit_on_error=False, description='read elf')
    def _read_hex(self, spans):
        images = [self._elf_image(path) for path in self.elf_paths]
        blobs = []
        for span in spans:
            data, missing = load_span_bytes(images[0], span.address, span.size, span.section)
            if self.map_diff:
                peer, peer_missing = load_span_bytes(images[1], span.peer_address, span.peer_size, span.section)
            else:
                peer, peer_missing = b'', False
            blobs.append(HexBlob(span.name, span.address, data, missing, span.peer_address, peer, peer_missing))
        label_a, label_b = self._asm_labels()
        view = view_from_hex(blobs, label_a, label_b, bool(self.map_diff), True)
        return view, blobs, (label_a, label_b)

    @work(thread=True, group='asm-objdump', exit_on_error=False, description='disassemble')
    def _disassemble(self, objdumps, targets, demangle):
        records = [
            load_disassembly(objdump, elf, demangle, False, self._asm_cache)
            for objdump, elf in zip(objdumps, self.elf_paths)
        ]
        label_a, label_b = self._asm_labels()
        return view_from_records(records, targets, label_a, label_b, bool(self.map_diff), False, False)

    @work(thread=True, exclusive=True, group='asm-rebuild', exit_on_error=False, description='rebuild asm')
    def rebuild_asm_view(self, targets, show_addresses, show_source):
        records = [
            load_disassembly(objdump, elf, self.cxx_demangle, show_source, self._asm_cache)
            for objdump, elf in zip(self.objdump_paths, self.elf_paths)
        ]
        label_a, label_b = self._asm_labels()
        return view_from_records(
            records, targets, label_a, label_b, bool(self.map_diff), show_addresses, show_source,
        )

    def display_name(self, node) -> str:
        name = node.value.name
        if self.cxx_demangle:
            return demangle_map_name(name)
        return name

    @on(Checkbox.Changed, "#show_debug")
    def show_debug_pressed(self, event: Checkbox.Changed) -> None:
        self.show_debug = event.value
        self.hide_show_debug_sections()
        self._refresh_for_filter()

    @on(Checkbox.Changed, "#cxx_demangle")
    def cxx_demangle_pressed(self, event: Checkbox.Changed) -> None:
        self.cxx_demangle = event.value
        self._refresh_for_filter()

    @on(Checkbox.Changed, "#hide_reduced")
    def hide_reduced_pressed(self, event: Checkbox.Changed) -> None:
        self.hide_reduced = event.value
        self._refresh_for_filter()

    @on(Input.Changed, '#name-filter')
    def name_filter_changed(self, event: Input.Changed) -> None:
        text = event.value
        box = event.input
        if text == '':
            self._name_filter = None
            box.remove_class('-invalid')
        else:
            try:
                compiled = re.compile(text)
            except re.error:
                box.add_class('-invalid')
                return
            self._name_filter = compiled
            box.remove_class('-invalid')
        self._refresh_for_filter()

    @on(Input.Submitted, '#name-filter')
    def name_filter_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.query_one(DataTable).focus()

    def hide_show_debug_sections(self):
        for k in self.table_data.children:
            if k.value.name.startswith(tuple(TableApp.DEBUG_SECTIONS)):
                k.hidden = not self.show_debug

def package_version():
    try:
        return version('mapuche')
    except PackageNotFoundError:
        return 'unknown'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='mapuche',
        description="Linker's map file browser",
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'mapuche {package_version()}',
    )
    parser.add_argument(
        'map_file',
        metavar='elf.map',
        help='map file of an ELF built with -ffunction-sections and -fdata-sections',
    )
    parser.add_argument(
        'diff_map_file',
        nargs='?',
        metavar='elf_for_diff.map',
        help='second map file to compare against',
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app = TableApp(args.map_file, args.diff_map_file)
    app.run()

if __name__ == "__main__":
    main()
