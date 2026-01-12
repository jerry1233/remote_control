import json

def encode(msg):
    return (json.dumps(msg)+"\n").encode()

async def decode(reader):
    try:
        line = await reader.readline()
        if not line: return None
        return json.loads(line.decode())
    except: return None
