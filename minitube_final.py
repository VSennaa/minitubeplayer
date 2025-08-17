import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, BooleanVar
import subprocess
import json
import threading
import os
import sys
import platform
import vlc
import ctypes

def resource_path(relative_path):
    try: base_path = sys._MEIPASS
    except Exception: base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def format_time(ms):
    if ms is None or ms < 0: return "--:--"
    total_seconds = int(ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

def is_admin():
    """Verifica se o script está rodando com privilégios de administrador no Windows."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

COOKIES_FILE = "youtube-cookies.txt"
NAVEGADOR_PARA_COOKIES = "chrome"

class MiniTubeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MiniTube Player")
        self.root.geometry("800x680")
        self.root.resizable(False, False)

        self.data_list = []
        self.current_process = None
        self.is_cancelled = False
        self.current_video_url = None
        
        self.vlc_instance = vlc.Instance("--vout=windib", "--avcodec-hw=none")
        self.player = self.vlc_instance.media_player_new()

        # --- Frames da Interface ---
        top_frame = tk.Frame(root); top_frame.pack(pady=5, padx=10, fill=tk.X)
        search_frame = tk.LabelFrame(top_frame, text="Busca"); search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        feed_frame = tk.LabelFrame(top_frame, text="Pessoal"); feed_frame.pack(side=tk.LEFT, padx=10)
        
        # --- Busca ---
        self.search_entry = tk.Entry(search_frame, width=45); self.search_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)
        self.search_entry.bind("<Return>", self.start_search)
        self.search_button = tk.Button(search_frame, text="Buscar", command=self.start_search); self.search_button.pack(side=tk.LEFT, padx=5)
        self.cancel_button = tk.Button(search_frame, text="Cancelar", command=self.cancel_operation, state=tk.DISABLED); self.cancel_button.pack(side=tk.LEFT, padx=5)

        # --- Feed ---
        self.load_feed_button = tk.Button(feed_frame, text="Carregar Feed", command=self.load_subscription_feed); self.load_feed_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # --- Player de Vídeo e Controles ---
        self.video_frame = tk.Frame(root, bg='black'); self.video_frame.pack(pady=5, padx=10, expand=True, fill=tk.BOTH)
        self.controls_frame = tk.Frame(root); self.controls_frame.pack(pady=5, padx=10, fill=tk.X)
        self.play_pause_button = tk.Button(self.controls_frame, text="▶ Play", width=10, command=self._toggle_play_pause); self.play_pause_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = tk.Button(self.controls_frame, text="■ Stop", width=10, command=self.stop_player); self.stop_button.pack(side=tk.LEFT)
        self.toggle_video_button = tk.Button(self.controls_frame, text="Ocultar Vídeo", width=12, command=self._toggle_video_visibility); self.toggle_video_button.pack(side=tk.LEFT, padx=5)
        self.time_label = tk.Label(self.controls_frame, text="--:-- / --:--", width=15); self.time_label.pack(side=tk.LEFT, padx=5)
        self.progress_slider = ttk.Scale(self.controls_frame, from_=0, to=1000, orient=tk.HORIZONTAL, command=self._on_seek_drag); self.progress_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_slider.bind("<ButtonRelease-1>", self._on_seek)
        self.volume_label = tk.Label(self.controls_frame, text="🔊"); self.volume_label.pack(side=tk.LEFT, padx=(10, 0))
        self.volume_slider = ttk.Scale(self.controls_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self._set_volume); self.volume_slider.pack(side=tk.LEFT, padx=5)
        self.volume_slider.set(100)
        self.results_listbox = tk.Listbox(root, selectmode=tk.SINGLE, font=("TkDefaultFont", 9), height=10); self.results_listbox.pack(pady=5, padx=10, fill=tk.X)
        self.results_listbox.bind("<Double-Button-1>", lambda e: self.launch_player())
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.update_job = None
        self._set_player_controls_state(tk.DISABLED)
        
    def _set_player_controls_state(self, state):
        self.play_pause_button.config(state=state); self.stop_button.config(state=state); self.toggle_video_button.config(state=state)
        slider_state = "normal" if state == tk.NORMAL else "disabled"; self.progress_slider.config(state=slider_state)
    def _on_closing(self):
        if self.player: self.player.stop(); self.player.release()
        if self.update_job: self.root.after_cancel(self.update_job); self.update_job = None
        self.root.destroy()
    def _toggle_play_pause(self):
        if self.player.is_playing(): self.player.pause(); self.play_pause_button.config(text="▶ Play")
        else: self.player.play(); self.play_pause_button.config(text="❚❚ Pause")
    def stop_player(self):
        if self.player: self.player.stop()
        self.play_pause_button.config(text="▶ Play"); self.time_label.config(text="--:-- / --:--")
        self.progress_slider.set(0); self.current_video_url = None; self._set_player_controls_state(tk.DISABLED)
        if self.update_job: self.root.after_cancel(self.update_job); self.update_job = None
    def _toggle_video_visibility(self):
        if not self.player.get_media(): return
        if self.video_frame.winfo_ismapped():
            self.video_frame.pack_forget(); self.toggle_video_button.config(text="Mostrar Vídeo")
        else:
            self.video_frame.pack(pady=5, padx=10, expand=True, fill=tk.BOTH, before=self.controls_frame); self.toggle_video_button.config(text="Ocultar Vídeo")
    def _on_seek(self, event):
        if self.player.get_media(): self.player.set_position(self.progress_slider.get() / 1000)
    def _on_seek_drag(self, value):
        if self.player.get_media():
            duration = self.player.get_length(); seek_time = int(duration * (float(value) / 1000))
            self.time_label.config(text=f"{format_time(seek_time)} / {format_time(duration)}")
    def _set_volume(self, value): self.player.audio_set_volume(int(float(value)))
    def _update_player_ui(self):
        if not self.player.get_media() or (not self.player.is_playing() and self.player.get_state() != vlc.State.Paused):
            self.stop_player(); return
        duration_ms, current_ms = self.player.get_length(), self.player.get_time()
        self.time_label.config(text=f"{format_time(current_ms)} / {format_time(duration_ms)}")
        if self.progress_slider.cget('state') != 'disabled' and self.progress_slider.bind("<B1-Motion>"):
            self.progress_slider.set(int(self.player.get_position() * 1000))
        self.update_job = self.root.after(500, self._update_player_ui)
    def launch_player(self):
        selected_indices = self.results_listbox.curselection()
        if not selected_indices or selected_indices[0] == 0: return
        item_info = self.data_list[selected_indices[0] - 1]
        self.stop_player(); self.time_label.config(text="Carregando...")
        if not self.video_frame.winfo_ismapped():
            self.video_frame.pack(pady=5, padx=10, expand=True, fill=tk.BOTH, before=self.controls_frame)
        self.toggle_video_button.config(text="Ocultar Vídeo")
        self.current_video_url = item_info.get('webpage_url') or item_info.get('url')
        threading.Thread(target=self._get_stream_and_play, args=(self.current_video_url,), daemon=True).start()
    def _get_stream_and_play(self, url):
        try:
            command = [sys.executable, '-m', 'yt_dlp', '--no-config', '--no-playlist', '-f', 'b', '-g', url]
            startupinfo = None
            if os.name == 'nt': startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startupinfo.wShowWindow = subprocess.SW_HIDE
            stream_url = subprocess.check_output(command, text=True, encoding='utf-8', startupinfo=startupinfo).strip().split('\n')[0]
            if not stream_url: self.root.after(0, self.stop_player); self.root.after(0, messagebox.showerror, ("Erro", "Não foi possível obter a URL.")); return
            media = self.vlc_instance.media_new(stream_url)
            self.player.set_media(media); self.player.audio_set_mute(0); self.player.audio_set_volume(int(self.volume_slider.get()))
            if platform.system() == "Windows": self.player.set_hwnd(self.video_frame.winfo_id())
            else: self.player.set_xwindow(self.video_frame.winfo_id())
            self.player.play()
            self.root.after(0, self._set_player_controls_state, tk.NORMAL)
            self.root.after(100, self.play_pause_button.config, {'text': "❚❚ Pause"})
            if self.update_job: self.root.after_cancel(self.update_job)
            self.root.after(500, self._update_player_ui)
        except Exception as e:
            self.root.after(0, self.stop_player)
            self.root.after(0, messagebox.showerror, ("Erro de Reprodução", f"Não foi possível iniciar o player:\n{e}"))

    def _update_ui_before_fetching(self, message="Buscando..."):
        self.is_cancelled=False; self.search_button.config(state=tk.DISABLED); self.load_feed_button.config(state=tk.DISABLED); self.cancel_button.config(state=tk.NORMAL); self.results_listbox.delete(0, tk.END); self.results_listbox.insert(tk.END, f"{message}, aguarde...")
    def _update_ui_after_fetching(self):
        self.search_button.config(state=tk.NORMAL); self.load_feed_button.config(state=tk.NORMAL); self.cancel_button.config(state=tk.DISABLED); self.current_process=None
    def cancel_operation(self):
        self.is_cancelled=True
        if self.current_process:
            try: self.current_process.kill()
            except: pass
        self._update_ui_after_fetching(); self.results_listbox.delete(0, tk.END); self.results_listbox.insert(tk.END, "--- Operação cancelada ---")
    
    def start_search(self, event=None):
        query = self.search_entry.get();
        if not query: return
        self._update_ui_before_fetching(f"Buscando vídeos para: '{query}'")
        base_command = [sys.executable, '-m', 'yt_dlp', '--dump-json']
        command = base_command + ['--flat-playlist', f"ytsearch15:{query}"]
        source_name = f"Vídeos: '{query}'"
        threading.Thread(target=self._fetch_and_display_data, args=(command, source_name), daemon=True).start()

    # LÓGICA DO FEED ATUALIZADA E MAIS INTELIGENTE
    def load_subscription_feed(self):
        self._update_ui_before_fetching("Tentando carregar feed do navegador...")
        threading.Thread(target=self._fetch_feed_with_fallback, daemon=True).start()

    def _fetch_feed_with_fallback(self):
        # TENTATIVA 1: NAVEGADOR (com verificação de Admin)
        if is_admin():
            messagebox.showwarning("Modo Administrador", "A busca no navegador foi pulada porque o programa está rodando como Administrador, o que impede a leitura de cookies.\n\nTentando com o arquivo de cookies local.")
        else:
            try:
                command_browser = [sys.executable, '-m', 'yt_dlp', '--cookies-from-browser', NAVEGADOR_PARA_COOKIES, '--dump-json', '--flat-playlist', '--playlist-items', '30', 'https://www.youtube.com/feed/subscriptions']
                # Esta função já tem timeout, então a usamos diretamente
                self._fetch_and_display_data(command_browser, "Feed do Navegador")
                return # Se funcionou, termina aqui
            except Exception as e:
                print(f"Busca no navegador falhou: {e}")
        
        # TENTATIVA 2: ARQUIVO LOCAL
        self.root.after(0, self._update_ui_before_fetching, "Tentando com arquivo de cookies local...")
        if not os.path.exists(COOKIES_FILE):
            self.root.after(0, self.update_ui_on_error, f"FALLBACK FALHOU: Arquivo '{COOKIES_FILE}' não encontrado.")
            return
        command_file = [sys.executable, '-m', 'yt_dlp', '--cookies', COOKIES_FILE, '--dump-json', '--flat-playlist', '--playlist-items', '30', 'https://www.youtube.com/feed/subscriptions']
        self._fetch_and_display_data(command_file, "Feed (Arquivo Local)")

    def _fetch_and_display_data(self, command, source_name):
        try:
            startupinfo = None
            if os.name == 'nt': startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.current_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=startupinfo)
            stdout, stderr = self.current_process.communicate(timeout=30)
            
            if self.is_cancelled: return
            if self.current_process.returncode != 0: self.root.after(0, self.update_ui_on_error, f"Erro ao buscar '{source_name}':\n{stderr}"); return
            
            self.data_list = []
            for line in stdout.strip().split('\n'):
                if not line: continue
                try: 
                    item_info = json.loads(line)
                    self.data_list.append(item_info)
                except json.JSONDecodeError: pass
            
            self.root.after(0, self._display_current_data, source_name)
        except subprocess.TimeoutExpired:
            self.current_process.kill()
            error_message = f"A busca por '{source_name}' demorou mais de 30 segundos e foi cancelada."
            self.root.after(0, self.update_ui_on_error, error_message)
        except Exception as e:
            if not self.is_cancelled: self.root.after(0, self.update_ui_on_error, f"Ocorreu um erro inesperado: {e}")
        finally:
            self.current_process=None
            if not self.is_cancelled: self.root.after(0, self._update_ui_after_fetching)

    def _display_current_data(self, source_name):
        self.results_listbox.delete(0, tk.END)
        if not self.data_list: self.results_listbox.insert(tk.END, f"Nenhum resultado para '{source_name}'."); 
        else:
            self.results_listbox.insert(tk.END, f"--- Resultados de: {source_name} ---")
            for item in self.data_list:
                duration = item.get('duration') # Duração em segundos (pode ser None)
                title = item.get('title', 'N/D')
                uploader = item.get('uploader', 'N/D')
                display_text = f"[{format_time(duration * 1000 if duration else -1)}] {title}"
                if uploader != 'N/D':
                    display_text += f" - ({uploader})"
                self.results_listbox.insert(tk.END, display_text)
        
    def update_ui_on_error(self, error_message):
        messagebox.showerror("Erro", error_message); self.results_listbox.delete(0, tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = MiniTubeApp(root)
    root.mainloop()