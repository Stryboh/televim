import asyncio
import os
from telethon import events

class TelegramViewModel:
    def __init__(self, model, view):
        self.model = model
        self.view = view
        
        # Состояние приложения
        self.chat_list = []
        self.focus = "chat"  # chat или msg
        self.selected_chat = 0
        self.chat_offset = 0
        
        self.messages = []
        self.message_blocks = []
        self.flat_lines = []
        self.line_offset = 0
        
        # Добавляем поддержку псевдокурсора
        self.selected_msg_idx = -1  # Индекс выбранного сообщения в списке
        self.selected_msg_id = None  # ID выбранного сообщения
        self.downloaded_msg_id = None  # ID сообщения с загруженным файлом
        self.message_line_map = {}  # Карта соответствия строк ID сообщений
        
    async def initialize(self):
        """Инициализация: подключаемся и получаем список диалогов"""
        await self.model.connect()
        self.chat_list = await self.model.get_dialogs()
        self.model.add_event_handler(self.new_message_handler, events.NewMessage)
        
    async def run(self, check_exit=None):
        """Главный цикл приложения"""
        # Обновляем список чатов в правильной позиции прокрутки
        if self.selected_chat < self.chat_offset:
            self.chat_offset = self.selected_chat
        elif self.selected_chat >= self.chat_offset + self.view.chat_win_height:
            self.chat_offset = self.selected_chat - self.view.chat_win_height + 1
            
        # Отрисовываем чаты
        self.view.draw_chat_window(self.chat_list, self.selected_chat, self.chat_offset)
        
        # Отрисовываем сообщения или пустой экран
        if self.focus == "msg" and self.flat_lines:
            # Проверяем, находится ли курсор на экране, и если нет - корректируем смещение
            self.ensure_cursor_visible()
            
            sender_name = self.chat_list[self.selected_chat].title if self.chat_list[self.selected_chat].title else "No Name"
            self.view.set_dialog_title(sender_name)
            self.view.draw_message_lines(self.flat_lines, self.line_offset, self.message_line_map)
            self.view.draw_msg_border()
        else:
            self.view.msg_win.erase()
            self.view.msg_win.noutrefresh()
            self.view.draw_msg_border()
            self.view.set_dialog_title("No messages")
            
        # Обновляем экран
        self.view.refresh()
        
        # Проверяем запрос на выход
        if check_exit and check_exit():
            return True  # Сигнал для выхода
        
        # Обрабатываем нажатия клавиш
        key = self.view.get_key()
        if key == -1:
            await asyncio.sleep(0.05)
            return False
            
        # Обработка ввода в зависимости от текущего фокуса
        if self.focus == "chat":
            return await self.handle_chat_focus_keys(key)
        elif self.focus == "msg":
            return await self.handle_message_focus_keys(key)
            
        return False
            
    async def handle_chat_focus_keys(self, key):
        """Обработка клавиш в режиме списка чатов"""
        import curses
        
        if key in (ord('j'), curses.KEY_DOWN):
            if self.selected_chat < len(self.chat_list) - 1:
                self.selected_chat += 1
            return False
        elif key in (ord('k'), curses.KEY_UP):
            if self.selected_chat > 0:
                self.selected_chat -= 1
            return False
        elif key in (ord('l'), 10, 13):  # Enter или 'l'
            await self.open_chat()
            return False
        elif key == ord('/'):  # Поиск по чатам
            return await self.search_chats()
        elif key in (ord('q'), 27):  # ESC или 'q'
            await self.cleanup()
            return True  # Сигнал для выхода
        return False
            
    async def handle_message_focus_keys(self, key):
        """Обработка клавиш в режиме просмотра сообщений"""
        import curses
        
        if key == ord('i'):  # Режим ввода
            # Проверяем, можно ли отправлять сообщения в текущем чате
            if self.can_send_messages():
                input_text = self.view.message_input_window()
                if input_text is not None and input_text.strip() != "":
                    await self.send_message(input_text)
            return False
        elif key == ord('y'):  # Копирование сообщения
            await self.copy_message_to_clipboard()
            return False
        elif key in (ord('j'), curses.KEY_DOWN):  # Вниз
            await self.move_cursor_down()
            return False
        elif key in (ord('k'), curses.KEY_UP):  # Вверх
            await self.move_cursor_up()
            return False
        elif key == ord('G'):  # Переход к последнему сообщению
            await self.jump_to_latest_messages()
            return False
        elif key == ord('g'):  # Переход к первому сообщению
            await self.jump_to_oldest_messages()
            return False
        elif key == ord('/'):  # Поиск по сообщениям
            await self.search_messages()
            return False
        elif key == 10 or key == curses.KEY_ENTER:  # Enter для загрузки файла
            await self.handle_enter_on_message()
            return False
        elif key in (ord('h'), 27):  # 'h' или ESC - возврат к списку чатов
            self.focus = "chat"
            self.reset_cursor()
            return False
        elif key == ord('q'):  # 'q' - выход
            self.focus = "chat"  # Сначала возвращаемся к списку чатов
            self.reset_cursor()
            return False
        return False
            
    async def open_chat(self):
        """Открывает выбранный чат и загружает сообщения"""
        await self.model.send_read_acknowledge(self.chat_list[self.selected_chat].entity)
        self.chat_list = await self.model.get_dialogs()
        
        # Загружаем сообщения
        latest_messages = await self.model.get_messages(self.chat_list[self.selected_chat], limit=20)
        if latest_messages:
            self.messages = latest_messages.copy()  # Создаем копию списка сообщений
        else:
            self.messages = []
        
        # Сбрасываем позицию курсора
        self.reset_cursor()
        self.downloaded_msg_id = None
        
        # Получаем название чата для именования файлов
        chat_title = self.chat_list[self.selected_chat].title if self.chat_list[self.selected_chat].title else "No_Title"
        
        self.message_blocks = await self.view.prepare_message_blocks(
            self.messages, 
            self.view.msg_win_width, 
            self.model, 
            chat_title
        )
        self.flat_lines = self.view.flatten_blocks(self.message_blocks)
        self.message_line_map = self.flat_lines[1]  # Получаем карту сообщений
        
        # Устанавливаем курсор на последнее сообщение
        if self.messages:
            last_msg = self.messages[-1]
            for i, msg_id in self.message_line_map.items():
                if msg_id == last_msg.id:
                    self.selected_msg_idx = i
                    self.selected_msg_id = last_msg.id
                    break
        
        # Показываем последние сообщения внизу окна
        self.line_offset = max(0, len(self.flat_lines[0]) - self.view.msg_win_height) if len(self.flat_lines[0]) > self.view.msg_win_height else 0
        
        # Обеспечиваем видимость курсора
        self.ensure_cursor_visible()
        
        self.focus = "msg"
        await self.refresh_message_blocks()
        
    async def send_message(self, text):
        """Отправляет сообщение в текущий чат"""
        sent_msg = await self.model.send_message(self.chat_list[self.selected_chat].entity, text)
        
        # Получаем название чата для именования файлов
        chat_title = self.chat_list[self.selected_chat].title if self.chat_list[self.selected_chat].title else "No_Title"
        
        new_block = await self.view.prepare_message_blocks(
            [sent_msg], 
            self.view.msg_win_width, 
            self.model,
            chat_title,
            self.selected_msg_id,
            self.downloaded_msg_id
        )
        new_flat_lines, new_message_map = self.view.flatten_blocks(new_block)
        
        # Объединяем новые сообщения и карту сообщений
        old_lines, old_map = self.flat_lines
        
        # Обновляем карту сообщений с учетом смещения индексов
        offset = len(old_lines)
        updated_map = old_map.copy()
        for idx, msg_id in new_message_map.items():
            updated_map[idx + offset] = msg_id
            
        old_lines.extend(new_flat_lines)
        self.flat_lines = (old_lines, updated_map)
        self.message_line_map = updated_map
        
        self.messages.append(sent_msg)
        self.line_offset = max(0, len(old_lines) - self.view.msg_win_height)
        
    async def scroll_messages_up(self):
        """Прокрутка сообщений вверх, подгрузка старых сообщений при необходимости"""
        if self.line_offset > 0:
            self.line_offset -= 1
            # После прокрутки проверяем, не нужно ли скорректировать положение курсора
            self.ensure_cursor_visible()
        else:
            if self.messages:
                oldest_message_id = self.messages[0].id
                older_messages = await self.model.get_messages(
                    self.chat_list[self.selected_chat], 
                    limit=20, 
                    offset_id=oldest_message_id
                )
                if older_messages:
                    # Получаем название чата для именования файлов
                    chat_title = self.chat_list[self.selected_chat].title if self.chat_list[self.selected_chat].title else "No_Title"
                    
                    # Создаем копию текущих сообщений перед добавлением новых
                    new_messages = older_messages.copy() + self.messages.copy()
                    self.messages = new_messages
                    
                    # Обновляем блоки сообщений
                    self.message_blocks = await self.view.prepare_message_blocks(
                        self.messages, 
                        self.view.msg_win_width, 
                        self.model,
                        chat_title,
                        self.selected_msg_id,
                        self.downloaded_msg_id
                    )
                    self.flat_lines = self.view.flatten_blocks(self.message_blocks)
                    self.message_line_map = self.flat_lines[1]
                    
                    # Пересчитываем индекс выбранного сообщения
                    if self.selected_msg_id:
                        for i, msg_id in self.message_line_map.items():
                            if msg_id == self.selected_msg_id:
                                self.selected_msg_idx = i
                                break
                                
                    # Проверяем видимость курсора после загрузки новых сообщений
                    self.ensure_cursor_visible()
        
    async def new_message_handler(self, event):
        """Обработчик новых сообщений"""
        # Сохраняем текущий ID диалога перед обновлением
        current_dialog = self.chat_list[self.selected_chat] if self.selected_chat < len(self.chat_list) else None
        current_dialog_id = self.model.get_dialog_id(current_dialog) if current_dialog else None

        new_dialogs = await self.model.get_dialogs()
        
        # Восстанавливаем позицию выбранного чата
        new_selected = None
        if current_dialog_id is not None:
            for idx, dialog in enumerate(new_dialogs):
                if self.model.get_dialog_id(dialog) == current_dialog_id:
                    new_selected = idx
                    break
        
        # Обновляем список и позицию только если чат существует
        if new_selected is not None:
            self.chat_list = new_dialogs
            self.selected_chat = new_selected
        else:
            self.chat_list = new_dialogs

        msg_peer_id = self.model.get_message_peer_id(event.message)
        current_open_dialog_id = self.model.get_dialog_id(self.chat_list[self.selected_chat]) if self.selected_chat < len(self.chat_list) else None
        
        # Если открыт чат, в который пришло сообщение - показываем его
        if self.focus == "msg" and msg_peer_id == current_open_dialog_id:
            # Получаем название чата для именования файлов
            chat_title = self.chat_list[self.selected_chat].title if self.chat_list[self.selected_chat].title else "No_Title"
            
            new_block = await self.view.prepare_message_blocks(
                [event.message], 
                self.view.msg_win_width, 
                self.model,
                chat_title,
                self.selected_msg_id,
                self.downloaded_msg_id
            )
            new_flat_lines, new_map = self.view.flatten_blocks(new_block)
            
            # Объединяем новые сообщения и карту сообщений
            old_lines, old_map = self.flat_lines
            
            # Обновляем карту сообщений с учетом смещения индексов
            offset = len(old_lines)
            updated_map = old_map.copy()
            for idx, msg_id in new_map.items():
                updated_map[idx + offset] = msg_id
                
            old_lines.extend(new_flat_lines)
            self.flat_lines = (old_lines, updated_map)
            self.message_line_map = updated_map
            
            self.messages.append(event.message)
            if self.line_offset >= len(old_lines) - self.view.msg_win_height - 1:
                self.line_offset = max(0, len(old_lines) - self.view.msg_win_height)
                await self.model.send_read_acknowledge(self.chat_list[self.selected_chat].entity)
                self.chat_list = await self.model.get_dialogs()
        
    async def cleanup(self):
        """Закрытие приложения и очистка ресурсов"""
        try:
            await self.model.disconnect()
        except Exception:
            pass
        
        # Удаляем временные файлы
        self.model.cleanup_downloads()
        os.system("clear")
        
    def reset_cursor(self):
        """Сбрасывает позицию курсора"""
        self.selected_msg_idx = -1
        self.selected_msg_id = None
    
    async def move_cursor_down(self):
        """Перемещает курсор вниз"""
        lines, message_map = self.flat_lines
        
        # Если это первое перемещение, выбираем первое сообщение
        if self.selected_msg_idx == -1:
            for i in range(self.line_offset, min(len(lines), self.line_offset + self.view.msg_win_height)):
                if i in message_map:
                    self.selected_msg_idx = i
                    self.selected_msg_id = message_map[i]
                    break
            await self.refresh_message_blocks()
            return
        
        # Ищем следующее сообщение после текущего выбранного
        current_msg_id = self.selected_msg_id
        next_msg_id = None
        found_current = False
        
        for msg in self.messages:
            if found_current:
                next_msg_id = msg.id
                break
            if msg.id == current_msg_id:
                found_current = True
                
        if next_msg_id:
            # Ищем строку с этим сообщением
            for i, msg_id in message_map.items():
                if msg_id == next_msg_id:
                    self.selected_msg_idx = i
                    self.selected_msg_id = next_msg_id
                    
                    # Обеспечиваем видимость курсора на экране
                    self.ensure_cursor_visible()
                    
                    await self.refresh_message_blocks()
                    break
    
    async def move_cursor_up(self):
        """Перемещает курсор вверх"""
        lines, message_map = self.flat_lines
        
        # Если это первое перемещение, выбираем последнее видимое сообщение
        if self.selected_msg_idx == -1:
            for i in range(min(len(lines) - 1, self.line_offset + self.view.msg_win_height - 1), self.line_offset - 1, -1):
                if i in message_map:
                    self.selected_msg_idx = i
                    self.selected_msg_id = message_map[i]
                    break
            await self.refresh_message_blocks()
            return
        
        # Ищем предыдущее сообщение перед текущим выбранным
        current_msg_id = self.selected_msg_id
        prev_msg_id = None
        
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].id == current_msg_id and i > 0:
                prev_msg_id = self.messages[i-1].id
                break
                
        if prev_msg_id:
            # Ищем строку с этим сообщением
            for i, msg_id in message_map.items():
                if msg_id == prev_msg_id:
                    self.selected_msg_idx = i
                    self.selected_msg_id = prev_msg_id
                    
                    # Обеспечиваем видимость курсора на экране
                    self.ensure_cursor_visible()
                    
                    await self.refresh_message_blocks()
                    break
        else:
            # Если мы в начале списка, пробуем загрузить более старые сообщения
            await self.scroll_messages_up()
    
    async def handle_enter_on_message(self):
        """Обрабатывает нажатие Enter на выбранном сообщении"""
        if not self.selected_msg_id:
            return
            
        # Ищем выбранное сообщение
        selected_message = None
        for msg in self.messages:
            if msg.id == self.selected_msg_id:
                selected_message = msg
                break
                
        if selected_message and selected_message.file:
            # Получаем информацию о файле
            chat_title = self.chat_list[self.selected_chat].title
            
            # Проверяем, уже скачан ли файл
            path = await self.model.download_media(
                selected_message.media, 
                chat_title, 
                selected_message.id, 
                force_download=False
            )
            
            # Проверяем, действительно ли файл был загружен (больше 1KB)
            file_fully_downloaded = os.path.exists(path) and os.path.getsize(path) > 1000
            
            if not file_fully_downloaded:
                # Файл не скачан или слишком маленький, загружаем его
                real_path = await self.model.download_media(
                    selected_message.media, 
                    chat_title, 
                    selected_message.id, 
                    force_download=True,
                    progress_callback=self.view.show_download_progress
                )
                
                # Отмечаем сообщение как загруженное
                self.downloaded_msg_id = selected_message.id
                
                # Скрываем прогресс-бар
                self.view.hide_progress_bar()
                
                # Обновляем отображение
                await self.refresh_message_blocks()
            else:
                # Файл уже скачан, открываем его
                os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')
            
    async def refresh_message_blocks(self):
        """Обновляет блоки сообщений с учетом выделения"""
        # Получаем название чата для именования файлов
        chat_title = self.chat_list[self.selected_chat].title if self.chat_list[self.selected_chat].title else "No_Title"
        
        # Пересоздаем блоки сообщений с новыми параметрами выделения
        self.message_blocks = await self.view.prepare_message_blocks(
            self.messages, 
            self.view.msg_win_width, 
            self.model, 
            chat_title, 
            self.selected_msg_id,
            self.downloaded_msg_id
        )
        self.flat_lines = self.view.flatten_blocks(self.message_blocks)
        self.message_line_map = self.flat_lines[1]  # Получаем карту сообщений 

    def can_send_messages(self):
        """Проверяет, можно ли отправлять сообщения в текущем чате"""
        if self.selected_chat < len(self.chat_list):
            chat = self.chat_list[self.selected_chat]
            # Проверяем права для отправки сообщений
            if hasattr(chat, 'entity') and hasattr(chat.entity, 'admin_rights'):
                # Для каналов и групп, где мы админы
                return True
            # Проверяем тип чата
            if hasattr(chat, 'entity'):
                # Для личных чатов всегда разрешено
                if hasattr(chat.entity, 'user_id'):
                    return True
                # Для других типов проверяем права
                if not hasattr(chat.entity, 'right'):
                    return True
        return True  # По умолчанию разрешаем отправку
        
    async def copy_message_to_clipboard(self):
        """Копирует выделенное сообщение в буфер обмена"""
        if not self.selected_msg_id:
            return
            
        # Ищем выбранное сообщение
        selected_message = None
        for msg in self.messages:
            if msg.id == self.selected_msg_id:
                selected_message = msg
                break
                
        if selected_message:
            # Если у сообщения есть файл, копируем путь к файлу
            if selected_message.file:
                chat_title = self.chat_list[self.selected_chat].title
                path = await self.model.download_media(
                    selected_message.media, 
                    chat_title, 
                    selected_message.id, 
                    force_download=False
                )
                
                # Если файл был полностью загружен (проверяем размер файла)
                if os.path.exists(path) and os.path.getsize(path) > 1000:
                    os.system(f'echo -n "{os.path.abspath(path)}" | xclip -selection clipboard 2>/dev/null')
                else:
                    # Если файл не загружен или слишком маленький, уведомляем что нужно сначала загрузить
                    print("\a")  # Звуковой сигнал
            else:
                # Если обычное текстовое сообщение, копируем текст
                text = selected_message.text if selected_message.text else ""
                if text:
                    # Экранируем специальные символы для shell
                    text = text.replace('"', '\\"')
                    os.system(f'echo -n "{text}" | xclip -selection clipboard 2>/dev/null')

    async def jump_to_latest_messages(self):
        """Переход к последним сообщениям, как в vim с помощью G"""
        if self.messages:
            # Устанавливаем курсор на последнее сообщение в списке
            last_msg = self.messages[-1]
            for i, msg_id in self.message_line_map.items():
                if msg_id == last_msg.id:
                    self.selected_msg_idx = i
                    self.selected_msg_id = last_msg.id
                    break
            
            # Показываем последние сообщения внизу окна
            lines, _ = self.flat_lines
            self.line_offset = max(0, len(lines) - self.view.msg_win_height)
            
            # Обеспечиваем видимость курсора
            self.ensure_cursor_visible()
            
            await self.refresh_message_blocks()

    async def jump_to_oldest_messages(self):
        """Переход к первым сообщениям, как в vim с помощью gg"""
        # Если есть сообщения, выбираем первое
        if self.messages:
            first_msg = self.messages[0]
            for i, msg_id in self.message_line_map.items():
                if msg_id == first_msg.id:
                    self.selected_msg_idx = i
                    self.selected_msg_id = first_msg.id
                    break
            
            # Устанавливаем смещение в начало
            self.line_offset = 0
            
            # Обеспечиваем видимость курсора
            self.ensure_cursor_visible()
            
            await self.refresh_message_blocks()

    async def search_chats(self):
        """Открывает окно поиска по чатам"""
        # Поиск только в режиме просмотра чатов
        if self.focus != "chat":
            return False
            
        search_result = await self.view.chat_search_window(self.chat_list)
        
        if search_result is not None:
            # Пользователь выбрал чат
            self.selected_chat = search_result
            await self.open_chat()
            
        return False
        
    async def search_messages(self):
        """Открывает окно поиска по сообщениям в активном чате"""
        # Поиск только в режиме просмотра сообщений
        if self.focus != "msg" or not self.messages:
            return False
        
        # Создаем функцию для загрузки дополнительных сообщений
        async def load_more_messages(offset_id):
            older_messages = await self.model.get_messages(
                self.chat_list[self.selected_chat], 
                limit=20, 
                offset_id=offset_id
            )
            return older_messages
            
        message_idx = await self.view.message_search_window(
            self.messages,
            load_more_callback=load_more_messages
        )
        
        if message_idx is not None:
            # Пользователь выбрал сообщение
            selected_message = self.messages[message_idx]
            self.selected_msg_id = selected_message.id
            
            # Находим строку для этого сообщения
            for i, msg_id in self.message_line_map.items():
                if msg_id == selected_message.id:
                    self.selected_msg_idx = i
                    
                    # Обеспечиваем видимость курсора на экране
                    self.ensure_cursor_visible()
                    
                    await self.refresh_message_blocks()
                    break
            
        return False 

    def ensure_cursor_visible(self):
        """Убеждается, что курсор видим на экране и корректирует смещение при необходимости"""
        # Если курсор не установлен, нечего корректировать
        if self.selected_msg_idx == -1 or not self.message_line_map:
            return
            
        lines, _ = self.flat_lines
        
        # Проверяем, выходит ли курсор за пределы видимой области сверху
        if self.selected_msg_idx < self.line_offset:
            self.line_offset = max(0, self.selected_msg_idx)
            
        # Проверяем, выходит ли курсор за пределы видимой области снизу
        elif self.selected_msg_idx >= self.line_offset + self.view.msg_win_height:
            self.line_offset = max(0, self.selected_msg_idx - self.view.msg_win_height + 1)
            
        # Проверяем, не слишком ли низко смещение для количества строк
        max_offset = max(0, len(lines) - self.view.msg_win_height)
        if self.line_offset > max_offset:
            self.line_offset = max_offset 