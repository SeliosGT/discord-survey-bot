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
import re
from collections import deque
import signal

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
SERVER_URL = os.environ.get('SERVER_URL', 'https://opros-app.onrender.com')

# Парсим список администраторов из переменной окружения
# Пример: ADMIN_USER_IDS=123456789,987654321,111222333
ADMIN_USER_IDS_STR = os.environ.get('ADMIN_USER_IDS', '')
ADMIN_USER_ID = int(os.environ.get('ADMIN_USER_ID', '0'))  # для обратной совместимости

# Собираем ID в список
admin_ids = []
if ADMIN_USER_IDS_STR:
    admin_ids = [int(x.strip()) for x in ADMIN_USER_IDS_STR.split(',') if x.strip().isdigit()]
elif ADMIN_USER_ID != 0:
    admin_ids = [ADMIN_USER_ID]

if not admin_ids:
    logger.error("❌ ADMIN_USER_IDS не найден! Добавьте переменную окружения.")
    logger.error("   Пример: ADMIN_USER_IDS=123456789,987654321")
    sys.exit(1)

logger.info(f'🔑 Токен найден: {TOKEN[:10]}...')
logger.info(f'👤 Администраторы: {admin_ids}')

# ============================================================
# НАСТРОЙКА DISCORD
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True

class NotificationBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin_ids = admin_ids
        self.notification_queue = deque()
        self.processing_task = None
        self.processed_ids = set()
        self.shutting_down = False
        
    async def setup_hook(self):
        self.processing_task = self.loop.create_task(self.process_notifications())
        logger.info('🔄 Задача обработки уведомлений создана')
    
    async def on_ready(self):
        logger.info(f'✅ Бот {self.user.name} запущен!')
        logger.info(f'📊 На серверах: {len(self.guilds)}')
        
        # Отправляем приветствие всем админам
        for admin_id in self.admin_ids:
            try:
                user = await self.fetch_user(admin_id)
                await user.send('🤖 **Бот запущен!** Готов принимать уведомления о новых заявках.')
                logger.info(f'✅ Приветствие отправлено админу {admin_id}')
            except discord.Forbidden:
                logger.warning(f'⚠️ Бот не может писать админу {admin_id}. Добавьте бота в друзья.')
            except Exception as e:
                logger.warning(f'⚠️ Не удалось отправить приветствие админу {admin_id}: {e}')
    
    async def on_message(self, message):
        if message.author.bot:
            return
    
    def format_date_with_offset(self, date_str):
        """Добавляет 3 часа к дате (МСК) и форматирует"""
        if not date_str:
            return "неизвестно"
        
        logger.info(f'📅 Обработка даты: "{date_str}"')
        
        # Убираем (МСК) если есть
        clean_date = re.sub(r'\s*\(МСК\)\s*', '', date_str)
        
        # Ищем время в строке (HH:MM)
        time_match = re.search(r'(\d{2}):(\d{2})', clean_date)
        if time_match:
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
            new_hours = (hours + 3) % 24
            
            formatted_date = clean_date[:time_match.start(1)] + f'{new_hours:02d}:{minutes:02d}' + clean_date[time_match.end(2):]
            logger.info(f'✅ {date_str} -> {formatted_date}')
            return formatted_date
        
        # Запасной вариант: пробуем распарсить через datetime
        try:
            dt = datetime.strptime(clean_date.strip(), '%d.%m.%Y %H:%M')
            dt = dt + timedelta(hours=3)
            return dt.strftime('%d.%m.%Y %H:%M')
        except ValueError:
            logger.warning(f'⚠️ Не удалось распарсить дату: {date_str}')
            return date_str
    
    def create_notification_embed(self, data):
        """Создает красивое embed-сообщение"""
        answer_id = data['answer_id']
        survey_type = data['survey_type']
        answer_data = data['answer_data']
        date_str = data['date_str']
        
        formatted_date = self.format_date_with_offset(date_str)
        
        type_names = {
            'discipline': '🏛️ Дисциплинарный инспектор',
            'hr': '👔 HR-менеджер'
        }
        type_name = type_names.get(survey_type, '📋 Новая заявка')
        
        ic_name = answer_data.get('q1', 'Не указано')
        ooc_name = answer_data.get('q2', 'Не указано')
        motivation = answer_data.get('motivation', '')
        
        # Формируем описание с моноширинным форматированием
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
        
        # Добавляем мотивацию, если есть
        if motivation and len(motivation) > 10:
            embed.add_field(
                name="📜 Мотивация",
                value=motivation[:300] + ('...' if len(motivation) > 300 else ''),
                inline=False
            )
        
        embed.set_footer(text="by Rubi Antwoord")
        
        return embed
    
    async def process_notifications(self):
        """Обработчик очереди уведомлений"""
        await self.wait_until_ready()
        logger.info('🔄 Обработчик очереди запущен')
        
        while not self.is_closed() and not self.shutting_down:
            try:
                if self.notification_queue:
                    data = self.notification_queue.popleft()
                    answer_id = data["answer_id"]
                    
                    # Защита от дублей
                    if answer_id in self.processed_ids:
                        logger.info(f'⏩ Заявка #{answer_id} уже обработана, пропускаем')
                        continue
                    
                    logger.info(f'📤 Отправка из очереди: заявка #{answer_id}')
                    
                    embed = self.create_notification_embed(data)
                    
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(
                        label="📋 Открыть админ-панель",
                        url=f"{SERVER_URL}/admin.html",
                        style=discord.ButtonStyle.link
                    ))
                    
                    # ============================================================
                    # ОТПРАВКА ВСЕМ АДМИНАМ
                    # ============================================================
                    success_count = 0
                    for admin_id in self.admin_ids:
                        try:
                            user = self.get_user(admin_id)
                            if not user:
                                user = await self.fetch_user(admin_id)
                            
                            await user.send(
                                content=f"🔔 **Новая заявка #{answer_id}!**",
                                embed=embed,
                                view=view
                            )
                            success_count += 1
                            logger.info(f'✅ Уведомление отправлено админу {admin_id}')
                            
                        except discord.Forbidden:
                            logger.warning(f'⚠️ Бот не может писать админу {admin_id}. Добавьте бота в друзья.')
                        except Exception as e:
                            logger.error(f'❌ Ошибка отправки админу {admin_id}: {e}')
                    
                    logger.info(f'📊 Уведомления отправлены: {success_count}/{len(self.admin_ids)}')
                    
                    # Отмечаем заявку как обработанную
                    self.processed_ids.add(answer_id)
                    
                    # Ограничиваем размер кеша
                    if len(self.processed_ids) > 1000:
                        self.processed_ids.clear()
                
                await asyncio.sleep(0.5)
                
            except discord.HTTPException as e:
                if e.status == 429:
                    logger.warning(f'⏳ Rate limit, ждём 5 секунд...')
                    await asyncio.sleep(5)
                else:
                    logger.error(f'❌ HTTP ошибка: {e.status} - {e.text}')
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f'❌ Ошибка обработки уведомления: {e}')
                logger.error(traceback.format_exc())
                await asyncio.sleep(1)
    
    def add_notification(self, survey_type, answer_data, answer_id, date_str):
        """Добавляет уведомление в очередь"""
        # Проверяем, не было ли уже такой заявки
        if answer_id in self.processed_ids:
            logger.info(f'⏩ Заявка #{answer_id} уже обработана, игнорируем')
            return False
        
        # Проверяем, нет ли уже в очереди
        for item in self.notification_queue:
            if item['answer_id'] == answer_id:
                logger.info(f'⏩ Заявка #{answer_id} уже в очереди, игнорируем')
                return False
        
        self.notification_queue.append({
            'survey_type': survey_type,
            'answer_data': answer_data,
            'answer_id': answer_id,
            'date_str': date_str
        })
        logger.info(f'📥 Уведомление #{answer_id} добавлено в очередь (всего: {len(self.notification_queue)})')
        return True

client = NotificationBot(intents=intents)

# ============================================================
# ГРАЦИОЗНОЕ ЗАВЕРШЕНИЕ
# ============================================================

def handle_shutdown(signum, frame):
    logger.info('🛑 Получен сигнал завершения')
    client.shutting_down = True
    if client.processing_task:
        client.processing_task.cancel()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

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
        logger.info(f'📅 Исходная дата: "{date_str}"')
        
        if not client.is_ready():
            logger.error('❌ Бот не готов')
            return jsonify({"success": False, "error": "Bot not ready"}), 503
        
        added = client.add_notification(survey_type, answer_data, answer_id, date_str)
        
        return jsonify({
            "success": True, 
            "message": "Notification queued" if added else "Already processed",
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
        "admin_count": len(client.admin_ids),
        "processed_count": len(client.processed_ids)
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
