"""Consulta de servidores federais para Windows, via API Flask HTTP."""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from api_client import ApiError, fetch_servants


UF_OPTIONS = [""] + "AC AL AP AM BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()
MODES = {"Nome exato": "exact", "Nome semelhante": "similar", "Padrão com %": "pattern"}
BG = "#f3f6fb"
DARK = "#152a43"
ACCENT = "#155fd6"
MUTED = "#52657d"


class SearchDesktop(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Federal Servant Search — Consulta Desktop")
        self.geometry("1160x740")
        self.minsize(850, 610)
        self.configure(bg=BG)
        self._events = queue.Queue()
        self._request_id = 0
        self._loading = False
        self._active_filters = None
        self._pagination = {"page": 1, "pages": 0, "total": 0, "page_size": 20}
        self._items = []
        self._setup_styles()
        self._build_ui()
        self.after(100, self._poll_results)

    def _setup_styles(self):
        theme = ttk.Style(self)
        theme.theme_use("clam")
        theme.configure("App.TFrame", background=BG)
        theme.configure("Card.TFrame", background="white")
        theme.configure("TLabel", font=("Segoe UI", 10), foreground=DARK, background="white")
        theme.configure("Caption.TLabel", font=("Segoe UI", 9), foreground=MUTED, background="white")
        theme.configure("Title.TLabel", font=("Segoe UI Semibold", 20), foreground=DARK, background="white")
        theme.configure("TEntry", font=("Segoe UI", 10), padding=5)
        theme.configure("TCombobox", padding=5, font=("Segoe UI", 10))
        theme.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(18, 9),
                        background=ACCENT, foreground="white", borderwidth=0)
        theme.map("Primary.TButton", background=[("active", "#0b48a6"), ("disabled", "#afbdd0")])
        theme.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(14, 8))
        theme.configure("Treeview", rowheight=31, font=("Segoe UI", 10),
                        foreground=DARK, background="white", fieldbackground="white")
        theme.configure("Treeview.Heading", font=("Segoe UI Semibold", 10), padding=7,
                        foreground=DARK, background="#eaf0f8")
        theme.map("Treeview", background=[("selected", "#d8e7ff")],
                  foreground=[("selected", DARK)])

    def _build_ui(self):
        shell = ttk.Frame(self, style="App.TFrame", padding=20)
        shell.pack(fill="both", expand=True)
        content = ttk.Frame(shell, style="Card.TFrame", padding=21)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)

        header = ttk.Frame(content, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Consulta de servidores", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Dados públicos do Poder Executivo Federal · Aplicação desktop",
                  style="Caption.TLabel").pack(anchor="w", pady=(0, 12))

        self.url = tk.StringVar(value="http://127.0.0.1:8080")
        self.name = tk.StringVar()
        self.mode = tk.StringVar(value="Nome exato")
        self.position = tk.StringVar()
        self.agency = tk.StringVar()
        self.uf = tk.StringVar(value="")
        self.page_size = tk.StringVar(value="20")

        form = ttk.Frame(content, style="Card.TFrame")
        form.grid(row=1, column=0, sticky="ew")
        for col in range(4):
            form.columnconfigure(col, weight=1)
        ttk.Label(form, text="URL da aplicação", style="Caption.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(form, textvariable=self.url).grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 14), pady=(3, 12))
        ttk.Label(form, text="Modo de pesquisa", style="Caption.TLabel").grid(row=0, column=2, columnspan=2, sticky="w")
        ttk.Combobox(form, textvariable=self.mode, values=list(MODES), state="readonly").grid(
            row=1, column=2, columnspan=2, sticky="ew", pady=(3, 12))

        specs = [(0, "Nome completo ou padrão (%)", self.name), (1, "Cargo ou profissão", self.position),
                 (2, "Órgão ou instituição", self.agency)]
        for col, label, var in specs:
            ttk.Label(form, text=label, style="Caption.TLabel").grid(row=2, column=col, sticky="w")
            ttk.Entry(form, textvariable=var).grid(row=3, column=col, sticky="ew", padx=(0, 14), pady=(3, 12))
        ttk.Label(form, text="UF", style="Caption.TLabel").grid(row=2, column=3, sticky="w")
        ttk.Combobox(form, textvariable=self.uf, values=UF_OPTIONS, state="readonly").grid(
            row=3, column=3, sticky="ew", pady=(3, 12))

        controls = ttk.Frame(content, style="Card.TFrame")
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 11))
        ttk.Label(controls, text="Resultados por página", style="Caption.TLabel").pack(side="left")
        ttk.Combobox(controls, textvariable=self.page_size, state="readonly",
                     width=5, values=["10", "20", "50", "100"]).pack(side="left", padx=(8, 20))
        self.search_button = ttk.Button(controls, text="Pesquisar", style="Primary.TButton", command=self.search)
        self.search_button.pack(side="left")
        self.clear_button = ttk.Button(controls, text="Limpar", style="Secondary.TButton", command=self.clear)
        self.clear_button.pack(side="left", padx=10)
        ttk.Label(controls, text="Busca por padrão: MARIA%SILVA%",
                  style="Caption.TLabel").pack(side="right")

        listing = ttk.Frame(content, style="Card.TFrame")
        listing.grid(row=3, column=0, sticky="nsew")
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        keys = ("nome", "cargo", "orgao", "uf", "fonte")
        self.table = ttk.Treeview(listing, columns=keys, show="headings", selectmode="browse")
        sizes = {"nome": 260, "cargo": 240, "orgao": 250, "uf": 65, "fonte": 110}
        captions = {"nome": "Nome", "cargo": "Cargo", "orgao": "Órgão", "uf": "UF", "fonte": "Fonte"}
        for field in keys:
            self.table.heading(field, text=captions[field])
            self.table.column(field, width=sizes[field], minwidth=55, stretch=(field != "uf"))
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(listing, orient="vertical", command=self.table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(listing, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.bind("<Double-1>", self.details)

        footer = ttk.Frame(content, style="Card.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.status = tk.StringVar(value="Informe um filtro e clique em Pesquisar.")
        ttk.Label(footer, textvariable=self.status, style="Caption.TLabel").pack(side="left")
        self.next_button = ttk.Button(footer, text="Próxima ›", command=lambda: self.change_page(1))
        self.next_button.pack(side="right")
        self.page_label = ttk.Label(footer, text="Página 0 de 0", style="Caption.TLabel")
        self.page_label.pack(side="right", padx=12)
        self.prev_button = ttk.Button(footer, text="‹ Anterior", command=lambda: self.change_page(-1))
        self.prev_button.pack(side="right")
        self.detail_button = ttk.Button(footer, text="Ver detalhes", command=self.details)
        self.detail_button.pack(side="right", padx=12)
        self._refresh_buttons()
        self.bind("<Return>", lambda _event: self.search())

    def _filters(self):
        return {"name": self.name.get(), "name_mode": MODES[self.mode.get()],
                "position": self.position.get(), "agency": self.agency.get(),
                "uf": self.uf.get(), "page_size": self.page_size.get()}

    def search(self):
        if self._loading:
            return
        filters = self._filters()
        if not any(str(filters[key]).strip() for key in ("name", "position", "agency", "uf")):
            self.status.set("Informe pelo menos um filtro para pesquisar.")
            return
        self._active_filters = filters
        self._items = []
        self._pagination = {"page": 1, "pages": 0, "total": 0, "page_size": int(filters["page_size"])}
        self.table.delete(*self.table.get_children())
        self._start_request(1)

    def change_page(self, delta):
        new_page = self._pagination["page"] + delta
        if (self._loading or self._active_filters is None
                or new_page < 1 or new_page > self._pagination["pages"]):
            return
        self._start_request(new_page)

    def _start_request(self, page):
        self._request_id += 1
        seq = self._request_id
        self._loading = True
        self._refresh_buttons()
        self.status.set("Consultando API...")
        target = self.url.get()
        filters = dict(self._active_filters)

        def work():
            try:
                outcome = ("ok", fetch_servants(target, filters, page))
            except ApiError as error:
                outcome = ("error", str(error))
            except Exception:
                outcome = ("error", "Falha inesperada na consulta. Tente novamente.")
            self._events.put((seq, outcome))

        threading.Thread(target=work, daemon=True).start()

    def _poll_results(self):
        try:
            while True:
                seq, outcome = self._events.get_nowait()
                if seq != self._request_id:
                    continue
                self._loading = False
                if outcome[0] == "ok":
                    self._render_results(outcome[1])
                else:
                    self.status.set(outcome[1])
                self._refresh_buttons()
        except queue.Empty:
            pass
        self.after(100, self._poll_results)

    def _render_results(self, data):
        self._items = data["items"]
        self._pagination = data["pagination"]
        self.table.delete(*self.table.get_children())
        for index, item in enumerate(self._items):
            fields = tuple(item[key] or "—" for key in ("nome", "cargo", "orgao", "uf", "fonte"))
            self.table.insert("", "end", iid=str(index), values=fields)
        total = self._pagination["total"]
        current = self._pagination["page"]
        per_page = self._pagination["page_size"]
        if total:
            first = (current - 1) * per_page + 1
            last = first + len(self._items) - 1
            self.status.set(f"Exibindo {first:,}–{last:,} de {total:,} registros".replace(",", "."))
        else:
            self.status.set("Nenhum registro encontrado para os filtros informados.")

    def _refresh_buttons(self):
        can_prev = not self._loading and self._pagination["page"] > 1
        can_next = not self._loading and self._pagination["page"] < self._pagination["pages"]
        self.search_button.configure(state="disabled" if self._loading else "normal")
        self.prev_button.configure(state="normal" if can_prev else "disabled")
        self.next_button.configure(state="normal" if can_next else "disabled")
        self.detail_button.configure(state="normal" if self._items and not self._loading else "disabled")
        self.page_label.configure(text=f"Página {self._pagination['page'] if self._pagination['pages'] else 0} de {self._pagination['pages']}")

    def clear(self):
        self._request_id += 1
        self._loading = False
        self._active_filters = None
        self._items = []
        self._pagination = {"page": 1, "pages": 0, "total": 0, "page_size": 20}
        for var in (self.name, self.position, self.agency, self.uf):
            var.set("")
        self.mode.set("Nome exato")
        self.page_size.set("20")
        self.table.delete(*self.table.get_children())
        self.status.set("Informe um filtro e clique em Pesquisar.")
        self._refresh_buttons()

    def details(self, _event=None):
        chosen = self.table.selection()
        if not chosen or self._loading:
            return
        item = self._items[int(chosen[0])]
        detail = tk.Toplevel(self)
        detail.title("Detalhes do registro")
        detail.geometry("650x330")
        detail.transient(self)
        detail.configure(bg="white")
        frame = ttk.Frame(detail, style="Card.TFrame", padding=24)
        frame.pack(fill="both", expand=True)
        headings = (("Nome", "nome"), ("Cargo", "cargo"), ("Órgão", "orgao"),
                    ("UF", "uf"), ("Fonte", "fonte"), ("ID", "id"))
        for idx, (title, key) in enumerate(headings):
            ttk.Label(frame, text=title, style="Caption.TLabel").grid(row=idx, column=0, sticky="nw", pady=7, padx=(0, 20))
            ttk.Label(frame, text=str(item.get(key) or "Não informado"), wraplength=460).grid(
                row=idx, column=1, sticky="nw", pady=7)
        frame.columnconfigure(1, weight=1)


def main():
    SearchDesktop().mainloop()


if __name__ == "__main__":
    main()
