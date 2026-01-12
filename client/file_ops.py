import os, base64
from protocol import encode

async def handle_upload(msg):
    path = msg["payload"]["path"]
    data = base64.b64decode(msg["payload"]["data"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"ab") as f:
        f.write(data)

async def handle_download(msg, writer):
    path = msg["payload"]["path"]
    offset = msg["payload"]["offset"]
    if not os.path.exists(path):
        writer.write(encode({"type":"file_download_chunk","path":path,"offset":offset,"data":"","eof":True}))
        await writer.drain()
        return
    with open(path,"rb") as f:
        f.seek(offset)
        chunk = f.read(4096)
    writer.write(encode({
        "type":"file_download_chunk",
        "path":path,
        "offset":offset,
        "data":base64.b64encode(chunk).decode(),
        "eof":len(chunk)==0
    }))
    await writer.drain()
