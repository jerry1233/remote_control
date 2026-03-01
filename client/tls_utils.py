import hashlib
import ssl
from client import config


def build_client_ssl_context():
    if not config.TLS_ENABLED:
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # 使用证书指纹固定（pinning）校验服务端身份。
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def verify_server_fingerprint(writer):
    if not config.TLS_ENABLED:
        return
    expected = (config.SERVER_CERT_SHA256 or "").lower().replace(":", "").strip()
    if not expected:
        raise ssl.SSLError("未配置 SERVER_CERT_SHA256，无法校验服务端证书")
    ssl_obj = writer.get_extra_info("ssl_object")
    if ssl_obj is None:
        raise ssl.SSLError("TLS 已启用但连接未建立 TLS 会话")
    cert_der = ssl_obj.getpeercert(binary_form=True)
    if not cert_der:
        raise ssl.SSLError("未读取到服务端证书")
    actual = hashlib.sha256(cert_der).hexdigest()
    if actual != expected:
        raise ssl.SSLError(f"服务端证书指纹不匹配: {actual}")
