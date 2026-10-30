# fastByDownload - YouTube ve diger sitelerden video (MP4) / ses (MP3) indirici
# yt-dlp (Unlicense) ve FFmpeg (GPL/LGPL) kullanir. Bkz. LICENSES/
import os, sys, json, re, threading, subprocess, hashlib, tempfile, urllib.request, io, time, shutil, queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP = "fastByDownload"
VERSION = "1.0.0"
REPO = "genelguvenlik/fastbydownload"
MANIFEST_URL = os.environ.get("FBD_MANIFEST") or f"https://github.com/{REPO}/releases/latest/download/fastbydownload-guncelleme.json"
APPDATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP)
BIN = os.path.join(APPDATA, "bin")
HIST = os.path.join(APPDATA, "gecmis.json")
SETTINGS = os.path.join(APPDATA, "ayarlar.json")
DEF_OUT = os.path.join(os.path.expanduser("~"), "Downloads", APP)
NOWIN = 0x08000000 if os.name == "nt" else 0
UA = {"User-Agent": f"{APP}/{VERSION}"}

def res(name):
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
    return os.path.join(base, name)

def exe(n): return n + (".exe" if os.name == "nt" else "")
YTDLP = os.path.join(BIN, exe("yt-dlp"))
FFMPEG = os.path.join(BIN, exe("ffmpeg"))

def prepare_bin():
    """Araclar exe icinde tek bir tools.zip olarak gelir; ilk acilista (veya surum degisince) %APPDATA%\\fastByDownload\\bin'e acilir."""
    import zipfile
    os.makedirs(BIN, exist_ok=True)
    z = res("tools.zip")
    if not os.path.exists(z): return
    stamp = f"{VERSION}:{os.path.getsize(z)}"
    mark = os.path.join(BIN, ".surum")
    try: cur = open(mark).read()
    except OSError: cur = ""
    if cur == stamp and os.path.exists(FFMPEG) and os.path.exists(YTDLP): return
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            if n.lower().startswith("yt-dlp") and os.path.exists(YTDLP): continue  # kendi guncellenen kopyayi koru
            zf.extract(n, BIN)
    with open(mark, "w") as f: f.write(stamp)

def load_json(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return d

def save_json(p, v):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(v, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)

def vtuple(v): return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])

def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, **kw)

def open_path(p):
    if os.name == "nt": os.startfile(p)
    else: subprocess.Popen(["xdg-open", p])

def reveal(p):
    if os.name == "nt" and os.path.isfile(p): subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
    else: open_path(p if os.path.isdir(p) else os.path.dirname(p))

# ---------------- guncelleme (QxMsn yontemi: manifest + SHA256 + PowerShell ile yerinde degistirme) -------------
PS_INSTALL = r'''
$ErrorActionPreference = 'Continue'
$log = Join-Path $env:FBD_DATA 'guncelleme.log'
function L($m) { Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $m) }
$new = $env:FBD_NEW; $tgt = $env:FBD_TGT; $sha = $env:FBD_SHA
L "basladi new=$new tgt=$tgt"
foreach ($p in ($env:FBD_PIDS -split ',')) { if ($p) { try { Wait-Process -Id ([int]$p) -Timeout 60 -ErrorAction Stop } catch {} } }
$ok = $false
$h = (Get-FileHash -LiteralPath $new -Algorithm SHA256).Hash.ToLower()
if ($h -eq $sha) {
  for ($n = 0; $n -lt 80 -and -not $ok; $n++) { try { Copy-Item -LiteralPath $new -Destination $tgt -Force -ErrorAction Stop; $ok = $true } catch { Start-Sleep -Milliseconds 750 } }
} else { L "sha uyusmadi $h" }
L "kopyalandi=$ok"
Remove-Item -LiteralPath $new -Force -ErrorAction SilentlyContinue
Get-ChildItem env: | Where-Object { $_.Name -like '_MEI*' -or $_.Name -like '_PYI*' } | ForEach-Object { Remove-Item ("env:" + $_.Name) }
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
Start-Process -FilePath $tgt
L "baslatildi"
'''

def fetch_manifest():
    with urllib.request.urlopen(urllib.request.Request(MANIFEST_URL, headers=UA), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def download_file(url, dst, cb=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, open(dst, "wb") as f:
        tot = int(r.headers.get("Content-Length") or 0); got = 0; h = hashlib.sha256()
        while True:
            b = r.read(1 << 16)
            if not b: break
            f.write(b); h.update(b); got += len(b)
            if cb and tot: cb(got / tot)
    return h.hexdigest()

def install_and_restart(new_exe, sha):
    tgt = sys.executable
    ps1 = os.path.join(APPDATA, "guncelle.ps1")
    with open(ps1, "w", encoding="utf-8-sig") as f: f.write(PS_INSTALL)
    env = {k: v for k, v in os.environ.items() if not (k.startswith("_MEI") or k.startswith("_PYI"))}
    env.update(FBD_NEW=new_exe, FBD_TGT=tgt, FBD_SHA=sha.lower(), FBD_DATA=APPDATA, FBD_PIDS=f"{os.getpid()},{os.getppid()}")
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", ps1]
    kw = dict(env=env, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try: subprocess.Popen(args, creationflags=0x08000000 | 0x00000200 | 0x01000000, **kw)  # NO_WINDOW | NEW_GROUP | BREAKAWAY_FROM_JOB
    except OSError: subprocess.Popen(args, creationflags=0x08000000 | 0x00000200, **kw)

# ---------------- arayuz ----------------
PROG_RE = re.compile(r"^FBDP\|(?P<p>[^|]*)\|(?P<s>[^|]*)\|(?P<e>[^|]*)\|(?P<d>[^|]*)\|(?P<t>[^|]*)$")

def dpi_aware():
    if os.name != "nt": return
    import ctypes
    try: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try: ctypes.windll.user32.SetProcessDPIAware()
            except Exception: pass

def load_fonts():
    """Exe icindeki Inter yazi tipini yalnizca bu islem icin yukler (sisteme kurmaz)."""
    if os.name != "nt": return
    import ctypes
    for n in ("Inter-Regular.ttf", "Inter-Bold.ttf"):
        f = res(os.path.join("fonts", n))
        if os.path.exists(f): ctypes.windll.gdi32.AddFontResourceExW(f, 0x10, 0)  # FR_PRIVATE

class App(tk.Tk):
    def __init__(self):
        dpi_aware(); load_fonts()
        super().__init__()
        self.title(f"{APP} {VERSION}"); sc = self.winfo_fpixels("1i") / 96; self.geometry(f"{int(920*sc)}x{int(680*sc)}"); self.minsize(int(780*sc), int(600*sc))
        try: self.iconbitmap(res("icon.ico"))
        except Exception: pass
        self.q = queue.Queue(); self.proc = None; self.cancelled = False; self.info = None; self.last_file = None
        self.settings = load_json(SETTINGS, {}); self.history = load_json(HIST, [])
        self.style()
        self.build()
        self.after(100, self.pump)
        threading.Thread(target=self.bg_init, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def style(self):
        import tkinter.font as tkf
        fams = set(tkf.families(self))
        self.FONT = next((f for f in ("Inter", "Segoe UI Variable Text", "Segoe UI", "DejaVu Sans") if f in fams), "TkDefaultFont")
        head = self.FONT
        try: self.tk.call("tk", "scaling", self.winfo_fpixels("1i") / 72.0)
        except Exception: pass
        for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
            try: tkf.nametofont(n).configure(family=self.FONT, size=10)
            except Exception: pass
        try:
            import sv_ttk; sv_ttk.set_theme("light")
        except Exception:
            ttk.Style(self).theme_use("vista" if os.name == "nt" else "clam")
        s = ttk.Style(self)
        for n in ("TkDefaultFont", "TkTextFont", "TkHeadingFont"):
            try: tkf.nametofont(n).configure(family=self.FONT, size=10)
            except Exception: pass
        s.configure(".", font=(self.FONT, 10))
        s.configure("Title.TLabel", font=(head, 15, "bold"))
        s.configure("Big.TButton", font=(self.FONT, 11, "bold"))
        s.configure("Treeview", rowheight=int(self.winfo_fpixels("1i") / 96 * 28))
        s.configure("Treeview.Heading", font=(self.FONT, 10, "bold"))
        self.option_add("*TCombobox*Listbox.font", (self.FONT, 10))
        self.F = lambda size=10, w="normal": (self.FONT, size, w)

    def build(self):
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=8, pady=8); self.nb = nb
        t1 = ttk.Frame(nb, padding=12); nb.add(t1, text="  İndir  ")
        t2 = ttk.Frame(nb, padding=12); nb.add(t2, text="  Geçmiş  ")
        t3 = ttk.Frame(nb, padding=12); nb.add(t3, text="  Ayarlar / Hakkında  ")
        # --- indir
        ttk.Label(t1, text="Video bağlantısını yapıştır", style="Title.TLabel").pack(anchor="w")
        r = ttk.Frame(t1); r.pack(fill="x", pady=6)
        self.url = tk.StringVar()
        self.e_url = ttk.Entry(r, textvariable=self.url, font=(self.FONT, 11)); self.e_url.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(r, text="Yapıştır", command=self.paste).pack(side="left", padx=4)
        ttk.Button(r, text="Önizle", command=self.preview).pack(side="left")
        self.url.trace_add("write", lambda *a: self.after(600, self.auto_preview, self.url.get()))
        pv = ttk.Frame(t1); pv.pack(fill="x", pady=6)
        self.thumb = ttk.Label(pv, text="(önizleme)", width=40, anchor="center", relief="groove"); self.thumb.pack(side="left", ipadx=4, ipady=40)
        self.thumb_img = None
        inf = ttk.Frame(pv); inf.pack(side="left", fill="both", expand=True, padx=10)
        self.l_title = ttk.Label(inf, text="", font=(self.FONT, 13, "bold"), wraplength=480, justify="left"); self.l_title.pack(anchor="w")
        self.l_meta = ttk.Label(inf, text="", foreground="#555"); self.l_meta.pack(anchor="w", pady=4)
        op = ttk.LabelFrame(t1, text="Seçenekler", padding=10); op.pack(fill="x", pady=6)
        self.kind = tk.StringVar(value=self.settings.get("kind", "video"))
        ttk.Radiobutton(op, text="Video (MP4)", value="video", variable=self.kind, command=self.kind_changed).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(op, text="Ses (MP3)", value="audio", variable=self.kind, command=self.kind_changed).grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(op, text="Kalite:").grid(row=0, column=2, padx=(30, 4))
        self.quality = tk.StringVar(); self.cb_q = ttk.Combobox(op, textvariable=self.quality, state="readonly", width=16); self.cb_q.grid(row=0, column=3)
        ttk.Label(op, text="Klasör:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.outdir = tk.StringVar(value=self.settings.get("outdir", DEF_OUT))
        ttk.Entry(op, textvariable=self.outdir).grid(row=1, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(op, text="Seç…", command=self.pick_dir).grid(row=1, column=4, padx=4, pady=(10, 0))
        ttk.Button(op, text="Aç", command=lambda: self.open_dir(self.outdir.get())).grid(row=1, column=5, pady=(10, 0))
        op.columnconfigure(3, weight=1)
        self.kind_changed()
        b = ttk.Frame(t1); b.pack(fill="x", pady=8)
        self.b_dl = ttk.Button(b, text="⬇  İndir", style="Accent.TButton", command=self.start); self.b_dl.pack(side="left")
        self.b_cancel = ttk.Button(b, text="İptal", command=self.cancel, state="disabled"); self.b_cancel.pack(side="left", padx=6)
        self.b_ofile = ttk.Button(b, text="Dosyayı Aç", command=self.open_last, state="disabled"); self.b_ofile.pack(side="right")
        self.b_odir = ttk.Button(b, text="Klasörde Göster", command=self.reveal_last, state="disabled"); self.b_odir.pack(side="right", padx=6)
        self.pb = ttk.Progressbar(t1, maximum=100); self.pb.pack(fill="x", pady=4)
        self.status = ttk.Label(t1, text="Hazır."); self.status.pack(anchor="w")
        # --- gecmis
        r = ttk.Frame(t2); r.pack(fill="x")
        ttk.Label(r, text="Ara:").pack(side="left")
        self.search = tk.StringVar(); self.search.trace_add("write", lambda *a: self.fill_history())
        ttk.Entry(r, textvariable=self.search).pack(side="left", fill="x", expand=True, padx=6)
        cols = ("tarih", "tur", "baslik", "dosya")
        self.tv = ttk.Treeview(t2, columns=cols, show="headings", selectmode="browse")
        for c, w, h in (("tarih", 130, "Tarih"), ("tur", 70, "Tür"), ("baslik", 330, "Başlık"), ("dosya", 260, "Dosya")):
            self.tv.heading(c, text=h); self.tv.column(c, width=w, anchor="w")
        self.tv.pack(fill="both", expand=True, pady=6)
        self.tv.bind("<Double-1>", lambda e: self.h_open())
        r = ttk.Frame(t2); r.pack(fill="x")
        ttk.Button(r, text="Dosyayı Aç", command=self.h_open).pack(side="left")
        ttk.Button(r, text="Klasörde Göster", command=self.h_reveal).pack(side="left", padx=4)
        ttk.Button(r, text="Tekrar İndir", command=self.h_redo).pack(side="left")
        ttk.Button(r, text="Bağlantıyı Kopyala", command=self.h_copy).pack(side="left", padx=4)
        ttk.Button(r, text="Kaydı Sil", command=self.h_delete).pack(side="right")
        ttk.Button(r, text="Geçmişi Temizle", command=self.h_clear).pack(side="right", padx=4)
        self.fill_history()
        # --- ayarlar
        ttk.Label(t3, text=f"{APP} sürüm {VERSION}", style="Title.TLabel").pack(anchor="w")
        self.l_ver = ttk.Label(t3, text="yt-dlp: …   ffmpeg: …"); self.l_ver.pack(anchor="w", pady=4)
        r = ttk.Frame(t3); r.pack(anchor="w", pady=6)
        ttk.Button(r, text="Program Güncellemesini Denetle", command=lambda: self.check_update(manual=True)).pack(side="left")
        ttk.Button(r, text="yt-dlp'yi Güncelle", command=self.update_ytdlp).pack(side="left", padx=6)
        ttk.Button(r, text="Veri Klasörünü Aç", command=lambda: self.open_dir(APPDATA)).pack(side="left")
        self.auto_upd = tk.BooleanVar(value=self.settings.get("auto_update", True))
        ttk.Checkbutton(t3, text="Açılışta güncellemeleri denetle", variable=self.auto_upd, command=self.save_settings).pack(anchor="w", pady=6)
        self.l_upd = ttk.Label(t3, text=""); self.l_upd.pack(anchor="w")
        ttk.Label(t3, foreground="#555", wraplength=760, justify="left", text=(
            "Açık kaynak: yt-dlp (Unlicense), FFmpeg (GPL), Python/Tkinter (PSF). Lisans metinleri program klasöründe LICENSES içinde.\n"
            "Yalnızca kendi içeriklerinizi veya indirme izni olan içerikleri indirin.")).pack(anchor="w", pady=12)

    # ---- yardimcilar
    def ui(self, fn, *a): self.q.put((fn, a))
    def pump(self):
        try:
            while True:
                fn, a = self.q.get_nowait(); fn(*a)
        except queue.Empty: pass
        self.after(80, self.pump)

    def save_settings(self):
        self.settings.update(kind=self.kind.get(), outdir=self.outdir.get(), auto_update=self.auto_upd.get())
        save_json(SETTINGS, self.settings)

    def kind_changed(self):
        if self.kind.get() == "video":
            vals = ["En iyi", "1080p", "720p", "480p", "360p"]
        else:
            vals = ["320 kbps", "192 kbps", "128 kbps"]
        self.cb_q["values"] = vals
        if self.quality.get() not in vals: self.quality.set(vals[0])

    def paste(self):
        try: self.url.set(self.clipboard_get().strip())
        except Exception: pass
        self.preview()

    def pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.outdir.get() if os.path.isdir(self.outdir.get()) else os.path.expanduser("~"))
        if d: self.outdir.set(os.path.normpath(d)); self.save_settings()

    def open_dir(self, d):
        os.makedirs(d, exist_ok=True); open_path(d)

    def bg_init(self):
        try: prepare_bin()
        except Exception as e: self.ui(self.status.config, {"text": f"Hata: araçlar hazırlanamadı: {e}"}); return
        self.refresh_versions()
        if self.settings.get("auto_update", True) and not os.environ.get("FBD_NO_AUTOUPDATE"):
            self.check_update(manual=False)

    def refresh_versions(self):
        try: yv = run([YTDLP, "--version"], timeout=30).stdout.strip()
        except Exception: yv = "?"
        try: fv = run([FFMPEG, "-version"], timeout=30).stdout.split("\n")[0].split(" ")[2]
        except Exception: fv = "?"
        self.ui(self.l_ver.config, {"text": f"yt-dlp: {yv}     ffmpeg: {fv}"})

    # ---- onizleme
    def auto_preview(self, val):
        if val == self.url.get() and re.match(r"https?://", val.strip()) and (not self.info or self.info.get("_url") != val.strip()):
            self.preview()

    def preview(self):
        u = self.url.get().strip()
        if not re.match(r"https?://", u):
            self.status.config(text="Geçerli bir bağlantı yapıştır (https://…)."); return
        self.status.config(text="Önizleme alınıyor…"); self.l_title.config(text=""); self.l_meta.config(text="")
        threading.Thread(target=self._preview, args=(u,), daemon=True).start()

    def _preview(self, u):
        try:
            p = run([YTDLP, "-J", "--no-playlist", "--no-warnings", u], timeout=90)
            if p.returncode != 0: raise RuntimeError((p.stderr.strip().splitlines() or ["bilinmeyen hata"])[-1])
            info = json.loads(p.stdout); info["_url"] = u; self.info = info
            dur = info.get("duration") or 0
            meta = f"{info.get('uploader') or info.get('extractor_key','')}   •   {int(dur//3600):d}:{int(dur%3600//60):02d}:{int(dur%60):02d}" if dur else (info.get("uploader") or "")
            self.ui(self.l_title.config, {"text": info.get("title", "")}); self.ui(self.l_meta.config, {"text": meta})
            self.ui(self.status.config, {"text": "Önizleme hazır. Biçim ve kaliteyi seçip İndir'e bas."})
            th = info.get("thumbnail")
            if th:
                from PIL import Image, ImageTk
                with urllib.request.urlopen(urllib.request.Request(th, headers=UA), timeout=20) as r: data = r.read()
                im = Image.open(io.BytesIO(data)).convert("RGB"); im.thumbnail((300, 170))
                def setimg(im=im):
                    self.thumb_img = ImageTk.PhotoImage(im); self.thumb.config(image=self.thumb_img, text="")
                self.ui(setimg)
        except Exception as e:
            self.ui(self.status.config, {"text": f"Önizleme alınamadı: {e}"})

    # ---- indirme
    def build_args(self, u, out):
        tmpl = os.path.join(out, "%(title).150B [%(id)s].%(ext)s")
        a = [YTDLP, u, "--no-playlist", "--newline", "--no-colors", "--ffmpeg-location", BIN, "-o", tmpl,
             "--progress-template", "download:FBDP|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress._downloaded_bytes_str)s|%(progress._total_bytes_str)s",
             "--print", "after_move:FBDF|%(filepath)s", "--windows-filenames"]
        q = self.quality.get()
        if self.kind.get() == "audio":
            a += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", q.split()[0] + "K", "--embed-thumbnail", "--add-metadata"]
        else:
            h = None if q.startswith("En") else q.rstrip("p")
            # once cozunurluk, ayni cozunurlukte Windows'ta her yerde oynayan H.264 + AAC tercih edilir
            a += ["-f", "bv*+ba/b", "-S", (f"res:{h}," if h else "res,") + "vcodec:h264,acodec:aac", "--merge-output-format", "mp4", "--remux-video", "mp4"]
        return a

    def start(self):
        u = self.url.get().strip()
        if not re.match(r"https?://", u):
            messagebox.showwarning(APP, "Önce geçerli bir bağlantı yapıştır."); return
        out = self.outdir.get().strip() or DEF_OUT
        try: os.makedirs(out, exist_ok=True)
        except Exception as e: messagebox.showerror(APP, f"Klasör oluşturulamadı:\n{e}"); return
        self.save_settings()
        self.cancelled = False; self.pb["value"] = 0
        self.b_dl.config(state="disabled"); self.b_cancel.config(state="normal")
        self.status.config(text="Başlatılıyor…")
        threading.Thread(target=self._download, args=(u, out, self.kind.get(), self.quality.get()), daemon=True).start()

    def _download(self, u, out, kind, q):
        files, err = [], []
        try:
            self.proc = subprocess.Popen(self.build_args(u, out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace", creationflags=NOWIN, bufsize=1)
            for line in self.proc.stdout:
                line = line.rstrip()
                m = PROG_RE.match(line)
                if m:
                    try: pct = float(m["p"].strip().rstrip("%"))
                    except ValueError: pct = None
                    txt = f"%{m['p'].strip().rstrip('%')}   •   {m['d'].strip()} / {m['t'].strip()}   •   Hız: {m['s'].strip()}   •   Kalan: {m['e'].strip()}"
                    if pct is not None: self.ui(self.pb.config, {"value": pct})
                    self.ui(self.status.config, {"text": txt})
                elif line.startswith("FBDF|"):
                    files.append(line[5:])
                elif "[ExtractAudio]" in line or "[Merger]" in line or "[VideoRemuxer]" in line:
                    self.ui(self.status.config, {"text": "Dönüştürülüyor (ffmpeg)…"})
                elif line.startswith("ERROR"):
                    err.append(line)
            rc = self.proc.wait()
        except Exception as e:
            rc, err = -1, [str(e)]
        self.proc = None
        self.ui(self.done, rc, files, err, u, kind, q)

    def done(self, rc, files, err, u, kind, q):
        self.b_dl.config(state="normal"); self.b_cancel.config(state="disabled")
        if self.cancelled:
            self.pb["value"] = 0; self.status.config(text="İndirme iptal edildi."); return
        if rc == 0 and files:
            f = files[-1]; self.last_file = f; self.pb["value"] = 100
            self.status.config(text=f"Tamamlandı: {os.path.basename(f)}")
            self.b_ofile.config(state="normal"); self.b_odir.config(state="normal")
            title = (self.info or {}).get("title") if (self.info or {}).get("_url") == u else None
            self.history.insert(0, {"tarih": time.strftime("%Y-%m-%d %H:%M"), "tur": "MP3" if kind == "audio" else "MP4", "kalite": q,
                                    "baslik": title or os.path.splitext(os.path.basename(f))[0], "url": u, "dosya": f})
            save_json(HIST, self.history); self.fill_history()
        else:
            msg = err[-1] if err else f"çıkış kodu {rc}"
            self.status.config(text=f"Hata: {msg}")
            messagebox.showerror(APP, f"İndirme başarısız:\n{msg}\n\nSite değiştiyse Ayarlar'dan yt-dlp'yi güncellemeyi dene.")

    def cancel(self):
        p = self.proc
        if p:
            self.cancelled = True
            if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, creationflags=NOWIN)
            else: p.kill()
            self.status.config(text="İptal ediliyor…")

    def open_last(self):
        if self.last_file and os.path.exists(self.last_file): open_path(self.last_file)
        else: messagebox.showwarning(APP, "Dosya bulunamadı.")
    def reveal_last(self):
        if self.last_file: reveal(self.last_file)

    # ---- gecmis
    def fill_history(self):
        s = self.search.get().lower().strip() if hasattr(self, "search") else ""
        self.tv.delete(*self.tv.get_children())
        for i, h in enumerate(self.history):
            if s and s not in (h.get("baslik", "") + " " + h.get("url", "") + " " + h.get("dosya", "")).lower(): continue
            self.tv.insert("", "end", iid=str(i), values=(h.get("tarih"), f"{h.get('tur')} {h.get('kalite','')}", h.get("baslik"), os.path.basename(h.get("dosya", ""))))
    def sel(self):
        s = self.tv.selection()
        if not s: messagebox.showinfo(APP, "Önce listeden bir kayıt seç."); return None
        return int(s[0])
    def h_open(self):
        i = self.sel()
        if i is None: return
        f = self.history[i].get("dosya")
        if f and os.path.exists(f): open_path(f)
        else: messagebox.showwarning(APP, "Dosya artık yerinde değil (silinmiş veya taşınmış olabilir).")
    def h_reveal(self):
        i = self.sel()
        if i is None: return
        f = self.history[i].get("dosya", "")
        if os.path.exists(f): reveal(f)
        elif os.path.isdir(os.path.dirname(f)): open_path(os.path.dirname(f))
        else: messagebox.showwarning(APP, "Klasör bulunamadı.")
    def h_redo(self):
        i = self.sel()
        if i is None: return
        h = self.history[i]
        self.kind.set("audio" if h.get("tur") == "MP3" else "video"); self.kind_changed()
        if h.get("kalite") in self.cb_q["values"]: self.quality.set(h["kalite"])
        self.url.set(h.get("url", "")); self.nb.select(0); self.preview()
    def h_copy(self):
        i = self.sel()
        if i is None: return
        self.clipboard_clear(); self.clipboard_append(self.history[i].get("url", "")); self.status.config(text="Bağlantı panoya kopyalandı.")
    def h_delete(self):
        i = self.sel()
        if i is None: return
        if messagebox.askyesno(APP, "Bu kayıt geçmişten silinsin mi? (İndirilen dosya silinmez)"):
            self.history.pop(i); save_json(HIST, self.history); self.fill_history()
    def h_clear(self):
        if self.history and messagebox.askyesno(APP, "Tüm geçmiş temizlensin mi? (İndirilen dosyalar silinmez)"):
            self.history = []; save_json(HIST, self.history); self.fill_history()

    # ---- guncellemeler
    def update_ytdlp(self):
        self.l_upd.config(text="yt-dlp güncelleniyor…")
        def w():
            p = run([YTDLP, "-U"], timeout=180)
            out = (p.stdout + p.stderr).strip().splitlines()
            self.ui(self.l_upd.config, {"text": "yt-dlp: " + (out[-1] if out else "bitti")})
            self.refresh_versions()
        threading.Thread(target=w, daemon=True).start()

    def check_update(self, manual=False):
        def w():
            try:
                m = fetch_manifest()
            except Exception as e:
                self.ui(self.l_upd.config, {"text": f"Güncelleme denetlenemedi ({type(e).__name__}). Henüz yayınlanmış sürüm olmayabilir."})
                if manual: self.ui(messagebox.showinfo, APP, "Güncelleme bilgisi alınamadı. Henüz yayınlanmış sürüm yok ya da bağlantı yok.")
                return
            ver = m.get("version", "0")
            if vtuple(ver) <= vtuple(VERSION):
                self.ui(self.l_upd.config, {"text": f"Güncelsin (son sürüm {ver})."})
                if manual: self.ui(messagebox.showinfo, APP, f"En güncel sürümü kullanıyorsun ({VERSION}).")
                return
            self.ui(self.ask_update, m)
        self.l_upd.config(text="Güncelleme denetleniyor…")
        threading.Thread(target=w, daemon=True).start()

    def ask_update(self, m):
        notes = m.get("notes", "")
        self.l_upd.config(text=f"Yeni sürüm var: {m.get('version')}")
        if not os.environ.get("FBD_TEST_AUTOACCEPT") and not messagebox.askyesno(APP, f"Yeni sürüm var: {m.get('version')} (sende {VERSION})\n\n{notes}\n\nŞimdi güncellensin mi? Program kapanıp yeni sürümle açılacak."):
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(APP, "Kaynak koddan çalışırken güncelleme kurulmaz."); return
        sha = str(m.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            messagebox.showerror(APP, "Güncelleme bilgisi geçersiz (SHA256 yok)."); return
        def w():
            try:
                dst = os.path.join(os.path.dirname(sys.executable), f".fastByDownload-yeni-{os.getpid()}.exe")
                try: open(dst, "wb").close()
                except OSError: dst = os.path.join(tempfile.gettempdir(), f"fastByDownload-yeni-{os.getpid()}.exe")
                got = download_file(m["url"], dst, lambda f: self.ui(self.l_upd.config, {"text": f"İndiriliyor… %{int(f*100)}"}))
                if got != sha:
                    os.remove(dst); self.ui(messagebox.showerror, APP, "İndirilen güncelleme doğrulanamadı (SHA256 uyuşmuyor)."); return
                install_and_restart(dst, sha)
                self.ui(self.destroy)
            except Exception as e:
                self.ui(messagebox.showerror, APP, f"Güncelleme başarısız: {e}")
        threading.Thread(target=w, daemon=True).start()

    def on_close(self):
        if self.proc and not messagebox.askyesno(APP, "İndirme sürüyor. Kapatılsın mı?"): return
        self.cancel(); self.save_settings(); self.destroy()

def selftest():
    """--selftest URL KIND QUALITY OUTDIR : arayuzsuz indirme (CI testi icin)"""
    prepare_bin()
    app = App(); app.withdraw()
    u, kind, q, out = sys.argv[2:6]
    app.kind.set(kind); app.kind_changed(); app.quality.set(q)
    p = run(app.build_args(u, out), timeout=900)
    print(p.stdout[-3000:], p.stderr[-2000:])
    files = [l[5:] for l in p.stdout.splitlines() if l.startswith("FBDF|")]
    app.history.insert(0, {"tarih": time.strftime("%Y-%m-%d %H:%M"), "tur": "MP3" if kind == "audio" else "MP4", "kalite": q, "baslik": "selftest", "url": u, "dosya": files[-1] if files else ""})
    save_json(HIST, app.history)
    print("FILES", files); sys.exit(0 if p.returncode == 0 and files and os.path.exists(files[-1]) else 1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--version": print(VERSION); sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest": selftest()
    a = App()
    if len(sys.argv) > 1 and re.match(r"https?://", sys.argv[1]): a.url.set(sys.argv[1]); a.after(300, a.preview)
    a.mainloop()
