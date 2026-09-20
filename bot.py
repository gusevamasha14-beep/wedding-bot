#!/usr/bin/env python3
"""Простой Telegram бот для вручения сертификата на фотосессию."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"
TOKEN_PATH = BASE_DIR / "token.txt"


def load_env(path: Path) -> None:
    """Загружает переменные окружения из .env файла."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


def load_config() -> dict[str, Any]:
    """Загружает конфигурацию из config.json."""
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit("Не найден файл config.json") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Ошибка в config.json: {exc}") from exc


def keyboard(rows: list[list[dict[str, str]]]) -> dict[str, Any]:
    """Создаёт inline клавиатуру."""
    return {"inline_keyboard": rows}


def callback_button(text: str, data: str) -> dict[str, str]:
    """Создаёт кнопку с callback данными."""
    return {"text": text, "callback_data": data}


def url_button(text: str, url: str) -> dict[str, str]:
    """Создаёт кнопку со ссылкой."""
    return {"text": text, "url": url}


class TelegramBot:
    """Простой Telegram бот."""
    
    def __init__(self, token: str, config: dict[str, Any]) -> None:
        self.api_url = f"https://api.telegram.org/bot{token}/"
        self.config = config

    def request(self, method: str, data: dict[str, Any] | None = None) -> Any:
        """Выполняет API запрос к Telegram."""
        payload = urllib.parse.urlencode(self._prepare(data or {})).encode("utf-8")
        request = urllib.request.Request(self.api_url + method, data=payload)
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram вернул ошибку {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Нет связи с Telegram: {exc.reason}") from exc

        if not result.get("ok"):
            raise RuntimeError(result.get("description", "Неизвестная ошибка Telegram"))
        return result.get("result")

    @staticmethod
    def _prepare(data: dict[str, Any]) -> dict[str, Any]:
        """Подготавливает данные для отправки."""
        prepared: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                prepared[key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                prepared[key] = "true" if value else "false"
            else:
                prepared[key] = value
        return prepared

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Отправляет текстовое сообщение."""
        data: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            data["reply_markup"] = reply_markup
        self.request("sendMessage", data)

    def answer_callback(self, callback_id: str) -> None:
        """Отвечает на callback query."""
        self.request("answerCallbackQuery", {"callback_query_id": callback_id})

    def send_photo(
        self,
        chat_id: int,
        photo_path: Path,
        caption: str,
        reply_markup: dict[str, Any],
    ) -> None:
        """Отправляет фотографию с подписью."""
        boundary = "----TelegramBot" + secrets.token_hex(12)
        body = bytearray()

        # Добавляем текстовые поля
        fields = {
            "chat_id": str(chat_id),
            "caption": caption,
            "reply_markup": json.dumps(reply_markup, ensure_ascii=False),
        }
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        # Добавляем файл
        mime_type = mimetypes.guess_type(photo_path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                'Content-Disposition: form-data; name="photo"; '
                f'filename="{photo_path.name}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode())
        body.extend(photo_path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        request = urllib.request.Request(
            self.api_url + "sendPhoto",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Не удалось отправить сертификат: {details}") from exc
        if not result.get("ok"):
            raise RuntimeError(result.get("description", "Не удалось отправить сертификат"))

    def start(self, chat_id: int) -> None:
        """Отправляет приветственное сообщение с кнопкой."""
        self.send_message(
            chat_id,
            self.config["start_text"],
            keyboard([[callback_button("🎁 ОТКРЫТЬ ПОДАРОК", "open_gift")]])
        )

    def send_certificate(self, chat_id: int) -> None:
        """Отправляет сертификат с кнопкой для связи."""
        username = self.config["photographer_username"].lstrip("@")
        photo_path = BASE_DIR / self.config["certificate_file"]
        
        contact_button = url_button(
            "💌 ИСПОЛЬЗОВАТЬ СЕРТИФИКАТ",
            f"https://t.me/{username}"
        )
        
        self.send_photo(
            chat_id,
            photo_path,
            self.config["certificate_caption"],
            keyboard([[contact_button]])
        )

    def handle_update(self, update: dict[str, Any]) -> None:
        """Обрабатывает входящее обновление."""
        # Обработка текстовых сообщений
        message = update.get("message")
        if message:
            chat_id = message["chat"]["id"]
            text = message.get("text", "")
            if text.startswith("/start"):
                self.start(chat_id)
            else:
                self.send_message(
                    chat_id,
                    "Чтобы получить подарок, нажмите /start"
                )
            return

        # Обработка нажатий на кнопки
        callback = update.get("callback_query")
        if not callback:
            return

        self.answer_callback(callback["id"])
        chat_id = callback["message"]["chat"]["id"]
        data = callback.get("data", "")

        if data == "open_gift":
            self.send_certificate(chat_id)

    def run(self) -> None:
        """Запускает бота в режиме long polling."""
        me = self.request("getMe")
        print(f"✓ Бот @{me['username']} запущен и готов к работе!")
        print("Для остановки нажмите Ctrl+C")
        
        offset = 0
        while True:
            try:
                updates = self.request(
                    "getUpdates",
                    {
                        "offset": offset,
                        "timeout": 50,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )
                for update in updates:
                    offset = update["update_id"] + 1
                    try:
                        self.handle_update(update)
                    except Exception as exc:
                        print(f"Ошибка при обработке сообщения: {exc}", file=sys.stderr)
            except KeyboardInterrupt:
                print("\n✓ Бот остановлен.")
                return
            except Exception as exc:
                print(f"Ошибка соединения: {exc}. Повтор через 5 секунд.", file=sys.stderr)
                time.sleep(5)


def validate(config: dict[str, Any], token: str | None) -> list[str]:
    """Проверяет наличие всех необходимых данных."""
    errors: list[str] = []
    
    if not token or token == "ВСТАВЬТЕ_СЮДА_ТОКЕН":
        errors.append("Добавьте токен от @BotFather в переменную окружения BOT_TOKEN")
    
    certificate_path = BASE_DIR / config.get("certificate_file", "")
    if not certificate_path.is_file():
        errors.append(f"Не найден сертификат: {certificate_path.name}")
    
    if not config.get("photographer_username"):
        errors.append("Добавьте photographer_username в config.json")
    
    return errors


def main() -> None:
    """Главная функция запуска бота."""
    load_env(ENV_PATH)
    config = load_config()
    
    # Получаем токен из переменных окружения или файла token.txt
    token = os.getenv("BOT_TOKEN")
    if (not token or token == "ВСТАВЬТЕ_СЮДА_ТОКЕН") and TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    
    # Проверяем наличие всех необходимых данных
    errors = validate(config, token)
    if errors:
        print("❌ Ошибка запуска:", file=sys.stderr)
        for error in errors:
            print(f"  • {error}", file=sys.stderr)
        sys.exit(1)
    
    # Запускаем бота
    TelegramBot(token, config).run()


if __name__ == "__main__":
    main()
