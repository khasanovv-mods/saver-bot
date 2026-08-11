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

# ОПТИМИЗИРОВАННЫЕ настройки для разных платформ
def get_ydl_opts(quality='best', platform='youtube'):
    """Настройки для скачивания в зависимости от платформы"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Базовые настройки для всех платформ
    base_opts = {
        'quiet': False,
        'no_warnings': False,
        'ignoreerrors': True,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'cookiefile': 'cookies.txt',
        'socket_timeout': 60,
        'retries': 20,
        'fragment_retries': 20,
        'continuedl': True,
        'sleep_interval': 2,
        'max_sleep_interval': 5,
    }
    
    if platform == 'tiktok':
        # СПЕЦИАЛЬНЫЕ настройки для TikTok
        opts = {
            **base_opts,
            'user_agent': 'Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
            'headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
            },
            'extractor_args': {
                'tiktok': {
                    'prefer_quality': 'high',
                    'extract_watermark': False,  # Без водяного знака
                }
            },
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'merge_output_format': 'mp4',
            'outtmpl': str(DOWNLOAD_DIR / f'tiktok_{timestamp}.%(ext)s'),
        }
        
        # Для аудио
        if quality == 'audio':
            opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            opts['outtmpl'] = str(DOWNLOAD_DIR / f'tiktok_audio_{timestamp}.%(ext)s')
        
        return opts
    
    else:  # youtube и другие
        # НАСТРОЙКИ ДЛЯ YOUTUBE (обновленные)
        opts = {
            **base_opts,
            'user_agent': random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            ]),
            'headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
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
                    'player_client': ['android', 'web'],
                    'skip': ['dash', 'hls'],
                    'player_skip': ['configs', 'webpage'],
                    'innertube_client': ['ANDROID', 'WEB'],
                }
            },
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'merge_output_format': 'mp4',
            'outtmpl': str(DOWNLOAD_DIR / f'youtube_{timestamp}.%(ext)s'),
        }
        
        # Для аудио
        if quality == 'audio':
            opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            opts['outtmpl'] = str(DOWNLOAD_DIR / f'youtube_audio_{timestamp}.%(ext)s')
        
        return opts

def detect_platform(url):
    """Определяет платформу по ссылке"""
    url_lower = url.lower()
    if any(x in url_lower for x in ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com']):
        return 'tiktok'
    elif any(x in url_lower for x in ['youtube.com', 'youtu.be']):
        return 'youtube'
    elif any(x in url_lower for x in ['instagram.com', 'instagr.am']):
        return 'instagram'
    elif 'rutube.ru' in url_lower:
        return 'rutube'
    elif any(x in url_lower for x in ['pinterest.com', 'pin.it']):
        return 'pinterest'
    else:
        return 'other'

def extract_urls(text):
    """Извлечение ссылок из текста"""
    url_pattern = re.compile(r'https?://[^\s]+', re.IGNORECASE)
    urls = url_pattern.findall(text)
    
    video_platforms = [
        'youtube.com', 'youtu.be',
        'tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com',
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
        "• TikTok ✅ (без водяного знака)\n"
        "• Instagram ✅\n"
        "• RuTube, Pinterest ✅\n\n"
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
    platform = detect_platform(url)
    context.user_data['platform'] = platform
    
    status_msg = await update.message.reply_text(f"🔄 Получаю информацию о видео с {platform.upper()}...")
    
    # Пробуем получить информацию
    info = await get_video_info(url, platform)
    
    if not info:
        await status_msg.edit_text(
            f"❌ Не удалось получить информацию с {platform.upper()}.\n\n"
            "Возможные причины:\n"
            "• Видео приватное или удалено\n"
            "• Платформа обновила защиту\n"
            "• Проблемы с авторизацией\n\n"
            "💡 Попробуйте:\n"
            "• Отправить ссылку еще раз\n"
            "• Использовать другое видео"
        )
        return
    
    title = info.get('title', 'video')[:60]
    duration = info.get('duration', 0)
    duration_str = f"⏱️ {duration // 60}:{duration % 60:02d}" if duration else ""
    
    context.user_data['title'] = title
    
    keyboard = [
        [InlineKeyboardButton("🎥 Лучшее качество", callback_data="quality_best")],
        [InlineKeyboardButton("📱 720p", callback_data="quality_high")],
        [InlineKeyboardButton("📱 480p", callback_data="quality_medium")],
        [InlineKeyboardButton("🎵 Аудио MP3", callback_data="quality_audio")],
    ]
    
    await status_msg.edit_text(
        f"📹 *{title}*\n{duration_str}\n\nВыберите качество:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def get_video_info(url, platform):
    """Получение информации о видео"""
    try:
        if platform == 'tiktok':
            # Специальные настройки для TikTok
            opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'cookiefile': 'cookies.txt',
                'user_agent': 'Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
                'extractor_args': {
                    'tiktok': {
                        'prefer_quality': 'high',
                        'extract_watermark': False,
                    }
                }
            }
        else:
            # Настройки для YouTube и других
            opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'cookiefile': 'cookies.txt',
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'skip': ['dash', 'hls'],
                        'player_skip': ['configs', 'webpage'],
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
        logger.error(f"Ошибка получения информации: {e}")
    
    return None

async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора качества"""
    query = update.callback_query
    await query.answer()
    
    quality = query.data.replace('quality_', '')
    url = context.user_data.get('url')
    platform = context.user_data.get('platform', 'youtube')
    
    if not url:
        await query.edit_message_text("❌ Ссылка не найдена. Отправьте заново.")
        return
    
    await query.edit_message_text(f"⏳ Скачиваю *{quality.upper()}* с {platform.upper()}...\nЭто может занять время.", parse_mode='Markdown')
    
    try:
        ydl_opts = get_ydl_opts(quality, platform)
        
        # Очищаем старые файлы
        for old_file in DOWNLOAD_DIR.glob('*.*'):
            if time.time() - old_file.stat().st_mtime > 300:  # 5 минут
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
        
        # Сортируем по времени создания
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        filename = str(files[0])
        
        # Проверяем размер файла
        file_size = os.path.getsize(filename)
        logger.info(f"Размер файла: {file_size} байт ({file_size / 1024:.2f} KB)")
        
        # Если файл слишком маленький - возможно это превью
        if file_size < 100 * 1024:  # меньше 100 KB
            os.remove(filename)
            await query.edit_message_text(
                "❌ Скачался только превью/заглушка.\n"
                "Попробуйте:\n"
                "• Обновить yt-dlp: pip install --upgrade yt-dlp\n"
                "• Использовать другую ссылку\n"
                "• Попробовать позже"
            )
            return
        
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
                        caption=f"📹 {title}\nИсточник: {platform.upper()}",
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
