"""Short realistic conversation + handover test. Run with the checker open.

Expected: NEW initially; REPEAT for clear paraphrases; CONTRADICTION for
right arm, absent peanut allergy, 10 mg, vomiting and wrong timed pain.
UNCLEAR is appropriate for uncertain 'penum'/'vest' transcription: similar
sounds alone must not establish an allergy or a symptom. No UPDATE labels.
"""
import argparse
import json
import socket

# Each paragraph is a finalized NEW transcription delta, not a growing copy.
TRANSCRIPT = ["Hi, I'm one of the paramedics. Can you tell me your name and what happened? I'm Tom, I'm 42. I "
 'was carrying the shopping upstairs when this pressure started in the middle of my chest. It went '
 'into my left arm. That was about twenty past ten.',
 "Are you having trouble breathing? A bit, yes. I feel sick as well, but I haven't thrown up. Did "
 "you pass out? No, I stayed awake the whole time. My wife called you. She's coming with me.",
 'Any allergies or regular medication? Peanuts give me an itchy rash. I take warfarin, five '
 "milligrams every evening. How bad was the pain at half past ten? Eight out of ten. It's quarter "
 "to eleven now, what is it like? It's down to three.",
 " This is Tom, forty-two, with central chest pressure starting at ten "
 'twenty while carrying shopping upstairs. He was breathless and nauseated. His wife is here with '
 'him.',
 'The pain spread into his right arm. He vomited twice, but there was no loss of consciousness. No '
 'known peanut allergy. He takes warfarin, ten milligrams each evening. At ten forty-five his pain '
 'was still eight out of ten.',
 'He described it as vest pain. There was also something that sounded like penum when we discussed '
 "allergies, but I couldn't make out that word. Can we check those details with him?",
 "It's eleven now. We've just measured his temperature for the first time; it's thirty-seven point "
 'one. Tom, how is the pain now? Two out of ten.']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port), timeout=10) as sock:
        sock.settimeout(600)
        with sock.makefile('rb') as replies:
            for number, text in enumerate(TRANSCRIPT, 1):
                message = {'session_id': 'tom-short-demo', 'chunk_id': number,
                           'final': True, 'text': text}
                sock.sendall((json.dumps(message) + '\n').encode('utf-8'))
                print('\n' + text, flush=True)
                # Wait for this check so the short demo also suits slower laptops.
                while True:
                    line = replies.readline()
                    if not line:
                        raise RuntimeError('Checker disconnected.')
                    result = json.loads(line)
                    if result.get('type') == 'error':
                        raise RuntimeError(result['message'])
                    if result.get('type') != 'result':
                        continue
                    if result.get('status') != 'ok':
                        raise RuntimeError(result.get('message', 'Checking stopped.'))
                    for event in result['events']:
                        print(f"  {event['kind']}: {event['quote']} — {event['reason']}")
                    break
    print('\nFinished. Review the labels; completion is not an accuracy score.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f'\nDemo stopped: {error}\nUse a fresh checker session: Stop, Clear, Start.')
