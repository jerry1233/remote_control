import asyncio
import json
import os
import socket
from client import config, screen_stream, file_ops, system_info
from server import protocol

client_id = socket.gethostname()

async def connect_control():
    while True:
        try:
            reader, writer = await asyncio.open_connection(
                config.SERVER_HOST,
                config.CONTROL_PORT
            )
            writer.write(f"{client_id}\n".encode())
            await writer.drain()
            return reader, writer
        except Exception:
            await asyncio.sleep(5)  # server 没启动时重试

async def main():
    reader, writer = await connect_control()
    stream_task = None
    stream_stop = None

    while True:
        try:
            data = await reader.readline()
            if not data:
                if stream_stop is not None:
                    stream_stop.set()
                if stream_task is not None:
                    try:
                        await stream_task
                    except Exception:
                        pass
                reader, writer = await connect_control()
                continue
            cmd = data.decode().strip()
            if cmd == protocol.CMD_VIEW:
                if stream_task is None or stream_task.done():
                    stream_stop = asyncio.Event()
                    stream_task = asyncio.create_task(
                        screen_stream.start_stream(client_id, stream_stop)
                    )
            elif cmd == protocol.CMD_STOP_VIEW:
                if stream_stop is not None:
                    stream_stop.set()
            elif cmd.startswith(f"{protocol.CMD_EXEC} "):
                command = cmd[5:]
                if not command:
                    continue
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                timed_out = False
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                except asyncio.TimeoutError:
                    timed_out = True
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    try:
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3)
                    except Exception:
                        stdout, stderr = b"", b""
                output = b""
                output += f"[exit {proc.returncode}]\n".encode()
                if stdout:
                    output += stdout
                if stderr:
                    output += stderr
                max_bytes = 64 * 1024
                if len(output) > max_bytes:
                    output = output[:max_bytes] + b"\n...[output truncated]...\n"
                if timed_out:
                    output = b"[timeout after 10s]\n" + output
                writer.write(f"{protocol.CMD_EXEC_RESULT}\n".encode())
                writer.write(len(output).to_bytes(8, "big") + output)
                await writer.drain()
            elif cmd == protocol.CMD_UPLOAD:
                ok, msg = await file_ops.recv_file_from_control(reader)
                msg_bytes = msg.encode("utf-8", errors="replace")
                writer.write(f"{protocol.CMD_UPLOAD_RESULT}\n".encode())
                writer.write((1 if ok else 0).to_bytes(1, "big"))
                writer.write(len(msg_bytes).to_bytes(4, "big"))
                writer.write(msg_bytes)
                await writer.drain()
            elif cmd == protocol.CMD_UPLOAD_TREE:
                ok, msg = await file_ops.recv_tree_from_control(reader)
                msg_bytes = msg.encode("utf-8", errors="replace")
                writer.write(f"{protocol.CMD_UPLOAD_RESULT}\n".encode())
                writer.write((1 if ok else 0).to_bytes(1, "big"))
                writer.write(len(msg_bytes).to_bytes(4, "big"))
                writer.write(msg_bytes)
                await writer.drain()
            elif cmd == protocol.CMD_INFO:
                try:
                    payload = {
                        "ok": True,
                        "data": system_info.collect_system_info(),
                    }
                except Exception as e:
                    payload = {
                        "ok": False,
                        "error": str(e),
                    }
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                writer.write(f"{protocol.CMD_INFO_RESULT}\n".encode())
                writer.write(len(raw).to_bytes(8, "big"))
                writer.write(raw)
                await writer.drain()
            elif cmd == protocol.CMD_DOWNLOAD:
                ok, msg, path_to_send, filesize, mode, entry_name = await file_ops.send_file_to_control(reader)
                msg_bytes = msg.encode("utf-8", errors="replace")
                try:
                    writer.write(f"{protocol.CMD_DOWNLOAD_RESULT}\n".encode())
                    writer.write((1 if ok else 0).to_bytes(1, "big"))
                    writer.write(len(msg_bytes).to_bytes(4, "big"))
                    writer.write(msg_bytes)
                    if ok:
                        writer.write(mode.to_bytes(1, "big"))
                        entry_name_bytes = entry_name.encode("utf-8", errors="replace")
                        writer.write(len(entry_name_bytes).to_bytes(4, "big"))
                        writer.write(entry_name_bytes)
                        writer.write(filesize.to_bytes(8, "big"))
                        with open(path_to_send, "rb") as f:
                            while True:
                                chunk = f.read(config.FILE_BUFFER_SIZE)
                                if not chunk:
                                    break
                                writer.write(chunk)
                    await writer.drain()
                finally:
                    if ok and mode == 1:
                        try:
                            os.remove(path_to_send)
                        except Exception:
                            pass
        except Exception:
            if stream_stop is not None:
                stream_stop.set()
            if stream_task is not None:
                try:
                    await stream_task
                except Exception:
                    pass
            reader, writer = await connect_control()

if __name__ == "__main__":
    asyncio.run(main())
