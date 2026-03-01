# 远程控制工具（Python）

这是一个基于 `asyncio` 的远程控制项目，支持：

- 客户端在线管理
- 远程桌面查看（`view` / `stop`）
- 远程命令执行（`exec`）
- 文件与目录上传下载（`upload` / `download`）
- 主机信息查询（`info`）
- 控制通道与桌面流通道 TLS 加密（含服务端证书指纹校验）

## 1. 项目结构

```text
remote_control/
├─ server/                 # 服务端
│  ├─ server_main.py       # 服务端主程序
│  ├─ screen_stream.py     # 桌面流接收与显示
│  ├─ protocol.py          # 通信协议常量
│  ├─ config.py            # 服务端配置
│  ├─ state.py             # 运行时状态
│  └─ cert/                # TLS 证书与私钥
│     ├─ server.crt
│     └─ server.key
├─ client/                 # 客户端（被控端）
│  ├─ client_main.py       # 客户端主程序
│  ├─ screen_stream.py     # 桌面流发送
│  ├─ file_ops.py          # 文件/目录传输
│  ├─ system_info.py       # 主机信息采集
│  ├─ tls_utils.py         # TLS 指纹校验
│  ├─ utils.py             # 抓屏工具
│  └─ config.py            # 客户端配置
├─ requirements.txt
└─ README.md
```

## 2. 环境要求

- Python 3.10 及以上（建议 3.11+）
- 可联网安装依赖
- 服务端若使用 `view`，需有图形界面（`cv2.imshow`）

安装依赖：

```bash
pip install -r requirements.txt
```

## 3. 配置说明

### 3.1 服务端配置

编辑 `server/config.py`：

- `SERVER_HOST`：服务端监听地址（常用 `0.0.0.0`）
- `CONTROL_PORT`：控制端口（默认 `9001`）
- `STREAM_PORT`：桌面流端口（默认 `9002`）
- `TLS_ENABLED`：是否启用 TLS（默认 `True`）
- `TLS_CERT_FILE` / `TLS_KEY_FILE`：服务端证书与私钥路径

### 3.2 客户端配置

编辑 `client/config.py`：

- `SERVER_HOST`：服务端 IP 或域名
- `CONTROL_PORT`：控制端口（与服务端一致）
- `STREAM_PORT`：流端口（与服务端一致）
- `TLS_ENABLED`：是否启用 TLS（与服务端一致）
- `SERVER_CERT_SHA256`：服务端证书 DER 指纹（SHA-256）

## 4. TLS 指纹配置（重要）

客户端通过证书指纹固定（pinning）校验服务端身份，防止中间人攻击。

当你更换 `server/cert/server.crt` 后，必须重新生成并更新客户端指纹：

```bash
openssl x509 -in server/cert/server.crt -outform der | openssl dgst -sha256
```

将输出的 64 位十六进制哈希填入 `client/config.py` 的 `SERVER_CERT_SHA256`。

## 5. 启动方式

### 5.1 启动服务端

```bash
python -m server.server_main
```

启动后会看到 `cmd>` 命令行提示和 `help` 信息。

### 5.2 启动客户端

在被控机器上执行：

```bash
python -m client.client_main
```

客户端会自动重连服务端。

## 6. 服务端命令用法

在服务端 `cmd>` 输入：

- `help`：显示帮助
- `list`：查看在线客户端
- `status`：查看在线数与推流状态
- `view <client_id>`：开始查看某客户端桌面
- `stop <client_id>`：停止查看某客户端桌面
- `exec <client_id> <command>`：在客户端执行命令并返回结果
- `info <client_id>`：查询客户端主机与硬件信息
- `upload <client_id> <local_path> [remote_path]`：上传文件或目录到客户端
- `download <client_id> <remote_path> [local_path]`：下载客户端文件或目录到服务端
- `exit`：退出服务端

说明：

- `client_id` 默认是客户端主机名。
- `upload/download` 都支持目录递归传输。
- 目录传输会自动打包/解包（`tar.gz`），保留子目录结构。

## 7. 部署到多台机器

1. 在服务端机器部署 `server/` 并准备证书。
2. 在每台客户端机器部署 `client/`。
3. 每台客户端 `client/config.py` 中将 `SERVER_HOST` 改为服务端地址。
4. 将服务端证书指纹同步到每台客户端的 `SERVER_CERT_SHA256`。
5. 先启动服务端，再启动客户端。

## 8. 常见问题

### 8.1 客户端连不上服务端

- 检查服务端是否已启动。
- 检查端口防火墙是否放行（`CONTROL_PORT` / `STREAM_PORT`）。
- 检查两端 `TLS_ENABLED` 是否一致。

### 8.2 TLS 指纹不匹配

- 说明客户端信任的证书指纹与服务端实际证书不一致。
- 重新生成指纹并更新 `client/config.py`。

### 8.3 `view` 没画面或窗口异常

- 被控端需要有图形会话和抓屏权限。
- 服务端需要图形环境显示窗口。

### 8.4 `exec` 长命令没返回

- 目前有超时与输出上限保护（防止会话卡死）。
- 建议执行可终止命令，例如 `ping -c 4`（Linux/macOS）或 `ping -n 4`（Windows）。

## 9. 安全建议

- 不要把 `server.key` 泄露到公开仓库。
- 定期轮换证书，并同步更新客户端指纹。
- 生产环境建议后续升级到 mTLS（双向证书认证）。

