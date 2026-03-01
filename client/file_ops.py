import os
import tarfile
import tempfile
from client import config

async def _drain_bytes(reader, size):
    remaining = size
    while remaining > 0:
        chunk_size = min(config.FILE_BUFFER_SIZE, remaining)
        chunk = await reader.readexactly(chunk_size)
        remaining -= len(chunk)

def _resolve_upload_target(remote_path, source_name):
    if remote_path.endswith("/") or remote_path.endswith("\\"):
        return os.path.join(remote_path, source_name)
    if os.path.isdir(remote_path):
        return os.path.join(remote_path, source_name)
    return remote_path

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

def _build_tar_archive(source_path):
    source_path = os.path.abspath(source_path)
    root_name = os.path.basename(source_path.rstrip("/\\"))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
    tmp_path = tmp.name
    tmp.close()
    with tarfile.open(tmp_path, "w:gz") as tar:
        tar.add(source_path, arcname=root_name)
    return tmp_path, root_name

async def recv_file_from_control(reader):
    remote_path_len_bytes = await reader.readexactly(4)
    remote_path_len = int.from_bytes(remote_path_len_bytes, "big")
    remote_path = (await reader.readexactly(remote_path_len)).decode()

    source_name_len_bytes = await reader.readexactly(4)
    source_name_len = int.from_bytes(source_name_len_bytes, "big")
    source_name = (await reader.readexactly(source_name_len)).decode()

    filesize_bytes = await reader.readexactly(8)
    filesize = int.from_bytes(filesize_bytes, "big")
    filename = _resolve_upload_target(remote_path, source_name)
    parent_dir = os.path.dirname(filename) or "."
    if not os.path.isdir(parent_dir):
        await _drain_bytes(reader, filesize)
        return False, f"上传失败: 目录不存在 {parent_dir}"

    remaining = filesize
    try:
        with open(filename, "wb") as f:
            while remaining > 0:
                chunk_size = min(config.FILE_BUFFER_SIZE, remaining)
                chunk = await reader.readexactly(chunk_size)
                f.write(chunk)
                remaining -= len(chunk)
        return True, f"上传成功: {filename}"
    except Exception as e:
        await _drain_bytes(reader, remaining)
        return False, f"上传失败: {e}"

async def recv_tree_from_control(reader):
    remote_path_len_bytes = await reader.readexactly(4)
    remote_path_len = int.from_bytes(remote_path_len_bytes, "big")
    remote_path = (await reader.readexactly(remote_path_len)).decode()

    archive_size_bytes = await reader.readexactly(8)
    archive_size = int.from_bytes(archive_size_bytes, "big")
    target_dir = remote_path
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
    if not os.path.isdir(target_dir):
        await _drain_bytes(reader, archive_size)
        return False, f"上传失败: 目标不是目录 {target_dir}"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
    tmp_path = tmp.name
    tmp.close()
    remaining = archive_size
    try:
        with open(tmp_path, "wb") as f:
            while remaining > 0:
                chunk_size = min(config.FILE_BUFFER_SIZE, remaining)
                chunk = await reader.readexactly(chunk_size)
                f.write(chunk)
                remaining -= len(chunk)
        with tarfile.open(tmp_path, "r:gz") as tar:
            _safe_extract_tar(tar, target_dir)
        return True, f"目录上传成功: {target_dir}"
    except Exception as e:
        if remaining > 0:
            await _drain_bytes(reader, remaining)
        return False, f"目录上传失败: {e}"
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

async def send_file_to_control(reader):
    filename_len_bytes = await reader.readexactly(4)
    filename_len = int.from_bytes(filename_len_bytes, "big")
    filename = (await reader.readexactly(filename_len)).decode()

    if not os.path.exists(filename):
        return False, f"路径不存在: {filename}", "", 0, 0, None

    if os.path.isdir(filename):
        archive_path, root_name = _build_tar_archive(filename)
        archive_size = os.path.getsize(archive_path)
        return True, f"下载目录成功: {filename}", archive_path, archive_size, 1, root_name

    filesize = os.path.getsize(filename)
    return True, f"下载文件成功: {filename}", filename, filesize, 0, os.path.basename(filename)
