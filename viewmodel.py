import asyncio
import os
from telethon import events

class TelegramViewModel:
    def __init__(self, model, view):
        self.model = model
        self.view = view
        self.chat_list = []
        self.focus = "chat"
        self.selected_chat = 0
        self.chat_offset = 0
        self.messages = []
        self.message_blocks = []
        self.flat_lines = []
        self.line_offset = 0
        self.selected_msg_idx = -1
        self.selected_msg_id = None
        self.downloaded_msg_id = None
        self.message_line_map = {}

    async def initialize(self):
        await self.model.connect()
        self.chat_list = await self.model.get_dialogs()
        self.model.add_event_handler(self.new_message_handler, events.NewMessage)

    async def run(self, check_exit=None):
        if self.selected_chat < self.chat_offset:
            self.chat_offset = self.selected_chat
        elif self.selected_chat >= self.chat_offset + self.view.chat_win_height:
            self.chat_offset = self.selected_chat - self.view.chat_win_height + 1

        self.view.draw_chat_window(self.chat_list, self.selected_chat, self.chat_offset)

        if self.focus == "msg" and self.flat_lines:
            self.ensure_cursor_visible()
            sender_name = self.chat_list[self.selected_chat].title or "No Name"
            
            # Обновляем заголовок с именем чата
            self.view.set_dialog_title(sender_name)
            self.view.draw_message_lines(self.flat_lines, self.line_offset, self.message_line_map)
            self.view.draw_msg_border()
        else:
            self.view.msg_win.erase()
            self.view.msg_win.noutrefresh()
            self.view.draw_msg_border()
            self.view.set_dialog_title("No messages")

        self.view.refresh()

        if check_exit and check_exit():
            return True

        key = self.view.get_key()
        if key == -1:
            await asyncio.sleep(0.05)
            return False

        if self.focus == "chat":
            return await self.handle_chat_focus_keys(key)
        elif self.focus == "msg":
            return await self.handle_message_focus_keys(key)

        return False

    async def handle_chat_focus_keys(self, key):
        import curses
        if key in (ord('j'), curses.KEY_DOWN):
            if self.selected_chat < len(self.chat_list) - 1:
                self.selected_chat += 1
        elif key in (ord('k'), curses.KEY_UP):
            if self.selected_chat > 0:
                self.selected_chat -= 1
        elif key in (ord('l'), 10, 13):
            await self.open_chat()
        elif key == ord('/'):
            return await self.search_chats()
        elif key in (ord('q'), 27):
            await self.cleanup()
            return True
        return False

    async def handle_message_focus_keys(self, key):
        import curses
        import inspect
        
        if key == 27:  # Escape
            self.focus = "chat"
            return False
        elif key == ord('i'):
            # Ввод сообщения
            # Двойная проверка - сначала через наш метод
            can_send = self.can_send_messages()
            
            # Прямая проверка через API, если первая проверка прошла
            if can_send and self.selected_chat < len(self.chat_list):
                chat = self.chat_list[self.selected_chat]
                if hasattr(chat, 'entity'):
                    # Используем прямую проверку через API
                    can_send = await self.model.check_can_send_messages(chat.entity)
                
            if not can_send:
                # Если писать нельзя, просто игнорируем нажатие
                return False
                
            # Только если можно писать в чат, показываем окно ввода
            text = self.view.message_input_window()
            if text:
                await self.send_message(text)
            return False
        elif key == ord('r'):
            # Ответ на сообщение
            if not self.selected_msg_id:
                return False
                
            # Та же двойная проверка
            can_send = self.can_send_messages()
            
            # Прямая проверка через API, если первая проверка прошла
            if can_send and self.selected_chat < len(self.chat_list):
                chat = self.chat_list[self.selected_chat]
                if hasattr(chat, 'entity'):
                    # Используем прямую проверку через API
                    can_send = await self.model.check_can_send_messages(chat.entity)
                
            if not can_send:
                # Если писать нельзя, просто игнорируем нажатие
                return False
                
            # Только если можно писать, показываем окно ввода
            text = self.view.message_input_window()
            if text:
                await self.reply_to_message(text)
            return False
        elif key == ord('j') or key == curses.KEY_DOWN:
            # Прокрутка вниз
            await self.move_cursor_down()
            return False
        elif key == ord('k') or key == curses.KEY_UP:
            await self.move_cursor_up()
        elif key == ord('G'):
            await self.jump_to_latest_messages()
        elif key == ord('g'):
            await self.jump_to_oldest_messages()
        elif key == ord('y'):
            # Копирование выделенного сообщения в буфер обмена
            await self.copy_message_to_clipboard()
        elif key == ord('/'):
            await self.search_messages()
        elif key in (10, curses.KEY_ENTER):
            await self.handle_enter_on_message()
        elif key in (ord('h'), 27):
            self.focus = "chat"
            self.reset_cursor()
        elif key == ord('q'):
            self.focus = "chat"
            self.reset_cursor()
        return False

    async def open_chat(self):
        await self.model.send_read_acknowledge(self.chat_list[self.selected_chat].entity)
        self.chat_list = await self.model.get_dialogs()
        latest_messages = await self.model.get_messages(self.chat_list[self.selected_chat], limit=20)
        self.messages = latest_messages.copy() if latest_messages else []
        self.reset_cursor()
        self.downloaded_msg_id = None

        chat_title = self.chat_list[self.selected_chat].title or "No_Title"
        self.message_blocks = await self.view.prepare_message_blocks(
            self.messages,
            self.view.msg_win_width,
            self.model,
            chat_title
        )
        self.flat_lines = self.view.flatten_blocks(self.message_blocks)
        self.message_line_map = self.flat_lines[1]

        if self.messages:
            last_msg = self.messages[-1]
            for i, msg_id in self.message_line_map.items():
                if msg_id == last_msg.id:
                    self.selected_msg_idx = i
                    self.selected_msg_id = last_msg.id
                    break

        self.line_offset = max(0, len(self.flat_lines[0]) - self.view.msg_win_height) if self.flat_lines[0] else 0
        self.ensure_cursor_visible()
        self.focus = "msg"
        await self.refresh_message_blocks()

    async def send_message(self, text, reply_to=None):
        """Отправляет сообщение в текущий чат"""
        try:
            sent_msg = await self.model.send_message(
                self.chat_list[self.selected_chat].entity, 
                text,
                reply_to=reply_to
            )
            
            # Если сообщение не удалось отправить, выходим
            if not sent_msg or not hasattr(sent_msg, 'id'):
                self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (не удалось отправить)")
                return
                
            chat_title = self.chat_list[self.selected_chat].title or "No_Title"
            new_block = await self.view.prepare_message_blocks(
                [sent_msg],
                self.view.msg_win_width,
                self.model,
                chat_title,
                self.selected_msg_id,
                self.downloaded_msg_id
            )
            new_flat_lines, new_map = self.view.flatten_blocks(new_block)
            old_lines, old_map = self.flat_lines
            offset = len(old_lines)
            updated_map = old_map.copy()
            for idx, msg_id in new_map.items():
                updated_map[idx + offset] = msg_id
            old_lines.extend(new_flat_lines)
            self.flat_lines = (old_lines, updated_map)
            self.message_line_map = updated_map
            self.messages.append(sent_msg)
            self.line_offset = max(0, len(old_lines) - self.view.msg_win_height + 1)  # +1 для предпоследнего сообщения
            await self.refresh_message_blocks()
        except Exception as e:
            # В случае ошибки уведомляем пользователя
            self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (ошибка отправки)")

    async def reply_to_message(self, text):
        """Отправляет сообщение как ответ на выбранное сообщение"""
        # Повторная проверка возможности отправки
        if not self.can_send_messages():
            return
            
        if not self.selected_msg_id:
            # Если нет выбранного сообщения, отправляем как обычное сообщение
            await self.send_message(text)
            return
            
        # Отправляем сообщение с указанием reply_to
        await self.send_message(text, reply_to=self.selected_msg_id)

    async def new_message_handler(self, event):
        """Обработчик новых сообщений"""
        current_dialog = self.chat_list[self.selected_chat] if self.selected_chat < len(self.chat_list) else None
        current_dialog_id = self.model.get_dialog_id(current_dialog) if current_dialog else None
        
        # Обновляем список диалогов
        new_dialogs = await self.model.get_dialogs()
        new_selected = None

        if current_dialog_id:
            for idx, dialog in enumerate(new_dialogs):
                if self.model.get_dialog_id(dialog) == current_dialog_id:
                    new_selected = idx
                    break

        if new_selected is not None:
            self.chat_list = new_dialogs
            self.selected_chat = new_selected
        else:
            self.chat_list = new_dialogs

        # Проверяем, соответствует ли сообщение текущему открытому диалогу
        msg_peer_id = self.model.get_message_peer_id(event.message)
        current_open_dialog_id = self.model.get_dialog_id(self.chat_list[self.selected_chat]) if self.selected_chat < len(self.chat_list) else None

        # Если сообщение относится к текущему открытому диалогу, добавляем его
        if self.focus == "msg" and msg_peer_id == current_open_dialog_id:
            chat_title = self.chat_list[self.selected_chat].title or "No_Title"
            
            # Создаем блок для нового сообщения
            new_block = await self.view.prepare_message_blocks(
                [event.message],
                self.view.msg_win_width,
                self.model,
                chat_title,
                self.selected_msg_id,
                self.downloaded_msg_id
            )
            
            # Добавляем новое сообщение к существующим
            new_flat_lines, new_map = self.view.flatten_blocks(new_block)
            old_lines, old_map = self.flat_lines
            offset = len(old_lines)
            updated_map = old_map.copy()
            for idx, msg_id in new_map.items():
                updated_map[idx + offset] = msg_id
            old_lines.extend(new_flat_lines)
            self.flat_lines = (old_lines, updated_map)
            self.message_line_map = updated_map
            self.messages.append(event.message)

            # Прокручиваем к новому сообщению
            total_lines = len(self.flat_lines[0])
            visible_height = self.view.msg_win_height
            self.line_offset = max(0, total_lines - visible_height + 1)  # +1 для предпоследнего сообщения

            # Если это исходящее сообщение, убеждаемся, что оно видно
            if event.message.out:
                self.line_offset = max(0, total_lines - visible_height + 1)
                # Выбираем новое сообщение
                self.selected_msg_id = event.message.id
                self.selected_msg_idx = offset  # Начальная позиция нового сообщения

            # Обновляем курсор и помечаем сообщения как прочитанные
            self.ensure_cursor_visible()
            await self.model.send_read_acknowledge(self.chat_list[self.selected_chat].entity)
            
            # Обновляем списки диалогов
            self.chat_list = await self.model.get_dialogs()
            await self.refresh_message_blocks()

    def ensure_cursor_visible(self):
        """Убеждается, что курсор видим на экране и корректирует смещение при необходимости"""
        if not self.message_line_map or self.selected_msg_idx == -1:
            return

        lines, _ = self.flat_lines
        visible_height = self.view.msg_win_height

        current_msg_id = self.message_line_map[self.selected_msg_idx]
        msg_start = self.selected_msg_idx
        msg_end = self.selected_msg_idx

        # Находим начало и конец текущего сообщения
        for i in range(self.selected_msg_idx, -1, -1):
            if self.message_line_map.get(i) == current_msg_id:
                msg_start = i
            else:
                break

        for i in range(self.selected_msg_idx, len(lines)):
            if self.message_line_map.get(i) == current_msg_id:
                msg_end = i
            else:
                break

        # Вычисляем размер сообщения
        msg_size = msg_end - msg_start + 1
        
        # Если сообщение полностью помещается в окно, центрируем его
        if msg_size <= visible_height:
            # Только если сообщение выходит за пределы видимой области, корректируем смещение
            if msg_end >= self.line_offset + visible_height or msg_start < self.line_offset:
                # Центрируем сообщение в окне
                new_offset = max(0, msg_start - (visible_height - msg_size) // 2)
                self.line_offset = new_offset
        else:
            # Если сообщение больше видимой области
            # Если курсор ближе к верхней части сообщения
            if self.selected_msg_idx - msg_start < msg_end - self.selected_msg_idx:
                # Показываем верхнюю часть сообщения
                if msg_start < self.line_offset:
                    self.line_offset = max(0, msg_start)
            else:
                # Показываем нижнюю часть сообщения
                if msg_end >= self.line_offset + visible_height:
                    self.line_offset = max(0, msg_end - visible_height + 1)
                    
        # Проверяем, не слишком ли низко смещение для количества строк
        max_offset = max(0, len(lines) - visible_height)
        if self.line_offset > max_offset:
            self.line_offset = max_offset

        # Специальная обработка для последнего сообщения
        if current_msg_id == self.messages[-1].id:
            self.line_offset = max(0, len(lines) - visible_height + 1)

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
            self.line_offset = max(0, len(lines) - self.view.msg_win_height + 1)  # +1 для видимости последнего сообщения

            # Обеспечиваем видимость курсора
            self.ensure_cursor_visible()

            await self.refresh_message_blocks()

    async def cleanup(self):
        """Закрытие приложения и очистка ресурсов"""
        # Отменяем все запущенные задачи
        for task in asyncio.all_tasks():
            if task != asyncio.current_task():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
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
        """Проверяет, можно ли отправлять сообщения в текущий чат"""
        try:
            if not self.chat_list or self.selected_chat >= len(self.chat_list):
                return False
                
            chat = self.chat_list[self.selected_chat]
            
            # Самый надежный способ проверки - прямой атрибут из Telethon
            if hasattr(chat, 'entity'):
                # Проверка на каналы
                if hasattr(chat.entity, 'broadcast') and getattr(chat.entity, 'broadcast', False):
                    # Это канал, проверяем права админа
                    if hasattr(chat.entity, 'admin_rights') and chat.entity.admin_rights:
                        # Права админа есть, проверяем право на отправку сообщений
                        if hasattr(chat.entity.admin_rights, 'post_messages') and chat.entity.admin_rights.post_messages:
                            return True
                    
                    # Для каналов по умолчанию запрещаем отправку, если не подтверждены права
                    return False
                    
                # Для обычных чатов проверяем ограничения
                if hasattr(chat.entity, 'default_banned_rights') and chat.entity.default_banned_rights:
                    # Проверяем право на отправку сообщений
                    if hasattr(chat.entity.default_banned_rights, 'send_messages') and chat.entity.default_banned_rights.send_messages:
                        return False
                
                # Для личных чатов всегда разрешаем
                if hasattr(chat.entity, 'user_id'):
                    return True
                    
            # Явная проверка флага can_send_messages из диалога
            if hasattr(chat, 'can_send_messages'):
                return chat.can_send_messages
                
            # По умолчанию разрешаем, если не удалось определить
            return True
        except Exception:
            # При любой ошибке безопаснее вернуть False
            return False

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
            try:
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
                        result = os.system(f'echo -n "{os.path.abspath(path)}" | xclip -selection clipboard 2>/dev/null')
                        if result == 0:
                            # Отображаем статус копирования
                            self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (путь к файлу скопирован)")
                        else:
                            self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (ошибка копирования)")
                    else:
                        # Если файл не загружен или слишком маленький, уведомляем что нужно сначала загрузить
                        self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (файл не загружен)")
                else:
                    # Если обычное текстовое сообщение, копируем текст
                    text = selected_message.text if selected_message.text else ""
                    if text:
                        # Экранируем специальные символы для shell
                        text = text.replace('"', '\\"')
                        result = os.system(f'echo -n "{text}" | xclip -selection clipboard 2>/dev/null')
                        if result == 0:
                            # Отображаем статус копирования
                            self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (текст скопирован)")
                        else:
                            self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (ошибка копирования)")
            except Exception as e:
                # В случае ошибки выводим сообщение
                self.view.set_dialog_title(f"{self.chat_list[self.selected_chat].title} (ошибка: {str(e)})")
                return

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
            load_more_callback=load_more_messages,
            model=self.model,
            chat_title=self.chat_list[self.selected_chat].title or "No_Title"
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

    async def scroll_messages_up(self):
        """Загружает более старые сообщения при прокрутке вверх"""
        if not self.messages:
            return

        # Получаем ID первого сообщения в текущем списке
        first_msg_id = self.messages[0].id

        # Загружаем более старые сообщения
        older_messages = await self.model.get_messages(
            self.chat_list[self.selected_chat],
            limit=20,
            offset_id=first_msg_id
        )

        if older_messages:
            # Добавляем старые сообщения в начало списка
            self.messages = older_messages + self.messages

            # Обновляем блоки сообщений
            chat_title = self.chat_list[self.selected_chat].title or "No_Title"
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

            # Обновляем отображение
            await self.refresh_message_blocks()
