import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp

# Настройка логирования для BotHost
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "8723588644:AAHKrHAqxmR5_C-K6gWGauS86fDpL3TLS7g"  # Замените на реальный токен от @BotFather
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ (лимит Telegram Bot API)

# Создаем директорию для скачанных файлов
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Настройки yt-dlp для разных платформ
YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'ignoreerrors': True,
    'no_check_certificate': True,
    'prefer_insecure': True,
    'cookiefile': 'cookies.txt',  # Опционально для Instagram/YouTube 18+
}

def get_ydl_opts(quality='best'):
    """Получение настроек yt-dlp в зависимости от выбранного качества"""
    if quality == 'best':
        return {
            **YDL_OPTS_BASE,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
        }
    elif quality == 'high':
        return {
            **YDL_OPTS_BASE,
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best',
            'merge_output_format': 'mp4',
        }
    elif quality == 'medium':
        return {
            **YDL_OPTS_BASE,
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
            'merge_output_format': 'mp4',
        }
    elif quality == 'audio':
        return {
            **YDL_OPTS_BASE,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
        }
    else:
        return {
            **YDL_OPTS_BASE,
            'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best',
            'merge_output_format': 'mp4',
        }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    welcome_text = (
        f"🎬 Привет, {user.first_name}!\n\n"
        "Я умею скачивать видео с разных платформ без водяных знаков:\n"
        "• YouTube (включая Shorts)\n"
        "• TikTok (без водяного знака)\n"
        "• Instagram (Reels, посты, IGTV)\n"
        "• Pinterest (видео)\n"
        "• Twitter/X\n"
        "• Reddit\n"
        "• И многие другие...\n\n"
        "📌 Просто отправь мне ссылку на видео, и я предложу выбрать качество!\n"
        "🎵 Для скачивания аудио используй качество 'Аудио'\n\n"
        "⚠️ Ограничение: файлы до 50 МБ (лимит Telegram)"
    )
    await update.message.reply_text(welcome_text)

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ссылок от пользователя"""
    url = update.message.text.strip()
    
    # Базовая проверка на ссылку
    url_pattern = re.compile(
        r'^https?://'  # http:// или https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # домен
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # или IP-адрес
        r'(?::\d+)?'  # опциональный порт
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )
    
    if not url_pattern.match(url):
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на видео.")
        return
    
    # Сохраняем URL в контекст для дальнейшего использования
    context.user_data['url'] = url
    
    # Отправляем уведомление о начале обработки
    status_msg = await update.message.reply_text("🔄 Получаю информацию о видео...")
    
    try:
        # Получаем информацию о видео для определения доступных форматов
        with yt_dlp.YoutubeDL(YDL_OPTS_BASE) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    await status_msg.edit_text("❌ Не удалось получить информацию по ссылке. Проверьте, что ссылка корректна и видео доступно.")
                    return
                
                # Получаем название видео
                title = info.get('title', 'video')
                if len(title) > 60:
                    title = title[:57] + "..."
                
                # Определяем длительность
                duration = info.get('duration', 0)
                duration_str = ""
                if duration:
                    minutes = duration // 60
                    seconds = duration % 60
                    duration_str = f"⏱️ {minutes}:{seconds:02d}"
                
                # Сохраняем название для использования при отправке
                context.user_data['title'] = title
                
                # Создаем клавиатуру с вариантами качества
                keyboard = [
                    [
                        InlineKeyboardButton("🎥 Лучшее качество", callback_data="quality_best"),
                    ],
                    [
                        InlineKeyboardButton("📱 1080p (High)", callback_data="quality_high"),
                        InlineKeyboardButton("📱 720p (Medium)", callback_data="quality_medium"),
                    ],
                    [
                        InlineKeyboardButton("📱 480p (Low)", callback_data="quality_low"),
                    ],
                    [
                        InlineKeyboardButton("🎵 Аудио (MP3)", callback_data="quality_audio"),
                    ],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Обновляем сообщение с информацией
                info_text = (
                    f"📹 Найдено видео: *{title}*\n"
                    f"{duration_str}\n\n"
                    "Выберите качество для скачивания:"
                )
                
                await status_msg.edit_text(
                    info_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при получении информации: {e}")
                await status_msg.edit_text(
                    "❌ Не удалось обработать ссылку.\n"
                    "Возможные причины:\n"
                    "• Видео приватное или удалено\n"
                    "• Ссылка неподдерживаемого формата\n"
                    "• Ограничения доступа (требуется авторизация)"
                )
                
    except Exception as e:
        logger.error(f"Общая ошибка: {e}")
        await status_msg.edit_text("❌ Произошла ошибка при обработке запроса.")

async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора качества"""
    query = update.callback_query
    await query.answer()
    
    quality = query.data.replace('quality_', '')
    url = context.user_data.get('url')
    
    if not url:
        await query.edit_message_text("❌ Ссылка не найдена. Пожалуйста, отправьте ссылку заново.")
        return
    
    # Обновляем сообщение
    await query.edit_message_text(f"⏳ Скачиваю видео с качеством *{quality.upper()}*...", parse_mode='Markdown')
    
    try:
        # Получаем настройки для выбранного качества
        ydl_opts = get_ydl_opts(quality)
        
        # Добавляем уникальное имя файла для избежания конфликтов
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ydl_opts['outtmpl'] = str(DOWNLOAD_DIR / f'video_{timestamp}.%(ext)s')
        
        # Скачиваем видео
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Для аудио файл будет с расширением .mp3
            if quality == 'audio':
                base = os.path.splitext(filename)[0]
                filename = f"{base}.mp3"
            
            # Проверяем, существует ли файл
            if not os.path.exists(filename):
                # Ищем файл с другими расширениями
                possible_files = list(DOWNLOAD_DIR.glob(f'video_{timestamp}.*'))
                if possible_files:
                    filename = str(possible_files[0])
                else:
                    await query.edit_message_text("❌ Не удалось найти скачанный файл.")
                    return
            
            # Проверяем размер файла
            file_size = os.path.getsize(filename)
            if file_size > MAX_FILE_SIZE:
                os.remove(filename)
                await query.edit_message_text(
                    f"❌ Файл слишком большой для Telegram ({file_size / (1024*1024):.1f} МБ).\n"
                    f"Максимальный размер: {MAX_FILE_SIZE / (1024*1024):.0f} МБ.\n"
                    "Попробуйте выбрать качество ниже."
                )
                return
            
            # Отправляем файл пользователю
            title = context.user_data.get('title', 'video')
            
            if quality == 'audio':
                # Отправляем аудио
                with open(filename, 'rb') as audio_file:
                    await query.message.reply_audio(
                        audio_file,
                        title=f"{title}.mp3",
                        performer="Downloader Bot",
                        duration=info.get('duration', 0)
                    )
            else:
                # Отправляем видео
                with open(filename, 'rb') as video_file:
                    await query.message.reply_video(
                        video_file,
                        caption=f"📹 {title}\n\n✅ Скачано с качеством: {quality.upper()}",
                        supports_streaming=True
                    )
            
            # Удаляем файл после отправки
            os.remove(filename)
            
            # Обновляем статус
            await query.edit_message_text("✅ Видео успешно скачано и отправлено!")
            
    except Exception as e:
        logger.error(f"Ошибка при скачивании: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при скачивании: {str(e)[:200]}\n\n"
            "Попробуйте другую ссылку или качество."
        )

async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для непонятных сообщений"""
    await update.message.reply_text(
        "🤔 Я понимаю только ссылки на видео.\n"
        "Отправьте ссылку с YouTube, TikTok, Instagram, Pinterest и других платформ!"
    )

def main():
    """Главная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(handle_quality_selection, pattern="^quality_"))
    application.add_handler(MessageHandler(filters.ALL, handle_unknown))
    
    # Запускаем бота
    logger.info("Бот запущен и готов к работе!")
    application.run_polling()

if __name__ == '__main__':
    main()