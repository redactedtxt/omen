"""OMEN's Tkinter interface.

Design intent: quiet, editorial, typographic — an off-white page, near-black
ink, a single green accent. No chrome for chrome's sake. The pipeline runs on
a worker thread so the window never freezes mid-translation.
"""

import threading
import tkinter as tk
from tkinter import font as tkfont

import config
import coreAI
import core_lyrics

# Palette (2 colors + neutrals, deliberately restrained)
PAPER = "#f6f3ec"
INK = "#1b1b18"
MUTED = "#6f6a5f"
ACCENT = "#245642"
RULE = "#d9d4c7"
FIELD = "#fffdf8"


class OmenApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("OMEN: Punjabi to English lyric translator")
        root.configure(bg=PAPER)
        root.geometry("980x760")
        root.minsize(720, 560)

        self.display_font = tkfont.Font(family="Georgia", size=30, weight="bold")
        self.sub_font = tkfont.Font(family="Segoe UI", size=11)
        self.label_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.body_font = tkfont.Font(family="Segoe UI", size=12)
        self.punjabi_font = tkfont.Font(family="Segoe UI Semibold", size=12)
        self.status_font = tkfont.Font(family="Segoe UI", size=10)

        page = tk.Frame(root, bg=PAPER)
        page.pack(fill="both", expand=True, padx=48, pady=32)

        # --- Masthead ------------------------------------------------------
        tk.Label(page, text="OMEN", font=self.display_font,
                 bg=PAPER, fg=INK, anchor="w").pack(fill="x")
        tk.Label(page,
                 text="Paste a YouTube link to a Punjabi song. OMEN identifies the track, "
                      "cleans up the metadata, and returns the lyrics line by line: "
                      "Romanized Punjabi over an English translation.",
                 font=self.sub_font, bg=PAPER, fg=MUTED,
                 anchor="w", justify="left", wraplength=820).pack(fill="x", pady=(4, 18))

        tk.Frame(page, bg=RULE, height=1).pack(fill="x")

        # --- Input row -----------------------------------------------------
        form = tk.Frame(page, bg=PAPER)
        form.pack(fill="x", pady=(20, 6))

        tk.Label(form, text="YOUTUBE LINK", font=self.label_font,
                 bg=PAPER, fg=MUTED, anchor="w").pack(fill="x")

        row = tk.Frame(form, bg=PAPER)
        row.pack(fill="x", pady=(6, 0))

        self.entry = tk.Entry(row, font=self.body_font, bg=FIELD, fg=INK,
                              insertbackground=INK, relief="solid", bd=1,
                              highlightthickness=1, highlightbackground=RULE,
                              highlightcolor=ACCENT)
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 12))
        self.entry.bind("<Return>", lambda _e: self.on_translate())

        self.button = tk.Button(row, text="Translate", font=self.label_font,
                                bg=ACCENT, fg=PAPER, activebackground=INK,
                                activeforeground=PAPER, relief="flat",
                                padx=22, pady=9, cursor="hand2",
                                command=self.on_translate)
        self.button.pack(side="right")

        self.status = tk.Label(form, text="", font=self.status_font,
                               bg=PAPER, fg=MUTED, anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

        # --- Results -------------------------------------------------------
        results_frame = tk.Frame(page, bg=PAPER)
        results_frame.pack(fill="both", expand=True, pady=(14, 0))

        self.text = tk.Text(results_frame, font=self.body_font, bg=FIELD, fg=INK,
                            relief="solid", bd=1, wrap="word", padx=24, pady=20,
                            state="disabled", highlightthickness=0)
        scroll = tk.Scrollbar(results_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        self.text.tag_configure("song", font=self.punjabi_font, foreground=ACCENT,
                                spacing3=14)
        self.text.tag_configure("punjabi", font=self.punjabi_font, foreground=INK,
                                spacing1=10)
        self.text.tag_configure("english", font=self.body_font, foreground=MUTED,
                                lmargin1=18, lmargin2=18, spacing3=6)
        self.text.tag_configure("hint", foreground=MUTED)

        self._set_results_hint()

        missing = config.missing_keys()
        if missing:
            self._set_status(f"Missing API keys: {', '.join(missing)} — see .env.example", error=True)

    # --- Behaviour ---------------------------------------------------------

    def on_translate(self):
        url = self.entry.get().strip()
        if not url:
            self._set_status("Enter a YouTube link first.", error=True)
            return
        if config.missing_keys():
            self._set_status(
                f"Missing API keys: {', '.join(config.missing_keys())} — see .env.example",
                error=True)
            return

        self.button.configure(state="disabled")
        self._set_status("Identifying track…")
        threading.Thread(target=self._run_pipeline, args=(url,), daemon=True).start()

    def _run_pipeline(self, url: str):
        try:
            track, hit = core_lyrics.resolve_track(url)
            artist = (hit.artist_names if hit else None) or track.artist or "Unknown artist"
            title = track.title or track.raw_title

            if not hit:
                raise RuntimeError(
                    f"Couldn't find a lyrics page for “{title}”. "
                    "Double-check the link points to a Punjabi song."
                )

            self.root.after(0, self._set_status,
                            f"Found “{title}” by {artist}. Fetching lyrics…", False)
            lyrics = core_lyrics.fetch_lyrics_text(hit.url)

            self.root.after(0, self._set_status,
                            f"Translating “{title}”…", False)
            pairs = coreAI.translate_lyrics(artist=artist, title=title, lyrics=lyrics)
            self.root.after(0, self._show_results, title, artist, pairs)
        except Exception as exc:
            self.root.after(0, self._show_error, str(exc))

    def _show_results(self, title: str, artist: str, pairs):
        self.button.configure(state="normal")
        self._set_status(f"{len(pairs)} lines translated.")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", f"{title} · {artist}\n", "song")
        for pair in pairs:
            self.text.insert("end", pair.punjabi + "\n", "punjabi")
            if pair.english:
                self.text.insert("end", pair.english + "\n", "english")
        self.text.configure(state="disabled")

    def _show_error(self, message: str):
        self.button.configure(state="normal")
        self._set_status(message, error=True)

    def _set_status(self, message: str, error: bool = False):
        self.status.configure(text=message, fg="#8a3b2e" if error else MUTED)

    def _set_results_hint(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "Translations appear here.", "hint")
        self.text.configure(state="disabled")


# Backwards-compatible alias for main.py
mygui = OmenApp
