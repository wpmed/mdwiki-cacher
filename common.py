# common functions
import sys
import requests
import json
from datetime import datetime

def is_medicine_tsv_avail():
    # e.g. http://download.openzim.org/wp1/enwiki_2022-03/customs/medicine.tsv
    url = 'http://download.openzim.org/wp1/enwiki_'
    url += datetime.now().strftime('%Y-%m')
    url += '/customs/medicine.tsv'

    r = requests.head(url)
    if r.status_code == 200:
        return True
    else:
        return False

def zimfarm_running(recipe):
    stat = get_zimfarm_stat(recipe)
    if stat['most_recent_task']['status'] == 'scraper_started':
        return True
    else:
        return False

def get_zimfarm_stat(recipe):
    # status of current run in ['most_recent_task']['status']
    zimfarm_api = 'https://api.farm.openzim.org/v1/schedules/'
    r = requests.get(zimfarm_api + recipe)
    return r.json()

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

def read_file_list(file_path):
    text = read_file(file_path)
    text_list = text.split('\n')[:-1]
    return text_list

def read_file(file_path, mode='rt'):
    try:
        with open(file_path, mode) as f:
            return f.read()
    except OSError as e:
        print('Unable to read file', e)
        raise