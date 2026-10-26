"""Setup window around setup_mod.py: pick the game files and Xenia folder, install.

usage: python setup_gui.py [<file or folder> ...]   (pre-selects those files)"""
import contextlib
import io
import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import setup_mod as sm

TITLE = "Doritos Crash Course mods - Setup"
ROWS = [  # (key, label, what it's for when missing)
    ((sm.CC1, sm.GAME), "Doritos Crash Course", "needed to set up Crash Course"),
    ((sm.CC1, sm.UPDATE), "    Title Update 2", "optional: City Lights DLC and shirt colour fix"),
    ((sm.CC1, sm.DLC), "    City Lights DLC", "optional: extra courses, needs Title Update 2"),
    ((sm.CC2, sm.GAME), "Doritos Crash Course 2", "needed to set up Crash Course 2"),
    ((sm.CC2, sm.UPDATE), "    Title Update 2", "needed for Crash Course 2"),
]


class QueueWriter(io.TextIOBase):
    """stdout replacement that hands the text to the window."""

    def __init__(self, q):
        self.q = q

    def write(self, s):
        self.q.put(("text", s))
        return len(s)


class App:
    def __init__(self, root, paths):
        self.root, self.paths, self.found, self.problems = root, [], {}, []
        self.q, self.busy, self.xenia_exe = queue.Queue(), False, None
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.title(TITLE)
        root.minsize(680, 600)
        pad = {"padx": 12, "pady": 6}

        ttk.Label(root, text="Doritos Crash Course 1 & 2 for Xenia",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(root, wraplength=650, justify="left",
                  text="This builds the mods from your own copies of the games and installs "
                       "them into Xenia Canary. Your game files are only read, never changed."
                  ).pack(anchor="w", **pad)

        files = ttk.LabelFrame(root, text=" 1. Your game files ")
        files.pack(fill="x", **pad)
        ttk.Label(files, wraplength=630, justify="left",
                  text="Add the game packages or the .zip files you have them in, or a folder "
                       "that contains them. Setup recognizes each file by its content, so the "
                       "file names don't matter.").grid(row=0, column=0, columnspan=4,
                                                        sticky="w", padx=8, pady=4)
        buttons = ttk.Frame(files)
        buttons.grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=4)
        self.inputs = [ttk.Button(buttons, text="Add files...", command=self.add_files),
                       ttk.Button(buttons, text="Add folder...", command=self.add_folder),
                       ttk.Button(buttons, text="Clear", command=self.clear)]
        for i, button in enumerate(self.inputs):
            button.pack(side="left", padx=(6 if i else 0, 0))
        self.status = {}
        for i, (key, label, _) in enumerate(ROWS):
            ttk.Label(files, text=label).grid(row=2 + i, column=0, sticky="w", padx=8)
            self.status[key] = ttk.Label(files, text="")
            self.status[key].grid(row=2 + i, column=1, sticky="w", padx=8)
        self.plan_label = ttk.Label(files, text="", wraplength=630, justify="left")
        self.plan_label.grid(row=2 + len(ROWS), column=0, columnspan=4, sticky="w", padx=8,
                             pady=(4, 8))

        xenia = ttk.LabelFrame(root, text=" 2. Xenia Canary ")
        xenia.pack(fill="x", **pad)
        ttk.Label(xenia, text="The folder with xenia_canary.exe:").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self.xenia = tk.StringVar(value=sm.default_xenia() or "")
        self.xenia.trace_add("write", lambda *_: self.refresh())
        entry = ttk.Entry(xenia, textvariable=self.xenia, width=70)
        entry.grid(row=1, column=0, sticky="we", padx=8)
        browse = ttk.Button(xenia, text="Browse...", command=self.browse_xenia)
        browse.grid(row=1, column=1, padx=(0, 8))
        self.inputs += [entry, browse]
        self.xenia_label = ttk.Label(xenia, text="", wraplength=630, justify="left")
        self.xenia_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 8))
        xenia.columnconfigure(0, weight=1)

        bottom = ttk.Frame(root)
        bottom.pack(fill="both", expand=True, **pad)
        actions = ttk.Frame(bottom)
        actions.pack(fill="x")
        self.install_button = ttk.Button(actions, text="Install", command=self.install)
        self.install_button.pack(side="left")
        self.play_buttons = {}
        for title, text in ((sm.CC1, "Play Crash Course"), (sm.CC2, "Play Crash Course 2")):
            self.play_buttons[title] = ttk.Button(actions, text=text,
                                                  command=lambda t=title: self.play(t))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=160)
        self.log = ScrolledText(bottom, height=10, wrap="word", state="disabled",
                                font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, pady=(8, 0))

        if paths:
            self.add(paths)
        self.refresh()

    # game files ---------------------------------------------------------
    def add_files(self):
        picked = filedialog.askopenfilenames(title="Choose your game files")
        if picked:
            self.add(list(picked))

    def add_folder(self):
        picked = filedialog.askdirectory(title="Choose a folder with your game files")
        if picked:
            self.add([picked])

    def clear(self):
        self.paths, self.found, self.problems = [], {}, []
        self.refresh()

    def add(self, paths):
        self.paths += [os.path.normpath(p) for p in paths]
        self.root.config(cursor="watch")
        self.root.update()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.found, self.problems = sm.find_packages(self.paths)
        finally:
            self.root.config(cursor="")
        self.refresh()

    # xenia ----------------------------------------------------------------
    def browse_xenia(self):
        picked = filedialog.askdirectory(title="Choose your Xenia Canary folder")
        if picked:
            self.xenia.set(os.path.normpath(picked))

    def chosen_xenia_folder(self):
        """The Xenia field as a folder; strips quotes ("Copy as path") and a
        trailing xenia_canary.exe."""
        folder = self.xenia.get().strip().strip('"')
        if folder.lower().endswith(".exe"):
            folder = os.path.dirname(folder)
        return folder

    # state ------------------------------------------------------------------
    def refresh(self):
        for key, _, missing in ROWS:
            ok = key in self.found
            self.status[key].config(text="found" if ok else f"not found ({missing})",
                                    foreground="green" if ok else "gray")
        games, notes = sm.plan(self.found)
        names = [g.name for g in games]
        if names:
            text = "Will set up: " + " and ".join(names) + "."
        elif self.paths:
            text = "No game recognized yet among the files you added."
        else:
            text = "Nothing added yet."
        self.plan_label.config(text="\n".join([text] + notes + self.problems))

        folder = self.chosen_xenia_folder()
        if not sm.is_xenia(folder):
            self.xenia_label.config(
                text="xenia_canary.exe is not in this folder. Download Xenia Canary, unpack it, "
                     "and choose its folder here.", foreground="red")
        elif not os.path.isfile(sm.config_path(folder)):
            self.xenia_label.config(
                text="Found, but Xenia has no settings file yet. Start Xenia once, close it, "
                     "and then install (otherwise the games run as trial versions).",
                foreground="darkorange")
        else:
            self.xenia_label.config(text="Found.", foreground="green")
        ready = games and sm.is_xenia(folder) and not self.busy
        self.install_button.config(state="normal" if ready else "disabled")
        for widget in self.inputs:
            widget.config(state="disabled" if self.busy else "normal")

    # install ----------------------------------------------------------------
    def write(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def install(self):
        if self.busy:
            return
        self.busy = True
        xenia = os.path.abspath(self.chosen_xenia_folder())
        self.refresh()
        for b in self.play_buttons.values():
            b.pack_forget()
        self.progress.pack(side="left", padx=12)
        self.progress.start(12)
        self.write("Setting up... this takes a minute or two per game. Please keep Xenia "
                   "closed meanwhile.\n")
        found = dict(self.found)

        def work():
            try:
                with contextlib.redirect_stdout(QueueWriter(self.q)):
                    result = sm.run(found, xenia, os.path.join(sm.ROOT, "build"))
                self.q.put(("done", result + (xenia,)))
            except sm.SetupError as e:
                self.q.put(("error", str(e)))
            except Exception:
                self.q.put(("crash", traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self.poll)

    def poll(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                if kind == "text":
                    self.write(value)
                    continue
                self.finish(kind, value)
                return
        except queue.Empty:
            self.root.after(100, self.poll)

    def finish(self, kind, value):
        self.busy = False
        self.progress.stop()
        self.progress.pack_forget()
        self.refresh()
        if kind == "error":
            self.write(f"\n{value}\n")
            messagebox.showerror(TITLE, value)
            return
        if kind == "crash":
            self.write("\n" + value)
            messagebox.showerror(TITLE, "Setup failed. The details are in the log at the "
                                        "bottom of the window.")
            return
        done, failed, full, xenia = value
        self.xenia_exe = os.path.join(xenia, "xenia_canary.exe")
        lines = [f"{g.name} is ready. Start it with the button below or with \"{g.play}\" "
                 "in the mod's folder." for g in done]
        lines += [f"{g.name} could not be set up: {why}" for g, why in failed]
        if full:
            lines.append(full)
        self.write("\n" + "\n".join(lines) + "\n")
        for g in done:
            self.play_buttons[g.title].pack(side="left", padx=(12, 0))
        if failed:
            messagebox.showwarning(TITLE, "\n\n".join(lines))
        else:
            messagebox.showinfo(TITLE, "Done!\n\n" + "\n\n".join(lines))

    def play(self, title):
        xex = os.path.join(sm.ROOT, "build", sm.GAMES[title].folder, "game", "default.xex")
        subprocess.Popen([self.xenia_exe, xex], cwd=os.path.dirname(self.xenia_exe))

    def close(self):
        if self.busy and not messagebox.askyesno(
                TITLE, "Setup is still working. Stop it and close the window? You can run "
                       "setup again later."):
            return
        self.root.destroy()


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    App(root, sys.argv[1:])
    root.mainloop()


if __name__ == "__main__":
    main()
