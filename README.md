# Lions Roar

Lions Roar is a Python service that watches selected Telegram channels with a **user account** (Telethon), uses an **LLM** to decide what counts as an incident, merge related posts, and when to open or close an alert, and sends consolidated updates to a **destination channel or group** via the **Telegram Bot API**.

## What it does

- **Ingest**: Subscribes to messages (and edits/deletes) from configured channels.
- **Understand**: Calls an OpenAI chat model with structured JSON output to classify urgency, relate messages to an ongoing incident, and detect closure conditions.
- **Act**: Posts formatted alerts through a bot token to `destination_chat_id` (or a debug chat when `is_debug` is enabled).
- **Operate**: Supports deferred closes, informational grace, manual `/close` from allowed admins (Telethon chat commands and optional Bot API DMs), and retries on message processing failures.

Time-based model selection uses **Asia/Jerusalem**: a “night” model applies between 18:30 and 08:00; otherwise the “day” model is used.

## Requirements

- Python **3.12+** (the bundled `Dockerfile` uses Python 3.12).
- A Telegram **API ID** and **API hash** from [my.telegram.org](https://my.telegram.org/apps).
- A Telegram **user session** file for Telethon (see below).
- A **bot token** from [@BotFather](https://t.me/BotFather) for sending messages to the alert chat.
- An **OpenAI API key** (the current `LLMClient` uses the OpenAI API).

## Quick start (local)

1. Clone the repository and create a virtual environment.

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy the sample config and edit it with your credentials and channel list.

   ```bash
   cp config_example.yaml config.yaml
   ```

   `config.yaml` is gitignored; keep it private.

3. Ensure Telethon can log in and persist a session:

   - Set `session_name` in `config.yaml` (for example `lions_roar`). Telethon will create `lions_roar.session` on first successful login when you run the app.
   - Run from the repository root so paths resolve correctly:

     ```bash
     python3 main.py
     ```

4. Add the user account to the channels you list under `monitored_chats`. If `monitored_chats` is omitted or empty, **every chat** the account can see is considered monitored—set an explicit allowlist in production. Ensure the bot can post in `destination_chat_id` (admin/post rights as required by Telegram).

For a field-by-field reference, start from `config_example.yaml` and the keys read in `main.py` (for example `is_debug`, `destination_chat_id_debug`, `admin_user_ids`, `enable_bot_dm_commands`, `deferred_close`).

## Configuration highlights

| Area | Notes |
|------|--------|
| **Debug** | `is_debug: true` switches the outbound chat to `destination_chat_id_debug`. |
| **Models** | `LLM_models.day` / `LLM_models.night` override the default; a single `model` key is still supported as a fallback. |
| **Deferred close** | Under `deferred_close`, each reason sets `enabled` and `seconds`. Defaults: `all_clear`, `out_of_subscriber_areas`, and `source_deleted` are enabled with **120** seconds; `informational_grace`, `ttl`, and `manual` are disabled with **0** seconds. |
| **Admin** | `admin_command_chat_id` and `admin_user_ids` control who may issue manual close commands; Bot DM `/close` is toggled with `enable_bot_dm_commands`. |

## Docker

The `Dockerfile` expects `lions_roar.session` to exist **at build time** (it is copied into the image). Runtime overrides typically mount `config.yaml` and a data directory, as in `tools/docker_run.sh`:

- `config.yaml` → `/app/config.yaml`
- `./data` → `/app/data`

Build and deployment scripts under `tools/` (`docker_build.sh`, `docker_run.sh`) are oriented toward a specific host and image naming; adjust paths, SSH keys, and image tags for your environment.

## Security

- Never commit `config.yaml`, `.session` files, or API keys.
- Treat the Telethon user session as highly sensitive: it can act as your Telegram account within the limits of the API.

