"""python -m archive_viewer [backup.zip|part.wtb] -- no bot/DB/env required."""
import argparse
from pathlib import Path
import webbrowser

from archive_viewer.server import ViewerServer


def main():
    parser = argparse.ArgumentParser(description="Офлайн-просмотрщик WatchTowerBot")
    parser.add_argument("archive", nargs="?", help="ZIP или любая часть .wtb (остальные части рядом)")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        from archive_viewer.self_test import run
        run()
        return
    path = args.archive
    if not path:
        from tkinter import Tk, filedialog
        root = Tk()
        root.withdraw()
        path = filedialog.askopenfilename(title="Открыть бекап WatchTowerBot", filetypes=[("Бекапы", "*.zip *.wtb")])
        root.destroy()
    if not path:
        return
    if not Path(path).is_file():
        parser.error("Файл не найден")
    with ViewerServer(path) as server:
        url = server.origin + "/#" + server.token
        print("Просмотрщик работает только на этом ПК. Для завершения нажмите Ctrl+C.")
        print(url)
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
