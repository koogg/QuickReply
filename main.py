import os
import sys
import traceback


os.environ['QT_LOGGING_RULES'] = '*.debug=false'
os.environ['QT_IMAGEIO_MAXALLOC'] = '0'


def _setup_workdir():
    """把工作目录切到程序所在目录，保证 Date.json / media_files / backup
    等运行时数据与 exe 同级，而非跟随快捷方式的"起始位置"。"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    try:
        os.chdir(base)
    except Exception:
        pass


def show_error_and_exit(exc_type, exc_value, exc_tb):
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        from utils import logger
        logger.critical('未捕获异常:\n%s', error_msg)
    except Exception:
        print(f'致命错误:\n{error_msg}')
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(None, '程序启动错误',
                             f'程序遇到致命错误:\n\n{error_msg}')
    except Exception:
        print(f'致命错误:\n{error_msg}')
        try:
            input('按回车键退出...')
        except EOFError:
            pass
    sys.exit(1)


sys.excepthook = show_error_and_exit


def main():
    _setup_workdir()
    from PyQt6.QtCore import QSharedMemory
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv)
    app.setApplicationName('快捷回复')

    # 单实例互斥：第二次启动时提示并退出，避免多开窗口
    single_instance = QSharedMemory('QuickReply_SingleInstance_9f3b1c7e')
    if not single_instance.create(1):
        if single_instance.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
            QMessageBox.information(None, '快捷回复', '快捷回复已在运行中，请勿重复打开。')
        sys.exit(0)

    from main_window import KefuHelperApp
    window = KefuHelperApp()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
