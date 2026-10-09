
import sounddevice as sd
import soundfile as sf
import numpy as np

# Recording settings
SAMPLE_RATE = 48000
DURATION = 10  # seconds
CHANNELS = 1
OUTPUT_FILE = "drone_test.wav"

# Display available audio devices
print("Available audio devices:")
print(sd.query_devices())

# Find the UMIK microphone
devices = sd.query_devices()
mic_index = next(
    (i for i, device in enumerate(devices)
     if "UMIK" in device["name"].upper()
     and device["max_input_channels"] > 0),
    None
)

if mic_index is None:
    raise RuntimeError("UMIK microphone not found!")

print(f"\nUsing microphone: {devices[mic_index]['name']}")

# Check microphone capabilities
sd.check_input_settings(
    device=mic_index,
    samplerate=SAMPLE_RATE,
    channels=CHANNELS
)

print(f"\nRecording for {DURATION} seconds...")

audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=CHANNELS,
    device=mic_index,
    dtype="float32"
)

sd.wait()

sf.write(
    OUTPUT_FILE,
    audio,
    SAMPLE_RATE,
    subtype="PCM_24"
)

print(f"Recording saved as {OUTPUT_FILE}")
print(f"Peak amplitude: {np.max(np.abs(audio)):.4f}")
