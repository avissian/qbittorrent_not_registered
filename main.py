import http.client as http_client
import json
import logging
import os
import time

import qbittorrentapi

from api_rt import Rutracker
from api_tlg import send_tlg

debug = False

if debug:
    http_client.HTTPConnection.debuglevel = 1


def process_torrent(torrent: qbittorrentapi.TorrentDictionary,
                    tor_topic_data: dict,
                    torrent_id: str,
                    qbt_client: qbittorrentapi.Client,
                    rutracker: Rutracker,
                    forum_categories: dict,
                    dry_run=False
                    ):
    msg = "%s\n\tPath: %s\n\tExternal id: %s" % (torrent.name, torrent.save_path, torrent_id)
    logging.info(msg)
    print(msg)

    file_name = rutracker.download_torrent(torrent_id)

    # Категория с торрента, или если нет - тема форума
    category_name = torrent.get("category") or forum_categories.get(tor_topic_data.get("forum_id"))

    if dry_run:
        logging.warning(f"\t(dry run) add torrent: {torrent.name} "
                        f"save_path={torrent.save_path} "
                        f"category={category_name}")
    else:
        ok = qbt_client.torrents_add(torrent_files=file_name,
                                     save_path=torrent.save_path,
                                     category=category_name)

        if ok == "Ok.":
            os.remove(f"./{torrent_id}.torrent")
        else:
            logging.warning(f"Ошибка добавления торрента {torrent_id}.torrent, статус ответа '{ok}'")
            return False
    return True


def main():
    with open("config.json", "r") as f:
        config = json.load(f)

    rutracker = Rutracker(
        user=config["rutracker"]["user"],
        password=config["rutracker"]["password"],
        api_key=config["rutracker"]["api_key"],
        proxy=config.get("proxy"),
        forum_url=config["rutracker"]["urls"]["forum"],
        api_url=config["rutracker"]["urls"]["api"],
        proxy_for_api=config.get("proxy_for_api"),
    )

    for client in config["qbt"]["clients"]:
        new_torrents = []
        bad_status = []
        qbt_client = qbittorrentapi.Client(
            host=client["host"],
            port=client["port"],
            username=client["login"],
            password=client["password"],
            REQUESTS_ARGS={"timeout": (300, 300)}  # timeout (connect, read response)
        )
        msg = f"Подключение к клиенту: {client['host']}:{client['port']}"
        logging.info(msg)
        print(msg)

        try:
            qbt_client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            logging.error(e)
            continue
        msg = f"Подключились, qBittorrent: {qbt_client.app.version} Web API: {qbt_client.app.web_api_version}"
        logging.info(msg)
        print(msg)

        # получаем список раздач из кубита
        print("Получаем список раздач")
        torrents_info = qbt_client.torrents_info()
        # чуть больше инфы по раздачам из кубита
        print("Получение расширенной информации по раздачам")
        torrents_prop = [qbt_client.torrents_properties(torrent.hash) for torrent in torrents_info]

        print("Обрабатываем данные")
        # исходные хеши раздач (для поиска новых и удалённых раздач)
        source_hashes = [x.hash for x in torrents_info]
        # вытащим ID раздач форума из коммента
        torrents_ids = [x.comment.split("=")[-1] for x in torrents_prop]

        print("Получаем из API данные по раздачам")
        tor_topic_data = rutracker.get_tor_topic_data(torrents_ids)

        print("Обрабатываем данные от API")
        # Список всех forum_id
        forum_ids = list(set(str(tor_topic_data.get(x, {}).get("forum_id")) for x in tor_topic_data
                             if tor_topic_data.get(x) and tor_topic_data.get(x, {}).get("forum_id")))
        # Категории с форума
        print("Получаем из API данные по категориям")
        forum_categories = rutracker.get_forum_data(forum_ids)

        print("Ищем обновившиеся раздачи")
        for idx, torrent in enumerate(torrents_info):
            torrent_id = torrents_ids[idx]
            tor_api_data = tor_topic_data.get(torrent_id)

            if tor_api_data:
                # Перекачиваем только для статусов по списку
                if tor_api_data.get("tor_status") in [0, 2, 3, 4, 8, 9, 10]:
                    if tor_api_data.get('info_hash') != torrent.infohash_v1.upper():
                        logging.debug("Хеш раздачи изменился, перекачаем")

                        new_torrents.append(torrent.name)

                        ok = process_torrent(torrent=torrent,
                                             torrent_id=torrent_id,
                                             tor_topic_data=tor_api_data,
                                             qbt_client=qbt_client,
                                             rutracker=rutracker,
                                             forum_categories=forum_categories,
                                             dry_run=config["dry_run"],
                                             )
                        if ok:
                            if config["dry_run"]:
                                logging.warning("\t(dry run) Removed old torrent: %s" % (torrent.name,))
                            else:
                                qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent.hash)
                                msg = f"Removed old torrent: {torrent.name}"
                                logging.info(msg)
                                print(msg)
                else:
                    logging.debug(f'Статус торрента {tor_api_data.get("tor_status")} - '
                                  f'"{rutracker.statuses.get(int(tor_api_data.get("tor_status")))}"'
                                  f' имя: {torrent.name}')
                    bad_status.append(f'{tor_api_data.get("tor_status")} - '
                                      f'"{rutracker.statuses.get(int(tor_api_data.get("tor_status")))}"'
                                      f' имя: {torrent.name}')
            else:
                msg = f'Торрент не найден в ответе API: {torrent.name}'
                logging.info(msg)
                print(msg)

        # уведомление в телеграм
        cfg_telegram = config.get("telegram")
        if cfg_telegram and cfg_telegram.get("receiver_user_id"):
            client_name = client["host"] + ":" + str(client["port"])
            if len(new_torrents):
                send_tlg(
                    cfg_telegram.get("sender_bot_token"),
                    cfg_telegram.get("receiver_user_id"),
                    client_name + ": Перекачанные раздачи:",
                    new_torrents
                )
            if len(bad_status) > 0:
                send_tlg(
                    cfg_telegram.get("sender_bot_token"),
                    cfg_telegram.get("receiver_user_id"),
                    client_name + ': "Плохие" статусы раздач:',
                    bad_status
                )
        print("***")

    logging.debug("Выход")


if __name__ == "__main__":
    try:
        os.mkdir("./logs")
    except FileExistsError:
        pass

    logger = logging.getLogger()

    logger.setLevel(logging.DEBUG)

    f_handler = logging.FileHandler("./logs/" + time.strftime("%y%m%d-%H%M.log"), encoding="utf-8")
    f_formatter = logging.Formatter(u"%(filename)-.10s[Ln:%(lineno)-3d]%(levelname)-8s[%(asctime)s]|%(message)s")
    f_handler.setFormatter(f_formatter)
    f_handler.setLevel(logging.DEBUG)
    logger.addHandler(f_handler)
    #
    main()
