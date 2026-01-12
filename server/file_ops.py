import base64
from protocol import encode

downloads = {}

async def upload_file(state, local, remote):
    """上传文件到客户端"""
    with open(local, "rb") as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            state.writer.write(encode({
                "type": "task",
                "action": "upload",
                "payload": {
                    "path": remote,
                    "data": base64.b64encode(chunk).decode()
                }
            }))
            await state.writer.drain()

async def handle_download_chunk(msg, state):
    """处理客户端下载分块"""
    f = downloads.get(msg["path"])
    if f:
        data = base64.b64decode(msg["data"])
        f.write(data)
        if msg["eof"]:
            f.close()
            downloads.pop(msg["path"], None)
            print(f"Download {msg['path']} finished")
        else:
            state.writer.write(encode({
                "type": "task",
                "action": "download",
                "payload": {
                    "path": msg["path"],
                    "offset": msg["offset"] + len(data)
                }
            }))
            await state.writer.drain()
