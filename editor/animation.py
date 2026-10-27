"""Orbit animations: the camera turns about the vertical axis through the model's centre, keeping its
height and distance, one still per frame, written as MP4 (through ffmpeg), GIF or animated WebP. A full
360 degrees goes round from the view it starts at; a smaller angle sweeps an arc centred on that view, or
with swing goes out to both ends of the arc and back, eased, so it loops.

The renderer's capture clock steps with the frames (frame / fps seconds), so flames, pulsing glows and the
other magic lights move in the animation as they do in the live view.

    views = orbit_views(eye, forward, right, up, centre, frames=120, degrees=90, swing=True)
    writer = FrameWriter("orbit.mp4", 720, 720, fps=30)
    for view in views: writer.add(rgb)    # (height, width, 3) uint8
    writer.close()                        # or writer.abort() to drop a half-written file
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

FORMATS = (".mp4", ".gif", ".webp")
ORBIT_LIMITS = (3840, 2160, 4096, 3600)  # width, height, samples, frames of an orbit
HELD_BYTES = 1_000_000_000  # GIF and WebP frames wait in memory until the file is written: at most this


def orbit_angle(fraction: float, degrees: float = 360.0, swing: bool = False) -> float:
    """The turn in degrees at `fraction` (0-1) of the way through: as orbit_angles, continuously (the
    Render dock's live preview)."""
    if swing:
        return degrees / 2 * float(np.sin(2 * np.pi * fraction))
    if degrees % 360 == 0:
        return degrees * fraction
    return degrees * (fraction - 0.5)


def orbit_angles(frames: int, degrees: float = 360.0, swing: bool = False) -> np.ndarray:
    """Each frame's turn in degrees from the starting view (counter-clockwise seen from above; a negative
    angle turns the other way). Whole turns start at the view and do not repeat the first frame at the end,
    so they loop; a smaller arc is centred on the view, from one end to the other. swing: out to one end of
    the arc, back through the view to the other and home again, eased at the ends: it loops at any angle."""
    i = np.arange(frames)
    if swing:
        return degrees / 2 * np.sin(2 * np.pi * i / frames)
    if degrees % 360 == 0:
        return degrees * i / frames
    return degrees * (i / (frames - 1) - 0.5)


def orbit_views(eye, forward, right, up, centre, frames: int, degrees: float = 360.0, swing: bool = False):
    """[(eye, forward, right, up), ...]: the camera turned about the vertical axis through `centre` by
    orbit_angles, one view a frame."""
    eye, centre = np.asarray(eye, float), np.asarray(centre, float)
    views = []
    for degree in orbit_angles(frames, degrees, swing):
        angle = np.radians(degree)
        c, s = np.cos(angle), np.sin(angle)
        turn = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        views.append((centre + turn @ (eye - centre), *(turn @ np.asarray(v, float) for v in (forward, right, up))))
    return views


def check_path(path) -> Path:
    path = Path(path)
    if path.suffix.lower() not in FORMATS:
        raise ValueError(f"An orbit is saved as {', '.join(FORMATS)}, not {path.suffix or 'no extension'}.")
    if path.suffix.lower() == ".mp4" and ffmpeg() is None:
        raise ValueError("MP4 needs ffmpeg on the PATH (ffmpeg.org); .gif and .webp need nothing more.")
    return path


def ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # the imageio-ffmpeg package brings one along
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class FrameWriter:
    """Frames into a file: streamed to ffmpeg for MP4 (H.264, near-lossless), kept and written at close for
    GIF and WebP (looping)."""

    def __init__(self, path, width: int, height: int, fps: float, frames: int | None = None):
        """frames: how many will come, if known, so a GIF or WebP that would not fit in memory is refused
        before the first one is drawn."""
        self.path = check_path(path)
        self.size, self.fps, self.frames = (width, height), float(fps), []
        if not 1 <= self.fps <= 120:
            raise ValueError("fps is 1-120")
        held = (frames or 0) * width * height * 3
        if self.path.suffix.lower() != ".mp4" and held > HELD_BYTES:
            raise ValueError(f"A {self.path.suffix[1:].upper()} keeps its frames in memory until it is written: "
                             f"{frames} frames of {width} x {height} would need {held / 1e9:.1f} GB. Save an .mp4, "
                             "or make it smaller or shorter.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.process = None
        if self.path.suffix.lower() == ".mp4":
            self.process = subprocess.Popen(
                [ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                 "-r", f"{self.fps:g}", "-i", "-", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow", "-movflags", "+faststart", str(self.path)],
                stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def add(self, rgb: np.ndarray) -> None:
        if rgb.shape != (self.size[1], self.size[0], 3):
            raise ValueError("a frame of another size")
        if self.process is not None:
            self.process.stdin.write(np.ascontiguousarray(rgb, dtype=np.uint8).tobytes())
        else:
            from PIL import Image
            self.frames.append(Image.fromarray(rgb))

    def close(self) -> Path:
        if self.process is not None:
            self.process.stdin.close()
            error = self.process.stderr.read().decode("utf-8", "replace").strip()
            if self.process.wait() != 0:
                raise OSError(f"ffmpeg could not write {self.path.name}: {error}")
            return self.path
        if not self.frames:
            raise ValueError("no frames")
        duration = round(1000 / self.fps)
        if self.path.suffix.lower() == ".gif":
            self.frames[0].save(self.path, save_all=True, append_images=self.frames[1:], duration=duration, loop=0,
                                disposal=1)
        else:
            self.frames[0].save(self.path, save_all=True, append_images=self.frames[1:], duration=duration, loop=0,
                                quality=90, method=4)
        return self.path

    def abort(self) -> None:
        """Stop and remove what was written so far."""
        if self.process is not None:
            self.process.stdin.close()
            self.process.kill()
            self.process.wait()
        self.frames = []
        self.path.unlink(missing_ok=True)
