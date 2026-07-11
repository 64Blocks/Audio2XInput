# Audio2XInput

Turn your game audio into real-time controller vibration.

Audio2XInput listens to Windows loopback audio and converts explosions, gunshots, engines, music, and other sound effects into intelligent XInput controller vibration using frequency analysis and adaptive calibration.

---

## Features

- 🎮 Real-time XInput vibration
- 🔊 Windows WASAPI Loopback Capture
- ⚡ FFT Frequency Analysis
- 🧠 Adaptive Auto Calibration
- 🎯 Transient Detection
- 🎮 Game Presets
- 📊 Live Audio Visualizer
- ⚙️ Fine Tuning Controls
- 💾 Automatic Calibration Save/Load
- 🌙 Modern Dark UI
- 🚀 Lightweight
- 🪟 Windows 10 / Windows 11

---

## How It Works

Audio2XInput captures your PC's output audio using WASAPI Loopback.

Every audio frame is analyzed using FFT.

The engine extracts:

- Bass
- Mid
- Treble

It detects audio transients (explosions, gunshots, impacts) and converts them into controller vibration intensity.

The resulting vibration is sent directly to any XInput-compatible controller.

---

## Features Explained

### Audio Analysis

- FFT Processing
- Peak Detection
- Frequency Band Weighting
- Adaptive Threshold

### Vibration Engine

- Left/Right Motor Control
- Smooth Decay
- Cooldown Protection
- Dynamic Strength Scaling

### Auto Calibration

Record gameplay audio.

Test vibration.

Choose:

- Too Weak
- Perfect
- Too Strong

The calibration engine automatically adjusts sensitivity and stores your preferred settings.

---

## Supported Controllers

Any XInput compatible controller including:

- Xbox 360
- Xbox One
- Xbox Series
- Twin USB (via XInput wrapper)
- Generic XInput controllers

---

## Requirements

- Windows 10
- Windows 11
- Python 3.10+
- XInput
- WASAPI Audio Device

---

## Installation

```bash
git clone https://github.com/yourname/audio2xinput.git

cd audio2xinput

pip install -r requirements.txt
```

Run

```bash
python main.py
```

---

## Dependencies

- numpy
- pyaudiowpatch

Built-in modules:

- tkinter
- ctypes
- threading
- json
- os

---

## Project Structure

```
main.py
calibration.json
requirements.txt
README.md
```

---

## Future Roadmap

- Multiple controller support
- Per-game profiles
- Machine Learning vibration prediction
- DualSense support
- DualShock support
- Steam Deck support
- HID vibration mode
- Plugin system

---

## License

MIT License
