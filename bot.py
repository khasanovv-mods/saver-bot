import os
import re
import logging
from pathlib import Path
from datetime import datetime
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "8723588644:AAHKrHAqxmR5_C-K6gWGauS86fDpL3TLS7g"
MAX_FILE_SIZE = 50 * 1024 * 1024

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# User-Agent для обхода блокировок
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# ОПТИМИЗИРОВАННЫЕ настройки для YouTube
YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'ignoreerrors': True,
    'no_check_certificate': True,
    'prefer_insecure': True,
    # ВАЖНО: указываем файл с cookies
    'cookiefile': 'cookies.txt',
    'user_agent': random.choice(USER_AGENTS),
    'headers': {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
    },
    'extractor_args': {
        'youtube': {
            # Пробуем разные клиенты
            'player_client': ['android', 'web', 'ios'],
            'skip': ['hls', 'dash'],
            'innertube_client': ['ANDROID', 'WEB'],
        }
    },
    # Таймауты
    'socket_timeout': 30,
    'retries': 10,
    'fragment_retries': 10,
}

def extract_urls(text):
    """Извлечение ссылок из текста"""
    url_pattern = re.compile(r'https?://[^\s]+', re.IGNORECASE)
    urls = url_pattern.findall(text)
    
    video_platforms = [
        'youtube.com', 'youtu.be',
        'tiktok.com', 'vm.tiktok.com',
        'instagram.com', 'instagr.am',
        'pinterest.com', 'pin.it',
        'twitter.com', 'x.com',
        'reddit.com', 'redd.it',
        'facebook.com', 'fb.com',
        'vimeo.com', 'dailymotion.com',
        'vk.com', 'twitch.tv'
    ]
    
    video_urls = []
    for url in urls:
        url_lower = url.lower()
        for platform in video_platforms:
            if platform in url_lower:
                video_urls.append(url)
                break
    
    return video_urls

def get_ydl_opts(quality='best'):
    """Настройки для скачивания"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    opts = YDL_OPTS_BASE.copy()
    opts['user_agent'] = random.choice(USER_AGENTS)
    
    if quality == 'best':
        opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        opts['merge_output_format'] = 'mp4'
        opts['outtmpl'] = str(DOWNLOAD_DIR / f'video_best_{timestamp}.%(ext)s')
    elif quality == 'high':
        opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
        opts['merge_output_format'] = 'mp4'
        opts['outtmpl'] = str(DOWNLOAD_DIR / f'video_1080p_{timestamp}.%(ext)s')
    elif quality == 'medium':
        opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
        opts['merge_output_format'] = 'mp4'
        opts['outtmpl'] = str(DOWNLOAD_DIR / f'video_720p_{timestamp}.%(ext)s')
    elif quality == 'low':
        opts['format'] = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best'
        opts['merge_output_format'] = 'mp4'
        opts['outtmpl'] = str(DOWNLOAD_DIR / f'video_480p_{timestamp}.%(ext)s')
    elif quality == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        opts['outtmpl'] = str(DOWNLOAD_DIR / f'audio_{timestamp}.%(ext)s')
    
    return opts

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"🎬 Привет, {user.first_name}!\n\n"
        "Я скачиваю видео без водяных знаков:\n"
        "• YouTube (включая Shorts)\n"
        "• TikTok, Instagram, Pinterest\n"
        "• Twitter/X, Reddit, VK\n"
        "• И другие платформы\n\n"
        "📌 Просто отправь ссылку!\n\n"
        "⚠️ Лимит: до 50 МБ"
    )
    await update.message.reply_text(welcome_text)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    text = update.message.text
    urls = extract_urls(text)
    
    if not urls:
        await update.message.reply_text(
            "🤔 Я не нашел ссылок на видео.\n"
            "Отправьте ссылку с YouTube, TikTok, Instagram и т.д."
        )
        return
    
    url = urls[0]
    if len(urls) > 1:
        await update.message.reply_text(f"🔍 Найдено {len(urls)} ссылок. Беру первую:\n{url}")
    
    context.user_data['url'] = url
    status_msg = await update.message.reply_text("🔄 Получаю информацию...")
    
    # Пробуем получить информацию
    info = await get_video_info(url)
    
    if not info:
        await status_msg.edit_text(
            "❌ Не удалось получить информацию.\n\n"
            "💡 Решение: нужно добавить cookies!\n\n"
            "1. Установите расширение 'Get cookies.txt' в браузере\n"
            "2. Зайдите на YouTube и авторизуйтесь\n"
            "3. Экспортируйте cookies в файл cookies.txt\n"
            "4. Загрузите файл на BotHost в папку с ботом\n\n"
            "Или попробуйте отправить ссылку позже."
        )
        return
    
    # Обработка информации
    title = info.get('title', 'video')[:60]
    duration = info.get('duration', 0)
    duration_str = f"⏱️ {duration // 60}:{duration % 60:02d}" if duration else ""
    
    context.user_data['title'] = title
    
    keyboard = [
        [InlineKeyboardButton("🎥 Лучшее", callback_data="quality_best")],
        [InlineKeyboardButton("📱 1080p", callback_data="quality_high"),
         InlineKeyboardButton("📱 720p", callback_data="quality_medium")],
        [InlineKeyboardButton("📱 480p", callback_data="quality_low")],
        [InlineKeyboardButton("🎵 Аудио MP3", callback_data="quality_audio")],
    ]
    
    await status_msg.edit_text(
        f"📹 *{title}*\n{duration_str}\n\nВыберите качество:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def get_video_info(url):
    """Получение информации с несколькими попытками"""
    methods = [
        lambda: get_info_with_opts(url, 'android'),
        lambda: get_info_with_opts(url, 'web'),
        lambda: get_info_with_opts(url, 'ios'),
    ]
    
    for method in methods:
        try:
            info = await asyncio.to_thread(method)
            if info:
                return info
        except Exception as e:
            logger.error(f"Method failed: {e}")
            continue
    
    return None

def get_info_with_opts(url, client='android'):
    """Получение информации с определенным клиентом"""
    opts = YDL_OPTS_BASE.copy()
    opts['user_agent'] = random.choice(USER_AGENTS)
    opts['extractor_args'] = {
        'youtube': {
            'player_client': [client],
            'innertube_client': client.upper(),
        }
    }
    
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info and info.get('_type') == 'playlist' and info.get('entries'):
            info = info['entries'][0]
        return info

async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора качества"""
    query = update.callback_query
    await query.answer()
    
    quality = query.data.replace('quality_', '')
    url = context.user_data.get('url')
    
    if not url:
        await query.edit_message_text("❌ Ссылка не найдена. Отправьте заново.")
        return
    
    await query.edit_message_text(f"⏳ Скачиваю *{quality.upper()}*...", parse_mode='Markdown')
    
    try:
        ydl_opts = get_ydl_opts(quality)
        
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        
        await asyncio.to_thread(download)
        
        # Ищем скачанный файл
        files = list(DOWNLOAD_DIR.glob('*.*'))
        if not files:
            await query.edit_message_text("❌ Файл не найден.")
            return
        
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        filename = str(files[0])
        
        # Проверка размера
        file_size = os.path.getsize(filename)
        if file_size > MAX_FILE_SIZE:
            os.remove(filename)
            await query.edit_message_text(
                f"❌ Файл слишком большой ({file_size / (1024*1024):.1f} МБ).\n"
                f"Лимит: 50 МБ."
            )
            return
        
        # Отправка
        title = context.user_data.get('title', 'video')
        ext = os.path.splitext(filename)[1].lower()
        
        if quality == 'audio' or ext == '.mp3':
            with open(filename, 'rb') as f:
                await query.message.reply_audio(f, title=title)
        else:
            with open(filename, 'rb') as f:
                await query.message.reply_video(f, caption=f"📹 {title}")
        
        os.remove(filename)
        await query.edit_message_text("✅ Готово!")
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)[:150]}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern="^quality_"))
    
    logger.info("🚀 Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    import asyncio
    main()
