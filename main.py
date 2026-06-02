import tkinter as tk

from deadspace_checker.gui.app import BanCheckerGUI


def run_gui():
    root = tk.Tk()
    app = BanCheckerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
