import tkinter as tk
from tkinter import ttk, messagebox
import threading
import ctypes
import numpy as np
import pyaudiowpatch as pyaudio
import json
import os

# ==========================================
# Part 1: Controller Vibration (XInput)
# ==========================================
try:
    xinput = ctypes.windll.xinput1_4
except AttributeError:
    xinput = ctypes.windll.xinput1_3

class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", ctypes.c_ushort),
                ("wRightMotorSpeed", ctypes.c_ushort)]

def set_vibration(user_index, left_speed, right_speed):
    vibration = XINPUT_VIBRATION(int(left_speed), int(right_speed))
    return xinput.XInputSetState(user_index, ctypes.byref(vibration)) == 0

def stop_vibration(user_index):
    set_vibration(user_index, 0, 0)

# ==========================================
# Part 2: Game Presets
# ==========================================
# Format: (threshold, sensitivity, strength, transient_ratio, bass_w, mid_w, treble_w, decay, cooldown)
GAME_PRESETS = {
    "Shooter (FPS)": (0.025, 180.0, 90, 2.0, 0.5, 0.8, 0.9, 0.12, 40),
    "Racing": (0.040, 220.0, 95, 1.5, 0.9, 0.4, 0.3, 0.08, 30),
    "Custom Settings": None
}

# ==========================================
# Part 3: Audio Processing & Learning Engine
# ==========================================
class AudioReactiveController:
    def __init__(self):
        self.is_running = False
        self.current_volume = 0.0
        
        # Core parameters
        self.threshold = 0.025
        self.sensitivity = 180.0
        self.strength = 90
        
        # Advanced parameters
        self.transient_ratio = 2.0
        self.bass_weight = 0.5
        self.mid_weight = 0.8      
        self.treble_weight = 0.9
        self.decay_speed = 0.12
        self.cooldown_ms = 40

        self.controller_id = 0
        self.recorder_thread = None
        self.audio_interface = None
        self.stream = None
        self.is_device_found = False

        # Internal states
        self._peak_history = []
        self._history_size = 15
        self._current_vibe = 0.0
        self._cooldown_counter = 0
        self._lock = threading.Lock()

        # Calibration states
        self.is_calibrating = False
        self.recorded_audio_buffer = []
        self.last_test_vibration = 0

        try:
            self.audio_interface = pyaudio.PyAudio()
            self.loopback_device = self.audio_interface.get_default_wasapi_loopback()
            self.is_device_found = True
        except Exception as e:
            print(f"Error finding Loopback device: {e}")
            self.is_device_found = False

        self.load_calibration()

    def _analyze_frequency_bands(self, audio_data, sample_rate):
        n = len(audio_data)
        if n < 256: return 0.0, 0.0, 0.0

        fft_data = np.fft.rfft(audio_data)
        fft_magnitude = np.abs(fft_data)
        freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

        bass_mask = (freqs >= 20) & (freqs <= 150)
        bass_energy = np.mean(fft_magnitude[bass_mask]) if np.any(bass_mask) else 0

        mid_mask = (freqs > 150) & (freqs <= 2000)
        mid_energy = np.mean(fft_magnitude[mid_mask]) if np.any(mid_mask) else 0

        treble_mask = (freqs > 2000) & (freqs <= 8000)
        treble_energy = np.mean(fft_magnitude[treble_mask]) if np.any(treble_mask) else 0

        max_possible = n * 32768.0
        return bass_energy/max_possible, mid_energy/max_possible, treble_energy/max_possible

    def _detect_transient(self, current_peak):
        self._peak_history.append(current_peak)
        if len(self._peak_history) > self._history_size:
            self._peak_history.pop(0)
        if len(self._peak_history) < 5: return True
        prev_avg = np.mean(self._peak_history[:-1])
        if prev_avg < 0.001: prev_avg = 0.001
        return (current_peak / prev_avg) > self.transient_ratio

    def _audio_loop(self):
        try:
            sample_rate = int(self.loopback_device['defaultSampleRate'])
            self.stream = self.audio_interface.open(
                format=pyaudio.paInt16,
                channels=self.loopback_device['maxInputChannels'],
                rate=sample_rate,
                frames_per_buffer=1024,
                input=True,
                input_device_index=self.loopback_device['index']
            )

            while self.is_running:
                data = self.stream.read(1024, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                peak_norm = np.max(np.abs(audio_data)) / 32768.0

                # Calibration mode: record audio, but DO NOT skip vibration logic
                if self.is_calibrating:
                    self.recorded_audio_buffer.extend(audio_data.tolist())
                    max_samples = sample_rate * 15
                    if len(self.recorded_audio_buffer) > max_samples:
                        self.recorded_audio_buffer = self.recorded_audio_buffer[-max_samples:]

                bass, mid, treble = self._analyze_frequency_bands(audio_data, sample_rate)
                is_hit = self._detect_transient(peak_norm)

                if self._cooldown_counter > 0:
                    self._cooldown_counter -= 1

                target_vibe = 0.0
                if peak_norm > self.threshold and is_hit and self._cooldown_counter <= 0:
                    weighted_sound = (bass * self.bass_weight + mid * self.mid_weight + treble * self.treble_weight)
                    intensity = weighted_sound * self.sensitivity
                    final_strength = intensity * (self.strength / 100.0)
                    target_vibe = min(1.0, final_strength)

                    frames_cooldown = max(1, int(self.cooldown_ms / (1024 / sample_rate * 1000)))
                    self._cooldown_counter = frames_cooldown

                if target_vibe > self._current_vibe:
                    self._current_vibe = target_vibe
                else:
                    self._current_vibe *= (1.0 - self.decay_speed)
                    if self._current_vibe < 0.01: self._current_vibe = 0.0

                xinput_val = int(self._current_vibe * 65535)
                left_motor = xinput_val
                right_motor = int(xinput_val * 0.7)

                if xinput_val > 100:
                    set_vibration(self.controller_id, left_motor, right_motor)
                else:
                    stop_vibration(self.controller_id)

                with self._lock:
                    self.current_volume = float(peak_norm)

        except Exception as e:
            print(f"Error in audio loop: {e}")
            self.is_running = False
        finally:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None

    # --- Calibration Functions ---
    def start_calibration_recording(self):
        if not self.is_running: return
        self.is_calibrating = True
        self.recorded_audio_buffer = []

    def analyze_and_test_vibration(self):
        if not self.recorded_audio_buffer: return 0.0
        
        audio_np = np.array(self.recorded_audio_buffer, dtype=np.int16)
        sample_rate = int(self.loopback_device['defaultSampleRate'])
        
        fft_samples = sample_rate * 2
        fft_audio = audio_np[-fft_samples:] if len(audio_np) > fft_samples else audio_np
            
        bass, mid, treble = self._analyze_frequency_bands(fft_audio, sample_rate)
        weighted = (bass * self.bass_weight + mid * self.mid_weight + treble * self.treble_weight)
        intensity = weighted * self.sensitivity
        final_strength = intensity * (self.strength / 100.0)
        vibe_val = min(1.0, final_strength)
        
        if vibe_val < 0.15: vibe_val = 0.50 
            
        xinput_val = int(vibe_val * 65535)
        set_vibration(self.controller_id, xinput_val, int(xinput_val * 0.7))
        self.last_test_vibration = vibe_val
        
        threading.Timer(2.0, lambda: stop_vibration(self.controller_id)).start()
        return vibe_val

    def apply_feedback(self, feedback_type):
        if self.last_test_vibration == 0: return

        if feedback_type == 'weak':
            self.sensitivity = min(500, self.sensitivity * 1.3)
            self.strength = min(100, self.strength + 10)
        elif feedback_type == 'strong':
            self.sensitivity = max(10, self.sensitivity * 0.7)
            self.strength = max(0, self.strength - 10)

        self.save_calibration()

    def save_calibration(self):
        data = {
            "threshold": self.threshold, "sensitivity": self.sensitivity,
            "strength": self.strength, "transient_ratio": self.transient_ratio,
            "bass_weight": self.bass_weight, "mid_weight": self.mid_weight,
            "treble_weight": self.treble_weight, "decay_speed": self.decay_speed,
            "cooldown_ms": self.cooldown_ms
        }
        with open("calibration.json", "w") as f:
            json.dump(data, f, indent=4)

    def load_calibration(self):
        if os.path.exists("calibration.json"):
            try:
                with open("calibration.json", "r") as f:
                    data = json.load(f)
                    for key, val in data.items():
                        if hasattr(self, key): setattr(self, key, val)
            except Exception: pass

    def start(self):
        if self.is_running or not self.is_device_found: return
        self._peak_history.clear()
        self._current_vibe = 0.0
        self._cooldown_counter = 0
        self.is_running = True
        self.recorder_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self.recorder_thread.start()

    def stop(self):
        self.is_running = False
        if self.recorder_thread:
            self.recorder_thread.join(timeout=1.0)
            self.recorder_thread = None
        stop_vibration(self.controller_id)
        self.current_volume = 0.0

    def cleanup(self):
        if self.audio_interface:
            self.audio_interface.terminate()
            self.audio_interface = None

# ==========================================
# Part 4: Dark Mode User Interface (UI)
# ==========================================
class AppUI:
    def __init__(self, root, controller):
        self.root = root
        self.controller = controller
        
        # Dark Mode Color Palette
        self.BG_COLOR = "#121212"
        self.CARD_COLOR = "#1e1e2e"
        self.CARD_HOVER = "#2a2a3c"
        self.TEXT_COLOR = "#e0e0e0"
        self.SUBTEXT_COLOR = "#888899"
        self.ACCENT_COLOR = "#00d2ff"
        self.ACCENT_HOVER = "#00b4d8"
        self.RECORD_COLOR = "#ff4757"
        self.SUCCESS_COLOR = "#2ed573"
        self.WARNING_COLOR = "#ffa502"

        self.root.title("Smart Vibration Controller")
        self.root.geometry("580x850")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG_COLOR)

        # Initialize dictionary safely to prevent KeyError
        self.sliders = {} 
        
        self.setup_styles()
        self.setup_ui()
        self.update_ui_loop()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Global Frames & Labels
        style.configure("TFrame", background=self.BG_COLOR)
        style.configure("Card.TFrame", background=self.CARD_COLOR)
        style.configure("TLabel", background=self.BG_COLOR, foreground=self.TEXT_COLOR, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=self.CARD_COLOR, foreground=self.TEXT_COLOR)
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=self.ACCENT_COLOR, background=self.BG_COLOR)
        style.configure("Subtext.TLabel", font=("Segoe UI", 9, "italic"), foreground=self.SUBTEXT_COLOR, background=self.BG_COLOR)
        
        # Labelframes (Cards)
        style.configure("Card.TLabelframe", background=self.CARD_COLOR, borderwidth=0, relief="flat")
        style.configure("Card.TLabelframe.Label", background=self.CARD_COLOR, foreground=self.ACCENT_COLOR, font=("Segoe UI", 11, "bold"))

        # Progressbar
        style.configure("Cyan.Horizontal.TProgressbar", troughcolor=self.CARD_HOVER, background=self.ACCENT_COLOR, borderwidth=0, lightcolor=self.ACCENT_COLOR, darkcolor=self.ACCENT_COLOR)
        
        # Combobox Dark Mode Styling (Safe approach)
        style.configure("TCombobox", fieldbackground=self.CARD_COLOR, background=self.CARD_COLOR, foreground=self.TEXT_COLOR, bordercolor=self.CARD_HOVER, arrowcolor=self.TEXT_COLOR)
        style.map("TCombobox",
                  fieldbackground=[('readonly', self.CARD_COLOR), ('disabled', self.CARD_HOVER)],
                  foreground=[('readonly', self.TEXT_COLOR)],
                  background=[('readonly', self.CARD_COLOR)])

    def create_card(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, style="Card.TLabelframe", padding=15)
        return frame

    def create_button(self, parent, text, command, bg_color, fg_color, width=None):
        btn = tk.Button(parent, text=text, command=command, bg=bg_color, fg=fg_color,
                        activebackground=bg_color, activeforeground=fg_color,
                        relief="flat", font=("Segoe UI", 10, "bold"), cursor="hand2",
                        bd=0, padx=10, pady=8, width=width)
        
        # Hover effects
        def on_enter(e):
            if bg_color == self.ACCENT_COLOR:
                e.widget['bg'] = self.ACCENT_HOVER
            elif bg_color != self.CARD_HOVER:
                e.widget['bg'] = self.CARD_HOVER
        def on_leave(e):
            e.widget['bg'] = bg_color
            
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        ttk.Label(main_frame, text="AUDIO REACTIVE VIBRATION", style="Title.TLabel").pack(pady=(0, 5))
        ttk.Label(main_frame, text="Machine Learning Calibration Enabled", style="Subtext.TLabel").pack(pady=(0, 20))

        # --- Calibration Section ---
        cal_frame = self.create_card(main_frame, "  CALIBRATION & AUTO-LEARNING  ")
        cal_frame.pack(fill=tk.X, pady=(0, 15))
        
        btn_frame1 = tk.Frame(cal_frame, bg=self.CARD_COLOR)
        btn_frame1.pack(fill=tk.X, pady=(0, 10))

        self.btn_record = self.create_button(btn_frame1, "● START RECORDING", self.start_recording, self.RECORD_COLOR, "#ffffff")
        self.btn_record.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

        self.btn_stop_record = self.create_button(btn_frame1, "■ STOP & TEST", self.stop_recording_and_test, self.CARD_HOVER, self.TEXT_COLOR)
        self.btn_stop_record.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        self.btn_stop_record.config(state=tk.DISABLED)

        btn_frame2 = tk.Frame(cal_frame, bg=self.CARD_COLOR)
        btn_frame2.pack(fill=tk.X)

        self.btn_weak = self.create_button(btn_frame2, "Too Weak", lambda: self.give_feedback('weak'), self.CARD_HOVER, self.TEXT_COLOR)
        self.btn_weak.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        
        self.btn_perfect = self.create_button(btn_frame2, "Perfect", lambda: self.give_feedback('perfect'), self.SUCCESS_COLOR, "#121212")
        self.btn_perfect.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
        
        self.btn_strong = self.create_button(btn_frame2, "Too Strong", lambda: self.give_feedback('strong'), self.CARD_HOVER, self.TEXT_COLOR)
        self.btn_strong.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(3, 0))

        self.cal_status = tk.Label(cal_frame, text="Status: Ready to record", bg=self.CARD_COLOR, fg=self.SUBTEXT_COLOR, font=("Segoe UI", 9), anchor="w")
        self.cal_status.pack(fill=tk.X, pady=(10, 0))

        # --- Presets ---
        pf = self.create_card(main_frame, "  GAME PRESETS  ")
        pf.pack(fill=tk.X, pady=(0, 15))
        
        self.preset_combo = ttk.Combobox(pf, values=list(GAME_PRESETS.keys()), state="readonly", font=("Segoe UI", 10))
        self.preset_combo.current(0)
        self.preset_combo.pack(fill=tk.X, pady=5)
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_preset_change)

        # --- Sliders ---
        sf = self.create_card(main_frame, "  FINE TUNING  ")
        sf.pack(fill=tk.X, pady=(0, 15))

        sliders_config = [
            ("Threshold", "threshold", 0.005, 0.2, 3),
            ("Sensitivity", "sensitivity", 10, 500, 1),
            ("Final Strength %", "strength", 0, 100, 0),
            ("Mid Weight (Punch)", "mid_weight", 0.0, 2.0, 1),
        ]

        for i, (label, attr, from_, to_, decimals) in enumerate(sliders_config):
            row_frame = tk.Frame(sf, bg=self.CARD_COLOR)
            row_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(row_frame, text=label, bg=self.CARD_COLOR, fg=self.TEXT_COLOR, font=("Segoe UI", 10), width=18, anchor="w").pack(side=tk.LEFT)
            
            # Using tk.Scale for better dark mode control than ttk.Scale
            scale = tk.Scale(row_frame, from_=from_, to=to_, orient=tk.HORIZONTAL, 
                             bg=self.CARD_COLOR, fg=self.TEXT_COLOR, troughcolor=self.CARD_HOVER,
                             highlightthickness=0, sliderrelief="flat", length=250,
                             command=lambda v, a=attr, d=decimals: self._on_slider(v, a, d))
            scale.set(getattr(self.controller, attr))
            scale.pack(side=tk.LEFT, padx=10)
            
            val_label = tk.Label(row_frame, text=self._fmt(getattr(self.controller, attr), decimals), 
                                 bg=self.CARD_COLOR, fg=self.ACCENT_COLOR, font=("Consolas", 10, "bold"), width=6)
            val_label.pack(side=tk.RIGHT)
            
            self.sliders[attr] = (scale, val_label, decimals)

        # --- Volume Visualizer ---
        vol_frame = self.create_card(main_frame, "  AUDIO VISUALIZER  ")
        vol_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.vol_bar = ttk.Progressbar(vol_frame, orient=tk.HORIZONTAL, length=480, mode='determinate', style="Cyan.Horizontal.TProgressbar")
        self.vol_bar.pack(fill=tk.X, pady=5)
        
        self.vol_label = tk.Label(vol_frame, text="0.0000", bg=self.CARD_COLOR, fg=self.SUBTEXT_COLOR, font=("Consolas", 10))
        self.vol_label.pack(anchor=tk.E)

        # --- Main Toggle ---
        self.toggle_btn = self.create_button(main_frame, "▶  START LISTENING & VIBRATING", self.toggle_process, self.ACCENT_COLOR, "#121212")
        self.toggle_btn.pack(fill=tk.X, pady=(10, 5), ipady=8)
        
        self.status_label = tk.Label(main_frame, text="Status: Ready", bg=self.BG_COLOR, fg=self.SUBTEXT_COLOR, font=("Segoe UI", 9))
        self.status_label.pack()

    def _fmt(self, val, decimals):
        if decimals == 0: return str(int(float(val)))
        return f"{float(val):.{decimals}f}"

    def _on_slider(self, val, attr, decimals):
        v = int(float(val)) if decimals == 0 else float(val)
        setattr(self.controller, attr, v)
        
        if attr in self.sliders:
            scale, label, _ = self.sliders[attr]
            label.config(text=self._fmt(v, decimals))

    def on_preset_change(self, event):
        sel = self.preset_combo.get()
        vals = GAME_PRESETS.get(sel)
        if vals is None: return
        
        attrs = ["threshold", "sensitivity", "strength", "transient_ratio",
                 "bass_weight", "mid_weight", "treble_weight", "decay_speed", "cooldown_ms"]
                 
        for attr, val in zip(attrs, vals):
            setattr(self.controller, attr, val)
            if attr in self.sliders:
                scale, label, dec = self.sliders[attr]
                scale.set(val)
                label.config(text=self._fmt(val, dec))

    # --- Calibration UI Functions ---
    def start_recording(self):
        if not self.controller.is_running:
            messagebox.showwarning("Warning", "Please click 'Start Listening' first.")
            return
        
        self.controller.start_calibration_recording()
        self.cal_status.config(text="● RECORDING... Vibration is active. Do your thing in-game!", fg=self.RECORD_COLOR)
        
        self.btn_record.config(state=tk.DISABLED, bg=self.CARD_HOVER)
        self.btn_stop_record.config(state=tk.NORMAL, bg=self.ACCENT_COLOR, fg="#121212")
        
        self.elapsed_time = 0
        self.update_recording_timer()

    def update_recording_timer(self):
        if self.controller.is_calibrating:
            self.elapsed_time += 0.1
            self.cal_status.config(text=f"● RECORDING... ({self.elapsed_time:.1f}s) - Click Stop when done", fg=self.RECORD_COLOR)
            self.root.after(100, self.update_recording_timer)

    def stop_recording_and_test(self):
        self.controller.is_calibrating = False
        self.btn_record.config(state=tk.NORMAL, bg=self.RECORD_COLOR)
        self.btn_stop_record.config(state=tk.DISABLED, bg=self.CARD_HOVER)
        
        vibe_val = self.controller.analyze_and_test_vibration()
        if vibe_val > 0:
            self.cal_status.config(text=f"✓ Done ({self.elapsed_time:.1f}s). Test vibration applied ({vibe_val*100:.0f}%). Your feedback?", fg=self.SUCCESS_COLOR)
        else:
            self.cal_status.config(text="✗ Not enough sound recorded. Try again.", fg=self.WARNING_COLOR)

    def give_feedback(self, feedback_type):
        self.controller.apply_feedback(feedback_type)
        messages = {
            'weak': ("↑ Sensitivity & Strength increased. Test again.", self.WARNING_COLOR),
            'perfect': ("✓ Perfect settings saved to calibration.json!", self.SUCCESS_COLOR),
            'strong': ("↓ Sensitivity & Strength decreased. Test again.", self.WARNING_COLOR)
        }
        msg, color = messages[feedback_type]
        self.cal_status.config(text=msg, fg=color)
        
        for attr in ["sensitivity", "strength"]:
            if attr in self.sliders:
                scale, label, dec = self.sliders[attr]
                val = getattr(self.controller, attr)
                scale.set(val)
                label.config(text=self._fmt(val, dec))

    def toggle_process(self):
        if not self.controller.is_running:
            if not self.controller.is_device_found:
                self.status_label.config(text="Status: Error! Loopback device not found.", fg=self.RECORD_COLOR)
                return
            self.controller.start()
            self.toggle_btn.config(text="■  STOP PROGRAM", bg=self.RECORD_COLOR, fg="#ffffff")
            self.status_label.config(text="Status: Listening to game audio...", fg=self.SUCCESS_COLOR)
        else:
            self.controller.stop()
            self.toggle_btn.config(text="▶  START LISTENING & VIBRATING", bg=self.ACCENT_COLOR, fg="#121212")
            self.status_label.config(text="Status: Stopped", fg=self.SUBTEXT_COLOR)
            self.vol_bar['value'] = 0
            self.vol_label.config(text="0.0000")

    def update_ui_loop(self):
        if self.controller.is_running:
            percent = min(100, (self.controller.current_volume / 0.3) * 100)
            self.vol_bar['value'] = percent
            self.vol_label.config(text=f"{self.controller.current_volume:.4f}")
        self.root.after(50, self.update_ui_loop)

    def on_closing(self):
        self.controller.stop()
        self.controller.cleanup()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    controller = AudioReactiveController()
    app = AppUI(root, controller)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
