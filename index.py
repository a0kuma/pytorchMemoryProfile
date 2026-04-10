import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    pickle_path = None
    if len(sys.argv) > 1:
        pickle_path = sys.argv[1]

    win = MainWindow(pickle_path=pickle_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
