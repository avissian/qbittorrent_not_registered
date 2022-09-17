import http.client as http_client
import json
import logging
import os
from urllib.parse import urlencode

import qbittorrentapi
import requests

debug = False
api_url = "http://api.rutracker.org"
forum_url = "https://rutracker.org"

if debug:
    http_client.HTTPConnection.debuglevel = 1

# noinspection PyUnresolvedReferences
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def rutracker_auth(config):
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}

    payload = urlencode(
        query={"login_username": config["rutracker"]["user"],
               "login_password": config["rutracker"]["password"],
               "login": "жопа"},
        encoding="windows-1251")
    session = requests.Session()

    if config.get("proxy"):
        proxy = {"http": config["proxy"]}
        proxy["https"] = proxy["http"]
        session.proxies = proxy

    session.verify = False

    session.post(forum_url + "/forum/login.php", headers=headers, data=payload)
    return session


def download_torrent(torrent_id, session):
    url = forum_url + "/forum/dl.php?t=" + torrent_id
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = session.get(url, allow_redirects=True, headers=headers)
    with open(torrent_id + ".torrent", "wb") as torr_file:
        for chunk in resp.iter_content(chunk_size=1024):
            torr_file.write(chunk)
            torr_file.flush()
            os.fsync(torr_file.fileno())


def get_topic_data(external_torrent_id, session):
    url = api_url + "/v1/get_tor_topic_data?by=topic_id&val=" + external_torrent_id
    try:
        resp = session.get(url, allow_redirects=True, verify=False)
    except:
        print("Cant process id: ", external_torrent_id)
        return None
    topic_data = json.loads(resp.content.decode("utf-8"))
    try:
        topic_data_id = topic_data["result"][external_torrent_id]["forum_id"]
    except:
        return None
    return topic_data_id


def get_torrent_cat(forum_id, session):
    url = api_url + "/v1/get_forum_data?by=forum_id&val=" + str(forum_id)
    try:
        resp = session.get(url, allow_redirects=True, verify=False)
    except:
        print("Cant process id: ", forum_id)
        return ""

    category = json.loads(resp.content.decode("utf-8"))
    category_name = category["result"][str(forum_id)]["forum_name"]
    return category_name


def process_torrent(torrent: qbittorrentapi.TorrentDictionary, qbt_client: qbittorrentapi.Client,
                    session: requests.Session, config):
    torrent_info = qbt_client.torrents_properties(torrent.hash)
    torrent_external_id = torrent_info.comment.split("=")[-1]
    print("\tPath:", torrent.save_path, "\n\tExternal id:", torrent_external_id)

    download_torrent(torrent_external_id, session)
    category_name = torrent.get("category")
    if not category_name:
        topic_data_id = get_topic_data(torrent_external_id, session)
        if not topic_data_id:
            return False
        category_name = get_torrent_cat(topic_data_id, session)

    if config["dry_run"]:
        print("\t(dry run) add torrent: " + torrent.name)
    else:
        ok = qbt_client.torrents_add(torrent_files=f"./{torrent_external_id}.torrent",
                                     save_path=torrent.save_path,
                                     category=category_name)

        if ok == "Ok.":
            os.remove(f"./{torrent_external_id}.torrent")
        else:
            print(f"Ошибка добавления торрента {torrent_external_id}.torrent, статус ответа '{ok}'")
    return True


def check_torrent_registration(torrent: qbittorrentapi.TorrentDictionary, qbt_client: qbittorrentapi.Client,
                               session: requests.Session):
    if not torrent.get("infohash_v2"):
        torrent_trackers_list = qbt_client.torrents_trackers(torrent.hash)
        for torrent_info in torrent_trackers_list:
            torrent_dict = dict(torrent_info)
            logging.info(torrent_dict)
            if torrent_dict["msg"] == "Torrent not registered":
                print("Found unregistered torrent: ", torrent.name)
                return torrent
    else:  # гибридный торрент, проверим состояние по V1 hash вручную, потому что статус в кубите всегда ошибочный
        # print("Hybrid: " + torrent.name + ", check by API")
        return check_by_api(qbt_client, torrent, session)
    return None


def check_by_api(qbt_client: qbittorrentapi.Client, torrent: qbittorrentapi.TorrentDictionary,
                 session: requests.Session):
    torrent_info = qbt_client.torrents_properties(torrent.hash)
    forum_id = torrent_info.comment.split("=")[-1]
    url = api_url + "/v1/get_tor_hash?by=topic_id&val=" + forum_id
    try:
        resp = session.get(url, allow_redirects=True, verify=False)
    except:
        print("Cant process forum_id: ", forum_id)
        return None

    data = json.loads(resp.content.decode("utf-8"))
    hash_v1 = torrent.infohash_v1.upper()
    if hash_v1 != data["result"][forum_id].upper():
        return torrent
    return None


def send_tlg_msg(from_bot, to_user, text: str):
    """ Отправка текста в телеграм """
    # пробуем отправить сообщение
    params = {"chat_id": to_user,
              "text": text}
    if from_bot:
        response = requests.get(f"https://api.telegram.org/bot{from_bot}/sendMessage", params)
    else:
        response = requests.get("https://bot.keeps.cyou/PlanB", params)

    # обновляем файл с хешами только если отправилось сообщение
    if response.status_code != 200:
        print("Не удалось отправить сообщение в телеграм:", response.text)


def send_tlg(from_bot, to_user, header_text, msg_set):
    """ Отправка iterable в телеграм с разбивкой по длине до 4000 """
    if len(msg_set) > 0 and to_user:
        msg = header_text + "\n"
        for item in msg_set:
            if len(msg) + len(item) <= 4000:
                msg += item + "\n"
            else:
                send_tlg_msg(from_bot, to_user, msg)
                msg = item + "\n"
        send_tlg_msg(from_bot, to_user, msg)


def main():
    with open("config.json", "r") as f:
        config = json.load(f)
    session = rutracker_auth(config)

    for client in config["qbt"]["clients"]:
        unregistered_files = []
        added_files = []

        qbt_client = qbittorrentapi.Client(
            host=client["host"],
            port=client["port"],
            username=client["login"],
            password=client["password"],
            REQUESTS_ARGS={"timeout": (300, 300)}  # timeout (connect, read response)
        )
        print("Processing client: ", client["host"], ":", client["port"])
        try:
            qbt_client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            print(e)
        print(f"qBittorrent: {qbt_client.app.version} Web API: {qbt_client.app.web_api_version}\n")
        source_hashes = []
        for torrent in qbt_client.torrents_info():
            source_hashes.append(torrent.hash)  # для поиска добавленных хешей
            unregistered = check_torrent_registration(torrent, qbt_client, session)
            if unregistered:
                ok = process_torrent(torrent, qbt_client, session, config)
                if ok:
                    if config["dry_run"]:
                        print("\t(dry run) Removed old torrent: ", torrent.name)
                    else:
                        for file in qbt_client.torrents_files(torrent.hash):
                            unregistered_files.append(file.name)
                        qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent.hash)
                        print("Removed old torrent: ", torrent.name)

        new_hashes = [x.hash for x in qbt_client.torrents_info() if x.hash not in source_hashes]

        for tor_hash in new_hashes:
            for file in qbt_client.torrents_files(tor_hash):
                added_files.append(file.name)

        added_list = set(added_files) - set(unregistered_files)
        print("Добавленные файлы:", "\n\t" + "\n\t".join(added_list))

        orphans_list = set(unregistered_files) - set(added_files)
        if len(orphans_list) > 0:
            print("Файлы без торрентов:", "\n\t" + "\n\t".join(orphans_list))

        # уведомление в телеграм
        if config.get("telegram", {}).get("receiver_user_id"):
            client_name = client["host"] + ":" + str(client["port"])
            if len(added_list) > 0 and config["telegram"].get("notice_added_files"):
                send_tlg(
                    config["telegram"].get("sender_bot_token"),
                    config["telegram"].get("receiver_user_id"),
                    client_name + ": Добавленные файлы:",
                    added_list
                )
            if len(orphans_list) > 0 and config["telegram"].get("notice_orphaned_files"):
                send_tlg(
                    config["telegram"].get("sender_bot_token"),
                    config["telegram"].get("receiver_user_id"),
                    client_name + ": Файлы без торрентов:",
                    orphans_list
                )


if __name__ == "__main__":
    if debug:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True
    #
    main()
