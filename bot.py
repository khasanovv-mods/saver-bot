import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import random
import time

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

# User-Agent
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

YDL_OPTS_BASE = {
    'quiet': False,  # Включаем логи для отладки
    'no_warnings': False,
    'extract_flat': False,
    'ignoreerrors': True,
    'no_check_certificate': True,
    'prefer_insecure': True,
    'cookiefile': 'cookies.txt',
    'user_agent': random.choice(USER_AGENTS),
    'headers': {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    },
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
            'skip': ['hls', 'dash'],
        }
    },
    'socket_timeout': 30,
    'retries': 10,
    'fragment_retries': 10,
    'continuedl': True,
}

def extract_urls(text):
    """Извлечение ссылок из текста"""
    url_pattern = re.compile(r'https?://[^\s]+', re.IGNORECASE)
    urls = url_pattern.findall(text)
    
    video_platforms = [
        'youtube.com', 'youtu.be',
        'tiktok.com', 'vm.tiktok.com',
        'instagram.com', 'instagr.am',
        'rutube.ru',
        'pinterest.com', 'pin.it',
        'twitter.com', 'x.com',
        'reddit.com',
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
    
    # Используем простое имя файла без спецсимволов
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
        "• YouTube (включая Shorts) ✅\n"
        "• TikTok (без водяного знака) ✅\n"
        "• RuTube, Instagram, Pinterest ✅\n\n"
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
    status_msg = await update.message.reply_text("🔄 Получаю информацию о видео...")
    
    # Пробуем получить информацию
    info = await get_video_info_with_retry(url)
    
    if not info:
        await status_msg.edit_text(
            "❌ Не удалось получить информацию.\n\n"
            "Возможные причины:\n"
            "• Видео приватное или удалено\n"
            "• Неправильный формат ссылки\n"
            "• Проблемы с авторизацией\n\n"
            "💡 Попробуйте:\n"
            "• Отправить ссылку еще раз\n"
            "• Проверить, что видео доступно\n"
            "• Использовать ссылку с другого ресурса"
        )
        return
    
    # Обработка информации
    title = info.get('title', 'video')
    if len(title) > 60:
        title = title[:57] + "..."
    
    duration = info.get('duration', 0)
    duration_str = f"⏱️ {duration // 60}:{duration % 60:02d}" if duration else ""
    
    context.user_data['title'] = title
    context.user_data['video_id'] = info.get('id', '')
    
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

async def get_video_info_with_retry(url):
    """Получение информации с несколькими попытками"""
    clients = ['android', 'web']
    
    for client in clients:
        try:
            logger.info(f"Пробуем клиент: {client}")
            opts = YDL_OPTS_BASE.copy()
            opts['user_agent'] = random.choice(USER_AGENTS)
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': [client],
                }
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    if info.get('_type') == 'playlist' and info.get('entries'):
                        info = info['entries'][0]
                    logger.info(f"Успешно с клиентом: {client}")
                    return info
        except Exception as e:
            logger.error(f"Клиент {client} не сработал: {e}")
            continue
    
    return None

def find_downloaded_file(download_dir, timeout=10):
    """Находит последний скачанный файл"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        files = list(download_dir.glob('*.*'))
        if files:
            # Сортируем по времени изменения
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            newest = files[0]
            # Проверяем, что файл не слишком старый (не старше 30 секунд)
            if time.time() - newest.stat().st_mtime < 30:
                return newest
        time.sleep(0.5)
    return None

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
        logger.info(f"Начинаем скачивание: {url}, качество: {quality}")
        
        # Очищаем старые файлы перед скачиванием
        for old_file in DOWNLOAD_DIR.glob('*.*'):
            if time.time() - old_file.stat().st_mtime > 60:  # Старше минуты
                try:
                    old_file.unlink()
                except:
                    pass
        
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        
        await asyncio.to_thread(download)
        
        # Ищем скачанный файл
        filename = None
        files = list(DOWNLOAD_DIR.glob('*.*'))
        
        if files:
            # Сортируем по времени создания
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            filename = files[0]
            logger.info(f"Найден файл: {filename}")
        else:
            # Пробуем найти файл с задержкой
            await asyncio.sleep(2)
            files = list(DOWNLOAD_DIR.glob('*.*'))
            if files:
                files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                filename = files[0]
                logger.info(f"Найден файл после задержки: {filename}")
        
        if not filename or not os.path.exists(filename):
            logger.error("Файл не найден")
            await query.edit_message_text(
                "❌ Файл не найден после скачивания.\n"
                "Попробуйте другое качество или ссылку."
            )
            return
        
        filename = str(filename)
        file_size = os.path.getsize(filename)
        logger.info(f"Размер файла: {file_size} байт")
        
        if file_size > MAX_FILE_SIZE:
            os.remove(filename)
            await query.edit_message_text(
                f"❌ Файл слишком большой ({file_size / (1024*1024):.1f} МБ).\n"
                f"Лимит: 50 МБ.\n"
                "Попробуйте качество ниже."
            )
            return
        
        # Отправляем файл
        title = context.user_data.get('title', 'video')
        ext = os.path.splitext(filename)[1].lower()
        
        try:
            if quality == 'audio' or ext == '.mp3':
                with open(filename, 'rb') as f:
                    await query.message.reply_audio(
                        f,
                        title=title,
                        performer="Video Downloader",
                        write_timeout=60,
                        read_timeout=60
                    )
            else:
                with open(filename, 'rb') as f:
                    await query.message.reply_video(
                        f,
                        caption=f"📹 {title}",
                        supports_streaming=True,
                        write_timeout=60,
                        read_timeout=60
                    )
            
            os.remove(filename)
            await query.edit_message_text("✅ Готово! Видео отправлено.")
            
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            await query.edit_message_text(f"❌ Ошибка отправки: {str(e)[:100]}")
        
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)[:150]}")

def main():
    # Проверяем наличие cookies
    if os.path.exists('cookies.txt'):
        logger.info("✅ Файл cookies.txt найден!")
    else:
        logger.warning("⚠️ Файл cookies.txt не найден!")
    
    # Проверяем наличие ffmpeg
    import subprocess
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True)
        logger.info("✅ FFmpeg установлен")
    except:
        logger.warning("⚠️ FFmpeg не найден!")
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern="^quality_"))
    
    logger.info("🚀 Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
