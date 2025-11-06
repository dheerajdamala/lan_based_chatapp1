import socket
import threading
import tkinter as tk
from tkinter import scrolledtext, simpledialog, messagebox, filedialog, ttk, Toplevel, PanedWindow, Label, Frame, Menu
import os
import struct
import time
import queue
import wave
import platform
import subprocess
import configparser
import re # For formatting
import math # Added for grid calculations

# --- Third-party libraries ---
try:
    import cv2
    import numpy as np
    import pyaudio
    import mss
    import mss.tools
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    import fitz  # PyMuPDF
except ImportError:
    print("Error: Required libraries not found.")
    print("Please run: pip install opencv-python numpy pyaudio mss pillow PyMuPDF")
    fitz = None
    exit()

# --- Configuration ---
config = configparser.ConfigParser()
try:
    config.read('config.ini')
    DISCOVERY_PORT = config.getint('Network', 'DiscoveryPort', fallback=9089)
    CHAT_PORT = config.getint('Network', 'ChatPort', fallback=9090)
    AUDIO_PORT = config.getint('Network', 'AudioPort', fallback=9091)
    VIDEO_PORT = config.getint('Network', 'VideoPort', fallback=9092)
    SCREEN_PORT = config.getint('Network', 'ScreenPort', fallback=9093)
    FILE_PORT = config.getint('Network', 'FilePort', fallback=9094)
    DOWNLOAD_DIR = config.get('Client', 'DownloadDirectory', fallback='client_downloads')
except Exception as e:
    print(f"Error reading config.ini: {e}. Using default values.")
    DISCOVERY_PORT = 9089
    CHAT_PORT = 9090
    AUDIO_PORT = 9091
    VIDEO_PORT = 9092
    SCREEN_PORT = 9093
    FILE_PORT = 9094
    DOWNLOAD_DIR = 'client_downloads'

# --- Global Config & Setup ---
DISCOVERY_REQUEST = b'SERVER_DISCOVERY_REQUEST'
if not os.path.exists(DOWNLOAD_DIR):
    try:
        os.makedirs(DOWNLOAD_DIR)
    except Exception as e:
        print(f"Error creating download directory '{DOWNLOAD_DIR}': {e}")
        DOWNLOAD_DIR = '.' # Fallback

running = True
SERVER_HOST = None

# --- Common UI elements and colors ---
PRIMARY_BG = "#2B2B2B"
SIDEBAR_BG = "#3C3C3C"
CHAT_HEADER_BG = "#3C3C3C"
CHAT_AREA_BG = "#2B2B2B"
CHAT_INPUT_BG = "#3C3C3C"
TEXT_COLOR = "#E0E0E0"
ACCENT_COLOR = "#00A859"
BUTTON_RED = "#D9534F"
BUTTON_RED_ACTIVE = "#C9302C"

# Message Colors
MESSAGE_MY_BG = "#00572C"
MESSAGE_REMOTE_BG = "#3C3C3C"
MESSAGE_PM_BG = "#2A4B3A"
MESSAGE_MY_PM_BG = "#00572C"
MESSAGE_SYS_FG = "#AAAAAA"
USER_STATUS_AWAY_FG = "#AAAAAA"

# --- Image Assets ---
def create_icon_image(size, color, shape='circle', text_label='', fill=True, bg_color=None):
    if bg_color is None:
        img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    else:
        img = Image.new('RGB', (size, size), bg_color)
    draw = ImageDraw.Draw(img)
    if shape == 'circle':
        if fill: draw.ellipse((0, 0, size-1, size-1), fill=color)
        else: draw.ellipse((0, 0, size-1, size-1), outline=color, width=2)
    elif shape == 'square':
        radius = size // 10
        if fill: draw.rounded_rectangle((0, 0, size-1, size-1), radius=radius, fill=color)
        else: draw.rounded_rectangle((0, 0, size-1, size-1), radius=radius, outline=color, width=2)
    if text_label:
        try:
            try: font = ImageFont.truetype("Arial.ttf", int(size * 0.4))
            except IOError: font = ImageFont.truetype("DejaVuSans.ttf", int(size * 0.4))
        except IOError: font = ImageFont.load_default()
        text_bbox = draw.textbbox((0, 0), text_label, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        draw.text(((size - text_width) / 2, (size - text_height) / 2 - (size*0.05)),
                  text_label, fill="white", font=font)
    return ImageTk.PhotoImage(img)

PROFILE_PIC_DEFAULT = None
APP_ICON_DEFAULT = None


# --- TextViewer Class ---
class TextViewer(Toplevel):
    def __init__(self, master, filepath):
        super().__init__(master)
        self.title(os.path.basename(filepath))
        self.geometry("700x800")
        self.configure(bg=PRIMARY_BG)
        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, state='normal',
                                                   bg=CHAT_AREA_BG, fg=TEXT_COLOR,
                                                   insertbackground=TEXT_COLOR, bd=0, relief="flat", padx=10, pady=10,
                                                   highlightthickness=0)
        self.text_area.pack(fill=tk.BOTH, expand=True)
        try:
            with open(filepath, 'r', encoding='utf-8') as f: content = f.read()
            self.text_area.insert(tk.END, content)
        except UnicodeDecodeError: self.text_area.insert(tk.END, f"--- Cannot display file: Not a valid text file ---")
        except Exception as e: self.text_area.insert(tk.END, f"--- Error opening file: {e} ---")
        self.text_area.config(state='disabled')


# --- PDFViewer Class ---
class PDFViewer(Toplevel):
    def __init__(self, master, filepath):
        super().__init__(master)
        self.title(os.path.basename(filepath))
        self.geometry("800x900")
        self.configure(bg=PRIMARY_BG)
        self.filepath = filepath
        self.pdf_doc = None
        self.current_page = 0
        self.total_pages = 0
        try:
            self.pdf_doc = fitz.open(filepath)
            self.total_pages = len(self.pdf_doc)
        except Exception as e:
            messagebox.showerror("PDF Error", f"Failed to open PDF file:\n{e}", parent=master)
            self.destroy(); return
        control_frame = Frame(self, bg=SIDEBAR_BG); control_frame.pack(fill=tk.X)
        self.prev_button = ttk.Button(control_frame, text="< Prev", command=self.prev_page)
        self.prev_button.pack(side=tk.LEFT, padx=10, pady=5)
        self.page_label = tk.Label(control_frame, text=f"Page 1 of {self.total_pages}", bg=SIDEBAR_BG, fg=TEXT_COLOR)
        self.page_label.pack(side=tk.LEFT, expand=True)
        self.next_button = ttk.Button(control_frame, text="Next >", command=self.next_page)
        self.next_button.pack(side=tk.RIGHT, padx=10, pady=5)
        self.page_display_label = tk.Label(self, bg=PRIMARY_BG)
        self.page_display_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.render_page(self.current_page)
    def render_page(self, page_num):
        if not (0 <= page_num < self.total_pages): return
        self.current_page = page_num
        try:
            page = self.pdf_doc.load_page(self.current_page)
            zoom = 2.0; mat = fitz.Matrix(zoom, zoom); pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            win_w = 780; win_h = 850
            if img.width > win_w or img.height > win_h: img.thumbnail((win_w, win_h), Image.LANCZOS)
            img_tk = ImageTk.PhotoImage(img)
            self.page_display_label.config(image=img_tk); self.page_display_label.image = img_tk
            self.page_label.config(text=f"Page {self.current_page + 1} of {self.total_pages}")
            self.prev_button.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
            self.next_button.config(state=tk.NORMAL if self.current_page < self.total_pages - 1 else tk.DISABLED)
        except Exception as e:
            print(f"Error rendering PDF page: {e}"); self.page_display_label.config(text=f"Error rendering page: {e}", image=None)
    def next_page(self): self.render_page(self.current_page + 1)
    def prev_page(self): self.render_page(self.current_page - 1)
    def on_close(self):
        if self.pdf_doc: self.pdf_doc.close()
        self.destroy()


# --- Audio Recorder Class ---
class AudioRecorder:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.FORMAT = pyaudio.paInt16; self.CHANNELS = 1; self.RATE = 44100; self.CHUNK = 1024
        self.stream = None; self.frames = []; self._is_recording = False
    def start_recording(self):
        try:
            self.frames = []
            self.stream = self.p.open(format=self.FORMAT, channels=self.CHANNELS, rate=self.RATE,
                                      input=True, frames_per_buffer=self.CHUNK)
            self._is_recording = True
            threading.Thread(target=self._record_loop, daemon=True).start()
            return True
        except Exception as e:
            print(f"[AUDIO RECORDER] Error: {e}")
            messagebox.showerror("Audio Error", f"Could not start recording.\n{e}")
            return False
    def _record_loop(self):
        while self._is_recording:
            try: data = self.stream.read(self.CHUNK, exception_on_overflow=False); self.frames.append(data)
            except IOError: pass
    def stop_recording(self, output_filename):
        if not self._is_recording: return
        self._is_recording = False
        try:
            if self.stream: self.stream.stop_stream(); self.stream.close()
        except Exception as e: print(f"[AUDIO RECORDER] Stream close error: {e}")
        if not self.frames: print("[AUDIO RECORDER] No frames recorded."); return
        try:
            wf = wave.open(output_filename, 'wb')
            wf.setnchannels(self.CHANNELS); wf.setsampwidth(self.p.get_sample_size(self.FORMAT))
            wf.setframerate(self.RATE); wf.writeframes(b''.join(self.frames)); wf.close()
            print(f"[AUDIO RECORDER] Saved to {output_filename}")
        except Exception as e: print(f"Error saving wave file: {e}")
    def __del__(self):
        try:
            if self.p: self.p.terminate()
        except Exception as e: print(f"Error terminating PyAudio: {e}")


# --- AudioPlayer Class (NEW & FIXED) ---
class AudioPlayer:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = None # The *currently active* stream
        self._lock = threading.Lock() # Serialize play/stop to avoid device churn

    def play_file(self, filepath):
        # Ensure only one play attempt at a time
        with self._lock:
            if not os.path.exists(filepath):
                print(f"Cannot play: File not found at {filepath}")
                messagebox.showerror("Audio Error", "File not found. It may need to be downloaded first.")
                return

            try:
                wf = wave.open(filepath, 'rb')
            except Exception as e:
                print(f"Error opening wave file: {e}")
                messagebox.showerror("Audio Error", f"Could not open audio file:\n{e}")
                return

            # Stop any currently playing stream safely (under the same lock)
            self._unsafe_stop()
            # Short delay to let device settle on some systems (prevents rare crashes)
            time.sleep(0.05)

            local_stream = None # Create a local var for the new stream
            try:
                local_stream = self.p.open(format=self.p.get_format_from_width(wf.getsampwidth()),
                                          channels=wf.getnchannels(),
                                          rate=wf.getframerate(),
                                          output=True)
                self.stream = local_stream # Now assign it to the class
            except Exception as e:
                print(f"Error opening audio stream: {e}")
                messagebox.showerror("Audio Error", f"Could not open audio stream:\n{e}")
                if local_stream: local_stream.close() # Clean up if it opened but failed
                return

            # Run playback in a thread, passing the *specific stream instance*
            print(f"Starting playback of {filepath}")
            threading.Thread(target=self._play_loop, args=(wf, local_stream), daemon=True).start()

    def _play_loop(self, wf, stream_instance):
        try:
            data = wf.readframes(1024)
            # Check the local stream instance's status
            while data and stream_instance.is_active():
                stream_instance.write(data)
                data = wf.readframes(1024)
        except IOError as e:
            if e.errno == -9983 or 'Stream is stopped' in str(e): # Handle stream stopped error
                print("Playback interrupted.")
            else:
                print(f"Error during audio playback (IOError): {e}")
        except Exception as e:
            print(f"Error during audio playback (Exception): {e}")
        finally:
            try:
                if stream_instance:
                    stream_instance.stop_stream()
                    stream_instance.close()
            except Exception:
                pass # Errors on close are common and usually fine
            wf.close()
            print("Playback finished.")

    def stop_playback(self):
        # Public safe stop
        with self._lock:
            self._unsafe_stop()

    def _unsafe_stop(self):
        # Internal stop that assumes caller holds _lock
        try:
            if self.stream:
                try:
                    self.stream.stop_stream()
                finally:
                    self.stream.close()
            self.stream = None
        except Exception as e:
            print(f"Error stopping playback stream: {e}")

    def __del__(self):
        try:
            self.stop_playback()
            if self.p:
                self.p.terminate()
        except Exception as e:
            print(f"Error terminating AudioPlayer: {e}")


# --- ChatWindow Class ---
class ChatWindow(Toplevel):
    # --- MODIFIED: Added main_app parameter ---
    def __init__(self, master, target_name, main_chat_client, main_app_instance):
        super().__init__(master)
        self.target_name = target_name
        self.main_chat_client = main_chat_client
        self.main_app = main_app_instance # Store reference to MainApplication
        self.log_lock = threading.Lock()
        safe_target_name = "".join(c if c.isalnum() else "_" for c in target_name)
        self.log_file = os.path.join(DOWNLOAD_DIR, f"chat_log_{self.main_chat_client.username}_{safe_target_name}.txt")

        # --- NEW: Audio properties ---
        self.audio_recorder = None
        self.audio_player = AudioPlayer()
        self.is_recording = False

        if target_name == "PUBLIC CHAT": self.title("Public Chat")
        else: self.title(f"Chat with {target_name}")
        self.geometry("500x600")
        self.configure(bg=PRIMARY_BG)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.chat_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, state='disabled',
                                                   bg=CHAT_AREA_BG, fg=TEXT_COLOR,
                                                   insertbackground=TEXT_COLOR, bd=0, relief="flat", padx=10, pady=10,
                                                   highlightthickness=0)
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # --- MODIFIED: Input frame with Emoji and Voice buttons ---
        input_frame = Frame(self, bg=CHAT_INPUT_BG, bd=1, relief="solid")
        input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Emoji Button
        self.emoji_button = tk.Button(input_frame, text="😀", command=self.open_emoji_picker,
                                      bg=CHAT_INPUT_BG, fg=ACCENT_COLOR, activebackground=CHAT_INPUT_BG, relief="flat", bd=0,
                                      highlightthickness=0, activeforeground=ACCENT_COLOR, width=2, font=("Arial", 10))
        self.emoji_button.pack(pady=5, padx=5, side=tk.LEFT)

        # Message Entry
        self.msg_entry = tk.Entry(input_frame, bg=CHAT_INPUT_BG, fg=TEXT_COLOR,
                                  insertbackground=TEXT_COLOR, relief="flat", bd=0)
        self.msg_entry.pack(padx=5, pady=10, fill=tk.X, side=tk.LEFT, expand=True)
        self.msg_entry.bind("<Return>", self.send_message)

        # Voice Record Button
        self.voice_button = tk.Button(input_frame, text="🎤", command=self.toggle_voice_record,
                                      bg=CHAT_INPUT_BG, fg=ACCENT_COLOR, activebackground=CHAT_INPUT_BG, relief="flat", bd=0,
                                      highlightthickness=0, activeforeground=ACCENT_COLOR, width=2, font=("Arial", 10))
        self.voice_button.pack(pady=5, padx=5, side=tk.LEFT)

        # Send Button
        self.send_button = tk.Button(input_frame, text="Send", command=self.send_message,
                                      bg=CHAT_INPUT_BG, fg=ACCENT_COLOR, activebackground=CHAT_INPUT_BG, relief="flat", bd=0,
                                      highlightthickness=0, activeforeground=ACCENT_COLOR)
        self.send_button.pack(pady=5, padx=5, side=tk.RIGHT)
        # --- End of modified input frame ---

        # Tags for message styling
        self.chat_area.tag_config("my_message", foreground="white", background=MESSAGE_MY_BG, justify='right', lmargin1=100, lmargin2=100, rmargin=10)
        self.chat_area.tag_config("remote_message", foreground=TEXT_COLOR, background=MESSAGE_REMOTE_BG, justify='left', lmargin1=10, lmargin2=10, rmargin=100)
        self.chat_area.tag_config("system_message", foreground=MESSAGE_SYS_FG, justify='center')
        self.chat_area.tag_config("pm_message", foreground=TEXT_COLOR, background=MESSAGE_PM_BG, justify='left', lmargin1=10, lmargin2=10, rmargin=100)
        self.chat_area.tag_config("my_pm_message", foreground="white", background=MESSAGE_MY_PM_BG, justify='right', lmargin1=100, lmargin2=100, rmargin=10)
        # Tags for formatting
        self.chat_area.tag_config("bold_tag", font=('Arial', 10, 'bold'))
        self.chat_area.tag_config("italic_tag", font=('Arial', 10, 'italic'))

        self.load_history()
        session_msg = f"--- Chat Opened {time.strftime('%Y-%m-%d %H:%M:%S')} ---"
        self.add_message(session_msg, "system_message", log=False) # No timestamp for session open

        self.main_chat_client.register_chat_window(self.target_name, self)

    def load_history(self):
        if not os.path.exists(self.log_file): return
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    tag = "remote_message" # Default
                    # Simple heuristic based on known prefixes
                    if line.startswith(("[SYSTEM]", "--- Chat Opened", "--- Previous History")): tag = "system_message"
                    elif line.startswith(f"You:") and self.target_name == "PUBLIC CHAT": tag = "my_message"
                    elif line.startswith(f"You [to"): tag = "my_pm_message"
                    elif line.startswith(f"{self.target_name}:") and self.target_name != "PUBLIC CHAT": tag = "pm_message"
                    elif ":" in line and self.target_name == "PUBLIC CHAT":
                        # Check public messages carefully, considering potential timestamps
                        sender_part = line.split(":", 1)[0]
                        potential_sender = sender_part
                        if len(sender_part) > 9 and sender_part[2] == ':' and sender_part[5] == ':': # Looks like HH:MM:SS User
                            potential_sender = sender_part.split(" ", 1)[1]
                        if potential_sender == self.main_chat_client.username: tag = "my_message"
                    self.add_message(line, tag=tag, log=False) # Add history line without re-logging
            self.add_message("--- Previous History Loaded ---", "system_message", log=False) # No timestamp
        except Exception as e:
            print(f"Error loading chat history for {self.target_name}: {e}")
            self.add_message(f"[SYSTEM] Error loading history: {e}", "system_message", log=False)

    def log_message(self, message):
        with self.log_lock:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f: f.write(message + '\n')
            except Exception as e: print(f"Error logging message for {self.target_name}: {e}")

    def add_message(self, message, tag=None, log=True):
        if not self.winfo_exists(): return

        # --- NEW: Check for Voice Message ---
        if "VOICE_MSG::" in message:
            try:
                # Extract sender and filename
                # Format: "HH:MM:SS Sender: VOICE_MSG::filename.wav"
                # Or: "You [to ...]: VOICE_MSG::filename.wav"
                prefix, filename = message.split("VOICE_MSG::", 1)
                filename = filename.strip() # Clean up filename

                self.chat_area.config(state='normal')

                # Determine background color for the button frame
                frame_bg = MESSAGE_REMOTE_BG
                if tag == "my_message": frame_bg = MESSAGE_MY_BG
                elif tag == "pm_message": frame_bg = MESSAGE_PM_BG
                elif tag == "my_pm_message": frame_bg = MESSAGE_MY_PM_BG

                # Add the prefix (like "HH:MM:SS Sender: ")
                self.chat_area.insert(tk.END, prefix.strip() + " ", tag)

                # Create the voice player widget
                play_frame = Frame(self.chat_area, bg=frame_bg)
                play_button = tk.Button(play_frame, text=f"▶ Play Voice Message",
                                        command=lambda f=filename: self.play_voice_message(f),
                                        bg="#555", fg="white", relief="flat", padx=10, pady=5, font=("Arial", 9))
                play_button.pack(pady=2)

                # Insert the widget into the text area
                self.chat_area.window_create(tk.END, window=play_frame, padx=5)
                self.chat_area.insert(tk.END, '\n\n', tag) # Add newline after

                self.chat_area.config(state='disabled')
                self.chat_area.yview(tk.END)
                if log: self.log_message(message) # Log the raw voice message link
                return # Skip the rest of the function
            except Exception as e:
                print(f"Error processing voice message widget: {e}")
                # Fallback to just printing the raw message

        # --- Original add_message logic continues below ---

        try:
            # Check if message *already* has a timestamp (from server or log file)
            has_timestamp = len(message) > 9 and message[2] == ':' and message[5] == ':' and message[8] == ' '

            # If logging locally (e.g., sending msg or local system msg), prepend timestamp if needed
            if log and not has_timestamp:
                 timestamp = time.strftime('%H:%M:%S')
                 # --- MOD: Add prefix for local echo ---
                 prefix = ""
                 if tag == "my_message": prefix = "You: "
                 elif tag == "my_pm_message": prefix = f"You [to {self.target_name}]: "
                 elif tag == "system_message": prefix = "[SYSTEM] "

                 log_message_content = f"{timestamp} {prefix}{message}"
                 self.log_message(log_message_content) # Log the timestamped version
                 display_message = log_message_content # Display timestamped version
            else:
                 display_message = message # Use original for display (already has timestamp or is history/sys msg)
                 if log: self.log_message(display_message) # Log messages that already have timestamps

            self.chat_area.config(state='normal')
            start_index = self.chat_area.index(tk.END + "-1c") # Index before insertion

            # Insert the message content
            self.chat_area.insert(tk.END, display_message + '\n', tag)

            # --- Apply Formatting ---
            # Apply bold (*text*) - Look within the display_message part
            for match in re.finditer(r'\*(.*?)\*', display_message):
                # Adjust indices relative to the start of the inserted text
                self.chat_area.tag_add("bold_tag", f"{start_index}+{match.start(1)}c", f"{start_index}+{match.end(1)}c")
            # Apply italic (_text_)
            for match in re.finditer(r'\_(.*?)\_', display_message):
                self.chat_area.tag_add("italic_tag", f"{start_index}+{match.start(1)}c", f"{start_index}+{match.end(1)}c")

            self.chat_area.config(state='disabled')
            self.chat_area.yview(tk.END)

        except tk.TclError: pass
        except Exception as e: print(f"Error adding message to window {self.target_name}: {e}")

    def send_message(self, event=None):
        # --- NEW: Check if recording ---
        if self.is_recording:
            messagebox.showwarning("Recording", "Please stop recording before sending a text message.", parent=self)
            return

        message = self.msg_entry.get().strip()
        if not message: return
        success = self.main_chat_client.send_actual_message(self.target_name, message)
        if success: self.msg_entry.delete(0, tk.END)

    def on_closing(self):
        # --- NEW: Stop any audio on close ---
        try:
            if self.audio_player:
                self.audio_player.stop_playback()
            if self.is_recording and self.audio_recorder:
                self.audio_recorder.stop_recording("temp_rec.wav") # Stop and delete temp
                if os.path.exists("temp_rec.wav"): os.remove("temp_rec.wav")
        except Exception as e:
            print(f"Error stopping audio during close: {e}")

        self.main_chat_client.unregister_chat_window(self.target_name)
        self.destroy()

    # --- New methods for Emoji and Voice ---

    def open_emoji_picker(self):
        picker = Toplevel(self)
        picker.title("Emojis")
        picker.configure(bg=PRIMARY_BG)
        picker.geometry("200x200")
        picker.transient(self) # Keep on top

        emoji_frame = Frame(picker, bg=PRIMARY_BG)
        emoji_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Add more emojis as needed
        emojis = ['😀', '😂', '😍', '🤔', '👍', '👎', '❤️', '🎉', '🔥', '🙏', '👋', '😢',
                  '😎', '🥳', '🤯', '😱', '😡', '✅', '❌', '💯', '👏', '👀', '👉', '👈']

        for i, emoji in enumerate(emojis):
            btn = tk.Button(emoji_frame, text=emoji, font=("Arial", 14),
                            command=lambda e=emoji, p=picker: self.insert_emoji(e, p),
                            relief="flat", bg=SIDEBAR_BG, fg=TEXT_COLOR,
                            activebackground=ACCENT_COLOR, activeforeground="white")
            btn.grid(row=i // 6, column=i % 6, sticky="nsew", padx=2, pady=2)

        for i in range(4): emoji_frame.grid_rowconfigure(i, weight=1)
        for i in range(6): emoji_frame.grid_columnconfigure(i, weight=1)

    def insert_emoji(self, emoji, picker):
        self.msg_entry.insert(tk.END, emoji)
        picker.destroy()
        self.msg_entry.focus()

    def toggle_voice_record(self):
        if self.is_recording:
            # --- STOP RECORDING ---
            print("Stopping recording...")
            self.is_recording = False
            self.voice_button.config(text="🎤", fg=ACCENT_COLOR) # Reset icon
            self.msg_entry.config(state='normal')
            self.msg_entry.delete(0, tk.END) # Clear "Recording..." text
            self.send_button.config(state='normal')
            self.emoji_button.config(state='normal')

            if not self.audio_recorder: return

            filename = f"voice_msg_{int(time.time())}.wav"
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            self.audio_recorder.stop_recording(filepath)
            self.audio_recorder = None # Clear instance

            # Check if file was created and has size (e.g., > 1KB)
            if not os.path.exists(filepath) or os.path.getsize(filepath) < 1024:
                print("Recording failed or was too short. Not sending.")
                if os.path.exists(filepath):
                    try: os.remove(filepath)
                    except Exception as e: print(f"Could not remove short audio file: {e}")
                return

            # File is valid, start upload
            print(f"Recording saved. Uploading {filepath}...")
            try:
                # --- MODIFIED: Use stored self.main_app reference ---
                if hasattr(self.main_app, 'file_client_view') and self.main_app.file_client_view:
                    self.voice_button.config(text="...", state=tk.DISABLED) # Show uploading state
                    
                    # --- [THE FIX for KeyboardInterrupt] ---
                    # Run the upload in a new thread to avoid blocking the UI
                    threading.Thread(
                        target=self.main_app.file_client_view._execute_upload, 
                        args=(filepath, self.on_voice_upload_complete), 
                        daemon=True
                    ).start()
                    # --- [END OF FIX] ---

                else:
                    # Lazy-initialize a headless FileClientView so uploads can work from chat
                    try:
                        if hasattr(self.main_app, 'file_client_view') and self.main_app.file_client_view:
                            pass
                        else:
                            hidden_parent = getattr(self.main_app, 'content_frame', self.main_app)
                            try:
                                hidden_frame = Frame(hidden_parent, bg=PRIMARY_BG)
                                hidden_frame.pack_forget()
                            except Exception:
                                hidden_frame = hidden_parent
                            self.main_app.file_client_view = FileClientView(hidden_frame, self.main_app.server_host)

                        self.voice_button.config(text="...", state=tk.DISABLED)
                        threading.Thread(
                            target=self.main_app.file_client_view._execute_upload,
                            args=(filepath, self.on_voice_upload_complete),
                            daemon=True
                        ).start()
                    except Exception:
                        messagebox.showerror("Error", "File client is not available to send voice message.", parent=self)
                        self.voice_button.config(text="🎤", state=tk.NORMAL)
            except Exception as e:
                messagebox.showerror("Upload Error", f"Could not send voice message:\n{e}", parent=self)
                self.voice_button.config(text="🎤", state=tk.NORMAL)

        else:
            # --- START RECORDING ---
            self.audio_recorder = AudioRecorder()
            if self.audio_recorder.start_recording():
                print("Started recording...")
                self.is_recording = True
                self.voice_button.config(text="STOP", fg=BUTTON_RED) # Change button
                self.msg_entry.delete(0, tk.END)
                self.msg_entry.insert(0, "Recording... Click STOP to send.")
                self.msg_entry.config(state='disabled')
                self.send_button.config(state='disabled')
                self.emoji_button.config(state='disabled')
            else:
                messagebox.showerror("Audio Error", "Could not start recording.\nCheck microphone permissions.", parent=self)
                self.audio_recorder = None

    def on_voice_upload_complete(self, filename):
        # This is the callback from _execute_upload
        self.voice_button.config(text="🎤", state=tk.NORMAL) # Reset button

        if filename:
            # Upload was successful, send the chat link
            print(f"Upload complete: {filename}. Sending message link.")
            special_message = f"VOICE_MSG::{filename}"
            # Log=False here because send_actual_message will handle the local echo
            self.main_chat_client.send_actual_message(self.target_name, special_message)

            # Optionally delete the local file after upload
            try:
                local_path = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.exists(local_path):
                    os.remove(local_path)
                    print(f"Removed local voice file: {local_path}")
            except Exception as e:
                print(f"Could not delete local voice file: {e}")
        else:
            # Upload failed
            messagebox.showerror("Upload Error", "Failed to upload voice message. Please try again.", parent=self)

        # Clean up UI
        if not self.is_recording:
            self.msg_entry.config(state='normal')
            self.msg_entry.delete(0, tk.END)

    def play_voice_message(self, filename):
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        print(f"Attempting to play: {filename}")

        if os.path.exists(filepath):
            # File exists, play it
            print("File found locally. Playing...")
            self.audio_player.play_file(filepath)
        else:
            # File not found, download it
            print("File not found. Attempting download...")
            try:
                # --- MODIFIED: Use stored self.main_app reference ---
                if hasattr(self.main_app, 'file_client_view') and self.main_app.file_client_view:
                    # Download, and set the callback to play the file
                    # We pass the *full path* to the player in the callback
                    self.main_app.file_client_view._execute_download(filename,
                        callback_on_success=lambda f=filepath: self.audio_player.play_file(f))
                else:
                    # Lazy-init a headless FileClientView so we can download
                    try:
                        hidden_parent = getattr(self.main_app, 'content_frame', self.main_app)
                        try:
                            hidden_frame = Frame(hidden_parent, bg=PRIMARY_BG)
                            hidden_frame.pack_forget()
                        except Exception:
                            hidden_frame = hidden_parent
                        self.main_app.file_client_view = FileClientView(hidden_frame, self.main_app.server_host)
                        self.main_app.file_client_view._execute_download(
                            filename,
                            callback_on_success=lambda f=filepath: self.audio_player.play_file(f)
                        )
                    except Exception:
                        messagebox.showerror("Error", "File client is not available to download voice message.", parent=self)
            except Exception as e:
                messagebox.showerror("Download Error", f"Could not download voice message:\n{e}", parent=self)

    # --- End of new methods ---


# --- ChatClient Class ---
class ChatClient:
    def __init__(self, chat_frame, username, server_host):
        self.chat_frame = chat_frame
        self.username = username
        self.server_host = server_host
        self.sock = None
        self.connected_users = {} # {username: status}
        self.open_chat_windows = {}
        self.external_user_list_widget = None
        self.receive_thread = None

        self._setup_chat_ui()
        self._connect_to_server() # Can now fail
        # Start receive thread only if connection succeeded (done in _connect_to_server)
        if self.sock: # Check if connection was successful
            print(f"--- Chat Client Initialized {time.strftime('%Y-%m-%d %H:%M:%S')} ---")

    def set_external_user_list(self, list_widget):
        self.external_user_list_widget = list_widget
        self._update_user_list_ui_threadsafe(self.connected_users, 'clear_and_add_all')

    def _setup_chat_ui(self):
        header_frame = Frame(self.chat_frame, bg=CHAT_HEADER_BG)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(header_frame, text="Online Users", font=("Arial", 16, "bold"), bg=CHAT_HEADER_BG, fg=TEXT_COLOR).pack(pady=10)
        user_list_frame = Frame(self.chat_frame, bg=SIDEBAR_BG)
        user_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.user_list_widget = tk.Listbox(user_list_frame, bg=SIDEBAR_BG, fg=TEXT_COLOR,
                                           selectbackground=ACCENT_COLOR, selectforeground="white",
                                           bd=0, relief="flat", exportselection=False,
                                           highlightbackground=SIDEBAR_BG, highlightcolor=ACCENT_COLOR, highlightthickness=1)
        self.user_list_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.user_list_widget.bind('<<ListboxSelect>>', self.on_user_select)
        self.user_list_widget.insert(tk.END, "PUBLIC CHAT")

    def on_user_select(self, event=None):
        try:
            selected_index = self.user_list_widget.curselection()[0]
            display_text = self.user_list_widget.get(selected_index)
            target_name = display_text.split(" (")[0] # Extract name before status
            window = self.open_chat_windows.get(target_name) # Use extracted name

            # --- MODIFIED: Pass MainApplication instance ---
            # Get the MainApplication instance (root window)
            main_app_instance = self.chat_frame.winfo_toplevel()

            if window and window.winfo_exists(): window.lift(); window.focus_force()
            else:
                # Pass main_app_instance to ChatWindow constructor
                ChatWindow(main_app_instance, target_name, self, main_app_instance)

        except IndexError: pass
        except Exception as e:
            print(f"Error opening chat window: {e}") # Debugging
        finally: self.user_list_widget.selection_clear(0, tk.END)

    def update_user_list_ui(self, user_name, user_status, action):
        if not self.chat_frame.winfo_exists(): return
        self.chat_frame.after(0, self._update_user_list_ui_threadsafe, (user_name, user_status), action)

    def _update_user_list_ui_threadsafe(self, user_data, action):
        target_widget = self.user_list_widget
        external_widget = self.external_user_list_widget
        def update_single_widget(widget):
            if not widget or not widget.winfo_exists(): return False
            try:
                if action == 'add':
                    user_name, user_status = user_data
                    # --- FIX: Must be != to show *other* users ---
                    if user_name != self.username:
                        display_text = f"{user_name}" + (f" ({user_status})" if user_status != "Online" else "")
                        widget.insert(tk.END, display_text)
                        if user_status == "Away": widget.itemconfig(tk.END, {'fg': USER_STATUS_AWAY_FG})
                elif action == 'remove':
                    user_name, _ = user_data
                    current_items = widget.get(0, tk.END)
                    for idx, item in enumerate(current_items):
                        if item.startswith(user_name + " ") or item == user_name: # Handle with/without status
                            widget.delete(idx); break
                elif action == 'update_status':
                     user_name, user_status = user_data
                     current_items = widget.get(0, tk.END)
                     for idx, item in enumerate(current_items):
                         if item.startswith(user_name + " ") or item == user_name:
                             display_text = f"{user_name}" + (f" ({user_status})" if user_status != "Online" else "")
                             widget.delete(idx); widget.insert(idx, display_text)
                             fg_color = USER_STATUS_AWAY_FG if user_status == "Away" else TEXT_COLOR
                             widget.itemconfig(idx, {'fg': fg_color}); break
                elif action == 'clear_and_add_all': # user_data is the full {name: status} dict
                    widget.delete(1, tk.END) # Keep PUBLIC CHAT
                    user_dict = user_data; sorted_users = sorted(user_dict.items()) # <-- This line was failing
                    for u_name, u_status in sorted_users:
                        # --- FIX: Must be != to show *other* users ---
                        if u_name != self.username:
                            display_text = f"{u_name}" + (f" ({u_status})" if u_status != "Online" else "")
                            widget.insert(tk.END, display_text)
                            if u_status == "Away": widget.itemconfig(tk.END, {'fg': USER_STATUS_AWAY_FG})
            except tk.TclError: return False
            except Exception as e: print(f"Error updating user list widget: {e}")
            return True
        update_single_widget(target_widget)
        if not update_single_widget(external_widget): self.external_user_list_widget = None

    def _connect_to_server(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.server_host, CHAT_PORT))
            self.sock.sendall(self.username.encode('utf-8'))
            response = self.sock.recv(1024)
            if response != b'OK':
                msg = "Username is already taken."
                if response != b'ERROR:USERNAME_TAKEN': msg = f"Server refused: {response.decode('utf-8','ignore')}"
                print(f"[SYSTEM] {msg}"); messagebox.showerror("Connection Error", f"{msg}\nPlease restart.")
                self.sock.close(); self.sock = None
                try:
                    # --- MODIFIED: Correctly get MainApplication instance ---
                    main_app_instance = self.chat_frame.winfo_toplevel()
                    if main_app_instance: main_app_instance.on_closing()
                except Exception: pass
                return
        except Exception as e:
            msg = f"[SYSTEM] Could not connect to chat server: {e}"
            print(msg); messagebox.showerror("Connection Error", msg)
            self.sock = None; return
        print(f"[SYSTEM] Connected as {self.username}. Welcome!")
        self.receive_thread = threading.Thread(target=self.receive_messages, daemon=True)
        self.receive_thread.start() # Start thread *after* successful connect

    def receive_messages(self):
        while running and self.sock:
            target_window = None; message_content = ""; tag = None; log_locally = True # Log received messages by default
            try:
                message_raw = self.sock.recv(1024).decode('utf-8')
                if not message_raw: break
                target_name = "PUBLIC CHAT"; timestamp = ""
                # Extract timestamp if present
                if len(message_raw) > 9 and message_raw[2] == ':' and message_raw[5] == ':':
                    parts = message_raw.split(" ", 1)
                    if len(parts) == 2: timestamp = parts[0]; message_body = parts[1]
                    else: message_body = message_raw # Malformed
                else: message_body = message_raw # No timestamp

                # Process message body
                if message_body.startswith("USER_LIST:"):
                    users_part = message_body.split(':', 1)[1]
                    self.connected_users.clear()
                    if users_part:
                        for pair in users_part.split(','):
                             name, status = pair.split('=', 1); self.connected_users[name] = status
                    
                    # --- [THE FIX for User List Error] ---
                    # Schedule the threadsafe UI update, passing the *dictionary*
                    self.chat_frame.after(0, self._update_user_list_ui_threadsafe, self.connected_users, 'clear_and_add_all')
                    continue
                    # --- [END OF FIX] ---

                elif message_body.startswith("USER_JOIN:"):
                    user_info = message_body.split(':', 1)[1]; user_name, user_status = user_info.split('=', 1)
                    self.connected_users[user_name] = user_status; self.update_user_list_ui(user_name, user_status, 'add')
                    message_content = f"[SYSTEM] {user_name} joined."; tag = "system_message"; log_locally = False # Don't log server broadcasts locally
                elif message_body.startswith("USER_LEAVE:"):
                    user_name = message_body.split(':', 1)[1]
                    if user_name in self.connected_users: del self.connected_users[user_name]
                    self.update_user_list_ui(user_name, None, 'remove')
                    message_content = f"[SYSTEM] {user_name} left."; tag = "system_message"; log_locally = False # Don't log locally
                    window_to_close = self.open_chat_windows.get(user_name)
                    if window_to_close: window_to_close.add_message("[SYSTEM] User has disconnected.", "system_message", log=False)
                elif message_body.startswith("STATUS_UPDATE:"):
                     user_info = message_body.split(':', 1)[1]; user_name, user_status = user_info.split('=', 1)
                     if user_name in self.connected_users:
                         self.connected_users[user_name] = user_status
                         self.update_user_list_ui(user_name, user_status, 'update_status')
                     continue # Just update list, no chat message
                elif message_body.startswith("PM_FROM:"):
                    sender, content = message_body.split(':', 2)[1:]
                    target_name = sender;
                    # --- MOD: Pass full message for voice check ---
                    message_content = f"{timestamp} {sender}: {content}";
                    tag = "pm_message"; # log_locally remains True
                elif message_body.startswith("PM_TO:"):
                    recipient, content = message_body.split(':', 2)[1:]
                    target_name = recipient;
                    # --- MOD: Pass full message for voice check ---
                    message_content = f"{timestamp} You [to {recipient}]: {content}";
                    tag = "my_pm_message"; log_locally = False # This is an echo from server, don't log locally
                elif message_body.startswith("SYSTEM:"):
                    content = message_body.split(':', 1)[1]
                    message_content = f"{timestamp} [SYSTEM] {content}"; tag = "system_message"; # log_locally remains True
                elif ":" in message_body: # Public msg (sender added by server)
                    sender = message_body.split(":", 1)[0]
                    target_name = "PUBLIC CHAT";
                    # --- MOD: Pass full message for voice check ---
                    message_content = f"{timestamp} {message_body}";
                    tag = "remote_message"; # log_locally remains True
                    if sender == self.username:
                        log_locally = False; continue # Don't display/log own echo
                else: message_content = f"{timestamp} {message_body}"; tag = "system_message"; # log_locally remains True

                # Display the message
                target_window = self.open_chat_windows.get(target_name)
                if target_window and target_window.winfo_exists():
                    # --- MOD: Pass log_locally flag ---
                    self.chat_frame.after(0, target_window.add_message, message_content, tag, log_locally)
                elif log_locally: # Log even if window is closed (includes PUBLIC CHAT)
                    safe_target_name = "".join(c if c.isalnum() else "_" for c in target_name)
                    temp_log_file = os.path.join(DOWNLOAD_DIR, f"chat_log_{self.username}_{safe_target_name}.txt")
                    try:
                        with open(temp_log_file, 'a', encoding='utf-8') as f: f.write(message_content + '\n')
                    except Exception as e: print(f"Error logging message for closed window {target_name}: {e}")
            except UnicodeDecodeError: print("[WARNING] Received non-UTF8 data, ignoring.")
            except (ConnectionResetError, BrokenPipeError):
                if running: print("[SYSTEM] Connection to server lost."); messagebox.showerror("Connection Lost", "Connection to the chat server was lost.")
                break
            except Exception as e:
                if running: print(f"Receive error: {e}")
                break
        print("[SYSTEM] Disconnected from chat.")
        for window in self.open_chat_windows.values():
             if window.winfo_exists(): self.chat_frame.after(0, window.add_message, "[SYSTEM] Disconnected from server.", "system_message", log=False)
        if self.sock: self.sock.close(); self.sock = None

    def send_actual_message(self, target_name, message):
        if not self.sock:
            msg = "[SYSTEM] You are not connected."; window = self.open_chat_windows.get(target_name)
            if window and window.winfo_exists(): self.chat_frame.after(0, window.add_message, msg, "system_message", log=False)
            return False
        formatted_message = ""; local_echo_msg = ""; local_echo_tag = None
        try:
            # --- MOD: Handle VOICEMSG echo ---
            is_voice = message.startswith("VOICE_MSG::")
            if target_name == "PUBLIC CHAT":
                formatted_message = message
                # Use the original message for echo, add_message will handle prefixing 'You:'
                local_echo_msg = message
                local_echo_tag = "my_message"
            else:
                formatted_message = f"PM:{target_name}:{message}"
                 # Use the original message for echo, add_message will handle prefixing 'You [to ...]:'
                local_echo_msg = message
                local_echo_tag = "my_pm_message"

            self.sock.sendall(formatted_message.encode('utf-8'))

            # Local Echo via add_message (handles log & timestamp)
            window = self.open_chat_windows.get(target_name)

            if window and window.winfo_exists():
                # --- MOD: Let add_message handle timestamp and prefix ---
                # log=True ensures it's written to file
                window.add_message(local_echo_msg, local_echo_tag, log=True)
            else: # Log directly if window not open
                 print(f"[WARN] Chat window for {target_name} not found for echo.")
                 safe_target_name = "".join(c if c.isalnum() else "_" for c in target_name)
                 temp_log_file = os.path.join(DOWNLOAD_DIR, f"chat_log_{self.username}_{safe_target_name}.txt")
                 try:
                     # --- MOD: Manually add timestamp and prefix for direct log ---
                     timestamp = time.strftime('%H:%M:%S')
                     prefix = f"You: " if target_name == "PUBLIC CHAT" else f"You [to {target_name}]: "
                     log_content = f"{timestamp} {prefix}{local_echo_msg}\n"
                     with open(temp_log_file, 'a', encoding='utf-8') as f: f.write(log_content)
                 except Exception as e: print(f"Error logging echo for closed window {target_name}: {e}")
            return True
        except Exception as e:
            msg = f"[SYSTEM] Failed to send message: {e}"; print(msg)
            window = self.open_chat_windows.get(target_name)
            if window and window.winfo_exists(): self.chat_frame.after(0, window.add_message, msg, "system_message", log=False)
            return False

    def send_status_update(self, new_status):
        if self.sock:
            try: self.sock.sendall(f"SET_STATUS:{new_status}".encode('utf-8'))
            except Exception as e: print(f"Error sending status update: {e}")

    def register_chat_window(self, target_name, window_instance):
        print(f"Registering window for {target_name}")
        self.open_chat_windows[target_name] = window_instance

    def unregister_chat_window(self, target_name):
        print(f"Unregistering window for {target_name}")
        if target_name in self.open_chat_windows: del self.open_chat_windows[target_name]

    def on_closing(self):
        for window in list(self.open_chat_windows.values()):
            if window.winfo_exists(): window.destroy()
        if self.sock: self.sock.close(); self.sock = None


# --- FileClientView Class ---
class FileClientView:
    def __init__(self, parent_frame, server_host):
        self.parent_frame = parent_frame; self.server_host = server_host; self.sock = None
        self._setup_file_ui(); self._connect_to_server()
    def _setup_file_ui(self):
        header_frame = Frame(self.parent_frame, bg=CHAT_HEADER_BG); header_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(header_frame, text="File Share", font=("Arial", 16, "bold"), bg=CHAT_HEADER_BG, fg=TEXT_COLOR).pack(pady=10)
        main_pane = PanedWindow(self.parent_frame, orient=tk.HORIZONTAL, sashwidth=6, bg=PRIMARY_BG, relief="flat", bd=0, sashrelief="flat"); main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        list_frame = Frame(main_pane, bg=SIDEBAR_BG, width=300); main_pane.add(list_frame, minsize=250, stretch="never")
        tk.Label(list_frame, text="Available Files:", bg=SIDEBAR_BG, fg=TEXT_COLOR, font=("Arial", 12, "bold")).pack(pady=10, padx=10, anchor='w')
        self.file_list = tk.Listbox(list_frame, width=40, bg=CHAT_INPUT_BG, fg=TEXT_COLOR, selectbackground=ACCENT_COLOR, selectforeground="white", bd=0, relief="flat", highlightthickness=0, exportselection=False); self.file_list.pack(padx=10, pady=(0, 10), fill=tk.BOTH, expand=True); self.file_list.bind('<<ListboxSelect>>', self.on_file_select)
        button_frame = Frame(list_frame, bg=SIDEBAR_BG); button_frame.pack(fill=tk.X, padx=10, pady=(5, 10), side=tk.BOTTOM)
        row1_frame = Frame(button_frame, bg=SIDEBAR_BG); row1_frame.pack(fill=tk.X, pady=(0,5))
        self.upload_button = ttk.Button(row1_frame, text="↑ Upload File", command=self.upload_file, style="TButton"); self.upload_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,2))
        self.download_button = ttk.Button(row1_frame, text="↓ Download Selected", command=self.download_file, style="TButton"); self.download_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2,0))
        row2_frame = Frame(button_frame, bg=SIDEBAR_BG); row2_frame.pack(fill=tk.X)
        self.delete_button = ttk.Button(row2_frame, text="❌ Delete Selected", command=self.delete_selected_file, style="Red.TButton"); self.delete_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=0); self.delete_button.config(state=tk.DISABLED)
        self.preview_frame = Frame(main_pane, bg=PRIMARY_BG); main_pane.add(self.preview_frame, stretch="always")
        tk.Label(self.preview_frame, text="File Preview", bg=PRIMARY_BG, fg=TEXT_COLOR, font=("Arial", 12, "bold")).pack(pady=10, padx=20, anchor='w')
        self.preview_image_label = tk.Label(self.preview_frame, bg=PRIMARY_BG); self.preview_image_label.pack(pady=20, padx=20)
        self.details_label = tk.Label(self.preview_frame, text="", bg=PRIMARY_BG, fg=TEXT_COLOR, font=("Arial", 11), justify='left', anchor='w', wraplength=400); self.details_label.pack(pady=10, padx=20, fill='x')
        self.open_button = ttk.Button(self.preview_frame, text="Open / Play Selected File", command=self.open_selected_file, style="TButton"); self.open_button.pack(pady=20, padx=20, fill='x'); self.open_button.config(state=tk.DISABLED)
        self.progress = ttk.Progressbar(self.parent_frame, orient=tk.HORIZONTAL, length=100, mode='determinate', style="Green.Horizontal.TProgressbar"); self.progress.pack(pady=(0, 10), padx=20, fill=tk.X, side=tk.BOTTOM)
        self.show_placeholder_preview()
    def on_file_select(self, event=None):
        try: idx = self.file_list.curselection()[0]; filename = self.file_list.get(idx); self.update_preview_pane(filename); self.open_button.config(state=tk.NORMAL); self.delete_button.config(state=tk.NORMAL)
        except IndexError: self.show_placeholder_preview() # Also disables buttons
    def update_preview_pane(self, filename):
        ext = os.path.splitext(filename)[1].lower(); local_path = os.path.join(DOWNLOAD_DIR, filename); status = "On Server"; preview_image = None; PREVIEW_SIZE = 150; BG_COLOR = "#2B2B2B"
        if os.path.exists(local_path): status = "Downloaded"
        details_text = f"File: {filename}\nType: Unknown\nStatus: {status}"; TXT_EXTS = ['.txt', '.md', '.log', '.py', '.js', '.css', '.html', '.xml', '.json', '.ini', '.cfg']
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']: details_text = f"File: {filename}\nType: Image File\nStatus: {status}"; preview_image = create_icon_image(PREVIEW_SIZE, ACCENT_COLOR, text_label='IMG', shape='square', bg_color=BG_COLOR)
        elif ext in TXT_EXTS: details_text = f"File: {filename}\nType: Text Document\nStatus: {status}"; preview_image = create_icon_image(PREVIEW_SIZE, "#3498DB", text_label='TXT', shape='square', bg_color=BG_COLOR)
        elif ext in ['.zip', '.rar', '.7z', '.gz', '.tar']: details_text = f"File: {filename}\nType: Archive\nStatus: {status}"; preview_image = create_icon_image(PREVIEW_SIZE, "#F1C40F", text_label='ZIP', shape='square', bg_color=BG_COLOR)
        elif ext in ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv']: details_text = f"File: {filename}\nType: Video File\nStatus: {status}"; preview_image = create_icon_image(PREVIEW_SIZE, "#E74C3C", text_label='VID', shape='square', bg_color=BG_COLOR)
        elif ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']: details_text = f"File: {filename}\nType: Audio File\nStatus: {status}"; preview_image = create_icon_image(PREVIEW_SIZE, "#9B59B6", text_label='AUD', shape='square', bg_color=BG_COLOR)
        elif ext == '.pdf': details_text = f"File: {filename}\nType: PDF Document\nStatus: {status}"; preview_image = create_icon_image(PREVIEW_SIZE, "#E67E22", text_label='PDF', shape='square', bg_color=BG_COLOR)
        else: details_text = f"File: {filename}\nType: Generic File\nStatus: {status}"; preview_image = create_icon_image(PREVIEW_SIZE, "#95A5A6", text_label='FILE', shape='square', bg_color=BG_COLOR)
        self.preview_image_label.config(image=preview_image, bg=BG_COLOR); self.preview_image_label.image = preview_image
        self.details_label.config(text=details_text)
    def show_placeholder_preview(self):
        PREVIEW_SIZE = 150; BG_COLOR = "#2B2B2B"; placeholder_image = create_icon_image(PREVIEW_SIZE, BG_COLOR, text_label='', shape='square', bg_color=BG_COLOR)
        self.preview_image_label.config(image=placeholder_image, bg=BG_COLOR); self.preview_image_label.image = placeholder_image
        self.details_label.config(text="Select a file from the list to see details.")
        self.open_button.config(state=tk.DISABLED); self.delete_button.config(state=tk.DISABLED)
    def _connect_to_server(self):
        try: self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); self.sock.connect((self.server_host, FILE_PORT))
        except Exception as e: messagebox.showerror("Connection Error", f"Could not connect to file server:\n{e}", parent=self.parent_frame); self.sock = None; return
        self.receive_thread = threading.Thread(target=self.receive_messages, daemon=True); self.receive_thread.start()
    def update_file_list(self, files_str):
        self.file_list.delete(0, tk.END);
        if files_str:
            for f in sorted(files_str.split(',')): self.file_list.insert(tk.END, f)
        self.show_placeholder_preview()
    def add_to_file_list(self, filename):
        all_files = list(self.file_list.get(0, tk.END)); all_files.append(filename)
        self.file_list.delete(0, tk.END);
        for f in sorted(all_files): self.file_list.insert(tk.END, f)
    def remove_from_file_list(self, filename):
        try:
            current_items = self.file_list.get(0, tk.END)
            if filename in current_items:
                idx = current_items.index(filename); self.file_list.delete(idx)
                if not self.file_list.curselection(): self.show_placeholder_preview()
        except Exception as e: print(f"Error removing file from list: {e}")
    def receive_messages(self):
        buffer = ""
        while running and self.sock:
            try:
                data = self.sock.recv(1024);
                if not data: break
                buffer += data.decode('utf-8')
                while '\n' in buffer:
                    message, buffer = buffer.split('\n', 1);
                    if not message: continue
                    if message.startswith('FILE_LIST:'): self.parent_frame.after(0, self.update_file_list, message.split(':', 1)[1])
                    elif message.startswith('NEW_FILE:'): self.parent_frame.after(0, self.add_to_file_list, message.split(':', 1)[1])
                    elif message.startswith('FILE_DELETED:'): self.parent_frame.after(0, self.remove_from_file_list, message.split(':', 1)[1])
                    elif message.startswith('OK:File deleted'): messagebox.showinfo("File Deleted", "File successfully deleted from server.", parent=self.parent_frame.master)
                    elif message.startswith('ERROR:'): messagebox.showerror("Server Error", f"File Server:\n{message.split(':', 1)[1]}", parent=self.parent_frame.master)
            except (ConnectionResetError, BrokenPipeError):
                if running: print("[SYSTEM] Connection to file server lost."); messagebox.showerror("Connection Lost", "Connection to the file server was lost.")
                break
            except Exception as e:
                if running: print(f"[FILE RECV] Error: {e}")
                break
        if self.sock: self.sock.close(); self.sock = None
        print("[SYSTEM] Disconnected from file server.")
    def upload_file(self):
        filepath = filedialog.askopenfilename(parent=self.parent_frame);
        if not filepath: return
        threading.Thread(target=self._execute_upload, args=(filepath, None), daemon=True).start()

    # --- MODIFIED: Added on_complete_callback ---
    def _execute_upload(self, filepath, on_complete_callback=None):
        if not self.server_host:
            messagebox.showerror("Upload Error", "Server host not defined.", parent=self.parent_frame)
            if on_complete_callback: self.parent_frame.after(0, on_complete_callback, None) # Signal failure
            return
        filename = os.path.basename(filepath); filesize = os.path.getsize(filepath)
        upload_sock = None
        try:
            upload_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); upload_sock.connect((self.server_host, FILE_PORT))
            upload_sock.recv(4096) # Consume greeting
            upload_sock.sendall(f"UPLOAD:{filename}:{filesize}\n".encode())
            response = upload_sock.recv(1024) # Expect OK\n or ERROR:...\n
            if not response.startswith(b'OK'):
                error_msg = response.decode('utf-8', 'ignore').split(':', 1)[-1].strip() if b':' in response else response.decode('utf-8', 'ignore').strip()
                messagebox.showerror("Upload Error", f"Server refused: {error_msg}", parent=self.parent_frame)
                if on_complete_callback: self.parent_frame.after(0, on_complete_callback, None) # Signal failure
                return

            # --- NEW: Get actual filename from server (in case of rename) ---
            # Server doesn't send this back, but we can assume it's the same
            # or we'd need a protocol change. We'll just use 'filename'.
            # A better way would be for the server to send "OK:new_filename.txt\n"

            sent_bytes = 0
            with open(filepath, 'rb') as f:
                while chunk := f.read(4096):
                    upload_sock.sendall(chunk); sent_bytes += len(chunk)
                    progress_val = (sent_bytes / filesize) * 100
                    self.parent_frame.after(0, lambda p=progress_val: self.progress.config(value=p))

            # --- MODIFIED: Handle callback ---
            if not on_complete_callback: # Only show this for manual uploads
                self.parent_frame.after(0, messagebox.showinfo, "Upload Complete", f"'{filename}' uploaded.", parent=self.parent_frame.master)
            self.parent_frame.after(500, lambda: self.progress.config(value=0))

            if on_complete_callback:
                # Pass the original filename (assuming server didn't rename)
                self.parent_frame.after(0, on_complete_callback, filename)

        except Exception as e:
            if not on_complete_callback: # Only show error for manual
                messagebox.showerror("Upload Error", f"Failed to upload '{filename}':\n{e}", parent=self.parent_frame)
            self.parent_frame.after(10, lambda: self.progress.config(value=0))
            if on_complete_callback:
                self.parent_frame.after(0, on_complete_callback, None) # Signal failure
        finally:
            if upload_sock: upload_sock.close()

    def download_file(self):
        try: filename = self.file_list.get(self.file_list.curselection()[0])
        except IndexError: messagebox.showwarning("Download Error", "Please select a file.", parent=self.parent_frame); return
        threading.Thread(target=self._execute_download, args=(filename, None), daemon=True).start()

    # --- MODIFIED: Added callback_on_success ---
    def _execute_download(self, filename, callback_on_success=None):
        if not self.server_host:
             messagebox.showerror("Download Error", "Server host not defined.", parent=self.parent_frame)
             if callback_on_success: self.parent_frame.after(0, lambda: self.details_label.config(text=f"Download failed (no server host)"))
             return
        download_sock = None; filepath = os.path.join(DOWNLOAD_DIR, filename)
        try:
            download_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); download_sock.connect((self.server_host, FILE_PORT))
            download_sock.recv(4096) # Consume greeting
            download_sock.sendall(f"DOWNLOAD:{filename}\n".encode())
            buffer = b""; header_str = ""
            while b'\n' not in buffer: buffer += download_sock.recv(1024) # Read until newline
            header, buffer = buffer.split(b'\n', 1); header_str = header.decode('utf-8')
            if not header_str.startswith('FILE_DATA:'):
                error_msg = header_str.split(':', 1)[-1] if ':' in header_str else header_str
                raise ConnectionAbortedError(f"Server error: {error_msg}") # Raise specific error
            filesize = int(header_str.split(':', 1)[1]); download_sock.sendall(b'OK') # Confirm
            received_bytes = len(buffer)
            with open(filepath, 'wb') as f:
                f.write(buffer) # Write initial part
                while received_bytes < filesize:
                    chunk = download_sock.recv(min(4096, filesize - received_bytes))
                    if not chunk: raise ConnectionAbortedError("Server disconnected during download")
                    f.write(chunk); received_bytes += len(chunk)
                    progress_val = (received_bytes / filesize) * 100
                    self.parent_frame.after(0, lambda p=progress_val: self.progress.config(value=p))
            if received_bytes == filesize:
                if callback_on_success:
                    self.parent_frame.after(0, callback_on_success, filepath) # Pass full path
                else:
                    messagebox.showinfo("Download Complete", f"'{filename}' downloaded to '{DOWNLOAD_DIR}'.", parent=self.parent_frame.master)
                self.parent_frame.after(0, self.update_preview_pane, filename) # Update status to "Downloaded"
            else: raise IOError(f"Incomplete download for {filename}. Expected {filesize}, got {received_bytes}")
        except (ConnectionAbortedError, ConnectionRefusedError, IOError) as ce:
             if not callback_on_success: # Only show error if not a background download
                 messagebox.showerror("Download Error", f"{ce}", parent=self.parent_frame)
             if os.path.exists(filepath): os.remove(filepath) # Clean up
             if callback_on_success: self.parent_frame.after(0, lambda: self.details_label.config(text=f"Download failed ({ce})"))
             else: self.parent_frame.after(0, self.update_preview_pane, filename)
        except Exception as e:
            if not callback_on_success:
                messagebox.showerror("Download Error", f"Failed to download '{filename}':\n{e}", parent=self.parent_frame)
            if os.path.exists(filepath): os.remove(filepath)
            if callback_on_success: self.parent_frame.after(0, lambda: self.details_label.config(text=f"Download failed (Error)"))
            else: self.parent_frame.after(0, self.update_preview_pane, filename)
        finally:
            self.parent_frame.after(100, lambda: self.progress.config(value=0)) # Ensure progress reset
            if download_sock: download_sock.close()

    def open_selected_file(self):
        try: filename = self.file_list.get(self.file_list.curselection()[0])
        except IndexError: return
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.exists(filepath): self.launch_viewer(filepath)
        else:
            self.progress.config(value=0); self.details_label.config(text=f"Downloading {filename} for preview...")
            threading.Thread(target=self._execute_download, args=(filename, self.launch_viewer), daemon=True).start()

    def launch_viewer(self, filepath):
        if not os.path.exists(filepath): self.details_label.config(text=f"Failed to find {os.path.basename(filepath)}"); return
        self.update_preview_pane(os.path.basename(filepath))
        ext = os.path.splitext(filepath)[1].lower()
        IMG = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']; TXT = ['.txt', '.md', '.log', '.py', '.js', '.css', '.html', '.xml', '.json', '.ini', '.cfg']; AUD = ['.mp3', '.wav', '.ogg', '.m4a', '.flac']; VID = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv']
        if ext in IMG: self.show_image_viewer(filepath)
        elif ext in TXT: self.show_text_viewer(filepath)
        elif ext == '.pdf':
            if fitz: self.show_pdf_viewer(filepath)
            else: messagebox.showwarning("PDF Error", "PyMuPDF missing.\nOpening with default app."); self.open_with_default_app(filepath)
        elif ext in AUD or ext in VID:
            # --- NEW: Don't auto-play voice msgs, but open other media ---
            if ext == '.wav' and 'voice_msg_' in filepath:
                 messagebox.showinfo("Info", "This is a voice message file.\nUse the 'Play' button in chat to listen.", parent=self.parent_frame)
            else:
                self.open_with_default_app(filepath)
        else: messagebox.showinfo("No Preview", f"No built-in preview for '{ext}'.\nOpening with default OS app."); self.open_with_default_app(filepath)

    def open_with_default_app(self, filepath):
        try:
            system = platform.system();
            if system == "Windows": os.startfile(filepath)
            elif system == "Darwin": subprocess.run(["open", filepath], check=True)
            else: subprocess.run(["xdg-open", filepath], check=True)
        except Exception as e: messagebox.showerror("Error", f"Could not open file.\n{e}\nEnsure a default app is set.", parent=self.parent_frame)
    def show_image_viewer(self, filepath):
        try:
            win = Toplevel(self.parent_frame); win.title(os.path.basename(filepath)); win.configure(bg=PRIMARY_BG)
            img_pil = Image.open(filepath); sw = int(self.parent_frame.winfo_screenwidth()*0.8); sh = int(self.parent_frame.winfo_screenheight()*0.8)
            if img_pil.width > sw or img_pil.height > sh: img_pil.thumbnail((sw, sh), Image.LANCZOS)
            img_tk = ImageTk.PhotoImage(img_pil); label = tk.Label(win, image=img_tk, bg=PRIMARY_BG); label.image = img_tk; label.pack(padx=10, pady=10); win.lift(); win.focus_force()
        except Exception as e: messagebox.showerror("Image Error", f"Could not open image:\n{e}", parent=self.parent_frame)
    def show_text_viewer(self, filepath):
        try: win = TextViewer(self.parent_frame, filepath); win.lift(); win.focus_force()
        except Exception as e: messagebox.showerror("Text File Error", f"Could not open file:\n{e}", parent=self.parent_frame)
    def show_pdf_viewer(self, filepath):
        try: win = PDFViewer(self.parent_frame, filepath); win.lift(); win.focus_force()
        except Exception as e: messagebox.showerror("PDF Error", f"Could not open PDF:\n{e}", parent=self.parent_frame)
    def delete_selected_file(self):
        if not self.sock: messagebox.showerror("Error", "Not connected to file server.", parent=self.parent_frame); return
        try: filename = self.file_list.get(self.file_list.curselection()[0])
        except IndexError: messagebox.showwarning("Delete Error", "Please select a file.", parent=self.parent_frame); return
        if messagebox.askyesno("Confirm Delete", f"Delete '{filename}' from the server?", parent=self.parent_frame):
            try: self.sock.sendall(f"DELETE:{filename}\n".encode('utf-8'))
            except Exception as e: messagebox.showerror("Delete Error", f"Failed to send request: {e}", parent=self.parent_frame)
    def on_closing(self):
        if self.sock: self.sock.close(); self.sock = None


# --- AudioClient Class ---
class AudioClient:
    def __init__(self, server_host):
        self.FORMAT = pyaudio.paInt16; self.CHANNELS = 1; self.RATE = 44100; self.CHUNK = 1024
        self.client_socket = None; self.send_stream = None; self.recv_stream = None
        self.audio = pyaudio.PyAudio(); self.server_host = server_host; self._running = False
    def start(self):
        if self._running: return True
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); self.client_socket.bind(('', 0))
            self.server_addr = (self.server_host, AUDIO_PORT)
            self.send_stream = self.audio.open(format=self.FORMAT, channels=self.CHANNELS, rate=self.RATE, input=True, frames_per_buffer=self.CHUNK)
            self.recv_stream = self.audio.open(format=self.FORMAT, channels=self.CHANNELS, rate=self.RATE, output=True, frames_per_buffer=self.CHUNK)
            self._running = True
        except Exception as e: print(f"[AUDIO] Error init: {e}"); messagebox.showerror("Audio Error", f"Could not initialize audio.\n{e}"); self._running = False; return False
        self.client_socket.sendto(b'REGISTER', self.server_addr)
        threading.Thread(target=self._send_audio_loop, daemon=True).start(); threading.Thread(target=self._receive_audio_loop, daemon=True).start()
        print("[AUDIO] Client started."); return True
    def _send_audio_loop(self):
        while running and self._running:
            try: data = self.send_stream.read(self.CHUNK, exception_on_overflow=False); self.client_socket.sendto(data, self.server_addr)
            except (IOError, OSError): break
            except Exception as e: print(f"Audio send error: {e}"); break
        print("[AUDIO] Sending stopped.")
    def _receive_audio_loop(self):
        while running and self._running:
            try: data, _ = self.client_socket.recvfrom(4096); self.recv_stream.write(data)
            except (IOError, OSError): pass
            except Exception as e: print(f"Audio recv error: {e}"); pass
        print("[AUDIO] Receiving stopped.")
    def stop(self):
        if not self._running: return
        self._running = False
        try:
            if self.send_stream: self.send_stream.stop_stream(); self.send_stream.close()
            if self.recv_stream: self.recv_stream.stop_stream(); self.recv_stream.close()
        except Exception as e: print(f"[AUDIO] Error closing streams: {e}")
        self.send_stream = None; self.recv_stream = None
        if self.client_socket: self.client_socket.close(); self.client_socket = None
        print("[AUDIO] Client stopped.")
    def __del__(self):
        try:
            if self.audio: self.audio.terminate()
        except Exception as e: print(f"Error terminating PyAudio: {e}")


# --- VideoClient Class ---
# [MODIFIED] This class is significantly changed to support a dynamic grid layout.
class VideoClient:
    def __init__(self, my_video_label, gallery_frame, server_host, username):
        self.my_video_label = my_video_label; self.gallery_frame = gallery_frame; self.JPEG_QUALITY = 50
        self.server_host = server_host; self.username = username; 
        self._running = False; self._sending = False # NEW: Separate flags
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); self.client_socket.bind(('', 0))
        self.server_addr = (self.server_host, VIDEO_PORT); 
        self.cap = None # Will be initialized in start_sending
        self.participant_labels = {}; self.last_frame_time = {}; self.image_queue = queue.Queue()

    def start(self):
        """Starts the client in RECEIVE-ONLY mode."""
        if self._running: return True
        
        # No webcam opening here
        self.client_socket.sendto(b'REGISTER', self.server_addr); self._running = True
        
        # Start only the receiving and processing loops
        threading.Thread(target=self._receive_video_loop, daemon=True).start()
        threading.Thread(target=self._check_stale_participants_loop, daemon=True).start()
        self.gallery_frame.after(100, self._process_image_queue)
        print("[VIDEO] Client started (Receiving)."); return True

    def start_sending(self):
        """Attempts to open the webcam and start sending video."""
        if self._sending: return True # Already sending
        try:
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                messagebox.showerror("Video Error", "Could not open webcam.")
                self.cap = None
                return False
        except Exception as e:
            messagebox.showerror("Video Error", f"Error opening webcam: {e}")
            self.cap = None
            return False
        
        self._sending = True
        threading.Thread(target=self._send_video_loop, daemon=True).start()
        print("[VIDEO] Sending started.")
        return True

    def stop_sending(self):
        """Stops the sending loop and releases the webcam."""
        self._sending = False # This will trigger the _send_video_loop to exit
        print("[VIDEO] Sending stopped (requested).")
        # The loop's 'finally' block will handle cap.release() and clearing the label

    def _send_video_loop(self):
        username_bytes = self.username.encode('utf-8')
        try:
            while running and self._running and self._sending and self.cap and self.cap.isOpened():
                try:
                    ret, frame = self.cap.read();
                    if not ret: continue
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.JPEG_QUALITY]; result, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
                    if result: data = username_bytes + b'::' + encoded_frame.tobytes(); self.client_socket.sendto(data, self.server_addr)
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB); img = Image.fromarray(frame_rgb)
                    try: # Protect against widget errors if closing
                        target_w = self.my_video_label.winfo_width(); target_h = self.my_video_label.winfo_height()
                        if target_w < 10 or target_h < 10: time.sleep(0.1); continue
                        w, h = img.size; ratio = min(target_w / w, target_h / h); new_size = (int(w * ratio), int(h * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                        new_img = Image.new("RGB", (target_w, target_h), "black"); new_img.paste(img, ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2))
                        img_tk = ImageTk.PhotoImage(image=new_img)
                        if self.my_video_label.winfo_exists(): self.my_video_label.config(image=img_tk); self.my_video_label.image = img_tk
                    except Exception: pass # Ignore UI update errors during shutdown
                    time.sleep(0.03)
                except cv2.error: break # Handle camera disconnect
                except Exception: break
        finally:
            if self.cap: self.cap.release(); self.cap = None
            self._sending = False
            print("[VIDEO] Sending loop stopped.")
            try:
                # Reset self-view to placeholder
                if self.my_video_label.winfo_exists():
                    main_app = self.my_video_label.winfo_toplevel() # Get MainApplication
                    if hasattr(main_app, 'my_camera_off_placeholder'):
                        self.my_video_label.config(image=main_app.my_camera_off_placeholder)
                        self.my_video_label.image = main_app.my_camera_off_placeholder
            except Exception: pass # Ignore UI errors on close


    def _receive_video_loop(self):
        BUFFER_SIZE = 66000
        while running and self._running:
            try:
                data, _ = self.client_socket.recvfrom(BUFFER_SIZE);
                if b'::' not in data: continue
                username_bytes, frame_bytes = data.split(b'::', 1); username = username_bytes.decode('utf-8','ignore')
                if username == self.username: continue
                self.last_frame_time[username] = time.time()
                np_data = np.frombuffer(frame_bytes, dtype=np.uint8); frame = cv2.imdecode(np_data, 1)
                if frame is not None: img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)); self.image_queue.put((username, img_pil))
            except socket.error: pass # Ignore socket errors on close
            except Exception: pass
        print("[VIDEO] Receiving stopped.")

    # [MODIFIED] This function now handles adding/updating labels and flagging for a grid rebuild.
    def _process_image_queue(self):
        if not self._running or not self.gallery_frame.winfo_exists(): return
        try:
            new_participant_added = False
            while not self.image_queue.empty():
                username, img_pil = self.image_queue.get_nowait()
                label = self.participant_labels.get(username)
                
                if not label or not label.winfo_exists():
                    if username in self.participant_labels: del self.participant_labels[username]
                    # Create the label but don't pack or grid it yet
                    label = tk.Label(self.gallery_frame, bg="black", text=username, fg="white", compound=tk.CENTER); 
                    self.participant_labels[username] = label
                    new_participant_added = True # Flag that we need to rebuild the grid

                # Update the image (this happens for new *and* existing users)
                # Resize to a reasonable default, the grid will stretch it
                img = img_pil.resize((320, 240), Image.LANCZOS); img_tk = ImageTk.PhotoImage(image=img)
                if label.winfo_exists(): 
                    label.config(image=img_tk, text=""); label.image = img_tk
            
            if new_participant_added:
                self._update_gallery_grid() # Rebuild the grid if we added someone

        except queue.Empty: pass
        except Exception as e: print(f"[VIDEO GUI] Error: {e}")
        self.gallery_frame.after(50, self._process_image_queue)

    # [NEW] This method rebuilds the entire gallery grid
    def _update_gallery_grid(self):
        if not self.gallery_frame.winfo_exists():
            return
            
        # Clear all existing widgets from the grid
        for widget in self.gallery_frame.winfo_children():
            widget.grid_forget() # Use grid_forget to remove from grid

        num_participants = len(self.participant_labels)
        if num_participants == 0:
            return

        # Calculate grid dimensions
        cols = int(math.ceil(math.sqrt(num_participants)))
        rows = int(math.ceil(num_participants / cols)) if cols > 0 else 0

        # Configure rows and columns to have equal weight
        for i in range(rows):
            self.gallery_frame.grid_rowconfigure(i, weight=1)
        for i in range(cols):
            self.gallery_frame.grid_columnconfigure(i, weight=1)

        # Re-add all labels to the grid
        r, c = 0, 0
        for label in self.participant_labels.values():
            if label.winfo_exists():
                label.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
                c += 1
                if c >= cols:
                    c = 0
                    r += 1

    def _check_stale_participants_loop(self):
        while running and self._running:
            now = time.time(); stale_users = [user for user, t in self.last_frame_time.items() if now - t > 5.0]
            for user in stale_users: 
                # Schedule removal on main thread
                self.gallery_frame.after(0, self.remove_participant, user) 
            time.sleep(2)

    # [MODIFIED] This function now triggers a grid update after removing a user.
    def remove_participant(self, username):
        if username not in self.participant_labels: # Fix for race condition
             return
        label = self.participant_labels.pop(username, None)
        if label and label.winfo_exists(): 
            label.destroy() # Destroy the widget completely
        
        # Update the grid since a user was removed
        try:
            if self.gallery_frame.winfo_exists():
                self._update_gallery_grid() # Rebuild the grid
        except tk.TclError:
            pass # Frame might be closing
        print(f"[VIDEO] Removed stale participant: {username}")

    def stop(self):
        """Stops all client activity (sending and receiving)."""
        if not self._running: return
        self._running = False
        self._sending = False
        if self.cap: self.cap.release(); self.cap = None
        if self.client_socket: self.client_socket.close(); self.client_socket = None
        try: self.gallery_frame.after(0, self._clear_gallery)
        except tk.TclError: pass
        print("[VIDEO] Client stopped (Full).")

    # [MODIFIED] This function just destroys widgets; grid is rebuilt on add/remove.
    def _clear_gallery(self):
        for label in self.participant_labels.values():
            if label.winfo_exists(): label.destroy()
        self.participant_labels.clear()


# --- ScreenShareClient Class ---
class ScreenShareClient:
    def __init__(self, remote_video_label, server_host):
        self.remote_video_label = remote_video_label; self.sock = None; self.server_host = server_host
        self._is_presenting = False; self._is_viewing = False
    def start_presenting(self):
        if self.sock: messagebox.showwarning("Screen Share", "Already connected."); return False
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); self.sock.connect((self.server_host, SCREEN_PORT)); self.sock.sendall(b'PRESENTER')
            print("[SCREEN] Starting as PRESENTER."); self._is_presenting = True; threading.Thread(target=self._send_screen_loop, daemon=True).start(); return True
        except Exception as e: messagebox.showerror("Screen Share Error", f"Could not connect as presenter:\n{e}"); self.stop(); return False
    def _send_screen_loop(self):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1] # Primary monitor
                while running and self.sock and self._is_presenting:
                    try:
                        sct_img = sct.grab(monitor); img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX"); frame = np.array(img); frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 70] ; result, encoded_frame = cv2.imencode('.jpg', frame, encode_param); data = encoded_frame.tobytes()
                        len_prefix = struct.pack('!I', len(data)); self.sock.sendall(len_prefix + data); time.sleep(0.05) # Adjust sleep for desired FPS
                    except (ConnectionResetError, BrokenPipeError): break
                    except Exception as e_inner: print(f"Screen send inner loop error: {e_inner}"); time.sleep(1); break # Prevent rapid error loops
        except Exception as e_outer: print(f"Screen send outer loop error: {e_outer}")
        finally: print("[SCREEN] Presenting stopped."); self.stop()
    def start_viewing(self):
        if self.sock: messagebox.showwarning("Screen Share", "Already connected."); return False
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); self.sock.connect((self.server_host, SCREEN_PORT)); self.sock.sendall(b'VIEWER')
            print("[SCREEN] Starting as VIEWER."); self._is_viewing = True; threading.Thread(target=self._receive_screen_loop, daemon=True).start(); return True
        except Exception as e: messagebox.showerror("Screen Share Error", f"Could not connect as viewer:\n{e}"); self.stop(); return False
    def _receive_screen_loop(self):
        while running and self.sock and self._is_viewing:
            try:
                len_data = self.sock.recv(4);
                if not len_data or len(len_data) < 4: break
                frame_size = struct.unpack('!I', len_data)[0];
                if frame_size <= 0 or frame_size > 20 * 1024 * 1024: break # Sanity check
                frame_data = b''
                while len(frame_data) < frame_size:
                    chunk = self.sock.recv(min(4096, frame_size - len(frame_data)));
                    if not chunk: break
                    frame_data += chunk
                if len(frame_data) != frame_size: break
                np_data = np.frombuffer(frame_data, dtype=np.uint8); frame = cv2.imdecode(np_data, 1)
                if frame is not None:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB); img = Image.fromarray(frame_rgb)
                    try: # Protect UI updates
                        if not self.remote_video_label.winfo_exists(): break
                        target_w = self.remote_video_label.winfo_width(); target_h = self.remote_video_label.winfo_height()
                        if target_w < 10 or target_h < 10: continue
                        w, h = img.size; ratio = min(target_w / w, target_h / h); new_size = (int(w * ratio), int(h * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                        new_img = Image.new("RGB", (target_w, target_h), "black"); new_img.paste(img, ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2))
                        img_tk = ImageTk.PhotoImage(image=new_img)
                        self.remote_video_label.config(image=img_tk); self.remote_video_label.image = img_tk
                    except Exception: pass # Ignore UI errors
            except (ConnectionResetError, BrokenPipeError): break
            except Exception: pass
        print("[SCREEN] Receiving stopped."); self.stop()
    def stop(self):
        self._is_presenting = False; self._is_viewing = False # Set flags first
        if self.sock:
            try: self.sock.shutdown(socket.SHUT_RDWR) # More forceful shutdown
            except Exception: pass
            try: self.sock.close()
            except Exception: pass
            self.sock = None
        print("[SCREEN] Client stopped.")


# --- MainApplication Class ---
# [MODIFIED] This class is updated to change the collaboration view logic.
class MainApplication(tk.Tk):
    def __init__(self, server_ip):
        super().__init__(); self.title("LAN Collaboration Suite"); self.geometry("1400x800"); self.configure(bg=PRIMARY_BG)
        self.server_host = server_ip; self.username = None
        while not self.username:
            self.username = simpledialog.askstring("Username", "Please enter your username:", parent=self)
            if self.username is None: self.destroy(); return
            self.username = self.username.strip()
            if not self.username: messagebox.showwarning("Invalid Username", "Username cannot be empty.")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        try:
            self.profile_pic_default = create_icon_image(40, "#555555", text_label=self.username[0].upper())
            self.app_icon_default = create_icon_image(60, ACCENT_COLOR, text_label='L', shape='square')
        except Exception as e: print(f"Warning: Could not create default icons: {e}"); self.profile_pic_default = None; self.app_icon_default = None
        self.audio_client = None; self.video_client = None; self.screen_client = None; self.chat_client = None; self.file_client_view = None
        self.my_camera_off_placeholder = self._create_video_placeholder(400, 300, "Camera Off")
        self.remote_stream_off_placeholder = self._create_video_placeholder(800, 600, "No Stream")
        self.sidebar_panel_visible = False; self.sidebar_content_type = None; self.collab_sidebar_frame = None
        self.main_display_pane = None; self.participants_list_widget = None; self.current_view_frame = None
        self.current_status = tk.StringVar(value="Online")
        self._setup_styles(); self._create_widgets()
        self.chat_view_frame = Frame(self.content_frame, bg=PRIMARY_BG)
        self.chat_client = ChatClient(self.chat_view_frame, self.username, self.server_host)
        if not self.chat_client or not self.chat_client.sock:
            print("Chat client failed, stopping MainApplication init.")
            if self.winfo_exists(): self.destroy()
            return
        self.show_chat_view(); self._update_status_bar()
    def _create_video_placeholder(self, width, height, text):
        try: img = Image.new('RGB', (width, height), color=SIDEBAR_BG); draw = ImageDraw.Draw(img)
        except Exception as e: print(f"Error creating placeholder image: {e}"); return None
        try: font = ImageFont.truetype("arial.ttf", int(width*0.05))
        except IOError:
            try: font = ImageFont.truetype("DejaVuSans.ttf", int(width*0.05))
            except IOError: font = ImageFont.load_default()
        text_bbox=draw.textbbox((0,0),text,font=font); tw=text_bbox[2]-text_bbox[0]; th=text_bbox[3]-text_bbox[1]
        draw.text(((width-tw)/2,(height-th)/2), text, fill=MESSAGE_SYS_FG, font=font); return ImageTk.PhotoImage(image=img)
    def _setup_styles(self):
        self.style = ttk.Style(self); self.style.theme_use('clam')
        self.style.configure("TButton", background=SIDEBAR_BG, foreground=TEXT_COLOR, font=("Arial", 10), relief="flat", padding=[15, 10], anchor="w", borderwidth=0, highlightthickness=0)
        self.style.map("TButton", background=[('active', ACCENT_COLOR)], foreground=[('active', 'white')])
        self.style.configure("Active.TButton", background=ACCENT_COLOR, foreground="white", font=("Arial", 10, "bold"), relief="flat", padding=[15, 10])
        self.style.configure("Red.TButton", background=BUTTON_RED, foreground="white", font=("Arial", 10, "bold"), relief="flat", padding=[10, 8])
        self.style.map("Red.TButton", background=[('active', BUTTON_RED_ACTIVE)])
        self.style.configure("TEntry", fieldbackground=CHAT_INPUT_BG, foreground=TEXT_COLOR, bordercolor="#555555", lightcolor="#555555", darkcolor="#555555", relief="flat", padding=5, insertcolor=TEXT_COLOR)
        self.style.configure("TSash", background=PRIMARY_BG, bordercolor=PRIMARY_BG, gripcount=0, sashthickness=6)
        self.style.configure("Green.Horizontal.TProgressbar", troughcolor=SIDEBAR_BG, background=ACCENT_COLOR, bordercolor=SIDEBAR_BG, lightcolor=SIDEBAR_BG, darkcolor=SIDEBAR_BG)
    def _create_widgets(self):
        self.paned_window = PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=5, bg=PRIMARY_BG, relief="flat", bd=0, sashrelief="flat"); self.paned_window.pack(fill=tk.BOTH, expand=True)
        self.sidebar = Frame(self.paned_window, width=200, bg=SIDEBAR_BG); self.paned_window.add(self.sidebar, minsize=180)
        self._create_sidebar_content()
        self.content_frame = Frame(self.paned_window, bg=PRIMARY_BG); self.paned_window.add(self.content_frame); self.paned_window.sash_place(0, 200, 0)
        self.active_sidebar_button = None
        self.status_bar = tk.Label(self, text="", bd=1, relief="flat", anchor=tk.W, bg=SIDEBAR_BG, fg=TEXT_COLOR, padx=10, pady=5); self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    def _create_sidebar_content(self):
        profile_frame = Frame(self.sidebar, bg=SIDEBAR_BG, pady=10); profile_frame.pack(fill=tk.X)
        if self.profile_pic_default: tk.Label(profile_frame, image=self.profile_pic_default, bg=SIDEBAR_BG).pack(pady=(0, 5))
        user_status_frame = Frame(profile_frame, bg=SIDEBAR_BG); user_status_frame.pack()
        tk.Label(user_status_frame, text=self.username, font=("Arial", 12, "bold"), bg=SIDEBAR_BG, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=(0, 5))
        status_menu_button = tk.Menubutton(user_status_frame, textvariable=self.current_status, bg=SIDEBAR_BG, fg=TEXT_COLOR, activebackground=ACCENT_COLOR, relief="flat", bd=0, indicatoron=False, pady=0, padx=5, font=("Arial", 9)); status_menu = Menu(status_menu_button, tearoff=0, bg=CHAT_INPUT_BG, fg=TEXT_COLOR); status_menu_button.config(menu=status_menu); status_menu.add_radiobutton(label="Online", variable=self.current_status, value="Online", command=self.update_status); status_menu.add_radiobutton(label="Away", variable=self.current_status, value="Away", command=self.update_status); status_menu_button.pack(side=tk.LEFT)
        self.nav_buttons = {}; ttk.Separator(self.sidebar, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)
        self._add_nav_button("Chat", self.show_chat_view); self._add_nav_button("Call / Share", self.show_collaboration_view); self._add_nav_button("Files", self.show_file_view); self._add_nav_button("Settings", self.show_settings_view)
        quit_button = ttk.Button(self.sidebar, text="Quit", command=self.on_closing, style="Red.TButton"); quit_button.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
    def _add_nav_button(self, text, command): btn_text = f"  {text}"; btn = ttk.Button(self.sidebar, text=btn_text, command=command, style="TButton"); btn.pack(fill=tk.X, padx=10, pady=2); self.nav_buttons[text] = btn
    def _switch_view(self, new_view_func, button_text):
        if self.current_view_frame:
            if self.current_view_frame == self.chat_view_frame: self.current_view_frame.pack_forget()
            else: self.current_view_frame.pack_forget(); self.current_view_frame.destroy()
        if self.active_sidebar_button: self.active_sidebar_button.config(style="TButton")
        self.active_sidebar_button = self.nav_buttons[button_text]; self.active_sidebar_button.config(style="Active.TButton")
        if new_view_func == self._create_chat_view_content: self.chat_view_frame.pack(fill=tk.BOTH, expand=True); self.current_view_frame = self.chat_view_frame; self._create_chat_view_content(None)
        else:
            if self.sidebar_panel_visible and self.main_display_pane and self.collab_sidebar_frame:
                try: self.main_display_pane.remove(self.collab_sidebar_frame)
                except tk.TclError: pass
            self.sidebar_panel_visible = False; self.sidebar_content_type = None
            if self.chat_client: self.chat_client.set_external_user_list(None)
            self.main_display_pane = None; self.collab_sidebar_frame = None; self.participants_list_widget = None
            
            # --- [MODIFIED] Clean up old clients when switching views ---
            if self.video_client: self.video_client.stop(); self.video_client = None
            if self.audio_client: self.audio_client.stop(); self.audio_client = None
            if self.screen_client: self.screen_client.stop(); self.screen_client = None
            
            new_frame = Frame(self.content_frame, bg=PRIMARY_BG); new_frame.pack(fill=tk.BOTH, expand=True); self.current_view_frame = new_frame; new_view_func(new_frame)
    def _update_status_bar(self):
        try:
            status_text = f"Connected: {self.server_host} | User: {self.username} ({self.current_status.get()})"
            if self.audio_client and self.audio_client._running: status_text += " | Audio ON"
            # [MODIFIED] Check _sending flag for video
            if self.video_client and self.video_client._sending: status_text += " | Video ON"
            if self.screen_client:
                if self.screen_client._is_presenting: status_text += " | Presenting"
                elif self.screen_client._is_viewing: status_text += " | Viewing Screen"
            self.status_bar.config(text=status_text); self.after(1000, self._update_status_bar)
        except tk.TclError: pass
    def show_chat_view(self, parent_frame=None): self._switch_view(self._create_chat_view_content, "Chat")
    def _create_chat_view_content(self, parent_frame):
        if self.chat_client: self.chat_client.set_external_user_list(None)
    def show_collaboration_view(self, parent_frame=None): self._switch_view(self._create_collaboration_view_content, "Call / Share")
    
    # [MODIFIED] This function is heavily changed
    def _create_collaboration_view_content(self, parent_frame):
        top_control_bar = Frame(parent_frame, bg=SIDEBAR_BG, height=60); top_control_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 5)); top_control_bar.pack_propagate(False)
        self.main_display_pane = PanedWindow(parent_frame, orient=tk.HORIZONTAL, sashwidth=6, bg=PRIMARY_BG, relief="flat", bd=0, sashrelief="flat"); self.main_display_pane.pack(fill=tk.BOTH, expand=True)
        video_frame = Frame(self.main_display_pane, bg="#1A1A1A"); self.main_display_pane.add(video_frame, stretch="always")
        
        # --- NEW DEFAULT: Pack gallery_frame first ---
        self.gallery_frame = Frame(video_frame, bg="#1A1A1A")
        # [MODIFIED] Use .grid instead of .pack for the gallery frame itself
        self.gallery_frame.grid(row=0, column=0, sticky="nsew") 
        
        # Configure the main video_frame's grid
        video_frame.grid_rowconfigure(0, weight=1)
        video_frame.grid_columnconfigure(0, weight=1)

        # --- Create remote_video_label (for screen share) but DO NOT grid it ---
        self.remote_video_label = tk.Label(video_frame, bg="black", image=self.remote_stream_off_placeholder); self.remote_video_label.image = self.remote_stream_off_placeholder
        
        # --- Self-view is placed on top of everything ---
        self.my_video_label = tk.Label(video_frame, bg="black", image=self.my_camera_off_placeholder); self.my_video_label.image = self.my_camera_off_placeholder; self.my_video_label.place(relx=0.98, rely=0.98, anchor='se', relwidth=0.25, relheight=0.25)
        
        self.collab_sidebar_frame = Frame(self.main_display_pane, bg=SIDEBAR_BG, width=250); self.sidebar_panel_visible = False
        btn_props = {"bg": SIDEBAR_BG, "activebackground": "#555555", "fg": TEXT_COLOR, "activeforeground": "white", "relief": "flat", "bd": 0, "highlightthickness": 0, "font": ("Arial", 10), "padx": 10, "pady": 5}
        self.call_timer_label = tk.Label(top_control_bar, text="00:00", font=("Arial", 12), bg=SIDEBAR_BG, fg=TEXT_COLOR); self.call_timer_label.pack(side=tk.LEFT, padx=20, pady=10)
        self.hangup_button = tk.Button(top_control_bar, text="End Call", command=self.hang_up_call, bg=BUTTON_RED, fg="white", activebackground=BUTTON_RED_ACTIVE, activeforeground="white", relief="flat", bd=0, highlightthickness=0, font=("Arial", 10, "bold"), padx=15, pady=5); self.hangup_button.pack(side=tk.RIGHT, padx=20, pady=10)
        center_frame = Frame(top_control_bar, bg=SIDEBAR_BG); center_frame.pack(side=tk.TOP, expand=True, fill=tk.X, pady=5)
        button_container = Frame(center_frame, bg=SIDEBAR_BG); button_container.pack()
        self.cam_button = tk.Button(button_container, text="Camera Off", command=self.toggle_video_call, width=10, **btn_props); self.cam_button.pack(side=tk.LEFT, padx=5)
        self.mic_button = tk.Button(button_container, text="Mic Off", command=self.toggle_audio_call, width=8, **btn_props); self.mic_button.pack(side=tk.LEFT, padx=5)
        self.share_button = tk.Button(button_container, text="Share", command=self.toggle_sharing_mode, width=8, **btn_props); self.share_button.pack(side=tk.LEFT, padx=5)
        ttk.Separator(button_container, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=5)
        self.chat_button = tk.Button(button_container, text="Chat", command=self.toggle_chat_panel, width=8, **btn_props); self.chat_button.pack(side=tk.LEFT, padx=5)
        self.participants_button = tk.Button(button_container, text="Users", command=self.toggle_participants_panel, width=8, **btn_props); self.participants_button.pack(side=tk.LEFT, padx=5)
        
        # --- Start VideoClient in receive-only mode ---
        self.video_client = VideoClient(self.my_video_label, self.gallery_frame, self.server_host, self.username)
        self.video_client.start()
        
        self._update_cam_button_state(False); self._update_mic_button_state(False); self._update_share_button_state(False)

    def show_file_view(self, parent_frame=None): self._switch_view(self._create_file_view_content, "Files")
    def _create_file_view_content(self, parent_frame):
        if self.file_client_view is not None: self.file_client_view.on_closing()
        self.file_client_view = FileClientView(parent_frame, self.server_host)
    def show_settings_view(self, parent_frame=None): self._switch_view(self._create_settings_view_content, "Settings")
    def _create_settings_view_content(self, parent_frame):
        header_frame = Frame(parent_frame, bg=CHAT_HEADER_BG); header_frame.pack(fill=tk.X, pady=(0, 10)); tk.Label(header_frame, text="Settings", font=("Arial", 16, "bold"), bg=CHAT_HEADER_BG, fg=TEXT_COLOR).pack(pady=10)
        sf = Frame(parent_frame, bg=PRIMARY_BG); sf.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        tk.Label(sf, text="Configuration:", font=("Arial", 12, "bold"), bg=PRIMARY_BG, fg=TEXT_COLOR, anchor='w').pack(pady=(0,5), fill='x')
        tk.Label(sf, text=f"Username: {self.username}", bg=PRIMARY_BG, fg=TEXT_COLOR, anchor='w').pack(fill='x')
        tk.Label(sf, text=f"Server: {self.server_host}", bg=PRIMARY_BG, fg=TEXT_COLOR, anchor='w').pack(fill='x')
        tk.Label(sf, text=f"Download Location: {os.path.abspath(DOWNLOAD_DIR)}", bg=PRIMARY_BG, fg=TEXT_COLOR, anchor='w').pack(pady=(5,0), fill='x')
        ttk.Button(sf, text="Open Download Folder", command=lambda: self.open_folder(DOWNLOAD_DIR)).pack(pady=10)
    def open_folder(self, path):
        try:
            abs_path = os.path.abspath(path) # Ensure path is absolute
            if not os.path.exists(abs_path): os.makedirs(abs_path) # Create if it doesn't exist
            if platform.system() == "Windows": os.startfile(abs_path)
            elif platform.system() == "Darwin": subprocess.run(["open", abs_path], check=True)
            else: subprocess.run(["xdg-open", abs_path], check=True)
        except Exception as e: messagebox.showerror("Error", f"Could not open folder:\n{e}")
    def _update_cam_button_state(self, is_on): self.cam_button.config(text="Camera On" if is_on else "Camera Off", fg=ACCENT_COLOR if is_on else TEXT_COLOR)
    def _update_mic_button_state(self, is_on): self.mic_button.config(text="Mic On" if is_on else "Mic Off", fg=ACCENT_COLOR if is_on else TEXT_COLOR)
    def _update_share_button_state(self, is_sharing): self.share_button.config(text="Stop Share" if is_sharing else "Share", fg=ACCENT_COLOR if is_sharing else TEXT_COLOR)
    def toggle_audio_call(self):
        if self.audio_client and self.audio_client._running: self.audio_client.stop(); self.audio_client = None; self._update_mic_button_state(False)
        else: self.audio_client = AudioClient(self.server_host);
        if self.audio_client.start(): self._update_mic_button_state(True)
        else: self.audio_client = None; self._update_mic_button_state(False)

    # [MODIFIED] This function now controls sending, not the view
    def toggle_video_call(self):
        if not self.video_client: # Should not happen in this view
            print("Video client not initialized.")
            return

        if self.video_client._sending:
            # Stop sending
            self.video_client.stop_sending()
            self._update_cam_button_state(False)
        else:
            # Start sending
            if self.video_client.start_sending():
                self._update_cam_button_state(True)
            else:
                # start_sending failed (e.g., no camera)
                self._update_cam_button_state(False)

    def toggle_sharing_mode(self):
        if self.screen_client: self.stop_sharing_call()
        else: answer = messagebox.askquestion("Screen Share", "Present screen (Yes) or View screen (No)?", icon='question', type='yesno');
        if answer == 'yes': self.start_presenting_call()
        elif answer == 'no': self.start_viewing_call()
        # Do nothing if user closes dialog

    # [MODIFIED] This function now hides the gallery and shows the stream
    def start_presenting_call(self):
        if self.video_client: 
            self.video_client.stop() # Stop all video
            self.video_client = None
        self.gallery_frame.grid_forget() # Hide gallery
        self.remote_video_label.grid(row=0, column=0, sticky="nsew") # Show stream
        
        self.screen_client = ScreenShareClient(self.remote_video_label, self.server_host)
        if self.screen_client.start_presenting(): 
            self._update_share_button_state(True)
            self.cam_button.config(state=tk.DISABLED)
            self._update_cam_button_state(False) # Ensure cam button is 'off'

    # [MODIFIED] This function now hides the gallery and shows the stream
    def start_viewing_call(self):
        if self.video_client: 
            self.video_client.stop() # Stop all video
            self.video_client = None
        self.gallery_frame.grid_forget() # Hide gallery
        self.remote_video_label.grid(row=0, column=0, sticky="nsew") # Show stream

        self.screen_client = ScreenShareClient(self.remote_video_label, self.server_host)
        if self.screen_client.start_viewing(): 
            self._update_share_button_state(True)
            self.cam_button.config(state=tk.DISABLED)
            self._update_cam_button_state(False) # Ensure cam button is 'off'

    # [MODIFIED] This function now hides the stream and shows the gallery
    def stop_sharing_call(self):
        if self.screen_client: 
            self.screen_client.stop()
            self.screen_client = None
        
        self._update_share_button_state(False)
        self.cam_button.config(state=tk.NORMAL)
        
        self.remote_video_label.grid_forget() # Hide the stream label
        self.remote_video_label.config(image=self.remote_stream_off_placeholder) # Reset it
        self.remote_video_label.image = self.remote_stream_off_placeholder
        
        self.gallery_frame.grid(row=0, column=0, sticky="nsew") # Show gallery again
        
        # Restart the video client in receiving mode
        if not self.video_client:
            self.video_client = VideoClient(self.my_video_label, self.gallery_frame, self.server_host, self.username)
            self.video_client.start()
        
        # Ensure buttons are in correct 'off' state
        self._update_cam_button_state(False)
        # self._update_mic_button_state(False) # Don't assume mic state

    # [MODIFIED] This function stops all *outgoing* streams
    def hang_up_call(self):
        if self.audio_client: 
            self.audio_client.stop()
            self.audio_client = None
            self._update_mic_button_state(False)
            
        if self.screen_client: 
            self.stop_sharing_call() # This handles stopping screen and restarting video
        elif self.video_client and self.video_client._sending:
            self.video_client.stop_sending() # Just stop sending our camera
            self._update_cam_button_state(False)

    def _clear_sidebar_panel(self):
        if not self.collab_sidebar_frame: return;
        for widget in self.collab_sidebar_frame.winfo_children(): widget.destroy()
        if self.chat_client: self.chat_client.set_external_user_list(None); self.participants_list_widget = None
    def toggle_participants_panel(self):
        if not self.main_display_pane or not self.collab_sidebar_frame: return
        if self.sidebar_panel_visible and self.sidebar_content_type == 'participants':
            try: self.main_display_pane.remove(self.collab_sidebar_frame)
            except tk.TclError: pass
            self.sidebar_panel_visible = False; self.sidebar_content_type = None; self._clear_sidebar_panel()
        else:
            self._clear_sidebar_panel(); tk.Label(self.collab_sidebar_frame, text="Participants", font=("Arial", 12, "bold"), bg=SIDEBAR_BG, fg=TEXT_COLOR).pack(pady=10)
            self.participants_list_widget = tk.Listbox(self.collab_sidebar_frame, bg=SIDEBAR_BG, fg=TEXT_COLOR, selectbackground=ACCENT_COLOR, selectforeground="white", bd=0, relief="flat", exportselection=False, highlightthickness=0); self.participants_list_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            if self.chat_client: self.chat_client.set_external_user_list(self.participants_list_widget) # Populate
            if not self.sidebar_panel_visible:
                try: self.main_display_pane.add(self.collab_sidebar_frame, minsize=200, stretch="never")
                except tk.TclError: print("Error adding sidebar frame"); return
            self.sidebar_panel_visible = True; self.sidebar_content_type = 'participants'
    def toggle_chat_panel(self):
        if self.chat_client:
             window = self.chat_client.open_chat_windows.get("PUBLIC CHAT")
             if window and window.winfo_exists(): window.lift(); window.focus_force()
             else: ChatWindow(self, "PUBLIC CHAT", self.chat_client, self) # Pass self (MainApplication)
    def update_status(self):
        new_status = self.current_status.get(); print(f"Setting status to: {new_status}")
        if self.chat_client: self.chat_client.send_status_update(new_status)
    def on_closing(self):
        global running; running = False
        print("Closing application...")
        if self.audio_client: self.audio_client.stop()
        if self.video_client: self.video_client.stop()
        if self.screen_client: self.screen_client.stop()
        if self.chat_client: self.chat_client.on_closing()
        if self.file_client_view: self.file_client_view.on_closing()
        time.sleep(0.1)
        if self.winfo_exists(): self.destroy()
        print("Goodbye.")

# --- Server Discovery Function ---
# [MODIFIED] Removed the automatic find_server() function.
# The server IP will be requested manually at startup.

# --- Main Execution ---
if __name__ == "__main__":
    # Create a temporary root window for the dialogs
    temp_root = tk.Tk()
    temp_root.withdraw() # Hide the root window

    SERVER_HOST = None
    while not SERVER_HOST:
        SERVER_HOST = simpledialog.askstring(
            "Server IP", 
            "Please enter the server's IP address:",
            parent=temp_root
        )
        if SERVER_HOST is None: # User clicked cancel
            print("Exiting: No server IP provided.")
            temp_root.destroy()
            exit()
        SERVER_HOST = SERVER_HOST.strip()
        if not SERVER_HOST:
             messagebox.showwarning("Invalid IP", "IP address cannot be empty.", parent=temp_root)
    
    # Destroy the temporary root window now that we have the IP
    temp_root.destroy()

    if SERVER_HOST:
        app = MainApplication(SERVER_HOST)
        # Check if app initialization was stopped (e.g., user cancel, connection fail)
        # Use hasattr to safely check if chat_client was even created
        if app.winfo_exists() and hasattr(app, 'chat_client') and app.chat_client and app.chat_client.sock:
            try:
                app.mainloop()
            except KeyboardInterrupt:
                print("\nKeyboardInterrupt detected. Closing application...")
                app.on_closing()
        else:
            print("Exiting: App initialization failed or was cancelled.")
            # Ensure Tkinter root window is destroyed if it exists but mainloop wasn't called
            if app.winfo_exists():
                app.destroy()
    else:
        # This case is less likely now but good to keep
        print("Exiting: No server IP.")