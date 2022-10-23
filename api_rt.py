import json
import logging
import os
from urllib.parse import urlencode

import requests

# noinspection PyUnresolvedReferences
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


class Rutracker:
    _api_url = "http://api.rutracker.org"
    _forum_url = "https://rutracker.org"
    _session = None

    def __init__(self,
                 user: str,
                 password: str,
                 api_key: str,
                 proxy: str
                 ):
        """ Логин на форум и сохранение сессии """
        self._api_key = api_key

        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}
        # кодируем параметры в windows-1251, иначе форум не понимает кириллицу
        payload = urlencode(
            query={"login_username": user,
                   "login_password": password,
                   "login": "вход"},
            encoding="windows-1251")
        self._session = requests.Session()

        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

        self._session.verify = False

        self._session.post(self._forum_url + "/forum/login.php", headers=headers, data=payload)

    """ Работа с форумом """

    def download_torrent(self, torrent_id: str):
        """ Получить torrent файл по ID темы и сохранить его на диск """
        url = self._forum_url + "/forum/dl.php"
        params = {"t": torrent_id}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = self._session.get(url=url, params=params, allow_redirects=True, headers=headers)
        with open(torrent_id + ".torrent", "wb") as torr_file:
            for chunk in resp.iter_content(chunk_size=1024):
                torr_file.write(chunk)
                torr_file.flush()
                os.fsync(torr_file.fileno())

    """ Работа с API """

    def get_tor_topic_data(self, torrent_id: [str, list]):
        """ Данные о раздаче по ID темы """
        if isinstance(torrent_id, list):
            torrent_id = ",".join(torrent_id)
        url = self._api_url + "/v1/get_tor_topic_data"
        params = {"api_key": self._api_key, "by": "topic_id", "val": torrent_id}
        try:
            resp = self._session.get(url=url, params=params, allow_redirects=True, verify=False)
        except:
            logging.warning("Cant process id: ", torrent_id)
            return None
        topic_data = json.loads(resp.content.decode("utf-8"))
        try:
            result = topic_data["result"]
        except:
            return None
        return result

    def get_forum_data(self, forum_id: [str, list]):
        """ Данные по разделу """
        if isinstance(forum_id, list):
            forum_id = ",".join(forum_id)
        url = self._api_url + "/v1/get_forum_data"
        params = {"api_key": self._api_key, "by": "forum_id", "val": forum_id}
        try:
            resp = self._session.get(url=url, params=params, allow_redirects=True, verify=False)
        except:
            logging.warning("Cant process id: ", forum_id)
            return None

        data = json.loads(resp.content.decode("utf-8"))
        return data["result"]

