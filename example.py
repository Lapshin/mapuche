#!/usr/bin/env python3

from itertools import cycle

from textual.app import App, ComposeResult
from tree_table import DataTable

ROWS = [
    ("lane", "swimmer", "country", "time"),
    ('1', "Joseph Schooling", "Singapore", 50.39),
    ([
        ('1', "Michael Phelps", "United States", 51.14),
        ('1', "Chad le Clos", "South Africa", 51.14),
    ([
        ('1', "Michael Phelps", "United States", 51.14),
        ('1', "Chad le Clos", "South Africa", 51.14),
        ('1', "László Cseh", "Hungary", 51.14)
    ]),
        ('1', "László Cseh", "Hungary", 51.14)
    ]),
    ('2', "Li Zhuhao", "China", 51.26),
    ('3', "Mehdy Metella", "France", 51.58),
    ('4', "Tom Shields", "United States", 51.73),
    ('5', "Aleksandr Sadovnikov", "Russia", 51.84),
    ('6', "Darren Burns", "Scotland", 51.84),
]

cursors = cycle(["column", "row", "cell"])


class TableApp(App):
    def compose(self) -> ComposeResult:
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = next(cursors)
        table.zebra_stripes = True
        table.add_columns(*ROWS[0])
        table.add_rows(ROWS[1:])

    def key_c(self):
        table = self.query_one(DataTable)
        table.cursor_type = next(cursors)


app = TableApp()
if __name__ == "__main__":
    app.run()
