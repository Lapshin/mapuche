# mapuche

Mapuche is a linker's map file browser

If you are reading this, please don't forget to give this project a star on GitHub!

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
- Press `/` to filter rows with a regular expression. A row stays if its name matches, if a parent matches, or if a child does (parents open to show the match). Input sections also match their object path. Demangled and mangled names both match. An invalid pattern keeps the last valid one until it compiles. Enter or Escape returns to the table. Hidden debug sections, and fully reduced rows while "Hide reduced" is on, stay hidden.
- In a map diff, smaller sections are green and larger sections are red. Tick "Hide reduced" at the top to hide reduced sections. A shrunk section stays on screen when a child inside it grew.
- Press `a` to open an assembler diff for the selected row. This is available when the ELF named by `OUTPUT()` in the map file is on disk. `objdump` is taken from the toolchain `bin` directory recorded on the `libc.a` path; if that binary is missing, mapuche asks for a path. The viewer has checkboxes to show instruction addresses and to interleave source code (`objdump -S`). A data, rodata, or other non-code section opens a hex diff of the ELF bytes instead.

## Screenshot

![mapuche diff maps](https://raw.githubusercontent.com/Lapshin/mapuche/master/imgs/mapuche_diff_demo.png)
