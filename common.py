# common functions
import sys
import json

# taken from sp_lib
def read_json_file(file_path):
    try:
        with open(file_path, 'r') as json_file:
            readstr = json_file.read()
            json_dict = json.loads(readstr)
        return json_dict
    except OSError as e:
        print('Unable to read url json file', e)
        raise

def write_json_file(src_dict, target_file, sort_keys=False):
    try:
        with open(target_file, 'w', encoding='utf8') as json_file:
            json.dump(src_dict, json_file, ensure_ascii=False, indent=2, sort_keys=sort_keys)
            json_file.write("\n")  # Add newline cause Py JSON does not
    except OSError as e:
        raise

def write_list(data, file):
    with open(file, 'w') as f:
        for d in data:
            f.write(d + '\n')

def read_file(file_path, mode='rt'):
    try:
        with open(file_path, mode) as f:
            return f.read()
    except OSError as e:
        print('Unable to read file', e)
        raise