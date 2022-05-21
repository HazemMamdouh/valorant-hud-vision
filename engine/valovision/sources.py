"""Frame sources: live screen capture, video files, image folders."""
from __future__ import annotations

import glob
import time
from pathlib import Path
from typing import Iterator, Optional, Tuple

import cv2
import numpy as np

Frame = Tuple[int, float, np.ndarray]   # index, timestamp (s), BGR image


class ScreenSource:
    """Desktop capture with ``mss`` (GDI BitBlt on Windows, XGetImage on X11, Quartz on macOS).

    ``mss`` returns a raw BGRA buffer that NumPy wraps directly; the 2022
    ``pyautogui.screenshot()`` round-tripped every grab through a PIL image.
    """

    def __init__(self, monitor: int = 1, fps: float = 30.0, region: Optional[Tuple[int, int, int, int]] = None):
        import mss
        self.sct = mss.mss()
        mon = self.sct.monitors[monitor]
        self.box = mon if region is None else {"left": region[0], "top": region[1],
                                               "width": region[2], "height": region[3]}
        self.period = 1.0 / fps
        self.fps = fps

    def __iter__(self) -> Iterator[Frame]:
        i, t0 = 0, time.perf_counter()
        while True:
            start = time.perf_counter()
            img = np.asarray(self.sct.grab(self.box))[:, :, :3]     # BGRA -> BGR view
            yield i, start - t0, np.ascontiguousarray(img)
            i += 1
            wait = self.period - (time.perf_counter() - start)
            if wait > 0:
                time.sleep(wait)


class VideoSource:
    def __init__(self, path: str | Path, realtime: bool = True, loop: bool = False):
        self.path = str(path)
        if not Path(self.path).exists():
            raise FileNotFoundError(self.path)
        self.realtime, self.loop = realtime, loop
        cap = cv2.VideoCapture(self.path)
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

    def __iter__(self) -> Iterator[Frame]:
        while True:
            cap = cv2.VideoCapture(self.path)
            i, t0 = 0, time.perf_counter()
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                ts = i / self.fps
                if self.realtime:
                    wait = ts - (time.perf_counter() - t0)
                    if wait > 0:
                        time.sleep(wait)
                yield i, ts, frame
                i += 1
            cap.release()
            if not self.loop:
                return


class ImageSource:
    """A folder glob (``'shots/*.png'``) or a file list (``@list.txt``), optionally looped."""

    def __init__(self, pattern: str, fps: float = 30.0, loop: bool = False, realtime: bool = False):
        if pattern.startswith("@"):
            base = Path(pattern[1:]).resolve().parent
            self.files = [str((base / l.strip()) if not Path(l.strip()).is_absolute() else l.strip())
                          for l in Path(pattern[1:]).read_text().splitlines() if l.strip()]
        else:
            self.files = sorted(glob.glob(pattern))
        if not self.files:
            raise FileNotFoundError(f"no images match {pattern}")
        self.fps, self.loop, self.realtime = fps, loop, realtime
        self._cache: dict = {}

    def __iter__(self) -> Iterator[Frame]:
        i, t0 = 0, time.perf_counter()
        while True:
            for f in self.files:
                if self.realtime:
                    wait = i / self.fps - (time.perf_counter() - t0)
                    if wait > 0:
                        time.sleep(wait)
                img = self._cache.get(f)
                if img is None:
                    img = cv2.imread(f)
                    if len(self._cache) < 256:
                        self._cache[f] = img
                yield i, i / self.fps, img
                i += 1
            if not self.loop:
                return


def open_source(spec: str, realtime: bool = True, loop: bool = False, fps: float = 30.0):
    """``screen`` | ``screen:2`` (monitor) | path/to/video.mp4 | 'frames/*.png' | @filelist.txt"""
    if spec == "screen" or spec.startswith("screen:"):
        mon = int(spec.split(":")[1]) if ":" in spec else 1
        return ScreenSource(monitor=mon, fps=fps)
    if spec.startswith("@") or any(ch in spec for ch in "*?"):
        return ImageSource(spec, fps=fps, loop=loop, realtime=realtime)
    return VideoSource(spec, realtime=realtime, loop=loop)
