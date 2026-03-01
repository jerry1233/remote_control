import os

SERVER_HOST = "127.0.0.1"
CONTROL_PORT = 9001
STREAM_PORT = 9002
FILE_BUFFER_SIZE = 4096

# TLS 配置
TLS_ENABLED = True
# 服务端证书 SHA-256（DER 指纹，小写十六进制）

SERVER_CERT_SHA256 = "92a39882c1a109491be38cd4e34783dc5b17dba72702a68d3ad35707a4ae89be"

# 这是“服务端证书指纹（pin）”，用于防中间人攻击。
# 含义：
# 客户端拿到服务端证书后，会算一遍 SHA-256。
# 必须和 SERVER_CERT_SHA256 完全一致才继续通信。
# 不一致就拒绝连接。
# 所以它相当于“客户端只信这一张服务端证书”。
# 注意：
# 你更换了 server.crt 后，这个值必须同步更新，否则客户端会连不上。
# 这是证书的 DER 编码哈希（不是证书文件文本直接哈希）。
# 可用这条命令生成新值：openssl x509 -in /Users/ning/Desktop/remote_control/server/cert/server.crt -outform der | openssl dgst -sha256