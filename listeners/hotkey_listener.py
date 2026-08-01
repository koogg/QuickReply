from PyQt6.QtCore import QThread, pyqtSignal
import time

from utils import logger

try:
    import win32gui
    from pynput import keyboard as pynput_keyboard, mouse as pynput_mouse

    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    win32gui = None
    pynput_keyboard = None
    pynput_mouse = None


class HotKeyListenerThread(QThread):
    hotkey_triggered = pyqtSignal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings or {}
        self.listener = None
        self._is_running = True

    def run(self):
        if not HAS_PYNPUT or not win32gui:
            logger.error('缺少 pynput 或 pywin32 模块，热键功能无法启动。')
            return

        trigger_type = self.settings.get('trigger_type', 'mouse')

        def on_trigger():
            if self._is_running:
                self.hotkey_triggered.emit()

        try:
            if trigger_type == 'mouse' and pynput_mouse:
                def on_click(x, y, button, pressed):
                    if not self._is_running:
                        return False
                    if button == pynput_mouse.Button.middle and pressed:
                        on_trigger()

                with pynput_mouse.Listener(on_click=on_click) as listener:
                    self.listener = listener
                    listener.join()

            elif trigger_type == 'keyboard' and pynput_keyboard:
                hotkey_str = self.settings.get('trigger_key', '')
                if not hotkey_str:
                    logger.warning('键盘热键未定义。')
                    return
                with pynput_keyboard.GlobalHotKeys({hotkey_str: on_trigger}) as listener:
                    self.listener = listener
                    listener.join()

            elif trigger_type == 'double_press' and pynput_keyboard:
                double_key_str = self.settings.get('double_key', '<ctrl>')
                key_map = {
                    '<ctrl>': pynput_keyboard.Key.ctrl_l,
                    '<ctrl_r>': pynput_keyboard.Key.ctrl_r,
                    '<alt>': pynput_keyboard.Key.alt_l,
                    '<alt_r>': pynput_keyboard.Key.alt_r,
                    '<shift>': pynput_keyboard.Key.shift_l,
                    '<shift_r>': pynput_keyboard.Key.shift_r,
                }
                target_key = key_map.get(double_key_str, pynput_keyboard.Key.ctrl_l)
                last_press_time = 0
                press_count = 0
                DOUBLE_PRESS_INTERVAL = 0.4

                def on_double_press(key):
                    nonlocal last_press_time, press_count
                    if key == target_key:
                        now = time.time()
                        if now - last_press_time < DOUBLE_PRESS_INTERVAL:
                            press_count += 1
                            if press_count >= 2:
                                press_count = 0
                                on_trigger()
                        else:
                            press_count = 1
                        last_press_time = now
                    else:
                        press_count = 0

                with pynput_keyboard.Listener(on_press=on_double_press) as listener:
                    self.listener = listener
                    listener.join()

        except ImportError:
            logger.error("pynput 模块未找到，请运行 'pip install pynput' 来安装。")
        except Exception as e:
            logger.error('无法启动热键监听器: %s', e)

    def stop_listener(self):
        self._is_running = False
        if self.listener:
            try:
                self.listener.stop()
            except Exception as e:
                logger.error('停止监听器时出错: %s', e)
