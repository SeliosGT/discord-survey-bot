import discord
import os
import requests
import json
from datetime import datetime
import asyncio
from flask import Flask, request, jsonify
import threading
import logging

# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# НАСТРОЙКА БОТА
# ============================================================

TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
ADMIN_USER_ID = int(os.environ.get('ADMIN_USER_ID', '0'))
SERVER_URL = os.environ.get('SERVER_URL', 'https://opros-app.onrender.com')

if not TOKEN:
    logger.error("❌ DISCORD_BOT_TOKEN не найден! Добавьте переменную окружения.")
    exit(1)

if ADMIN_USER_ID == 0:
    logger.error("❌ ADMIN_USER_ID не найден! Добавьте переменную окружения.")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True

client = discord.Client(intents=intents)

# ============================================================
# СОБЫТИЕ: БОТ ГОТОВ
# ============================================================

@client.event
async def on_ready():
    logger.info(f'✅ Бот {client.user.name} запущен!')
    logger.info(f'📊 На серверах: {len(client.guilds)}')
    
    # Пробуем отправить тестовое сообщение админу
    try:
        user = await client.fetch_user(ADMIN_USER_ID)
        
        # Проверяем, можем ли писать в ЛС
        try:
            await user.send('🤖 **Бот запущен!** Готов принимать уведомления о новых заявках.')
            logger.info('✅ Приветствие отправлено админу в ЛС')
        except discord.Forbidden:
            logger.warning('⚠️ Бот не может писать админу в ЛС! Добавьте бота в друзья.')
            
            # Пробуем найти сервер, где есть админ
            for guild in client.guilds:
                member = guild.get_member(ADMIN_USER_ID)
                if member:
                    try:
                        # Пытаемся отправить в общий канал
                        for channel in guild.text_channels:
                            if channel.permissions_for(guild.me).send_messages:
                                await channel.send(f'🤖 **Бот запущен!**\n👤 Админ: {member.mention}\n📌 Добавьте бота в друзья для получения уведомлений в ЛС.')
                                logger.info(f'✅ Сообщение отправлено в канал #{channel.name}')
                                break
                        break
                    except:
                        pass
                    
    except Exception as e:
        logger.error(f'⚠️ Ошибка при отправке приветствия: {e}')

@client.event
async def on_message(message):
    if message.author.bot:
        return

# ============================================================
# ФУНКЦИЯ: ОТПРАВКА УВЕДОМЛЕНИЯ
# ============================================================

async def send_notification(survey_type, answer_data, answer_id, date_str):
    """Отправляет уведомление админу в ЛС"""
    try:
        user = await client.fetch_user(ADMIN_USER_ID)
        
        type_names = {
            'discipline': '🏛️ Дисциплинарный инспектор',
            'hr': '👔 HR-менеджер'
        }
        type_name = type_names.get(survey_type, '📋 Новая заявка')
        
        # Создаём красивое Embed-сообщение
        embed = discord.Embed(
            title="🔔 **Новая заявка!**",
            color=0x5865F2,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="🆔 Номер заявки", value=f"`#{answer_id}`", inline=True)
        embed.add_field(name="📋 Куда устроиться", value=type_name, inline=True)
        embed.add_field(name="👤 Имя персонажа (IC)", value=answer_data.get('q1', '—'), inline=True)
        embed.add_field(name="👤 Ваше имя (OOC)", value=answer_data.get('q2', '—'), inline=True)
        embed.add_field(name="📅 Дата подачи", value=date_str, inline=True)
        embed.add_field(name="🔗 Ссылка", value=f"[Открыть админ-панель]({SERVER_URL}/admin.html)", inline=False)
        
        # Мотивация (если есть)
        motivation = answer_data.get('motivation', '')
        if motivation:
            embed.add_field(
                name="📜 Мотивация",
                value=motivation[:200] + ('...' if len(motivation) > 200 else ''),
                inline=False
            )
        
        embed.set_footer(
            text="by Rubi Antwoord",
            icon_url="https://cdn-icons-png.flaticon.com/512/3196/3196109.png"
        )
        
        # Кнопка-ссылка
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="📋 Перейти к админ-панели",
            url=f"{SERVER_URL}/admin.html",
            style=discord.ButtonStyle.link
        ))
        
        # Отправляем в ЛС
        await user.send(content=f"🔔 **Поступила новая заявка #{answer_id}!**", embed=embed, view=view)
        logger.info(f'✅ Уведомление отправлено админу (заявка #{answer_id})')
        
    except discord.Forbidden:
        logger.warning(f'⚠️ Бот не может писать админу в ЛС! Добавьте бота в друзья.')
    except Exception as e:
        logger.error(f'⚠️ Ошибка отправки уведомления: {e}')

# ============================================================
# ВЕБ-СЕРВЕР ДЛЯ ПРИЁМА ЗАПРОСОВ
# ============================================================

app = Flask(__name__)

@app.route('/notify', methods=['POST'])
def notify():
    """Принимает POST-запрос от основного сервера"""
    try:
        data = request.json
        survey_type = data.get('survey_type')
        answer_data = data.get('answer_data')
        answer_id = data.get('answer_id')
        date_str = data.get('date_str')
        
        logger.info(f'📨 Получен запрос на уведомление: заявка #{answer_id}, тип: {survey_type}')
        
        # Запускаем отправку в фоновом режиме
        asyncio.create_task(send_notification(survey_type, answer_data, answer_id, date_str))
        
        return jsonify({"success": True}), 200
        
    except Exception as e:
        logger.error(f'⚠️ Ошибка в /notify: {e}')
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/')
def index():
    return "🤖 Discord Survey Bot is running!"

@app.route('/ping')
def ping():
    """Эндпоинт для Uptime Robot"""
    return "pong"

# ============================================================
# ЗАПУСК БОТА В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================

def run_bot():
    try:
        client.run(TOKEN)
    except Exception as e:
        logger.error(f'❌ Ошибка запуска бота: {e}')

if __name__ == '__main__':
    logger.info('🚀 Запуск бота...')
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запускаем Flask-сервер
    logger.info('🌐 Запуск веб-сервера на порту 8080...')
    app.run(host='0.0.0.0', port=8080)
