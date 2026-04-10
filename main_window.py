import webbrowser

from PySide6.QtWidgets import QMainWindow, QLabel, QTabWidget
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
        viz_url = "https://a0kuma.github.io/pytorchMemoryViz/"

        if _HAS_WEBENGINE:
            tabs = QTabWidget(self)
            self.setCentralWidget(tabs)

            self.main_browser = _QWebEngineView(self)
            self.main_browser.load(_QUrl(url))
            tabs.addTab(self.main_browser, "main_browser")

            self.browser_Viz = _QWebEngineView(self)
            self.browser_Viz.load(_QUrl(viz_url))
            tabs.addTab(self.browser_Viz, "browser_Viz")

            # Keep the window title aligned with the currently visible page.
            def _sync_title() -> None:
                current = tabs.currentWidget()
                if isinstance(current, _QWebEngineView):
                    page_title = current.title().strip()
                    self.setWindowTitle(page_title or "PyTorch Memory Profiler")
                else:
                    self.setWindowTitle("PyTorch Memory Profiler")

            tabs.currentChanged.connect(lambda _index: _sync_title())
            self.main_browser.titleChanged.connect(lambda _title: _sync_title())
            self.browser_Viz.titleChanged.connect(lambda _title: _sync_title())
            _sync_title()
        else:
            # Graceful fallback: open in external browser, show info label
            webbrowser.open(url)
            webbrowser.open(viz_url)
            label = QLabel(
                f"<p style='font-size:14px'>"
                f"<b>PySide6-WebEngine is not installed.</b><br><br>"
                f"Open these URLs in your browser:<br>"
                f"main_browser: <a href='{url}'>{url}</a><br>"
                f"browser_Viz: <a href='{viz_url}'>{viz_url}</a><br><br>"
                f"Install <code>pyside6-webengine</code> for the embedded view."
                f"</p>",
                self,
            )
            label.setAlignment(Qt.AlignCenter)
            label.setOpenExternalLinks(True)
            label.setWordWrap(True)
            self.setCentralWidget(label)
