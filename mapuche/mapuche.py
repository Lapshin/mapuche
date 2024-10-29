#!/usr/bin/env python3

from itertools import cycle
from os import sys
from textual.app import App, ComposeResult, RenderResult
from textual.binding import Binding
from textual.message import Message
from textual.containers import Horizontal, HorizontalScroll, Container
from textual.widgets import DataTable, Footer, Header, Checkbox, Label, Button
from textual.reactive import Reactive
from .parser import get_table_header, get_table_data
from .styles import get_stylized_table_header, get_stylized_table_row, get_stylized_row_label
from textual.containers import ScrollableContainer

from textual.app import RenderResult
from textual.dom import NoScreen
from textual.events import Click, Mount
from textual.reactive import Reactive
from textual.widget import Widget

from textual import events, on
from rich.color import Color

class UnfocusableButton(Button):
    def __init__(self, label: str, id=None):
        super().__init__(label, id=id)
        self.can_focus = False

class MyHeader(ScrollableContainer, can_focus=False, can_focus_children=False):
    DEFAULT_CSS = """
    MyHeader {
        dock: top;
        width: 100%;
        background: $foreground 5%;
        color: $text;
        height: 1;
    }
    """

    DEFAULT_CLASSES = ""

    def __init__(
        self,
        show_debug_button,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        self.show_debug_button=show_debug_button
        super().__init__(name=name, id=id, classes=classes)

    def compose(self):
        with Horizontal(id="top-right"):
            yield self.show_debug_button

class TableApp(App):
    map_diff = False
    rows = None
    table_header = []
    show_debug = False

    BINDINGS = [
        Binding("right", "right_arrow_key", "expand", False),
        Binding("left", "left_arrow_key", "collapse", False),
        Binding("space", "space_key", "expand/collapse", False),
    ]

    DEBUG_SECTIONS = [
        '.comment',
        '.debug_',
    ]

    CSS = """
    UnfocusableButton {
        padding: 0 0;
        height: 1;
        border: none;
        width: auto;
        min-width: 20;
    }
    """

    def __init__(self):
        self.map_diff = len(sys.argv) == 3
        self.table_data = get_table_data(sys.argv[1], sys.argv[2] if self.map_diff else None)
        self.table_header = get_table_header(self.map_diff)
        self.show_debug = False
        self.show_debug_button = UnfocusableButton(self.get_show_debug_label(), id='show_debug')
        self.hide_show_debug_sections()

        super().__init__()

    def compose(self) -> ComposeResult:
        # yield Checkbox("Grumman", True)
        yield MyHeader(self.show_debug_button)
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = 'row'
        table.zebra_stripes = True
        table.fixed_rows = 1
        table.add_columns(*get_stylized_table_header(*self.table_header))
        self.reset_table()

    async def _on_message(self, message: Message) -> None:
        message_class = message.__class__.__name__
        if message_class == 'RowLabelSelected':
            self.notify(
                'Can not implement expand/collapse on click - see issue https://github.com/Textualize/textual/issues/4470',
                title="!!!Use keybord arrows and space!!!",
                severity="warning",
            )
        elif message_class == 'HeaderSelected':
            self.table_data.sort(message.column_index)
            self.reset_table()

        await super()._on_message(message)

    def collect_rows(self, data):
        rows = []
        for i, c in enumerate(data.children):
            if c.hidden:
                continue
            value_tuple = get_stylized_table_row(c)
            if not self.map_diff:
                value_tuple = value_tuple[0:3]
            rows.append([value_tuple, c])
            if c.expand:
                rows += self.collect_rows(c)
        return rows

    def reset_table(self):
        total_row = get_stylized_table_row(self.table_data)
        if not self.map_diff:
            total_row = total_row[0:3]
        rows = [(total_row, self.table_data)] + self.collect_rows(self.table_data)
        table = self.query_one(DataTable)
        scroll_x = table.scroll_x
        scroll_y = table.scroll_y
        scroll_target_x = table.scroll_target_x
        scroll_target_y = table.scroll_target_y
        table.clear()
        for i, (r, k) in enumerate(rows):
            table.add_row(*r, key=k, label=get_stylized_row_label(k))
        table.scroll_x = scroll_x
        table.scroll_y = scroll_y
        table.scroll_target_x = scroll_target_x
        table.scroll_target_y = scroll_target_y

    def collapse_expand_node(self, expand=None) -> None:
        table = self.query_one(DataTable)
        cursor_coordinate = table.cursor_coordinate
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value.is_root():
            return
        if expand == None:
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
            row_key.value.set_expand(expand)
        self.reset_table()
        table.cursor_coordinate = cursor_coordinate

    def action_right_arrow_key(self) -> None:
        self.collapse_expand_node(True)

    def action_left_arrow_key(self) -> None:
        self.collapse_expand_node(False)

    def action_space_key(self) -> None:
        self.collapse_expand_node()

    def get_show_debug_label(self) -> str:
        return f'[{"X" if self.show_debug else " "}] Debug sections'

    @on(Button.Pressed, "#show_debug")
    def show_debug_pressed(self) -> None:
        self.show_debug = not self.show_debug
        self.show_debug_button.label = self.get_show_debug_label()
        self.hide_show_debug_sections()
        self.reset_table()

    def hide_show_debug_sections(self):
        for k in self.table_data.children:
            if k.value.name.startswith(tuple(TableApp.DEBUG_SECTIONS)):
                k.hidden = not self.show_debug

def main():
    app = TableApp()
    app.run()

if __name__ == "__main__":
    main()
