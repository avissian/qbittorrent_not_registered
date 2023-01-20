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
    _proxy_for_api = False
    _api_limit = 1

    # Статусы раздач, возвращаемые API
    statuses = {
        "0": "не проверено",
        "1": "закрыто",
        "2": "проверено",
        "3": "недооформлено",
        "4": "не оформлено",
        "5": "повтор",
        "7": "поглощено",
        "8": "сомнительно",
        "9": "проверяется",
        "10": "временная",
        "11": "премодерация"
    }

    def __init__(self,
                 user: str,
                 password: str,
                 api_key: str,
                 proxy: str,
                 forum_url: str,
                 api_url: str,
                 proxy_for_api: bool = False,
                 ):
        """ Логин на форум и сохранение сессии """
        # Сохраним параметры в атрибуты объекта
        self._api_key = api_key
        self._forum_url = forum_url
        self._api_url = api_url
        self._proxy_for_api = proxy_for_api

        # Нормализация параметров
        if not self._forum_url.startswith("http"):
            self._forum_url = f"https://{self._forum_url}"

        if not self._api_url.startswith("http"):
            self._api_url = f"https://{self._api_url}"

        # Авторизация на форуме для переиспользования сессии
        self.forum_login(user=user, password=password, proxy=proxy)

        if self._proxy_for_api:
            self._session_api = self._session
        else:
            self._session_api = requests.Session()
            self._session_api.verify = False

        # Получение лимита на запросы к API
        self._api_limit = self.get_limit()

    """ Работа с форумом """

    def forum_login(self, user: str, password: str, proxy: str):
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

    def download_torrent(self, torrent_id: str) -> str:
        """ Получить torrent файл по ID темы и сохранить его на диск """
        url = f"{self._forum_url}/forum/dl.php"
        params = {"t": torrent_id}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = self._session.get(url=url, params=params, allow_redirects=True, headers=headers)
        f_name = torrent_id + ".torrent"
        with open(f_name, "wb") as torr_file:
            for chunk in resp.iter_content(chunk_size=1024):
                torr_file.write(chunk)
                torr_file.flush()
                os.fsync(torr_file.fileno())
        return f_name

    """ Работа с API """

    def get_tor_topic_data(self, torrent_id: [str, list]):
        """ Данные о раздаче по ID темы """
        # Приведём ID раздач к списку, даже если там одна (строка)
        if isinstance(torrent_id, str):
            torrent_id = [torrent_id]

        # Запрос инфы из API блоками по _api_limit штук
        url = f"{self._api_url}/v1/get_tor_topic_data"

        params = {"api_key": self._api_key, "by": "topic_id"}
        return self._api_get_list(url=url, params=params, val=torrent_id)

    def get_forum_data(self, forum_id: [str, list]):
        """ Данные по разделу """
        if isinstance(forum_id, str):
            forum_id = [forum_id]

        url = f"{self._api_url}/v1/get_forum_data"
        params = {"api_key": self._api_key, "by": "forum_id"}
        return self._api_get_list(url=url, params=params, val=forum_id)

    def get_limit(self):
        """ Получить лимит параметров в запросе """
        url = f"{self._api_url}/v1/get_limit"

        resp = self._session_api.get(url=url, allow_redirects=True)

        data = json.loads(resp.content.decode("utf-8"))
        return int(data["result"]["limit"])

    def _api_get_list(self, url, params, val: list):
        """ Запрос инфы из API блоками по _api_limit штук """
        result = {}
        for i in range(0, len(val), self._api_limit):
            params["val"] = ",".join(val[i:i + self._api_limit])
            try:
                resp = self._session_api.get(url=url, params=params, allow_redirects=True)
            except Exception as e:
                logging.error(e)
                continue
            data = json.loads(resp.content.decode("utf-8"))
            try:
                result.update(dict(data["result"]))
            except Exception as e:
                logging.warning("Cant pase JSON")
                logging.error(e)
        # logging.debug(f"Returning: {result}")
        return result
