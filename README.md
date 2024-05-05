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
```

## Screenshot

![mapuche diff maps](./imgs/mapuche_diff_demo.png)

## TODO list

- [ ] implement `--help`/`--version` 
- [ ] regex filters
- [ ] columns sort
- [ ] support expand/collapse by space button
- [ ] move input section name from "name" to separate column
- [ ] cute alignment for `size`/`diff`/`delta` columns
- [ ] assembler diff viewer in popup widget
- [ ] support map files for ELFs without `-ffunction-sections`/`-fdata-sections`
- [ ] tests
