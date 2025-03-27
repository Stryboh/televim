import os
import glob
from telethon import TelegramClient, events
from telethon.tl.types import PeerUser, PeerChat, PeerChannel
import mimetypes
import configparser

class TelegramModel:
    def __init__(self, session_name, api_id, api_hash):
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.client.session.save_entities = False
        self.config = self.load_config()
        
    def load_config(self):
        """Загружает настройки из конфигурационного файла"""
        config = configparser.ConfigParser()
        config_file = os.path.join(os.getcwd(), '.config')
        
        # Настройки по умолчанию
        default_config = {
            'RemoveDownloadsOnExit': '1'
        }
        
        # Проверяем существование файла конфигурации
        if os.path.exists(config_file):
            config.read(config_file)
            if 'Settings' not in config:
                config['Settings'] = default_config
        else:
            config['Settings'] = default_config
            with open(config_file, 'w') as f:
                config.write(f)
                
        return config
        
    async def connect(self):
        await self.client.connect()
        
    async def is_user_authorized(self):
        """Проверяет, авторизован ли пользователь"""
        return await self.client.is_user_authorized()
        
    async def start(self, phone=None):
        """Запускает клиент и выполняет авторизацию"""
        await self.client.start(phone=phone)
        
    async def login(self, phone=None):
        """Интерактивный вход в аккаунт"""
        return await self.client.start(phone=phone)
        
    async def disconnect(self):
        await self.client.disconnect()
        
    async def get_dialogs(self):
        return await self.client.get_dialogs()
        
    async def get_messages(self, entity, limit=20, offset_id=0):
        messages = await self.client.get_messages(entity, limit=limit, offset_id=offset_id)
        messages.reverse()
        return messages
        
    async def send_message(self, entity, message):
        return await self.client.send_message(entity, message)
        
    async def download_media(self, media, chat_title, message_id, force_download=False, progress_callback=None):
        """Загружает медиа-файл с заданным именем или создает пустой файл-заглушку
        
        Args:
            media: Медиа-объект для загрузки
            chat_title: Название чата для именования файла
            message_id: ID сообщения для именования файла
            force_download: True для принудительной загрузки, False для создания заглушки
            progress_callback: Функция обратного вызова для отображения прогресса загрузки
            
        Returns:
            Путь к файлу
        """
        # Создаем безопасное имя для папки чата
        safe_chat_title = "".join(c if c.isalnum() or c in ['-', '_'] else '_' for c in chat_title)
        
        # Создаем папку для чата, если её нет
        chat_folder = f"downloads/{safe_chat_title}"
        os.makedirs(chat_folder, exist_ok=True)
        
        # Путь для сохранения файла
        file_path = f"{chat_folder}/{message_id}"
        
        # Проверяем, существует ли уже файл
        existing_files = glob.glob(f"{file_path}*")
        if existing_files:
            if force_download:
                # Если требуется загрузка, удаляем существующие файлы
                for f in existing_files:
                    os.remove(f)
            else:
                # Возвращаем путь к существующему файлу
                return existing_files[0]
        
        if force_download:
            # Создаем функцию для отслеживания прогресса, если есть callback
            if progress_callback:
                async def progress(current, total):
                    if progress_callback:
                        progress_callback(current, total)
                callback = progress
            else:
                callback = None
                
            # Загружаем файл с отображением прогресса
            path = await self.client.download_media(media, file_path, progress_callback=callback)
            return path
        else:
            # Пытаемся определить расширение файла для создания правильной заглушки
            mime_type = getattr(media, 'mime_type', None)
            file_ext = ""
            
            if mime_type:
                ext = mimetypes.guess_extension(mime_type)
                if ext:
                    file_ext = ext
            
            # Если не удалось определить расширение, используем расширение по умолчанию
            if not file_ext:
                # Проверяем атрибуты для определения типа файла
                if getattr(media, 'photo', None):
                    file_ext = '.jpg'
                elif getattr(media, 'video', None):
                    file_ext = '.mp4'
                elif getattr(media, 'document', None):
                    # Попробуем получить имя файла
                    attributes = getattr(media.document, 'attributes', [])
                    for attr in attributes:
                        if hasattr(attr, 'file_name') and attr.file_name:
                            _, ext = os.path.splitext(attr.file_name)
                            if ext:
                                file_ext = ext
                                break
                    
                    # Если имя файла не найдено
                    if not file_ext:
                        file_ext = '.bin'
                elif getattr(media, 'voice', None):
                    file_ext = '.ogg'
                else:
                    file_ext = '.bin'
            
            # Создаем пустой файл с правильным расширением
            empty_file_path = f"{file_path}{file_ext}"
            with open(empty_file_path, 'wb') as f:
                # Создаем пустой файл минимального размера
                f.write(b'0')
            
            return empty_file_path
        
    async def send_read_acknowledge(self, entity):
        return await self.client.send_read_acknowledge(entity)
        
    def add_event_handler(self, callback, event):
        self.client.add_event_handler(callback, event)
        
    @staticmethod
    def get_dialog_id(dialog):
        if hasattr(dialog.entity, 'id'):
            return dialog.entity.id
        return None
    
    @staticmethod
    def get_message_peer_id(message):
        peer = message.to_id
        if isinstance(peer, PeerUser):
            return peer.user_id
        elif isinstance(peer, PeerChat):
            return peer.chat_id
        elif isinstance(peer, PeerChannel):
            return peer.channel_id
        return None
        
    @staticmethod
    def cleanup_downloads():
        """Очищает директорию downloads в соответствии с настройками"""
        # Загружаем конфигурацию
        config = configparser.ConfigParser()
        config_file = os.path.join(os.getcwd(), '.config')
        
        remove_downloads = True  # По умолчанию удаляем
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'Settings' in config and 'RemoveDownloadsOnExit' in config['Settings']:
                remove_downloads = config['Settings']['RemoveDownloadsOnExit'] == '1'
                
        if remove_downloads:
            downloads_path = os.path.join(os.getcwd(), "downloads")
            if os.path.exists(downloads_path):
                for root, dirs, files in os.walk(downloads_path):
                    for file in files:
                        try:
                            os.remove(os.path.join(root, file))
                        except Exception:
                            pass