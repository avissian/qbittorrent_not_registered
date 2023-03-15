import requests


def send_tlg_msg(from_bot, to_user, text: str):
    """ Отправка текста в телеграм """
    # пробуем отправить сообщение
    params = {"chat_id": to_user,
              "text": text,
              "parse_mode": "MarkdownV2"}
    if from_bot:
        response = requests.get(f"https://api.telegram.org/bot{from_bot}/sendMessage", params)
    else:
        response = requests.get("https://bot.keeps.cyou/PlanB", params)

    if response.status_code != 200:
        print("Не удалось отправить сообщение в телеграм:", response.text)


def send_tlg(from_bot, to_user, header_text, msg_set):
    """ Отправка iterable в телеграм с разбивкой по длине до 4000 """
    if len(msg_set) > 0 and to_user:
        msg = header_text + "\n"
        for item in msg_set:
            if len(msg.encode('utf-8')) + len(item.encode('utf-8')) + 1 <= 2000:
                msg += item + "\n"
            else:
                send_tlg_msg(from_bot, to_user, msg)
                msg = item + "\n"
        send_tlg_msg(from_bot, to_user, msg)
