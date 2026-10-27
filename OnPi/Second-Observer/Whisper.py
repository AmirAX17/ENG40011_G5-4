#!/usr/bin/env python3
import argparse, json, os, queue, shutil, socket, subprocess, sys, tempfile, threading, time, uuid, wave
import numpy as np
import sounddevice as sd

# ================= CONFIG =================
_ap = argparse.ArgumentParser()
_ap.add_argument("session", nargs="?", default=f"patient-{uuid.uuid4().hex[:8]}")
_ap.add_argument("--host", default="69.69.69.2")
_ap.add_argument("--port", type=int, default=8765)
_args = _ap.parse_args()

PC_HOST = _args.host
PC_PORT = _args.port
SESSION_ID = _args.session

WHISPER_BIN = os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL = os.path.expanduser("~/whisper.cpp/models/ggml-base.en.bin")
WHISPER_THREADS = 4

INPUT_DEVICE = None           # None = auto, or index (int), or name substring (str)
PIPER_VOICE = "en_US-amy-medium"
PIPER_DIR = os.path.expanduser("~/piper_voices")
AUDIO_OUT = "plughw:2,0"   # HyperX headset; check `aplay -l` if card numbers change

LOG_FILE = f"{SESSION_ID}.jsonl"  # local copy of finalised chunks
WHISPER_RATE = 16000
SPEECH_RMS = 500                  # tune: int16 RMS threshold for speech
SILENCE_END_S = 1.0               # silence that ends an utterance
MIN_UTTER_S = 0.4
MAX_UTTER_S = 20.0
PRE_ROLL_BLOCKS = 3
MAX_CHARS = 1200
NOISE_TAGS = {"[BLANK_AUDIO]", "[ Silence ]", "(silence)", "[MUSIC]", "[NOISE]", "[SOUND]"}
SHOW_RMS = False                  # True to print live RMS for threshold tuning
# ==========================================

for p in (WHISPER_BIN, WHISPER_MODEL):
    if not os.path.isfile(p):
        sys.exit(f"Missing file: {p}")

try:
    socket.create_connection((PC_HOST, PC_PORT), timeout=3).close()
    print(f"PC reachable at {PC_HOST}:{PC_PORT}", file=sys.stderr)
except OSError as e:
    print(f"WARNING: cannot reach {PC_HOST}:{PC_PORT} ({e}). "
          "Check the PC app is running with --host 0.0.0.0, firewall, and that both "
          "machines are on the same subnet. Will keep retrying.", file=sys.stderr)

stop_event = threading.Event()
tts_active = threading.Event()
text_q = queue.Queue()
send_q = queue.Queue()
tts_q = queue.Queue()
lock = threading.Lock()
chunks, acked, resolved, spoken = {}, set(), set(), set()
ack_events, ack_errors = {}, {}
conn_state = {"inflight": None}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


# ---------- Audio device ----------
def pick_device():
    devs = sd.query_devices()
    if isinstance(INPUT_DEVICE, int):
        return INPUT_DEVICE
    cands = [i for i, d in enumerate(devs) if d["max_input_channels"] > 0]
    if isinstance(INPUT_DEVICE, str):
        cands = [i for i in cands if INPUT_DEVICE.lower() in devs[i]["name"].lower()]
    if not cands:
        sys.exit("No input (microphone) device found. Check arecord -l and lsusb.")
    usb = [i for i in cands if "usb" in devs[i]["name"].lower()]
    return (usb or cands)[0]


DEV = pick_device()
DEV_INFO = sd.query_devices(DEV)
NATIVE_RATE = int(DEV_INFO["default_samplerate"])
CHANNELS = 1 if DEV_INFO["max_input_channels"] < 2 else 2
BLOCK = NATIVE_RATE // 10
log(f"mic: [{DEV}] {DEV_INFO['name']} | {CHANNELS}ch @ {NATIVE_RATE} Hz")


def to_16k(x):
    x = x.astype(np.float32)
    if NATIVE_RATE == WHISPER_RATE:
        return x.astype(np.int16)
    if NATIVE_RATE % WHISPER_RATE == 0:
        f = NATIVE_RATE // WHISPER_RATE
        n = len(x) // f * f
        return x[:n].reshape(-1, f).mean(axis=1).astype(np.int16)
    n_out = int(len(x) * WHISPER_RATE / NATIVE_RATE)
    return np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.int16)


# ---------- Recorder ----------
def recorder():
    audio_q = queue.Queue()

    def cb(indata, frames, t, status):
        audio_q.put(indata.copy())

    buf, pre, silent, in_speech = [], [], 0, False
    with sd.InputStream(device=DEV, samplerate=NATIVE_RATE, channels=CHANNELS,
                        dtype="int16", blocksize=BLOCK, callback=cb):
        log("recording... speak now")
        while not stop_event.is_set():
            try:
                blk = audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if tts_active.is_set():                 # don't hear our own alerts
                buf, pre, silent, in_speech = [], [], 0, False
                continue
            mono = blk.astype(np.float32).mean(axis=1) if CHANNELS > 1 else blk[:, 0].astype(np.float32)
            rms = float(np.sqrt(np.mean(mono ** 2)))
            if SHOW_RMS:
                print(f"rms={rms:6.0f}", end="\r", file=sys.stderr)
            mono = mono.astype(np.int16)
            speech = rms >= SPEECH_RMS
            if not in_speech:
                pre = (pre + [mono])[-PRE_ROLL_BLOCKS:]
                if speech:
                    in_speech, buf, silent = True, list(pre), 0
                continue
            buf.append(mono)
            silent = 0 if speech else silent + 1
            dur = len(buf) * BLOCK / NATIVE_RATE
            if silent * BLOCK / NATIVE_RATE >= SILENCE_END_S or dur >= MAX_UTTER_S:
                if dur >= MIN_UTTER_S:
                    text_q.put(np.concatenate(buf))
                buf, in_speech, silent = [], False, 0


# ---------- Transcription ----------
def transcribe(samples):
    pcm = to_16k(samples)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(WHISPER_RATE)
            w.writeframes(pcm.tobytes())
        r = subprocess.run(
            [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", path, "-l", "en",
             "-t", str(WHISPER_THREADS), "-nt", "-np"],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log("whisper error:", r.stderr[-300:])
            return ""
        return " ".join(r.stdout.split())
    except subprocess.TimeoutExpired:
        log("whisper timeout")
        return ""
    finally:
        os.unlink(path)


def split_text(text):
    out = []
    while len(text) > MAX_CHARS:
        cut = max(text.rfind(p, 0, MAX_CHARS) for p in (". ", "? ", "! "))
        cut = cut + 1 if cut > 0 else text.rfind(" ", 0, MAX_CHARS)
        cut = cut if cut > 0 else MAX_CHARS
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


def is_noise(text):
    t = text.strip()
    if not t or t in NOISE_TAGS:
        return True
    rest = t
    for tag in NOISE_TAGS:
        rest = rest.replace(tag, "")
    return not rest.strip()


def transcriber():
    next_id = 1                                   # single producer owns numbering
    while not (stop_event.is_set() and text_q.empty()):
        try:
            samples = text_q.get(timeout=0.5)
        except queue.Empty:
            continue
        text = transcribe(samples)
        if is_noise(text):
            continue
        for part in split_text(text):
            with lock:
                chunks[next_id] = part
                ack_events[next_id] = threading.Event()
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"session_id": SESSION_ID, "chunk_id": next_id,
                                    "text": part}, ensure_ascii=False) + "\n")
            log(f"chunk {next_id}: {part}")
            send_q.put(next_id)
            next_id += 1


# ---------- Network ----------
def handle_reply(msg):
    t, cid = msg.get("type"), msg.get("chunk_id")
    if t in ("ack", "result") and msg.get("session_id") == SESSION_ID:
        action = msg.get("action")
        with lock:
            acked.add(cid)
            ev = ack_events.get(cid)
            if t == "result" and action in ("alert", "silent"):
                resolved.add(cid)
        if ev:
            ev.set()
        if t == "result":
            if action == "alert" and msg.get("message"):
                key = (SESSION_ID, cid)
                with lock:
                    first = key not in spoken
                    spoken.add(key)
                if first:
                    tts_q.put(msg["message"])
            elif action == "error":
                log(f"CHECK FAILED chunk {cid}: {msg.get('message')} (NOT a clean result)")
            elif action == "cancelled":
                log(f"chunk {cid} cancelled")
    elif t == "error":
        m = msg.get("message", "")
        log("protocol error:", m)
        with lock:
            cid = conn_state["inflight"]
            if cid is not None:
                ack_errors[cid] = m
                ev = ack_events.get(cid)
                if ev:
                    ev.set()


def reader(sock):
    f = sock.makefile("rb")
    try:
        while not stop_event.is_set():
            line = f.readline()
            if not line:
                break
            try:
                handle_reply(json.loads(line.decode("utf-8")))
            except ValueError:
                log("bad line:", line[:100])
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass
        log("connection closed")


def send_line(sock, cid):
    msg = {"session_id": SESSION_ID, "chunk_id": cid, "final": True, "text": chunks[cid]}
    sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))


def sender():
    carry = []                                    # ids left over after a dropped connection
    while True:
        if stop_event.is_set() and send_q.empty() and not carry:
            return
        try:
            sock = socket.create_connection((PC_HOST, PC_PORT), timeout=5)
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as e:
            log("connect failed:", e)
            time.sleep(3)
            continue
        log(f"connected to {PC_HOST}:{PC_PORT}")
        threading.Thread(target=reader, args=(sock,), daemon=True).start()
        with lock:
            pending = sorted(c for c in chunks if c not in resolved)   # resend unresolved
        for c in carry:
            if c not in pending:
                pending.append(c)
        pending.sort()
        carry = []
        seen = set(pending)
        try:
            while True:
                if not pending:
                    try:
                        c = send_q.get(timeout=0.5)
                    except queue.Empty:
                        if stop_event.is_set():
                            return
                        continue
                    if c in seen:
                        continue
                    seen.add(c)
                    pending.append(c)
                cid = pending[0]
                with lock:
                    already = cid in acked
                    ev = ack_events[cid]
                    ev.clear()
                    ack_errors.pop(cid, None)
                    conn_state["inflight"] = cid
                if not already:
                    send_line(sock, cid)
                    if not ev.wait(timeout=30):
                        raise OSError("ack timeout")
                    with lock:
                        err = ack_errors.pop(cid, None)
                    if err:
                        wait = 30 if "stop" in err.lower() else 2
                        log(f"chunk {cid} rejected ({err}); retry in {wait}s")
                        time.sleep(wait)
                        continue                  # same ID, same text
                pending.pop(0)
        except OSError as e:
            log("send failed:", e)
            carry = list(pending)
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(2)


# ---------- TTS ----------
def speak(text):
    wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        subprocess.run([sys.executable, "-m", "piper", "-m", PIPER_VOICE,
                        "--data-dir", PIPER_DIR, "-f", wav],
                       input=text, text=True, check=True, capture_output=True, timeout=60)
        subprocess.run(["aplay", "-q", "-D", AUDIO_OUT, wav])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        log("piper failed, using espeak-ng:", getattr(e, "stderr", e))
        if shutil.which("espeak-ng"):
            subprocess.run(["espeak-ng", text])
    finally:
        if os.path.exists(wav):
            os.unlink(wav)


def tts_worker():
    while not stop_event.is_set():
        try:
            text = tts_q.get(timeout=0.5)
        except queue.Empty:
            continue
        log("TTS:", text)
        tts_active.set()
        try:
            speak(text)
        finally:
            time.sleep(0.5)
            tts_active.clear()


# ---------- Main ----------
if __name__ == "__main__":
    log("session:", SESSION_ID)
    for fn in (recorder, transcriber, sender, tts_worker):
        threading.Thread(target=fn, daemon=True, name=fn.__name__).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("stopping...")
        stop_event.set()
        time.sleep(3)
