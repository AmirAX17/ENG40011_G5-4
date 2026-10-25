"""TCP NDJSON adapter. GUI and model run elsewhere."""
import json
import socketserver
import threading

class Receiver:
    def __init__(self, submit, host='127.0.0.1', port=8765):
        self.submit=submit
        owner=self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                lock=threading.Lock()
                self.request.settimeout(3600)
                def send(data):
                    try:
                        with lock:
                            self.request.sendall((json.dumps(data,ensure_ascii=False)+'\n').encode('utf-8'))
                    except OSError:
                        pass  # Sender reconnects/replays same ID to retrieve retained result.
                try:
                    while True:
                        line=self.rfile.readline(16385)
                        if not line: return
                        if len(line)>16384 or not line.endswith(b'\n'):
                            send({'type':'error','message':'Message exceeds 16 KiB or lacks newline.'}); return
                        try:
                            msg=json.loads(line.decode('utf-8'))
                            owner.submit(msg,send)
                        except (ValueError,UnicodeError) as e:
                            send({'type':'error','message':str(e)})
                except OSError:
                    return
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address=True
            daemon_threads=True
        self.server=Server((host,port),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def start(self): self.thread.start()
    def close(self):
        self.server.shutdown()
        self.server.server_close()
