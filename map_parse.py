#!/usr/bin/env python

import sys

sections = []

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
    # insert section name to section[i].name
    return {'name': name, 'address': split[0], 'size': split[1], 'source': split[2] if len(split) == 3 else None, 'entries': []}


def convert_to_textual_rows(json_data):
    rows = [tuple(['name', 'address', 'size', 'source'])]
    for entry in json_data:
        rows.append(tuple([entry['name'], entry['address'], entry['size'], entry['source'] or '']))
        if len(entry['entries']) > 0:
            rows += tuple([convert_to_textual_rows(entry['entries'])])
    return rows
    

def parse_map_file(map_file):
    # open file in argv[0] and read until string "Linker script and memory map"
    # array of sections. Contains section name, address and size
    parse = False
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
                sections.append(parse_mapfile_entry(f, line))
            elif line.startswith(' .'):
                # append last sections element with entry
                sections[-1]['entries'].append(parse_mapfile_entry(f, line))
    # print pretty json
    #for s in sections:
    #    print(f'{s["name"]} = {len(s["entries"])}')
    # import json
    # print(json.dumps(sections, indent=4))

    return convert_to_textual_rows(sections)

if __name__ == "__main__":
    # input argument argv[1] is a file name

    if len(sys.argv) != 2:
        print("Wrong number of arguments. Please provide two files.")
        exit()  # exit the program
    rows = parse_map_file(sys.argv[1])
    print(rows[:10])
