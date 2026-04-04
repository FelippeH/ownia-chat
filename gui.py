# executar com:
# python gui.py

import json
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw
import requests

# ════════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES
# ════════════════════════════════════════════════════════════════
import sys, os

# Diretório base: onde o .exe está (ou onde o script roda)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

os.chdir(BASE_DIR)

MEMORY_FILE = str(BASE_DIR / "memory.json")
SYSTEM_PROMPT_FILE = str(BASE_DIR / "system_prompt.txt")
CONFIG_FILE = str(BASE_DIR / "config.json")

DEFAULT_CONFIG = {
    "bot_name": "",
    "user_nickname": "",
    "avatar_path": "",
}

def load_config():
    if not Path(CONFIG_FILE).exists():
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # garantir que todas as chaves existam
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

# Paleta de cores (tema escuro moderno)
BG_PRIMARY = "#1a1a2e"       # fundo principal
BG_SECONDARY = "#16213e"     # fundo do chat
BG_INPUT = "#0f3460"         # fundo da entrada
ACCENT = "#e94560"           # destaque / botão
TEXT_PRIMARY = "#eaeaea"      # texto claro
TEXT_SECONDARY = "#a8a8b3"    # texto secundário
USER_BUBBLE = "#0f3460"      # bolha do usuário
BOT_BUBBLE = "#1b2838"       # bolha do agente
SCROLLBAR_BG = "#16213e"
SCROLLBAR_FG = "#0f3460"

# ════════════════════════════════════════════════════════════════
#  LÓGICA DO AGENTE (reutilizada do agent.py)
# ════════════════════════════════════════════════════════════════

def load_memory():
    if not Path(MEMORY_FILE).exists():
        return {
            "user_preferences": [],
            "important_facts": [],
            "conversation_history": []
        }
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)

def load_system_prompt():
    with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()

def extract_memory(user_input, memory):
    keywords = ["meu nome", "eu gosto", "eu prefiro", "trabalho", "estudo"]
    for word in keywords:
        if word in user_input.lower():
            memory["important_facts"].append(user_input)

def build_context(system_prompt, memory, user_input, bot_name="", user_nickname=""):
    # Reformatar histórico com rótulos claros
    formatted_history = []
    for msg in memory["conversation_history"][-8:]:
        if msg.startswith("Usuário: "):
            formatted_history.append(f"[Usuário]: {msg[len('Usuário: '):]}") 
        elif msg.startswith("Agente: "):
            formatted_history.append(f"[{bot_name}]: {msg[len('Agente: '):]}") 
        else:
            formatted_history.append(msg)
    history = "\n".join(formatted_history)
    facts = "\n".join(memory["important_facts"])
    system_msg = system_prompt.replace("{bot_name}", bot_name).replace("{user_nickname}", user_nickname)

    user_msg = ""
    if facts:
        user_msg += f"Coisas que você sabe sobre o usuário:\n{facts}\n\n"
    if history:
        user_msg += f"Conversa recente:\n{history}\n\n"
    user_msg += f"[Usuário]: {user_input}\n\nResponda como {bot_name}."

    return system_msg, user_msg

# Evento global para cancelar geração em andamento
_cancel_event = threading.Event()

def ask_llm(prompt, temperature=0.6, system_msg=None):
    """Envia prompt para o Ollama via streaming e retorna a resposta completa."""
    _cancel_event.clear()
    payload = {
        "model": "mistral:latest",  # nome do modelo registrado no Ollama
        "stream": True,
        "keep_alive": -1,
        "options": {
            "temperature": temperature,
            "do_sample": True,
            "top_p": 0.8,
            "top_k": 30,
            "frequency_penalty": 0.7,
            "repeat_penalty": 1.05,
            "num_predict": 256,
            "num_ctx": 1024,
        }
    }
    if system_msg:
        payload["messages"] = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]
        url = "http://localhost:11434/api/chat"
    else:
        payload["prompt"] = prompt
        url = "http://localhost:11434/api/generate"

    result_chunks = []
    
    # timeout longo para evitar que o requests cancele a conexão durante respostas longas, mas ainda permitir cancelamento manual via _cancel_event
    with requests.post(url, json=payload, timeout=(10, 300), stream=True) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if _cancel_event.is_set():
                resp.close()
                return "[geração cancelada]"
            if line:
                data = json.loads(line)
                if system_msg:
                    chunk = data.get("message", {}).get("content", "")
                else:
                    chunk = data.get("response", "")
                result_chunks.append(chunk)
    return "".join(result_chunks).strip()


def _filter_think_tags(text):
    """Remove blocos <tool_call>...<tool_call> do DeepSeek R1."""
    if "<tool_call>" in text:
        text = text.split("<tool_call>", 1)[-1].strip()
    elif "<think>" in text:
        text = ""
    return text


# ════════════════════════════════════════════════════════════════
#  WIDGETS AUXILIARES
# ════════════════════════════════════════════════════════════════

def make_circle_avatar(path, size=70):
    """Carrega uma imagem, recorta em quadrado centralizado e retorna como círculo."""
    img = Image.open(path).convert("RGBA")
    # Crop centralizado 1:1
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)
    # Máscara circular
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return ImageTk.PhotoImage(img)

# Função genérica para criar ícones vetoriais desenhados com Pillow
def _make_icon(draw_func, size=20, fg="#eaeaea", bg=None):
    """Cria um ícone vetorial desenhado com Pillow (renderiza em 4x e reduz para antialiasing)."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    draw_func(d, s, fg)
    img = img.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(img)

def _icon_refresh(d, s, fg):
    """Seta circular (regenerar)."""
    w = max(s // 8, 2)
    margin = s // 6
    d.arc([margin, margin, s - margin, s - margin], start=30, end=330, fill=fg, width=w)
    # Ponta da seta
    import math
    angle = math.radians(30)
    cx, cy = s // 2, s // 2
    r = (s - 2 * margin) // 2
    ax = cx + r * math.cos(angle)
    ay = cy - r * math.sin(angle)
    arrow_size = s // 5
    d.polygon([
        (ax, ay),
        (ax - arrow_size, ay - arrow_size // 3),
        (ax - arrow_size // 4, ay + arrow_size),
    ], fill=fg)

def _icon_pencil(d, s, fg):
    """Lápis (editar)."""
    w = max(s // 8, 2)
    m = s // 5
    # Corpo do lápis
    d.line([(m, s - m), (s - m, m)], fill=fg, width=w)
    d.line([(m, s - m), (m + s // 8, s - m - s // 8)], fill=fg, width=w)
    # Ponta
    tip = s // 7
    d.polygon([
        (m - tip // 2, s - m + tip // 2),
        (m, s - m),
        (m + tip // 2, s - m + tip // 2 - tip),
    ], fill=fg)


def _icon_trash(d, s, fg):
    """Lixeira (excluir)."""
    w = max(s // 10, 2)
    mx = s // 5  # margem horizontal
    top = s // 4
    # Tampa
    d.rectangle([mx, top, s - mx, top + w], fill=fg)
    # Alça
    handle_w = s // 4
    hx1 = s // 2 - handle_w
    hx2 = s // 2 + handle_w
    d.arc([hx1, top - s // 6, hx2, top + s // 8], start=0, end=180, fill=fg, width=w)
    # Corpo
    body_top = top + w + w // 2
    body_bot = s - mx
    bx1 = mx + w
    bx2 = s - mx - w
    d.rectangle([bx1, body_top, bx2, body_bot], outline=fg, width=w)
    # Linhas internas
    third = (bx2 - bx1) // 3
    for i in range(1, 3):
        x = bx1 + third * i
        d.line([(x, body_top + w), (x, body_bot - w)], fill=fg, width=max(w // 2, 1))


def _icon_arrow_right(d, s, fg):
    """Seta para direita (continuar)."""
    w = max(s // 8, 2)
    my = s // 2
    mx = s // 5
    # Linha horizontal
    d.line([(mx, my), (s - mx, my)], fill=fg, width=w)
    # Ponta da seta
    arrow = s // 4
    d.line([(s - mx - arrow, my - arrow), (s - mx, my)], fill=fg, width=w)
    d.line([(s - mx - arrow, my + arrow), (s - mx, my)], fill=fg, width=w)


def _icon_online(d, s, fg):
    """Círculo verde (online)."""
    m = s // 5
    d.ellipse([m, m, s - m, s - m], fill="#4ade80", outline="#22c55e", width=max(s // 12, 1))


def _icon_gear(d, s, fg):
    """Engrenagem (configurações)."""
    import math
    cx, cy = s // 2, s // 2
    r_outer = s // 2 - s // 10
    r_inner = s // 3
    r_hole = s // 6
    teeth = 8
    w = max(s // 10, 2)
    # Dentes
    for i in range(teeth):
        a = math.radians(i * 360 / teeth)
        a2 = math.radians(i * 360 / teeth + 360 / teeth / 2)
        x1 = cx + r_outer * math.cos(a)
        y1 = cy + r_outer * math.sin(a)
        x2 = cx + r_outer * math.cos(a2)
        y2 = cy + r_outer * math.sin(a2)
        d.line([(cx + r_inner * math.cos(a), cy + r_inner * math.sin(a)), (x1, y1)], fill=fg, width=w)
    # Círculo externo
    d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], outline=fg, width=w)
    # Furo central
    d.ellipse([cx - r_hole, cy - r_hole, cx + r_hole, cy + r_hole], outline=fg, width=max(w // 2, 1))


def _icon_send(d, s, fg):
    """Aviãozinho de papel (enviar)."""
    m = s // 7
    # Triângulo principal (avião apontando para direita)
    d.polygon([
        (s - m, s // 2),          # ponta direita
        (m, m + s // 10),          # canto superior esquerdo
        (m + s // 3, s // 2),      # dobra central
        (m, s - m - s // 10),      # canto inferior esquerdo
    ], fill=fg)
    # Linha da dobra
    w = max(s // 14, 1)
    d.line([(m + s // 3, s // 2), (s - m, s // 2)], fill="#1a1a2e", width=w)


def _icon_document(d, s, fg):
    """Documento / prompt."""
    w = max(s // 10, 2)
    mx = s // 4
    my = s // 6
    # Corpo do documento
    d.rectangle([mx, my, s - mx, s - my], outline=fg, width=w)
    # Linhas de texto
    lx1 = mx + s // 6
    lx2 = s - mx - s // 6
    gap = (s - 2 * my) // 5
    for i in range(1, 4):
        ly = my + gap * i
        d.line([(lx1, ly), (lx2, ly)], fill=fg, width=max(w // 2, 1))


class RoundedFrame(tk.Canvas):

    def __init__(self, parent, bg_color, text, text_color, max_width, fonts, **kw):
        super().__init__(parent, highlightthickness=0, bg=BG_SECONDARY, **kw)
        self._bg_color = bg_color
        self._draw_bubble(text, text_color, max_width, fonts)

    def _draw_bubble(self, text, text_color, max_width, fonts):
        # Texto temporário para medir largura
        tmp = self.create_text(
            0, 0, text=text, font=fonts, width=max_width - 40, anchor="nw"
        )
        bbox = self.bbox(tmp)
        self.delete(tmp)

        w = bbox[2] - bbox[0] + 28
        h = bbox[3] - bbox[1] + 20
        r = 16  # raio da borda

        self.config(width=w, height=h)

        # Retângulo arredondado
        self._round_rect(4, 4, w - 4, h - 4, r, fill=self._bg_color, outline="")

        # Texto
        self.create_text(14, 10, text=text, font=fonts, fill=text_color,
                         width=max_width - 40, anchor="nw")

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kw)


# ════════════════════════════════════════════════════════════════
#  JANELA PRINCIPAL
# ════════════════════════════════════════════════════════════════

class ChatApp(tk.Tk):
    def __init__(self):
        super().__init__()

        bot_name = load_config().get("bot_name", "Atlas")
        self.title(f"{bot_name}")

        # Centralizar janela na tela
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w, win_h = 720, 1000
        x = (screen_w - win_w) // 2
        y = 0
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")

        self.minsize(500, 700)
        self.configure(bg=BG_PRIMARY)
        self.resizable(True, True)

        # Ícone (ignora se não existir)
        try:
            self.iconbitmap("icon.ico")
        except Exception:
            pass

        # Fontes
        self.font_title = tkfont.Font(family="Segoe UI", size=20, weight="bold")
        self.font_msg = tkfont.Font(family="Segoe UI", size=11)
        self.font_small = tkfont.Font(family="Segoe UI", size=9)
        self.font_input = tkfont.Font(family="Segoe UI", size=12)

        # Config, memória e prompt
        self.app_config = load_config()
        self.memory = load_memory()
        self.system_prompt = load_system_prompt()

        # Avatar
        self._avatar_img = None
        self._load_avatar()

        # Rastrear última interação para regenerar/editar
        self._last_user_input = None
        self._last_user_row = None
        self._last_bot_row = None
        self._last_bot_text = None
        self._regen_btn_row = None
        self._generating = False  # trava contra duplo-clique

        # Fila thread-safe para comunicação com a UI
        self._ui_queue = queue.Queue()

        # Gerar ícones vetoriais HD
        self._icon_refresh = _make_icon(_icon_refresh, 18, TEXT_SECONDARY)
        self._icon_pencil = _make_icon(_icon_pencil, 18, TEXT_SECONDARY)
        self._icon_trash = _make_icon(_icon_trash, 18, TEXT_SECONDARY)
        self._icon_arrow = _make_icon(_icon_arrow_right, 18, TEXT_SECONDARY)
        self._icon_online = _make_icon(_icon_online, 16)
        self._icon_gear = _make_icon(_icon_gear, 16, TEXT_PRIMARY)
        self._icon_trash_header = _make_icon(_icon_trash, 16, TEXT_PRIMARY)
        self._icon_send = _make_icon(_icon_send, 20, "white")
        self._icon_document = _make_icon(_icon_document, 16, TEXT_PRIMARY)

        self._build_ui()
        self._load_history()
        self.after(100, self._drain_ui_queue)

        # Fechar app salva memória
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── AVATAR ────────────────────────────────────────────────
    def _load_avatar(self):
        path = self.app_config.get("avatar_path", "")
        if path and Path(path).exists():
            try:
                self._avatar_img = make_circle_avatar(path, 200)
                self._avatar_mini = make_circle_avatar(path, 80)
            except Exception:
                self._avatar_img = None
                self._avatar_mini = None
        else:
            self._avatar_img = None
            self._avatar_mini = None

    # ── UI ────────────────────────────────────────────────────
    def _build_ui(self):
        # ── HEADER ──
        header = tk.Frame(self, bg=BG_PRIMARY, pady=24)
        header.pack(fill="x")

        # Avatar no header (clicável para trocar)
        self._header_avatar_frame = tk.Frame(header, bg=BG_PRIMARY)
        self._header_avatar_frame.pack(side="left", padx=(16, 16))
        self._draw_header_avatar()

        # Nome do bot (clicável para editar)
        self._name_label = tk.Label(
            header, text=f"{self.app_config['bot_name']}", font=self.font_title,
            bg=BG_PRIMARY, fg=ACCENT, cursor="hand2"
        )
        self._name_label.pack(side="left")
        self._name_label.bind("<Button-1>", lambda e: self._open_settings())

        online_lbl = tk.Label(header, image=self._icon_online, bg=BG_PRIMARY)
        online_lbl.pack(side="left", padx=(6, 10))

        # Frame para botões empilhados verticalmente
        btn_column = tk.Frame(header, bg=BG_PRIMARY)
        btn_column.pack(side="right", padx=(0, 10))

        # Botão configurações
        settings_btn = tk.Button(
            btn_column, image=self._icon_gear, text="Configurar",
            compound="left", font=("Segoe UI", 11, "bold"),
            bg=BG_INPUT, fg=TEXT_PRIMARY, activebackground=ACCENT,
            activeforeground="white", bd=0, padx=12, pady=4,
            cursor="hand2", command=self._open_settings
        )
        settings_btn.pack(fill="x", pady=(0, 12))

        # Botão limpar
        clear_btn = tk.Button(
            btn_column, image=self._icon_trash_header, text="Limpar",
            compound="left", font=("Segoe UI", 11, "bold"),
            bg=BG_INPUT, fg=TEXT_PRIMARY, activebackground=ACCENT,
            activeforeground="white", bd=0, padx=12, pady=4,
            cursor="hand2", command=self._clear_history
        )
        clear_btn.pack(fill="x", pady=(0, 12))

        # Botão prompt
        prompt_btn = tk.Button(
            btn_column, image=self._icon_document, text="Prompt",
            compound="left", font=("Segoe UI", 11, "bold"),
            bg=BG_INPUT, fg=TEXT_PRIMARY, activebackground=ACCENT,
            activeforeground="white", bd=0, padx=12, pady=4,
            cursor="hand2", command=self._open_prompt_editor
        )
        prompt_btn.pack(fill="x")

        # Linha separadora
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

        # ── ÁREA DO CHAT (Canvas + Scrollbar) ──
        chat_container = tk.Frame(self, bg=BG_SECONDARY)
        chat_container.pack(fill="both", expand=True)

        self.chat_canvas = tk.Canvas(
            chat_container, bg=BG_SECONDARY, highlightthickness=0
        )
        self.scrollbar = tk.Scrollbar(
            chat_container, orient="vertical", command=self.chat_canvas.yview,
            bg=SCROLLBAR_BG, troughcolor=SCROLLBAR_BG,
            activebackground=SCROLLBAR_FG
        )
        self.chat_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.chat_canvas.pack(side="left", fill="both", expand=True)

        # Frame interno onde as bolhas são adicionadas
        self.chat_frame = tk.Frame(self.chat_canvas, bg=BG_SECONDARY)
        self.chat_window_id = self.chat_canvas.create_window(
            (0, 0), window=self.chat_frame, anchor="nw"
        )

        self.chat_frame.bind("<Configure>", self._on_frame_configure)
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)

        # Scroll com roda do mouse
        self.chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # ── ÁREA DE INPUT ──
        input_bar = tk.Frame(self, bg=BG_PRIMARY, pady=10)
        input_bar.pack(fill="x", side="bottom")
        
        # Entry (wrapper para padding horizontal interno)
        entry_wrapper = tk.Frame(input_bar, bg=BG_INPUT)
        entry_wrapper.pack(side="left", fill="x", expand=True, padx=(20, 10), ipady=11)

        self.entry = tk.Entry(
            entry_wrapper, font=self.font_input, bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat", bd=0
        )
        self.entry.pack(fill="both", expand=True, padx=(12, 4))
        self.entry.bind("<Return>", lambda e: self._send_message())
        self.entry.focus_set()

        # Botão enviar
        self.send_btn = tk.Button(
            input_bar, text="Enviar",
            compound="left", font=("Segoe UI", 13, "bold"),
            bg=ACCENT, fg="white", activebackground="#c83650",
            activeforeground="white", bd=0, padx=18, pady=6,
            cursor="hand2", command=self._send_message
        )
        self.send_btn.pack(side="right", padx=(0, 20))

        # Botão cancelar (inicialmente oculto)
        self.cancel_btn = tk.Button(
            input_bar, text="Parar",
            font=("Segoe UI", 13, "bold"),
            bg="#c83650", fg="white", activebackground=ACCENT,
            activeforeground="white", bd=0, padx=18, pady=6,
            cursor="hand2", command=self._cancel_generation
        )
        # Não empacotar agora — será mostrado durante a geração

        # Label de status
        self.status_label = tk.Label(
            self, text="", font=self.font_small,
            bg=BG_PRIMARY, fg=TEXT_SECONDARY
        )
        self.status_label.pack(side="bottom", pady=(0, 2))

    # ── MÉTODOS DE SCROLL ────────────────────────────────────
    def _on_frame_configure(self, event=None):
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.chat_canvas.itemconfig(self.chat_window_id, width=event.width)

    def _on_mousewheel(self, event):
        self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _scroll_to_bottom(self):
        self.chat_canvas.yview_moveto(1.0)

    def _drain_ui_queue(self):
        """Drena mensagens postadas pelas threads de background — seguro para o tkinter."""
        try:
            while True:
                response = self._ui_queue.get_nowait()
                self._on_response_ready(response)
        except queue.Empty:
            pass
        self.after(100, self._drain_ui_queue)

    # ── AVATAR NO HEADER ─────────────────────────────────────
    def _draw_header_avatar(self):
        for w in self._header_avatar_frame.winfo_children():
            w.destroy()
        if self._avatar_img:
            lbl = tk.Label(
                self._header_avatar_frame, image=self._avatar_img,
                bg=BG_PRIMARY, cursor="hand2"
            )
            lbl.pack()
            lbl.bind("<Button-1>", lambda e: self._open_settings())
        else:
            # Placeholder circular com inicial
            c = tk.Canvas(
                self._header_avatar_frame, width=80, height=80,
                bg=BG_PRIMARY, highlightthickness=0
            )
            c.pack()
            c.create_oval(1, 1, 80, 80, fill=ACCENT, outline="")
            initial = self.app_config["bot_name"][0].upper() if self.app_config["bot_name"] else "?"
            c.create_text(40, 40, text=initial, fill="white", font=("Segoe UI", 28, "bold"))
            c.bind("<Button-1>", lambda e: self._open_settings())
            c.config(cursor="hand2")

    # ── BOLHAS DE MENSAGEM ───────────────────────────────────
    def _add_bubble(self, sender, text, show_regen=False):
        """Adiciona uma bolha de mensagem ao chat."""
        is_user = sender == "user"

        row = tk.Frame(self.chat_frame, bg=BG_SECONDARY)
        row.pack(fill="x", padx=16, pady=4)

        max_w = 480

        bot_name = self.app_config.get("bot_name", "Atlas")
        name = "Você" if is_user else bot_name
        anchor_side = "e" if is_user else "w"

        # Container horizontal: [mini avatar] + [nome + bolha]
        msg_container = tk.Frame(row, bg=BG_SECONDARY)
        msg_container.pack(anchor=anchor_side)

        # Mini avatar à esquerda (só para o bot)
        if not is_user:
            av_frame = tk.Frame(msg_container, bg=BG_SECONDARY)
            av_frame.pack(side="left", anchor="n", padx=(0, 6), pady=(2, 0))

            if self._avatar_mini:
                av_lbl = tk.Label(av_frame, image=self._avatar_mini, bg=BG_SECONDARY)
                av_lbl.pack()
            else:
                # Placeholder mini circular
                c = tk.Canvas(av_frame, width=28, height=28,
                              bg=BG_SECONDARY, highlightthickness=0)
                c.pack()
                c.create_oval(1, 1, 27, 27, fill=ACCENT, outline="")
                initial = bot_name[0].upper() if bot_name else "?"
                c.create_text(14, 14, text=initial, fill="white",
                              font=("Segoe UI", 10, "bold"))

        # Coluna com nome + bolha
        content_col = tk.Frame(msg_container, bg=BG_SECONDARY)
        content_col.pack(side="left" if not is_user else "right")

        name_lbl = tk.Label(
            content_col, text=name, font=self.font_small,
            bg=BG_SECONDARY, fg=TEXT_SECONDARY
        )
        name_lbl.pack(anchor="w" if not is_user else "e", padx=2)

        bubble = RoundedFrame(
            content_col,
            bg_color=USER_BUBBLE if is_user else BOT_BUBBLE,
            text=text,
            text_color=TEXT_PRIMARY,
            max_width=max_w,
            fonts=self.font_msg,
        )
        bubble.pack(anchor="w" if not is_user else "e")

        # Rastrear para regeneração/edição
        if is_user:
            self._last_user_input = text
            self._last_user_row = row
            # Remover botões anteriores
            self._remove_regen_btn()
            # Mostrar botão de excluir na mensagem do usuário
            if show_regen:
                self._show_user_delete_btn()
        else:
            self._last_bot_row = row
            self._last_bot_text = text
            # Remover botão anterior
            self._remove_regen_btn()
            # Mostrar botões na resposta mais recente
            if show_regen:
                self._show_regen_btn()

        self.after(30, self._scroll_to_bottom)

    def _show_regen_btn(self):
        """Mostra os botões de regenerar e editar abaixo da última resposta do bot."""
        if self._last_user_input is None:
            return
        regen_row = tk.Frame(self.chat_frame, bg=BG_SECONDARY)
        regen_row.pack(fill="x", padx=52, pady=(0, 4))

        btn_cfg = dict(
            bg=BG_INPUT, activebackground=ACCENT,
            bd=0, padx=8, pady=4, cursor="hand2",
            relief="flat", highlightthickness=0,
        )

        btn_regen = tk.Button(regen_row, image=self._icon_refresh, command=self._regenerate_response, **btn_cfg)
        btn_regen.pack(side="left", padx=3)

        btn_edit = tk.Button(regen_row, image=self._icon_pencil, text="Editar", command=self._edit_response, **btn_cfg)
        btn_edit.pack(side="left", padx=3)

        btn_delete = tk.Button(regen_row, image=self._icon_trash, command=self._delete_response, **btn_cfg)
        btn_delete.pack(side="left", padx=3)

        btn_continue = tk.Button(regen_row, image=self._icon_arrow, text="Continuar", command=self._continue_response, **btn_cfg)
        btn_continue.pack(side="left", padx=3)

        self._regen_btn_row = regen_row

    def _show_user_delete_btn(self):
        """Mostra apenas o botão de excluir abaixo da última mensagem do usuário."""
        row = tk.Frame(self.chat_frame, bg=BG_SECONDARY)
        row.pack(fill="x", padx=20, pady=(0, 4))

        btn = tk.Button(
            row, image=self._icon_trash,
            bg=BG_INPUT, activebackground=ACCENT,
            bd=0, padx=8, pady=4, cursor="hand2",
            relief="flat", highlightthickness=0,
            command=self._delete_user_message
        )
        btn.pack(anchor="e")

        self._regen_btn_row = row

    def _remove_regen_btn(self):
        """Remove o botão de regenerar atual, se existir."""
        if self._regen_btn_row is not None:
            self._regen_btn_row.destroy()
            self._regen_btn_row = None

    # ── CANCELAR GERAÇÃO ────────────────────────────────────
    def _cancel_generation(self):
        """Cancela a geração em andamento."""
        _cancel_event.set()
        self.status_label.config(text="Cancelando…")

    # ── ENVIAR MENSAGEM ──────────────────────────────────────
    def _send_message(self):
        user_input = self.entry.get().strip()
        if not user_input or self._generating:
            return
        self._generating = True

        self.entry.delete(0, "end")
        self._add_bubble("user", user_input)

        self.entry.config(state="disabled")
        self.send_btn.pack_forget()
        self.cancel_btn.pack(side="right", padx=(0, 20))
        bot_name = self.app_config.get("bot_name", "Atlas")
        self.status_label.config(text=f"{bot_name} está digitando…")

        thread = threading.Thread(
            target=self._process_response, args=(user_input, False), daemon=True
        )
        thread.start()

    def _process_response(self, user_input, is_regen=False):
        try:
            extract_memory(user_input, self.memory)
            bot_name = self.app_config.get("bot_name", "Atlas")

            if is_regen:
                if (len(self.memory["conversation_history"]) >= 1
                        and self.memory["conversation_history"][-1].startswith("Agente: ")):
                    self.memory["conversation_history"].pop()

            system_msg, user_msg = build_context(self.system_prompt, self.memory, user_input, bot_name,
                                         self.app_config.get("user_nickname", ""))
            temp = 1.0 if is_regen else 0.7

            raw = ask_llm(user_msg, temperature=temp, system_msg=system_msg)
            response = _filter_think_tags(raw) or raw.strip()

            if is_regen:
                self.memory["conversation_history"].append(f"Agente: {response}")
            else:
                self.memory["conversation_history"].append(f"Usuário: {user_input}")
                self.memory["conversation_history"].append(f"Agente: {response}")

            save_memory(self.memory)
            self._ui_queue.put(response)

        except requests.exceptions.ConnectionError:
            self._ui_queue.put("⚠️ Não consegui conectar ao Ollama. Verifique se está rodando em localhost:11434.")
        except requests.exceptions.Timeout:
            self._ui_queue.put("⚠️ O modelo demorou demais para responder (timeout).")
        except Exception as e:
            self._ui_queue.put(f"⚠️ Erro: {e}")

    def _on_response_ready(self, response):
        self._add_bubble("bot", response, show_regen=True)
        self._re_enable_input()
        self._generating = False

    # ── REGENERAR RESPOSTA ───────────────────────────────────
    def _regenerate_response(self):
        """Remove a última resposta do bot e gera uma nova."""
        if not self._last_user_input or not self._last_bot_row or self._generating:
            return
        self._generating = True

        self._remove_regen_btn()
        self._last_bot_row.destroy()
        self._last_bot_row = None

        self.entry.config(state="disabled")
        self.send_btn.pack_forget()
        self.cancel_btn.pack(side="right", padx=(0, 20))
        bot_name = self.app_config.get("bot_name", "Atlas")
        self.status_label.config(text=f"{bot_name} está digitando…")

        user_input = self._last_user_input
        thread = threading.Thread(
            target=self._process_response, args=(user_input, True), daemon=True
        )
        thread.start()

    # ── EXCLUIR RESPOSTA ─────────────────────────────────────
    def _delete_response(self):
        """Remove apenas a última resposta do bot."""
        if not self._last_bot_row:
            return

        # Remover apenas a resposta do bot do histórico
        history = self.memory["conversation_history"]
        if (len(history) >= 1
                and history[-1].startswith("Agente: ")):
            history.pop()
        save_memory(self.memory)

        # Recarregar chat para mostrar botões na nova última mensagem
        self._reload_chat()

    # ── EXCLUIR MINHA MENSAGEM ────────────────────────────────
    def _delete_user_message(self):
        """Remove a última mensagem do usuário da tela e do histórico."""
        if not self._last_user_row:
            return

        # Remover do histórico
        history = self.memory["conversation_history"]
        if (len(history) >= 1
                and history[-1].startswith("Usuário: ")):
            history.pop()
        save_memory(self.memory)

        # Recarregar chat
        self._reload_chat()

    # ── CONTINUAR RESPOSTA ───────────────────────────────
    def _continue_response(self):
        """Pede ao bot para enviar uma mensagem complementar sem input do usuário."""
        if not self._last_bot_text or self._generating:
            return
        self._generating = True

        self._remove_regen_btn()

        self.entry.config(state="disabled")
        self.send_btn.pack_forget()
        self.cancel_btn.pack(side="right", padx=(0, 20))
        bot_name = self.app_config.get("bot_name", "Atlas")
        self.status_label.config(text=f"{bot_name} está digitando…")

        thread = threading.Thread(
            target=self._process_continue, daemon=True
        )
        thread.start()

    def _process_continue(self):
        try:
            bot_name = self.app_config.get("bot_name", "Atlas")
            user_nickname = self.app_config.get("user_nickname", "")

            formatted_history = []
            for msg in self.memory["conversation_history"][-12:]:
                if msg.startswith("Usuário: "):
                    formatted_history.append(f"[Usuário]: {msg[len('Usuário: '):]}")
                elif msg.startswith("Agente: "):
                    formatted_history.append(f"[{bot_name}]: {msg[len('Agente: '):]}")
                else:
                    formatted_history.append(msg)
            history = "\n".join(formatted_history)

            system_msg = self.system_prompt.replace("{bot_name}", bot_name).replace("{user_nickname}", user_nickname)

            user_msg = f"""Conversa recente:
{history}

A última mensagem foi sua. Envie mais uma mensagem complementando o que você disse, como se estivesse continuando a conversa naturalmente. Não repita o que já disse. Seja breve."""

            raw = ask_llm(user_msg, temperature=0.8, system_msg=system_msg)
            response = _filter_think_tags(raw) or raw.strip()

            self.memory["conversation_history"].append(f"Agente: {response}")
            save_memory(self.memory)
            self._ui_queue.put(response)

        except requests.exceptions.ConnectionError:
            self._ui_queue.put("⚠️ Não consegui conectar ao Ollama.")
        except Exception as e:
            self._ui_queue.put(f"⚠️ Erro: {e}")

    # ── EDITAR RESPOSTA ─────────────────────────────────────
    def _edit_response(self):
        """Abre janela para editar a última resposta do bot."""
        if not self._last_bot_text or not self._last_bot_row:
            return

        win = tk.Toplevel(self)
        win.title("Editar resposta")
        win.geometry("480x600")
        win.configure(bg=BG_PRIMARY)
        win.resizable(True, True)
        win.transient(self)
        win.grab_set()

        tk.Label(
            win, text="✏️  Editar resposta", font=self.font_title,
            bg=BG_PRIMARY, fg=ACCENT
        ).pack(pady=(14, 8))

        tk.Frame(win, bg=ACCENT, height=2).pack(fill="x", padx=20)

        # Área de texto editável
        text_frame = tk.Frame(win, bg=BG_PRIMARY)
        text_frame.pack(fill="both", expand=True, padx=20, pady=(1, 8))

        text_box = tk.Text(
            text_frame, font=self.font_msg, bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat", bd=0,
            wrap="word", padx=10, pady=1, state="normal"
        )
        text_box.pack(fill="both", expand=True)
        text_box.insert("1.0", self._last_bot_text)
        text_box.focus_force()

        def _save_edit():
            new_text = text_box.get("1.0", "end-1c").strip()
            if not new_text:
                return

            # Atualizar no memory.json
            for i in range(len(self.memory["conversation_history"]) - 1, -1, -1):
                if self.memory["conversation_history"][i].startswith("Agente: "):
                    self.memory["conversation_history"][i] = f"Agente: {new_text}"
                    break
            save_memory(self.memory)

            # Remover bolha antiga e botões
            self._remove_regen_btn()
            self._last_bot_row.destroy()
            self._last_bot_row = None
            self._last_bot_text = None

            # Adicionar nova bolha com texto editado
            self._add_bubble("bot", new_text, True)

            win.destroy()

        tk.Button(
            win, text="Salvar", font=self.font_msg,
            bg=ACCENT, fg="white", activebackground="#c83650",
            activeforeground="white", bd=0, padx=30, pady=10,
            cursor="hand2", command=_save_edit
        ).pack(pady=(0, 8))

    def _re_enable_input(self):
        self.cancel_btn.pack_forget()
        self.send_btn.pack(side="right", padx=(0, 20))
        self.entry.config(state="normal")
        self.status_label.config(text="")
        self.entry.focus_set()

    # ── CARREGAR HISTÓRICO ───────────────────────────────────
    def _load_history(self):
        history = self.memory.get("conversation_history", [])
        if not history:
            return
        # Detectar se a última mensagem é do usuário ou do bot
        last_is_user = history[-1].startswith("Usuário: ")
        for i, msg in enumerate(history):
            is_last = (i == len(history) - 1)
            if msg.startswith("Usuário: "):
                show = is_last and last_is_user
                self._add_bubble("user", msg[len("Usuário: "):], show_regen=show)
            elif msg.startswith("Agente: "):
                # Mostrar botões só na última mensagem do bot (e se for a última msg geral)
                is_last_bot = is_last and not last_is_user
                self._add_bubble("bot", msg[len("Agente: "):], show_regen=is_last_bot)

    def _reload_chat(self):
        for widget in self.chat_frame.winfo_children():
            widget.destroy()
        self._last_user_input = None
        self._last_user_row = None
        self._last_bot_row = None
        self._last_bot_text = None
        self._regen_btn_row = None
        self._load_history()
    # ── LIMPAR HISTÓRICO ─────────────────────────────────────
    def _clear_history(self):
        self.memory["conversation_history"] = []
        self.memory["important_facts"] = []
        save_memory(self.memory)

        # Remover bolhas da tela
        for widget in self.chat_frame.winfo_children():
            widget.destroy()

        # Resetar rastreamento
        self._last_user_input = None
        self._last_user_row = None
        self._last_bot_row = None
        self._last_bot_text = None
        self._regen_btn_row = None

    # ── CONFIGURAÇÕES ─────────────────────────────────────────
    def _open_settings(self):
        """Abre janela de configurações para nome e avatar."""
        win = tk.Toplevel(self)
        win.title("Configurações")
        win.geometry("420x480")
        win.configure(bg=BG_PRIMARY)
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        # ── Título ──
        tk.Label(
            win, text="⚙  Configurações", font=self.font_title,
            bg=BG_PRIMARY, fg=ACCENT
        ).pack(pady=(18, 12))

        tk.Frame(win, bg=ACCENT, height=2).pack(fill="x", padx=20)

        body = tk.Frame(win, bg=BG_PRIMARY)
        body.pack(fill="both", expand=True, padx=30, pady=16)

        # ── Nome do agente ──
        tk.Label(
            body, text="Nome do agente", font=self.font_msg,
            bg=BG_PRIMARY, fg=TEXT_PRIMARY
        ).pack(anchor="w", pady=(8, 4))

        name_var = tk.StringVar(value=self.app_config["bot_name"])
        name_wrapper = tk.Frame(body, bg=BG_INPUT)
        name_wrapper.pack(fill="x", ipady=8)
        name_entry = tk.Entry(
            name_wrapper, textvariable=name_var, font=self.font_input,
            bg=BG_INPUT, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
            relief="flat", bd=0
        )
        name_entry.pack(fill="both", expand=True, padx=(12, 4))

        # ── Apelido do usuário ──
        tk.Label(
            body, text="Como o bot te chama", font=self.font_msg,
            bg=BG_PRIMARY, fg=TEXT_PRIMARY
        ).pack(anchor="w", pady=(12, 4))

        nickname_var = tk.StringVar(value=self.app_config.get("user_nickname", ""))
        nickname_wrapper = tk.Frame(body, bg=BG_INPUT)
        nickname_wrapper.pack(fill="x", ipady=8)
        nickname_entry = tk.Entry(
            nickname_wrapper, textvariable=nickname_var, font=self.font_input,
            bg=BG_INPUT, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
            relief="flat", bd=0
        )
        nickname_entry.pack(fill="both", expand=True, padx=(12, 4))

        # ── Avatar ──
        tk.Label(
            body, text="Imagem de perfil", font=self.font_msg,
            bg=BG_PRIMARY, fg=TEXT_PRIMARY
        ).pack(anchor="w", pady=(16, 4))

        avatar_frame = tk.Frame(body, bg=BG_PRIMARY)
        avatar_frame.pack(fill="x")

        avatar_path_var = tk.StringVar(value=self.app_config.get("avatar_path", ""))

        # Preview do avatar
        preview_frame = tk.Frame(avatar_frame, bg=BG_PRIMARY)
        preview_frame.pack(side="left", padx=(0, 12))

        def _update_preview():
            for w in preview_frame.winfo_children():
                w.destroy()
            p = avatar_path_var.get()
            if p and Path(p).exists():
                try:
                    img = make_circle_avatar(p, 70)
                    lbl = tk.Label(preview_frame, image=img, bg=BG_PRIMARY)
                    lbl.image = img  # manter referência
                    lbl.pack()
                except Exception:
                    tk.Label(
                        preview_frame, text="❌", font=self.font_title,
                        bg=BG_PRIMARY, fg=ACCENT
                    ).pack()
            else:
                c = tk.Canvas(preview_frame, width=70, height=70,
                              bg=BG_PRIMARY, highlightthickness=0)
                c.pack()
                c.create_oval(2, 2, 68, 68, fill=BG_INPUT, outline=ACCENT, width=2)
                c.create_text(35, 35, text="?", fill=TEXT_SECONDARY,
                              font=("Segoe UI", 18, "bold"))

        _update_preview()

        btn_frame = tk.Frame(avatar_frame, bg=BG_PRIMARY)
        btn_frame.pack(side="left", fill="y")

        def _pick_image():
            path = filedialog.askopenfilename(
                parent=win,
                title="Escolher imagem de perfil",
                filetypes=[
                    ("Imagens", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                    ("Todos os arquivos", "*.*")
                ]
            )
            if path:
                avatar_path_var.set(path)
                _update_preview()

        def _remove_image():
            avatar_path_var.set("")
            _update_preview()

        tk.Button(
            btn_frame, text="📁  Escolher imagem", font=self.font_small,
            bg=BG_INPUT, fg=TEXT_PRIMARY, activebackground=ACCENT,
            activeforeground="white", bd=0, padx=12, pady=6,
            cursor="hand2", command=_pick_image
        ).pack(anchor="w", pady=(0, 6))

        tk.Button(
            btn_frame, text="✕  Remover", font=self.font_small,
            bg=BG_INPUT, fg=TEXT_SECONDARY, activebackground=ACCENT,
            activeforeground="white", bd=0, padx=12, pady=6,
            cursor="hand2", command=_remove_image
        ).pack(anchor="w")

        # Label de erro (invisível inicialmente)
        error_label = tk.Label(
            body, text="", font=self.font_small,
            bg=BG_PRIMARY, fg=ACCENT
        )
        error_label.pack(anchor="w", pady=(4, 0))

        # ── Botão salvar ──
        def _save():
            new_name = name_var.get().strip()
            if not new_name:
                error_label.config(text="Por favor, insira um nome válido.")
                name_entry.focus_set()
                return
            error_label.config(text="")
            self.app_config["bot_name"] = new_name
            self.app_config["user_nickname"] = nickname_var.get().strip() or ""
            self.app_config["avatar_path"] = avatar_path_var.get()
            save_config(self.app_config)

            # Atualizar avatar
            self._load_avatar()

            # Atualizar header
            self._name_label.config(text=f"{new_name}")
            self.title(f"{new_name}")
            self._draw_header_avatar()

            win.destroy()

        tk.Button(
            win, text="Salvar", font=self.font_msg,
            bg=ACCENT, fg="white", activebackground="#c83650",
            activeforeground="white", bd=0, padx=30, pady=10,
            cursor="hand2", command=_save
        ).pack(pady=(0, 18))

        name_entry.focus_set()

    # ── EDITOR DE PROMPT ─────────────────────────────────────
    def _open_prompt_editor(self):
        """Abre janela para editar o system_prompt.txt."""
        win = tk.Toplevel(self)
        win.title("Editar System Prompt")
        win.geometry("600x700")
        win.configure(bg=BG_PRIMARY)
        win.resizable(True, True)
        win.transient(self)
        win.grab_set()

        # Título
        tk.Label(
            win, text="📝  System Prompt", font=self.font_title,
            bg=BG_PRIMARY, fg=ACCENT
        ).pack(pady=(14, 8))

        tk.Frame(win, bg=ACCENT, height=2).pack(fill="x", padx=20)

        # Área de texto editável
        text_frame = tk.Frame(win, bg=BG_PRIMARY)
        text_frame.pack(fill="both", expand=True, padx=20, pady=(12, 8))

        text_scroll = tk.Scrollbar(text_frame)
        text_scroll.pack(side="right", fill="y")

        text_box = tk.Text(
            text_frame, font=self.font_msg, bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat", bd=0,
            wrap="word", padx=12, pady=10,
            yscrollcommand=text_scroll.set
        )
        text_box.pack(fill="both", expand=True)
        text_scroll.config(command=text_box.yview)

        # Carregar conteúdo atual do arquivo
        try:
            with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as f:
                current_prompt = f.read()
        except FileNotFoundError:
            current_prompt = ""

        text_box.insert("1.0", current_prompt)
        text_box.focus_force()

        # Feedback label
        feedback_label = tk.Label(
            win, text="", font=self.font_small,
            bg=BG_PRIMARY, fg="#4ade80"
        )
        feedback_label.pack(pady=(0, 4))

        # Botões
        btn_frame = tk.Frame(win, bg=BG_PRIMARY)
        btn_frame.pack(pady=(0, 14))

        def _save_prompt():
            new_prompt = text_box.get("1.0", "end-1c")
            with open(SYSTEM_PROMPT_FILE, "w", encoding="utf-8") as f:
                f.write(new_prompt)
            # Recarregar o prompt na memória da aplicação
            self.system_prompt = new_prompt
            feedback_label.config(text="✓ Prompt salvo com sucesso!")
            win.after(1500, lambda: feedback_label.config(text=""))

        def _reset_prompt():
            """Recarrega o conteúdo do arquivo (descarta edições não salvas)."""
            try:
                with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                content = ""
            text_box.delete("1.0", "end")
            text_box.insert("1.0", content)
            feedback_label.config(text="Alterações descartadas.")
            win.after(1500, lambda: feedback_label.config(text=""))

        tk.Button(
            btn_frame, text="Salvar", font=self.font_msg,
            bg=ACCENT, fg="white", activebackground="#c83650",
            activeforeground="white", bd=0, padx=30, pady=10,
            cursor="hand2", command=_save_prompt
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btn_frame, text="Descartar", font=self.font_msg,
            bg=BG_INPUT, fg=TEXT_PRIMARY, activebackground=ACCENT,
            activeforeground="white", bd=0, padx=20, pady=10,
            cursor="hand2", command=_reset_prompt
        ).pack(side="left")

    # ── FECHAR ───────────────────────────────────────────────
    def _on_close(self):
        save_memory(self.memory)
        self.destroy()


# ════════════════════════════════════════════════════════════════
#  EXECUTAR
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = ChatApp()
    app.mainloop()
