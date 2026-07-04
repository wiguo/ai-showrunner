"""Local media helpers: last-frame extraction and MP4 -> WebM conversion.

Uses the ffmpeg binary bundled with imageio-ffmpeg, so no system ffmpeg is
required on Windows.
"""

import re
import subprocess

import imageio_ffmpeg


def ffmpeg_exe():
    return imageio_ffmpeg.get_ffmpeg_exe()


def has_audio(path):
    """True if the media file contains at least one audio stream."""
    proc = subprocess.run([ffmpeg_exe(), "-i", str(path)],
                          capture_output=True, text=True)
    return bool(re.search(r"Stream #0:\d.*Audio:", proc.stderr))


def audio_duration(path):
    """Return duration in seconds by parsing ffmpeg's probe output."""
    proc = subprocess.run([ffmpeg_exe(), "-i", str(path)],
                          capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _srt_subtitles_filter(srt_path):
    """Build an ffmpeg subtitles filter with a Windows-safe escaped path."""
    p = str(srt_path).replace("\\", "/").replace(":", "\\:")
    style = ("Fontsize=18,PrimaryColour=&Hffffff&,OutlineColour=&H000000&,"
             "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=42")
    return f"subtitles='{p}':force_style='{style}'"


def extract_last_frame(video_path, out_image_path):
    """Write the final frame of a video to a PNG."""
    import imageio.v3 as iio

    last = None
    for frame in iio.imiter(str(video_path), plugin="FFMPEG"):
        last = frame
    if last is None:
        raise RuntimeError(f"could not read frames from {video_path}")
    iio.imwrite(str(out_image_path), last)
    return out_image_path


def to_ogg(src_path, ogg_path):
    """Transcode any audio to clean Vorbis .ogg (fixes malformed WAV headers)."""
    cmd = [ffmpeg_exe(), "-y", "-i", str(src_path),
           "-c:a", "libvorbis", "-q:a", "5", str(ogg_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg ogg conversion failed for {src_path}:\n{proc.stderr[-2000:]}")
    return ogg_path


def concat_audio(paths, out_path):
    """Concatenate audio files back-to-back into one clean .ogg."""
    paths = [str(p) for p in paths]
    if len(paths) == 1:
        return to_ogg(paths[0], out_path)
    cmd = [ffmpeg_exe(), "-y"]
    for p in paths:
        cmd += ["-i", p]
    streams = "".join(f"[{i}:a]" for i in range(len(paths)))
    cmd += ["-filter_complex", f"{streams}concat=n={len(paths)}:v=0:a=1[a]",
            "-map", "[a]", "-c:a", "libvorbis", "-q:a", "5", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{proc.stderr[-2000:]}")
    return out_path


def mp4_to_webm(mp4_path, webm_path, crf=32):
    """Convert an MP4 to VP9+Opus WebM (Ren'Py's preferred movie format)."""
    cmd = [
        ffmpeg_exe(), "-y", "-i", str(mp4_path),
        "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf),
        "-c:a", "libopus", "-b:a", "96k",
        str(webm_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg webm conversion failed for {mp4_path}:\n{proc.stderr[-2000:]}"
        )
    return webm_path


def mux_voice_into_video(mp4_path, voice_path, webm_path, srt_path=None,
                         ambient_vol=0.4, delay_ms=300, crf=32):
    """Mux a voice track over a clip's (ducked) ambient audio -> VP9/Opus WebM.

    The character's monologue plays over the visuals; original clip audio is
    ducked to `ambient_vol`. If `srt_path` is given, the lines are also burned
    into the video as subtitles (synced to the voice).
    """
    clip_has_audio = has_audio(mp4_path)
    if clip_has_audio:
        afilter = (f"[0:a]volume={ambient_vol}[bg];"
                   f"[1:a]adelay={delay_ms}|{delay_ms},apad[vc];"
                   f"[bg][vc]amix=inputs=2:duration=first:normalize=0,"
                   f"alimiter=limit=0.95[a]")
    else:
        # Silent clip (some flash models emit no audio): voice becomes the track.
        afilter = f"[1:a]adelay={delay_ms}|{delay_ms},alimiter=limit=0.95[a]"
    cmd = [ffmpeg_exe(), "-y", "-i", str(mp4_path), "-i", str(voice_path)]
    if srt_path is not None:
        vfilter = f"[0:v]{_srt_subtitles_filter(srt_path)}[v]"
        cmd += ["-filter_complex", f"{vfilter};{afilter}",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", afilter, "-map", "0:v", "-map", "[a]"]
    cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf),
            "-c:a", "libopus", "-b:a", "128k"]
    if not clip_has_audio:
        cmd += ["-shortest"]   # end with the (shorter) video
    cmd += [str(webm_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg voice mux failed for {mp4_path}:\n{proc.stderr[-2000:]}")
    return webm_path
