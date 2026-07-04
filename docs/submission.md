# Devpost submission draft — Global AI Hackathon Series with Qwen Cloud

**Track:** AI Showrunner

## Project name

**Once Upon a Line**
*Every story starts with a single line.*

## Elevator pitch (≤ ~200 chars)

Once Upon a Line: type one sentence and an autonomous Qwen-powered agent
writes, storyboards, films, voices and subtitles a branching interactive film —
then hands you the playable game. A full studio in a textbox.

## Project story (draft)

**Inspiration.** I've been a fan of interactive video games for years, and
I've always dreamed of shipping one of my own. But every time I looked into
it, the answer was the same: you need a team — a writer, a storyboard artist,
a film crew, voice actors, an editor, a game programmer. As one person, I
never got past the first page of ideas.

Qwen Cloud changed that math. For the first time, everything a studio does
lives behind one API key: a model that writes (qwen3.7-max), models that see
and paint (wan t2i), a model that films (happyhorse i2v), and a model that
speaks (qwen tts). So I asked the obvious question: if the whole crew is in
one place, can one autonomous agent BE the studio? Once Upon a Line is my
answer — and my first game credit. The economics are almost absurd: a
complete voiced, subtitled, branching interactive film costs a few dollars
of API calls and one sentence of imagination.

**What it does.** You give it a premise ("a lighthouse keeper discovers the
fog is alive…"). The agent:
1. writes a production-grade screenplay (qwen3.7-max),
2. compiles it into a *branching* scene graph — real choices that fork into
   different scene chains and rejoin — validated for reachability and fitted
   to a runtime budget,
3. pitches it back to you with an estimated media budget (**the agent asks
   before spending**),
4. then shoots it: a style-locked keyframe per scene (wan2.6-t2i, stable
   seeds + embedded character appearance for consistency), a video clip per
   scene (happyhorse-1.1-i2v), the protagonist's inner monologue voiced by
   cosyvoice with subtitles burned in sync, and a narrator intro,
5. and finally assembles, lints and zips a complete Ren'Py game.

**How we built it.** An 8-stage resumable pipeline behind a FastAPI web app
on Alibaba Cloud. Every stage leaves artifacts on disk, so the live UI derives
per-scene progress purely from the filesystem, jobs are resumable after quota
errors, and each job runs in an isolated directory. Model access goes through
fallback chains (e.g. happyhorse → wan-flash) so per-model quota exhaustion
hops models instead of failing the job.

**Challenges.** TTS audio with corrupt RIFF headers (transcode to ogg), i2v
models that emit no audio stream (mux detection), muted voice channels in
Ren'Py (voice is mixed into the video instead), subtitle/voice drift from
stale artifacts (fixed by per-job isolation), and free-tier quotas mid-shoot
(fallback chains + resume).

**What's next.** Multi-character dialogue with per-character voices,
scene-to-scene continuity via last-frame chaining, longer formats, and music.

## Built with

Python · FastAPI · Qwen Cloud (qwen3.7-max, wan2.6-t2i, happyhorse-1.1-i2v,
cosyvoice-v3-plus) · ffmpeg · Ren'Py · Docker · Alibaba Cloud Simple
Application Server

## Submission checklist

- [ ] Public GitHub repo URL (MIT license visible in About)
- [ ] Demo video 1–3 min (storyboard: premise typed → pitch + budget card →
      approve → live scene grid time-lapse → download → play in Ren'Py with a
      choice taken both ways → architecture diagram)
- [ ] Separate short recording proving backend on Alibaba Cloud
      (SAS Workbench Overview + browser at public IP)
- [ ] Architecture diagram (docs/architecture.mmd → export PNG)
- [ ] Written summary (README top section)
- [ ] Track selected: AI Showrunner
- [ ] Optional: blog post for Best Blog prize
