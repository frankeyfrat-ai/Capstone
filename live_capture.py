"""Terminal-controlled recording and sample-aligned manual labels (macOS/Linux)."""

import os
import select
import sys
from contextlib import contextmanager, ExitStack
from datetime import datetime

import numpy as np
import sounddevice as sd

RATE = 48000
BLOCK = 1024


class Timeline:
    def __init__(self, initial_label):
        if initial_label not in {'drone', 'no_drone', None}:
            raise ValueError('Initial label must be drone, no_drone, or unknown.')
        self.changes = [(0, initial_label)]

    @property
    def label(self):
        return self.changes[-1][1]

    def mark(self, frame, label):
        if label not in {'drone', 'no_drone'}:
            raise ValueError('Choose drone or no_drone.')
        if frame < self.changes[-1][0]:
            raise ValueError('Markers must be chronological.')
        if label == self.label:
            return
        if frame == self.changes[-1][0]:
            self.changes[-1] = (frame, label)
        else:
            self.changes.append((frame, label))

    def intervals(self, total_frames):
        result = []
        for index, (start, label) in enumerate(self.changes):
            end = self.changes[index + 1][0] if index + 1 < len(self.changes) else total_frames
            end = min(end, total_frames)
            if start < end:
                result.append((start / RATE, end / RATE, label))
        return result


def interval_text(intervals):
    # Enough precision to round-trip 48 kHz frame positions without rounding past EOF.
    return ';'.join(f'{start:.9f}-{end:.9f}:{label}' for start, end, label in intervals if label is not None)


@contextmanager
def single_keys():
    if not sys.stdin.isatty():
        raise ValueError('Run in VS Code’s integrated TERMINAL so live marking keys are available.')
    import termios
    import tty
    descriptor = sys.stdin.fileno()
    original = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        # Discard the Enter key left by the preceding prompt.
        termios.tcflush(descriptor, termios.TCIFLUSH)
        yield descriptor
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, original)


def record_live(seconds, device, initial_label=None, monitor_device=None, marker_delay_s=0, enable_marking=True):
    total = round(seconds * RATE)
    audio = np.empty((total, 1), dtype=np.float32)
    position = 0
    timeline = Timeline(initial_label)
    warnings = []
    stopped_early = False
    print('LIVE KEYS: D/N/SPACE = draft bookmarks | Q = stop and save' if enable_marking else
          'RECORD ONLY: labels pending later review | Q = stop and save')
    print('Ctrl+C cancels this take. Keep this terminal focused. No Enter needed.', flush=True)
    with single_keys() as descriptor, ExitStack() as stack:
        output = None
        if monitor_device is not None:
            output = stack.enter_context(sd.OutputStream(samplerate=RATE, blocksize=BLOCK,
                                         channels=2, dtype='float32', device=monitor_device))
        # Open headphones first so their connection time doesn't fill the input buffer.
        stream = stack.enter_context(sd.InputStream(samplerate=RATE, blocksize=BLOCK,
                                     channels=1, dtype='float32', device=device))
        started = datetime.now().astimezone()
        shown_second = -1
        while position < total:
            block, overflow = stream.read(min(BLOCK, total - position))
            audio[position:position + len(block)] = block
            position += len(block)
            if overflow and 'Input overflow: audio lost; review timing and labels' not in warnings:
                warnings.append('Input overflow: audio lost; review timing and labels')
            if output is not None:
                try:
                    underflow = output.write(np.repeat(block, 2, axis=1))
                    message = 'Headphone playback underflow: review marker timing'
                    if underflow and message not in warnings:
                        warnings.append(message)
                except sd.PortAudioError:
                    # Capture continues if the headphone connection fails.
                    output = None
                    warnings.append('Headphone monitoring disconnected')
                    print('\nHeadphone monitoring disconnected; microphone recording continues.', flush=True)
            while select.select([descriptor], [], [], 0)[0]:
                key = os.read(descriptor, 1).decode(errors='ignore').lower()
                if key == 'q':
                    stopped_early = True
                    break
                label = 'drone' if key == 'd' else 'no_drone' if key == 'n' else None
                if key == ' ':
                    label = 'no_drone' if timeline.label == 'drone' else 'drone'
                if label and enable_marking:
                    marker_frame = max(timeline.changes[-1][0], position - round(marker_delay_s * RATE))
                    timeline.mark(marker_frame, label)
                    print(f'\nMARK {marker_frame / RATE:.2f}s: {label}', flush=True)
            current_second = position // RATE
            if current_second != shown_second:
                print(f'\rRecording {position / RATE:.0f}/{seconds:g}s | {timeline.label or "unlabeled"}       ',
                      end='', flush=True)
                shown_second = current_second
            if stopped_early:
                break
    print('\nRecording finished.', flush=True)
    if stopped_early:
        warnings.append('Stopped early by operator')
    return audio[:position], started, '; '.join(warnings), interval_text(timeline.intervals(position))
