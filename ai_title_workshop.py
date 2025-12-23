# ai_title_workshop_v27_SAFE.py
# NOTE: 文字列の改行/引用符ミスを避けるため、全ソースを再チェックしてから書き出しています。
# 工房（最小・実用版）
# 目的:
# - workspace.json（本体が出力）を読み込み、除外したい例/残したい例/無視語を確認
# - ルール（正規表現）を作ってON/OFFし、ヒット数を見ながら育てる
# - 他ソフトへコピペできる形で「輸出」する（rules_pack.json を生成）
#
# 入力:
#   workspace.json (default: ./workspace.json)
# 出力:
#   rules_pack.json (default: ./rules_pack.json)
#
# 起動例:
#   python ai_title_workshop_v27.py --workspace workspace.json --rules-pack rules_pack.json

import os
import re
import json
import argparse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

# ---- 材料数の目安（色でガイド） ----
EX_MIN, EX_MAX = 5, 15
KEEP_MIN, KEEP_MAX = 3, 10
COLOR_GRAY = "#666666"
COLOR_GREEN = "#2e8b57"
COLOR_BLUE = "#1e90ff"

def _color_for_count(count: int, min_v: int, max_v: int) -> str:
    if count < min_v:
        return COLOR_GRAY
    if min_v <= count <= max_v:
        return COLOR_GREEN
    return COLOR_BLUE


APP_TITLE = "AI Title Workshop v27 (Factory)"

SCOPE_TMP = "TMP"
SCOPE_GLOBAL = "__global__"
SCOPE_GENRE = "__genre__"
SCOPE_LABELS = {
    SCOPE_TMP: "TMP（試作）",
    SCOPE_GLOBAL: "共通（全ジャンル）",
    SCOPE_GENRE: "ジャンル別",
}

# ---------- Models ----------
@dataclass
class Rule:
    key: str
    name: str
    pattern: str
    why: str
    enabled: bool = True
    flags: int = 0
    source: str = "WORKSHOP"
    error: str = ""
    genres: Optional[List[str]] = None
    scope: str = SCOPE_GLOBAL
    apply_genre: str = ""

# ---------- Helpers ----------
def safe_load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def safe_save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def normalize_preview(s: str, n: int = 80) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[: max(0, n - 3)] + "..."

def compile_rule(r: Rule) -> Optional[re.Pattern]:
    if (not r.enabled) or (not r.pattern):
        return None
    try:
        return re.compile(r.pattern, r.flags)
    except re.error as e:
        r.error = str(e)
        return None

def heuristic_suggestions(examples: List[str], ignore_words: List[str]) -> List[Rule]:
    """
    乱暴に見えるが、最初の「叩き台」には十分。
    - 末尾番号
    - 括弧タグ（[...], (...), 【...】）
    - よくあるノイズ語（ignore_words）
    """
    rules: List[Rule] = []
    # 末尾番号（例: "タイトル 01", "title_12", "title-003"）
    rules.append(Rule(
        key="tail_number",
        name="末尾番号（01/001/12-345 など）",
        pattern=r"(?i)(?:^|[ _\-\u3000])\d{1,4}(?:-\d{1,4})?$",
        why="末尾の巻数/番号っぽい部分を除外するため",
    ))
    # 括弧タグ
    rules.append(Rule(
        key="bracket_tag",
        name="括弧タグ（[...]/(...)/【...】）",
        pattern=r"[\[\(（【].{1,30}?[\]\)）】]",
        why="表紙/差分/修正版などが括弧に入ることが多いため",
    ))
    # ignore_words を OR でまとめた軽量ルール（まずは素朴）
    if ignore_words:
        # エスケープして OR
        parts = [re.escape(w) for w in ignore_words if w.strip()]
        if parts:
            rules.append(Rule(
                key="ignore_words",
                name="無視語（まとめ）",
                pattern=r"(?i)(" + "|".join(parts[:80]) + r")",
                why="無視語に入っている語をまとめて除外するため",
            ))
    # 先頭の "IMG_2023" みたいなカメラ系
    rules.append(Rule(
        key="camera_prefix",
        name="カメラ系プレフィックス（IMG_/DSC_ など）",
        pattern=r"(?i)\b(?:img|dsc|pxl|vid|mv)[ _-]?\d{3,}\b",
        why="撮影機器由来の管理番号を除外するため",
    ))
    return rules

# ---------- App ----------
class WorkshopApp(tk.Toplevel):
    def __init__(self, master, workspace_path: str, rules_pack_path: str):
        super().__init__(master)
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(980, 700)

        try:
            self.transient(master)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.workspace_path = workspace_path
        self.rules_pack_path = rules_pack_path

        self.workspace: Dict = {}
        self.sample_titles: List[str] = []
        self.exclude_examples: List[str] = []
        self.keep_examples: List[str] = []
        self.ignore_words: List[str] = []
        self.genre: str = "未選択"

        self.rules: List[Rule] = []
        self.compiled: List[Optional[re.Pattern]] = []

        self._build_menu()
        self._build_ui()

        self.load_workspace(self.workspace_path)
        self.load_rules_pack(self.rules_pack_path, silent=True)

        # 何も無ければ叩き台を入れる
        if not self.rules:
            self.rules = heuristic_suggestions(self.exclude_examples, self.ignore_words)
            self.recompile_all()
            self.refresh_all()

    # ---------- UI ----------
    def _build_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        m_file = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="ファイル", menu=m_file)
        m_file.add_command(label="workspace.json を開く", command=self.pick_workspace)
        m_file.add_command(label="rules_pack.json を開く", command=self.pick_rules_pack)
        m_file.add_separator()
        m_file.add_command(label="rules_pack.json に保存", command=self.export_rules_pack)
        m_file.add_separator()
        m_file.add_command(label="終了", command=self.destroy)

        m_tools = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="ツール", menu=m_tools)
        m_tools.add_command(label="叩き台ルールを追加", command=self.add_heuristics)
        m_tools.add_command(label="全ルール再計算", command=self.refresh_all)
        m_tools.add_separator()
        m_tools.add_command(label="選択ルールの正規表現をコピー", command=self.copy_selected_pattern)

        m_help = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="ヘルプ", menu=m_help)
        m_help.add_command(label="この工房について", command=self.show_about)

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        self.meta_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.meta_var).pack(anchor="w")

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=8)

        left = ttk.Frame(paned)
        mid = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=2)
        paned.add(mid, weight=2)
        paned.add(right, weight=3)

        # Left: examples
        lf = ttk.LabelFrame(left, text="例（本体から来た材料）")
        lf.pack(fill="both", expand=True)

        self.ex_count_label = ttk.Label(lf, text="ノイズを含むタイトル（0 / 5〜15）", font=("Segoe UI", 10, "bold"))
        self.ex_count_label.pack(anchor="w", padx=8, pady=(8, 0))
        self.ex_list = tk.Listbox(lf, height=8)
        self.ex_list.pack(fill="x", padx=8, pady=(2, 8))

        self.keep_count_label = ttk.Label(lf, text="ノイズを含まないタイトル（0 / 3〜10）", font=("Segoe UI", 10, "bold"))
        self.keep_count_label.pack(anchor="w", padx=8)
        self.keep_list = tk.Listbox(lf, height=6)
        self.keep_list.pack(fill="x", padx=8, pady=(2, 8))

        ttk.Label(lf, text="無視語").pack(anchor="w", padx=8)
        self.ig_list = tk.Listbox(lf, height=6)
        self.ig_list.pack(fill="x", padx=8, pady=(2, 8))

        # Mid: rules list
        mf = ttk.LabelFrame(mid, text="ルール（ON/OFF + ヒット数）")
        mf.pack(fill="both", expand=True)

        scopebar = ttk.Frame(mf)
        scopebar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(scopebar, text="編集スコープ:").pack(side="left")
        self.scope_var = tk.StringVar(value=SCOPE_LABELS[SCOPE_TMP])
        self.scope_combo = ttk.Combobox(scopebar, textvariable=self.scope_var, state="readonly", width=16,
                                       values=[SCOPE_LABELS[SCOPE_TMP], SCOPE_LABELS[SCOPE_GLOBAL], SCOPE_LABELS[SCOPE_GENRE]])
        self.scope_combo.pack(side="left", padx=6)
        self.scope_combo.bind("<<ComboboxSelected>>", lambda e: self.on_scope_changed())
        ttk.Separator(scopebar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(scopebar, text="選択ルールを共通へ昇格", command=self.promote_selected_rule_to_global).pack(side="left")
        ttk.Button(scopebar, text="選択ルールをジャンルへ昇格", command=self.promote_selected_rule_to_genre).pack(side="left", padx=6)
        ttk.Button(scopebar, text="TMPを空にする", command=self.clear_tmp_scope).pack(side="right")

        self.rule_tree = ttk.Treeview(mf, columns=("scope", "on", "hit", "name"), show="headings", height=16)
        self.rule_tree.heading("scope", text="scope")
        self.rule_tree.heading("on", text="ON")
        self.rule_tree.heading("hit", text="hit")
        self.rule_tree.heading("name", text="rule")
        self.rule_tree.column("scope", width=90, anchor="w")
        self.rule_tree.column("on", width=50, anchor="center")
        self.rule_tree.column("hit", width=60, anchor="e")
        self.rule_tree.column("name", width=300, anchor="w")
        self.rule_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.rule_tree.bind("<<TreeviewSelect>>", lambda e: self.show_rule_detail())

        btns = ttk.Frame(mf)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="ON/OFF", command=self.toggle_selected_rule).pack(side="left")
        ttk.Button(btns, text="コピー", command=self.copy_selected_pattern).pack(side="left", padx=6)
        ttk.Button(btns, text="保存（rules_pack.json）", command=self.export_rules_pack).pack(side="right")

        # Right: rule detail + preview hits
        rf = ttk.LabelFrame(right, text="ルール詳細（編集可）")
        rf.pack(fill="both", expand=True)

        frm = ttk.Frame(rf)
        frm.pack(fill="x", padx=8, pady=8)
        ttk.Label(frm, text="名前:").grid(row=0, column=0, sticky="w")
        ttk.Label(frm, text="視点(任意):").grid(row=1, column=0, sticky="w")
        ttk.Label(frm, text="理由:").grid(row=2, column=0, sticky="w")
        ttk.Label(frm, text="flags:").grid(row=3, column=0, sticky="w")

        self.name_var = tk.StringVar(value="")
        self.genres_var = tk.StringVar(value="")
        self.why_var = tk.StringVar(value="")
        self.flags_var = tk.StringVar(value="0")

        ttk.Entry(frm, textvariable=self.name_var, width=44).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Entry(frm, textvariable=self.genres_var, width=44).grid(row=1, column=1, sticky="we", padx=6)
        ttk.Entry(frm, textvariable=self.why_var, width=44).grid(row=2, column=1, sticky="we", padx=6)
        ttk.Entry(frm, textvariable=self.flags_var, width=12).grid(row=3, column=1, sticky="w", padx=6)

        ttk.Label(rf, text="正規表現（pattern）:").pack(anchor="w", padx=8)
        self.pattern_txt = tk.Text(rf, height=6, wrap="none", undo=True, autoseparators=True, maxundo=-1)
        self.pattern_txt.pack(fill="x", padx=8, pady=(2, 8))

        # Undo/Redo（正規表現入力欄）
        self.pattern_txt.bind("<Control-z>", lambda e: (self.pattern_txt.edit_undo(), "break")[1])
        self.pattern_txt.bind("<Control-y>", lambda e: (self.pattern_txt.edit_redo(), "break")[1])
        self.pattern_txt.bind("<Control-Z>", lambda e: (self.pattern_txt.edit_undo(), "break")[1])
        self.pattern_txt.bind("<Control-Y>", lambda e: (self.pattern_txt.edit_redo(), "break")[1])
        # macOS
        self.pattern_txt.bind("<Command-z>", lambda e: (self.pattern_txt.edit_undo(), "break")[1])
        self.pattern_txt.bind("<Command-Shift-Z>", lambda e: (self.pattern_txt.edit_redo(), "break")[1])

        act = ttk.Frame(rf)
        act.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(act, text="反映（再計算）", command=self.apply_rule_edit).pack(side="left")
        ttk.Button(act, text="新規ルール", command=self.add_new_rule).pack(side="left", padx=6)
        ttk.Button(act, text="削除", command=self.delete_selected_rule).pack(side="left", padx=6)

        ttk.Separator(rf).pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(rf, text="プレビュー（最初にヒットした例を表示）").pack(anchor="w", padx=8)
        self.preview = tk.Text(rf, height=18, wrap="word")
        self.preview.pack(fill="both", expand=True, padx=8, pady=(2, 8))


    # ---------- Scopes ----------
    def _scope_key_from_label(self, label: str) -> str:
        for k, v in SCOPE_LABELS.items():
            if v == label:
                return k
        return SCOPE_TMP

    def get_current_scope(self) -> str:
        if hasattr(self, "scope_var"):
            return self._scope_key_from_label(self.scope_var.get())
        return SCOPE_TMP

    def on_scope_changed(self):
        self.refresh_rule_tree()
        self.refresh_ignore_list()
        self.update_meta()

    def update_meta(self):
        scope = self.get_current_scope()
        scope_label = SCOPE_LABELS.get(scope, scope)
        self.meta_var.set(
            f"workspace: {os.path.basename(self.workspace_path)} / ジャンル: {self.genre} / スコープ: {scope_label} / EX:{len(self.exclude_examples)} / KEEP:{len(self.keep_examples)} / sample:{len(self.sample_titles)}"
        )

    def refresh_ignore_list(self):
        self.ig_list.delete(0, "end")
        scope = self.get_current_scope()
        if scope == SCOPE_TMP:
            words = self.ignore_scoped.get(SCOPE_TMP, [])
        elif scope == SCOPE_GENRE:
            gm = self.ignore_scoped.get(SCOPE_GENRE, {})
            words = gm.get(self.genre, []) if isinstance(gm, dict) else []
        else:
            words = self.ignore_scoped.get(SCOPE_GLOBAL, [])

        if not isinstance(words, list):
            words = []
        for s in words[:500]:
            self.ig_list.insert("end", s)

    def _ensure_scoped_structures(self):
        if not hasattr(self, "ignore_scoped") or not isinstance(self.ignore_scoped, dict):
            self.ignore_scoped = {SCOPE_GLOBAL: [], SCOPE_TMP: [], SCOPE_GENRE: {}}

        if not isinstance(self.ignore_scoped.get(SCOPE_GLOBAL), list):
            self.ignore_scoped[SCOPE_GLOBAL] = []
        if not isinstance(self.ignore_scoped.get(SCOPE_TMP), list):
            self.ignore_scoped[SCOPE_TMP] = []
        if not isinstance(self.ignore_scoped.get(SCOPE_GENRE), dict):
            self.ignore_scoped[SCOPE_GENRE] = {}

        for r in self.rules:
            if not hasattr(r, "scope") or not r.scope:
                r.scope = SCOPE_GLOBAL
            if not hasattr(r, "apply_genre"):
                r.apply_genre = ""

    def promote_selected_rule_to_global(self):
        sel = self.rule_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        r = self.rules[i]
        r.scope = SCOPE_GLOBAL
        r.apply_genre = ""
        self.save_workspace()
        self.refresh_rule_tree()

    def promote_selected_rule_to_genre(self):
        sel = self.rule_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        r = self.rules[i]
        r.scope = SCOPE_GENRE
        r.apply_genre = self.genre
        self.save_workspace()
        self.refresh_rule_tree()

    def clear_tmp_scope(self):
        if not messagebox.askyesno("確認", "TMP（試作）を空にしますか？\nTMPの無視語とTMPのルールが削除されます。"):
            return
        self.rules = [r for r in self.rules if getattr(r, "scope", SCOPE_GLOBAL) != SCOPE_TMP]
        self.ignore_scoped[SCOPE_TMP] = []
        self.save_workspace()
        self.refresh_rule_tree()
        self.refresh_ignore_list()

    def save_workspace(self):
        if not getattr(self, "workspace_path", ""):
            return
        data = dict(self.workspace) if isinstance(getattr(self, "workspace", None), dict) else {}
        data["genre"] = self.genre
        data["exclude_examples"] = self.exclude_examples
        data["keep_examples"] = self.keep_examples
        data["sample_titles"] = self.sample_titles
        data["ignore_scoped"] = self.ignore_scoped
        data["ignore_words"] = list(self.ignore_scoped.get(SCOPE_GLOBAL, []))  # legacy
        data["rules"] = [rule_to_dict(r) for r in self.rules]
        safe_save_json(self.workspace_path, data)
        self.workspace = data
    def on_close(self):
        try:
            self.destroy()
        except Exception:
            pass

    # ---------- Workspace ----------
    def pick_workspace(self):
        p = filedialog.askopenfilename(title="workspace.json を選択", filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if p:
            self.load_workspace(p)

    def load_workspace(self, path: str):
        data = safe_load_json(path)
        if not isinstance(data, dict):
            messagebox.showerror("workspace", f"読み込み失敗: {path}")
            return

        self.workspace_path = path
        self.workspace = data

        # workspaceに保存されている「ジャンル」は、ユーザー定義カテゴリの"現在選択"です
        self.genre = str(data.get("genre") or "未選択")

        # scoped ignore (backward compatible)
        self.ignore_scoped = data.get("ignore_scoped")
        if not isinstance(self.ignore_scoped, dict):
            self.ignore_scoped = {SCOPE_GLOBAL: list(data.get("ignore_words") or []), SCOPE_TMP: [], SCOPE_GENRE: {}}

        self.exclude_examples = list(data.get("exclude_examples") or [])
        self.keep_examples = list(data.get("keep_examples") or [])
        self.sample_titles = list(data.get("sample_titles") or [])

        # rules in workspace（あれば）
        rules_data = data.get("rules") or []
        rules: List[Rule] = []
        if isinstance(rules_data, list):
            for it in rules_data:
                if not isinstance(it, dict):
                    continue
                genres = it.get("genres")
                if isinstance(genres, list):
                    genres = [str(x) for x in genres if str(x).strip()]
                else:
                    genres = None
                r = Rule(
                    key=str(it.get("key") or f"R_{len(rules)}"),
                    name=str(it.get("name") or "rule"),
                    pattern=str(it.get("pattern") or ""),
                    why=str(it.get("why") or ""),
                    enabled=bool(it.get("enabled", True)),
                    flags=int(it.get("flags", 0) or 0),
                    source=str(it.get("source") or "WORKSHOP"),
                    error=str(it.get("error") or ""),
                    genres=genres,
                )
                r.scope = str(it.get("scope") or SCOPE_GLOBAL)
                r.apply_genre = str(it.get("apply_genre") or "")
                rules.append(r)

        self.rules = rules

        self._ensure_scoped_structures()
        self.update_meta()

        self.refresh_workspace_lists()
        self.refresh_all()
    def refresh_workspace_lists(self):
        self.ex_list.delete(0, "end")
        for s in self.exclude_examples[:500]:
            self.ex_list.insert("end", s)

        self.keep_list.delete(0, "end")
        for s in self.keep_examples[:500]:
            self.keep_list.insert("end", s)

        self.refresh_ignore_list()

        self.update_material_labels()

    def update_material_labels(self):
        ex_n = len(self.exclude_examples)
        keep_n = len(self.keep_examples)

        if hasattr(self, "ex_count_label"):
            self.ex_count_label.configure(
                text=f"ノイズを含むタイトル（{ex_n} / {EX_MIN}〜{EX_MAX}）",
                foreground=_color_for_count(ex_n, EX_MIN, EX_MAX),
            )
        if hasattr(self, "keep_count_label"):
            self.keep_count_label.configure(
                text=f"ノイズを含まないタイトル（{keep_n} / {KEEP_MIN}〜{KEEP_MAX}）",
                foreground=_color_for_count(keep_n, KEEP_MIN, KEEP_MAX),
            )

    # ---------- Rules pack ----------
    def pick_rules_pack(self):
        p = filedialog.askopenfilename(title="rules_pack.json を選択", filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if p:
            self.load_rules_pack(p)

    def load_rules_pack(self, path: str, silent: bool = False):
        data = safe_load_json(path)
        if data is None:
            if not silent:
                messagebox.showinfo("rules_pack", f"見つかりません: {path}\n新規作成で進めます。")
            return

        rules_data = data
        if isinstance(data, dict):
            rules_data = data.get("rules") or []

        rules: List[Rule] = []
        if isinstance(rules_data, list):
            for it in rules_data:
                if not isinstance(it, dict):
                    continue
                genres = it.get("genres")
                if isinstance(genres, list):
                    genres = [str(x) for x in genres if str(x).strip()]
                else:
                    genres = None
                rules.append(Rule(
                    key=str(it.get("key") or f"R_{len(rules)}"),
                    name=str(it.get("name") or "rule"),
                    pattern=str(it.get("pattern") or ""),
                    why=str(it.get("why") or ""),
                    enabled=bool(it.get("enabled", True)),
                    flags=int(it.get("flags", 0) or 0),
                    source=str(it.get("source") or "WORKSHOP"),
                    error=str(it.get("error") or ""),
                    genres=genres,
                ))

        self.rules_pack_path = path
        self.rules = rules
        self.recompile_all()
        self.refresh_all()

    def export_rules_pack(self):
        # default to rules_pack_path
        path = self.rules_pack_path or "rules_pack.json"
        # allow save-as
        path = filedialog.asksaveasfilename(
            title="rules_pack.json に保存",
            defaultextension=".json",
            initialfile=os.path.basename(path),
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        ) or ""
        if not path:
            return

        data = {
            "meta": {
                "name": "workshop_v27",
                "generated_at": time_string(),
            },
            "rules": [rule_to_dict(r) for r in self.rules],
        }
        try:
            safe_save_json(path, data)
            self.rules_pack_path = path
            messagebox.showinfo("保存", f"保存しました:\n{path}")
        except Exception as e:
            messagebox.showerror("保存", f"保存失敗: {e}")

    # ---------- Rule operations ----------
    def recompile_all(self):
        self.compiled = []
        for r in self.rules:
            r.error = ""
            self.compiled.append(compile_rule(r))

    def add_heuristics(self):
        base = heuristic_suggestions(self.exclude_examples, self.ignore_words)
        # avoid duplicate keys
        existing = {r.key for r in self.rules}
        for r in base:
            if r.key not in existing:
                self.rules.append(r)
        self.recompile_all()
        self.refresh_all()

    def add_new_rule(self):
        n = len(self.rules)
        self.rules.append(Rule(
            key=f"custom_{n}",
            name=f"新規ルール{n}",
            pattern=r"",
            why="",
            enabled=True
        ))
        self.recompile_all()
        # 新規ルールは現在のスコープに置く（既定: TMP）
        sc = self.get_current_scope()
        r = self.rules[-1]
        r.scope = sc
        r.apply_genre = self.genre if sc == SCOPE_GENRE else ""
        self.save_workspace()
        self.refresh_all()
        # select last
        self.select_rule_index(len(self.rules)-1)

    def delete_selected_rule(self):
        idx = self.get_selected_rule_index()
        if idx is None:
            return
        if messagebox.askyesno("削除", "選択ルールを削除しますか？"):
            self.rules.pop(idx)
            self.recompile_all()
            self.refresh_all()

    def toggle_selected_rule(self):
        idx = self.get_selected_rule_index()
        if idx is None:
            return
        self.rules[idx].enabled = not self.rules[idx].enabled
        self.recompile_all()
        self.refresh_all()
        self.select_rule_index(idx)

    def apply_rule_edit(self):
        idx = self.get_selected_rule_index()
        if idx is None:
            return
        r = self.rules[idx]
        r.name = self.name_var.get().strip() or r.name
        r.why = self.why_var.get().strip()
        # genres: comma separated, empty => None
        gs = [x.strip() for x in (self.genres_var.get() or "").split(",") if x.strip()]
        r.genres = gs if gs else None
        try:
            r.flags = int(self.flags_var.get().strip() or "0")
        except ValueError:
            r.flags = 0
            self.flags_var.set("0")
        r.pattern = self.pattern_txt.get("1.0", "end").strip()
        self.recompile_all()
        self.refresh_all()
        self.select_rule_index(idx)

    def copy_selected_pattern(self):
        idx = self.get_selected_rule_index()
        if idx is None:
            return
        pat = self.rules[idx].pattern or ""
        if not pat.strip():
            messagebox.showinfo("コピー", "pattern が空です。")
            return
        self.clipboard_clear()
        self.clipboard_append(pat)
        messagebox.showinfo("コピー", "正規表現をクリップボードにコピーしました。")

    # ---------- Selection ----------
    def get_selected_rule_index(self) -> Optional[int]:
        sel = self.rule_tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def select_rule_index(self, idx: int):
        if idx < 0 or idx >= len(self.rules):
            return
        self.rule_tree.selection_set(str(idx))
        self.rule_tree.see(str(idx))
        self.show_rule_detail()

    # ---------- Refresh / Preview ----------
    def refresh_all(self):
        self.update_rule_hits()
        self.refresh_rule_tree()
        self.show_rule_detail()
        self.refresh_preview()

    def update_rule_hits(self):
        # first-hit counting like main
        for r in self.rules:
            r._hit = 0  # type: ignore

        titles = self.sample_titles or []
        # cap to keep UI snappy
        titles = titles[:3000]

        compiled = self.compiled
        for t in titles:
            for idx, r in enumerate(self.rules):
                cre = compiled[idx]
                if (not r.enabled) or cre is None:
                    continue
                if cre.search(t):
                    r._hit += 1  # type: ignore
                    break

    def refresh_rule_tree(self):
        for it in self.rule_tree.get_children():
            self.rule_tree.delete(it)

        scope = self.get_current_scope()
        g = self.genre

        def visible(r: Rule) -> bool:
            rs = getattr(r, "scope", SCOPE_GLOBAL) or SCOPE_GLOBAL
            if scope == SCOPE_TMP:
                return rs == SCOPE_TMP
            if scope == SCOPE_GENRE:
                return rs == SCOPE_GENRE and (getattr(r, "apply_genre", "") or "") == g
            return rs == SCOPE_GLOBAL

        order = [i for i in range(len(self.rules)) if visible(self.rules[i])]
        order.sort(key=lambda i: (-(getattr(self.rules[i], "_hit", 0)), self.rules[i].name.lower()))

        for i in order:
            r = self.rules[i]
            on = "ON" if r.enabled else "OFF"
            hit = getattr(r, "_hit", 0)
            name = r.name
            if r.genres:
                name += f" (視点:{'/'.join(r.genres)})"

            rs = getattr(r, "scope", SCOPE_GLOBAL) or SCOPE_GLOBAL
            if rs == SCOPE_TMP:
                scope_cell = "TMP"
            elif rs == SCOPE_GENRE:
                scope_cell = f"genre:{getattr(r, 'apply_genre', '') or ''}"
            else:
                scope_cell = "共通"

            self.rule_tree.insert("", "end", iid=str(i), values=(scope_cell, on, hit, name))

    def show_rule_detail(self):
        idx = self.get_selected_rule_index()
        if idx is None:
            self.name_var.set("")
            self.genres_var.set("")
            self.why_var.set("")
            self.flags_var.set("0")
            self.pattern_txt.delete("1.0", "end")
            return
        r = self.rules[idx]
        self.name_var.set(r.name)
        self.genres_var.set(",".join(r.genres) if r.genres else "")
        self.why_var.set(r.why)
        self.flags_var.set(str(r.flags))
        self.pattern_txt.delete("1.0", "end")
        self.pattern_txt.insert("1.0", r.pattern)

    def refresh_preview(self):
        self.preview.delete("1.0", "end")
        titles = self.sample_titles[:400] if self.sample_titles else []
        if not titles:
            self.preview.insert("1.0", "sample_titles がありません（本体で読み込み→workspace保存してください）")
            return

        lines = []
        compiled = self.compiled
        for t in titles[:200]:
            hit = ""
            for idx, r in enumerate(self.rules):
                cre = compiled[idx]
                if (not r.enabled) or cre is None:
                    continue
                if cre.search(t):
                    hit = f" -> {r.name}"
                    break
            lines.append(t + hit)

        # errors
        errs = [r for r in self.rules if r.error]
        if errs:
            lines.append("\n[ERROR]")
            for r in errs[:20]:
                lines.append(f"- {r.name}: {r.error}")

        self.preview.insert("1.0", "\n".join(lines))

    # ---------- About ----------
    def show_about(self):
        messagebox.showinfo(
            "この工房について",
            "AI Title Workshop v27\n\n"
            "本体が出した workspace.json を材料に\n"
            "正規表現ルールを育てて rules_pack.json に輸出します。\n\n"
            "・ON/OFF\n"
            "・ヒット数\n"
            "・pattern をコピペ\n"
            "が中心です。"
        )

# ---------- Serialization ----------
def rule_to_dict(r: Rule) -> Dict:
    d = {
        "key": r.key,
        "name": r.name,
        "pattern": r.pattern,
        "why": r.why,
        "enabled": r.enabled,
        "flags": r.flags,
        "source": r.source,
    }
    if r.genres:
        d["genres"] = r.genres
    if getattr(r, "scope", None):
        d["scope"] = r.scope
    if getattr(r, "apply_genre", None):
        d["apply_genre"] = r.apply_genre
    if r.error:
        d["error"] = r.error
    return d

def time_string() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")

# ---------- Main ----------
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="workspace.json")
    ap.add_argument("--rules-pack", default="rules_pack.json")
    return ap.parse_args()

def ensure_workspace_file(path: str):
    """workspace.json が無い場合に安全な初期値で作成（共有・復旧用）"""
    if not path:
        return
    if os.path.exists(path):
        return
    data = {
        "genre": "（無選択）",
        "exclude_examples": [],
        "keep_examples": [],
        "sample_titles": [],
        "ignore_scoped": {"__global__": [], "TMP": [], "__genre__": {}},
        "rules": [],
    }
    try:
        safe_save_json(path, data)
    except Exception:
        # 最後の手段：素のjson
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def open_workshop_window(parent=None, workspace_path: str = "workspace.json", rules_pack_path: str = "rules_pack.json"):
    """本体から呼び出す入口。parent があれば Toplevel、なければ単体起動。"""
    ensure_workspace_file(workspace_path)
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        WorkshopApp(root, workspace_path, rules_pack_path)
        root.mainloop()
    else:
        ensure_workspace_file(workspace_path)
        return WorkshopApp(parent, workspace_path, rules_pack_path)

def main():
    args = parse_args()
    open_workshop_window(None, args.workspace, args.rules_pack)

if __name__ == "__main__":
    main()
