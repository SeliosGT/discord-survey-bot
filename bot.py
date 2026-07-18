import discord
import os
import requests
import json
from datetime import datetime, timezone
import asyncio
from flask import Flask, request, jsonify
import threading
import logging
import traceback
import time
import sys

# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# НАСТРОЙКА БОТА
# ============================================================

TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
ADMIN_USER_ID = int(os.environ.get('ADMIN_USER_ID', '0'))
SERVER_URL = os.environ.get('SERVER_URL', 'https://opros-app.onrender.com')

if not TOKEN:
    logger.error("❌ DISCORD_BOT_TOKEN не найден!")
    sys.exit(1)

if ADMIN_USER_ID == 0:
    logger.error("❌ ADMIN_USER_ID не найден!")
    sys.exit(1)

logger.info(f'🔑 Токен найден: {TOKEN[:10]}...')
logger.info(f'👤 ADMIN_USER_ID: {ADMIN_USER_ID}')

# ============================================================
# НАСТРОЙКА DISCORD
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True

client = discord.Client(intents=intents)
loop = None
client_ready = False

# ============================================================
# СОБЫТИЕ: БОТ ГОТОВ
# ============================================================

@client.event
async def on_ready():
    global client_ready
    client_ready = True
    logger.info(f'✅ Бот {client.user.name} запущен!')
    logger.info(f'📊 На серверах: {len(client.guilds)}')
    
    try:
        user = await client.fetch_user(ADMIN_USER_ID)
        await user.send('🤖 **Бот запущен!** Готов принимать уведомления.')
        logger.info('✅ Приветствие отправлено админу в ЛС')
    except Exception as e:
        logger.warning(f'⚠️ Не удалось отправить приветствие: {e}')

@client.event
async def on_message(message):
    if message.author.bot:
        return

# ============================================================
# ЗАПУСК БОТА
# ============================================================

def run_bot():
    global loop
    try:
        logger.info('🚀 Запуск бота...')
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client.run(TOKEN)
    except Exception as e:
        logger.error(f'❌ Бот упал: {e}')
        logger.error(traceback.format_exc())

# ============================================================
# ФУНКЦИЯ: ОТПРАВКА УВЕДОМЛЕНИЯ (ИСПРАВЛЕННАЯ)
# ============================================================

def send_notification(survey_type, answer_data, answer_id, date_str):
    try:
        logger.info(f'📤 Отправка уведомления (заявка #{answer_id})')
        
        if not client_ready:
            logger.error('❌ Бот не готов к отправке')
            return False
        
        # Получаем пользователя
        user = client.get_user(ADMIN_USER_ID)
        if not user:
            logger.error('❌ Пользователь не найден в кеше, пробуем fetch...')
            # Пробуем получить через fetch
            future = asyncio.run_coroutine_threadsafe(
                client.fetch_user(ADMIN_USER_ID),
                loop
            )
            try:
                user = future.result(timeout=10)
            except Exception as e:
                logger.error(f'❌ Не удалось получить пользователя: {e}')
                return False
        
        type_names = {
            'discipline': '🏛️ Дисциплинарный инспектор',
            'hr': '👔 HR-менеджер'
        }
        type_name = type_names.get(survey_type, '📋 Новая заявка')
        
        embed = discord.Embed(
            title="🔔 Новая заявка!",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(name="🆔 Номер", value=f"#{answer_id}", inline=True)
        embed.add_field(name="📋 Должность", value=type_name, inline=True)
        embed.add_field(name="👤 IC", value=answer_data.get('q1', '—'), inline=True)
        embed.add_field(name="👤 OOC", value=answer_data.get('q2', '—'), inline=True)
        embed.add_field(name="📅 Дата", value=date_str, inline=True)
        embed.add_field(name="🔗 Ссылка", value=f"[Админ-панель]({SERVER_URL}/admin.html)", inline=False)
        
        embed.set_footer(text="by Rubi Antwoord")
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="📋 Открыть админку",
            url=f"{SERVER_URL}/admin.html",
            style=discord.ButtonStyle.link
        ))
        
        # Отправляем с повторной попыткой
        def send_message():
            future = asyncio.run_coroutine_threadsafe(
                user.send(
                    content=f"🔔 **Новая заявка #{answer_id}!**",
                    embed=embed,
                    view=view
                ),
                loop
            )
            return future.result(timeout=30)
        
        # Пробуем отправить с повторной попыткой
        try:
            send_message()
            logger.info(f'✅ Уведомление отправлено (заявка #{answer_id})')
            return True
        except asyncio.TimeoutError:
            logger.warning(f'⏰ Таймаут, пробуем ещё раз...')
            time.sleep(2)
            try:
                send_message()
                logger.info(f'✅ Уведомление отправлено (заявка #{answer_id}) со второй попытки')
                return True
            except asyncio.TimeoutError:
                logger.error(f'⏰ Таймаут после двух попыток (заявка #{answer_id})')
                return False
        
    except Exception as e:
        logger.error(f'❌ Ошибка отправки: {e}')
        logger.error(traceback.format_exc())
        return False

# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

@app.route('/notify', methods=['POST'])
def notify():
    try:
        data = request.json
        survey_type = data.get('survey_type')
        answer_data = data.get('answer_data')
        answer_id = data.get('answer_id')
        date_str = data.get('date_str')
        
        logger.info(f'📨 Запрос на уведомление: заявка #{answer_id}')
        
        # Отправляем синхронно (блокируем до отправки)
        def run_sync():
            try:
                send_notification(survey_type, answer_data, answer_id, date_str)
            except Exception as e:
                logger.error(f'❌ Ошибка в потоке: {e}')
        
        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()
        
        # Ждём немного, чтобы уведомление отправилось
        time.sleep(1)
        
        return jsonify({"success": True}), 200
        
    except Exception as e:
        logger.error(f'❌ Ошибка в /notify: {e}')
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/')
def index():
    return "🤖 Discord Survey Bot is running!"

@app.route('/ping')
def ping():
    return "pong"

@app.route('/status')
def status():
    return jsonify({
        "bot_ready": client_ready,
        "bot_name": client.user.name if client.user else None,
        "guilds": len(client.guilds) if client.user else 0
    })

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == '__main__':
    logger.info('🚀 Запуск бота в фоне...')
    
    # Запускаем бота
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Ждём 5 секунд для запуска
    time.sleep(5)
    
    if client_ready:
        logger.info('✅ Бот успешно запущен!')
    else:
        logger.warning('⚠️ Бот не готов через 5 секунд')
    
    logger.info('🌐 Запуск Flask на порту 10000...')
    app.run(host='0.0.0.0', port=10000)
