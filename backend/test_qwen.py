import urllib.request
import json
import sys

def test():
    req = urllib.request.Request(
        'http://localhost:11434/api/generate',
        data=json.dumps({
            'model': 'qwen3.5:9b',
            'prompt': 'Genera un JSON con una lista de diccionarios. Usa llaves [ y ].',
            'stream': True
        }).encode()
    )
    
    try:
        res = urllib.request.urlopen(req)
        for line in res:
            if line:
                data = json.loads(line)
                if 'response' in data:
                    print(data['response'], end='', flush=True)
        print("\n\n--DONE--")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test()
