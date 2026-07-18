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
from queue import Queue

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
client_ready = False
notification_queue = Queue()
user_cache = None  # Кешируем пользователя

# ============================================================
# СОБЫТИЕ: БОТ ГОТОВ
# ============================================================

@client.event
async def on_ready():
    global client_ready, user_cache
    client_ready = True
    logger.info(f'✅ Бот {client.user.name} запущен!')
    logger.info(f'📊 На серверах: {len(client.guilds)}')
    
    try:
        # Кешируем пользователя при старте
        user_cache = await client.fetch_user(ADMIN_USER_ID)
        await user_cache.send('🤖 **Бот запущен!** Готов принимать уведомления.')
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

async def process_notifications():
    """Фоновая задача для обработки уведомлений"""
    global user_cache
    
    while True:
        try:
            # Проверяем очередь
            if not notification_queue.empty():
                notification_data = notification_queue.get()
                logger.info(f'📤 Отправка уведомления из очереди (заявка #{notification_data["answer_id"]})')
                
                # Обновляем кеш пользователя если нужно
                if not user_cache:
                    try:
                        user_cache = await client.fetch_user(ADMIN_USER_ID)
                    except Exception as e:
                        logger.error(f'❌ Не удалось получить пользователя: {e}')
                        continue
                
                # Формируем сообщение
                type_names = {
                    'discipline': '🏛️ Дисциплинарный инспектор',
                    'hr': '👔 HR-менеджер'
                }
                type_name = type_names.get(notification_data['survey_type'], '📋 Новая заявка')
                
                embed = discord.Embed(
                    title="🔔 Новая заявка!",
                    color=0x5865F2,
                    timestamp=datetime.now(timezone.utc)
                )
                
                embed.add_field(name="🆔 Номер", value=f"#{notification_data['answer_id']}", inline=True)
                embed.add_field(name="📋 Должность", value=type_name, inline=True)
                embed.add_field(name="👤 IC", value=notification_data['answer_data'].get('q1', '—'), inline=True)
                embed.add_field(name="👤 OOC", value=notification_data['answer_data'].get('q2', '—'), inline=True)
                embed.add_field(name="📅 Дата", value=notification_data['date_str'], inline=True)
                embed.add_field(name="🔗 Ссылка", value=f"[Админ-панель]({SERVER_URL}/admin.html)", inline=False)
                
                embed.set_footer(text="by Rubi Antwoord")
                
                view = discord.ui.View()
                view.add_item(discord.ui.Button(
                    label="📋 Открыть админку",
                    url=f"{SERVER_URL}/admin.html",
                    style=discord.ButtonStyle.link
                ))
                
                # Отправляем
                await user_cache.send(
                    content=f"🔔 **Новая заявка #{notification_data['answer_id']}!**",
                    embed=embed,
                    view=view
                )
                
                logger.info(f'✅ Уведомление отправлено (заявка #{notification_data["answer_id"]})')
                notification_queue.task_done()
            
            await asyncio.sleep(0.5)  # Проверяем очередь каждые 500мс
            
        except Exception as e:
            logger.error(f'❌ Ошибка обработки уведомления: {e}')
            logger.error(traceback.format_exc())
            await asyncio.sleep(1)  # Ждем перед повторной попыткой

def run_bot():
    try:
        logger.info('🚀 Запуск бота...')
        
        # Запускаем фоновую задачу при старте
        @client.event
        async def on_ready_inner():
            global client_ready, user_cache
            client_ready = True
            logger.info(f'✅ Бот {client.user.name} запущен!')
            logger.info(f'📊 На серверах: {len(client.guilds)}')
            
            try:
                user_cache = await client.fetch_user(ADMIN_USER_ID)
                await user_cache.send('🤖 **Бот запущен!** Готов принимать уведомления.')
                logger.info('✅ Приветствие отправлено админу в ЛС')
                # Запускаем обработчик очереди
                client.loop.create_task(process_notifications())
            except Exception as e:
                logger.warning(f'⚠️ Не удалось отправить приветствие: {e}')
        
        client.run(TOKEN)
    except Exception as e:
        logger.error(f'❌ Бот упал: {e}')
        logger.error(traceback.format_exc())

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
        
        if not client_ready:
            logger.error('❌ Бот не готов')
            return jsonify({"success": False, "error": "Bot not ready"}), 503
        
        # Добавляем в очередь вместо прямой отправки
        notification_queue.put({
            'survey_type': survey_type,
            'answer_data': answer_data,
            'answer_id': answer_id,
            'date_str': date_str
        })
        
        logger.info(f'📥 Уведомление добавлено в очередь (заявка #{answer_id})')
        return jsonify({"success": True, "message": "Queued"}), 200
        
    except Exception as e:
        logger.error(f'❌ Ошибка в /notify: {e}')
        logger.error(traceback.format_exc())
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
        "guilds": len(client.guilds) if client.user else 0,
        "queue_size": notification_queue.qsize()
    })

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == '__main__':
    logger.info('🚀 Запуск бота в фоне...')
    
    # Запускаем бота
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Ждем 5 секунд для запуска
    time.sleep(5)
    
    if client_ready:
        logger.info('✅ Бот успешно запущен!')
    else:
        logger.warning('⚠️ Бот не готов через 5 секунд')
    
    logger.info('🌐 Запуск Flask на порту 10000...')
    app.run(host='0.0.0.0', port=10000)
