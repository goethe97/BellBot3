# Bell Bot

Бот для обработки заявок в Discord.  
Поддерживает анкету в личных сообщениях, сохранение прогресса и автоматическую выдачу ролей.

---

## 🚀 Возможности

- Чтение сообщений из канала заявок
- Автоматическая обработка анкет
- Ведение прогресса ответов
- Выдача ролей после завершения анкеты
- Чёрный список по ID

---

## 📦 Установка и запуск (из исходников)

1. Склонируйте репозиторий:
   git clone https://github.com/username/repo.git
   cd repo

2. Установите зависимости:
   pip install -r requirements.txt

3. Создайте файл `.env` и добавьте туда ваш Discord токен:
   DISCORD*TOKEN=ваш*токен

4. Запустите бота:
   python bot.py

---

## 💻 Сборка .exe

Если хотите собрать готовый exe (чтобы запускать без Python):
pip install pyinstaller
pyinstaller --onefile bot.py

После сборки файл появится в папке `dist/`.

---

## 📥 Скачивание готового exe

Готовый билд можно будет скачать в разделе [Releases](https://github.com/username/repo/releases).  
➡️ [Скачать последнюю версию](https://github.com/username/repo/releases/latest)

---

## ⚙️ Требования

- Python 3.10+
- discord.py (см. `requirements.txt`)
