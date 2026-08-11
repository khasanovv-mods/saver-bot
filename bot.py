import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime

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
TOKEN = "8723588644:AAHKrHAqxmR5_C-K6gWGauS86fDpL3TLS7g"  # Замените на реальный токен
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ

# Создаем директорию
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Базовые настройки yt-dlp с заголовками браузера
YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'ignoreerrors': True,
    'no_check_certificate': True,
    'prefer_insecure': True,
    'cookiefile': 'cookies.txt',  # Опционально
    # Имитация браузера - ЭТО ВАЖНО ДЛЯ YouTube!
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'headers': {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    },
    # Дополнительные настройки для обхода блокировок
    'extractor_args': {
        'youtube': {
            'player_client': 'android',  # Имитация Android-клиента
            'skip': ['hls', 'dash'],  # Пропускаем некоторые форматы
        }
    }
}

def get_ydl_opts(quality='best'):
    """Получение настроек yt-dlp в зависимости от качества"""
    base_opts = YDL_OPTS_BASE.copy()
    
    # Имя файла с временной меткой
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if quality == 'best':
        base_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        base_opts['merge_output_format'] = 'mp4'
    elif quality == 'high':
        base_opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
        base_opts['merge_output_format'] = 'mp4'
    elif quality == 'medium':
        base_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
        base_opts['merge_output_format'] = 'mp4'
    elif quality == 'low':
        base_opts['format'] = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best'
        base_opts['merge_output_format'] = 'mp4'
    elif quality == 'audio':
        base_opts['format'] = 'bestaudio/best'
        base_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        base_opts['outtmpl'] = str(DOWNLOAD_DIR / f'audio_{timestamp}.%(ext)s')
        return base_opts
    
    base_opts['outtmpl'] = str(DOWNLOAD_DIR / f'video_{timestamp}.%(ext)s')
    return base_opts

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    user = update.effective_user
    welcome_text = (
        f"🎬 Привет, {user.first_name}!\n\n"
        "Я умею скачивать видео без водяных знаков:\n"
        "• YouTube (включая Shorts)\n"
        "• TikTok (без водяного знака)\n"
        "• Instagram (Reels, посты, IGTV)\n"
        "• Pinterest, Twitter/X, Reddit\n"
        "• И многие другие...\n\n"
        "📌 Просто отправь мне ссылку на видео!\n\n"
        "⚠️ Лимит Telegram: файлы до 50 МБ"
    )
    await update.message.reply_text(welcome_text)

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ссылок"""
    url = update.message.text.strip()
    
    # Проверка на ссылку
    if not re.match(r'^https?://', url):
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку.")
        return
    
    context.user_data['url'] = url
    status_msg = await update.message.reply_text("🔄 Получаю информацию о видео...")
    
    try:
        # Пробуем разные методы получения информации
        info = await get_video_info(url)
        
        if info is None:
            # Пробуем альтернативный метод
            info = await get_video_info_alt(url)
            
        if info is None:
            await status_msg.edit_text(
                "❌ Не удалось получить информацию.\n\n"
                "Возможные причины:\n"
                "• Видео приватное или удалено\n"
                "• Требуется авторизация\n"
                "• YouTube временно блокирует запросы\n\n"
                "🔄 Попробуйте отправить ссылку еще раз через минуту."
            )
            return
        
        # Получаем название
        title = info.get('title', 'video')
        if len(title) > 60:
            title = title[:57] + "..."
        
        # Длительность
        duration = info.get('duration', 0)
        duration_str = f"⏱️ {duration // 60}:{duration % 60:02d}" if duration else ""
        
        context.user_data['title'] = title
        
        # Клавиатура с качеством
        keyboard = [
            [InlineKeyboardButton("🎥 Лучшее качество", callback_data="quality_best")],
            [InlineKeyboardButton("📱 1080p", callback_data="quality_high"),
             InlineKeyboardButton("📱 720p", callback_data="quality_medium")],
            [InlineKeyboardButton("📱 480p", callback_data="quality_low")],
            [InlineKeyboardButton("🎵 Аудио MP3", callback_data="quality_audio")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        info_text = (
            f"📹 *{title}*\n"
            f"{duration_str}\n\n"
            "Выберите качество:"
        )
        
        await status_msg.edit_text(
            info_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await status_msg.edit_text(
            f"❌ Ошибка: {str(e)[:150]}\n\n"
            "Попробуйте другую ссылку или повторите позже."
        )

async def get_video_info(url):
    """Получение информации о видео с правильными заголовками"""
    try:
        opts = YDL_OPTS_BASE.copy()
        opts['extract_flat'] = False
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Получаем информацию
            info = ydl.extract_info(url, download=False)
            
            # Проверяем, что это не плейлист
            if info and info.get('_type') == 'playlist':
                entries = info.get('entries', [])
                if entries:
                    info = entries[0]
            
            return info
    except Exception as e:
        logger.error(f"get_video_info error: {e}")
        return None

async def get_video_info_alt(url):
    """Альтернативный метод получения информации"""
    try:
        opts = YDL_OPTS_BASE.copy()
        opts['extract_flat'] = False
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['hls', 'dash'],
                'innertube_client': 'ANDROID',
            }
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and info.get('_type') == 'playlist' and info.get('entries'):
                info = info['entries'][0]
            return info
    except Exception as e:
        logger.error(f"get_video_info_alt error: {e}")
        return None

async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора качества"""
    query = update.callback_query
    await query.answer()
    
    quality = query.data.replace('quality_', '')
    url = context.user_data.get('url')
    
    if not url:
        await query.edit_message_text("❌ Ссылка не найдена. Отправьте ссылку заново.")
        return
    
    await query.edit_message_text(f"⏳ Скачиваю *{quality.upper()}*...", parse_mode='Markdown')
    
    try:
        ydl_opts = get_ydl_opts(quality)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Определяем имя файла
            filename = None
            if quality == 'audio':
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = str(DOWNLOAD_DIR / f'audio_{timestamp}.mp3')
                # Проверяем существование
                if not os.path.exists(filename):
                    # Ищем файл
                    files = list(DOWNLOAD_DIR.glob('audio_*.mp3'))
                    if files:
                        filename = str(files[-1])
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                # Ищем видео файл
                files = list(DOWNLOAD_DIR.glob('video_*.mp4'))
                if files:
                    filename = str(files[-1])
            
            if not filename or not os.path.exists(filename):
                # Пробуем найти любой недавний файл
                files = sorted(DOWNLOAD_DIR.glob('*.*'), key=os.path.getmtime, reverse=True)
                if files:
                    filename = str(files[0])
                else:
                    await query.edit_message_text("❌ Файл не найден.")
                    return
            
            # Проверяем размер
            file_size = os.path.getsize(filename)
            if file_size > MAX_FILE_SIZE:
                os.remove(filename)
                await query.edit_message_text(
                    f"❌ Файл слишком большой ({file_size / (1024*1024):.1f} МБ).\n"
                    f"Лимит Telegram: 50 МБ.\n"
                    "Попробуйте качество ниже."
                )
                return
            
            # Отправляем
            title = context.user_data.get('title', 'video')
            
            if quality == 'audio':
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
        logger.error(f"Download error: {e}")
        await query.edit_message_text(
            f"❌ Ошибка скачивания: {str(e)[:150]}\n\n"
            "Попробуйте другое качество или ссылку."
        )

async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Неизвестные сообщения"""
    await update.message.reply_text(
        "🤔 Отправьте мне ссылку на видео.\n"
        "Я поддерживаю YouTube, TikTok, Instagram, Pinterest и другие!"
    )

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(handle_quality_selection, pattern="^quality_"))
    application.add_handler(MessageHandler(filters.ALL, handle_unknown))
    
    logger.info("🚀 Бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
