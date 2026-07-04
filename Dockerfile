# AI Showrunner: story -> playable Ren'Py interactive film, as a web service.
# All AI generation happens via the Qwen Cloud API; this image only needs
# Python, ffmpeg (bundled via imageio-ffmpeg) and the Ren'Py SDK for linting.

FROM python:3.11-slim

# libgl/libglib: minimal shared libs so the Ren'Py SDK can run headless lint.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl bzip2 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Ren'Py SDK (headless lint of the generated project; non-fatal if it fails).
ARG RENPY_VERSION=8.3.4
RUN curl -fsSL "https://www.renpy.org/dl/${RENPY_VERSION}/renpy-${RENPY_VERSION}-sdk.tar.bz2" \
      | tar -xj -C /opt \
    && mv /opt/renpy-${RENPY_VERSION}-sdk /opt/renpy-sdk

ENV RENPY_EXE=/opt/renpy-sdk/renpy.sh \
    SDL_VIDEODRIVER=dummy \
    SDL_AUDIODRIVER=dummy \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline/ pipeline/
COPY server/ server/
COPY scripts/ scripts/

EXPOSE 8080
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8080"]
