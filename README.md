# mapuche

Mapuche is a linker's map file browser

If you are reading this, please don't forget to give this project a star on GitHub!

> [!CAUTION]
> Mapuche is in pre-alfa development stage. Crashes or unexpected output may occur! Please create an issue if any.


## Install

```
pip install mapuche
```

## Usage

> [!IMPORTANT]
> For now mapuche supports only map files of ELFs generated with `-ffunction-sections` and `-fdata-sections` compile options.

```
mapuche <elf.map> [elf_for_diff.map]
mapuche --help
mapuche --version
```

- Use keyboard arrows and the space bar, or a mouse, to navigate the map tree.
- Click table header columns to sort the table.
- Show/hide debug sections using checkbox at the top.
- Demangle C++ names using checkbox at the top (on by default).
- Press `a` to open an assembler diff for the selected row. This is available when the ELF named by `OUTPUT()` in the map file is on disk. `objdump` is taken from the toolchain `bin` directory recorded on the `libc.a` path; if that binary is missing, mapuche asks for a path. The viewer has checkboxes to show instruction addresses and to interleave source code (`objdump -S`). A data, rodata, or other non-code section opens a hex diff of the ELF bytes instead.

## Screenshot

![mapuche diff maps](https://raw.githubusercontent.com/Lapshin/mapuche/master/imgs/mapuche_diff_demo.png)

## TODO list

- [x] implement `--help`/`--version` 
- [x] copy cell content (press Shift and select using mouse as you would in other terminal apps.)
- [ ] regex filters
- [ ] map diff: highlight reduced sections with green and red otherwise (also, add shortcut "hide reduced")
- [x] button that hides debug sections
- [x] columns sort
- [x] support expand/collapse by left/right arrows and space button
- [ ] move input section name from "name" to separate column
- [x] cute alignment for `size`/`diff`/`delta` columns
- [x] assembler diff viewer in popup widget
- [ ] support map files for ELFs without `-ffunction-sections`/`-fdata-sections`
- [x] reduce startup time
- [ ] screenshot/copy all table
- [x] C++ demangling
- [x] tests (`python -m unittest discover -s tests`)
