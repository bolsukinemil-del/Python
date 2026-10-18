import asyncio
import html
import re
import urllib.parse
import urllib.request
from datetime import datetime
from telethon import TelegramClient, events, errors
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from google import genai

# ================= КОНФИГУРАЦИЯ =================
API_ID = 30819743
API_HASH = '4afc9afef1cd00d51a3da5dc1f9c0951'
GEMINI_API_KEY = 'AQ.Ab8RN6LX0vmTXth7QXDH_-ffoYSTfLDU6gxVtpev0pin9ehbxQ'

PREFERRED_MODELS = [
    'gemini-3-flash-preview',
    'gemini-3.5-flash-lite',
    'gemma-4-31b-it'
]
# ================================================

client = TelegramClient('my_userbot_session', API_ID, API_HASH)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

AVAILABLE_MODELS = []
ACTIVE_MODEL = PREFERRED_MODELS[0]

# Хранилища режимов по чатам
MUTED_CHATS = set()
MUTED_USERS = set()
HEART_CHATS = set()  # Чаты, где включена авто-реакция ♥️

# Хранилище для режима /afk
AFK_STATE = {
    'active': False,
    'reason': '',
    'since': None,
    'replied_users': set()
}


def init_models():
    """Проверяет доступные модели при запуске и выбирает лучшую рабочую."""
    global ACTIVE_MODEL, AVAILABLE_MODELS
    try:
        for m in ai_client.models.list():
            name = m.name.replace('models/', '')
            if 'gemini' in name or 'gemma' in name:
                AVAILABLE_MODELS.append(name)

        for pref in PREFERRED_MODELS:
            if pref in AVAILABLE_MODELS:
                ACTIVE_MODEL = pref
                break

        print(f"✅ Основная рабочая модель: {ACTIVE_MODEL}")
    except Exception as e:
        print(f"⚠️ Не удалось проверить список моделей при старте: {e}")


def search_web(query: str, max_results: int = 5) -> str:
    """Быстрый поиск актуальной информации в интернете (DuckDuckGo)."""
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            page = resp.read().decode('utf-8', errors='ignore')

        snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', page, re.DOTALL)
        results = []
        for s in snippets[:max_results]:
            clean_text = html.unescape(re.sub(r'<[^>]+>', '', s)).strip()
            if clean_text:
                results.append(f"• {clean_text}")

        return "\n".join(results)
    except Exception as e:
        print(f"⚠️ Ошибка веб-поиска: {e}")
        return ""


def ask_ai(query: str, use_search: bool = True) -> str:
    """Отправляет запрос в ИИ (с веб-поиском или без него)."""
    global ACTIVE_MODEL

    today = datetime.now().strftime("%d.%m.%Y")
    if use_search:
        web_context = search_web(query)
        if web_context:
            full_prompt = (
                f"Сегодняшняя дата: {today}.\n"
                f"Актуальная информация из интернета по запросу:\n{web_context}\n\n"
                f"Используя эти данные и свои знания, дай четкий и полезный ответ на русском языке на запрос: {query}"
            )
        else:
            full_prompt = f"Сегодняшняя дата: {today}.\nОтветь на запрос: {query}"
    else:
        full_prompt = query

    models_queue = [ACTIVE_MODEL] + [m for m in PREFERRED_MODELS if m != ACTIVE_MODEL]

    last_error = None
    for model_name in models_queue:
        try:
            response = ai_client.models.generate_content(
                model=model_name,
                contents=full_prompt
            )
            if response and response.text:
                if ACTIVE_MODEL != model_name:
                    ACTIVE_MODEL = model_name
                return response.text.strip()
        except Exception as e:
            last_error = e
            continue

    raise Exception(last_error)


# ================= 1. РЕЖИМЫ /PUT HEART, /MUTE И /AFK =================

# Включение/выключение авто-реакции ♥️ только в текущем чате
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/put\s+heart$'))
async def put_heart_handler(event):
    chat_id = event.chat_id

    if chat_id in HEART_CHATS:
        HEART_CHATS.discard(chat_id)
        status = "💔 **Авто-реакция ♥️ выключена** в этом чате."
    else:
        HEART_CHATS.add(chat_id)
        status = "♥️ **Авто-реакция включена!** Теперь на все сообщения собеседника в этом чате будет ставиться ♥️."

    await event.edit(status)
    await asyncio.sleep(1.2)
    await event.delete()


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/(mute|unmute)$'))
async def mute_command_handler(event):
    cmd = event.pattern_match.group(1).lower()
    chat_id = event.chat_id

    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.sender_id:
            target = (chat_id, reply_msg.sender_id)
            if cmd == 'unmute' or target in MUTED_USERS:
                MUTED_USERS.discard(target)
                status = "🔊 **Мут снят** с пользователя."
            else:
                MUTED_USERS.add(target)
                status = "🔇 **Режим Mute включен** для этого пользователя."

            await event.edit(status)
            await asyncio.sleep(1.2)
            await event.delete()
            return

    if cmd == 'unmute' or chat_id in MUTED_CHATS:
        MUTED_CHATS.discard(chat_id)
        status = "🔊 **Режим Mute выключен.**"
    else:
        MUTED_CHATS.add(chat_id)
        status = "🔇 **Режим Mute включен.** Все входящие сообщения удаляются."

    await event.edit(status)
    await asyncio.sleep(1.2)
    await event.delete()


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/afk(?:\s+([\s\S]+))?$'))
async def afk_on_handler(event):
    reason = event.pattern_match.group(1)
    AFK_STATE['active'] = True
    AFK_STATE['reason'] = reason.strip() if reason else "Занят"
    AFK_STATE['since'] = datetime.now()
    AFK_STATE['replied_users'].clear()

    await event.edit(f"💤 **Режим AFK включен.**\nПричина: `{AFK_STATE['reason']}`")


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/unafk$'))
async def afk_off_handler(event):
    AFK_STATE['active'] = False
    AFK_STATE['replied_users'].clear()
    await event.edit("⚡️ **Режим AFK выключен.** Я снова в сети!")
    await asyncio.sleep(2)
    await event.delete()


# Перехватчик всех входящих сообщений
@client.on(events.NewMessage(incoming=True))
async def incoming_interceptor(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    # 1. Мгновенное удаление сообщений от тех, кто в муте
    if chat_id in MUTED_CHATS or (chat_id, sender_id) in MUTED_USERS:
        try:
            await event.delete(revoke=True)
        except Exception:
            pass
        raise events.StopPropagation

    # 2. Мгновенная реакция ♥️ (только в тех чатах, где написали /put heart)
    if chat_id in HEART_CHATS:
        for heart_emoji in ('❤️', '❤', '♥️'):
            try:
                await client(SendReactionRequest(
                    peer=chat_id,
                    msg_id=event.id,
                    reaction=[ReactionEmoji(emoticon=heart_emoji)]
                ))
                break
            except Exception:
                continue

    # 3. Автоответчик AFK в личных сообщениях
    if AFK_STATE['active'] and event.is_private and not event.out:
        sender = await event.get_sender()
        if sender and not getattr(sender, 'bot', False):
            if sender_id not in AFK_STATE['replied_users']:
                AFK_STATE['replied_users'].add(sender_id)
                mins = int((datetime.now() - AFK_STATE['since']).total_seconds() // 60)
                time_str = f"{mins} мин." if mins > 0 else "только что"
                await event.reply(
                    f"🤖 *Автоответчик:* Сейчас меня нет на месте (отошел {time_str} назад).\n"
                    f"📌 **Причина:** {AFK_STATE['reason']}"
                )


# ================= 2. ПРИКОЛЬНЫЕ КОМАНДЫ =================

# Меню помощи: /help
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/help$'))
async def help_handler(event):
    help_text = (
        "🛠 **Панель управления Юзерботом:**\n\n"
        "🤖 **Нейросеть (Gemini):**\n"
        "• `Gemini [вопрос]` — ответ с поиском в интернете\n"
        "• `/roast` *(реплай)* — остроумно подколоть собеседника\n"
        "• `/sum` *(реплай)* — краткая суть длинного сообщения\n"
        "• `/tr [язык]` *(реплай)* — перевести сообщение\n"
        "• `/models` — список доступных моделей ИИ\n\n"
        "🔥 **Эффекты и фан:**\n"
        "• `/put heart` — авто-реакция ♥️ на сообщения в текущем чате\n"
        "• `/type [текст]` — печатная машинка\n"
        "• `/hack` — анимация взлома\n"
        "• `/send [кол-во] [текст]` — спам сообщениями\n\n"
        "🛡 **Модерация и утилиты:**\n"
        "• `/mute` / `/unmute` — автоудаление сообщений собеседника\n"
        "• `/purge` *(реплай)* — очистить чат от сообщения до низа\n"
        "• `/afk [причина]` / `/unafk` — умный автоответчик в ЛС\n"
        "• `/id` — узнать ID чата и пользователя"
    )
    await event.edit(help_text)


# Эффект печатной машинки: /type Привет мир
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/type\s+([\s\S]+)'))
async def typewriter_handler(event):
    text = event.pattern_match.group(1)
    step = max(1, len(text) // 15)
    current = ""

    for i in range(0, len(text), step):
        current = text[:i + step]
        try:
            await event.edit(current + " ▒")
            await asyncio.sleep(0.15)
        except errors.FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception:
            break

    await event.edit(text)


# Шуточный взлом: /hack
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/hack$'))
async def hack_handler(event):
    stages = [
        "💻 `Инициализация эксплойта...`",
        "🔍 `Поиск уязвимостей в Telegram API... [24%]`",
        "🔓 `Обход двухфакторной аутентификации... [51%]`",
        "📂 `Скачивание архива личных переписок... [78%]`",
        "📸 `Выгрузка скрытых фото на внешний сервер... [99%]`",
        "✅ **Взлом успешно завершен! Все данные скопированы.**"
    ]
    for stage in stages:
        try:
            await event.edit(stage)
            await asyncio.sleep(0.9)
        except Exception:
            break


# ИИ-прожарка собеседника: /roast (в ответ на сообщение)
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/roast$'))
async def roast_handler(event):
    if not event.is_reply:
        await event.edit("⚠️ Ответь этой командой на сообщение, которое нужно прожарить!")
        return

    reply_msg = await event.get_reply_message()
    if not reply_msg or not reply_msg.text:
        await event.edit("⚠️ В сообщении нет текста!")
        return

    await event.edit("🔥 *Генерирую ответку...*")
    prompt = (
        f"Придумай короткий, дерзкий, очень смешной и остроумный подкол (сарказм/прожарку) "
        f"в ответ на это сообщение собеседника: «{reply_msg.text}». "
        f"Без оскорблений матом, но максимально метко, на русском языке (1-2 предложения)."
    )
    try:
        answer = await asyncio.to_thread(ask_ai, prompt, False)
        await event.edit(answer)
    except Exception as e:
        await event.edit(f"❌ Ошибка: `{e}`")


# Краткая выжимка текста: /sum (в ответ на сообщение)
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/sum$'))
async def summarize_handler(event):
    if not event.is_reply:
        await event.edit("⚠️ Ответь командой `/sum` на длинное сообщение!")
        return

    reply_msg = await event.get_reply_message()
    if not reply_msg or not reply_msg.text:
        await event.edit("⚠️ В сообщении нет текста!")
        return

    await event.edit("📝 *Выделяю главную суть...*")
    prompt = f"Сделай максимально краткую выжимку (буквально 1-3 пункта по сути) из этого текста:\n\n{reply_msg.text}"
    try:
        answer = await asyncio.to_thread(ask_ai, prompt, False)
        await event.edit(f"📌 **Краткая суть:**\n{answer}")
    except Exception as e:
        await event.edit(f"❌ Ошибка: `{e}`")


# Переводчик: /tr [язык] (в ответ на сообщение)
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/tr(?:\s+(.+))?$'))
async def translate_handler(event):
    if not event.is_reply:
        await event.edit("⚠️ Ответь командой `/tr` на сообщение для перевода!")
        return

    target_lang = event.pattern_match.group(1) or "русский"
    reply_msg = await event.get_reply_message()
    if not reply_msg or not reply_msg.text:
        await event.edit("⚠️ В сообщении нет текста!")
        return

    await event.edit(f"🌐 *Перевожу на {target_lang}...*")
    prompt = f"Переведи следующий текст на {target_lang} язык (выдай только сам перевод без лишних слов):\n\n{reply_msg.text}"
    try:
        answer = await asyncio.to_thread(ask_ai, prompt, False)
        await event.edit(f"🌐 **Перевод ({target_lang}):**\n{answer}")
    except Exception as e:
        await event.edit(f"❌ Ошибка: `{e}`")


# Очистка чата: /purge (в ответ на сообщение)
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/purge$'))
async def purge_handler(event):
    if not event.is_reply:
        await event.edit("⚠️ Ответь командой `/purge` на сообщение, с которого нужно начать зачистку!")
        return

    reply_msg = await event.get_reply_message()
    msg_ids = []

    async for msg in client.iter_messages(event.chat_id, min_id=reply_msg.id - 1):
        msg_ids.append(msg.id)
        if len(msg_ids) >= 100:
            await client.delete_messages(event.chat_id, msg_ids, revoke=True)
            msg_ids.clear()

    if msg_ids:
        await client.delete_messages(event.chat_id, msg_ids, revoke=True)


# Информация об ID: /id
@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/id$'))
async def id_handler(event):
    text = f"💬 **ID чата:** `{event.chat_id}`\n"
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        text += f"👤 **ID пользователя:** `{reply_msg.sender_id}`"
    await event.edit(text)


# ================= 3. БАЗОВЫЕ КОМАНДЫ (/SEND, /MODELS, GEMINI) =================

@client.on(events.NewMessage(outgoing=True, pattern=r'^/send\s+(\d+)\s+([\s\S]+)'))
async def spam_handler(event):
    count = int(event.pattern_match.group(1))
    text = event.pattern_match.group(2).strip()

    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]

    await event.delete()

    for _ in range(count):
        try:
            await client.send_message(event.chat_id, text)
            await asyncio.sleep(0.3)
        except errors.FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception:
            break


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/models$'))
async def list_models_handler(event):
    models_str = "\n".join(f"• `{m}`" for m in AVAILABLE_MODELS[:20]) if AVAILABLE_MODELS else "Список пуст"
    await event.edit(
        f"🤖 **Активная модель:** `{ACTIVE_MODEL}`\n\n"
        f"**Резервная очередь:**\n" + "\n".join(f"• `{m}`" for m in PREFERRED_MODELS) + "\n\n"
        f"**Все доступные на ключе:**\n{models_str}"
    )


@client.on(events.NewMessage(pattern=r'(?i)^gemini(?:\s+([\s\S]+))?$'))
async def gemini_handler(event):
    query = event.pattern_match.group(1)

    if not query or not query.strip():
        await event.reply(
            "👋 Привет! Я ИИ-ассистент Gemini.\n"
            "Напиши `Gemini [твой вопрос]`, и я найду свежую информацию в интернете!"
        )
        return

    query = query.strip()
    status_msg = await event.reply("🔍 *Ищу информацию в интернете...*")

    try:
        answer = await asyncio.to_thread(ask_ai, query, True)

        if len(answer) > 4000:
            answer = answer[:4000] + "...\n\n*(ответ сокращен из-за лимитов Telegram)*"

        try:
            await status_msg.edit(answer)
        except Exception:
            await status_msg.edit(answer, parse_mode=None)

    except Exception as e:
        await status_msg.edit(f"❌ Ошибка при обращении к API:\n`{e}`")


async def main():
    init_models()
    await client.start()
    print("🚀 Юзербот полностью готов к работе! Напишите /help в любом чате.")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
