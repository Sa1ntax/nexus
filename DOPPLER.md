# Запуск с Doppler

## 1. Установи Doppler CLI

**Windows (PowerShell):**
```powershell
iwr https://cli.doppler.com/install.ps1 -useb | iex
```

**Linux / macOS:**
```bash
curl -Ls https://cli.doppler.com/install.sh | sh
```

## 2. Войди и настрой проект

```bash
doppler login
doppler setup
```

Выбери организацию → проект → окружение (например `dev` или `prd`).

## 3. Добавь секреты в Doppler

Через сайт [dashboard.doppler.com](https://dashboard.doppler.com) или CLI:

```bash
doppler secrets set DISCORD_TOKEN="твой_токен"
doppler secrets set TURSO_DATABASE_URL="libsql://..."
doppler secrets set TURSO_AUTH_TOKEN="токен_turso"
doppler secrets set URLHAUS_AUTH_KEY="ключ_или_пусто"
doppler secrets set GUILD_ID="123456789"   # опционально
```

## 4. Запуск бота

```bash
doppler run -- docker compose up -d --build
```

Логи:
```bash
doppler run -- docker compose logs -f
```

Остановка:
```bash
doppler run -- docker compose down
```

## Важно

- Файл `.env` больше не нужен и не должен лежать в репозитории.
- Все секреты живут только в Doppler.
- На сервере достаточно один раз сделать `doppler setup` и дальше запускать через `doppler run`.
