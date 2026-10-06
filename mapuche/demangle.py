from cxxfilt import Error, InvalidName, demangle

_cache = {}


def demangle_map_name(name: str) -> str:
    """Demangle Itanium C++ symbols embedded in a map-file name.

    Section names look like ``.text._ZN3Foo3barEv`` or
    ``.rodata._ZNK3Foo4whatEv.str1.4``. The mangled token is replaced in
    place; prefixes and GCC suffixes stay. Names are not mutated by the caller.
    """
    cached = _cache.get(name)
    if cached is not None:
        return cached
    if "_Z" not in name:
        _cache[name] = name
        return name

    parts = name.split(".")
    changed = False
    for i, part in enumerate(parts):
        z = part.find("_Z")
        if z < 0:
            continue
        mangled = part[z:]
        try:
            demangled = demangle(mangled)
        except InvalidName:
            continue
        except Error:
            _cache[name] = name
            return name
        if demangled != mangled:
            parts[i] = part[:z] + demangled
            changed = True

    result = ".".join(parts) if changed else name
    _cache[name] = result
    return result
