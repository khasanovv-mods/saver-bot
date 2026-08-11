import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import random
import time
import subprocess
import json

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

# НОВЫЙ подход для YouTube - используем только мобильные форматы
YDL_OPTS_BASE = {
    'quiet': False,
    'no_warnings': False,
    'ignoreerrors': True,
    'no_check_certificate': True,
    'prefer_insecure': True,
    'cookiefile': 'cookies.txt',
    'user_agent': 'Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
    'headers': {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    },
    'extractor_args': {
        'youtube': {
            'player_client': ['android'],
            'skip': ['dash', 'hls'],
            'player_skip': ['configs', 'webpage', 'js'],
            'innertube_client': 'ANDROID',
            'formats': 'best',
        }
    },
    'socket_timeout': 60,
    'retries': 10,
    'fragment_retries': 10,
    'continuedl': True,
}

def get_ydl_opts(quality='best'):
    """Настройки для скачивания"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    opts = YDL_OPTS_BASE.copy()
    
    # Только мобильные форматы (они лучше работают)
    if quality == 'best':
        opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]'
    elif quality == 'high':
        opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]'
    elif quality == 'medium':
        opts['format'] = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]'
    elif quality == 'audio':
        opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    
    opts['merge_output_format'] = 'mp4'
    opts['outtmpl'] = str(DOWNLOAD_DIR / f'video_{timestamp}.%(ext)s')
    return opts

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
        'vimeo.com',
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"🎬 Привет, {user.first_name}!\n\n"
        "Я скачиваю видео с разных платформ:\n"
        "• YouTube (включая Shorts) ⚠️ может не работать\n"
        "• TikTok ✅\n"
        "• Instagram ✅\n"
        "• RuTube ✅\n\n"
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
    info = await get_video_info_simple(url)
    
    if not info:
        # Пробуем альтернативный метод
        info = await get_video_info_alternative(url)
    
    if not info:
        await status_msg.edit_text(
            "❌ Не удалось получить информацию.\n\n"
            "Для YouTube:\n"
            "• Попробуйте обновить yt-dlp: pip install --upgrade yt-dlp\n"
            "• Обновите cookies (зайдите на YouTube)\n"
            "• Используйте другое видео\n\n"
            "Для TikTok/Instagram - должно работать."
        )
        return
    
    title = info.get('title', 'video')[:60]
    duration = info.get('duration', 0)
    duration_str = f"⏱️ {duration // 60}:{duration % 60:02d}" if duration else ""
    
    context.user_data['title'] = title
    
    keyboard = [
        [InlineKeyboardButton("🎥 Лучшее", callback_data="quality_best")],
        [InlineKeyboardButton("📱 720p", callback_data="quality_high")],
        [InlineKeyboardButton("📱 480p", callback_data="quality_medium")],
        [InlineKeyboardButton("🎵 Аудио MP3", callback_data="quality_audio")],
    ]
    
    await status_msg.edit_text(
        f"📹 *{title}*\n{duration_str}\n\nВыберите качество:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def get_video_info_simple(url):
    """Простой метод получения информации"""
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'cookiefile': 'cookies.txt',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'extract_flat': False,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                }
            }
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                if info.get('_type') == 'playlist' and info.get('entries'):
                    info = info['entries'][0]
                return info
    except Exception as e:
        logger.error(f"Simple method failed: {e}")
    return None

async def get_video_info_alternative(url):
    """Альтернативный метод получения информации"""
    try:
        # Используем внешний API для YouTube
        import requests
        
        # Пробуем получить через youtube-dl (старая версия)
        import subprocess
        result = subprocess.run(
            ['yt-dlp', '--dump-json', '--no-download', '--cookies', 'cookies.txt', url],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return info
    except Exception as e:
        logger.error(f"Alternative method failed: {e}")
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
    
    await query.edit_message_text(f"⏳ Скачиваю *{quality.upper()}*...\nЭто может занять время.", parse_mode='Markdown')
    
    try:
        ydl_opts = get_ydl_opts(quality)
        
        # Очищаем старые файлы
        for old_file in DOWNLOAD_DIR.glob('*.*'):
            if time.time() - old_file.stat().st_mtime > 120:
                try:
                    old_file.unlink()
                except:
                    pass
        
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        
        await asyncio.to_thread(download)
        
        # Ищем скачанный файл
        await asyncio.sleep(2)
        files = list(DOWNLOAD_DIR.glob('*.*'))
        
        if not files:
            await query.edit_message_text("❌ Файл не найден после скачивания.")
            return
        
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        filename = str(files[0])
        logger.info(f"Найден файл: {filename}")
        
        file_size = os.path.getsize(filename)
        if file_size > MAX_FILE_SIZE:
            os.remove(filename)
            await query.edit_message_text(
                f"❌ Файл слишком большой ({file_size / (1024*1024):.1f} МБ).\n"
                f"Лимит: 50 МБ."
            )
            return
        
        title = context.user_data.get('title', 'video')
        ext = os.path.splitext(filename)[1].lower()
        
        try:
            if quality == 'audio' or ext == '.mp3':
                with open(filename, 'rb') as f:
                    await query.message.reply_audio(
                        f,
                        title=title,
                        performer="Video Downloader"
                    )
            else:
                with open(filename, 'rb') as f:
                    await query.message.reply_video(
                        f,
                        caption=f"📹 {title}",
                        supports_streaming=True
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
    # Проверка
    if os.path.exists('cookies.txt'):
        logger.info("✅ cookies.txt найден")
    else:
        logger.warning("⚠️ cookies.txt не найден!")
    
    # Проверка версии yt-dlp
    try:
        import yt_dlp
        logger.info(f"yt-dlp version: {yt_dlp.version.__version__}")
    except:
        pass
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern="^quality_"))
    
    logger.info("🚀 Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
