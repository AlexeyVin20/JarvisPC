# JarvisPC — личный ассистент «Джарвис»

Третья система в семействе: берёт **профили, память и общение** из Android-приложения
[VoxRelay](../VoxRelay) и **интернет-поиск** из PC-системы [VoiceAgent](../VoiceAgent).

- **Голос + текст** через Gemini Live (как VoxRelay) — микрофон в браузере,
  ответ голосом + живые транскрипты; текстовые сообщения в активную голосовую
  сессию отвечаются голосом.
- **Профили-персоны**: Фенрир / Кора / Пак / Аоэда (голоса Gemini Live, свои
  системные промпты и флаги инструментов) — переименовываются в веб-UI, плюс
  свои профили: имя, роль, голос (Fenrir/Kore/Puck/Aoede/Charon/Zephyr), промпт.
- **Полуавтоматическая память** (4000 токенов): инструмент `update_memory`
  (append/replace) + фоновый экстрактор фактов после каждого хода — без спроса.
- **Веб-поиск**: vendored-пайплайн из VoiceAgent — локальный 4get → MinHash
  дедупликация → MMR → извлечение DOM→Markdown → склейка окон.
- **Headless**: REST `POST /api/chat` и CLI `python -m app.cli`.
- **PostgreSQL** вместо Firebase: профили, сессии, сообщения.
- Плагинный реестр инструментов (`app/tools/registry.py`) — место для будущих
  Devin/ACP-задач (флаг `enable_tasks` в профиле уже заложен).

## Структура

```
JarvisPC/
├── docker-compose.yml      postgres:16 + 4get (метапоиск)
├── .env                    GEMINI_API_KEY, DATABASE_URL, ...
├── backend/                FastAPI + uvicorn (Python 3.12+, uv)
│   └── app/
│       ├── main.py         REST /api/* + WS /ws (голос+чат)
│       ├── agent.py        сессии, авто-память, оркестрация (≈ VoxRelay controller+VM)
│       ├── presets.py      4 дефолтных профиля + промпт-пресеты (порт AcpModels.kt)
│       ├── prompts.py      сборка системной инструкции (порт buildEffectiveSystemInstruction)
│       ├── memory.py       update_memory + экстрактор (порт extractMemoryFromConversation)
│       ├── store.py, db.py asyncpg слой
│       ├── gemini/
│       │   ├── live.py     GeminiLiveClient (адаптирован из VoiceAgent: +send_text, +live-транскрипты)
│       │   └── text.py     generateContent REST + function-calling loop
│       ├── tools/          реестр: web_search (4get), update_memory
│       ├── websearch/      vendored пайплайн из VoiceAgent (как есть)
│       └── cli.py          headless REPL
└── web/                    Next.js 15 (App Router)
```

## Запуск

1. `cp .env.example .env` и прописать `GEMINI_API_KEY`
2. `docker compose up -d` — postgres + 4get
3. `backend\setup.bat` — venv + зависимости; `backend\run.bat` — API на :8787
4. `cd web; npm install; npm run dev` — UI на http://localhost:3000

Или одной командой для разработки: `run-dev.bat`.

> PowerShell: `&&` не работает в старых версиях — используйте `;`.
> `run.bat`/`setup.bat` вызывайте из каталога `JarvisPC` (они сами
> переходят в свою папку), или просто `backend\run.bat`.

## Вход через Google (как в VoxRelay)

Вместо ручного ключа можно войти Google-аккаунтом — OAuth 2.0 со scope
`generative-language` даёт приложению доступ к Gemini API от имени
пользователя (аналог входа через Firebase в VoxRelay).

1. В [Google Cloud Console](https://console.cloud.google.com) выберите проект
   (левый верхний угол) — **важно: тот же проект, в котором будет OAuth-клиент**.
2. APIs & Services → Library → найдите **Generative Language API** → **Enable**.
   Без этого Google отвечает `Error 400: invalid_scope`.
3. Google Auth platform → Audience → **External** → в **Test users** добавьте
   свой Google-аккаунт (пока приложение не опубликовано, войти могут только
   тестовые пользователи).
4. Credentials → **Create OAuth client ID** → тип **Web application**
   (или Desktop app) → в Authorized redirect URIs добавьте
   `http://localhost:8787/api/auth/google/callback`.
5. Пропишите `GOOGLE_OAUTH_CLIENT_ID` и `GOOGLE_OAUTH_CLIENT_SECRET` в `.env`,
   перезапустите backend.
5. В веб-UI карточка «Статус» покажет «Войти через Google» — аккаунт и email
   подхватятся, токены хранятся в Postgres и обновляются сами.

Приоритет креденшелов: `GEMINI_API_KEY` из `.env` → ключ, вставленный в UI
(поле в карточке «Статус») → Google-аккаунт. Один и тот же креденшел
используется и для Live-голоса, и для текста.

> Click на карточку **«Статус»** включает/выключает голосовой чат.

## Headless

```bash
# REST
curl -X POST http://localhost:8787/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Что нового в Gemini API?"}'

# CLI
backend\run.bat cli            # или: uv run python -m app.cli --profile PUCK
```

## REST API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | статус, модели |
| GET/PUT | `/api/profiles`, `/api/profiles/{id}` | список/обновление профиля |
| POST/DELETE | `/api/profiles`, `/api/profiles/{id}` | создать / удалить свой профиль |
| GET | `/api/voices` | доступные голоса Gemini Live |
| POST | `/api/profiles/{id}/activate`, `/reset` | активировать / сбросить (память сохраняется) |
| PUT/DELETE | `/api/profiles/{id}/memory` | записать (`mode`=append\|replace) / очистить память |
| GET/POST/DELETE | `/api/sessions[/{id}]` | диалоги и сообщения |
| POST | `/api/chat` | headless ход чата (тот же инструментарий, что у голоса) |
| WS | `/ws` | голосовой канал: JSON-события + бинарный PCM16 @24kHz |

## WS-протокол `/ws`

Клиент → сервер: `init` (session_id?, profile_id?), `start_voice`/`stop_voice`,
`chat` {text}, `set_profile` {profile_id}, бинарные PCM16-фреймы.
Сервер → клиент: `ready`, `state`, `transcript` (финал), `transcript_partial`
(стриминг), `tool_trace`, `barge_in`, `memory_updated`, бинарное аудио ответа.
