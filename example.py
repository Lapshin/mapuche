#!/usr/bin/env python3

from itertools import cycle
from os import sys
from textual.app import App, ComposeResult
from tree_table import DataTable
from map_parse import parse_map_file

cursors = cycle(["column", "row", "cell"])


class TableApp(App):
    def compose(self) -> ComposeResult:
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = next(cursors)
        table.zebra_stripes = True
        rows = parse_map_file(sys.argv[1])
        table.add_columns(*rows[0])
        table.add_rows(rows[1:])

    def key_c(self):
        table = self.query_one(DataTable)
        table.cursor_type = next(cursors)


app = TableApp()
if __name__ == "__main__":
    app.run()
