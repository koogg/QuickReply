from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QMouseEvent
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton


class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(0)

        self.icon_label = QLabel('💬')
        self.icon_label.setFixedWidth(28)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel('快捷回复v1.0.4_by52pojie_KOOGG')
        self.title_label.setFont(QFont('Microsoft YaHei UI', 11, QFont.Weight.Bold))
        self.title_label.setStyleSheet('color: #D0E0F0;')
        layout.addWidget(self.title_label)
        layout.addStretch()

        min_btn = QPushButton('─')
        min_btn.setFixedSize(32, 28)
        min_btn.clicked.connect(parent.showMinimized)
        layout.addWidget(min_btn)

        close_btn = QPushButton('✕')
        close_btn.setFixedSize(32, 28)
        close_btn.clicked.connect(parent.close)
        layout.addWidget(close_btn)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.parent_window.windowHandle()
            if handle:
                handle.startSystemMove()
            event.accept()