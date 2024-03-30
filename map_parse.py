#!/usr/bin/env python

import sys

INFO = "*info*"  # TODO remove

sections = {}
sections_diff = {}

def pretty_print_dict(d):
    # print pretty json
    import json
    print(json.dumps(d, indent=4))

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
    # remove the first element from split
    split.pop(0)
    # check if one word in line
    if len(split) == 0:
        # read new line and print
        line = f.readline()
        split = line.split()

    if len(split) == 1:
        return None

    source = split[2] if len(split) == 3 else None

    return {'name': name, 'address': split[0], 'size': int(split[1], 16), 'source': source}


def convert_to_textual_rows(json_data, add_header=True):
    rows = []
    if add_header:
        rows += [tuple(['name', 'address', 'size', 'source'])]
    for k in json_data:
        entry = json_data[k]
        rows.append(tuple([entry['name'], entry['address'], entry['size'], entry['source'] or '']))
        if len(entry['entries']) > 0:
            rows += tuple([convert_to_textual_rows(entry['entries'], False)])
    return rows
    

def fill_all_fields_with_info(data):
    size = 0
    for k in data['entries']:
        size += fill_all_fields_with_info(data['entries'][k])

    if data['size'] == None:
        data['size'] = size
    return data['size']

def convert_diff_to_textual_rows(json_data, add_header=True):
    rows = []
    if add_header:
        rows += [tuple(['name', 'address', 'size', 'diff', 'delta'])]
    for k, v in json_data['entries'].items():
        rows.append(tuple([v['name'], v['address'], v['size'], v['diff'], v['delta']]))
        if len(v['entries']) == 0:
            continue
        rows += tuple([convert_diff_to_textual_rows(v, False)])
    return rows


def add_entry_to_entries(entries, name, entry=None):
    if name in entries:
        return

    if entry != None:
        entries[name] = entry
    else:
        entries[name] = {'name': name, 'address': None, 'size': None, 'source': None}
    entries[name]['entries'] = {}

def _parse_map_file(map_file):
    # open file in argv[0] and read until string "Linker script and memory map"
    # array of sections. Contains section name, address and size
    sections = {}
    parse = False
    root_entry_name = ''
    with open(map_file, 'r') as f:
        while True:
            line = f.readline()
            if not line:
                break
            if not parse:
                if "Linker script and memory map" in line:
                    parse = True
                continue
            if "Cross Reference Table" in line:
                break

            if line.startswith('.'):
                is_root_entry = True
            elif line.startswith(' .'):
                is_root_entry = False
            else:
                continue

            map_entry = parse_mapfile_entry(f, line)
            
            if map_entry is None:
                continue
            
            if is_root_entry:
                root_entry_name = map_entry['name']
                add_entry_to_entries(sections, root_entry_name, map_entry)
            else:
                # append last sections element with entry
                lib, obj_file = parse_lib_and_objfile(map_entry['source'])
                add_entry_to_entries(sections[root_entry_name]['entries'], lib)
                add_entry_to_entries(sections[root_entry_name]['entries'][lib]['entries'], obj_file)
                add_entry_to_entries(sections[root_entry_name]['entries'][lib]['entries'][obj_file]['entries'], map_entry['name'], map_entry)
    sections = {'name': 'total', 'size': 0, 'entries': sections}
    fill_all_fields_with_info(sections)
    return sections

def parse_map_file(map_file):
    p = _parse_map_file(map_file)
    return convert_to_textual_rows(p)

def get_all_entries_keys(d1, d2):
    result = []
    if not d1 is None:
        result += d1['entries'].keys()
    if not d2 is None:
        result += d2['entries'].keys()
    return list(dict.fromkeys(result))

def _collect_diff(diff_entries, leaf, m1, m2):
    has_diff = False

    diff_entries[leaf] = {'name': leaf, 'address': None, 'size': 0, 'diff': 0, 'delta': 0, 'source': None, 'entries': {}}

    for k in get_all_entries_keys(m1, m2):
        if m2 == None or not k in m2['entries']:
            has_diff |= _collect_diff(diff_entries[leaf]['entries'], k, m1['entries'][k], None)
            continue

        if m1 == None or not k in m1['entries']:
            has_diff |= _collect_diff(diff_entries[leaf]['entries'], k, None, m2['entries'][k])
            continue

        has_diff |= _collect_diff(diff_entries[leaf]['entries'], k, m1['entries'][k], m2['entries'][k])


    s1 = 0 if m1 == None else m1['size']
    s2 = 0 if m2 == None else m2['size']
    has_diff |= s1 != s2

    if not has_diff:
        del diff_entries[leaf]
        return has_diff

    reference = m1
    if m1 is None:
        reference = m2

    diff_entries[leaf]['name'] = reference['name']
    diff_entries[leaf]['size'] = s1
    diff_entries[leaf]['address'] = reference['address'] if 'address' in reference else None
    diff_entries[leaf]['source'] = reference['source'] if 'source' in reference else None
    diff_entries[leaf]['diff'] = s1 - s2
    diff_entries[leaf]['delta'] = 100 if s2 == 0 else round((s1 - s2 ) / s2 * 100, 1)

    return has_diff


def generate_diff_table(map_1, map_2):
    m1 = _parse_map_file(map_1)
    m2 = _parse_map_file(map_2)

    _collect_diff(sections_diff, 'total', m1, m2)

    return convert_diff_to_textual_rows(sections_diff['total'])


if __name__ == "__main__":
    if len(sys.argv) == 2:
        rows_file = parse_map_file(sys.argv[1])
        print(rows_file)
    elif len(sys.argv) == 3:
        rows_diff = generate_diff_table(sys.argv[1], sys.argv[2])
    else:
        print("Wrong number of arguments. Please provide one or two files.")
        exit()
