"""Exercise construction and navigation of the Windows GUI without requiring a GPU or server."""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import Desktop


def main() -> int:
    try:
        probe = tk.Tk()
        probe.withdraw()
        probe.destroy()
    except tk.TclError as exc:
        print("GUI smoke skipped: interactive desktop not available:", exc)
        return 0

    app = Desktop()
    try:
        app.withdraw()
        assert len(app.pages) == 6
        assert len(app.nav_buttons) == 6
        for index in range(6):
            app._show_page(index)
            assert app._page_index == index
        app._show_page(3)
        app._chat_append("Test", "UI rendering check")
        app.new_chat()
        app._show_page(4)
        app.monitor_state.set("IDLE")
        app.monitor_queue.set("0")
        app._show_page(0)
        app._set_busy(False)
        app.update_idletasks()
        print("Windows GUI smoke passed: six views, controls, chat, monitor and navigation")
        return 0
    finally:
        app._closing = True
        app.destroy()


if __name__ == "__main__":
    sys.exit(main())
