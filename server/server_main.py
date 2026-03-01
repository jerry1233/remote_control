import asyncio
import json
import os
import shlex
import ssl
import tarfile
import tempfile
from server import config, protocol, state
from server.screen_stream import handle_stream

def _build_server_ssl_context():
    if not config.TLS_ENABLED:
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(config.TLS_CERT_FILE, config.TLS_KEY_FILE)
    return ctx

async def _send_upload_request(writer, local_path, remote_path):
    file_size = os.path.getsize(local_path)
    source_name = os.path.basename(local_path)
    writer.write(f"{protocol.CMD_UPLOAD}\n".encode())
    remote_path_bytes = remote_path.encode()
    source_name_bytes = source_name.encode()
    writer.write(len(remote_path_bytes).to_bytes(4, "big"))
    writer.write(remote_path_bytes)
    writer.write(len(source_name_bytes).to_bytes(4, "big"))
    writer.write(source_name_bytes)
    writer.write(file_size.to_bytes(8, "big"))
    with open(local_path, "rb") as f:
        while True:
            chunk = f.read(config.FILE_BUFFER_SIZE)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()

def _build_tar_archive(source_path):
    source_path = os.path.abspath(source_path)
    root_name = os.path.basename(source_path.rstrip("/\\"))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
    tmp_path = tmp.name
    tmp.close()
    with tarfile.open(tmp_path, "w:gz") as tar:
        tar.add(source_path, arcname=root_name)
    return tmp_path

async def _send_upload_tree_request(writer, local_path, remote_base_path):
    archive_path = _build_tar_archive(local_path)
    try:
        archive_size = os.path.getsize(archive_path)
        writer.write(f"{protocol.CMD_UPLOAD_TREE}\n".encode())
        remote_path_bytes = remote_base_path.encode()
        writer.write(len(remote_path_bytes).to_bytes(4, "big"))
        writer.write(remote_path_bytes)
        writer.write(archive_size.to_bytes(8, "big"))
        with open(archive_path, "rb") as f:
            while True:
                chunk = f.read(config.FILE_BUFFER_SIZE)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
    finally:
        try:
            os.remove(archive_path)
        except Exception:
            pass

async def _send_download_request(writer, remote_path):
    writer.write(f"{protocol.CMD_DOWNLOAD}\n".encode())
    remote_path_bytes = remote_path.encode()
    writer.write(len(remote_path_bytes).to_bytes(4, "big"))
    writer.write(remote_path_bytes)
    await writer.drain()

async def _wait_transfer_result(client_id, pending_map, timeout=30):
    pending = pending_map.get(client_id)
    if pending is None:
        return False, "内部错误: 无待处理任务"
    try:
        await asyncio.wait_for(pending["event"].wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pending_map.pop(client_id, None)
        return False, f"等待客户端响应超时({timeout}s)"
    ok = pending.get("ok", False)
    msg = pending.get("message", "无返回信息")
    pending_map.pop(client_id, None)
    return ok, msg

async def _drain_bytes(reader, size):
    remaining = size
    while remaining > 0:
        chunk_size = min(config.FILE_BUFFER_SIZE, remaining)
        chunk = await reader.readexactly(chunk_size)
        remaining -= len(chunk)

def _is_within_directory(base_dir, target_path):
    base_dir = os.path.abspath(base_dir)
    target_path = os.path.abspath(target_path)
    return os.path.commonpath([base_dir]) == os.path.commonpath([base_dir, target_path])

def _safe_extract_tar(tar, dest_dir):
    for member in tar.getmembers():
        member_path = os.path.join(dest_dir, member.name)
        if not _is_within_directory(dest_dir, member_path):
            raise ValueError(f"非法路径: {member.name}")
    try:
        tar.extractall(dest_dir, filter="data")
    except TypeError:
        # Python < 3.12 does not support the filter argument.
        tar.extractall(dest_dir)

def _resolve_download_file_path(target_path, entry_name, path_specified):
    if not path_specified:
        return os.path.join(".", entry_name)
    if os.path.isdir(target_path):
        return os.path.join(target_path, entry_name)
    return target_path

def _resolve_download_extract_dir(target_path, path_specified):
    if not path_specified:
        return "."
    if os.path.exists(target_path) and not os.path.isdir(target_path):
        raise ValueError(f"本地路径不是目录: {target_path}")
    os.makedirs(target_path, exist_ok=True)
    return target_path

def _format_mounts(mounts):
    if not mounts:
        return "无"
    lines = []
    for item in mounts:
        mnt = item.get("mount", "未知")
        total = item.get("total_human", "未知")
        used = item.get("used_human", "未知")
        lines.append(f"    - {mnt} (总容量: {total}, 已用: {used})")
    return "\n".join(lines)

def _format_info_output(client_id, payload):
    if not payload.get("ok"):
        err = payload.get("error", "未知错误")
        return f"[INFO] {client_id} 获取失败: {err}"
    data = payload.get("data", {})
    basic = data.get("basic", {})
    hardware = data.get("hardware", {})
    mounts_text = _format_mounts(hardware.get("mounts", []))
    return (
        f"[INFO] {client_id}\n"
        f"1. 基本信息\n"
        f"  主机名: {basic.get('hostname', '未知')}\n"
        f"  公网IP地址: {basic.get('public_ip', '未知')}\n"
        f"  局域网IP地址: {basic.get('local_ip', '未知')}\n"
        f"  MAC地址: {basic.get('mac', '未知')}\n"
        f"  时区+主机时间: {basic.get('timezone', '未知')} {basic.get('time', '未知')}\n"
        f"  系统语言: {basic.get('language', '未知')}\n"
        f"  操作系统: {basic.get('os', '未知')}\n"
        f"  内核版本: {basic.get('kernel', '未知')}\n"
        f"  系统启动时长: {basic.get('uptime', '未知')}\n"
        f"  当前用户: {basic.get('user', '未知')}\n"
        f"  用户权限: {basic.get('privilege', '未知')}\n"
        f"2. 硬件信息\n"
        f"  CPU型号: {hardware.get('cpu_model', '未知')}\n"
        f"  核心数量(物理/逻辑): {hardware.get('cpu_cores_physical', '未知')}/{hardware.get('cpu_cores_logical', '未知')}\n"
        f"  GPU型号: {hardware.get('gpu_model', '未知')}\n"
        f"  运行内存容量(当前占用): {hardware.get('memory_total', '未知')} ({hardware.get('memory_used', '未知')})\n"
        f"  硬盘容量(当前占用): {hardware.get('disk_total', '未知')} ({hardware.get('disk_used', '未知')})\n"
        f"  硬盘挂载点:\n"
        f"{mounts_text}"
    )

async def handle_client(reader, writer):
    client_id = (await reader.readline()).decode().strip()
    state.clients[client_id] = writer
    print(f"[+] {client_id} connected")

    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            cmd = data.decode().strip()
            if cmd == protocol.CMD_VIEW:
                pass  # client 会自己开流
            elif cmd == protocol.CMD_EXEC_RESULT:
                result_len_bytes = await reader.readexactly(8)
                result_len = int.from_bytes(result_len_bytes, "big")
                result_data = await reader.readexactly(result_len)
                try:
                    text = result_data.decode("utf-8", errors="replace")
                except Exception:
                    text = str(result_data)
                print(f"[EXEC_RESULT] {client_id}:\n{text}")
            elif cmd == protocol.CMD_UPLOAD_RESULT:
                ok = bool(int.from_bytes(await reader.readexactly(1), "big"))
                msg_len = int.from_bytes(await reader.readexactly(4), "big")
                msg = (await reader.readexactly(msg_len)).decode("utf-8", errors="replace")
                pending = state.pending_uploads.get(client_id)
                if pending is not None:
                    pending["ok"] = ok
                    pending["message"] = msg
                    pending["event"].set()
            elif cmd == protocol.CMD_DOWNLOAD_RESULT:
                ok = bool(int.from_bytes(await reader.readexactly(1), "big"))
                msg_len = int.from_bytes(await reader.readexactly(4), "big")
                msg = (await reader.readexactly(msg_len)).decode("utf-8", errors="replace")
                pending = state.pending_downloads.get(client_id)
                if pending is not None:
                    pending["ok"] = ok
                    pending["message"] = msg
                    if ok:
                        mode = int.from_bytes(await reader.readexactly(1), "big")
                        name_len = int.from_bytes(await reader.readexactly(4), "big")
                        entry_name = (await reader.readexactly(name_len)).decode("utf-8", errors="replace")
                        file_size = int.from_bytes(await reader.readexactly(8), "big")
                        remaining = file_size
                        if mode == 0:
                            save_path = _resolve_download_file_path(
                                pending["save_path"],
                                entry_name,
                                pending.get("path_specified", False),
                            )
                            try:
                                with open(save_path, "wb") as f:
                                    while remaining > 0:
                                        chunk_size = min(config.FILE_BUFFER_SIZE, remaining)
                                        chunk = await reader.readexactly(chunk_size)
                                        f.write(chunk)
                                        remaining -= len(chunk)
                                pending["message"] = f"{msg} -> {save_path}"
                            except Exception as e:
                                await _drain_bytes(reader, remaining)
                                pending["ok"] = False
                                pending["message"] = f"保存失败: {e}"
                        elif mode == 1:
                            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
                            tmp_path = tmp.name
                            tmp.close()
                            try:
                                with open(tmp_path, "wb") as f:
                                    while remaining > 0:
                                        chunk_size = min(config.FILE_BUFFER_SIZE, remaining)
                                        chunk = await reader.readexactly(chunk_size)
                                        f.write(chunk)
                                        remaining -= len(chunk)
                                extract_dir = _resolve_download_extract_dir(
                                    pending["save_path"],
                                    pending.get("path_specified", False),
                                )
                                with tarfile.open(tmp_path, "r:gz") as tar:
                                    _safe_extract_tar(tar, extract_dir)
                                pending["message"] = f"{msg} -> {extract_dir}"
                            except Exception as e:
                                if remaining > 0:
                                    await _drain_bytes(reader, remaining)
                                pending["ok"] = False
                                pending["message"] = f"保存失败: {e}"
                            finally:
                                try:
                                    os.remove(tmp_path)
                                except Exception:
                                    pass
                        else:
                            await _drain_bytes(reader, remaining)
                            pending["ok"] = False
                            pending["message"] = f"未知下载模式: {mode}"
                    pending["event"].set()
            elif cmd == protocol.CMD_INFO_RESULT:
                data_len = int.from_bytes(await reader.readexactly(8), "big")
                raw = await reader.readexactly(data_len)
                try:
                    payload = json.loads(raw.decode("utf-8", errors="replace"))
                except Exception as e:
                    payload = {"ok": False, "error": f"解析失败: {e}"}
                pending = state.pending_infos.get(client_id)
                if pending is not None:
                    pending["ok"] = bool(payload.get("ok"))
                    pending["message"] = _format_info_output(client_id, payload)
                    pending["event"].set()
    except Exception as e:
        print(f"[!] {client_id} 通信异常: {e}")
    finally:
        state.clients.pop(client_id, None)
        state.streaming.discard(client_id)
        if client_id in state.pending_uploads:
            state.pending_uploads[client_id]["ok"] = False
            state.pending_uploads[client_id]["message"] = "客户端已断开"
            state.pending_uploads[client_id]["event"].set()
        if client_id in state.pending_downloads:
            state.pending_downloads[client_id]["ok"] = False
            state.pending_downloads[client_id]["message"] = "客户端已断开"
            state.pending_downloads[client_id]["event"].set()
        if client_id in state.pending_infos:
            state.pending_infos[client_id]["ok"] = False
            state.pending_infos[client_id]["message"] = "客户端已断开"
            state.pending_infos[client_id]["event"].set()
        writer.close()
        print(f"[-] {client_id} disconnected")

async def stream_server():
    ssl_ctx = _build_server_ssl_context()

    async def stream_accept(reader, writer):
        client_id = (await reader.readline()).decode().strip()
        await handle_stream(reader, client_id)

    server = await asyncio.start_server(
        stream_accept,
        config.SERVER_HOST,
        config.STREAM_PORT,
        ssl=ssl_ctx,
    )
    async with server:
        await server.serve_forever()

async def cmd_loop():
    help_text = (
        "可用命令:\n"
        "  list                查看在线客户端列表\n"
        "  view <client_id>    开始查看指定客户端桌面\n"
        "  stop <client_id>    停止查看指定客户端桌面\n"
        "  exec <client_id> <command>  在客户端执行命令并返回结果\n"
        "  info <client_id>    查看客户端主机与硬件信息\n"
        "  upload <client_id> <local_path> [remote_path]  上传文件/目录到客户端\n"
        "  download <client_id> <remote_path> [local_path]  下载客户端文件/目录到服务端\n"
        "  status              查看当前状态\n"
        "  help                显示此帮助\n"
        "  exit                退出服务端\n"
    )
    print(help_text)
    while True:
        cmd = await asyncio.to_thread(input, "cmd> ")
        if cmd in ("help", "?"):
            print(help_text)
            continue
        if cmd in ("exit", "quit"):
            print("正在退出服务端...")
            break
        if cmd == "list":
            print(list(state.clients.keys()))
        else:
            try:
                parts = shlex.split(cmd)
            except ValueError as e:
                print(f"命令解析失败: {e}")
                continue
            if not parts:
                continue
            action = parts[0]
            if action == "view":
                if len(parts) != 2:
                    print("用法: view <client_id>")
                    continue
                cid = parts[1]
                if cid in state.clients:
                    state.clients[cid].write(f"{protocol.CMD_VIEW}\n".encode())
                    await state.clients[cid].drain()
                else:
                    print(f"客户端不在线: {cid}")
            elif action == "stop":
                if len(parts) != 2:
                    print("用法: stop <client_id>")
                    continue
                cid = parts[1]
                if cid in state.clients:
                    state.clients[cid].write(f"{protocol.CMD_STOP_VIEW}\n".encode())
                    await state.clients[cid].drain()
                else:
                    print(f"客户端不在线: {cid}")
            elif action == "exec":
                if len(parts) < 3:
                    print("用法: exec <client_id> <command>")
                    continue
                cid = parts[1]
                if cid in state.clients:
                    command = " ".join(parts[2:])
                    state.clients[cid].write(f"{protocol.CMD_EXEC} {command}\n".encode())
                    await state.clients[cid].drain()
                else:
                    print(f"客户端不在线: {cid}")
            elif action == "info":
                if len(parts) != 2:
                    print("用法: info <client_id>")
                    continue
                cid = parts[1]
                if cid not in state.clients:
                    print(f"客户端不在线: {cid}")
                    continue
                if cid in state.pending_infos:
                    print(f"客户端 {cid} 的信息查询正在处理中")
                    continue
                state.pending_infos[cid] = {"event": asyncio.Event(), "ok": None, "message": ""}
                try:
                    state.clients[cid].write(f"{protocol.CMD_INFO}\n".encode())
                    await state.clients[cid].drain()
                except Exception as e:
                    state.pending_infos.pop(cid, None)
                    print(f"[INFO] {cid} 查询失败 - 发送中断: {e}")
                    continue
                ok, msg = await _wait_transfer_result(cid, state.pending_infos, timeout=45)
                if ok:
                    print(msg)
                else:
                    print(f"[INFO] {cid} 查询失败: {msg}")
            elif action == "upload":
                if len(parts) not in (3, 4):
                    print("用法: upload <client_id> <local_path> [remote_path]")
                    continue
                cid = parts[1]
                local_path = parts[2]
                if os.path.isdir(local_path):
                    remote_path = parts[3] if len(parts) == 4 else "."
                else:
                    remote_path = parts[3] if len(parts) == 4 else os.path.basename(local_path)
                if cid not in state.clients:
                    print(f"客户端不在线: {cid}")
                    continue
                if not os.path.exists(local_path):
                    print(f"本地文件不存在: {local_path}")
                    continue
                if cid in state.pending_uploads:
                    print(f"客户端 {cid} 有上传任务正在处理中")
                    continue
                state.pending_uploads[cid] = {"event": asyncio.Event(), "ok": None, "message": ""}
                try:
                    if os.path.isdir(local_path):
                        await _send_upload_tree_request(state.clients[cid], local_path, remote_path)
                    else:
                        await _send_upload_request(state.clients[cid], local_path, remote_path)
                except Exception as e:
                    state.pending_uploads.pop(cid, None)
                    print(f"[UPLOAD] {cid}: 失败 - 发送中断: {e}")
                    continue
                ok, msg = await _wait_transfer_result(cid, state.pending_uploads)
                print(f"[UPLOAD] {cid}: {'成功' if ok else '失败'} - {msg}")
            elif action == "download":
                if len(parts) not in (3, 4):
                    print("用法: download <client_id> <remote_path> [local_path]")
                    continue
                cid = parts[1]
                remote_path = parts[2]
                path_specified = len(parts) == 4
                local_path = parts[3] if path_specified else "."
                if cid not in state.clients:
                    print(f"客户端不在线: {cid}")
                    continue
                if cid in state.pending_downloads:
                    print(f"客户端 {cid} 有下载任务正在处理中")
                    continue
                state.pending_downloads[cid] = {
                    "event": asyncio.Event(),
                    "ok": None,
                    "message": "",
                    "save_path": local_path,
                    "path_specified": path_specified,
                }
                await _send_download_request(state.clients[cid], remote_path)
                ok, msg = await _wait_transfer_result(cid, state.pending_downloads)
                print(f"[DOWNLOAD] {cid}: {'成功' if ok else '失败'} - {msg}")
            elif action == "status":
                print(f"在线客户端: {len(state.clients)}")
                print(f"正在推流: {list(state.streaming)}")
            else:
                print("未知命令，输入 help 查看用法。")

async def main():
    ssl_ctx = _build_server_ssl_context()
    server = await asyncio.start_server(
        handle_client,
        config.SERVER_HOST,
        config.CONTROL_PORT,
        ssl=ssl_ctx,
    )
    asyncio.create_task(stream_server())
    cmd_task = asyncio.create_task(cmd_loop())
    async with server:
        await cmd_task

if __name__ == "__main__":
    asyncio.run(main())
