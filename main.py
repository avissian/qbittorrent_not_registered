import http.client as http_client
import json
import logging
import os
from urllib.parse import urlencode

import qbittorrentapi
import requests

debug = False

if debug:
    http_client.HTTPConnection.debuglevel = 1

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def rutracker_auth(config):
    headers = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded'}

    payload = urlencode(
        query={"login_username": config["rutracker"]["user"],
               "login_password": config["rutracker"]["password"],
               "login": "жопа"},
        encoding="windows-1251")
    session = requests.Session()

    if config["proxy"]:
        proxy = {"http": config["proxy"]}
        proxy["https"] = proxy["http"]
        session.proxies = proxy

    session.verify = False

    session.post('https://rutracker.org/forum/login.php', headers=headers, data=payload)
    return session


def download_torrent(torrend_id, session):
    url = "https://rutracker.org/forum/dl.php?t=" + torrend_id
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = session.get(url, allow_redirects=True, headers=headers)
    with open(torrend_id + '.torrent', 'wb') as torr_file:
        for chunk in resp.iter_content(chunk_size=1024):
            torr_file.write(chunk)
            torr_file.flush()
            os.fsync(torr_file.fileno())


def get_topic_data(external_torrent_id, session):
    url = "http://api.rutracker.org/v1/get_tor_topic_data?by=topic_id&val=" + external_torrent_id
    try:
        resp = session.get(url, allow_redirects=True, verify=False)
    except:
        print("Cant proccess id: ", external_torrent_id)
        return ''
    topic_data = json.loads(resp.content.decode("utf-8"))
    try:
        topic_data_id = topic_data['result'][external_torrent_id]['forum_id']
    except:
        return None
    return topic_data_id


def get_torrent_cat(forum_id, session):
    url = "http://api.rutracker.org/v1/get_forum_data?by=forum_id&val=" + str(forum_id)
    try:
        resp = session.get(url, allow_redirects=True, verify=False)
    except:
        print("Cant proccess id: ", forum_id)
        return ''
    category = json.loads(resp.content.decode("utf-8"))
    category_name = category['result'][str(forum_id)]['forum_name']
    return category_name


def proccess_torrent(torrent, qbt_client, session):
    torrent_info = qbt_client.torrents_properties(torrent.hash)
    torrent_external_id = torrent_info.comment.split("=")[-1]
    print(torrent.name, ":\n\tPath:", torrent.save_path, "\n\tExternal id:", torrent_external_id)

    download_torrent(torrent_external_id, session)
    topic_data_id = get_topic_data(torrent_external_id, session)
    if not topic_data_id:
        return False
    category_name = get_torrent_cat(topic_data_id, session)
    qbt_client.torrents_add(torrent_files="./" + torrent_external_id + '.torrent', save_path=torrent.save_path,
                            category=category_name)
    os.remove("./" + torrent_external_id + '.torrent')
    return True


def check_torrent_registration(torrent, qbt_client):
    torrent_info_list = qbt_client.torrents_trackers(torrent.hash)
    for torrent_info in torrent_info_list:
        torrent_dict = dict(torrent_info)
        logging.info(torrent_dict)
        if torrent_dict["msg"] == "Torrent not registered":
            print("Found unregistered torrent: ", torrent.name)
            return torrent
    return None


def main():
    with open('config.json', 'r') as f:
        config = json.load(f)
    session = rutracker_auth(config)

    for client in config["qbt"]["clients"]:
        qbt_client = qbittorrentapi.Client(
            host=client["host"],
            port=client["port"],
            username=client["login"],
            password=client["password"],
            REQUESTS_ARGS={'timeout': (300, 300)}  # timeout (connect, read response)
        )
        print("Processing client: ", client["host"], ":", client["port"])
        try:
            qbt_client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            print(e)
        print(f'qBittorrent: {qbt_client.app.version}')
        print(f'qBittorrent Web API: {qbt_client.app.web_api_version}')
        for torrent in qbt_client.torrents_info():
            unregistered = check_torrent_registration(torrent, qbt_client)
            if unregistered:
                ok = proccess_torrent(torrent, qbt_client, session)
                if ok:
                    qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent.hash)
                    print("Removed old torrent: ", torrent.name)


if __name__ == '__main__':
    if debug:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True
    #
    main()
