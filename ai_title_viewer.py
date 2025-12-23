# ai_title_viewer_v27_MAIN_FINAL_v5.py
# v5:
# - Wikipedia を検索エンジンに追加
# - 「検索エンジン編集」窓を追加（追加/編集/削除・既定に戻す）
# - エンジン設定は ini に保存（ai_title_viewer_main.ini / [engines]）
#
# 仕様:
# - URLテンプレートは {} を1つ含む（検索語はURLエンコード済みで差し込む）
#   例: https://www.google.com/search?q={}
# - MAIN：どの語句で検索するか（RAW/検索キー）をプレビュー表示
# - 材料収集：別ウィンド（EX/KEEP/無視語 + AI用文章コピー）
# - 工房起動ボタンあり（既定: ai_title_workshop_v27_SAFE.py）

import os
import re
import sys
import time
import subprocess
import webbrowser
import urllib.parse
import configparser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

APP_TITLE = "AI Title Viewer v27 - FINAL v5"
APP_INI = "ai_title_viewer_main.ini"
DEFAULT_WORKSHOP = "ai_title_workshop_v27_SAFE_COLOR_UNDO_TMP.py"

DEFAULT_GENRES = [
    "漫画",
    "小説",
    "アニメ",
    "ゲーム",
    "音楽",
    "映画",
    "資料",
]

DEFAULT_ENGINES: Dict[str, str] = {
    "Perplexity": "https://www.perplexity.ai/search?q={}",
    "ChatGPT":   "https://chatgpt.com/?q={}",
    "Google":    "https://www.google.com/search?q={}",
    "YouTube":   "https://www.youtube.com/results?search_query={}",
    "Wikipedia": "https://ja.wikipedia.org/w/index.php?search={}",
}

DIGITS_ONLY_RE = re.compile(r"^[0-9]+$")
SPACES_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[!！?？,，.．・:：;；/／\\|｜~〜^＾`´'\"\[\]\(\)（）【】{}<>＜＞「」『』]")

def app_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(app_dir(), APP_INI), encoding="utf-8")
    return cfg

def save_config(cfg: configparser.ConfigParser) -> None:
    try:
        with open(os.path.join(app_dir(), APP_INI), "w", encoding="utf-8") as f:
            cfg.write(f)
    except Exception:
        pass

def load_engines(cfg: configparser.ConfigParser) -> Dict[str, str]:
    if not cfg.has_section("engines"):
        cfg["engines"] = {}
    engines = {}
    # Load saved
    for k, v in cfg.items("engines"):
        name = k.strip()
        tpl = v.strip()
        if not name or not tpl:
            continue
        # configparser lowercases keys by default; keep original-ish by title-casing if matches defaults
        # We'll store display names separately in a list (see below). Here, just use as-is.
        engines[name] = tpl
    if not engines:
        # seed defaults
        engines = DEFAULT_ENGINES.copy()
        cfg["engines"] = {k: v for k, v in engines.items()}
        save_config(cfg)
    else:
        # merge in defaults that are missing (non-destructive)
        changed = False
        for k, v in DEFAULT_ENGINES.items():
            lk = k.lower()
            if lk not in engines and k not in engines:
                cfg["engines"][k] = v
                changed = True
        if changed:
            save_config(cfg)
        # Reload to include newly added defaults
        engines = {}
        for k, v in cfg.items("engines"):
            engines[k.strip()] = v.strip()
    return engines

def normalize_engine_display_name(name: str) -> str:
    # configparser のキーは小文字化されるので、見た目を少し整える
    # 既定に一致するものは既定の表記を使う
    for dk in DEFAULT_ENGINES.keys():
        if name.lower() == dk.lower():
            return dk
    # それ以外は先頭大文字
    return name[:1].upper() + name[1:] if name else name

def build_search_key(title_raw: str) -> str:
    s = (title_raw or "").strip().lower()
    s = PUNCT_RE.sub(" ", s)
    s = SPACES_RE.sub(" ", s).strip()
    return s

@dataclass
class Row:
    title_raw: str
    search_key: str
    path: str

class EngineEditor(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("検索エンジン編集")
        self.geometry("720x420")
        self.minsize(640, 380)
        self.transient(app)
        self.grab_set()

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(frm, text="URLテンプレートは {} を1つ含めてください（検索語はURLエンコード済みで差し込みます）").pack(anchor="w")

        body = ttk.Frame(frm)
        body.pack(fill="both", expand=True, pady=(10, 0))

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        self.lb = tk.Listbox(left, height=12)
        self.lb.pack(fill="both", expand=True)
        self.lb.bind("<<ListboxSelect>>", lambda e: self.on_select())

        right = ttk.Frame(body)
        right.pack(side="left", fill="y", padx=(12, 0))

        ttk.Button(right, text="追加", command=self.add_engine).pack(fill="x")
        ttk.Button(right, text="編集", command=self.edit_engine).pack(fill="x", pady=6)
        ttk.Button(right, text="削除", command=self.delete_engine).pack(fill="x")
        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=10)
        ttk.Button(right, text="既定に戻す", command=self.reset_defaults).pack(fill="x")

        details = ttk.LabelFrame(frm, text="選択中")
        details.pack(fill="x", pady=(10, 0))
        self.sel_name = tk.StringVar(value="")
        self.sel_tpl = tk.StringVar(value="")
        ttk.Label(details, text="名前:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(details, textvariable=self.sel_name, state="readonly").grid(row=0, column=1, sticky="we", padx=8, pady=6)
        ttk.Label(details, text="URL:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(details, textvariable=self.sel_tpl, state="readonly").grid(row=1, column=1, sticky="we", padx=8, pady=6)
        details.columnconfigure(1, weight=1)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="閉じる", command=self.close).pack(side="right")

    def refresh(self):
        self.lb.delete(0, "end")
        for name in self.app.engine_names():
            self.lb.insert("end", name)
        # select current default if present
        cur = self.app.engine_var.get()
        names = self.app.engine_names()
        if cur in names:
            idx = names.index(cur)
            self.lb.selection_set(idx)
            self.lb.see(idx)
            self.on_select()
        else:
            self.sel_name.set("")
            self.sel_tpl.set("")

    def on_select(self):
        sel = self.lb.curselection()
        if not sel:
            self.sel_name.set("")
            self.sel_tpl.set("")
            return
        name = self.lb.get(sel[0])
        tpl = self.app.engines.get(name, "")
        self.sel_name.set(name)
        self.sel_tpl.set(tpl)

    def _ask_name_tpl(self, title: str, init_name: str = "", init_tpl: str = "") -> Optional[Tuple[str, str]]:
        name = simpledialog.askstring(title, "表示名（例: DuckDuckGo）", initialvalue=init_name, parent=self)
        if name is None:
            return None
        name = name.strip()
        if not name:
            messagebox.showerror("エラー", "名前が空です。", parent=self)
            return None

        tpl = simpledialog.askstring(title, "URLテンプレート（{} を含む）", initialvalue=init_tpl, parent=self)
        if tpl is None:
            return None
        tpl = tpl.strip()
        if tpl.count("{}") != 1:
            messagebox.showerror("エラー", "{} を1つだけ含むURLテンプレートにしてください。", parent=self)
            return None
        return name, tpl

    def add_engine(self):
        res = self._ask_name_tpl("追加")
        if not res:
            return
        name, tpl = res
        if name in self.app.engines:
            messagebox.showerror("エラー", "同じ名前が既にあります。", parent=self)
            return
        self.app.engines[name] = tpl
        self.app.persist_engines()
        self.app.rebuild_engine_ui()
        self.refresh()

    def edit_engine(self):
        sel = self.lb.curselection()
        if not sel:
            return
        old = self.lb.get(sel[0])
        res = self._ask_name_tpl("編集", init_name=old, init_tpl=self.app.engines.get(old, ""))
        if not res:
            return
        name, tpl = res

        # rename handling
        if name != old and name in self.app.engines:
            messagebox.showerror("エラー", "変更先の名前が既にあります。", parent=self)
            return

        # apply
        del self.app.engines[old]
        self.app.engines[name] = tpl

        # update default selection if needed
        if self.app.engine_var.get() == old:
            self.app.engine_var.set(name)

        self.app.persist_engines()
        self.app.rebuild_engine_ui()
        self.refresh()

    def delete_engine(self):
        sel = self.lb.curselection()
        if not sel:
            return
        name = self.lb.get(sel[0])
        if len(self.app.engines) <= 1:
            messagebox.showerror("エラー", "最低1つは必要です。", parent=self)
            return
        if not messagebox.askyesno("確認", f"「{name}」を削除しますか？", parent=self):
            return
        del self.app.engines[name]
        if self.app.engine_var.get() == name:
            self.app.engine_var.set(self.app.engine_names()[0])
        self.app.persist_engines()
        self.app.rebuild_engine_ui()
        self.refresh()

    def reset_defaults(self):
        if not messagebox.askyesno("確認", "検索エンジン設定を既定に戻しますか？", parent=self):
            return
        self.app.engines = DEFAULT_ENGINES.copy()
        self.app.persist_engines(reset=True)
        self.app.rebuild_engine_ui()
        self.refresh()

    def close(self):
        self.destroy()

class MaterialsWindow(tk.Toplevel):
    # 目安
    EX_MIN, EX_MAX = 5, 15
    KEEP_MIN, KEEP_MAX = 3, 10

    COLOR_GRAY = "#666666"
    COLOR_GREEN = "#2e8b57"
    COLOR_BLUE = "#1e90ff"

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("材料収集（正規表現づくりの材料を集める）")
        self.geometry("1180x780")
        self.minsize(1020, 700)
        self.transient(app)

        self.left_mode = tk.StringVar(value="RAW")  # RAW / KEY
        self._build_ui()
        self.refresh_all()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(
            top,
            text="左の一覧から例を集めて、右の『ノイズあり／ノイズなし』に振り分けます。十分集まったらAIへ投げます。",
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(bar, text="左の一覧表示:").pack(side="left")
        ttk.Radiobutton(bar, text="RAW", value="RAW", variable=self.left_mode, command=self.refresh_left).pack(side="left", padx=6)
        ttk.Radiobutton(bar, text="検索キー", value="KEY", variable=self.left_mode, command=self.refresh_left).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)

        self.count_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.count_var).pack(side="left")

        ttk.Button(bar, text="無視語編集", command=self.app.open_ignore_editor).pack(side="right")
        ttk.Button(bar, text="材料をクリア", command=self.clear_materials).pack(side="right", padx=8)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=10)

        # Left list
        left = ttk.Frame(paned)
        paned.add(left, weight=2)

        self.tree = ttk.Treeview(left, columns=("t", "p"), show="headings", height=18)
        self.tree.heading("t", text="タイトル")
        self.tree.heading("p", text="パス")
        self.tree.column("t", width=560, anchor="w", stretch=True)
        self.tree.column("p", width=480, anchor="w", stretch=True)
        self.tree.pack(fill="both", expand=True)

        # --- NEW: 1行テキスト欄（ドラッグで語句選択） ---
        hint = ttk.Label(left, text="選択したタイトル（ドラッグで語句を拾えます）")
        hint.pack(anchor="w", pady=(8, 2))

        self.pick_text = tk.Text(left, height=2, wrap="word")
        self.pick_text.pack(fill="x")
        self.pick_text.configure(state="disabled")

        # 右クリックメニュー（無視語へ）
        self.word_menu = tk.Menu(self, tearoff=False)
        self.word_menu.add_command(label="選択語句 → 無視語に追加", command=self.add_selected_word_to_ignore)
        self.word_menu.add_command(label="全文 → 無視語に追加", command=self.add_full_text_to_ignore)
        self.pick_text.bind("<Button-3>", self._popup_word_menu)

        # 選択行が変わったらテキスト欄更新
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_pick_text())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="選択 → ノイズを含むタイトル に追加", command=self.add_to_ex).pack(side="left")
        ttk.Button(btns, text="選択 → ノイズを含まないタイトル に追加", command=self.add_to_keep).pack(side="left", padx=8)
        ttk.Button(btns, text="選択語句 → 無視語に追加", command=self.add_selected_word_to_ignore).pack(side="right")

        # Right collected
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        # EX
        exf = ttk.LabelFrame(right, text="ノイズを含むタイトル")
        exf.pack(fill="both", expand=True)

        self.ex_title = ttk.Label(exf, text="（種類が違うものを 5〜15件程度）", font=("Segoe UI", 10, "bold"))
        self.ex_title.pack(anchor="w", padx=8, pady=(8, 2))

        self.ex_list = tk.Listbox(exf, height=10)
        self.ex_list.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        exb = ttk.Frame(exf)
        exb.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(exb, text="削除", command=lambda: self.delete_selected(self.ex_list, self.app.material_ex)).pack(side="left")

        # KEEP
        keepf = ttk.LabelFrame(right, text="ノイズを含まないタイトル")
        keepf.pack(fill="both", expand=True)

        self.keep_title = ttk.Label(keepf, text="（“守りたい形”が伝わる 3〜10件程度）", font=("Segoe UI", 10, "bold"))
        self.keep_title.pack(anchor="w", padx=8, pady=(8, 2))

        self.keep_list = tk.Listbox(keepf, height=8)
        self.keep_list.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        keepb = ttk.Frame(keepf)
        keepb.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(keepb, text="削除", command=lambda: self.delete_selected(self.keep_list, self.app.material_keep)).pack(side="left")

        # Big button (AI prompt copy)
        big = ttk.Frame(self)
        big.pack(fill="x", padx=10, pady=(0, 10))
        try:
            style = ttk.Style()
            style.configure("Big.TButton", padding=(12, 12), font=("Segoe UI", 12, "bold"))
        except Exception:
            pass
        ttk.Button(big, text="AIで正規表現作成（ブラウザに貼る文章をコピー）", style="Big.TButton", command=self.copy_ai_prompt).pack(fill="x")

    def _popup_word_menu(self, e):
        # 右クリックしたら、まずフォーカスを当てる
        try:
            self.pick_text.focus_set()
        except Exception:
            pass
        self.word_menu.tk_popup(e.x_root, e.y_root)

    def _color_for_count(self, count: int, min_v: int, max_v: int) -> str:
        if count < min_v:
            return self.COLOR_GRAY
        if min_v <= count <= max_v:
            return self.COLOR_GREEN
        return self.COLOR_BLUE

    def _set_pick_text(self, s: str):
        self.pick_text.configure(state="normal")
        self.pick_text.delete("1.0", "end")
        self.pick_text.insert("1.0", s or "")
        self.pick_text.configure(state="disabled")

    def update_pick_text(self):
        # 左一覧の選択行から、RAW/検索キー（left_mode）に合わせて表示
        sel = self.tree.selection()
        if not sel:
            self._set_pick_text("")
            return
        iid = sel[0]
        try:
            r = self.app.rows[int(iid)]
        except Exception:
            self._set_pick_text("")
            return
        s = r.title_raw if self.left_mode.get() == "RAW" else r.search_key
        self._set_pick_text(s)

    def _add_ignore_tokens(self, text: str):
        # 複数語なら空白で分割して追加。空は無視。
        text = (text or "").strip()
        if not text:
            return 0
        tokens = [t.strip() for t in re.split(r"\s+", text) if t.strip()]
        added = 0
        for t in tokens:
            if t not in self.app.ignore_words:
                self.app.ignore_words.append(t)
                added += 1
        return added

    def add_selected_word_to_ignore(self):
        # Text の選択範囲を無視語に追加
        try:
            sel = self.pick_text.get("sel.first", "sel.last")
        except Exception:
            sel = ""
        sel = (sel or "").strip()
        if not sel:
            messagebox.showinfo("無視語", "テキスト欄で語句をドラッグ選択してください。")
            return
        added = self._add_ignore_tokens(sel)
        if added <= 0:
            return
        self.refresh_counts()

    def add_full_text_to_ignore(self):
        # 表示中の全文を無視語に追加（用途：完全一致で消したい語句があるとき）
        self.pick_text.configure(state="normal")
        full = self.pick_text.get("1.0", "end").strip()
        self.pick_text.configure(state="disabled")
        if not full:
            return
        added = self._add_ignore_tokens(full)
        if added <= 0:
            return
        self.refresh_counts()

    def refresh_left(self):
        for c in self.tree.get_children():
            self.tree.delete(c)
        mode = self.left_mode.get()
        for i, r in enumerate(self.app.rows):
            if self.app.hide_digits.get() and DIGITS_ONLY_RE.match(r.title_raw):
                continue
            title = r.title_raw if mode == "RAW" else r.search_key
            self.tree.insert("", "end", iid=str(i), values=(title, r.path))

        # 再描画後に選択行があればテキストも追従
        kids = self.tree.get_children()
        if kids and not self.tree.selection():
            self.tree.selection_set(kids[0])
        self.update_pick_text()

    def refresh_right(self):
        self.ex_list.delete(0, "end")
        self.keep_list.delete(0, "end")
        for t in self.app.material_ex:
            self.ex_list.insert("end", t)
        for t in self.app.material_keep:
            self.keep_list.insert("end", t)

    def refresh_counts(self):
        ex_n = len(self.app.material_ex)
        keep_n = len(self.app.material_keep)
        ig_n = len(self.app.ignore_words)

        self.count_var.set(f"ノイズあり:{ex_n}（目安 {self.EX_MIN}〜{self.EX_MAX}） / ノイズなし:{keep_n}（目安 {self.KEEP_MIN}〜{self.KEEP_MAX}） / 無視語:{ig_n}")

        self.ex_title.configure(
            text=f"（種類が違うものを {self.EX_MIN}〜{self.EX_MAX}件程度）  現在: {ex_n}",
            foreground=self._color_for_count(ex_n, self.EX_MIN, self.EX_MAX),
        )
        self.keep_title.configure(
            text=f"（“守りたい形”が伝わる {self.KEEP_MIN}〜{self.KEEP_MAX}件程度）  現在: {keep_n}",
            foreground=self._color_for_count(keep_n, self.KEEP_MIN, self.KEEP_MAX),
        )

    def refresh_all(self):
        self.refresh_left()
        self.refresh_right()
        self.refresh_counts()
        self.update_pick_text()

    def selected_rows(self) -> List[Row]:
        out = []
        for iid in self.tree.selection():
            try:
                out.append(self.app.rows[int(iid)])
            except Exception:
                pass
        return out

    def add_to_ex(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("材料", "左の一覧から行を選択してください。")
            return
        for r in rows:
            t = r.title_raw
            if t not in self.app.material_ex:
                self.app.material_ex.append(t)
            if t in self.app.material_keep:
                self.app.material_keep.remove(t)
        self.refresh_all()

    def add_to_keep(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("材料", "左の一覧から行を選択してください。")
            return
        for r in rows:
            t = r.title_raw
            if t not in self.app.material_keep:
                self.app.material_keep.append(t)
            if t in self.app.material_ex:
                self.app.material_ex.remove(t)
        self.refresh_all()

    def delete_selected(self, lb: tk.Listbox, backing: List[str]):
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        try:
            backing.pop(idx)
        except Exception:
            pass
        self.refresh_all()

    def clear_materials(self):
        if not messagebox.askyesno("確認", "ノイズあり/ノイズなし の材料をすべてクリアしますか？"):
            return
        self.app.material_ex.clear()
        self.app.material_keep.clear()
        self.refresh_all()

    def copy_ai_prompt(self):
        if not self.app.rows:
            messagebox.showinfo("AI", "先にフォルダを読み込んでください。")
            return
        prompt = self.app.build_ai_prompt()
        self.clipboard_clear()
        self.clipboard_append(prompt)
        messagebox.showinfo("コピー", "ブラウザのAIへ貼り付けてください。\\n生成結果は工房へ貼り付けて育てます。")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.engines = {normalize_engine_display_name(k): v for k, v in load_engines(self.cfg).items()}
        self.genres = self.load_genres_from_cfg()
        self.genre_var = tk.StringVar(value=self.cfg.get("app", "genre", fallback="（無選択）"))
        if self.genre_var.get() not in (["（無選択）"] + self.genres):
            self.genre_var.set("（無選択）")

        # --- genres ---
        self.genres = self.load_genres_from_cfg()
        self.genre_var = tk.StringVar(value=self.cfg.get("app", "genre", fallback="（無選択）"))
        if self.genre_var.get() not in (["（無選択）"] + self.genres):
            self.genre_var.set("（無選択）")

        # default engine
        default_engine = self.cfg.get("app", "default_engine", fallback="Perplexity")
        default_engine = normalize_engine_display_name(default_engine)
        if default_engine not in self.engines:
            default_engine = list(self.engines.keys())[0]

        self.title(APP_TITLE)
        self.geometry("1200x820")
        self.minsize(1020, 700)

        self.rows: List[Row] = []
        self.filtered: List[int] = []

        self.engine_var = tk.StringVar(value=default_engine)
        self.hide_digits = tk.BooleanVar(value=True)

        self.show_raw = tk.BooleanVar(value=True)
        self.show_key = tk.BooleanVar(value=False)
        self.show_path = tk.BooleanVar(value=True)

        self.search_mode = tk.StringVar(value="RAW")  # RAW / KEY

        self.material_ex: List[str] = []
        self.material_keep: List[str] = []
        self.ignore_words: List[str] = []

        self.material_win: Optional[MaterialsWindow] = None
        self.workshop_path: Optional[str] = None

        self._build_ui()
        self.rebuild_columns()

    # ---------- engines persistence ----------
    def engine_names(self) -> List[str]:
        return list(self.engines.keys())

    def persist_engines(self, reset: bool = False):
        if not self.cfg.has_section("engines"):
            self.cfg["engines"] = {}
        if reset:
            self.cfg["engines"] = {k: v for k, v in self.engines.items()}
        else:
            # rewrite
            self.cfg.remove_section("engines")
            self.cfg["engines"] = {k: v for k, v in self.engines.items()}

        if not self.cfg.has_section("app"):
            self.cfg["app"] = {}
        self.cfg["app"]["default_engine"] = self.engine_var.get()
        if hasattr(self, "genre_var"):
            self.cfg["app"]["genre"] = self.genre_var.get()
        save_config(self.cfg)

    def rebuild_engine_ui(self):
        # update optionmenu
        names = self.engine_names()
        if self.engine_var.get() not in names and names:
            self.engine_var.set(names[0])

        menu = self.engine_option["menu"]
        menu.delete(0, "end")
        for n in names:
            menu.add_command(label=n, command=lambda v=n: self._set_engine(v))

        # rebuild right-click menu
        self.menu.delete(0, "end")
        self.menu.add_command(label="AI検索（デフォルト）", command=self.ai_search)
        self.menu.add_separator()
        for name in names:
            self.menu.add_command(label=f"{name}で検索", command=lambda n=name: self.ai_search(engine=n))

        self.persist_engines()
        self.update_status()

    # ---------- genres persistence ----------
    def load_genres_from_cfg(self) -> List[str]:
        if not self.cfg.has_section("genres"):
            self.cfg["genres"] = {g: "1" for g in DEFAULT_GENRES}
            save_config(self.cfg)

        genres = []
        for k, _v in self.cfg.items("genres"):
            name = k.strip()
            if name:
                genres.append(name)

        if not genres:
            genres = DEFAULT_GENRES[:]
            self.cfg["genres"] = {g: "1" for g in genres}
            save_config(self.cfg)

        order = {g: i for i, g in enumerate(DEFAULT_GENRES)}
        genres.sort(key=lambda x: order.get(x, 999))
        return genres

    def persist_genres_to_cfg(self):
        # rewrite [genres]
        if self.cfg.has_section("genres"):
            self.cfg.remove_section("genres")
        self.cfg["genres"] = {g: "1" for g in self.genres}
        if not self.cfg.has_section("app"):
            self.cfg["app"] = {}
        self.cfg["app"]["genre"] = self.genre_var.get()
        save_config(self.cfg)

    def _set_genre(self, g: str):
        self.genre_var.set(g)
        self.persist_genres_to_cfg()
        self.update_status()

    def open_genre_editor(self):
        win = tk.Toplevel(self)
        win.title("ジャンル編集")
        win.geometry("520x420")
        win.minsize(480, 360)
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(frm, text="ジャンル一覧（本体では文脈としてAIに渡します）").pack(anchor="w")

        lb = tk.Listbox(frm, height=12)
        lb.pack(fill="both", expand=True, pady=(8, 8))
        for g in self.genres:
            lb.insert("end", g)

        btns = ttk.Frame(frm)
        btns.pack(fill="x")

        def refresh_lb():
            lb.delete(0, "end")
            for gg in self.genres:
                lb.insert("end", gg)

        def add_genre():
            name = simpledialog.askstring("追加", "ジャンル名", parent=win)
            if name is None:
                return
            name = name.strip()
            if not name or name in self.genres:
                return
            self.genres.append(name)
            refresh_lb()

        def rename_genre():
            sel = lb.curselection()
            if not sel:
                return
            old = lb.get(sel[0])
            name = simpledialog.askstring("変更", "ジャンル名", initialvalue=old, parent=win)
            if name is None:
                return
            name = name.strip()
            if not name or (name != old and name in self.genres):
                return
            idx2 = self.genres.index(old)
            self.genres[idx2] = name
            if self.genre_var.get() == old:
                self.genre_var.set(name)
            refresh_lb()

        def delete_genre():
            sel = lb.curselection()
            if not sel:
                return
            g = lb.get(sel[0])
            if not messagebox.askyesno("確認", f"「{g}」を削除しますか？", parent=win):
                return
            if g in self.genres:
                self.genres.remove(g)
            if self.genre_var.get() == g:
                self.genre_var.set("（無選択）")
            refresh_lb()

        def restore_defaults():
            if not messagebox.askyesno("確認", "既定ジャンルに戻しますか？", parent=win):
                return
            self.genres = DEFAULT_GENRES[:]
            if self.genre_var.get() not in (["（無選択）"] + self.genres):
                self.genre_var.set("（無選択）")
            refresh_lb()

        ttk.Button(btns, text="追加", command=add_genre).pack(side="left")
        ttk.Button(btns, text="変更", command=rename_genre).pack(side="left", padx=8)
        ttk.Button(btns, text="削除", command=delete_genre).pack(side="left")
        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(btns, text="既定に戻す", command=restore_defaults).pack(side="left")

        bottom = ttk.Frame(frm)
        bottom.pack(fill="x", pady=(10, 0))

        def on_save():
            self.persist_genres_to_cfg()
            self.genre_combo["values"] = ["（無選択）"] + self.genres
            if self.genre_var.get() not in self.genre_combo["values"]:
                self.genre_var.set("（無選択）")
            self.update_status()
            win.destroy()

        ttk.Button(bottom, text="キャンセル", command=win.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", command=on_save).pack(side="right", padx=8)

    def _set_engine(self, name: str):
        self.engine_var.set(name)
        self.persist_engines()
        self.update_status()

    # ---------- UI ----------
    def _build_ui(self):
        # Menu bar
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        m_tools = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="ツール", menu=m_tools)
        m_tools.add_command(label="検索エンジン編集", command=self.open_engine_editor)
        m_tools.add_separator()
        m_tools.add_command(label="無視語編集", command=self.open_ignore_editor)
        m_tools.add_separator()
        m_tools.add_command(label="ジャンル編集", command=self.open_genre_editor)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text="フォルダ選択", command=self.pick_folder).pack(side="left")
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var, width=56).pack(side="left", padx=6)
        ttk.Button(top, text="読み込み", command=self.load).pack(side="left", padx=6)

        ttk.Label(top, text="検索エンジン:").pack(side="left", padx=(20, 4))
        self.engine_option = ttk.OptionMenu(top, self.engine_var, self.engine_var.get(), *self.engine_names(), command=lambda _: self.persist_engines())
        self.engine_option.pack(side="left")

        ttk.Button(top, text="エンジン編集", command=self.open_engine_editor).pack(side="left", padx=8)

        ttk.Label(top, text="ジャンル:").pack(side="left", padx=(14, 4))
        self.genre_combo = ttk.Combobox(top, textvariable=self.genre_var, state="readonly", width=14)
        self.genre_combo["values"] = ["（無選択）"] + list(self.genres)
        self.genre_combo.pack(side="left")
        self.genre_combo.bind("<<ComboboxSelected>>", lambda e: self._set_genre(self.genre_var.get()))
        ttk.Button(top, text="ジャンル編集", command=self.open_genre_editor).pack(side="left", padx=8)

        opt = ttk.LabelFrame(self, text="表示オプション / 検索モード")
        opt.pack(fill="x", padx=10, pady=(0, 8))

        r0 = ttk.Frame(opt)
        r0.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Checkbutton(r0, text="数字のみのタイトルを非表示", variable=self.hide_digits, command=self.apply_filter).pack(side="left")

        ttk.Separator(r0, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(r0, text="AI検索に使う語句:").pack(side="left")
        ttk.Radiobutton(r0, text="RAW", value="RAW", variable=self.search_mode, command=self.update_search_preview).pack(side="left", padx=6)
        ttk.Radiobutton(r0, text="検索キー", value="KEY", variable=self.search_mode, command=self.update_search_preview).pack(side="left")

        r1 = ttk.Frame(opt)
        r1.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(r1, text="表示する列:").pack(side="left")
        ttk.Checkbutton(r1, text="RAWタイトル", variable=self.show_raw, command=self.rebuild_columns).pack(side="left", padx=(10, 0))
        ttk.Checkbutton(r1, text="検索キー（整形後）", variable=self.show_key, command=self.rebuild_columns).pack(side="left", padx=10)
        ttk.Checkbutton(r1, text="パス", variable=self.show_path, command=self.rebuild_columns).pack(side="left")

        pv = ttk.Frame(self)
        pv.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(pv, text="今回AIに投げる語句:").pack(side="left")
        self.search_preview = tk.StringVar(value="（未選択）")
        ttk.Entry(pv, textvariable=self.search_preview, state="readonly", width=90).pack(side="left", padx=8, fill="x", expand=True)

        big = ttk.Frame(self)
        big.pack(fill="x", padx=10, pady=(0, 10))
        try:
            style = ttk.Style()
            style.configure("Big.TButton", padding=(10, 10), font=("Segoe UI", 12, "bold"))
        except Exception:
            pass
        ttk.Button(big, text="AI検索（選択タイトル）", style="Big.TButton", command=self.ai_search).pack(side="left", fill="x", expand=True)
        ttk.Button(big, text="材料収集", style="Big.TButton", command=self.open_materials).pack(side="left", padx=10)
        ttk.Button(big, text="工房を開く", style="Big.TButton", command=self.launch_workshop).pack(side="left")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tree = ttk.Treeview(mid, show="headings", height=18)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<ButtonRelease-1>", lambda e: self.update_search_preview())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_search_preview())
        self.tree.bind("<Button-3>", self._popup_menu)

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="AI検索（デフォルト）", command=self.ai_search)
        self.menu.add_separator()
        for name in self.engine_names():
            self.menu.add_command(label=f"{name}で検索", command=lambda n=name: self.ai_search(engine=n))

        self.status_var = tk.StringVar(value="未読み込み")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=10, pady=(0, 8))

    def open_engine_editor(self):
        EngineEditor(self)

    # ---------- data ----------
    def pick_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.path_var.set(d)

    def load(self):
        folder = self.path_var.get().strip()
        if not os.path.isdir(folder):
            messagebox.showerror("エラー", "フォルダを選択してください")
            return
        self.rows.clear()
        for root, _, files in os.walk(folder):
            for f in files:
                raw, _ = os.path.splitext(f)
                self.rows.append(Row(raw, build_search_key(raw), os.path.join(root, f)))
        self.apply_filter()

    def apply_filter(self):
        self.filtered.clear()
        for i, r in enumerate(self.rows):
            if self.hide_digits.get() and DIGITS_ONLY_RE.match(r.title_raw):
                continue
            self.filtered.append(i)
        self.render()
        self.update_search_preview()
        self.update_status()
        if self.material_win and self.material_win.winfo_exists():
            self.material_win.refresh_all()

    def rebuild_columns(self):
        if (not self.show_raw.get()) and (not self.show_key.get()):
            self.show_raw.set(True)

        cols = []
        if self.show_raw.get():
            cols.append(("raw", "RAWタイトル", 420))
        if self.show_key.get():
            cols.append(("key", "検索キー（整形後）", 360))
        if self.show_path.get():
            cols.append(("path", "パス", 520))

        self.tree["columns"] = [c[0] for c in cols]
        for cid, text, width in cols:
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, anchor="w", stretch=True)

        self.render()
        self.update_search_preview()
        self.update_status()

    def render(self):
        for c in self.tree.get_children():
            self.tree.delete(c)

        cols = self.tree["columns"]
        for i in self.filtered:
            r = self.rows[i]
            vals = []
            for cid in cols:
                if cid == "raw":
                    vals.append(r.title_raw)
                elif cid == "key":
                    vals.append(r.search_key)
                elif cid == "path":
                    vals.append(r.path)
                else:
                    vals.append("")
            self.tree.insert("", "end", iid=str(i), values=tuple(vals))

        kids = self.tree.get_children()
        if kids and not self.tree.selection():
            self.tree.selection_set(kids[0])

    def selected_row(self) -> Optional[Row]:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self.rows[int(sel[0])]
        except Exception:
            return None

    def current_query(self) -> str:
        r = self.selected_row()
        if not r:
            return ""
        return r.title_raw if self.search_mode.get() == "RAW" else r.search_key

    def update_search_preview(self):
        q = self.current_query()
        mode = "RAW" if self.search_mode.get() == "RAW" else "検索キー"
        self.search_preview.set(f"[{mode}] {q}" if q else "（未選択）")

    def ai_search(self, engine: str = None):
        if not self.selected_row():
            messagebox.showinfo("AI検索", "タイトルを選択してください")
            return
        eng = engine or self.engine_var.get()
        if eng not in self.engines:
            eng = self.engine_names()[0]
        tpl = self.engines[eng]
        q = self.current_query()
        q_enc = urllib.parse.quote(q, safe="")
        try:
            url = tpl.format(q_enc)
        except Exception:
            messagebox.showerror("エラー", f"URLテンプレートが不正です: {tpl}")
            return
        webbrowser.open(url)

    def _popup_menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid:
            self.tree.selection_set(iid)
            self.update_search_preview()
            self.menu.tk_popup(e.x_root, e.y_root)

    # ---------- materials ----------
    def open_materials(self):
        if self.material_win and self.material_win.winfo_exists():
            self.material_win.lift()
            self.material_win.focus_force()
            return
        self.material_win = MaterialsWindow(self)

    def open_ignore_editor(self):
        win = tk.Toplevel(self)
        win.title("無視語の編集")
        win.geometry("420x420")
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(frm, text="1行=1語（空行は無視）").pack(anchor="w")

        txt = tk.Text(frm, wrap="word", height=18)
        txt.pack(fill="both", expand=True, pady=(6, 10))
        txt.insert("1.0", "\n".join(self.ignore_words))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")

        def on_save():
            raw = txt.get("1.0", "end").splitlines()
            self.ignore_words = [x.strip() for x in raw if x.strip()]
            win.destroy()
            if self.material_win and self.material_win.winfo_exists():
                self.material_win.refresh_all()

        ttk.Button(btns, text="保存", command=on_save).pack(side="right")
        ttk.Button(btns, text="キャンセル", command=win.destroy).pack(side="right", padx=8)

    def build_ai_prompt(self) -> str:
        folder = self.path_var.get().strip()
        ex = self.material_ex[:80]
        keep = self.material_keep[:50]
        ig = self.ignore_words[:80]
        sample = [self.rows[i].title_raw for i in self.filtered[:120]]

        lines = []
        lines.append("あなたは正規表現の専門家です。次の『タイトル名のゴミ』を削除する正規表現ルール案を複数作ってください。")
        lines.append("")
        lines.append("【目的】")
        lines.append("- ファイル名は変更せず、文字列からゴミだけを除去して検索・分類に使う。")
        lines.append("- ルールは小さく分割し、ON/OFFしやすく。")
        lines.append("- それぞれ『何を消すか』を短く説明する。")
        lines.append("")
        if folder:
            lines.append(f"【対象フォルダ】{folder}")
        g = self.genre_var.get() if hasattr(self, "genre_var") else "（無選択）"
        if g and g != "（無選択）":
            lines.append(f"【ジャンル】{g}")
        lines.append(f"【作成日時】{time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        if ig:
            lines.append("【無視語（候補）】")
            lines.extend([f"- {w}" for w in ig])
            lines.append("")
        if ex:
            lines.append("【EX: 消したい例（ゴミ入り）】")
            lines.extend([f"- {t}" for t in ex])
            lines.append("")
        if keep:
            lines.append("【KEEP: 消さない例】")
            lines.extend([f"- {t}" for t in keep])
            lines.append("")
        lines.append("【追加サンプル（傾向）】")
        lines.extend([f"- {t}" for t in sample])
        lines.append("")
        lines.append("【出力フォーマット】（ルールごと）")
        lines.append("- name: ルール名")
        lines.append("- pattern: 正規表現（1行）")
        lines.append("- why: 何を消すか（日本語で簡潔）")
        lines.append("- 注意: 誤爆しそうな例")
        lines.append("")
        return "\n".join(lines)

    # ---------- workshop ----------
    def resolve_workshop(self) -> Optional[str]:
        if self.workshop_path and os.path.exists(self.workshop_path):
            return self.workshop_path
                # 同フォルダ内の候補を順に探す（新しいもの優先）
        candidates = [
            DEFAULT_WORKSHOP,
            "ai_title_workshop_v27_SAFE_COLOR_UNDO_TMP.py",
            "ai_title_workshop_v27_SAFE_COLOR_UNDO.py",
            "ai_title_workshop_v27_SAFE_COLOR.py",
            "ai_title_workshop_v27_SAFE.py",
            "ai_title_workshop_v27.py",
        ]
        for fn in candidates:
            cand = os.path.join(app_dir(), fn)
            if os.path.exists(cand):
                self.workshop_path = cand
                return cand
        path = filedialog.askopenfilename(title="工房の .py を選択", initialdir=app_dir(), filetypes=[("Python file", "*.py"), ("All files", "*.*")])
        if path and os.path.exists(path):
            self.workshop_path = path
            return path
        return None

    def launch_workshop(self):
        """工房を同一プロセス内で開く（EXE化でも動く）"""
        try:
            import ai_title_workshop
        except Exception as e:
            messagebox.showerror(
                "工房",
                "工房モジュール（ai_title_workshop.py）が見つからないか読み込めません。\n"
                "配布版（EXE）では通常ここは出ません。\n\n"
                f"詳細: {e}"
            )
            return

        try:
            if hasattr(ai_title_workshop, "open_workshop_window"):
                ai_title_workshop.open_workshop_window(self)
            else:
                messagebox.showerror("工房", "工房に open_workshop_window() がありません。")
        except Exception as e:
            messagebox.showerror("工房", f"起動に失敗しました: {e}")

    def update_status(self):
        self.status_var.set(f"表示: {len(self.filtered)} / 全体: {len(self.rows)}   | 既定: {self.engine_var.get()}   | ジャンル: {self.genre_var.get() if hasattr(self, 'genre_var') else '（無選択）'}   | 検索: {self.search_mode.get()}")

if __name__ == "__main__":
    App().mainloop()
