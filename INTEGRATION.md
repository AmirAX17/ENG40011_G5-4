# Second Observer integration

Second Observer runs on the PC. The Raspberry Pi records and transcribes the conversation, then sends the finished text to the PC over TCP. The PC checks it with Qwen3.5 4B and returns the result on the same connection.

The transcription should cover the whole conversation, from the paramedic arriving to the hospital handover. There is no separate reference file or handover mode to switch on.

## Running the PC side

Install Python with Tkinter, Ollama, and the model:

```powershell
ollama pull qwen3.5:4b
```

Keep the application files together. From that folder, run:

```powershell
py -3 main.py --host 0.0.0.0
```

The latest `main.py` starts Ollama in the background if it is not already running. On Windows it enables Vulkan and integrated GPU support for the server it starts. An existing Ollama process keeps its own settings. Click **Test model** before connecting the Pi.

The PC and Pi need to be able to reach each other on the network. Allow Python through Windows Firewall on the private network if prompted. Run `ipconfig` on the PC and find the IPv4 address for its active Wi-Fi or Ethernet connection.

Use that address in the Pi sender:

```python
PC_HOST = "192.168.1.20"  # Replace with the PC's actual address.
PC_PORT = 8765
```

Do not use `0.0.0.0` or `127.0.0.1` as the destination on the Pi. The first is the PC's listening address; the second would point back to the Pi itself. This prototype uses an unencrypted connection without authentication, so keep it on a trusted private network.

## Which files are involved

`receiver.py` is the PC's socket adapter. It reads messages and passes them to the app. It is already connected to the checking queue, so it does not need to be run separately or copied onto the Pi.

`service.py` checks the message fields, keeps the text in order, prevents duplicate processing and returns results. `engine.py` handles the model comparison. The PC needs both of these, plus `main.py` and `ollama_client.py`.

Most of the integration work should be in the Pi's sender. If it sends the format below, the current receiver can stay as it is. `send_demo.py` is a working client example using the same socket route.

## Sending transcription

Send one JSON object per line, encoded as UTF-8:

```json
{"session_id":"patient-001","chunk_id":1,"final":true,"text":"The patient is Tom. He has chest pain."}
```

| Field | What to send |
| --- | --- |
| `session_id` | A non-empty string for this patient session. Keep it the same throughout the conversation. |
| `chunk_id` | An integer starting at 1. Increase it by 1 for each new message. |
| `final` | Always `true`. Only send text once the transcriber has finalised it. |
| `text` | The new text since the previous message, up to 1,200 characters. |

The newline at the end is required:

```python
message = {
    "session_id": session_id,
    "chunk_id": next_chunk_id,
    "final": True,
    "text": finalised_text,
}

sock.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
```

Send only the new part of the transcription each time. Do not keep sending the entire growing paragraph or overlapping transcription windows, because the app will treat those as repeated speech. Avoid interim transcription guesses that will change a moment later.

A message can contain a sentence or a short paragraph. Keep complete phrases together where possible, especially medication doses and statements such as "did not vomit". The interface joins the received text into continuous prose; the IDs are for the connection, not for numbering the conversation on screen.

## Reading replies

The receiver acknowledges accepted messages straight away:

```json
{"type":"ack","session_id":"patient-001","chunk_id":1,"status":"queued"}
```

This means the text is queued. It does not mean the AI has checked it yet.

The result comes later, also as a JSON line. For example:

```json
{
  "type": "result",
  "session_id": "patient-001",
  "chunk_id": 1,
  "status": "ok",
  "action": "silent",
  "message": "",
  "seconds": 2.4,
  "events": [
    {
      "kind": "NEW",
      "quote": "The patient is Tom.",
      "start": 0,
      "end": 24,
      "prior_ids": [],
      "reason": "First mention of the patient's name.",
      "evidence": []
    }
  ]
}
```

That is shown across several lines here for readability. On the socket, each reply is a single JSON line.

For TTS, check both `type` and `action`:

```python
if reply.get("type") == "result" and reply.get("action") == "alert":
    text_to_speak = reply["message"]
    # Pass text_to_speak to the Pi's TTS queue.
```

| Action | What the sender should do |
| --- | --- |
| `alert` | Forward the message to TTS as a possible discrepancy. |
| `silent` | Nothing needs to be spoken. |
| `error` | Report a checking failure. Do not interpret it as a clean result. |
| `cancelled` | The check was cancelled after Stop. Do not speak it. |

Normal events use `NEW`, `REPEAT`, `CONTRADICTION` and `UNCLEAR`. Greetings and questions without patient assertions can be skipped internally, so an otherwise successful result may have an empty events list. `UNCLEAR` is shown in the GUI but does not currently trigger TTS. There is no UPDATE category.

The `start` and `end` fields locate the statement in the displayed transcript. `prior_ids` and `evidence` link it to earlier observations. The sender does not need these fields for TTS.

A rejected request returns a protocol error instead of an acknowledgement:

```json
{"type":"error","message":"Expected chunk_id 2."}
```

Always read complete lines. TCP does not preserve message boundaries: one receive call can contain half a JSON object or several objects. Python's `sock.makefile("rb").readline()` is one way to handle that. The receiver rejects wire lines over 16 KiB.

## Keeping the stream moving

Wait for the acknowledgement before sending the next message. There is no need to wait for the AI result. Use a separate reader thread to read acknowledgements and results continuously while the transcription continues.

Replies can interleave. Match them using `session_id` and `chunk_id`, not by assuming the next reply belongs to the last message sent. Keep a single producer responsible for numbering the text. The app checks accepted messages in order and has room for 100 queued messages. If the AI is slower than the speech, results will lag behind the live transcript.

Keep a local copy of finalised messages on the sender. If the connection drops, reconnect and resend the same session ID, chunk ID and original text. The app recognises an identical resend and returns its existing acknowledgement or result without processing it twice. Do not increase the ID just because a send was retried. Reusing an ID with different text is rejected.

Deduplicate TTS too: an already completed result can be returned again after reconnecting. Speak an alert only once per session and chunk ID.

## Stop, Clear and a new patient

**Stop** blocks new input and cancels the app's pending checks. It does not stop the Pi microphone, transcription program or shared Ollama server. The Pi needs its own recording controls.

Rejected messages have not been accepted. If the receiver is still starting, or the queue is full, retain the message and retry the same ID later. If the operator has stopped the session, pause the sender rather than repeatedly reconnecting.

**Clear** becomes available after cancellation finishes. It removes the transcript, findings and comparison context. Export first if the session needs to be kept. After Clear, click **Start** and start the next sender session with a new session ID and chunk ID 1. Do not resume old numbered messages into the cleared session.

The PC only keeps one patient at a time. A different session ID is rejected until the existing session is cleared. Duplicate tracking is in memory, so restarting the PC app also resets it. To recover an interrupted session after an app restart, replay that patient's saved messages from ID 1.

If a model check fails, later text cannot be checked reliably against the incomplete context. The app reports errors rather than treating later text as safe. Export if needed, resolve the error, then Stop, Clear, Start and replay the saved transcription.

## Quick connection test

Before connecting real transcription, run the PC app and then open another terminal in its folder:

```powershell
py -3 send_demo.py
```

To test from another computer, copy the standalone demo sender there and use:

```powershell
py -3 send_demo.py --host 192.168.1.20
```

Replace the address with the PC's IP. For a Pi with Python 3, use `python3` instead of `py -3`. Start with an empty checker session each time.

If this works, use the same message-building and reply-reading approach in the actual transcription program.

## What the checker can establish

It compares what was said earlier with what is said later. It does not independently verify medical facts. Similar-sounding words, unclear speakers and missing timing can still lead to wrong classifications or require clarification.

The current context is bounded. The app stops checking when the prepared context becomes too large instead of silently forgetting earlier facts. A long single-patient recording needs further work before it can be handled reliably. Test the actual transcription feed as well as the example text before relying on the alerts.
