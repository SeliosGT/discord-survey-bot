import discord
import os
import json
from datetime import datetime, timezone, timedelta
import asyncio
from flask import Flask, request, jsonify
import threading
import logging
import traceback
import time
import sys
from collections import deque

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

def format_datetime_msk(date_str):
    """Форматирует дату, добавляя 3 часа для МСК"""
    try:
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
            '%d.%m.%Y %H:%M:%S',
            '%d.%m.%Y %H:%M',
            '%d.%m.%Y'
        ]
        
        dt = None
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        
        if dt is None:
            return date_str
        
        # Просто добавляем 3 часа
        dt_msk = dt + timedelta(hours=3)
        
        return dt_msk.strftime('%d.%m.%Y %H:%M')
    except Exception as e:
        logger.warning(f'⚠️ Ошибка форматирования даты: {e}')
        return date_str

class NotificationBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin_user = None
        self.notification_queue = deque()
        self.processing_task = None
        
    async def setup_hook(self):
        self.processing_task = self.loop.create_task(self.process_notifications())
        logger.info('🔄 Задача обработки уведомлений создана')
    
    async def on_ready(self):
        logger.info(f'✅ Бот {self.user.name} запущен!')
        logger.info(f'📊 На серверах: {len(self.guilds)}')
        
        try:
            self.admin_user = await self.fetch_user(ADMIN_USER_ID)
            await self.admin_user.send('🤖 **Бот запущен!** Готов принимать уведомления.')
            logger.info('✅ Приветствие отправлено админу в ЛС')
        except Exception as e:
            logger.warning(f'⚠️ Не удалось отправить приветствие: {e}')
    
    async def on_message(self, message):
        if message.author.bot:
            return
    
    def create_notification_embed(self, data):
        """Создает красивое embed-сообщение"""
        answer_id = data['answer_id']
        survey_type = data['survey_type']
        answer_data = data['answer_data']
        date_str = data['date_str']
        
        formatted_date = format_datetime_msk(date_str)
        
        type_names = {
            'discipline': '🏛️ Дисциплинарный инспектор',
            'hr': '👔 HR-менеджер'
        }
        type_name = type_names.get(survey_type, '📋 Новая заявка')
        
        ic_name = answer_data.get('q1', 'Не указано')
        ooc_name = answer_data.get('q2', 'Не указано')
        
        # Создаем красивое текстовое описание
        description = (
            f"```ansi\n"
            f"🆔 Номер заявки      │ #{answer_id}\n"
            f"📋 Должность         │ {type_name}\n"
            f"👤 Имя персонажа (IC)│ {ic_name}\n"
            f"👤 Ваше имя (OOC)    │ {ooc_name}\n"
            f"📅 Дата подачи       │ {formatted_date}\n"
            f"🔗 Ссылка            │ Админ-панель\n"
            f"```"
        )
        
        embed = discord.Embed(
            title="🔔 Новая заявка!",
            description=description,
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.set_footer(text="by Rubi Antwoord")
        
        return embed
    
    async def process_notifications(self):
        await self.wait_until_ready()
        logger.info('🔄 Обработчик очереди запущен')
        
        while not self.is_closed():
            try:
                if self.notification_queue and self.admin_user:
                    data = self.notification_queue.popleft()
                    logger.info(f'📤 Отправка из очереди: заявка #{data["answer_id"]}')
                    
                    embed = self.create_notification_embed(data)
                    
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(
                        label="📋 Открыть админ-панель",
                        url=f"{SERVER_URL}/admin.html",
                        style=discord.ButtonStyle.link
                    ))
                    
                    await self.admin_user.send(
                        content=f"🔔 **Поступила новая заявка #{data['answer_id']}!**",
                        embed=embed,
                        view=view
                    )
                    
                    logger.info(f'✅ Уведомление отправлено (заявка #{data["answer_id"]})')
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f'❌ Ошибка обработки уведомления: {e}')
                logger.error(traceback.format_exc())
                await asyncio.sleep(1)
    
    def add_notification(self, survey_type, answer_data, answer_id, date_str):
        self.notification_queue.append({
            'survey_type': survey_type,
            'answer_data': answer_data,
            'answer_id': answer_id,
            'date_str': date_str
        })
        logger.info(f'📥 Уведомление #{answer_id} добавлено в очередь (всего: {len(self.notification_queue)})')

client = NotificationBot(intents=intents)

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
        
        logger.info(f'📨 Получен запрос: заявка #{answer_id}')
        
        if not client.is_ready():
            logger.error('❌ Бот не готов')
            return jsonify({"success": False, "error": "Bot not ready"}), 503
        
        if not client.admin_user:
            logger.error('❌ Админ не найден')
            return jsonify({"success": False, "error": "Admin user not found"}), 503
        
        client.add_notification(survey_type, answer_data, answer_id, date_str)
        
        return jsonify({
            "success": True, 
            "message": "Notification queued",
            "queue_size": len(client.notification_queue)
        }), 200
        
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
        "bot_ready": client.is_ready(),
        "bot_name": client.user.name if client.user else None,
        "guilds": len(client.guilds) if client.user else 0,
        "queue_size": len(client.notification_queue),
        "has_admin": client.admin_user is not None
    })

# ============================================================
# ЗАПУСК
# ============================================================

def run_bot():
    try:
        logger.info('🚀 Запуск бота...')
        client.run(TOKEN)
    except Exception as e:
        logger.error(f'❌ Бот упал: {e}')
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    logger.info('🚀 Запуск бота в фоне...')
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info('⏳ Ожидание готовности бота...')
    timeout = 30
    start_time = time.time()
    while not client.is_ready() and (time.time() - start_time) < timeout:
        time.sleep(1)
    
    if client.is_ready():
        logger.info('✅ Бот успешно запущен!')
    else:
        logger.warning(f'⚠️ Бот не готов после {timeout} секунд')
    
    logger.info('🌐 Запуск Flask на порту 10000...')
    app.run(host='0.0.0.0', port=10000)
