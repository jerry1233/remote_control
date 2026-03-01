# 保存客户端状态
clients = {}        # client_id -> writer
streaming = set()   # 正在推流的 client_id

# client_id -> {"event": asyncio.Event, "ok": bool|None, "message": str}
pending_uploads = {}

# client_id -> {"event": asyncio.Event, "ok": bool|None, "message": str, "save_path": str}
pending_downloads = {}

# client_id -> {"event": asyncio.Event, "ok": bool|None, "message": str}
pending_infos = {}
