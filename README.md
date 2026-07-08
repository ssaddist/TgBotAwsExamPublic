# Інструкція з запуску та деплою Telegram-бота

## Локальний запуск (Development)

1. Клонуйте репозиторій:

   ```bash
   git clone https://github.com/ssaddist/TgBotAwsExamPublic.git
   cd TgBotAwsExamPublic
   ```

2. Створіть віртуальне оточення та активуйте його:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Встановіть залежності:

   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Створіть файл `.env` на основі шаблону та вкажіть ваш токен:

   ```bash
   cp .env.example .env
   ```

   Всередині `.env` обов'язково заповніть токен бота та вкажіть ім'я для вашої бази даних SQLite (наприклад, `database.sqlite3` або `data/price_tracker.db`):

   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   DB_NAME=database.sqlite3
   ```

   > [!NOTE]
   > База даних із вказаним ім'ям буде створена та налаштована автоматично при першому запуску бота. Додатково створювати таблиці вручну не потрібно.

5. Запустіть бота через стартовий скрипт:
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

---

## ☁️ Деплой на AWS EC2 (Amazon Linux 2023)

### Крок 0. Створення інстансу EC2 в AWS Console

1. Увійдіть у консоль AWS та перейдіть у сервіс **EC2**.
2. Натисніть **Launch Instance**.
3. Вкажіть ім'я інстансу та виберіть операційну систему **Amazon Linux 2023** (AMI).
4. Виберіть тип інстансу (наприклад, безкоштовний `t2.micro` або `t3.micro`).
5. У блоці **Key pair (login)** виберіть існуючу ключову пару або створіть нову (**Create new key pair**). Це дозволить підключатися до сервера по SSH безпечно та без введення пароля (використовуючи приватний SSH-ключ `.pem`).
   > [!IMPORTANT]
   > Не вибирайте варіант _«Proceed without a key pair»_ (Продовжити без ключової пари). Без приватного SSH-ключа (файлу `.pem`) ви не зможете підключитися до сервера по SSH для початкового налаштування та деплою, а також він необхідний для налаштування секретів GitHub Actions. Збережіть цей файл на вашому локальному комп'ютері.
6. У налаштуваннях мережі (**Network Settings / Security Groups**) додайте такі правила для вхідного трафіку (Inbound Rules):
   - **SSH (порт 22):** дозволено тільки з вашої IP-адреси (для безпечного підключення).
   - **Custom TCP (порт 8000):** дозволено з будь-якого місця (`0.0.0.0/0`), якщо планується використовувати FastAPI Health Check API `/health`.
7. Натисніть **Launch Instance** для запуску сервера.

### Крок 1. Підготовка сервера та клонування

1. Підключіться до сервера по SSH (без пароля, з використанням збереженого приватного ключа `.pem`) та встановіть необхідні пакети:
   ```bash
   sudo dnf install git python3.13 python3.13-pip -y
   ```
2. Згенеруйте SSH Deploy-ключ для авторизації у вашому приватному репозиторії GitHub:
   ```bash
   ssh-keygen -t ed25519 -b 4096 -C "ec2-deploy-key" -f ~/.ssh/github_deploy -N ""
   ```
3. Скопіюйте публічний ключ та додайте його в GitHub (**Settings -> Deploy keys -> Add deploy key**):
   ```bash
   cat ~/.ssh/github_deploy.pub
   ```
4. **Важливо:** Для того, щоб GitHub Actions міг підключатися до сервера, додайте публічну частину згенерованого ключа `github_deploy` до списку авторизованих ключів сервера:
   ```bash
   cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```
5. Створіть SSH-конфигурацію на сервері:
   ```bash
   nano ~/.ssh/config
   ```
   Додайте туди такі рядки:
   ```text
   Host github.com
     IdentityFile ~/.ssh/github_deploy
     User git
   ```
   Налаштуйте права доступу до конфігурації:
   ```bash
   chmod 600 ~/.ssh/config
   ```
5. Перевірте підключення по SSH до GitHub (натисніть `yes` при запиті):
   ```bash
   ssh -T git@github.com
   ```
6. Клонуйте проект у домашню директорію:
   ```bash
   git clone git@github.com:ssaddist/TgBotAwsExamPublic.git /home/ec2-user/TgBotAwsExamPublic
   cd /home/ec2-user/TgBotAwsExamPublic
   ```

### Крок 2. Налаштування оточення на сервері

1. Створіть віртуальне оточення та встановіть залежності:
   ```bash
   python3.13 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
2. Створіть файл `.env`, впишіть ваш токен Telegram-бота та вкажіть конкретне ім'я для вашої бази даних SQLite (рекомендується `database.sqlite3`):
   ```bash
   cp .env.example .env
   nano .env
   ```
   Переконайтеся, що вказані правильні параметри:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   DB_NAME=database.sqlite3
   ```
   > [!NOTE]
   > При запуску скрипт автоматично створить файл бази даних із вказаним ім'ям у робочій директорії та виконає ініціалізацію таблиц.

### Крок 3. Налаштування автозапуску через systemd

1. Створіть файл служби:

   ```bash
   sudo nano /etc/systemd/system/tgbot.service
   ```

   Вставте таку конфігурацію:

   ```ini
   [Unit]
   Description=Telegram Price Tracker Bot
   After=network.target

   [Service]
   Type=simple
   User=ec2-user
   WorkingDirectory=/home/ec2-user/TgBotAwsExamPublic
   ExecStart=/bin/bash /home/ec2-user/TgBotAwsExamPublic/start.sh
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

2. Запустіть та активуйте службу:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable tgbot.service
   sudo systemctl start tgbot.service
   ```
3. Перевірте статус служби:
   ```bash
   sudo systemctl status tgbot.service
   ```

### Крок 4. Зупинка роботи бота

Якщо вам знадобиться зупинити бота, виконайте команду:

```bash
sudo systemctl stop tgbot.service
```

А для повного відключення автозапуска при старті системи:

```bash
sudo systemctl disable tgbot.service
```

---

## Автоматичний деплой через GitHub Actions (CI/CD)

У репозиторії налаштований робочий процес (workflow) для автоматичного оновлення бота на сервері при кожному пуші у гілку `main`.

Для роботи автоматичного деплою необхідно додати секрети у ваш репозиторій на GitHub:

1. Перейдіть у **Settings -> Secrets and variables -> Actions**.
2. Натисніть кнопку **New repository secret**.
3. Додайте такі змінні:
   - `EC2_HOST`: Публічна IP-адреса або DNS-ім'я вашого інстансу EC2.
   - `EC2_USER`: Ім'я користувача SSH для підключення (для Amazon Linux 2023 за замовчуванням `ec2-user`).
   - `EC2_SSH_KEY`: Вміст приватного SSH-ключа. Якщо ви використовуєте згенерований на сервері ключ `github_deploy`, виведіть його приватну частину командою `cat ~/.ssh/github_deploy`, скопіюйте весь вміст (включаючи початковий рядок `-----BEGIN OPENSSH PRIVATE KEY-----` та кінцевий `-----END OPENSSH PRIVATE KEY-----`) і вставте в поле секрету.

Після налаштування секретів будь-який комміт/пуш у гілку `main` автоматично запустить процес оновлення коду на сервері, оновить залежності та перезапустить службу `tgbot.service`.
