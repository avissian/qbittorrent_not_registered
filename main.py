import http.client as http_client
import json
import logging
import os
import sys

import qbittorrentapi

from api_rt import Rutracker
from api_tlg import send_tlg

debug = False

if debug:
    http_client.HTTPConnection.debuglevel = 1


def process_torrent(torrent: qbittorrentapi.TorrentDictionary,
                    qbt_client: qbittorrentapi.Client,
                    rutracker: Rutracker,
                    config
                    ):
    torrent_info = qbt_client.torrents_properties(torrent.hash)
    torrent_external_id = torrent_info.comment.split("=")[-1]
    logging.info("\tPath:", torrent.save_path, "\n\tExternal id:", torrent_external_id)

    rutracker.download_torrent(torrent_external_id)
    category_name = torrent.get("category")
    if not category_name:
        topic_data = rutracker.get_tor_topic_data(torrent_external_id)
        if not topic_data:
            return False
        forum_id = topic_data[torrent_external_id]["forum_id"]
        forum_data = rutracker.get_forum_data(forum_id)
        category_name = forum_data[str(forum_id)]["forum_name"]

    if config["dry_run"]:
        logging.warning("\t(dry run) add torrent: ", torrent.name)
    else:
        ok = qbt_client.torrents_add(torrent_files=f"./{torrent_external_id}.torrent",
                                     save_path=torrent.save_path,
                                     category=category_name)

        if ok == "Ok.":
            os.remove(f"./{torrent_external_id}.torrent")
        else:
            logging.warning(f"Ошибка добавления торрента {torrent_external_id}.torrent, статус ответа '{ok}'")
    return True


def check_torrent_registration(torrent: qbittorrentapi.TorrentDictionary,
                               qbt_client: qbittorrentapi.Client,
                               rutracker: Rutracker
                               ):
    if not torrent.get("infohash_v2"):
        torrent_trackers_list = qbt_client.torrents_trackers(torrent.hash)
        for torrent_info in torrent_trackers_list:
            torrent_dict = dict(torrent_info)
            logging.info(torrent_dict)
            if torrent_dict["msg"] == "Torrent not registered":
                logging.info("Found unregistered torrent: ", torrent.name)
                return torrent
    else:  # гибридный торрент, проверим состояние по V1 hash вручную, потому что статус в кубите всегда ошибочный
        # print("Hybrid: " + torrent.name + ", check by API")
        return rutracker.check_by_api(qbt_client, torrent)
    return None


def main():
    with open("config.json", "r") as f:
        config = json.load(f)

    rutracker = Rutracker(user=config["rutracker"]["user"], password=config["rutracker"]["password"], api_key=config["rutracker"]["api_key"], proxy=config.get("proxy"))

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
        logging.info("Processing client: ", client["host"], ":", client["port"])

        try:
            qbt_client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            logging.error(e)
            continue

        logging.info(f"qBittorrent: {qbt_client.app.version} Web API: {qbt_client.app.web_api_version}\n")

        # получаем список раздач
        torrents_info = qbt_client.torrents_info()

        torrents_prop = [qbt_client.torrents_properties(torrent.hash) for torrent in torrents_info]
        torrents_id=[x.comment.split("=")[-1] for x in torrents_prop]

        logging.info(rutracker.get_tor_topic_data(torrents_id))

        sys.exit(0)

        source_hashes = []
        for torrent in qbt_client.torrents_info():
            source_hashes.append(torrent.hash)  # для поиска добавленных хешей
            unregistered = check_torrent_registration(torrent, qbt_client, rutracker)
            if unregistered:
                ok = process_torrent(torrent, qbt_client, rutracker, config)
                if ok:
                    if config["dry_run"]:
                        logging.warning("\t(dry run) Removed old torrent: ", torrent.name)
                    else:
                        for file in qbt_client.torrents_files(torrent.hash):
                            unregistered_files.append(torrent.save_path + os.path.sep + file.name)
                        qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent.hash)
                        logging.info("Removed old torrent: ", torrent.name)

        new_hashes = [(x.hash, x.save_path) for x in qbt_client.torrents_info() if x.hash not in source_hashes]

        for tor_hash in new_hashes:
            for file in qbt_client.torrents_files(tor_hash[0]):
                added_files.append(tor_hash[1] + os.path.sep + file.name)

        added_list = set(added_files) - set(unregistered_files)
        if len(added_list) > 0:
            logging.info("Добавленные файлы:", "\n\t" + "\n\t".join(added_list))

        orphans_list = set(unregistered_files) - set(added_files)
        if len(orphans_list) > 0:
            logging.info("Файлы без торрентов:", "\n\t" + "\n\t".join(orphans_list))

        # уведомление в телеграм
        cfg_telegram = config.get("telegram")
        if cfg_telegram and cfg_telegram.get("receiver_user_id"):
            client_name = client["host"] + ":" + str(client["port"])
            if len(added_list) > 0 and cfg_telegram.get("notice_added_files"):
                send_tlg(
                    cfg_telegram.get("sender_bot_token"),
                    cfg_telegram.get("receiver_user_id"),
                    client_name + ": Добавленные файлы:",
                    added_list
                )
            if len(orphans_list) > 0 and cfg_telegram.get("notice_orphaned_files"):
                send_tlg(
                    cfg_telegram.get("sender_bot_token"),
                    cfg_telegram.get("receiver_user_id"),
                    client_name + ": Файлы без торрентов:",
                    orphans_list
                )
        logging.debug("Выход")


if __name__ == "__main__":
    if debug or 1==1:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True
    #
    main()
