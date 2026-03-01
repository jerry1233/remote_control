import os

# 服务端配置
SERVER_HOST = "0.0.0.0"
CONTROL_PORT = 9001       # 控制端口
STREAM_PORT = 9002        # 桌面流端口

# 文件传输参数
FILE_BUFFER_SIZE = 4096

# TLS 配置
TLS_ENABLED = True
TLS_CERT_FILE = os.path.join(os.path.dirname(__file__), "cert", "server.crt")
TLS_KEY_FILE = os.path.join(os.path.dirname(__file__), "cert", "server.key")
