from .models import MapValue, TreeNode

def parse_lib_and_objfile(source):
    if source == None:
        return (None, None)
    objfile = None

    lib_end = source.rfind('(')
    if lib_end > 0:
        objfile = source[lib_end + 1:-1]
    else:
        lib_end = len(source)
    lib_start = source.rfind('/') + 1
    lib = source[lib_start:lib_end]
    return (lib, objfile)


def parse_mapfile_entry(f, line):
    split = line.split()
    name = split[0]
    split.pop(0)
    if f and len(split) == 0:
        line = f.readline()
        split = line.split()

    if len(split) == 1:
        return None

    try:
        address = split[0]
        size = split[1]
        source = split[2] if len(split) == 3 else None
        return MapValue(name, address, size, source)
    except (IndexError, ValueError):
        # address or size is not a number
        return None


def set_size_for_all_nodes(data):
    size = 0
    for c in data.children:
        size += set_size_for_all_nodes(c) or 0
    if not data.value.size:
        data.value.size = size
    return data.value.size or 0


def parse_map_file(map_file):
    sections = TreeNode(MapValue())
    parse = False
    root_entry_name = ''
    last_address = None
    cur_parrent = None
    prev_symbol = None
    remain_section_size = -1
    with open(map_file, 'r') as f:
        while True:
            line = f.readline()
            if not line:
                break
            if not parse:
                if "Linker script and memory map" in line:
                    while not line.startswith('.'):  # Skip unwanted data, go to the first section
                        line = f.readline()
                    parse = True
                continue
            if "Cross Reference Table" in line:
                break

            if line.startswith('.'):
                is_root_entry = True
            elif line.startswith(' .'):
                is_root_entry = False
            elif line.lstrip().startswith('0x'):
                # Symbol size is the distance to the next symbol. The last
                # symbol in a section keeps whatever size is still unaccounted.
                split = line.split()
                if len(split) != 2 or cur_parrent is None:
                    continue
                map_entry = MapValue(split[1], split[0], None, None)

                if prev_symbol is not None:
                    prev_symbol_size = map_entry.address - prev_symbol.address
                    if prev_symbol_size < 0:
                        prev_symbol_size = 0
                    if remain_section_size >= 0 and prev_symbol_size > remain_section_size:
                        prev_symbol_size = remain_section_size
                    prev_symbol.size = prev_symbol_size
                    remain_section_size -= prev_symbol_size

                cur_parrent.add_child(map_entry)
                prev_symbol = map_entry
                continue
            else:
                continue

            map_entry = parse_mapfile_entry(f, line)
            if map_entry is None:
                continue

            if prev_symbol is not None:
                if prev_symbol.size is None:
                    prev_symbol.size = remain_section_size if remain_section_size > 0 else 0
                remain_section_size = -1

            if is_root_entry:
                root_entry_name = map_entry.name
                sections.add_child(map_entry)
            else:
                lib, obj_file = parse_lib_and_objfile(map_entry.source)
                root_prev = sections.find_child_by_name(root_entry_name)
                # A loose .obj has no archive member. Skip that level instead of
                # inserting a node whose name is None.
                if lib:
                    root = root_prev.find_child_by_name(lib)
                    if root == None:
                        root = root_prev.add_child(MapValue(lib))
                    root_prev = root
                if obj_file:
                    found = root_prev.find_child_by_name(obj_file)
                    if found == None:
                        found = root_prev.add_child(MapValue(obj_file))
                    root_prev = found
                cur_parrent = root_prev.add_child(map_entry)
                remain_section_size = cur_parrent.value.size
            prev_symbol = None
    if prev_symbol is not None and prev_symbol.size is None:
        prev_symbol.size = remain_section_size if remain_section_size > 0 else 0
    set_size_for_all_nodes(sections)
    return sections


def generate_diff_table(map_1, map_2):
    sections_diff = TreeNode(MapValue())
    m1 = parse_map_file(map_1)
    m2 = parse_map_file(map_2)
    _collect_diff(sections_diff, 'Total', m1, m2)
    return sections_diff

def _collect_diff(diff_entry, leaf, m1, m2):
    has_diff = False
    children_to_add = get_all_childs(m1, m2)
    for entry_name in children_to_add:
        child = diff_entry.add_child(MapValue(entry_name))
        _collect_diff(child, entry_name, m1.find_child_by_name(entry_name) if m1 else None, m2.find_child_by_name(entry_name) if m2 else None)

    s1 = m1.value.size if m1 else 0
    s2 = m2.value.size if m2 else 0
    has_diff = s1 != s2

    if not has_diff:
        # Totals can match while children still differ. Keep this node then.
        # The root has no parent, so it cannot be removed.
        if diff_entry.children or diff_entry.parent is None:
            diff_entry.value.size = s1
            diff_entry.value.address = m1.value.address if m1 else (m2.value.address if m2 else 0)
            diff_entry.value.source = m1.value.address if m1 else (m2.value.address if m2 else 0)
            diff_entry.value.diff = 0
            diff_entry.value.delta = 0
            diff_entry.value.address_a = m1.value.address if m1 else 0
            diff_entry.value.size_a = s1 or 0
            diff_entry.value.address_b = m2.value.address if m2 else 0
            diff_entry.value.size_b = s2 or 0
            return False
        diff_entry.parent.remove_child_by_name(diff_entry.value.name)
        return False

    diff_entry.value.size = s1
    diff_entry.value.address = m1.value.address if m1 else m2.value.address
    diff_entry.value.source = m1.value.address if m1 else m2.value.address
    diff_entry.value.diff = s1 - s2
    diff_entry.value.delta = 100 if s2 == 0 else round((s1 - s2 ) / s2 * 100, 1)
    diff_entry.value.address_a = m1.value.address if m1 else 0
    diff_entry.value.size_a = s1 or 0
    diff_entry.value.address_b = m2.value.address if m2 else 0
    diff_entry.value.size_b = s2 or 0
    return True

def get_all_childs(m1, m2):
    result = []
    if m1:
        result.extend(c.value.name for c in m1.children)
    if m2:
        result.extend(c.value.name for c in m2.children)
    return list(dict.fromkeys(result))

def get_table_data(map_file_1, map_file_2):
    if map_file_2 != None:
        return generate_diff_table(map_file_1, map_file_2)
    return parse_map_file(map_file_1)        

def get_table_header(map_diff):
    if map_diff:
        return [tuple(['name', 'address', 'size', 'diff', 'delta'])]
    return [tuple(['name', 'address', 'size'])]
