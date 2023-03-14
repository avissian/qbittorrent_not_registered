#!/usr/bin/env python3
import http.client as http_client
import json
import logging
import os
import time

import qbittorrentapi
import torrent_parser
import yaml

from api_rt import Rutracker
from api_tlg import send_tlg

debug = False

if debug:
    http_client.HTTPConnection.debuglevel = 1


def get_file_list(torrent_file):
    res = []
    with open(torrent_file, 'br') as file:
        tor_data = torrent_parser.TorrentFileParser(file).parse()
        # кубит клеит имя раздачи, тоже приклеим для сравнения файлов
        iname = tor_data.get("info", {}).get("name")
        for ifile in tor_data.get("info", {}).get("files", []):
            res.append(os.path.join(iname, *ifile.get("path", [])))

    return res


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

    torrent_files = [os.path.join(torrent.save_path, x) for x in get_file_list(file_name)]

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
            msg = f"\t*** Ошибка добавления торрента {torrent_id}.torrent, статус ответа '{ok}'"
            logging.warning(msg)
            print(msg)
            return None
    return torrent_files


def migrate_config():
    if not os.path.exists('config.yml'):
        with open("config.json", "r") as f:
            cfg = json.load(f)
            cfg['dry run'] = cfg.pop('dry_run', False)
            cfg['delete lost files'] = cfg.pop('delete_lost_files', False)
            cfg['proxy for api'] = cfg.pop('proxy_for_api', False)
            cfg['telegram'] = cfg.get('telegram', {})
            cfg['telegram']['receiver user_id'] = cfg['telegram'].pop('receiver_user_id', None)
            cfg['telegram']['sender bot_token'] = cfg['telegram'].pop('sender_bot_token', None)

        with open("config.yml", 'w') as yml:
            yml.write(yaml.safe_dump(cfg))
        os.remove('config.json')


def main():
    migrate_config()

    # читаем конфиг
    with open('config.yml') as f:
        config = yaml.safe_load(f)

    rutracker = Rutracker(
        user=config["rutracker"]["user"],
        password=config["rutracker"]["password"],
        api_key=config["rutracker"]["api_key"],
        proxy=config.get("proxy"),
        forum_url=config["rutracker"]["urls"]["forum"],
        api_url=config["rutracker"]["urls"]["api"],
        proxy_for_api=config.get("proxy for api"),
    )

    new_files = []
    lost_files = []

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
        except Exception as e:
            logging.error(e)
            print("Ошибка, подробности в файле логов")
            continue
        msg = f"qBittorrent: {qbt_client.app.version} Web API: {qbt_client.app.web_api_version}"
        logging.info(msg)
        print(msg)

        # получаем список раздач из кубита
        print("Получаем список раздач")
        torrents_info = qbt_client.torrents_info()
        # чуть больше инфы по раздачам из кубита
        print("Получение расширенной информации по раздачам")
        torrents_prop = [qbt_client.torrents_properties(torrent.hash) for torrent in torrents_info]

        # вытащим ID раздач форума из коммента
        torrents_ids = [x.comment.split("=")[-1] for x in torrents_prop]

        print("Получаем из API данные по раздачам")
        tor_topic_data = rutracker.get_tor_topic_data(torrents_ids)

        # print("Обрабатываем данные от API")
        # Список всех forum_id
        forum_ids = list(set(str(tor_topic_data.get(x, {}).get("forum_id")) for x in tor_topic_data if tor_topic_data.get(x) and tor_topic_data.get(x, {}).get("forum_id")))
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
                    if tor_api_data.get('info_hash') != torrent.get('infohash_v1', torrent.hash).upper():
                        logging.debug("Хеш раздачи изменился, перекачаем")

                        new_torrents.append(torrent.name)

                        tor_files = process_torrent(torrent=torrent,
                                                    torrent_id=torrent_id,
                                                    tor_topic_data=tor_api_data,
                                                    qbt_client=qbt_client,
                                                    rutracker=rutracker,
                                                    forum_categories=forum_categories,
                                                    dry_run=config["dry run"],
                                                    )
                        if tor_files:
                            qbt_files = [os.path.join(torrent.save_path, x.name) for x in qbt_client.torrents_files(torrent.hash)]
                            l_lost_files = list(set(qbt_files) - set(tor_files))
                            l_new_files = list(set(tor_files) - set(qbt_files))
                            new_files.extend(l_new_files)
                            lost_files.extend(l_lost_files)
                            print('Lost files:', '\t\n'.join(l_lost_files))
                            print('New files:', '\t\n'.join(l_new_files))
                            if config["dry run"]:
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
                msg = f'({torrent.state}) Торрент не найден в ответе API: {torrent.name} {torrents_prop[idx].comment}'  # {torrent.magnet_uri}'
                logging.info(msg)
                print(msg)

        # уведомление в телеграм
        cfg_telegram = config.get("telegram")
        if cfg_telegram and cfg_telegram.get("receiver user_id"):
            client_name = client["host"] + ":" + str(client["port"])
            if len(new_torrents):
                send_tlg(
                    cfg_telegram.get("sender bot_token"),
                    cfg_telegram.get("receiver user_id"),
                    client_name + ": Перекачанные раздачи:",
                    new_torrents
                )
            if len(bad_status):
                send_tlg(
                    cfg_telegram.get("sender bot_token"),
                    cfg_telegram.get("receiver user_id"),
                    client_name + ': "Плохие" статусы раздач:',
                    bad_status
                )
        print("***")

    cfg_telegram = config.get("telegram")
    if cfg_telegram and cfg_telegram.get("receiver user_id"):
        if len(new_files):
            send_tlg(
                cfg_telegram.get("sender bot_token"),
                cfg_telegram.get("receiver user_id"),
                "Новые файлы:",
                new_files
            )
        if len(lost_files):
            send_tlg(
                cfg_telegram.get("sender bot_token"),
                cfg_telegram.get("receiver user_id"),
                'Потерянные файлы:',
                lost_files
            )
    if config.get("delete lost files"):
        for i in lost_files:
            os.remove(i)
            msg = f'Удалили {i}'
            logging.info(msg)
            print(msg)
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
