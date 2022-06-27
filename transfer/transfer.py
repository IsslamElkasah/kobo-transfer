import glob
import io
import json
import os
import requests
import uuid
from datetime import datetime
from xml.etree import ElementTree as ET

from .media import get_media, del_media
from helpers.config import Config


def get_submission_edit_data():
    config = Config().new
    _v_, v = get_info_from_deployed_versions()
    data = {
        'asset_uid': config['asset_uid'],
        'version': v,
        '__version__': _v_,
        'formhub_uuid': get_formhub_uuid(),
    }
    return data


def get_old_submissions_xml(xml_url):
    config = Config().old
    res = requests.get(
        url=xml_url, headers=config['headers'], params=config['params']
    )
    if not res.status_code == 200:
        raise Exception('Something went wrong')
    return ET.fromstring(res.text)


def submit_data(xml_sub, _uuid):
    config = Config().new

    file_tuple = (_uuid, io.BytesIO(xml_sub))
    files = {'xml_submission_file': file_tuple}

    # see if there is media to upload with it
    submission_attachments_path = os.path.join(
        Config.TEMP_DIR, Config().old['asset_uid'], _uuid, '*'
    )
    for file_path in glob.glob(submission_attachments_path):
        filename = os.path.basename(file_path)
        files[filename] = (filename, open(file_path, 'rb'))

    res = requests.Request(
        method='POST',
        url=config['submission_url'],
        files=files,
        headers=config['headers'],
    )
    session = requests.Session()
    res = session.send(res.prepare())
    return res.status_code


def update_element_value(e, name, value):
    """
    Get or create a node and give it a value, even if nested within a group
    """
    el = e.find(name)
    if el is None:
        if '/' in name:
            root, node = name.split('/')
            el = ET.SubElement(e.find(root), node)
        else:
            el = ET.SubElement(e, name)
    el.text = value


def update_root_element_tag_and_attrib(e, tag, attrib):
    """
    Update the root of each submission's XML tree
    """
    e.tag = tag
    e.attrib = attrib


def transfer_submissions(all_submissions_xml, asset_data, quiet):
    results = []
    for submission_xml in all_submissions_xml:
        # Use the same UUID so that duplicates are rejected
        _uuid = submission_xml.find('meta/instanceID').text.replace('uuid:', '')

        new_attrib = {
            'id': asset_data['asset_uid'],
            'version': asset_data['version'],
        }
        update_root_element_tag_and_attrib(
            submission_xml, asset_data['asset_uid'], new_attrib
        )
        update_element_value(
            submission_xml, '__version__', asset_data['__version__']
        )
        update_element_value(
            submission_xml, 'formhub/uuid', asset_data['formhub_uuid']
        )

        result = submit_data(ET.tostring(submission_xml), _uuid)
        if not quiet:
            if result == 201:
                print(f'✅ {_uuid}')
            elif result == 202:
                print(f'⚠️  {_uuid}')
            else:
                print(f'❌ {_uuid}')
        results.append(result)
    return results


def get_formhub_uuid():
    config = Config().new
    res = requests.get(
        url=config['forms_url'],
        headers=config['headers'],
        params=config['params'],
    )
    if not res.status_code == 200:
        raise Exception('Something went wrong')
    all_forms = res.json()
    latest_form = [
        f for f in all_forms if f['id_string'] == config['asset_uid']
    ][0]
    return latest_form['uuid']


def get_deployed_versions():
    config = Config().new
    res = requests.get(
        url=config['assets_url'],
        headers=config['headers'],
        params=config['params'],
    )
    if not res.status_code == 200:
        raise Exception('Something went wrong')
    data = res.json()
    return data['deployed_versions']


def format_date_string(date_str):
    """
    Format goal: "1 (2021-03-29 19:40:28)"
    """
    date, time = date_str.split('T')
    return f"{date} {time.split('.')[0]}"


def get_info_from_deployed_versions():
    """
    Get the version formats
    """
    deployed_versions = get_deployed_versions()
    count = deployed_versions['count']

    latest_deployment = deployed_versions['results'][0]
    date = latest_deployment['date_deployed']
    version = latest_deployment['uid']

    return version, f'{count} ({format_date_string(date)})'


def print_stats(results):
    total = len(results)
    success = results.count(201)
    skip = results.count(202)
    fail = total - success - skip
    print(f'🧮 {total}\t✅ {success}\t⚠️ {skip}\t❌ {fail}')


def main(limit, keep_media=False, quiet=False):
    config = Config().old

    print('📸 Getting all submission media', end=' ', flush=True)
    get_media()

    xml_url_old = config['xml_url'] + f'?limit={limit}'
    all_results = []
    submission_edit_data = get_submission_edit_data()

    print('📨 Transferring submission data')

    def do_the_stuff(all_results, url=None):
        parsed_xml = get_old_submissions_xml(xml_url=url)
        submissions = parsed_xml.findall(f'results/{config["asset_uid"]}')
        next_ = parsed_xml.find('next').text
        results = transfer_submissions(
            submissions, submission_edit_data, quiet=quiet
        )
        all_results += results
        if next_ != 'None':
            do_the_stuff(all_results, next_)

    do_the_stuff(all_results, xml_url_old)

    if not keep_media:
        del_media()

    print('✨ Done')
    print_stats(all_results)
