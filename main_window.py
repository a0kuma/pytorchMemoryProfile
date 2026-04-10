import webbrowser

from PySide6.QtWidgets import QMainWindow, QLabel
from PySide6.QtCore import Qt

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView as _QWebEngineView
    from PySide6.QtCore import QUrl as _QUrl
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False


class MainWindow(QMainWindow):
    """
    Application window.

    When PySide6-WebEngine is available the UI is rendered inside an embedded
    QWebEngineView that loads the HTML/JS/CSS frontend served by the local
    Flask REST API.

    When PySide6-WebEngine is *not* installed the URL is opened in the system
    default browser and a simple label is shown instead.
    """

    def __init__(self, url: str):
        super().__init__()
        self.setWindowTitle("PyTorch Memory Profiler")
        self.resize(1400, 800)

        if _HAS_WEBENGINE:
            self._browser = _QWebEngineView(self)
            self.setCentralWidget(self._browser)
            self._browser.load(_QUrl(url))
            # Mirror the page <title> in the window title bar
            self._browser.titleChanged.connect(self.setWindowTitle)
        else:
            # Graceful fallback: open in external browser, show info label
            webbrowser.open(url)
            label = QLabel(
                f"<p style='font-size:14px'>"
                f"<b>PySide6-WebEngine is not installed.</b><br><br>"
                f"The REST API is running at:<br>"
                f"<a href='{url}'>{url}</a><br><br>"
                f"Open the URL above in your browser to use the interface.<br>"
                f"Install <code>pyside6-webengine</code> for the embedded view."
                f"</p>",
                self,
            )
            label.setAlignment(Qt.AlignCenter)
            label.setOpenExternalLinks(True)
            label.setWordWrap(True)
            self.setCentralWidget(label)
