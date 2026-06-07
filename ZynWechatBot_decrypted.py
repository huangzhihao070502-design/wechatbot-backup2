import threading
import time
import json
import uuid
import base64
import random
import sys
import subprocess
import os
import hashlib
import struct
import shutil

try:
    from Crypto.Cipher import AES as _CryptoAES
    _HAS_PYCRYPTODOME = True
except ImportError:
    _HAS_PYCRYPTODOME = False
from pathlib import Path
from typing import Optional, Dict, List, Union
from datetime import datetime
import io
import socketserver
from http.server import SimpleHTTPRequestHandler
import select
import urllib.request
import urllib.error
import urllib.parse

def is_termux():
    if sys.platform != "linux":
        return False
    
    checks = [
        "termux" in sys.prefix.lower(),
        "com.termux" in sys.prefix.lower(),
        "termux" in sys.executable.lower(),
        "com.termux" in sys.executable.lower(),
    ]
    
    if os.environ.get("TERMUX") or os.environ.get("PREFIX", "").startswith("/data/data/com.termux"):
        return True
    
    termux_paths = [
        "/data/data/com.termux",
        "/data/data/com.termux/files/usr/bin/python",
    ]
    for path in termux_paths:
        try:
            if os.path.exists(path):
                return True
        except Exception:
            pass
    
    return any(checks)

def setup_termux_compat():
    if not is_termux():
        return
    
    print("=" * 60)
    print("[Sioboot] 检测到 Termux 环境")
    print("[Sioboot] 正在启用兼容模式...")
    print("=" * 60)
    
    env_vars = {
        'TMPDIR': '/data/data/com.termux/files/usr/tmp',
        'TEMP': '/data/data/com.termux/files/usr/tmp',
        'TMP': '/data/data/com.termux/files/usr/tmp',
        'TERMUX': '1',
        'LD_LIBRARY_PATH': '/data/data/com.termux/files/usr/lib',
        'PATH': '/data/data/com.termux/files/usr/bin:' + os.environ.get('PATH', ''),
    }
    
    for key, value in env_vars.items():
        os.environ.setdefault(key, value)
        print(f"[TERMUX]   ✓ 设置 {key}")
    
    tmp_dir = Path("/data/data/com.termux/files/usr/tmp")
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        print(f"[TERMUX]   ✓ 确保临时目录存在: {tmp_dir}")
    except Exception as e:
        print(f"[TERMUX]   ⚠ 无法创建临时目录: {e}")
    
    tools = ["pkg", "python", "pip"]
    for tool in tools:
        if shutil.which(tool):
            print(f"[TERMUX]   ✓ {tool} 可用")
        else:
            print(f"[TERMUX]   ⚠ {tool} 未找到")
    
    print("[TERMUX] 兼容性设置完成")
    print("=" * 60)

setup_termux_compat()

def ensure_pip_available():
    if is_termux():
        print("[Sioboot] 检测到 Termux 环境，尝试使用 pkg 安装 pip...")
        try:
            subprocess.check_call(["pkg", "install", "-y", "python-pip"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[TERMUX] Termux pip 安装成功")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("[TERMUX] pkg 安装失败，尝试其他方式...")
    
    try:
        import pip
        return True
    except ImportError:
        pass
    
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return True
    except Exception:
        pass
    
    try:
        import ensurepip
        print("正在通过 ensurepip 安装 pip...")
        
        try:
            ensurepip.bootstrap(upgrade=True)
        except Exception as bootstrap_err:
            print(f"  bootstrap 升级失败，尝试基础安装...")
            ensurepip.bootstrap()
        
        import site
        site.main()
        
        result = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print("pip 安装成功")
            return True
        else:
            print(f"  验证失败: {result.stderr}")
            
            import importlib
            try:
                if 'pip' in sys.modules:
                    del sys.modules['pip']
                importlib.import_module('pip')
                print("pip 安装成功（通过重新导入）")
                return True
            except ImportError:
                pass
                
    except Exception as e:
        print(f"ensurepip 安装失败: {e}")
    
    try:
        print("正在下载 get-pip.py...")
        import tempfile
        get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
        
        if is_termux():
            temp_dir = Path("/data/data/com.termux/files/usr/tmp") / "temp_pip_install"
        else:
            temp_dir = Path(tempfile.gettempdir()) / "temp_pip_install"
        
        temp_dir.mkdir(exist_ok=True, parents=True)
        get_pip_path = temp_dir / "get-pip.py"
        
        urllib.request.urlretrieve(get_pip_url, str(get_pip_path))
        
        print("正在运行 get-pip.py 安装 pip...")
        result = subprocess.run(
            [sys.executable, str(get_pip_path), "--user", "--no-warn-script-location"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"用户目录安装失败，尝试使用临时目录...")
            target_dir = Path(temp_dir) / "pip_target"
            target_dir.mkdir(exist_ok=True)
            
            result = subprocess.run(
                [sys.executable, str(get_pip_path), "--target", str(target_dir)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise Exception(result.stderr)
                
            sys.path.insert(0, str(target_dir))
        
        get_pip_path.unlink(missing_ok=True)
        print("pip 安装成功")
        return True
    except Exception as e:
        print(f"get-pip.py 安装失败: {e}")
    
    return False

_PIP_MIRRORS = [
    ("https://pypi.tuna.tsinghua.edu.cn/simple", "pypi.tuna.tsinghua.edu.cn"),
    ("https://mirrors.aliyun.com/pypi/simple", "mirrors.aliyun.com"),
    ("https://mirrors.cloud.tencent.com/pypi/simple", "mirrors.cloud.tencent.com"),
    ("https://pypi.mirrors.ustc.edu.cn/simple", "pypi.mirrors.ustc.edu.cn"),
    ("https://mirrors.huaweicloud.com/repository/pypi/simple", "mirrors.huaweicloud.com"),
]

def _get_pip_index_args():
    import urllib.request
    for url, host in _PIP_MIRRORS:
        try:
            urllib.request.urlopen(url + "/", timeout=5)
            return ["-i", url, "--trusted-host", host]
        except Exception:
            continue
    return []

def install_package(package):
    index_args = _get_pip_index_args()
    if index_args:
        print(f"  使用镜像源: {index_args[1]}")

    install_commands = []
    if index_args:
        install_commands.append([sys.executable, "-m", "pip", "install", package] + index_args)
        install_commands.append([sys.executable, "-m", "pip", "install", "--user", package] + index_args)
    install_commands.append([sys.executable, "-m", "pip", "install", package])
    install_commands.append([sys.executable, "-m", "pip", "install", "--user", package])

    pip_exe = shutil.which("pip") or shutil.which("pip3")
    if pip_exe:
        if index_args:
            install_commands.insert(0, [pip_exe, "install", package] + index_args)
        install_commands.append([pip_exe, "install", package])
    
    for cmd in install_commands:
        try:
            print(f"  尝试: {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )
            
            if result.returncode == 0:
                return True
            else:
                err_msg = result.stderr.strip()
                if len(err_msg) > 200:
                    err_msg = err_msg[-200:]
                print(f"  失败: {err_msg}")
        except subprocess.TimeoutExpired:
            print(f"  超时(180s)")
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"  错误: {e}")
    
    if is_termux():
        try:
            print("  [TERMUX] 尝试 Termux 方式...")
            termux_cmd = ["pip", "install", package]
            if index_args:
                termux_cmd += index_args
            subprocess.check_call(termux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    
    return False

def check_and_install_dependencies():
    required_packages = {
        "qrcode": "qrcode"
    }
    
    missing_packages = []
    for pip_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(pip_name)
    
    if missing_packages:
        print(f"需要安装的库: {', '.join(missing_packages)}")
        
        has_pip = True
        try:
            import pip
        except ImportError:
            print("未检测到 pip，正在尝试自动安装...")
            has_pip = ensure_pip_available()
        
        if not has_pip:
            print("错误: 无法安装 pip，请手动安装后重试")
            print("  - Windows: python -m ensurepip --upgrade")
            print("  - Linux/Mac: python3 -m ensurepip --upgrade")
            print("  - Termux: pkg install python-pip")
            sys.exit(1)
        
        for package in missing_packages:
            print(f"正在安装 {package}...")
            if install_package(package):
                print(f"{package} 安装完成")
            else:
                print(f"{package} 安装失败，请手动安装: pip install {package}")
                sys.exit(1)

    try:
        from Crypto.Cipher import AES
    except ImportError:
        print()
        print("=" * 56)
        print("  未安装 pycryptodome 库，媒体解密将极慢（纯Python实现）")
        print("  建议安装以获得 1000x+ 解密速度提升，请运行：")
        print()
        print("    pip install pycryptodome -i https://pypi.tuna.tsinghua.edu.cn/simple")
        print("    (阿里云: -i https://mirrors.aliyun.com/pypi/simple)")
        print("    (腾讯云: -i https://mirrors.cloud.tencent.com/pypi/simple)")
        print()
        print("  安装后重启程序即可生效")
        print("=" * 56)
        print()

    try:
        import pilk
    except ImportError:
        print()
        print("=" * 56)
        print("  未安装 pilk 库，SILK 语音将依赖 ffmpeg 转码")
        print("  建议安装 pilk 以获得更快的语音解码速度，请运行：")
        print()
        print("    pip install pilk -i https://pypi.tuna.tsinghua.edu.cn/simple")
        print("    (阿里云: -i https://mirrors.aliyun.com/pypi/simple)")
        print("    (腾讯云: -i https://mirrors.cloud.tencent.com/pypi/simple)")
        print()
        print("  安装后重启程序即可生效")
        print("=" * 56)
        print()

check_and_install_dependencies()

import qrcode
from persona_manager import PersonaManager

CONFIG_FILE = "wechat_bot_config.json"
MESSAGES_FILE = "wechat_messages.json"
AI_CONFIG_FILE = "ai_config.json"
PERSONAS_FILE = "personas.json"
MEDIA_CACHE_DIR = "media_cache"
USER_DATA_DIR = "user_data"



class WeChatiLinkBot:
    ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
    MEDIA_TYPE_MAP = {"image": 2, "voice": 3, "file": 4, "video": 5}
    MEDIA_TYPE_NAMES = {2: "图片", 3: "语音", 4: "文件", 5: "视频"}
    MEDIA_TYPE_PREFIXES = {"image": "[图片]", "video": "[视频]", "file": "[文件]", "voice": "[语音]"}
    EXPIRED_CODES = {-14, 40014, 1002}
    SCRIPT_VERSION = "2.3"
    AUTHOR_NAME = "Sioboot"
    
    def __init__(self):
        self.token: Optional[str] = None
        self.bot_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self._cursor: str = ""
        self._context_tokens: Dict[str, str] = {}
        self._current_user: Optional[str] = None
        self._timeout = 35
        self._running = True 
        self._qrcode_matrix: Optional[List[List[str]]] = None
        self._http_server = None
        self._server_thread = None
        self._qrcode_key = None
        self._login_done = False
        self._web_port = 8888
        self._messages: List[dict] = []
        self._message_callback = None
        self._max_messages_per_user = 500
        self._total_max_messages = 2000
        self.ai_config = self._load_ai_config()
        self._active_timers: Dict[str, threading.Timer] = {}
        self._session_tokens: Dict[str, float] = {}
        self._media_cache_dir = Path(MEDIA_CACHE_DIR)
        self._media_cache_dir.mkdir(parents=True, exist_ok=True)
        self._user_data_dir = Path(USER_DATA_DIR)
        self._user_data_dir.mkdir(parents=True, exist_ok=True)
        self._media_downloading: Dict[str, threading.Event] = {}
        self._media_download_lock = threading.Lock()
        self._add_user_lock = threading.Lock()
        self._pending_qrcode: Optional[dict] = None
        self._msg_lock = threading.Lock()

        self.pm = PersonaManager()

        self._bot_accounts: Dict[str, dict] = {}
        self._user_token_map: Dict[str, str] = {}
        self._poll_threads: List[threading.Thread] = []
        
        self._load_messages()
    
    def _load_ai_config(self) -> dict:
        default_config = {
            "auto_reply": False,
            "scheduled_reply": False,
            "api_url": "",
            "api_key": "",
            "model": "deepseek-chat",
            "active_interval": 60,
            "min_words": 10,
            "max_words": 200,
            "system_prompt": "你是一个微信聊天助手，请用自然的中文回复。"
        }
        try:
            if Path(AI_CONFIG_FILE).exists():
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if "enabled" in saved and "auto_reply" not in saved:
                        saved["auto_reply"] = saved.pop("enabled")
                    default_config.update(saved)
                    print(f"[AI] 已加载 AI 配置: auto_reply={default_config.get('auto_reply')}, scheduled_reply={default_config.get('scheduled_reply')}, api_url={default_config.get('api_url', '')[:50]}, api_key={'已设置' if default_config.get('api_key') else '未设置'}")
            else:
                print("[AI] 未找到 AI 配置文件，使用默认配置")
        except Exception as e:
            print(f"[AI] 加载 AI 配置失败: {e}")
        return default_config
    
    def _save_ai_config(self):
        try:
            with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.ai_config, f, ensure_ascii=False, indent=2)
            print(f"[AI] 配置已保存: auto_reply={self.ai_config.get('auto_reply')}, scheduled_reply={self.ai_config.get('scheduled_reply')}, api_url={self.ai_config.get('api_url', '')[:50]}, api_key={'已设置' if self.ai_config.get('api_key') else '未设置'}")
        except Exception as e:
            print(f"[AI] 保存 AI 配置失败: {e}")
    
    def _generate_session_token(self) -> str:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        self._session_tokens[token] = time.time() + 3600
        if len(self._session_tokens) > 100:
            self._cleanup_expired_sessions()
        return token
    
    def _verify_session_token(self, token: str) -> bool:
        if not token:
            return False
        if token in self._session_tokens:
            if time.time() < self._session_tokens[token]:
                return True
            else:
                del self._session_tokens[token]
        return False
    
    def _cleanup_expired_sessions(self):
        now = time.time()
        expired = [t for t, exp in self._session_tokens.items() if exp <= now]
        for t in expired:
            del self._session_tokens[t]
    
    def _get_token_for_user(self, user_id: str) -> Optional[str]:
        return self._user_token_map.get(user_id) or self.token
    
    def _register_user_to_account(self, user_id: str, ctx_token: str, bot_token: str):
        self._context_tokens[user_id] = ctx_token
        self._user_token_map[user_id] = bot_token
        
        if bot_token not in self._bot_accounts:
            self._bot_accounts[bot_token] = {
                "bot_id": self.bot_id or "",
                "user_id": self.user_id or "",
                "cursor": "",
                "context_tokens": {}
            }
        self._bot_accounts[bot_token]["context_tokens"][user_id] = ctx_token
        
        self._save_user_token(user_id, ctx_token)
        if not self._current_user:
            self._current_user = user_id
    
    def _get_user_dir(self, user_id: str) -> Path:
        safe_id = hashlib.md5(user_id.encode('utf-8')).hexdigest()[:16]
        user_dir = self._user_data_dir / safe_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def _get_user_media_dir(self, user_id: str) -> Path:
        media_dir = self._get_user_dir(user_id) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        return media_dir
    
    def _get_user_token_file(self, user_id: str) -> Path:
        return self._get_user_dir(user_id) / "token.json"
    
    def _get_user_messages_file(self, user_id: str) -> Path:
        return self._get_user_dir(user_id) / "messages.json"
    
    def _save_user_token(self, user_id: str, context_token: str):
        try:
            data = {
                "user_id": user_id,
                "context_token": context_token,
                "saved_at": datetime.now().isoformat()
            }
            with open(self._get_user_token_file(user_id), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[USER] 保存用户 token 失败 ({user_id}): {e}")
    
    def _load_user_token(self, user_id: str) -> Optional[str]:
        token_file = self._get_user_token_file(user_id)
        try:
            if token_file.exists():
                with open(token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("context_token")
        except Exception as e:
            print(f"[USER] 加载用户 token 失败 ({user_id}): {e}")
        return None
    
    def _save_user_messages(self, user_id: str):
        if not user_id:
            return
        try:
            user_msgs = [m for m in self._messages 
                        if m.get('from') == user_id or m.get('to') == user_id]
            
            if len(user_msgs) > self._max_messages_per_user * 2:
                user_msgs = user_msgs[-self._max_messages_per_user:]
            
            data = {
                "user_id": user_id,
                "messages": user_msgs,
                "count": len(user_msgs),
                "saved_at": datetime.now().isoformat()
            }
            with open(self._get_user_messages_file(user_id), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[USER] 保存用户消息失败 ({user_id}): {e}")
    
    def _load_user_messages(self, user_id: str) -> List[dict]:
        msg_file = self._get_user_messages_file(user_id)
        try:
            if msg_file.exists():
                with open(msg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("messages", [])
        except Exception as e:
            print(f"[USER] 加载用户消息失败 ({user_id}): {e}")
        return []
    
    def _load_all_user_messages(self):
        all_msgs = []
        loaded_ids = set()
        
        for user_id in self._context_tokens.keys():
            user_msgs = self._load_user_messages(user_id)
            for msg in user_msgs:
                msg_id = msg.get('id')
                if msg_id and msg_id not in loaded_ids:
                    all_msgs.append(msg)
                    loaded_ids.add(msg_id)
        
        all_msgs.sort(key=lambda m: m.get('id', 0))
        self._messages = all_msgs
        
        if self._messages:
            self._last_msg_id = max(msg.get('id', 0) for msg in self._messages)
        else:
            self._last_msg_id = 0
        
        print(f"[MSG] 已从用户文件夹加载 {len(self._messages)} 条消息 ({len(self._context_tokens)} 个用户)")
    
    def _save_all_messages(self):
        for user_id in self._context_tokens.keys():
            self._save_user_messages(user_id)
    
    def _get_user_media_cache_path(self, user_id: str, cache_key: str) -> Path:
        return self._get_user_media_dir(user_id) / cache_key
    
    def _get_user_media_meta_path(self, user_id: str, cache_key: str) -> Path:
        return self._get_user_media_dir(user_id) / (cache_key + ".meta")
    
    def _save_user_media_cache(self, user_id: str, cache_key: str, media_data: bytes, mime: str, filename: str = ""):
        try:
            self._get_user_media_cache_path(user_id, cache_key).write_bytes(media_data)
            meta = {'mime': mime, 'filename': filename, 'size': len(media_data)}
            self._get_user_media_meta_path(user_id, cache_key).write_text(json.dumps(meta, ensure_ascii=False), 'utf-8')
        except Exception as e:
            print(f"[媒体缓存] 保存失败: {e}")
    
    def _get_user_cached_media(self, user_id: str, cache_key: str) -> Optional[tuple]:
        data_path = self._get_user_media_cache_path(user_id, cache_key)
        meta_path = self._get_user_media_meta_path(user_id, cache_key)
        if data_path.exists() and meta_path.exists():
            try:
                media_data = data_path.read_bytes()
                meta = json.loads(meta_path.read_text('utf-8'))
                return (media_data, meta.get('mime', 'application/octet-stream'), meta.get('filename', ''))
            except Exception:
                return None
        return None
    
    def _call_ai_api(self, user_message: str, history: List[dict], is_active: bool = False, custom_instruction: str = "", user_id: str = "") -> Optional[str]:
        if not self.ai_config.get("api_url") or not self.ai_config.get("api_key"):
            error_msg = f"[AI] API 配置不完整: url={self.ai_config.get('api_url')}, key={'已设置' if self.ai_config.get('api_key') else '未设置'}"
            print(error_msg)
            return None

        print(f"[AI] 正在调用 AI API，{'主动发送' if is_active else '回复消息'}")
        if not is_active:
            print(f"[AI] 用户消息: {user_message[:100]}...")
        print(f"[AI] 历史消息数量: {len(history)} 条")

        system_prompt = self.ai_config.get("system_prompt", "")
        if not system_prompt:
            system_prompt = "你是一个微信聊天助手，请用自然的中文回复。"

        # ── 角色卡注入 ─────────────────────────────
        persona_block = self.pm.build_persona_block(user_id) if user_id else ""
        if persona_block:
            system_prompt = persona_block + "\n\n=====\n\n额外背景：\n" + system_prompt
            print(f"[角色卡] 已注入角色设定 (user={user_id})")

        messages = []

        if is_active:
            pass
        else:
            # 去掉历史中最后一条用户消息（避免传给 AI 时当前消息重复出现两次）
            hist = history[-50:]
            if hist and hist[-1].get("type") == "in" and hist[-1].get("text") == user_message:
                hist = hist[:-1]

            for msg in hist:
                if msg.get("type") == "in":
                    messages.append({"role": "user", "content": msg.get("text", "")})
                elif msg.get("type") == "out":
                    messages.append({"role": "assistant", "content": msg.get("text", "")})

        if is_active:
            final_prompt = f"{system_prompt}\n\n现在没有用户的新消息，你需要主动发起一个话题。"
            messages.append({"role": "user", "content": final_prompt})
        else:
            if custom_instruction:
                final_prompt = f"{system_prompt}\n\n用户说：{user_message}\n\n额外要求：{custom_instruction}\n\n请严格按照你的性格要求和额外要求回复。"
            else:
                final_prompt = f"{system_prompt}\n\n用户说：{user_message}\n\n请严格按照你的性格要求回复。"
            messages.append({"role": "user", "content": final_prompt})
        
        payload = {
            "model": self.ai_config.get("model", "deepseek-chat"),
            "messages": messages,
            "temperature": 1.2,
            "max_tokens": 500,
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.ai_config.get('api_key')}"
        }
        
        # 自动补全 API URL：如果只有域名没有路径，加上 /chat/completions
        raw_url = self.ai_config.get("api_url", "").strip()
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.path in ("", "/"):
            raw_url = raw_url.rstrip("/") + "/chat/completions"
            print(f"[AI] API URL 自动补全路径: {raw_url}")
        elif not parsed.path.endswith("chat/completions"):
            raw_url = raw_url.rstrip("/") + "/chat/completions"
            print(f"[AI] API URL 自动补全路径: {raw_url}")

        # 将补全后的 URL 保存回配置，下次直接用
        if raw_url != self.ai_config.get("api_url"):
            self.ai_config["api_url"] = raw_url
            self._save_ai_config()

        req = urllib.request.Request(
            raw_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        try:
            print(f"[AI] 请求 URL: {raw_url}")
            with urllib.request.urlopen(req, timeout=60) as resp:
                status_code = resp.getcode()
                print(f"[AI] HTTP 状态码: {status_code}")
                result = json.loads(resp.read().decode("utf-8"))
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    print(f"[AI] API 返回内容: {content[:200]}...")
                else:
                    finish_reason = result.get("choices", [{}])[0].get("finish_reason", "")
                    print(f"[AI] API 返回空内容, finish_reason={finish_reason}")
                    if self._message_callback:
                        self._message_callback({"type": "ai_error", "text": f"[AI] API 返回空内容 (finish_reason={finish_reason})"})
                return content
        except urllib.error.HTTPError as e:
            status_code = e.code
            error_detail = ""
            try:
                error_body = e.read().decode('utf-8')
                error_detail = error_body[:500]
                print(f"[AI] HTTP 错误: {status_code} - {e.reason}")
                print(f"[AI] 错误详情: {error_detail}")
            except Exception:
                print(f"[AI] HTTP 错误: {status_code} - {e.reason}")
            if self._message_callback:
                self._message_callback({"type": "ai_error", "text": f"[AI] API 请求失败 (HTTP {status_code}): {error_detail[:100] if error_detail else e.reason}"})
            return None
        except urllib.error.URLError as e:
            err_msg = f"[AI] 网络错误: {e.reason}"
            print(err_msg)
            if self._message_callback:
                self._message_callback({"type": "ai_error", "text": err_msg})
            return None
        except Exception as e:
            err_msg = f"[AI] 未知错误: {e}"
            print(err_msg)
            if self._message_callback:
                self._message_callback({"type": "ai_error", "text": err_msg})
            return None
    
    def _should_segment(self, text: str) -> tuple:
        if len(text) < 30:
            return text, 1, 0
        
        sentences = text.replace('！', '。').replace('？', '。').replace('；', '。').split('。')
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) >= 3:
            mid = len(sentences) // 2
            part1 = '。'.join(sentences[:mid]) + '。'
            part2 = '。'.join(sentences[mid:]) + '。'
            return [part1, part2], 2, 2
        
        if len(text) > 100:
            half = len(text) // 2
            part1 = text[:half]
            part2 = text[half:]
            return [part1, part2], 2, 2
        
        return text, 1, 0
    
    def _send_ai_reply_in_segments(self, to_user_id: str, response_text: str):
        print(f"[AI] 准备发送: {response_text[:100]}...")
        
        segments, seg_count, delay = self._should_segment(response_text)
        
        if seg_count <= 1:
            self.send_text(to_user_id, response_text)
            return
        
        def send_segments():
            if isinstance(segments, list):
                for idx, seg_text in enumerate(segments):
                    if not self._running:
                        break
                    print(f"[AI] 发送第 {idx+1}/{seg_count} 段: {seg_text[:30]}...")
                    self.send_text(to_user_id, seg_text)
                    if idx < len(segments) - 1:
                        time.sleep(delay)
            else:
                self.send_text(to_user_id, segments)
        
        threading.Thread(target=send_segments, daemon=True).start()
    
    def _auto_ai_reply(self, from_user: str, user_message: str):
        if not self.ai_config.get("auto_reply"):
            return

        print(f"[AI] 收到来自 {from_user} 的消息，准备回复...")

        history = self.get_user_messages(from_user, 200)
        print(f"[AI] 获取到 {len(history)} 条历史消息作为上下文")

        response = self._call_ai_api(user_message, history, is_active=False, user_id=from_user)

        if response:
            self._send_ai_reply_in_segments(from_user, response)
        else:
            print(f"[AI] 未能获取有效回复")
            # 在消息历史中插入一条可见的系统通知（from/to 设为 from_user 以确保 Web UI 能显示）
            error_msg = {
                'from': from_user,
                'to': from_user,
                'text': '⚠️ AI 回复失败：API 调用未返回有效内容。请查看终端 [AI] 日志。',
                'time': datetime.now().strftime('%H:%M:%S'),
                'type': 'in'
            }
            self._add_message_to_history(error_msg)
    
    def _manual_ai_reply(self, from_user: str, user_message: str, custom_instruction: str = ""):
        if not self.ai_config.get("api_url") or not self.ai_config.get("api_key"):
            print("[AI] AI 功能未配置，请先在设置中配置 API")
            return False
        
        print(f"[AI] 手动触发 AI 回复，用户: {from_user}")
        if custom_instruction:
            print(f"[AI] 额外指令: {custom_instruction}")
        
        history = self.get_user_messages(from_user, 200)
        
        response = self._call_ai_api(user_message, history, is_active=False, custom_instruction=custom_instruction, user_id=from_user)
        
        if response:
            self._send_ai_reply_in_segments(from_user, response)
            return True
        else:
            print(f"[AI] 未能获取有效回复")
            return False
    
    def _schedule_active_message(self, user_id: str):
        if not self.ai_config.get("scheduled_reply"):
            return
        
        interval = self.ai_config.get("active_interval", 60)
        if interval <= 0:
            return
        
        if user_id in self._active_timers:
            old_timer = self._active_timers[user_id]
            if old_timer:
                old_timer.cancel()
        
        print(f"[AI] 为 {user_id} 安排主动发送，间隔 {interval} 秒")
        
        timer = threading.Timer(interval, self._send_active_message, args=[user_id])
        timer.daemon = True
        timer.start()
        self._active_timers[user_id] = timer
    
    def _send_active_message(self, user_id: str):
        if not self.ai_config.get("scheduled_reply"):
            return
        
        if not self._running:
            return
        
        if user_id not in self._context_tokens:
            print(f"[AI] 用户 {user_id} 已不存在，取消主动发送")
            if user_id in self._active_timers:
                del self._active_timers[user_id]
            return
        
        print(f"[AI] 主动发送定时器触发，准备向 {user_id} 发送消息...")
        
        history = self.get_user_messages(user_id, 200)
        print(f"[AI] 获取到 {len(history)} 条历史消息作为上下文")
        
        response = self._call_ai_api("", history, is_active=True, user_id=user_id)
        
        if response:
            self._send_ai_reply_in_segments(user_id, response)
        else:
            print(f"[AI] 主动发送未能获取有效回复")
        
        if self.ai_config.get("scheduled_reply") and self._running and user_id in self._context_tokens:
            self._schedule_active_message(user_id)
    
    def _on_new_user(self, user_id: str):
        if self.ai_config.get("scheduled_reply"):
            print(f"[AI] 检测到新用户 {user_id}，启动主动发送定时器")
            self._schedule_active_message(user_id)
    
    def _load_messages(self):
        try:
            if Path(MESSAGES_FILE).exists():
                with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    old_messages = data.get("messages", [])
                    print(f"[MSG] 检测到旧格式消息文件，共 {len(old_messages)} 条，正在迁移...")
                    
                    user_msg_map: Dict[str, list] = {}
                    for msg in old_messages:
                        uid = msg.get('from') if msg.get('type') == 'in' else msg.get('to')
                        if uid and uid != 'me':
                            if uid not in user_msg_map:
                                user_msg_map[uid] = []
                            user_msg_map[uid].append(msg)
                    
                    for uid, msgs in user_msg_map.items():
                        existing = self._load_user_messages(uid)
                        existing_ids = {m.get('id') for m in existing}
                        new_msgs = [m for m in msgs if m.get('id') not in existing_ids]
                        if new_msgs:
                            all_msgs = existing + new_msgs
                            all_msgs.sort(key=lambda m: m.get('id', 0))
                            save_data = {
                                "user_id": uid,
                                "messages": all_msgs,
                                "count": len(all_msgs),
                                "saved_at": datetime.now().isoformat()
                            }
                            with open(self._get_user_messages_file(uid), "w", encoding="utf-8") as f:
                                json.dump(save_data, f, ensure_ascii=False, indent=2)
                    
                    bak_file = MESSAGES_FILE + ".bak"
                    shutil.move(MESSAGES_FILE, bak_file)
                    print(f"[MSG] 迁移完成，旧文件已备份为 {bak_file}")
        except Exception as e:
            print(f"[MSG] 消息迁移失败: {e}")
        
        self._messages = []
        self._last_msg_id = 0
    
    def _save_messages(self):
        try:
            if len(self._messages) > self._total_max_messages:
                print(f"[MSG] 消息数量超过限制，保留最近 {self._total_max_messages} 条")
                self._messages = self._messages[-self._total_max_messages:]
            
            self._save_all_messages()
        except Exception as e:
            print(f"[MSG] 保存消息失败: {e}")
    
    def _add_message_to_history(self, msg: dict):
        with self._msg_lock:
            if not hasattr(self, '_last_msg_id'):
                self._last_msg_id = 0
            self._last_msg_id += 1
            msg['id'] = self._last_msg_id
            
            if 'time' not in msg:
                msg['time'] = datetime.now().strftime('%H:%M:%S')
            
            self._messages.append(msg)
            print(f"[MSG] 添加消息: id={msg['id']}, type={msg.get('type')}, text={msg.get('text', '')[:50]}...")
            
            target_id = msg.get('to') or msg.get('from')
            if target_id:
                user_msgs = [m for m in self._messages if m.get('to') == target_id or m.get('from') == target_id]
                if len(user_msgs) > self._max_messages_per_user:
                    remove_ids = {m.get('id') for m in user_msgs[:len(user_msgs) - self._max_messages_per_user]}
                    self._messages = [m for m in self._messages if m.get('id') not in remove_ids]
        
        threading.Thread(target=self._save_messages, daemon=True).start()
    
    def get_user_messages(self, user_id: str, limit: int = 50) -> List[dict]:
        if not user_id:
            return self._messages[-limit:] if self._messages else []
        
        user_msgs = [m for m in self._messages
                     if m.get('from') == user_id or m.get('to') == user_id]
        
        return user_msgs[-limit:] if limit > 0 else user_msgs
    
    def _open_browser(self):
        url = f'http://localhost:{self._web_port}'
        
        if is_termux():
            print(f"\n[TERMUX] 网页地址: {url}")
            print("[TERMUX] 提示:")
            print("  1. 在同一设备上打开浏览器访问上述地址")
            print("  2. 或使用其他设备访问（需确保网络可达）")
            print("  3. 或使用 termux-open-url 工具")
            
            try:
                subprocess.run(["termux-open-url", url], check=False, 
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[TERMUX] 已尝试用 termux-open-url 打开浏览器")
                return
            except FileNotFoundError:
                pass
            
            try:
                intent_url = f'intent://action=android.intent.action.VIEW#Intent;scheme=http;package=com.android.chrome;end'
                subprocess.run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url],
                             check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[TERMUX] 已尝试用系统默认应用打开")
                return
            except FileNotFoundError:
                pass
            
            print("[TERMUX] ⚠ 无法自动打开浏览器，请手动访问上述地址")
            return
        
        try:
            import webbrowser
            webbrowser.open(url)
            print(f"\n[WEB] 已在浏览器中打开: {url}")
        except ImportError:
            print(f"\n[WEB] 请手动在浏览器中打开: {url}")
        except Exception as e:
            print(f"\n[WEB] 打开浏览器失败: {e}")
            print(f"[WEB] 请手动访问: {url}")
    
    def _save_config(self):
        config = {
            "token": self.token,
            "bot_id": self.bot_id,
            "user_id": self.user_id,
            "cursor": self._cursor,
            "context_tokens": self._context_tokens,
            "current_user": self._current_user,
            "bot_accounts": {k: v for k, v in self._bot_accounts.items()},
            "user_token_map": dict(self._user_token_map),
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        try:
            Path(CONFIG_FILE).chmod(0o600)
        except (OSError, AttributeError, NotImplementedError):
            pass
        
        for user_id, ctx_token in self._context_tokens.items():
            self._save_user_token(user_id, ctx_token)
    
    def load_config(self) -> bool:
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            self.token = config.get("token")
            self.bot_id = config.get("bot_id")
            self.user_id = config.get("user_id")
            self._cursor = config.get("cursor", "")
            self._context_tokens = config.get("context_tokens", {})
            self._current_user = config.get("current_user")
            self._bot_accounts = config.get("bot_accounts", {})
            self._user_token_map = config.get("user_token_map", {})
            
            if self.token and self.token not in self._bot_accounts:
                self._bot_accounts[self.token] = {
                    "bot_id": self.bot_id or "",
                    "user_id": self.user_id or "",
                    "cursor": self._cursor,
                    "context_tokens": dict(self._context_tokens)
                }
            
            for user_id in list(self._context_tokens.keys()):
                if user_id not in self._user_token_map:
                    self._user_token_map[user_id] = self.token
            
            self._load_all_user_messages()
            
            if self.token:
                print(f"加载配置成功，{len(self._context_tokens)} 个会话，{len(self._bot_accounts)} 个 bot 账号，{len(self._messages)} 条消息")
                if self._current_user:
                    print(f"当前会话用户: {self._current_user}")
                for user_id in self._context_tokens.keys():
                    self._on_new_user(user_id)
                return True
            return False
        except FileNotFoundError:
            return False
    
    def _get_qrcode_matrix(self, qrcode_url: str) -> List[List[str]]:
        qr = qrcode.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        result = []
        for row in matrix:
            line = []
            for cell in row:
                line.append('█' if cell else ' ')
            result.append(line)
        return result
    
    def _generate_wasm_wrapper(self, session_token: str) -> str:
        return '''window.__ZN''' + session_token[:16] + ''' = (function() {
    let _state = {
        token: "''' + session_token + '''",
        apiBase: "",
        currentUser: null,
        lastMsgId: 0,
        pollInterval: null,
        displayedIds: new Set(),
        users: [],
        selectedMessage: null,
        selectedUserId: null,
        aiModalVisible: false,
        view: "list",
        nicknames: JSON.parse(localStorage.getItem("zyn_nicknames") || "{}"),
        lastMessages: {},
        personas: [],
        personaMode: 'none',
        globalPersonaId: null,
        userPersonaMap: {},
        editingPersonaId: null
    };

    function antiDebug() {
        document.addEventListener("contextmenu", function(e) { e.preventDefault(); return false; });
        document.addEventListener("keydown", function(e) {
            if (e.key === "F12" || e.keyCode === 123 ||
                (e.ctrlKey && e.shiftKey && (e.key === "I" || e.keyCode === 73)) ||
                (e.ctrlKey && e.shiftKey && (e.key === "J" || e.keyCode === 74)) ||
                (e.ctrlKey && (e.key === "U" || e.keyCode === 85)) ||
                (e.ctrlKey && (e.key === "s" || e.keyCode === 83))) {
                e.preventDefault();
                return false;
            }
        });
    }
    
    const _api = function(e, t) {
        return new Promise((function(r, n) {
            const o = new XMLHttpRequest();
            o.open("POST", "/api/wasm/" + e, true);
            o.setRequestHeader("Content-Type", "application/json");
            o.setRequestHeader("X-Session-Token", _state.token);
            o.timeout = 120000;
            o.onload = function() {
                if (o.status >= 200 && o.status < 300) {
                    try {
                        r(JSON.parse(o.responseText));
                    } catch(e) {
                        r({});
                    }
                } else {
                    n(new Error(o.statusText || "HTTP " + o.status));
                }
            };
            o.onerror = function() { return n(new Error("Network Error")); };
            o.ontimeout = function() { return n(new Error("请求超时")); };
            o.send(JSON.stringify(t || {}));
        }));
    };
    
    const _get = function(e) {
        return new Promise((function(r, n) {
            const o = new XMLHttpRequest();
            o.open("GET", "/api/wasm/" + e, true);
            o.setRequestHeader("X-Session-Token", _state.token);
            o.onload = function() {
                if (o.status >= 200 && o.status < 300) {
                    try {
                        r(JSON.parse(o.responseText));
                    } catch(e) {
                        r({});
                    }
                } else {
                    n(new Error(o.statusText));
                }
            };
            o.onerror = function() { return n(new Error("Network Error")); };
            o.send();
        }));
    };
    
    const _escape = function(e) {
        const t = document.createElement("div");
        t.textContent = e;
        return t.innerHTML;
    };
    
    const _toast = function(e, t) {
        const n = document.getElementById("toast");
        if (!n) return;
        n.textContent = e;
        n.classList.add("show");
        setTimeout((function() { return n.classList.remove("show"); }), t || 3000);
    };
    
    const _svgImage = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
    const _svgVideo = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>';
    const _svgFile = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    const _svgVoice = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/><path d="M19 10v2a7 7 0 01-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>';
    const _svgPlay = '<svg viewBox="0 0 24 24" width="36" height="36" fill="rgba(0,0,0,0.5)"><path d="M8 5v14l11-7z"/></svg>';

    const _renderMsg = function(e) {
        const t = document.getElementById("messages-area");
        if (!t) return;
        const n = t.querySelector(".empty-state");
        if (n) n.remove();
        const o = document.createElement("div");
        o.className = "msg-row " + (e.type === "out" ? "out" : "in");
        if (e.id) o.dataset.msgId = e.id;
        var bubbleContent = "";
        var mt = e.media_type;
        if (mt === "image" || mt === 2) {
            var imgSrc = e.media_data || "";
            var cacheSrc = e.media_cache_id ? '/api/wasm/media/' + e.media_cache_id : '';
            if (cacheSrc || imgSrc) {
                var cdnAttr = (e.media_cdn && !e.media_cache_id) ? ' data-cdn="' + encodeURIComponent(e.media_cdn) + '"' : '';
                var displaySrc = imgSrc || cacheSrc;
                var loadAttr = cacheSrc && imgSrc ? ' data-hq-src="' + cacheSrc + '"' : '';
                bubbleContent = '<div class="bubble-media-img-wrap"' + cdnAttr + loadAttr + '><img class="bubble-media-img" src="' + displaySrc + '" alt="图片" /></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-img-wrap bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '"><div class="bubble-media-placeholder">' + _svgImage + '<span>图片</span></div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-placeholder">' + _svgImage + '<span>图片</span></div>';
            }
        } else if (mt === "video" || mt === 5) {
            if (e.media_cache_id) {
                var videoSrc = '/api/wasm/media/' + e.media_cache_id;
                bubbleContent = '<div class="bubble-media-img-wrap"><div class="bubble-media-video-thumb" data-action="play-video" data-video-src="' + videoSrc + '"><video class="bubble-media-video-thumb-vid" src="' + videoSrc + '" preload="metadata" muted playsinline></video><div class="bubble-media-play-btn">' + _svgPlay + '</div></div></div>';
            } else if (e.media_data) {
                bubbleContent = '<div class="bubble-media-img-wrap"><div class="bubble-media-video-thumb" data-action="play-video"><img class="bubble-media-img" src="' + e.media_data + '" alt="视频" /><div class="bubble-media-play-btn">' + _svgPlay + '</div></div></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-img-wrap bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '" data-media-type="video"><div class="bubble-media-placeholder">' + _svgVideo + '<span>视频</span></div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgVideo + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "视频") + '</div><div class="bubble-media-file-size">' + (e.media_duration ? (e.media_duration / 1000).toFixed(1) + "s" : "") + '</div></div></div>';
            }
        } else if (mt === "file" || mt === 4) {
            if (e.media_cache_id) {
                bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-file bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '" data-media-type="file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
            }
        } else if (mt === "voice" || mt === 3) {
            var dur = e.media_duration ? Math.ceil(e.media_duration / 1000) : 1;
            var bars = "";
            for (var i = 0; i < Math.min(dur, 12); i++) {
                var h = 6 + Math.floor(Math.random() * 14);
                bars += '<div class="bubble-media-voice-bar" style="height:' + h + 'px"></div>';
            }
            if (e.media_cache_id) {
                bubbleContent = '<div class="bubble-media-voice" data-action="play-voice" data-cache-id="' + e.media_cache_id + '">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div><div class="bubble-media-voice-progress"><div class="bubble-media-voice-progress-fill"></div></div></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-voice bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '" data-media-type="voice">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div><div class="bubble-media-voice-progress"><div class="bubble-media-voice-progress-fill"></div></div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-voice">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div><div class="bubble-media-voice-progress"><div class="bubble-media-voice-progress-fill"></div></div></div>';
            }
        } else {
            bubbleContent = '<div class="bubble-text">' + _escape(e.text || "") + '</div>';
        }
        o.innerHTML = '<div class="bubble ' + (e.type === "out" ? "out" : "in") + '">' + bubbleContent + '<div class="msg-time-row">' + (e.media_cdn && !e.media_cache_id ? '<span class="msg-send-status msg-send-loading"></span>' : '') + '<span class="msg-time">' + (e.time || "") + '</span></div></div>';
        o._msgData = e;
        t.appendChild(o);
        t.scrollTop = t.scrollHeight;
        
        var loadingEl = o.querySelector('.bubble-media-loading');
        if (loadingEl) {
            window._loadCdnMedia(loadingEl);
        }

        var hqWrap = o.querySelector('.bubble-media-img-wrap[data-hq-src]');
        if (hqWrap) {
            var hqImg = new Image();
            hqImg.onload = (function(wrap, src) {
                return function() {
                    var img = wrap.querySelector('.bubble-media-img');
                    if (img) img.src = src;
                };
            })(hqWrap, hqWrap.dataset.hqSrc);
            hqImg.src = hqWrap.dataset.hqSrc;
        }

        const bubbleDiv = o.querySelector('.bubble');
        if (bubbleDiv) {
            var isMediaMsg = (mt === "image" || mt === 2 || mt === "video" || mt === 5 || mt === "voice" || mt === 3 || mt === "file" || mt === 4);
            if (isMediaMsg) {
                bubbleDiv.style.cursor = 'pointer';
                bubbleDiv.addEventListener('click', (function(ev) {
                    ev.stopPropagation();
                    _handleMediaClick(e);
                }));
            } else if (e.type === 'in') {
                bubbleDiv.style.cursor = 'pointer';
                bubbleDiv.addEventListener('click', (function(ev) {
                    ev.stopPropagation();
                    _showAiModal(e.id, e.text, e.from || _state.currentUser);
                }));
            }
        }
    };

    const _renderSendingMsg = function(e) {
        const t = document.getElementById("messages-area");
        if (!t) return;
        const n = t.querySelector(".empty-state");
        if (n) n.remove();
        const o = document.createElement("div");
        o.className = "msg-row out";
        o.dataset.sendingId = e.id;
        if (e.id) o.dataset.msgId = e.id;
        var bubbleContent = "";
        var mt = e.media_type;
        if (mt === 2 && e.media_data) {
            bubbleContent = '<div class="bubble-media-img-wrap"><img class="bubble-media-img" src="' + e.media_data + '" alt="图片" /></div>';
        } else if (mt === 5 && e.media_data) {
            bubbleContent = '<div class="bubble-media-img-wrap"><div class="bubble-media-video-thumb"><img class="bubble-media-img" src="' + e.media_data + '" alt="视频" /><div class="bubble-media-play-btn">' + _svgPlay + '</div></div></div>';
        } else if (mt === 3) {
            var dur = e.media_duration ? Math.ceil(e.media_duration / 1000) : 1;
            var bars = "";
            for (var i = 0; i < Math.min(dur, 12); i++) {
                var h = 6 + Math.floor(Math.random() * 14);
                bars += '<div class="bubble-media-voice-bar" style="height:' + h + 'px"></div>';
            }
            bubbleContent = '<div class="bubble-media-voice">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div><div class="bubble-media-voice-progress"><div class="bubble-media-voice-progress-fill"></div></div></div>';
        } else if (mt === 4) {
            bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
        } else {
            bubbleContent = '<div class="bubble-text">' + _escape(e.text || "") + '</div>';
        }
        o.innerHTML = '<div class="bubble out">' + bubbleContent + '<div class="msg-time-row"><span class="msg-send-status msg-send-loading"></span><span class="msg-time">' + (e.time || "") + '</span></div></div>';
        t.appendChild(o);
        t.scrollTop = t.scrollHeight;
    };

    var _currentAudio = null;
    var _currentVoiceEl = null;

    const _cdnInfoStr = function(cdn) {
        if (typeof cdn === 'string') return cdn;
        return JSON.stringify(cdn);
    };

    const _handleMediaClick = function(msg) {
        var mt = msg.media_type;
        if (mt === "image" || mt === 2) {
            if (msg.media_cache_id) {
                window._previewImage('/api/wasm/media/' + msg.media_cache_id);
            } else if (msg.media_data) {
                window._previewImage(msg.media_data);
            } else if (msg.media_cdn) {
                _toast("正在加载图片...");
                fetch('/api/wasm/download-media', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
                    body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
                }).then(function(r) {
                    if (!r.ok) {
                        return r.text().then(function(t) { throw new Error('HTTP ' + r.status); });
                    }
                    return r.json();
                }).then(function(result) {
                    if (result.success && result.cache_key) {
                        window._previewImage('/api/wasm/media/' + result.cache_key);
                    } else {
                        _toast("图片加载失败: " + (result.error || ""));
                    }
                }).catch(function(err) {
                    console.log('图片加载异常:', err);
                    _toast("图片加载失败");
                });
            }
        } else if (mt === "video" || mt === 5) {
            _playVideo(msg);
        } else if (mt === "voice" || mt === 3) {
            _playVoice(msg);
        } else if (mt === "file" || mt === 4) {
            _downloadMedia(msg, "file");
        }
    };

    var _voicePlayFailed = {};
    var _voiceProgressRaf = null;

    const _playVoice = function(msg) {
        if (!msg.media_cdn && !msg.media_cache_id) {
            _toast("语音数据不可用");
            return;
        }
        var msgId = msg.id;
        if (_voicePlayFailed[msgId]) {
            delete _voicePlayFailed[msgId];
            _downloadMedia(msg, "voice");
            return;
        }
        if (_currentAudio) {
            _currentAudio.pause();
            _currentAudio = null;
            if (_currentVoiceEl) {
                _currentVoiceEl.classList.remove('voice-playing');
                var pf = _currentVoiceEl.querySelector('.bubble-media-voice-progress-fill');
                if (pf) pf.style.width = '0%';
                _currentVoiceEl = null;
            }
        }
        if (_voiceProgressRaf) {
            cancelAnimationFrame(_voiceProgressRaf);
            _voiceProgressRaf = null;
        }
        var voiceEl = null;
        if (msgId) {
            var msgRow = document.querySelector('[data-msg-id="' + msgId + '"]');
            if (msgRow) voiceEl = msgRow.querySelector('.bubble-media-voice');
        }
        var tryPlayAudio = function(cacheId) {
            var cacheUrl = '/api/wasm/media/' + cacheId;
            var audio = new Audio();
            var hasPlayed = false;
            var updateProgress = function() {
                if (!audio.duration || !voiceEl) return;
                var pct = (audio.currentTime / audio.duration) * 100;
                var fill = voiceEl.querySelector('.bubble-media-voice-progress-fill');
                if (fill) fill.style.width = pct + '%';
                var durEl = voiceEl.querySelector('.bubble-media-voice-dur');
                if (durEl && audio.duration) {
                    var remain = Math.ceil(audio.duration - audio.currentTime);
                    durEl.textContent = remain + '"';
                }
                if (!audio.paused && !audio.ended) {
                    _voiceProgressRaf = requestAnimationFrame(updateProgress);
                }
            };
            audio.addEventListener('canplaythrough', function() {
                hasPlayed = true;
                if (voiceEl) {
                    _currentVoiceEl = voiceEl;
                    voiceEl.classList.add('voice-playing');
                }
                audio.play().catch(function() {
                    _voicePlayFailed[msgId] = true;
                    if (voiceEl) voiceEl.classList.remove('voice-playing');
                    var pf = voiceEl ? voiceEl.querySelector('.bubble-media-voice-progress-fill') : null;
                    if (pf) pf.style.width = '0%';
                    _toast("语音播放失败，再次点击可下载");
                });
            });
            audio.addEventListener('error', function() {
                if (!hasPlayed) {
                    _voicePlayFailed[msgId] = true;
                    _toast("浏览器不支持此语音格式，再次点击可下载");
                }
            });
            audio.addEventListener('ended', function() {
                _currentAudio = null;
                if (_voiceProgressRaf) {
                    cancelAnimationFrame(_voiceProgressRaf);
                    _voiceProgressRaf = null;
                }
                if (_currentVoiceEl) {
                    _currentVoiceEl.classList.remove('voice-playing');
                    var pf = _currentVoiceEl.querySelector('.bubble-media-voice-progress-fill');
                    if (pf) pf.style.width = '0%';
                    var durEl = _currentVoiceEl.querySelector('.bubble-media-voice-dur');
                    if (durEl && msg.media_duration) durEl.textContent = Math.ceil(msg.media_duration / 1000) + '"';
                    _currentVoiceEl = null;
                }
            });
            audio.addEventListener('playing', function() {
                if (_voiceProgressRaf) cancelAnimationFrame(_voiceProgressRaf);
                _voiceProgressRaf = requestAnimationFrame(updateProgress);
            });
            audio.addEventListener('pause', function() {
                if (_voiceProgressRaf) {
                    cancelAnimationFrame(_voiceProgressRaf);
                    _voiceProgressRaf = null;
                }
            });
            _currentAudio = audio;
            audio.src = cacheUrl;
            audio.load();
        };
        if (msg.media_cache_id) {
            tryPlayAudio(msg.media_cache_id);
            return;
        }
        _toast("正在加载语音...");
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
        }).then(function(r) {
            if (!r.ok) {
                return r.text().then(function(t) { throw new Error('HTTP ' + r.status + ': ' + t); });
            }
            return r.json();
        }).then(function(result) {
            if (result.success && result.cache_key) {
                tryPlayAudio(result.cache_key);
            } else {
                _toast("语音加载失败: " + (result.error || "未知错误"));
            }
        }).catch(function(err) {
            console.log('语音加载异常:', err);
            _toast("语音加载失败");
        });
    };

    const _playVideo = function(msg) {
        if (!msg.media_cdn && !msg.media_cache_id) {
            _toast("视频数据不可用");
            return;
        }
        var tryPlayVideo = function(cacheId) {
            var videoUrl = '/api/wasm/media/' + cacheId;
            window._previewVideo(videoUrl);
        };
        if (msg.media_cache_id) {
            tryPlayVideo(msg.media_cache_id);
            return;
        }
        _toast("正在加载视频...");
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
        }).then(function(r) {
            if (!r.ok) {
                return r.text().then(function(t) { throw new Error('HTTP ' + r.status + ': ' + t); });
            }
            return r.json();
        }).then(function(result) {
            if (result.success && result.cache_key) {
                tryPlayVideo(result.cache_key);
            } else {
                _toast("视频加载失败: " + (result.error || "未知错误"));
            }
        }).catch(function(err) {
            console.log('视频加载异常:', err);
            _toast("视频加载失败");
        });
    };

    window._previewVideo = function(src) {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.92);z-index:10002;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:default';
        var video = document.createElement('video');
        video.src = src;
        video.controls = true;
        video.autoplay = true;
        video.playsInline = true;
        video.style.cssText = 'max-width:95%;max-height:85%;border-radius:8px;background:#000;outline:none';
        var closeBtn = document.createElement('div');
        closeBtn.style.cssText = 'position:absolute;top:16px;right:16px;width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:20px;color:#fff;z-index:10003';
        closeBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        var downloadBtn = document.createElement('div');
        downloadBtn.style.cssText = 'position:absolute;top:16px;right:60px;width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:10003';
        downloadBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
        downloadBtn.addEventListener('click', function(ev) {
            ev.stopPropagation();
            var a = document.createElement('a');
            a.href = src + '?download=1';
            a.download = 'video.mp4';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        });
        var closeOverlay = function() {
            video.pause();
            video.src = '';
            if (overlay.parentNode) document.body.removeChild(overlay);
        };
        closeBtn.addEventListener('click', function(ev) { ev.stopPropagation(); closeOverlay(); });
        overlay.addEventListener('click', function(ev) { if (ev.target === overlay) closeOverlay(); });
        overlay.appendChild(video);
        overlay.appendChild(closeBtn);
        overlay.appendChild(downloadBtn);
        document.body.appendChild(overlay);
    };

    const _downloadDirectUrl = function(cacheId, filename) {
        try {
            var downloadUrl = '/api/wasm/media/' + cacheId + '?download=1';
            var a = document.createElement('a');
            a.href = downloadUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            _toast("正在接收: " + filename);
        } catch (err) {
            _toast("下载失败");
        }
    };

    const _downloadMedia = function(msg, mediaType) {
        if (!msg.media_cdn && !msg.media_cache_id) {
            _toast("媒体数据不可用");
            return;
        }
        var filename = msg.media_filename || (mediaType === "video" ? "video.mp4" : mediaType === "voice" ? "voice.silk" : "file.bin");
        if (msg.media_cache_id) {
            _downloadDirectUrl(msg.media_cache_id, filename);
            return;
        }
        _toast("正在接收 " + filename + "...");
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
        }).then(function(r) {
            if (!r.ok) {
                return r.text().then(function(t) { throw new Error('HTTP ' + r.status); });
            }
            return r.json();
        }).then(function(result) {
            if (result.success && result.cache_key) {
                _downloadDirectUrl(result.cache_key, filename);
            } else {
                _toast("下载失败: " + (result.error || "未知错误"));
            }
        }).catch(function(err) {
            console.log('下载异常:', err);
            _toast("下载失败");
        });
    };

    window._previewImage = function(src) {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.9);z-index:10002;display:flex;align-items:center;justify-content:center;cursor:zoom-out';
        var img = document.createElement('img');
        img.src = src;
        img.style.cssText = 'max-width:95%;max-height:95%;object-fit:contain;border-radius:4px';
        overlay.appendChild(img);
        overlay.addEventListener('click', function() { document.body.removeChild(overlay); });
        document.body.appendChild(overlay);
    };

    const _removeLoadingSpinner = function(el, cacheKey) {
        var row = el.closest('.msg-row');
        if (row) {
            var spinner = row.querySelector('.msg-send-loading');
            if (spinner) spinner.remove();
            if (cacheKey && row._msgData) {
                row._msgData.media_cache_id = cacheKey;
            }
        }
    };

    window._loadCdnMedia = function(el) {
        var cdn = decodeURIComponent(el.dataset.cdn || "");
        var mediaType = el.dataset.mediaType || "image";
        if (!cdn) return;
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(cdn)})
        }).then(function(r) { return r.json(); }).then(function(result) {
            if (result.success && result.cache_key) {
                var cacheUrl = '/api/wasm/media/' + result.cache_key;
                if (mediaType === "video") {
                    el.innerHTML = '<div class="bubble-media-video-thumb" data-action="play-video" data-video-src="' + cacheUrl + '"><video class="bubble-media-video-thumb-vid" src="' + cacheUrl + '" preload="metadata" muted playsinline></video><div class="bubble-media-play-btn">' + _svgPlay + '</div></div>';
                } else if (mediaType === "file") {
                    el.classList.remove('bubble-media-loading');
                    el.removeAttribute('data-cdn');
                    el.removeAttribute('data-media-type');
                    el.dataset.cacheId = result.cache_key;
                    return _removeLoadingSpinner(el, result.cache_key);
                } else if (mediaType === "voice") {
                    el.classList.remove('bubble-media-loading');
                    el.removeAttribute('data-cdn');
                    el.removeAttribute('data-media-type');
                    el.dataset.action = 'play-voice';
                    el.dataset.cacheId = result.cache_key;
                    return _removeLoadingSpinner(el, result.cache_key);
                } else {
                    el.innerHTML = '<img class="bubble-media-img" src="' + cacheUrl + '" alt="图片" />';
                }
                el.classList.remove('bubble-media-loading');
                _removeLoadingSpinner(el, result.cache_key);
            } else {
                var svgIcon = _svgImage;
                var label = "加载失败";
                if (mediaType === "video") { svgIcon = _svgVideo; label = "视频加载失败"; }
                else if (mediaType === "file") { svgIcon = _svgFile; label = "文件加载失败"; }
                else if (mediaType === "voice") { svgIcon = _svgVoice; label = "语音加载失败"; }
                else { label = "图片加载失败"; }
                el.innerHTML = '<div class="bubble-media-placeholder">' + svgIcon + '<span>' + label + '</span></div>';
                el.classList.remove('bubble-media-loading');
                _removeLoadingSpinner(el);
            }
        }).catch(function() {
            var svgIcon = _svgImage;
            var label = "加载失败";
            if (mediaType === "video") { svgIcon = _svgVideo; label = "视频加载失败"; }
            else if (mediaType === "file") { svgIcon = _svgFile; label = "文件加载失败"; }
            else if (mediaType === "voice") { svgIcon = _svgVoice; label = "语音加载失败"; }
            else { label = "图片加载失败"; }
            el.innerHTML = '<div class="bubble-media-placeholder">' + svgIcon + '<span>' + label + '</span></div>';
            el.classList.remove('bubble-media-loading');
            _removeLoadingSpinner(el);
        });
    };
    
    const _showAiModal = function(msgId, msgText, userId) {
        _state.selectedMessage = { id: msgId, text: msgText };
        _state.selectedUserId = userId;
        const modal = document.getElementById("ai-modal");
        const msgPreview = document.getElementById("ai-modal-msg-preview");
        const instructionInput = document.getElementById("ai-instruction");
        if (modal) {
            if (msgPreview) msgPreview.innerText = msgText;
            if (instructionInput) instructionInput.value = "";
            modal.classList.add("show");
        }
    };
    
    const _closeAiModal = function() {
        const modal = document.getElementById("ai-modal");
        if (modal) modal.classList.remove("show");
        _state.selectedMessage = null;
        _state.selectedUserId = null;
    };
    
    const _sendAiReply = async function() {
        if (!_state.selectedMessage) {
            _toast("请选择要回复的消息");
            _closeAiModal();
            return;
        }
        let targetUser = _state.selectedUserId;
        if (!targetUser) {
            targetUser = _state.currentUser;
        }
        if (!targetUser) {
            _toast("无法确定要回复的用户");
            _closeAiModal();
            return;
        }
        const instruction = document.getElementById("ai-instruction") ? document.getElementById("ai-instruction").value : "";
        const selectedMsg = _state.selectedMessage;
        _closeAiModal();
        _toast("正在生成 AI 回复...");
        const result = await _api("ai-manual-reply", {
            user_id: targetUser,
            original_message: selectedMsg.text,
            instruction: instruction
        });
        if (result && result.success) {
            _toast("AI 回复已发送");
            setTimeout(_fetchMessages, 500);
        } else {
            _toast((result && result.error) || "AI 回复失败，请检查 API 配置");
        }
    };
    
    const _loadUsers = async function() {
        const e = await _get("users");
        if (e && e.users) {
            _state.users = e.users;
            if (_state.view === 'list') {
                _renderChatList();
                _loadChatListPreviews();
            }
        }
    };
    
    const _updateSelector = function() {
        const e = document.getElementById("user-select-btn");
        const t = document.getElementById("user-dropdown");
        if (e && _state.currentUser) {
            var nick = _state.nicknames[_state.currentUser] || '';
            e.textContent = nick || (_state.currentUser ? _state.currentUser.substring(0, 15) + (_state.currentUser.length > 15 ? "..." : "") : "选择用户");
        }
        if (t && _state.users && _state.users.length > 0) {
            t.innerHTML = _state.users.map((function(r) {
                return `<div class="user-option ${r === _state.currentUser ? "current" : ""}" data-user-id="${r}">用户 ${r}</div>`;
            })).join("");
            t.querySelectorAll(".user-option").forEach((function(e) {
                e.addEventListener("click", (function() {
                    const t = e.getAttribute("data-user-id");
                    if (t) _openChat(t);
                }));
            }));
        }
    };
    
    const _selectUser = async function(e) {
        if (!e) return;
        _openChat(e);
    };
    
    const _renderChatList = function() {
        var container = document.getElementById("chat-list-items");
        if (!container) return;
        if (!_state.users || _state.users.length === 0) {
            container.innerHTML = '<div class="chat-list-empty"><div class="chat-list-empty-icon">💬</div><div>暂无聊天</div></div>';
            return;
        }
        var html = '';
        _state.users.forEach(function(userId) {
            var nickname = _state.nicknames[userId] || '';
            var displayName = nickname || userId;
            var lastMsg = _state.lastMessages[userId];
            var preview = '';
            var time = '';
            if (lastMsg) {
                if (lastMsg.media_type) {
                    var mediaLabels = {2: '[图片]', 3: '[语音]', 4: '[文件]', 5: '[视频]', 'image': '[图片]', 'voice': '[语音]', 'file': '[文件]', 'video': '[视频]'};
                    preview = mediaLabels[lastMsg.media_type] || lastMsg.text || '';
                } else {
                    preview = lastMsg.text || '';
                }
                time = lastMsg.time || '';
            }
            html += '<div class="chat-list-item" data-user-id="' + _escape(userId) + '">' +
                '<div class="chat-list-item-avatar">用户</div>' +
                '<div class="chat-list-item-content">' +
                '<div class="chat-list-item-name">' + _escape(displayName) + '</div>' +
                '<div class="chat-list-item-msg">' + _escape(preview) + '</div>' +
                '</div>' +
                '<div class="chat-list-item-time">' + time + '</div>' +
                '</div>';
        });
        container.innerHTML = html;
        container.querySelectorAll('.chat-list-item').forEach(function(item) {
            item.addEventListener('click', function() {
                var userId = item.getAttribute('data-user-id');
                if (userId) _openChat(userId);
            });
        });
    };
    
    const _openChat = async function(userId) {
        if (!userId) return;
        _state.currentUser = userId;
        _state.view = 'chat';
        _state.displayedIds.clear();
        _state.lastMsgId = 0;
        var chatListPage = document.getElementById("chat-list-page");
        if (chatListPage) chatListPage.classList.remove("active");
        var chatPage = document.getElementById("chat-page");
        if (chatPage) chatPage.classList.add("active");
        _updateSidebarActive(null);
        var title = document.getElementById("chat-header-title");
        if (title) {
            var nickname = _state.nicknames[userId] || '';
            title.textContent = nickname || userId;
        }
        var messagesArea = document.getElementById("messages-area");
        if (messagesArea) messagesArea.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⏳</div><div>正在加载历史消息...</div></div>';
        await _api("switch-user", { user_id: userId });
        _loadHistory(userId);
    };
    
    const _backToChatList = function() {
        _state.view = 'list';
        _state.currentUser = null;
        _state.displayedIds.clear();
        var chatPage = document.getElementById("chat-page");
        if (chatPage) chatPage.classList.remove("active");
        var chatListPage = document.getElementById("chat-list-page");
        if (chatListPage) chatListPage.classList.add("active");
        _updateSidebarActive(document.getElementById('sidebar-chat-list'));
        _updateBottomNavActive(document.getElementById('bn-chats'));
        _loadUsers();
        _loadChatListPreviews();
    };

    var _addUserPollTimer = null;

    const _startAddUser = async function() {
        var modal = document.getElementById("add-user-modal");
        var statusEl = document.getElementById("add-user-status");
        var qrEl = document.getElementById("add-user-qr");
        if (modal) modal.classList.add("show");
        if (statusEl) statusEl.textContent = "正在生成二维码...";
        if (qrEl) qrEl.innerHTML = '<div class="add-user-modal-spinner"></div>';
        
        try {
            var result = await _api("add-user-start", {});
            if (result.status === "already_running") {
                if (statusEl) statusEl.textContent = "已有进行中的添加操作，请等待...";
                _startAddUserPoll();
                return;
            }
            if (result.matrix) {
                _renderAddUserQR(result.matrix);
                if (statusEl) statusEl.textContent = "请使用微信扫码添加新用户";
                _startAddUserPoll();
            } else {
                if (statusEl) statusEl.textContent = "正在生成二维码...";
                _startAddUserPoll();
            }
        } catch(e) {
            if (statusEl) statusEl.textContent = "启动失败，请重试";
        }
    };

    const _startAddUserPoll = function() {
        if (_addUserPollTimer) clearInterval(_addUserPollTimer);
        _addUserPollTimer = setInterval(async function() {
            try {
                var data = await _get("add-user-status");
                var statusEl = document.getElementById("add-user-status");
                var qrEl = document.getElementById("add-user-qr");
                
                if (data.matrix && qrEl && qrEl.querySelector(".add-user-modal-spinner")) {
                    _renderAddUserQR(data.matrix);
                }
                
                var st = data.qrcode_status;
                if (st === "scaned" && statusEl) {
                    statusEl.textContent = "已扫码，请在手机上确认...";
                } else if (st === "done") {
                    if (statusEl) statusEl.textContent = "连接成功！正在刷新用户列表...";
                    if (_addUserPollTimer) { clearInterval(_addUserPollTimer); _addUserPollTimer = null; }
                    await _loadUsers();
                    _renderChatList();
                    _loadChatListPreviews();
                    _toast("新用户已添加！");
                    setTimeout(_closeAddUserModal, 1500);
                } else if (st === "expired" || st === "timeout") {
                    if (statusEl) statusEl.textContent = "二维码已过期，请重新点击加号重试";
                    if (_addUserPollTimer) { clearInterval(_addUserPollTimer); _addUserPollTimer = null; }
                } else if (st === "error") {
                    if (statusEl) statusEl.textContent = "获取失败，请重试";
                    if (_addUserPollTimer) { clearInterval(_addUserPollTimer); _addUserPollTimer = null; }
                } else if (st === "waiting" && statusEl) {
                    statusEl.textContent = "请使用微信扫码添加新用户";
                }
            } catch(e) {}
        }, 2000);
    };

    const _renderAddUserQR = function(matrix) {
        var qrEl = document.getElementById("add-user-qr");
        if (!qrEl || !matrix) return;
        var rows = matrix.length;
        var cols = matrix[0].length;
        var cellSize = Math.max(6, Math.min(12, Math.floor(280 / cols)));
        var width = cols * cellSize + 40;
        var html = '<div class="qr-grid" style="grid-template-columns: repeat(' + cols + ', ' + cellSize + 'px); width: ' + width + 'px; max-width: 100%; overflow-x: auto; margin: 0 auto;">';
        for (var i = 0; i < rows; i++) {
            for (var j = 0; j < cols; j++) {
                html += '<div class="qr-cell ' + (matrix[i][j] === " " ? "white" : "") + '" style="width:' + cellSize + 'px;height:' + cellSize + 'px;"></div>';
            }
        }
        html += "</div>";
        qrEl.innerHTML = html;
    };

    const _closeAddUserModal = function() {
        var modal = document.getElementById("add-user-modal");
        if (modal) modal.classList.remove("show");
        if (_addUserPollTimer) { clearInterval(_addUserPollTimer); _addUserPollTimer = null; }
    };

    const _loadChatListPreviews = async function() {
        var promises = _state.users.map(async function(userId) {
            try {
                var data = await _get("history?user=" + encodeURIComponent(userId) + "&limit=1");
                if (data && data.messages && data.messages.length > 0) {
                    var lastMsg = data.messages[data.messages.length - 1];
                    _state.lastMessages[userId] = {
                        text: lastMsg.text || '',
                        time: lastMsg.time || '',
                        media_type: lastMsg.media_type
                    };
                }
            } catch(e) {}
        });
        await Promise.all(promises);
        _renderChatList();
    };
    
    const _openNicknameModal = function() {
        if (!_state.currentUser) return;
        var modal = document.getElementById("nickname-modal");
        var input = document.getElementById("nickname-input");
        var userIdDiv = document.getElementById("nickname-modal-userid");
        if (!modal || !input) return;
        if (userIdDiv) userIdDiv.textContent = '用户ID: ' + _state.currentUser;
        input.value = _state.nicknames[_state.currentUser] || '';
        modal.classList.add("show");
        setTimeout(function() { input.focus(); }, 100);
    };
    
    const _closeNicknameModal = function() {
        var modal = document.getElementById("nickname-modal");
        if (modal) modal.classList.remove("show");
    };
    
    const _saveNickname = function() {
        if (!_state.currentUser) return;
        var input = document.getElementById("nickname-input");
        var nickname = input ? input.value.trim() : '';
        if (nickname) {
            _state.nicknames[_state.currentUser] = nickname;
        } else {
            delete _state.nicknames[_state.currentUser];
        }
        localStorage.setItem("zyn_nicknames", JSON.stringify(_state.nicknames));
        var title = document.getElementById("chat-header-title");
        if (title) title.textContent = nickname || _state.currentUser;
        _closeNicknameModal();
        _toast(nickname ? "备注名已保存" : "备注名已清除");
    };
    
    const _loadHistory = async function(e) {
        const t = e ? `/history?user=${encodeURIComponent(e)}&limit=500` : "/history?limit=500";
        const n = await _get(t);
        if (!n || n.error) return;
        const o = n.messages || [];
        if (o.length === 0) return;
        const i = document.getElementById("messages-area");
        if (i) i.innerHTML = "";
        _state.displayedIds.clear();
        o.forEach((function(e) {
            _renderMsg(e);
            if (e.id) _state.displayedIds.add(e.id);
        }));
        if (o.length > 0) {
            const e = Math.max.apply(null, o.map((function(e) { return e.id || 0; })));
            _state.lastMsgId = Math.max(_state.lastMsgId, e);
        }
        const r = document.getElementById("messages-area");
        if (r) r.scrollTop = r.scrollHeight;
    };
    
    const _fetchMessages = async function() {
        const e = _state.currentUser ? "&user=" + encodeURIComponent(_state.currentUser) : "";
        const t = await _get("messages?since=" + _state.lastMsgId + e);
        if (t && t.messages) {
            t.messages.forEach((function(e) {
                if (e.id && !_state.displayedIds.has(e.id)) {
                    if (_state.view === 'chat' && _state.currentUser) {
                        _renderMsg(e);
                    }
                    _state.displayedIds.add(e.id);
                    _state.lastMsgId = Math.max(_state.lastMsgId, e.id);
                    var fromUser = e.from || _state.currentUser;
                    if (fromUser) {
                        _state.lastMessages[fromUser] = {
                            text: e.text || '',
                            time: e.time || '',
                            media_type: e.media_type
                        };
                    }
                }
            }));
            if (_state.view === 'list') {
                _renderChatList();
            }
        }
    };
    
    const _startPoll = function() {
        if (_state.pollInterval) clearInterval(_state.pollInterval);
        _state.pollInterval = setInterval(_fetchMessages, 500);
    };
    
    const _sendMsg = async function() {
        const e = document.getElementById("message-input");
        const t = e ? e.value.trim() : "";
        if (!t) {
            _toast("请输入消息内容");
            return;
        }
        if (!_state.currentUser) {
            _toast("请先选择用户");
            return;
        }
        if (e) e.value = "";
        const n = await _api("send", { text: t });
        if (n && n.success) {
            setTimeout(_fetchMessages, 200);
            _toast("发送成功");
        } else {
            _toast((n && n.error) || "发送失败");
            if (e) e.value = t;
        }
    };
    
    const _toggleMediaPanel = function() {
        const panel = document.getElementById("media-panel");
        const btn = document.getElementById("plus-btn");
        if (!panel || !btn) return;
        if (panel.classList.contains("show")) {
            panel.classList.remove("show");
            btn.classList.remove("active");
        } else {
            panel.classList.add("show");
            btn.classList.add("active");
            const input = document.getElementById("message-input");
            if (input) input.blur();
        }
    };
    
    const _closeMediaPanel = function() {
        const panel = document.getElementById("media-panel");
        const btn = document.getElementById("plus-btn");
        if (panel) panel.classList.remove("show");
        if (btn) btn.classList.remove("active");
    };
    
    const _showUploadProgress = function(text) {
        const el = document.getElementById("media-upload-progress");
        const txt = el ? el.querySelector(".media-upload-text") : null;
        if (txt) txt.textContent = text || "正在发送...";
        if (el) el.classList.add("show");
    };
    
    const _hideUploadProgress = function() {
        const el = document.getElementById("media-upload-progress");
        if (el) el.classList.remove("show");
    };
    
    const _readFileAsBase64 = function(file) {
        return new Promise(function(resolve, reject) {
            var reader = new FileReader();
            reader.onload = function() {
                var result = reader.result;
                var base64 = result.split(",")[1] || result;
                resolve(base64);
            };
            reader.onerror = function() { reject(reader.error); };
            reader.readAsDataURL(file);
        });
    };
    
    const _readFileAsArrayBuffer = function(file) {
        return new Promise(function(resolve, reject) {
            var reader = new FileReader();
            reader.onload = function() { resolve(reader.result); };
            reader.onerror = function() { reject(reader.error); };
            reader.readAsArrayBuffer(file);
        });
    };
    
    const _generateThumbnail = function(file, maxWidth, maxHeight) {
        return new Promise(function(resolve) {
            if (file.type && file.type.startsWith("image/")) {
                var img = new Image();
                var url = URL.createObjectURL(file);
                img.onload = function() {
                    var w = img.width, h = img.height;
                    var scale = Math.min(maxWidth / w, maxHeight / h, 1);
                    var cw = Math.round(w * scale), ch = Math.round(h * scale);
                    var canvas = document.createElement("canvas");
                    canvas.width = cw; canvas.height = ch;
                    var ctx = canvas.getContext("2d");
                    ctx.drawImage(img, 0, 0, cw, ch);
                    URL.revokeObjectURL(url);
                    var dataUrl = canvas.toDataURL("image/jpeg", 0.6);
                    resolve(dataUrl);
                };
                img.onerror = function() { URL.revokeObjectURL(url); resolve(""); };
                img.src = url;
            } else if (file.type && file.type.startsWith("video/")) {
                var video = document.createElement("video");
                var vurl = URL.createObjectURL(file);
                video.preload = "metadata";
                video.muted = true;
                video.onloadeddata = function() {
                    video.currentTime = Math.min(1, video.duration / 4);
                };
                video.onseeked = function() {
                    var w = video.videoWidth, h = video.videoHeight;
                    var scale = Math.min(maxWidth / w, maxHeight / h, 1);
                    var cw = Math.round(w * scale), ch = Math.round(h * scale);
                    var canvas = document.createElement("canvas");
                    canvas.width = cw; canvas.height = ch;
                    var ctx = canvas.getContext("2d");
                    ctx.drawImage(video, 0, 0, cw, ch);
                    URL.revokeObjectURL(vurl);
                    var dataUrl = canvas.toDataURL("image/jpeg", 0.6);
                    resolve(dataUrl);
                };
                video.onerror = function() { URL.revokeObjectURL(vurl); resolve(""); };
                video.src = vurl;
            } else {
                resolve("");
            }
        });
    };

    const _sendMediaFile = async function(file, mediaType) {
        if (!_state.currentUser) {
            _toast("请先选择用户");
            return;
        }
        if (!file) return;
        
        var maxSize = 25 * 1024 * 1024;
        if (file.size > maxSize) {
            _toast("文件过大，最大支持 25MB");
            return;
        }
        
        _closeMediaPanel();
        
        var mediaTypeInt = {"image": 2, "voice": 3, "file": 4, "video": 5}[mediaType] || 4;
        var mediaTypeLabel = {"image": "图片", "voice": "语音", "file": "文件", "video": "视频"}[mediaType] || "文件";
        var thumbDataUrl = "";
        
        if (mediaType === "image") {
            thumbDataUrl = await _generateThumbnail(file, 200, 200);
        } else if (mediaType === "video") {
            thumbDataUrl = await _generateThumbnail(file, 200, 200);
        }
        
        var placeholderMsg = {
            from: 'me',
            to: _state.currentUser,
            text: '[' + mediaTypeLabel + '] ' + file.name,
            time: new Date().toTimeString().slice(0, 8),
            type: 'out',
            media_type: mediaTypeInt,
            media_data: thumbDataUrl,
            media_filename: file.name,
            _sending: true
        };
        
        _state._tempMsgId = (_state._tempMsgId || 0) + 1;
        placeholderMsg.id = "sending_" + _state._tempMsgId;
        
        _renderSendingMsg(placeholderMsg);
        
        try {
            var base64Data = await _readFileAsBase64(file);
            var thumbnailData = "";
            
            if (mediaType === "image" || mediaType === "video") {
                try {
                    var fullThumb = await _generateThumbnail(file, 300, 300);
                    if (fullThumb) {
                        thumbnailData = fullThumb.split(",")[1] || "";
                    }
                } catch(e) {}
            }
            
            var payload = {
                media_type: mediaType,
                filename: file.name,
                file_data: base64Data,
                file_size: file.size,
                thumbnail: thumbnailData
            };
            
            var result = await _api("send-media", payload);
            
            var sendingEl = document.querySelector('[data-sending-id="' + placeholderMsg.id + '"]');
            
            if (result && result.success && result.message) {
                var msg = result.message;
                if (!msg.id) {
                    _state._tempMsgId = (_state._tempMsgId || 0) + 1;
                    msg.id = "temp_" + _state._tempMsgId;
                }
                if (sendingEl) sendingEl.remove();
                if (!_state.displayedIds.has(msg.id)) {
                    _renderMsg(msg);
                    _state.displayedIds.add(msg.id);
                }
            } else if (result && result.success) {
                if (sendingEl) sendingEl.remove();
                setTimeout(_fetchMessages, 300);
            } else {
                if (sendingEl) {
                    var statusEl = sendingEl.querySelector('.msg-send-status');
                    if (statusEl) {
                        statusEl.className = 'msg-send-status msg-send-fail';
                        statusEl.textContent = '!';
                    }
                }
                _toast((result && result.error) || "发送失败");
            }
        } catch(e) {
            var sendingEl2 = document.querySelector('[data-sending-id="' + placeholderMsg.id + '"]');
            if (sendingEl2) {
                var statusEl2 = sendingEl2.querySelector('.msg-send-status');
                if (statusEl2) {
                    statusEl2.className = 'msg-send-status msg-send-fail';
                    statusEl2.textContent = '!';
                }
            }
            _toast("发送失败: " + (e.message || e));
        }
    };
    
    const _handlePhotoSelect = function(e) {
        var file = e.target.files && e.target.files[0];
        if (file) _sendMediaFile(file, "image");
        e.target.value = "";
    };
    
    const _handleVideoSelect = function(e) {
        var file = e.target.files && e.target.files[0];
        if (file) _sendMediaFile(file, "video");
        e.target.value = "";
    };
    
    const _handleFileSelect = function(e) {
        var file = e.target.files && e.target.files[0];
        if (file) _sendMediaFile(file, "file");
        e.target.value = "";
    };
    
    const _loadAIConfig = async function() {
        const e = await _get("ai-config");
        if (e) {
            const ar = document.getElementById("ai-auto-reply");
            const sr = document.getElementById("ai-scheduled-reply");
            const n = document.getElementById("api-url");
            const o = document.getElementById("api-key");
            const i = document.getElementById("model-name");
            const r = document.getElementById("active-interval");
            const s = document.getElementById("min-words");
            const a = document.getElementById("max-words");
            const c = document.getElementById("system-prompt");
            if (ar) ar.checked = e.auto_reply || false;
            if (sr) sr.checked = e.scheduled_reply || false;
            if (n) n.value = e.api_url || "";
            if (o) o.value = e.api_key || "";
            if (i) i.value = e.model || "deepseek-chat";
            if (r) r.value = e.active_interval || 60;
            if (s) s.value = e.min_words || 10;
            if (a) a.value = e.max_words || 200;
            if (c) c.value = e.system_prompt || "你是一个微信聊天助手，请用自然的中文回复，回复内容要简洁自然，像真人一样。";
        }
    };
    
    const _saveAIConfig = async function() {
        const e = {
            auto_reply: document.getElementById("ai-auto-reply") ? document.getElementById("ai-auto-reply").checked : false,
            scheduled_reply: document.getElementById("ai-scheduled-reply") ? document.getElementById("ai-scheduled-reply").checked : false,
            api_url: document.getElementById("api-url") ? document.getElementById("api-url").value : "",
            api_key: document.getElementById("api-key") ? document.getElementById("api-key").value : "",
            model: document.getElementById("model-name") ? document.getElementById("model-name").value : "deepseek-chat",
            active_interval: parseInt(document.getElementById("active-interval") ? document.getElementById("active-interval").value : "60") || 60,
            min_words: parseInt(document.getElementById("min-words") ? document.getElementById("min-words").value : "10") || 10,
            max_words: parseInt(document.getElementById("max-words") ? document.getElementById("max-words").value : "200") || 200,
            system_prompt: document.getElementById("system-prompt") ? document.getElementById("system-prompt").value : ""
        };
        const t = await _api("ai-config", e);
        if (t && t.success) {
            _toast("AI 配置已保存");
            _showSettingsPage('settings-main');
        } else {
            _toast("保存失败: " + ((t && t.error) || "未知错误"));
        }
    };
    
    const _openSettings = function() {
        const e = document.getElementById("settings-panel");
        if (e) {
            e.classList.add("show");
            _showSettingsPage('settings-main');
        }
    };
    
    const _closeSettings = function() {
        const e = document.getElementById("settings-panel");
        if (e) e.classList.remove("show");
    };
    
    const _showSettingsPage = function(pageId) {
        var pages = document.querySelectorAll('.settings-page');
        pages.forEach(function(p) { p.classList.remove('active'); p.classList.remove('settings-page-slide'); });
        var target = document.getElementById(pageId);
        if (target) {
            target.classList.add('active');
            if (pageId !== 'settings-main') {
                target.classList.add('settings-page-slide');
            }
        }
        if (pageId === 'settings-api') {
            _loadAIConfig();
        } else if (pageId === 'settings-about') {
            _loadAbout();
        } else if (pageId === 'settings-persona') {
            _loadPersonas().then(function() {
                _renderPersonaList();
                _loadPersonaConfig().then(function() {
                    _renderPersonaSetup();
                });
            });
        }
    };

    const _loadAbout = async function() {
        const authorEl = document.getElementById("about-author");
        const versionEl = document.getElementById("about-version");
        if (authorEl) authorEl.textContent = "加载中...";
        if (versionEl) versionEl.textContent = "加载中...";
        const e = await _get("about");
        if (e) {
            if (authorEl) authorEl.textContent = e.author || "未知";
            if (versionEl) versionEl.textContent = e.version || "未知";
        } else {
            if (authorEl) authorEl.textContent = "获取失败";
            if (versionEl) versionEl.textContent = "获取失败";
        }
    };

    const _onAvatarClick = function() {
        const img = document.querySelector(".about-logo-img");
        if (!img) return;
        img.classList.remove("spinning");
        void img.offsetWidth;
        img.classList.add("spinning");
    };
    
    const _initTheme = function() {
        var saved = localStorage.getItem('theme');
        if (saved === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            var btn = document.getElementById('theme-toggle-btn');
            if (btn) btn.classList.add('active');
        }
    };
    
    const _toggleTheme = function() {
        var btn = document.getElementById('theme-toggle-btn');
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        if (isDark) {
            document.documentElement.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
            if (btn) btn.classList.remove('active');
        } else {
            document.documentElement.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
            if (btn) btn.classList.add('active');
        }
    };
    
    const _checkStatus = async function() {
        const e = await _get("status");
        if (e && e.logged_in && e.login_done) {
            _showChat(e);
            return true;
        }
        // 不再自动加载二维码，用户需手动点击按钮
        const statusEl = document.getElementById("status-text");
        if (statusEl) statusEl.innerHTML = '<div class="qr-tip">点击下方按钮获取二维码</div><div class="qr-subtip">或直接进入聊天界面</div>';
        const loadingEl = document.getElementById("qr-loading");
        if (loadingEl) loadingEl.style.display = "none";
        return false;
    };
    
    const _loadQR = async function() {
        const e = await _get("qrcode");
        if (e && (e.redirect_to_chat || e.login_done)) {
            _toast("检测到已连接，正在跳转...");
            const t = await _get("status");
            if (t && t.logged_in && t.login_done) {
                _showChat(t);
            }
            return;
        }
        if (!e || !e.matrix) {
            const t = await _get("status");
            if (t && t.logged_in && t.login_done) {
                _toast("检测到已连接，正在进入聊天...");
                _showChat(t);
                return;
            }
            const n = document.getElementById("status-text");
            if (n) n.textContent = (e && e.message) || "正在获取二维码...";
            setTimeout(_loadQR, 3000);
            return;
        }
        _renderQR(e.matrix);
        if (e.login_done) {
            _toast("连接成功！");
            setTimeout(_checkStatus, 1000);
        } else {
            setTimeout((async function() {
                const t = await _get("status");
                if (t && t.logged_in && t.login_done) {
                    _toast("扫码成功！正在进入聊天...");
                    _showChat(t);
                } else {
                    _loadQR();
                }
            }), 2000);
        }
    };
    
    const _renderQR = function(e) {
        const t = document.getElementById("qr-code");
        if (!t) return;
        const n = e.length;
        const o = e[0].length;
        const i = window.innerWidth || screen.width;
        let r;
        if (i < 768) {
            r = Math.min(i * 0.85, 320);
        } else {
            r = Math.min(300, 350);
        }
        const s = Math.max(5, Math.min(10, Math.floor((r - 80) / o)));
        const a = o * s + 40;
        let c = '<div class="qr-grid" style="grid-template-columns: repeat(' + o + ', ' + s + 'px); width: ' + a + 'px; max-width: 100%; overflow-x: auto; margin: 0 auto;">';
        for (const i of e) {
            for (const e of i) {
                c += '<div class="qr-cell ' + (e === " " ? "white" : "") + '" style="width:' + s + 'px;height:' + s + 'px;"></div>';
            }
        }
        c += "</div>";
        t.innerHTML = c;
        const l = document.getElementById("qr-loading");
        if (l) l.style.display = "none";
        const d = document.getElementById("status-text");
        if (d) d.innerHTML = '<div class="qr-tip">请使用微信扫码连接</div><div class="qr-subtip">打开手机微信 → 扫一扫 → 确认连接</div>';
    };
    
    const _showChat = function(e) {
        const t = document.getElementById("login-page");
        if (t) t.style.display = "none";
        _state.users = e.users || [];
        _state.view = 'list';
        const n = document.getElementById("chat-list-page");
        if (n) n.classList.add("active");
        _setupDesktopLayout();
        _renderChatList();
        _loadChatListPreviews();
        _startPoll();
        _toast("已进入聊天界面");
    };
    
    const _manualRefresh = async function() {
        const e = document.getElementById("refresh-btn");
        const t = e ? e.textContent : "";
        if (e) {
            e.textContent = "检查中...";
            e.disabled = true;
        }
        try {
            const statusEl = document.getElementById("status-text");
            if (statusEl) statusEl.innerHTML = '<div class="qr-tip">正在获取二维码...</div>';
            const loadingEl = document.getElementById("qr-loading");
            if (loadingEl) loadingEl.style.display = "block";
            _toast("正在获取二维码...");
            await _loadQR();
        } catch(e) {
            _toast("检查失败");
        } finally {
            setTimeout((function() {
                if (e) {
                    e.textContent = t;
                    e.disabled = false;
                }
            }), 1500);
        }
    };
    
    const _forceChat = async function() {
        const e = document.getElementById("force-chat-btn");
        if (e) {
            e.textContent = "进入中...";
            e.disabled = true;
        }
        try {
            _toast("正在进入聊天界面...");
            const t = await _get("status");
            if (!t) throw new Error("无法获取状态");
            _showChat(t);
        } catch(t) {
            try {
                const n = document.getElementById("login-page");
                if (n) n.style.display = "none";
                _state.users = [];
                _state.view = 'list';
                const o = document.getElementById("chat-list-page");
                if (o) o.classList.add("active");
                _renderChatList();
                _startPoll();
                _toast("已强制进入聊天");
            } catch(e) {
                _toast("强制进入失败");
            }
        } finally {
            setTimeout((function() {
                if (e) {
                    e.textContent = "进入聊天";
                    e.disabled = false;
                }
            }), 2000);
        }
    };
    
    const _initMobileViewport = function() {
        if (!window.visualViewport) return;
        var vv = window.visualViewport;
        var onResize = function() {
            var isKeyboardOpen = vv.height < window.innerHeight - 80;
            if (isKeyboardOpen) {
                document.body.classList.add('keyboard-open');
                var chatContainer = document.querySelector('.chat-container.active');
                if (chatContainer) {
                    chatContainer.style.height = vv.height + 'px';
                }
                var chatPage = document.getElementById('chat-page');
                if (chatPage && chatPage.classList.contains('active')) {
                    chatPage.style.height = vv.height + 'px';
                }
                var settingsPanel = document.getElementById('settings-panel');
                if (settingsPanel && settingsPanel.classList.contains('show')) {
                    settingsPanel.style.height = vv.height + 'px';
                }
                var inputArea = document.querySelector('.chat-container.active .input-area');
                if (inputArea) {
                    inputArea.style.position = 'sticky';
                    inputArea.style.bottom = '0';
                }
                var messagesArea = document.getElementById('messages-area');
                if (messagesArea) {
                    messagesArea.scrollTop = messagesArea.scrollHeight;
                }
                var activeInput = document.querySelector('input:focus, textarea:focus');
                if (activeInput) {
                    setTimeout(function() {
                        activeInput.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                    }, 80);
                }
            } else {
                document.body.classList.remove('keyboard-open');
                var chatContainers = document.querySelectorAll('.chat-container');
                chatContainers.forEach(function(c) { c.style.height = ''; });
                var chatP = document.getElementById('chat-page');
                if (chatP) chatP.style.height = '';
                var sp = document.getElementById('settings-panel');
                if (sp) sp.style.height = '';
                var inputAreas = document.querySelectorAll('.input-area');
                inputAreas.forEach(function(ia) {
                    ia.style.position = '';
                    ia.style.bottom = '';
                });
            }
        };
        vv.addEventListener('resize', onResize);
        vv.addEventListener('scroll', function() {
            if (vv.height < window.innerHeight - 80) {
                window.scrollTo(0, 0);
                document.documentElement.scrollTop = 0;
            }
        });
        window.addEventListener('orientationchange', function() {
            setTimeout(function() {
                document.body.classList.remove('keyboard-open');
                var chatContainers = document.querySelectorAll('.chat-container');
                chatContainers.forEach(function(c) { c.style.height = ''; });
                var chatP = document.getElementById('chat-page');
                if (chatP) chatP.style.height = '';
                var sp = document.getElementById('settings-panel');
                if (sp) sp.style.height = '';
                var inputAreas = document.querySelectorAll('.input-area');
                inputAreas.forEach(function(ia) {
                    ia.style.position = '';
                    ia.style.bottom = '';
                });
            }, 200);
        });
    };

    const _initEvents = function() {
        document.addEventListener("error", function(ev) {
            var img = ev.target;
            if (img.tagName === 'IMG' && img.classList.contains('bubble-media-img')) {
                var wrap = img.closest('.bubble-media-img-wrap');
                if (wrap && wrap.dataset.cdn && !wrap.classList.contains('bubble-media-loading') && img.src.indexOf('/api/wasm/media/') === -1) {
                    wrap.classList.add('bubble-media-loading');
                    wrap.innerHTML = '<div class="bubble-media-placeholder">' + _svgImage + '<span>图片</span></div>';
                    window._loadCdnMedia(wrap);
                }
            }
        }, true);
        document.addEventListener("click", function(ev) {
            var thumb = ev.target.closest("[data-action='play-video']");
            if (thumb) {
                var videoSrc = thumb.dataset.videoSrc;
                if (videoSrc) {
                    window._previewVideo(videoSrc);
                } else {
                    var imgEl = thumb.querySelector('img');
                    if (imgEl && imgEl.src && imgEl.src.indexOf('/api/wasm/media/') !== -1) {
                        window._previewVideo(imgEl.src);
                    }
                }
                return;
            }
        });
        const e = document.getElementById("send-btn");
        if (e) e.addEventListener("click", _sendMsg);
        const t = document.getElementById("message-input");
        if (t) {
            t.addEventListener("keypress", function(e) { if (e.key === "Enter") { _closeMediaPanel(); _sendMsg(); } });
            t.addEventListener("focus", function() { _closeMediaPanel(); setTimeout(function() { var ma = document.getElementById('messages-area'); if (ma) ma.scrollTop = ma.scrollHeight; }, 100); });
        }
        const plusBtn = document.getElementById("plus-btn");
        if (plusBtn) plusBtn.addEventListener("click", _toggleMediaPanel);
        const photoOpt = document.getElementById("media-photo");
        if (photoOpt) photoOpt.addEventListener("click", function() { document.getElementById("file-photo").click(); });
        const cameraOpt = document.getElementById("media-camera");
        if (cameraOpt) cameraOpt.addEventListener("click", function() { document.getElementById("file-camera").click(); });
        const videoOpt = document.getElementById("media-video");
        if (videoOpt) videoOpt.addEventListener("click", function() { document.getElementById("file-video").click(); });
        const fileOpt = document.getElementById("media-file");
        if (fileOpt) fileOpt.addEventListener("click", function() { document.getElementById("file-doc").click(); });
        const filePhoto = document.getElementById("file-photo");
        if (filePhoto) filePhoto.addEventListener("change", _handlePhotoSelect);
        const fileCamera = document.getElementById("file-camera");
        if (fileCamera) fileCamera.addEventListener("change", _handlePhotoSelect);
        const fileVideo = document.getElementById("file-video");
        if (fileVideo) fileVideo.addEventListener("change", _handleVideoSelect);
        const fileVideoCap = document.getElementById("file-video-capture");
        if (fileVideoCap) fileVideoCap.addEventListener("change", _handleVideoSelect);
        const fileDoc = document.getElementById("file-doc");
        if (fileDoc) fileDoc.addEventListener("change", _handleFileSelect);
        const n = document.getElementById("user-select-btn");
        if (n) n.addEventListener("click", function() { const e = document.getElementById("user-dropdown"); if (e) e.classList.toggle("show"); });
        const chatListSettingsBtn = document.getElementById("chat-list-settings-btn");
        if (chatListSettingsBtn) chatListSettingsBtn.addEventListener("click", _openSettings);
        const addUserBtn = document.getElementById("chat-list-add-btn");
        if (addUserBtn) addUserBtn.addEventListener("click", _startAddUser);
        const addUserCloseBtn = document.getElementById("add-user-close-btn");
        if (addUserCloseBtn) addUserCloseBtn.addEventListener("click", _closeAddUserModal);
        const chatBackBtn = document.getElementById("chat-back-btn");
        if (chatBackBtn) chatBackBtn.addEventListener("click", _backToChatList);
        const chatMenuBtn = document.getElementById("chat-menu-btn");
        if (chatMenuBtn) chatMenuBtn.addEventListener("click", _openNicknameModal);
        const nicknameCancelBtn = document.getElementById("nickname-cancel-btn");
        if (nicknameCancelBtn) nicknameCancelBtn.addEventListener("click", _closeNicknameModal);
        const nicknameSaveBtn = document.getElementById("nickname-save-btn");
        if (nicknameSaveBtn) nicknameSaveBtn.addEventListener("click", _saveNickname);
        const nicknameInput = document.getElementById("nickname-input");
        if (nicknameInput) nicknameInput.addEventListener("keypress", function(e) { if (e.key === "Enter") _saveNickname(); });
        const i = document.getElementById("refresh-btn");
        if (i) i.onclick = _manualRefresh;
        const r = document.getElementById("force-chat-btn");
        if (r) r.onclick = _forceChat;
        const modalClose = document.getElementById("ai-modal-close");
        if (modalClose) modalClose.addEventListener("click", _closeAiModal);
        const modalCancel = document.getElementById("ai-modal-cancel");
        if (modalCancel) modalCancel.addEventListener("click", _closeAiModal);
        const modalSend = document.getElementById("ai-modal-send");
        if (modalSend) modalSend.addEventListener("click", _sendAiReply);
        document.addEventListener("click", function(e) {
            const t = document.getElementById("user-dropdown");
            const n = document.getElementById("user-select-btn");
            const o = document.getElementById("settings-panel");
            const chatListSettingsBtn = document.getElementById("chat-list-settings-btn");
            const modal = document.getElementById("ai-modal");
            const mediaPanel = document.getElementById("media-panel");
            const plusBtn = document.getElementById("plus-btn");
            const nicknameModal = document.getElementById("nickname-modal");
            if (t && !t.contains(e.target) && n && !n.contains(e.target)) {
                t.classList.remove("show");
            }
            if (o && o.classList.contains("show") && !o.contains(e.target) && chatListSettingsBtn && !chatListSettingsBtn.contains(e.target)) {
                _closeSettings();
            }
            if (modal && modal.classList.contains("show") && e.target === modal) {
                _closeAiModal();
            }
            if (nicknameModal && nicknameModal.classList.contains("show") && e.target === nicknameModal) {
                _closeNicknameModal();
            }
            var addUserModal = document.getElementById("add-user-modal");
            if (addUserModal && addUserModal.classList.contains("show") && e.target === addUserModal) {
                _closeAddUserModal();
            }
            if (mediaPanel && mediaPanel.classList.contains("show") && !mediaPanel.contains(e.target) && plusBtn && !plusBtn.contains(e.target)) {
                _closeMediaPanel();
            }
        });
        const s = document.getElementById("settings-back-btn");
        if (s) s.addEventListener("click", _closeSettings);
        const apiBackBtn = document.getElementById("api-back-btn");
        if (apiBackBtn) apiBackBtn.addEventListener("click", function() { _showSettingsPage('settings-main'); });
        const apiItem = document.getElementById("settings-api-item");
        if (apiItem) apiItem.addEventListener("click", function() { _showSettingsPage('settings-api'); });
        const aboutItem = document.getElementById("settings-about-item");
        if (aboutItem) aboutItem.addEventListener("click", function() { _showSettingsPage('settings-about'); });
        const aboutBackBtn = document.getElementById("about-back-btn");
        if (aboutBackBtn) aboutBackBtn.addEventListener("click", function() { _showSettingsPage('settings-main'); });
        const aboutLogoImg = document.querySelector(".about-logo-img");
        if (aboutLogoImg) {
            aboutLogoImg.addEventListener("click", _onAvatarClick);
            aboutLogoImg.addEventListener("animationend", function() { aboutLogoImg.classList.remove("spinning"); });
        }
        const themeBtn = document.getElementById("theme-toggle-btn");
        if (themeBtn) themeBtn.addEventListener("click", function(ev) { ev.stopPropagation(); _toggleTheme(); });
        const themeItem = document.getElementById("settings-theme-item");
        if (themeItem) themeItem.addEventListener("click", function() { _toggleTheme(); });
        const a = document.querySelector(".settings-save");
        if (a) a.addEventListener("click", _saveAIConfig);

        // ===== Persona Navigation & Events
        const personaItem = document.getElementById("settings-persona-item");
        if (personaItem) personaItem.addEventListener("click", function() { _showSettingsPage('settings-persona'); });
        const personaBackBtn = document.getElementById("persona-back-btn");
        if (personaBackBtn) personaBackBtn.addEventListener("click", function() { _showSettingsPage('settings-main'); });

        const personaCreateBtn = document.getElementById("persona-create-btn");
        if (personaCreateBtn) personaCreateBtn.addEventListener("click", function() { _openPersonaEdit(null); });

        const peditCloseBtn = document.getElementById("pedit-modal-close");
        if (peditCloseBtn) peditCloseBtn.addEventListener("click", _closePersonaEdit);
        const peditCancelBtn = document.getElementById("pedit-cancel-btn");
        if (peditCancelBtn) peditCancelBtn.addEventListener("click", _closePersonaEdit);
        const peditSaveBtn = document.getElementById("pedit-save-btn");
        if (peditSaveBtn) peditSaveBtn.addEventListener("click", _savePersona);
        document.addEventListener("click", function(ev) {
            var peditModal = document.getElementById("persona-edit-modal");
            if (peditModal && peditModal.classList.contains("show") && ev.target === peditModal) {
                _closePersonaEdit();
            }
        });

        const personaSaveCfgBtn = document.getElementById("persona-save-config-btn");
        if (personaSaveCfgBtn) personaSaveCfgBtn.addEventListener("click", _savePersonaConfig);

        document.querySelectorAll('input[name="persona-mode"]').forEach(function(r) {
            r.addEventListener('change', function() {
                _state.personaMode = this.value;
                _renderPersonaSetup();
            });
        });

        // ===== Sidebar Navigation =====
        var sidebarItems = document.querySelectorAll('#sidebar .sidebar-nav-item[data-action]');
        sidebarItems.forEach(function(item) {
            item.addEventListener('click', function() {
                var action = item.getAttribute('data-action');
                if (action === 'chat-list') {
                    if (_state.currentUser) _backToChatList();
                    _updateSidebarActive(item);
                } else if (action === 'new-chat') {
                    _startAddUser();
                } else if (action === 'settings') {
                    _openSettings();
                } else if (action === 'help') {
                    _showSettingsPage('settings-about');
                    _openSettings();
                } else if (action === 'knowledge' || action === 'favorites' || action === 'workspace') {
                    _toast('功能即将上线');
                }
            });
        });

        // ===== Bottom Nav (Mobile) =====
        var bnChats = document.getElementById('bn-chats');
        var bnNewChat = document.getElementById('bn-new-chat');
        var bnSettings = document.getElementById('bn-settings');
        if (bnChats) bnChats.addEventListener('click', function() {
            if (_state.currentUser) _backToChatList();
            _updateBottomNavActive(bnChats);
        });
        if (bnNewChat) bnNewChat.addEventListener('click', function() { _startAddUser(); });
        if (bnSettings) bnSettings.addEventListener('click', function() { _openSettings(); });

        // ===== Sidebar Overlay =====
        var sidebarOverlay = document.getElementById('sidebar-overlay');
        if (sidebarOverlay) {
            sidebarOverlay.addEventListener('click', function() {
                _closeSidebar();
            });
        }

        // ===== Sidebar Logo Click =====
        var sidebarBrand = document.querySelector('#sidebar .sidebar-brand');
        if (sidebarBrand) {
            sidebarBrand.addEventListener('click', function() {
                if (_state.currentUser) _backToChatList();
                _updateSidebarActive(document.getElementById('sidebar-chat-list'));
            });
            sidebarBrand.style.cursor = 'pointer';
        }
    };

    var _updateSidebarActive = function(item) {
        document.querySelectorAll('#sidebar .sidebar-nav-item').forEach(function(el) { el.classList.remove('active'); });
        if (item) item.classList.add('active');
    };

    var _updateBottomNavActive = function(item) {
        document.querySelectorAll('.bottom-nav-item').forEach(function(el) { el.classList.remove('active'); });
        if (item) item.classList.add('active');
    };

    var _closeSidebar = function() {
        var sidebar = document.getElementById('sidebar');
        var overlay = document.getElementById('sidebar-overlay');
        if (sidebar) sidebar.classList.remove('mobile-open');
        if (overlay) overlay.classList.remove('show');
    };

    var _setupDesktopLayout = function() {
        var app = document.getElementById('app');
        if (!app) return;
        if (window.innerWidth >= 1025) {
            app.classList.add('has-sidebar');
        } else {
            app.classList.remove('has-sidebar');
        }
    };

    if (window.addEventListener) {
        window.addEventListener('resize', _setupDesktopLayout);
    }

    const _init = function() {
        antiDebug();
        _initTheme();
        _initMobileViewport();
        _setupDesktopLayout();
        _initEvents();
        _checkStatus();
    };

    // ─── 角色卡（Persona）系统 ──────────────────────────────────

    const _loadPersonas = async function() {
        const data = await _get("personas");
        if (!data || data.error) return;
        _state.personas = data.personas || [];
        _state.personaMode = data.persona_mode || 'none';
        _state.globalPersonaId = data.global_persona_id || null;
        _state.userPersonaMap = data.user_persona_map || {};
    };

    const _loadPersonaConfig = async function() {
        const data = await _get("persona-config");
        if (!data || data.error) return;
        _state.personaMode = data.persona_mode || 'none';
        _state.globalPersonaId = data.global_persona_id || null;
        _state.userPersonaMap = data.user_persona_map || {};
    };

    const _renderPersonaList = function() {
        var container = document.getElementById("persona-list-items");
        if (!container) { _loadPersonas(); return; }
        var list = _state.personas;
        if (!list || list.length === 0) {
            container.innerHTML = '<div class="chat-list-empty" style="padding:60px 20px"><div class="chat-list-empty-icon" style="font-size:32px">🎭</div><div>暂无角色卡</div><div style="font-size:12px;color:var(--text-hint);margin-top:8px">点击下方按钮创建角色</div></div>';
            return;
        }
        var html = '';
        list.forEach(function(p) {
            var preview = p.personality ? p.personality.slice(0, 30) + (p.personality.length > 30 ? '...' : '') : '未设置性格';
            var isActive = (function() {
                if (_state.personaMode === 'global' && _state.globalPersonaId === p.id) return true;
                if (_state.personaMode === 'per_user') {
                    for (var uid in _state.userPersonaMap) {
                        if (_state.userPersonaMap[uid] === p.id) return true;
                    }
                }
                return false;
            })();
            html += '<div class="persona-card" data-pid="' + p.id + '">' +
                '<div class="persona-card-header">' +
                '<div class="persona-card-avatar">' + _escape(p.name.charAt(0) || '?') + '</div>' +
                '<div class="persona-card-info">' +
                '<div class="persona-card-name">' + _escape(p.name) + (isActive ? ' <span class="persona-active-badge">使用中</span>' : '') + '</div>' +
                '<div class="persona-card-preview">' + _escape(preview) + '</div>' +
                '</div></div>' +
                '<div class="persona-card-actions">' +
                '<button class="persona-btn persona-btn-sm persona-btn-edit" data-pid="' + p.id + '">编辑</button>' +
                '<button class="persona-btn persona-btn-sm persona-btn-del" data-pid="' + p.id + '">删除</button>' +
                '</div></div>';
        });
        container.innerHTML = html;
        container.querySelectorAll('.persona-btn-edit').forEach(function(btn) {
            btn.addEventListener('click', function(ev) {
                ev.stopPropagation();
                _openPersonaEdit(btn.dataset.pid);
            });
        });
        container.querySelectorAll('.persona-btn-del').forEach(function(btn) {
            btn.addEventListener('click', function(ev) {
                ev.stopPropagation();
                if (confirm('确定删除此角色卡？')) _deletePersona(btn.dataset.pid);
            });
        });
        container.querySelectorAll('.persona-card').forEach(function(card) {
            card.addEventListener('click', function() {
                _openPersonaEdit(card.dataset.pid);
            });
        });
    };

    const _openPersonaEdit = function(pid) {
        _state.editingPersonaId = pid;
        var modal = document.getElementById("persona-edit-modal");
        var p = null;
        if (pid) {
            for (var i = 0; i < _state.personas.length; i++) {
                if (_state.personas[i].id === pid) { p = _state.personas[i]; break; }
            }
        }
        document.getElementById("pedit-name").value = p ? p.name : '';
        document.getElementById("pedit-personality").value = p ? p.personality : '';
        document.getElementById("pedit-language").value = p ? p.language_style : '';
        document.getElementById("pedit-background").value = p ? p.background : '';
        document.getElementById("pedit-behavior").value = p ? p.behavior : '';
        document.getElementById("pedit-other").value = p ? p.other_details : '';
        document.getElementById("pedit-modal-title").textContent = p ? '编辑角色' : '新建角色';

        // 用户分配复选框
        var assignSection = document.getElementById("pedit-user-assign-section");
        var assignList = document.getElementById("pedit-user-assign-list");
        if (assignSection && assignList) {
            if (_state.users.length > 0 && p) {
                assignSection.style.display = 'block';
                var html = '';
                _state.users.forEach(function(uid) {
                    var nick = _state.nicknames[uid] || '';
                    var display = nick || uid;
                    var checked = (_state.userPersonaMap[uid] === pid) ? ' checked' : '';
                    html += '<label class="pedit-assign-row" data-uid="' + uid + '">' +
                        '<input type="checkbox" class="pedit-assign-cb" data-uid="' + uid + '"' + checked + '> ' +
                        '<span title="' + _escape(uid) + '">' + _escape(display) + '</span></label>';
                });
                assignList.innerHTML = html;
            } else {
                assignSection.style.display = 'none';
            }
        }

        if (modal) modal.classList.add("show");
    };

    const _closePersonaEdit = function() {
        var modal = document.getElementById("persona-edit-modal");
        if (modal) modal.classList.remove("show");
        _state.editingPersonaId = null;
    };

    const _savePersona = async function() {
        var data = {
            id: _state.editingPersonaId,
            name: document.getElementById("pedit-name").value.trim(),
            personality: document.getElementById("pedit-personality").value.trim(),
            language_style: document.getElementById("pedit-language").value.trim(),
            background: document.getElementById("pedit-background").value.trim(),
            behavior: document.getElementById("pedit-behavior").value.trim(),
            other_details: document.getElementById("pedit-other").value.trim()
        };
        if (!data.name) { _toast("请输入角色名称"); return; }

        // 收集用户分配
        var assignCbs = document.querySelectorAll('.pedit-assign-cb:checked');
        var assignedUsers = [];
        assignCbs.forEach(function(cb) { assignedUsers.push(cb.dataset.uid); });
        data.assigned_users = assignedUsers;

        var result = await _api("persona-save", data);
        if (result && result.success) {
            // 更新 user_persona_map
            var pid = result.persona ? result.persona.id : _state.editingPersonaId;
            if (pid) {
                _state.users.forEach(function(uid) {
                    if (assignedUsers.indexOf(uid) !== -1) {
                        _state.userPersonaMap[uid] = pid;
                    } else if (_state.userPersonaMap[uid] === pid) {
                        delete _state.userPersonaMap[uid];
                    }
                });
                // 同步到后端
                await _api("persona-config", {
                    persona_mode: _state.personaMode,
                    global_persona_id: _state.globalPersonaId,
                    user_persona_map: _state.userPersonaMap
                });
            }
            _toast("角色卡已保存");
            _closePersonaEdit();
            await _loadPersonas();
            _renderPersonaList();
            _renderPersonaSetup();
        } else {
            _toast("保存失败: " + ((result && result.error) || "未知错误"));
        }
    };

    const _deletePersona = async function(pid) {
        var result = await _api("persona-delete", { id: pid });
        if (result && result.success) {
            _toast("角色卡已删除");
            await _loadPersonas();
            _renderPersonaList();
            _renderPersonaSetup();
        } else {
            _toast("删除失败: " + ((result && result.error) || "未知错误"));
        }
    };

    const _renderPersonaSetup = function() {
        var modeRadios = document.querySelectorAll('input[name="persona-mode"]');
        modeRadios.forEach(function(r) {
            r.checked = (r.value === _state.personaMode);
        });
        var globalSelect = document.getElementById("persona-global-select");
        if (globalSelect) {
            var html = '<option value="">不使用全局角色</option>';
            _state.personas.forEach(function(p) {
                var sel = _state.globalPersonaId === p.id ? ' selected' : '';
                html += '<option value="' + p.id + '"' + sel + '>' + _escape(p.name) + '</option>';
            });
            globalSelect.innerHTML = html;
        }
        var perUserContainer = document.getElementById("persona-peruser-list");
        if (perUserContainer) {
            var html2 = '';
            _state.users.forEach(function(uid) {
                var assigned = _state.userPersonaMap[uid] || '';
                var nick = _state.nicknames[uid] || '';
                var display = nick || uid;
                html2 += '<div class="persona-peruser-row" data-uid="' + uid + '">' +
                    '<span class="persona-peruser-label" title="' + _escape(uid) + '">' + _escape(display) + '</span>' +
                    '<select class="persona-peruser-select" data-uid="' + uid + '">';
                html2 += '<option value="">不指定</option>';
                _state.personas.forEach(function(p) {
                    var sel = assigned === p.id ? ' selected' : '';
                    html2 += '<option value="' + p.id + '"' + sel + '>' + _escape(p.name) + '</option>';
                });
                html2 += '</select></div>';
            });
            if (_state.users.length === 0) {
                html2 = '<div style="text-align:center;padding:20px;color:var(--text-hint);font-size:13px">暂无用户，添加用户后可单独指定角色</div>';
            }
            perUserContainer.innerHTML = html2;
            perUserContainer.querySelectorAll('.persona-peruser-select').forEach(function(sel) {
                sel.addEventListener('change', function() {
                    var uid = sel.dataset.uid;
                    var pid = sel.value;
                    _state.userPersonaMap[uid] = pid;
                });
            });
        }
        var modeSettings = document.getElementById("persona-mode-settings");
        if (modeSettings) {
            var mode = _state.personaMode;
            modeSettings.style.display = (mode === 'none') ? 'none' : 'block';
            var globalSection = document.getElementById("persona-global-section");
            if (globalSection) globalSection.style.display = (mode === 'global') ? 'block' : 'none';
            var perUserSection = document.getElementById("persona-peruser-section");
            if (perUserSection) perUserSection.style.display = (mode === 'per_user') ? 'block' : 'none';
        }
    };

    const _savePersonaConfig = async function() {
        var mode = 'none';
        document.querySelectorAll('input[name="persona-mode"]').forEach(function(r) { if (r.checked) mode = r.value; });
        var globalPid = document.getElementById("persona-global-select") ? document.getElementById("persona-global-select").value : null;
        var configData = {
            persona_mode: mode,
            global_persona_id: globalPid || null,
            user_persona_map: _state.userPersonaMap
        };
        var result = await _api("persona-config", configData);
        if (result && result.success) {
            _toast("角色配置已保存");
            _state.personaMode = mode;
            _state.globalPersonaId = globalPid || null;
            _showSettingsPage('settings-main');
        } else {
            _toast("保存失败: " + ((result && result.error) || "未知错误"));
        }
    };

    return { init: _init };
})();

window.ZynWasm = window.__ZN''' + session_token[:16] + ''';
window.ZynWasm.init();
'''
    
    def start_web_interface(self):
        if self._http_server is not None:
            print(f"网页服务已在运行中: http://localhost:{self._web_port}")
            return
        
        port = self._web_port
        handler = self._make_web_handler()
        
        bind_addresses = [""]
        if is_termux():
            bind_addresses = ["127.0.0.1", "localhost", ""]
            print("[TERMUX] 使用 Termux 兼容模式启动 Web 服务")
        
        server_started = False
        
        for bind_addr in bind_addresses:
            try:
                self._http_server = socketserver.ThreadingTCPServer((bind_addr, port), handler)
                self._server_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
                self._server_thread.start()
                
                display_addr = "localhost" if bind_addr else "127.0.0.1"
                print(f"\n[WEB] 网页界面已启动: http://{display_addr}:{port}")
                print("消息发送与二维码扫描请去本地网页操作! ")
                if is_termux():
                    print("     [TERMUX] 提示: 如果无法访问，请使用端口转发或反向代理")
                server_started = True
                break
            except OSError as e:
                if bind_addr != "":
                    continue
                for p in range(port + 1, port + 100):
                    try:
                        self._web_port = p
                        self._http_server = socketserver.ThreadingTCPServer((bind_addr, p), handler)
                        self._server_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
                        self._server_thread.start()
                        
                        display_addr = "localhost" if bind_addr else "127.0.0.1"
                        print(f"\n[WEB] 网页界面已启动: http://{display_addr}:{p}")
                        print("     支持扫码连接和聊天功能")
                        server_started = True
                        break
                    except OSError:
                        continue
                
                if server_started:
                    break
        
        if not server_started:
            print("[ERROR] 无法启动网页服务，端口均被占用")
            if is_termux():
                print("[TERMUX] 提示: Termux 可能需要特殊权限才能绑定端口")
                print("         尝试: termux-chroot 或使用 root 权限")
    
    def _make_web_handler(self):
        bot = self
        
        class WebHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            
            def _check_auth(self):
                session_token = self.headers.get('X-Session-Token')
                if session_token and bot._verify_session_token(session_token):
                    return True
                cookie_header = self.headers.get('Cookie', '')
                if cookie_header:
                    for part in cookie_header.split(';'):
                        part = part.strip()
                        if part.startswith('session_token='):
                            token = part.split('=', 1)[1]
                            if token and bot._verify_session_token(token):
                                return True
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                token_param = params.get('token', [None])[0]
                if token_param and bot._verify_session_token(token_param):
                    return True
                return False
            
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                
                if parsed.path == '/':
                    self._serve_wasm_page()

                elif parsed.path.startswith('/api/wasm/'):
                    if not self._check_auth():
                        self.send_response(401)
                        self.end_headers()
                        return
                    api_path = parsed.path[10:]
                    if api_path == 'status':
                        self._serve_status()
                    elif api_path == 'qrcode':
                        self._serve_qrcode()
                    elif api_path == 'messages':
                        self._serve_messages()
                    elif api_path == 'users':
                        self._serve_users()
                    elif api_path == 'history':
                        self._serve_history()
                    elif api_path == 'ai-config':
                        self._serve_ai_config()
                    elif api_path == 'about':
                        self._serve_about()
                    elif api_path == 'personas':
                        self._serve_personas()
                    elif api_path == 'persona-config':
                        self._serve_persona_config()
                    elif api_path == 'add-user-status':
                        self._serve_add_user_status()
                    elif api_path.startswith('media/'):
                        self._serve_cached_media(api_path[6:])
                    else:
                        self.send_error(404)
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if not self._check_auth():
                    self.send_response(401)
                    self.end_headers()
                    return
                
                data = self._parse_json_body()
                if data is None:
                    return
                
                parsed = urllib.parse.urlparse(self.path)
                
                if parsed.path == '/api/wasm/send':
                    self._handle_send(data)
                elif parsed.path == '/api/wasm/send-media':
                    self._handle_send_media(data)
                elif parsed.path == '/api/wasm/download-media':
                    self._handle_download_media(data)
                elif parsed.path == '/api/wasm/switch-user':
                    self._handle_switch_user(data)
                elif parsed.path == '/api/wasm/ai-config':
                    self._handle_save_ai_config(data)
                elif parsed.path == '/api/wasm/ai-manual-reply':
                    self._handle_ai_manual_reply(data)
                elif parsed.path == '/api/wasm/add-user-start':
                    self._handle_add_user_start(data)
                elif parsed.path == '/api/wasm/persona-save':
                    self._handle_persona_save(data)
                elif parsed.path == '/api/wasm/persona-delete':
                    self._handle_persona_delete(data)
                elif parsed.path == '/api/wasm/persona-config':
                    self._handle_persona_config(data)
                else:
                    self.send_error(404)
            
            def _parse_json_body(self):
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length) if content_length else b'{}'
                try:
                    return json.loads(body.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    self._send_json({'success': False, 'error': f'请求数据格式错误: {e}'}, 400)
                    return None
            
            def _handle_ai_manual_reply(self, data):
                try:
                    user_id = data.get('user_id')
                    original_message = data.get('original_message', '')
                    instruction = data.get('instruction', '')
                    
                    if not user_id:
                        self._send_json({'success': False, 'error': '用户ID不能为空'})
                        return
                    
                    print(f"[WEB] 收到手动 AI 回复请求: user={user_id}, msg={original_message[:50]}, instruction={instruction[:50] if instruction else '无'}")
                    
                    success = bot._manual_ai_reply(user_id, original_message, instruction)
                    
                    if success:
                        self._send_json({'success': True, 'message': 'AI 回复已发送'})
                    else:
                        self._send_json({'success': False, 'error': 'AI 回复失败，请检查 API 配置'})
                        
                except Exception as e:
                    print(f"[WEB] 手动 AI 回复异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _handle_add_user_start(self, data):
                try:
                    with bot._add_user_lock:
                        if bot._pending_qrcode and bot._pending_qrcode.get("status") not in ("done", "error", "expired"):
                            self._send_json({'success': True, 'status': 'already_running', 'message': '已有进行中的添加操作'})
                            return
                    
                    qrcode_key = bot.start_add_user_qrcode()
                    print(f"[WEB] 开始添加用户，qrcode_key={qrcode_key}")
                    
                    for _ in range(30):
                        with bot._add_user_lock:
                            if bot._pending_qrcode and bot._pending_qrcode.get("matrix"):
                                self._send_json({
                                    'success': True,
                                    'status': 'qrcode_ready',
                                    'matrix': bot._pending_qrcode.get("matrix"),
                                    'key': qrcode_key
                                })
                                return
                        time.sleep(0.5)
                    
                    self._send_json({'success': True, 'status': 'generating', 'message': '正在生成二维码...'})
                except Exception as e:
                    print(f"[WEB] 添加用户异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _serve_add_user_status(self):
                try:
                    status = bot.get_add_user_status()
                    was_done = status.get("status") == "done"
                    self._send_json({
                        'success': True,
                        'qrcode_status': status.get('status'),
                        'matrix': status.get('matrix'),
                        'key': status.get('key'),
                        'users': list(bot._context_tokens.keys()),
                        'login_done': was_done
                    })
                except Exception as e:
                    self._send_json({'success': False, 'error': str(e)})
            
            def _serve_wasm_page(self):
                session_token = bot._generate_session_token()

                html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover, interactive-widget=resizes-content">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Dancing+Script:wght@500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" integrity="sha384-7mGJN1QfRrK2G/52m3MqI0H5CmwRNq/gOBlYMB0G4kKQjW4b2LvkK1hKWVtBqFc" crossorigin="anonymous"></script>
<title>Sioboot</title>
<style>
/* ===== Reset & Base ===== */
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{width:100%;height:100vh;height:100dvh;overflow:hidden;font-family:"PingFang SC","HarmonyOS Sans","Noto Sans SC","Microsoft YaHei",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px;background:var(--bg-primary);color:var(--text-primary);-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility}

/* ===== Design Tokens ===== */
:root{
  --bg-primary:#F7F3EC;
  --bg-secondary:#EFE8DD;
  --bg-card:#FFFFFF;
  --bg-chat:#FAF7F2;
  --accent:#B7864A;
  --accent-hover:#C89658;
  --accent-light:rgba(183,134,74,0.08);
  --accent-glow:rgba(183,134,74,0.15);
  --text-primary:#2A2622;
  --text-secondary:#6E665E;
  --text-hint:#9C9589;
  --bubble-out:#E9D9C2;
  --bubble-out-text:#2A2622;
  --bubble-in:#FFFFFF;
  --bubble-in-border:rgba(0,0,0,0.05);
  --bubble-in-shadow:0 2px 12px rgba(0,0,0,0.04);
  --divider:rgba(0,0,0,0.05);
  --divider-strong:rgba(0,0,0,0.08);
  --header-height:60px;
  --sidebar-width:280px;
  --nav-bg:rgba(255,255,255,0.88);
  --chat-bg:#FAF7F2;
  --input-bg:#FFFFFF;
  --shadow-sm:0 1px 3px rgba(0,0,0,0.03);
  --shadow-md:0 4px 16px rgba(0,0,0,0.05);
  --shadow-lg:0 8px 32px rgba(0,0,0,0.06);
  --radius-sm:12px;
  --radius-md:16px;
  --radius-lg:24px;
  --radius-xl:32px;
  --radius-full:999px;
  --blur:20px;
  --transition-fast:150ms;
  --transition-normal:250ms;
  --transition-slow:350ms;
  --easing:ease-out;
  --font-display:600 24px/1.3 "PingFang SC","HarmonyOS Sans","Noto Sans SC",sans-serif;
  --font-body:400 15px/1.6 "PingFang SC","HarmonyOS Sans","Noto Sans SC",sans-serif;
}

[data-theme="dark"]{
  --bg-primary:#181614;
  --bg-secondary:#1E1B18;
  --bg-card:#23201D;
  --bg-chat:#1A1816;
  --accent:#D3A46A;
  --accent-hover:#DEB580;
  --accent-light:rgba(211,164,106,0.1);
  --accent-glow:rgba(211,164,106,0.12);
  --text-primary:#F4EFE8;
  --text-secondary:#A09889;
  --text-hint:#6D665E;
  --bubble-out:#3D3329;
  --bubble-out-text:#F4EFE8;
  --bubble-in:#23201D;
  --bubble-in-border:rgba(255,255,255,0.06);
  --bubble-in-shadow:0 2px 12px rgba(0,0,0,0.2);
  --divider:rgba(255,255,255,0.06);
  --divider-strong:rgba(255,255,255,0.1);
  --nav-bg:rgba(24,22,20,0.9);
  --chat-bg:#1A1816;
  --input-bg:#23201D;
  --shadow-sm:0 1px 3px rgba(0,0,0,0.2);
  --shadow-md:0 4px 16px rgba(0,0,0,0.25);
  --shadow-lg:0 8px 32px rgba(0,0,0,0.3);
}

/* ===== Scrollbar ===== */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(183,134,74,0.25);border-radius:10px}
::-webkit-scrollbar-thumb:hover{background:rgba(183,134,74,0.4)}
[data-theme="dark"] ::-webkit-scrollbar-thumb{background:rgba(211,164,106,0.2)}
[data-theme="dark"] ::-webkit-scrollbar-thumb:hover{background:rgba(211,164,106,0.35)}

/* ===== App Layout ===== */
#app{display:flex;width:100%;height:100vh;height:100dvh;background:var(--bg-primary);position:relative;overflow:hidden}
#app.has-sidebar{padding-left:var(--sidebar-width)}
@media(max-width:768px){#app.has-sidebar{padding-left:0}}

/* ===== Sidebar ===== */
#sidebar{position:fixed;left:0;top:0;bottom:0;width:var(--sidebar-width);background:var(--bg-card);border-right:1px solid var(--divider);display:flex;flex-direction:column;z-index:100;overflow:hidden;transition:transform var(--transition-normal) var(--easing)}
#sidebar .sidebar-inner{display:flex;flex-direction:column;height:100%;padding:0}
.sidebar-brand{padding:28px 24px 20px;flex-shrink:0}
.sidebar-brand-name{font-family:'Dancing Script',cursive;font-size:28px;font-weight:600;color:var(--text-primary);letter-spacing:.5px;line-height:1.2}
.sidebar-brand-sub{font-size:12px;color:var(--text-hint);margin-top:3px;letter-spacing:.5px;font-weight:400}
.sidebar-divider{height:1px;background:var(--divider);margin:0 20px;flex-shrink:0}
.sidebar-nav{flex:1;overflow-y:auto;padding:12px 0;flex-shrink:1}
.sidebar-nav-section{padding:0 12px;margin-bottom:4px}
.sidebar-nav-label{padding:8px 12px 4px;font-size:11px;font-weight:600;color:var(--text-hint);text-transform:uppercase;letter-spacing:1px}
.sidebar-nav-item{display:flex;align-items:center;gap:12px;padding:10px 12px;margin:2px 8px;border-radius:10px;cursor:pointer;color:var(--text-secondary);font-size:14px;font-weight:450;transition:all var(--transition-fast) var(--easing);position:relative;user-select:none;-webkit-user-select:none}
.sidebar-nav-item:hover{background:var(--accent-light);color:var(--text-primary)}
.sidebar-nav-item:active{transform:scale(.97)}
.sidebar-nav-item.active{background:var(--accent-light);color:var(--accent);font-weight:550}
.sidebar-nav-item.active::before{content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);width:3px;height:20px;background:var(--accent);border-radius:0 3px 3px 0}
.sidebar-nav-item .nav-icon{width:20px;height:20px;display:flex;align-items:center;justify-content:center;flex-shrink:0;opacity:.75}
.sidebar-nav-item.active .nav-icon{opacity:1}
.sidebar-nav-item .nav-badge{margin-left:auto;font-size:10px;font-weight:600;background:var(--accent);color:#fff;padding:2px 8px;border-radius:10px;min-width:20px;text-align:center}
.sidebar-footer{padding:16px 20px;border-top:1px solid var(--divider);flex-shrink:0}
.sidebar-footer-user{display:flex;align-items:center;gap:10px;padding:8px;border-radius:10px;cursor:pointer;transition:background var(--transition-fast)}
.sidebar-footer-user:hover{background:var(--accent-light)}
.sidebar-footer-avatar{width:32px;height:32px;border-radius:50%;background:var(--accent-light);color:var(--accent);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;flex-shrink:0}
.sidebar-footer-name{font-size:13px;color:var(--text-secondary);font-weight:450;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ===== Main Content ===== */
.main-content{flex:1;display:flex;flex-direction:column;min-width:0;position:relative;height:100%}

/* ===== Login Page ===== */
.login-container{width:100%;height:100vh;height:100dvh;display:flex;flex-direction:column;align-items:center;justify-content:center;background:var(--bg-primary);overflow-y:auto;position:relative}
.login-container::before{content:'';position:absolute;top:0;left:0;right:0;bottom:0;background:radial-gradient(ellipse at 50% 40%,rgba(183,134,74,0.04) 0%,transparent 70%);pointer-events:none}
.login-header{text-align:center;padding:0 20px 48px;animation:fadeUp .8s ease-out;position:relative;z-index:1}
.login-header h1{font-family:'Dancing Script',cursive;font-size:clamp(42px,6vw,60px);font-weight:600;color:var(--text-primary);margin-bottom:10px;letter-spacing:.5px;line-height:1.15}
.login-header p{font-size:16px;color:var(--text-secondary);letter-spacing:.8px;font-weight:350}
.qr-container{background:var(--bg-card);border-radius:var(--radius-lg);padding:48px 40px;box-shadow:var(--shadow-lg);text-align:center;max-width:380px;width:calc(100% - 40px);margin:0 auto;animation:fadeUp .8s ease-out .2s both;position:relative;z-index:1;border:1px solid var(--divider)}
#qr-code{margin:32px auto;display:flex;justify-content:center;max-width:100%;overflow:visible}
.qr-grid{display:grid;gap:0;background:#FFFFFF;padding:24px;border-radius:var(--radius-md);border:1px solid var(--divider);max-width:280px;width:auto;min-width:180px;box-sizing:border-box;image-rendering:pixelated;margin:0 auto;box-shadow:var(--shadow-sm)}
.qr-cell{width:9px;height:9px;background:#2A2622;min-width:5px;min-height:5px;display:block}
.qr-cell.white{background:var(--bg-card)}
.qr-tip{color:var(--accent);font-size:16px;font-weight:600;margin:24px 0 8px;letter-spacing:.5px}
.qr-subtip{color:var(--text-hint);font-size:13px}
.status-text{color:var(--text-secondary);font-size:14px;margin-top:16px}
.loading-spinner{width:36px;height:36px;border:2px solid var(--divider);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin:24px auto}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}

/* ===== Chat List ===== */
.chat-list-container{display:none;flex-direction:column;width:100%;height:100vh;height:100dvh;background:var(--bg-primary)}
.chat-list-container.active{display:flex}
.chat-list-header{height:var(--header-height);background:var(--nav-bg);backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));display:flex;align-items:center;justify-content:center;padding:0 20px;flex-shrink:0;border-bottom:1px solid var(--divider);position:relative;z-index:2}
.chat-list-header-title{font-size:18px;font-weight:600;color:var(--text-primary);letter-spacing:.5px}
.chat-list-settings-btn{position:absolute;right:16px;top:50%;transform:translateY(-50%);width:38px;height:38px;border-radius:50%;background:var(--bg-card);color:var(--text-secondary);border:1px solid var(--divider);cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all var(--transition-fast)}
.chat-list-settings-btn:hover{background:var(--accent-light);color:var(--accent)}
.chat-list-settings-btn:active{transform:translateY(-50%) scale(.94)}
.chat-list-add-btn{position:absolute;left:16px;top:50%;transform:translateY(-50%);width:38px;height:38px;border-radius:50%;background:var(--accent);color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all var(--transition-fast);box-shadow:0 2px 8px var(--accent-glow)}
.chat-list-add-btn:hover{background:var(--accent-hover);box-shadow:0 4px 14px var(--accent-glow)}
.chat-list-add-btn:active{transform:translateY(-50%) scale(.94)}
.chat-list-items{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;background:var(--bg-primary);padding:4px 0}
.chat-list-item{display:flex;align-items:center;padding:14px 20px;border-bottom:1px solid var(--divider);cursor:pointer;transition:all var(--transition-fast);gap:14px;position:relative}
.chat-list-item:hover{background:var(--accent-light)}
.chat-list-item:active{background:rgba(0,0,0,0.03)}
[data-theme="dark"] .chat-list-item:active{background:rgba(255,255,255,0.03)}
.chat-list-item-avatar{width:48px;height:48px;border-radius:50%;background:var(--accent-light);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:600;color:var(--accent);flex-shrink:0;transition:transform var(--transition-fast)}
.chat-list-item:hover .chat-list-item-avatar{transform:scale(1.05)}
.chat-list-item-content{flex:1;min-width:0}
.chat-list-item-name{font-size:15px;color:var(--text-primary);font-weight:550;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:.2px}
.chat-list-item-msg{font-size:13px;color:var(--text-hint);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-list-item-time{font-size:11px;color:var(--text-hint);flex-shrink:0;align-self:flex-start;margin-top:2px}
.chat-list-empty{text-align:center;padding:120px 20px;color:var(--text-hint)}
.chat-list-empty-icon{font-size:40px;margin-bottom:16px;opacity:.2}
.chat-list-empty div{font-size:14px}

/* ===== Chat Page ===== */
.chat-container{display:none;flex-direction:column;width:100%;height:100%;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--bg-primary)}
.chat-container.active{display:flex}
.chat-header{height:var(--header-height);background:var(--nav-bg);backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));display:flex;align-items:center;justify-content:center;padding:0 56px;flex-shrink:0;border-bottom:1px solid var(--divider);position:relative;z-index:2}
.chat-header-title{font-size:17px;font-weight:600;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;letter-spacing:.3px}
.chat-back-btn{position:absolute;left:16px;top:50%;transform:translateY(-50%);width:36px;height:36px;border-radius:50%;background:transparent;color:var(--accent);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all var(--transition-fast)}
.chat-back-btn:hover{background:var(--accent-light)}
.chat-back-btn:active{transform:translateY(-50%) scale(.9)}
.chat-header-menu-btn{position:absolute;right:16px;top:50%;transform:translateY(-50%);width:36px;height:36px;border-radius:50%;background:transparent;color:var(--text-secondary);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all var(--transition-fast)}
.chat-header-menu-btn:hover{background:var(--accent-light);color:var(--accent)}
.chat-header-menu-btn:active{transform:translateY(-50%) scale(.9)}

/* ===== Messages ===== */
.messages-area{flex:1;overflow-y:auto;padding:24px 20px;display:flex;flex-direction:column;gap:12px;background:var(--bg-primary);scroll-behavior:smooth}
.messages-area::before{content:'';display:block;height:8px;flex-shrink:0}
.msg-row{display:flex;align-items:flex-end;gap:8px;max-width:72%;animation:msgIn .25s ease-out}
.msg-row.out{flex-direction:row-reverse;margin-left:auto}
@keyframes msgIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.bubble{position:relative;padding:14px 18px;border-radius:24px;max-width:100%;line-height:1.6;font-size:15px;color:var(--text-primary);word-break:break-word;transition:all var(--transition-fast)}
.bubble.in{background:var(--bubble-in);border:1px solid var(--bubble-in-border);box-shadow:var(--bubble-in-shadow);border-bottom-left-radius:8px}
.bubble.in:hover{box-shadow:0 4px 16px rgba(0,0,0,0.06)}
.bubble.in:active{transform:scale(.985)}
.bubble.out{background:var(--bubble-out);color:var(--bubble-out-text);border-bottom-right-radius:8px;cursor:default;box-shadow:var(--shadow-sm)}
.bubble-text{margin-bottom:2px;white-space:pre-wrap}
.msg-time{font-size:10px;color:var(--text-hint);margin-top:6px;text-align:right;opacity:.8}
.msg-time-row{display:flex;align-items:center;justify-content:flex-end;gap:4px;margin-top:2px}
.msg-send-status{display:inline-flex;align-items:center;justify-content:center}
.msg-send-loading{width:12px;height:12px;border:2px solid var(--text-hint);border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite}
.msg-send-fail{width:18px;height:18px;border-radius:50%;background:#C45C4A;color:#fff;font-size:11px;font-weight:700;line-height:18px;text-align:center;cursor:pointer}

/* ===== Input Area ===== */
.input-area{background:var(--nav-bg);backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));padding:12px 16px;display:flex;gap:10px;align-items:center;border-top:1px solid var(--divider);flex-shrink:0;padding-bottom:calc(12px + env(safe-area-inset-bottom,0px));z-index:2}
.message-input{flex:1;height:48px;border:1px solid var(--divider);border-radius:24px;padding:0 20px;font-size:15px;outline:none;transition:all var(--transition-normal);background:var(--input-bg);color:var(--text-primary);box-shadow:var(--shadow-sm);font-family:inherit}
.message-input:hover{border-color:var(--divider-strong)}
.message-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light)}
.message-input::placeholder{color:var(--text-hint);font-weight:350}
.send-button{width:44px;height:44px;border-radius:50%;border:none;background:var(--accent);color:white;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all var(--transition-fast);font-size:18px;box-shadow:0 2px 10px var(--accent-glow);flex-shrink:0}
.send-button:hover{background:var(--accent-hover);box-shadow:0 4px 16px var(--accent-glow);transform:translateY(-1px)}
.send-button:active{transform:scale(.92)}
.plus-button{width:44px;height:44px;border-radius:50%;border:none;background:transparent;color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all var(--transition-fast);font-size:26px;font-weight:300;flex-shrink:0;user-select:none;-webkit-user-select:none}
.plus-button:hover{background:var(--accent-light);color:var(--accent)}
.plus-button:active{transform:scale(.88)}
.plus-button.active{color:var(--accent);transform:rotate(45deg);background:var(--accent-light)}

/* ===== Media Panel ===== */
.media-panel{background:var(--nav-bg);backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));border-top:1px solid var(--divider);display:none;flex-direction:column;flex-shrink:0;overflow:hidden}
.media-panel.show{display:flex;animation:slideUp .25s ease-out}
@keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.media-panel-inner{padding:24px 16px;display:grid;grid-template-columns:repeat(4,1fr);gap:16px;justify-items:center}
.media-option{display:flex;flex-direction:column;align-items:center;gap:8px;cursor:pointer;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none;transition:transform var(--transition-fast)}
.media-option:hover{transform:translateY(-2px)}
.media-option:active .media-option-icon{transform:scale(.9)}
.media-option-icon{width:56px;height:56px;border-radius:var(--radius-md);background:var(--bg-card);border:1px solid var(--divider);display:flex;align-items:center;justify-content:center;font-size:24px;transition:all var(--transition-fast);box-shadow:var(--shadow-sm)}
.media-option:hover .media-option-icon{border-color:var(--accent);box-shadow:0 2px 12px var(--accent-glow)}
.media-option-label{font-size:12px;color:var(--text-secondary);text-align:center;line-height:1.2;font-weight:450}

/* ===== Media Upload ===== */
.media-upload-progress{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.25);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;z-index:10001}
.media-upload-progress.show{display:flex}
.media-upload-box{background:var(--bg-card);border-radius:var(--radius-lg);padding:32px 36px;text-align:center;color:var(--text-primary);min-width:150px;box-shadow:var(--shadow-lg);border:1px solid var(--divider)}
.media-upload-spinner{width:32px;height:32px;border:2px solid var(--divider);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 16px}
.media-upload-text{font-size:14px;font-weight:450;color:var(--text-secondary)}

/* ===== Bubble Media ===== */
.bubble-media-img{max-width:220px;max-height:220px;border-radius:16px;cursor:pointer;display:block;object-fit:cover;transition:transform var(--transition-fast)}
.bubble-media-img:hover{transform:scale(1.02)}
.bubble-media-file{display:flex;align-items:center;gap:12px;min-width:180px;cursor:pointer}
.bubble-media-file-icon{width:42px;height:42px;border-radius:var(--radius-sm);background:var(--accent-light);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;color:var(--accent)}
.bubble-media-file-info{flex:1;min-width:0}
.bubble-media-file-name{font-size:14px;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px;font-weight:450}
.bubble-media-file-size{font-size:11px;color:var(--text-hint);margin-top:2px}
.bubble-media-voice{display:flex;align-items:center;gap:8px;min-width:80px;cursor:pointer;position:relative;padding-bottom:6px}
.bubble-media-voice-bars{display:flex;align-items:center;gap:2px;height:20px}
.bubble-media-voice-bar{width:3px;border-radius:2px;background:var(--text-secondary)}
.bubble-media-voice-dur{font-size:12px;color:var(--text-hint)}
.bubble-media-voice-progress{position:absolute;bottom:0;left:0;right:0;height:2px;background:var(--divider);border-radius:2px;overflow:hidden}
.bubble-media-voice-progress-fill{height:100%;width:0%;background:var(--accent);border-radius:2px;transition:width .2s linear}
.bubble-media-voice.voice-playing .bubble-media-voice-bar{animation:voiceBarPulse .5s ease-in-out infinite alternate}
@keyframes voiceBarPulse{from{opacity:.35}to{opacity:1}}
.bubble-media-img-wrap{position:relative;overflow:hidden;border-radius:16px;background:var(--bg-secondary);min-height:80px;display:flex;align-items:center;justify-content:center}
.bubble-media-placeholder{display:flex;flex-direction:column;align-items:center;gap:6px;padding:20px;color:var(--text-hint);font-size:12px}
.bubble-media-placeholder span{white-space:nowrap}
.bubble-media-loading{cursor:wait}
.bubble-media-loading .bubble-media-placeholder{animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.bubble-media-video-thumb{position:relative;cursor:pointer}
.bubble-media-video-thumb-vid{max-width:100%;max-height:240px;border-radius:16px;display:block;object-fit:contain;background:#1a1a1a}
.bubble-media-play-btn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:52px;height:52px;border-radius:50%;background:rgba(0,0,0,0.35);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;pointer-events:none;transition:transform var(--transition-fast)}
.bubble-media-video-thumb:hover .bubble-media-play-btn{transform:translate(-50%,-50%) scale(1.08)}
.bubble-media-play-btn svg{width:24px;height:24px;fill:#fff;margin-left:2px}

/* ===== Toast ===== */
.toast{position:fixed;top:60px;left:50%;transform:translateX(-50%) translateY(-120px);background:var(--bg-card);color:var(--text-primary);padding:12px 28px;border-radius:24px;font-size:14px;font-weight:450;z-index:9999;transition:transform var(--transition-slow) cubic-bezier(.2,.9,.4,1.1);pointer-events:none;white-space:nowrap;max-width:90%;overflow:hidden;text-overflow:ellipsis;box-shadow:var(--shadow-md);border:1px solid var(--divider)}
.toast.show{transform:translateX(-50%) translateY(0)}

/* ===== Empty State ===== */
.empty-state{text-align:center;padding:100px 20px;color:var(--text-hint)}
.empty-state-icon{font-size:40px;margin-bottom:16px;opacity:.15}
.empty-state div{font-size:14px;line-height:1.6}

/* ===== Settings ===== */
.settings-panel{position:fixed;top:0;left:0;right:0;bottom:0;background:var(--bg-primary);z-index:1000;display:none;flex-direction:column;overflow:hidden;height:100vh;height:100dvh}
.settings-panel.show{display:flex}
.settings-page{position:absolute;top:0;left:0;right:0;bottom:0;background:var(--bg-primary);display:none;flex-direction:column;overflow:hidden}
.settings-page.active{display:flex}
.settings-page-slide{animation:slideInRight .3s cubic-bezier(.25,.1,.25,1)}
@keyframes slideInRight{from{transform:translateX(30%)}to{transform:translateX(0)}}
.settings-nav-header{height:var(--header-height);background:var(--nav-bg);backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));display:flex;align-items:center;padding:0 20px;flex-shrink:0;border-bottom:1px solid var(--divider);gap:12px}
.settings-nav-header .back-btn{width:32px;height:32px;border:none;background:transparent;color:var(--accent);font-size:22px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;border-radius:50%;transition:all var(--transition-fast)}
.settings-nav-header .back-btn:hover{background:var(--accent-light)}
.settings-nav-header .back-btn:active{transform:scale(.9)}
.settings-nav-header .nav-title{font-size:18px;font-weight:600;color:var(--text-primary)}
.settings-scroll{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:16px 16px 40px}
.settings-group{margin-top:20px}
.settings-group:first-child{margin-top:12px}
.settings-group-title{padding:0 16px 8px;font-size:11px;color:var(--text-hint);font-weight:600;letter-spacing:1px;text-transform:uppercase}
.settings-item{display:flex;align-items:center;padding:15px 18px;background:var(--bg-card);cursor:pointer;transition:all var(--transition-fast);min-height:56px;border:1px solid var(--divider)}
.settings-item:hover{background:var(--accent-light)}
.settings-item:active{transform:scale(.99)}
.settings-item+.settings-item{border-top:none}
.settings-item:first-child{border-radius:var(--radius-md) var(--radius-md) 0 0}
.settings-item:last-child{border-radius:0 0 var(--radius-md) var(--radius-md)}
.settings-item:only-child{border-radius:var(--radius-md)}
.settings-item-icon{width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;margin-right:14px;font-size:14px;flex-shrink:0}
.settings-item-content{flex:1;min-width:0}
.settings-item-label{font-size:15px;color:var(--text-primary);font-weight:450}
.settings-item-desc{font-size:12px;color:var(--text-hint);margin-top:2px}
.settings-item-arrow{color:var(--text-hint);font-size:16px;margin-left:8px;flex-shrink:0;transition:transform var(--transition-fast)}
.settings-item:hover .settings-item-arrow{transform:translateX(2px)}
.settings-item-action{margin-left:8px;flex-shrink:0}
.theme-toggle{width:52px;height:30px;border-radius:15px;background:var(--divider-strong);position:relative;cursor:pointer;transition:background var(--transition-normal);border:none;padding:0}
.theme-toggle.active{background:var(--accent)}
.theme-toggle-knob{width:26px;height:26px;border-radius:50%;background:#FFFFFF;position:absolute;top:2px;left:2px;transition:transform var(--transition-normal) cubic-bezier(.4,.0,.2,1);box-shadow:0 1px 3px rgba(0,0,0,0.12)}
.theme-toggle.active .theme-toggle-knob{transform:translateX(22px)}
.settings-header{padding:16px;background:var(--accent);color:white;border-radius:var(--radius-md) var(--radius-md) 0 0;font-weight:600;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0}
.settings-close{background:none;border:none;color:white;font-size:20px;cursor:pointer}
.settings-body{padding:16px;padding-bottom:40px}
.setting-item{margin-bottom:18px}
.setting-label{display:block;font-size:13px;color:var(--text-secondary);margin-bottom:8px;font-weight:500;letter-spacing:.3px}
.setting-input,.setting-select{width:100%;padding:12px 16px;border:1px solid var(--divider);border-radius:var(--radius-sm);font-size:14px;outline:none;background:var(--bg-card);color:var(--text-primary);transition:all var(--transition-normal);font-family:inherit}
.setting-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light)}
.setting-checkbox{display:flex;align-items:center;gap:10px;cursor:pointer;font-size:14px;color:var(--text-primary)}
.setting-checkbox input{width:18px;height:18px;cursor:pointer;accent-color:var(--accent)}
.setting-row{display:flex;gap:14px}
.setting-row .setting-item{flex:1}
.settings-save{width:100%;padding:14px;background:var(--accent);color:white;border:none;border-radius:24px;font-size:15px;font-weight:550;cursor:pointer;margin-top:12px;transition:all var(--transition-fast);box-shadow:0 2px 10px var(--accent-glow);letter-spacing:.5px}
.settings-save:hover{background:var(--accent-hover);box-shadow:0 4px 18px var(--accent-glow)}
.settings-save:active{transform:scale(.97)}

/* ===== About ===== */
.about-logo{display:flex;flex-direction:column;align-items:center;padding:48px 0 24px}
.about-logo-circle{width:80px;height:80px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:700;box-shadow:0 4px 24px var(--accent-glow)}
.about-logo-img{width:80px;height:80px;border-radius:50%;object-fit:cover;background:var(--bg-secondary);box-shadow:0 4px 24px var(--accent-glow);cursor:pointer;transition:all var(--transition-fast)}
.about-logo-img:hover{box-shadow:0 6px 30px rgba(183,134,74,0.3);transform:scale(1.02)}
.about-logo-img:active{box-shadow:0 4px 24px var(--accent-glow)}
.about-logo-img.spinning{animation:aboutLogoSpin .7s cubic-bezier(.4,0,.2,1)}
@keyframes aboutLogoSpin{to{transform:rotate(360deg)}}
.about-logo-name{font-family:'Dancing Script',cursive;margin-top:16px;font-size:26px;font-weight:600;color:var(--text-primary);letter-spacing:.5px}
.about-info{margin-top:20px;background:var(--bg-card);border-radius:var(--radius-md);overflow:hidden;border:1px solid var(--divider)}
.about-row{display:flex;align-items:center;justify-content:space-between;padding:16px 18px}
.about-row+.about-row{border-top:1px solid var(--divider)}
.about-label{font-size:14px;color:var(--text-secondary)}
.about-value{font-size:14px;color:var(--text-primary);font-weight:500}

/* ===== Buttons ===== */
.refresh-btn{margin-top:20px;padding:12px 28px;background:transparent;color:var(--accent);border:1px solid var(--accent);border-radius:24px;font-size:14px;cursor:pointer;transition:all var(--transition-fast);font-weight:450;letter-spacing:.3px;font-family:inherit}
.refresh-btn:hover{background:var(--accent-light)}
.refresh-btn:active{transform:scale(.96)}
.refresh-btn.primary{background:var(--accent);color:#FFFFFF;border:none;box-shadow:0 2px 8px var(--accent-glow)}
.refresh-btn.primary:hover{background:var(--accent-hover);box-shadow:0 4px 16px var(--accent-glow)}

/* ===== AI Modal ===== */
.ai-modal{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.3);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;z-index:10000}
.ai-modal.show{display:flex}
.ai-modal.show .ai-modal-content{animation:modalIn .25s cubic-bezier(.25,.1,.25,1)}
@keyframes modalIn{from{opacity:0;transform:scale(.95) translateY(10px)}to{opacity:1;transform:scale(1) translateY(0)}}
.ai-modal-content{background:var(--bg-card);border-radius:var(--radius-lg);width:90%;max-width:420px;max-height:80vh;overflow-y:auto;box-shadow:var(--shadow-lg);border:1px solid var(--divider)}
.ai-modal-header{padding:24px;border-bottom:1px solid var(--divider);font-weight:600;font-size:17px;display:flex;justify-content:space-between;align-items:center;color:var(--text-primary)}
.ai-modal-close{background:none;border:none;font-size:22px;cursor:pointer;color:var(--text-hint);padding:0 8px;transition:color var(--transition-fast);line-height:1}
.ai-modal-close:hover{color:var(--text-primary)}
.ai-modal-body{padding:24px}
.ai-modal-msg-preview{background:var(--bg-secondary);padding:16px;border-radius:var(--radius-sm);margin-bottom:20px;font-size:13px;color:var(--text-secondary);word-break:break-all;max-height:150px;overflow-y:auto;line-height:1.6;border:1px solid var(--divider)}
.ai-modal-label{font-size:13px;color:var(--text-secondary);margin-bottom:10px;display:block;font-weight:500}
.ai-instruction-input{width:100%;padding:14px 16px;border:1px solid var(--divider);border-radius:var(--radius-sm);font-size:14px;outline:none;resize:vertical;font-family:inherit;background:var(--bg-card);color:var(--text-primary);transition:all var(--transition-normal);line-height:1.5}
.ai-instruction-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light)}
.ai-modal-footer{padding:16px 24px;border-top:1px solid var(--divider);display:flex;gap:12px;justify-content:flex-end}
.ai-modal-btn{padding:10px 24px;border-radius:20px;border:none;cursor:pointer;font-size:14px;font-weight:450;transition:all var(--transition-fast);letter-spacing:.3px;font-family:inherit}
.ai-modal-btn:hover{transform:translateY(-1px)}
.ai-modal-btn:active{transform:scale(.95)}
.ai-modal-btn.cancel{background:var(--bg-secondary);color:var(--text-secondary);border:1px solid var(--divider)}
.ai-modal-btn.send{background:var(--accent);color:white;box-shadow:0 2px 8px var(--accent-glow)}
.ai-modal-btn.send:hover{background:var(--accent-hover);box-shadow:0 4px 16px var(--accent-glow)}

/* ===== Nickname Modal ===== */
.nickname-modal{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.3);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;z-index:10002}
.nickname-modal.show{display:flex}
.nickname-modal.show .nickname-modal-content{animation:modalIn .25s cubic-bezier(.25,.1,.25,1)}
.nickname-modal-content{background:var(--bg-card);border-radius:var(--radius-lg);width:90%;max-width:380px;padding:32px;box-shadow:var(--shadow-lg);border:1px solid var(--divider)}
.nickname-modal-title{font-size:18px;font-weight:600;color:var(--text-primary);margin-bottom:12px;text-align:center}
.nickname-modal-userid{font-size:11px;color:var(--text-hint);text-align:center;margin-bottom:20px;word-break:break-all;background:var(--bg-secondary);padding:8px 12px;border-radius:8px}
.nickname-modal-input{width:100%;padding:14px 16px;border:1px solid var(--divider);border-radius:var(--radius-sm);font-size:15px;outline:none;background:var(--bg-card);color:var(--text-primary);margin-bottom:24px;transition:all var(--transition-normal);font-family:inherit}
.nickname-modal-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light)}
.nickname-modal-btns{display:flex;gap:12px}
.nickname-modal-btn{flex:1;padding:12px;border-radius:20px;border:none;cursor:pointer;font-size:14px;font-weight:450;transition:all var(--transition-fast);letter-spacing:.2px;font-family:inherit}
.nickname-modal-btn:hover{transform:translateY(-1px)}
.nickname-modal-btn:active{transform:scale(.95)}
.nickname-modal-btn.cancel{background:var(--bg-secondary);color:var(--text-secondary);border:1px solid var(--divider)}
.nickname-modal-btn.save{background:var(--accent);color:white;box-shadow:0 2px 8px var(--accent-glow)}

/* ===== Add User Modal ===== */
.add-user-modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.3);backdrop-filter:blur(6px);z-index:1000;align-items:center;justify-content:center}
.add-user-modal.show{display:flex}
.add-user-modal.show .add-user-modal-content{animation:modalIn .25s cubic-bezier(.25,.1,.25,1)}
.add-user-modal-content{background:var(--bg-card);border-radius:var(--radius-lg);padding:32px;width:90%;max-width:360px;text-align:center;box-shadow:var(--shadow-lg);border:1px solid var(--divider)}
.add-user-modal-title{font-size:20px;font-weight:600;color:var(--text-primary);margin-bottom:16px}
.add-user-modal-status{font-size:14px;color:var(--text-secondary);margin-bottom:20px;min-height:20px}
.add-user-modal-qr{display:flex;justify-content:center;margin-bottom:20px;min-height:200px;align-items:center}
.add-user-modal-close{margin-top:16px;padding:12px 32px;border-radius:24px;background:var(--bg-secondary);color:var(--text-secondary);border:1px solid var(--divider);cursor:pointer;font-size:14px;font-weight:450;transition:all var(--transition-fast)}
.add-user-modal-close:hover{background:var(--accent-light)}
.add-user-modal-close:active{transform:scale(.95)}
.add-user-modal-spinner{width:36px;height:36px;border:2px solid var(--divider);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;margin:24px auto}

/* ===== Responsive ===== */
@media(max-width:1024px){
  #app.has-sidebar{padding-left:0}
  #sidebar{transform:translateX(-100%);box-shadow:var(--shadow-lg)}
  #sidebar.mobile-open{transform:translateX(0)}
  .sidebar-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.2);z-index:99}
  .sidebar-overlay.show{display:block}
  .chat-list-item{padding:14px 18px}
}

@media(max-width:768px){
  .login-header h1{font-size:34px}.login-header p{font-size:15px}
  .qr-container{padding:36px 28px;max-width:calc(100% - 24px)}.qr-grid{padding:18px;max-width:260px}
  .chat-header{padding:0 48px}.chat-header-title{font-size:16px}
  .messages-area{padding:20px 12px;gap:10px}
  .input-area{padding:10px 12px;padding-bottom:calc(10px + env(safe-area-inset-bottom,0px));gap:8px}
  .message-input{font-size:16px;height:44px}
  .msg-row{max-width:84%}.bubble{padding:12px 16px;font-size:14px}
  .plus-button{width:40px;height:40px;font-size:24px}.send-button{width:40px;height:40px}
  .media-panel-inner{padding:20px 12px;gap:14px}.media-option-icon{width:52px;height:52px;font-size:22px}.media-option-label{font-size:11px}
  .bubble-media-img{max-width:180px;max-height:180px}
  .chat-list-item{padding:14px 16px}.chat-list-item-avatar{width:44px;height:44px;font-size:16px}
  .chat-list-item-name{font-size:14px}.chat-list-item-msg{font-size:12px}
  .chat-back-btn,.chat-header-menu-btn,.chat-list-settings-btn,.chat-list-add-btn{width:34px;height:34px}
}

@media(max-width:480px){
  .login-header h1{font-size:28px}
  .qr-container{padding:28px 20px;border-radius:var(--radius-md)}
  .bubble{font-size:13px;padding:10px 14px;border-radius:20px}
  .bubble.in{border-bottom-left-radius:6px}.bubble.out{border-bottom-right-radius:6px}
  .message-input{height:42px;font-size:15px}.send-button{width:38px;height:38px}
  .refresh-btn{padding:10px 24px;font-size:13px}
  .chat-list-item{padding:12px 14px;gap:10px}.chat-list-item-avatar{width:40px;height:40px;font-size:15px}
  .chat-list-item-name{font-size:13px}.chat-list-item-msg{font-size:11px}
  .nickname-modal-content{padding:24px}
  .messages-area{padding:16px 10px;gap:8px}
  .msg-row{max-width:88%}
}

/* ===== Sidebar Bottom Nav (Mobile) ===== */
@media(max-width:1024px){
  .bottom-nav{display:flex;position:fixed;bottom:0;left:0;right:0;height:56px;background:var(--nav-bg);backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));border-top:1px solid var(--divider);z-index:90;padding-bottom:env(safe-area-inset-bottom,0px);justify-content:space-around;align-items:center}
  .bottom-nav-item{display:flex;flex-direction:column;align-items:center;gap:2px;padding:6px 0;cursor:pointer;color:var(--text-hint);font-size:10px;font-weight:450;transition:color var(--transition-fast);flex:1;text-align:center;-webkit-tap-highlight-color:transparent}
  .bottom-nav-item.active{color:var(--accent)}
  .bottom-nav-item .bn-icon{width:22px;height:22px;display:flex;align-items:center;justify-content:center}
  .chat-list-container,.chat-container{padding-bottom:56px}
}

@media(min-width:1025px){
  .bottom-nav{display:none!important}
}

/* ===== Support dvh ===== */
@supports(height:100dvh){html,body{height:100dvh}#app{height:100dvh}}
body.keyboard-open .chat-container{height:100vh;height:100dvh}
body.keyboard-open .media-panel{display:none!important}
body.keyboard-open .plus-button.active{transform:none;color:var(--text-secondary);background:transparent}
body.keyboard-open #app{height:auto;min-height:100vh;min-height:100dvh}

/* ===== Performance fallback ===== */
@supports not (backdrop-filter:blur(1px)){
  .chat-list-header,.chat-header,.input-area,.media-panel,.settings-nav-header,.toast,.bottom-nav,#sidebar{background:var(--bg-card)!important}
}

/* ===== Sidebar overlay ===== */
#sidebar-overlay{display:none}

/* ===== Persona Cards ===== */
.persona-card{background:var(--bg-card);border:1px solid var(--divider);border-radius:var(--radius-md);padding:16px;margin-bottom:10px;cursor:pointer;transition:all var(--transition-fast)}
.persona-card:hover{box-shadow:var(--shadow-md);transform:translateY(-1px)}
.persona-card-header{display:flex;align-items:center;gap:14px}
.persona-card-avatar{width:44px;height:44px;border-radius:50%;background:var(--accent-light);color:var(--accent);display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:600;flex-shrink:0}
.persona-card-info{flex:1;min-width:0}
.persona-card-name{font-size:15px;font-weight:550;color:var(--text-primary)}
.persona-card-preview{font-size:12px;color:var(--text-hint);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.persona-active-badge{display:inline-block;font-size:10px;font-weight:500;background:var(--accent);color:#fff;padding:1px 8px;border-radius:10px;vertical-align:middle;margin-left:6px}
.persona-card-actions{display:flex;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--divider)}
.persona-btn{font-family:inherit;font-size:13px;padding:6px 16px;border-radius:16px;border:1px solid var(--divider);background:var(--bg-card);color:var(--text-secondary);cursor:pointer;transition:all var(--transition-fast)}
.persona-btn:hover{background:var(--accent-light);color:var(--accent);border-color:var(--accent)}
.persona-btn-sm{font-size:12px;padding:4px 14px}
.persona-btn-del{color:#C45C4A;border-color:rgba(196,92,74,0.3)}
.persona-btn-del:hover{background:rgba(196,92,74,0.08);border-color:#C45C4A;color:#C45C4A}
.persona-create-btn{width:100%;padding:12px;border:2px dashed var(--divider-strong);border-radius:var(--radius-md);background:transparent;color:var(--text-hint);font-size:14px;cursor:pointer;transition:all var(--transition-fast);font-family:inherit;margin-top:8px}
.persona-create-btn:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-light)}

/* ===== Persona Setup ===== */
.persona-mode-group{display:flex;flex-direction:column;gap:10px;margin:16px 0}
.persona-mode-option{display:flex;align-items:center;gap:12px;padding:12px 16px;background:var(--bg-card);border:1px solid var(--divider);border-radius:var(--radius-sm);cursor:pointer;transition:all var(--transition-fast)}
.persona-mode-option:hover{border-color:var(--accent);background:var(--accent-light)}
.persona-mode-option input[type="radio"]{accent-color:var(--accent);width:18px;height:18px;cursor:pointer;flex-shrink:0}
.persona-mode-option label{flex:1;cursor:pointer;color:var(--text-primary);font-size:14px;font-weight:450}
.persona-mode-option .mode-desc{display:block;font-size:11px;color:var(--text-hint);font-weight:350;margin-top:2px}
.persona-section-title{font-size:13px;font-weight:550;color:var(--text-primary);margin:16px 0 8px}
.persona-peruser-list{display:flex;flex-direction:column;gap:8px}
.persona-peruser-row{display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--bg-card);border-radius:var(--radius-sm);border:1px solid var(--divider)}
.persona-peruser-label{font-size:12px;color:var(--text-secondary);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.persona-peruser-select{font-size:13px;padding:6px 10px;border-radius:12px;border:1px solid var(--divider);background:var(--bg-card);color:var(--text-primary);max-width:160px;font-family:inherit;cursor:pointer}
.persona-save-config-btn{width:100%;padding:14px;background:var(--accent);color:white;border:none;border-radius:24px;font-size:15px;font-weight:550;cursor:pointer;margin-top:20px;transition:all var(--transition-fast);box-shadow:0 2px 10px var(--accent-glow);letter-spacing:.5px;font-family:inherit}
.persona-save-config-btn:hover{background:var(--accent-hover);box-shadow:0 4px 18px var(--accent-glow)}
.persona-save-config-btn:active{transform:scale(.97)}

/* ===== Persona Edit Modal ===== */
.pedit-modal{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.3);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;z-index:10005}
.pedit-modal.show{display:flex}
.pedit-modal.show .pedit-modal-content{animation:modalIn .25s cubic-bezier(.25,.1,.25,1)}
.pedit-modal-content{background:var(--bg-card);border-radius:var(--radius-lg);width:92%;max-width:480px;max-height:90vh;overflow-y:auto;box-shadow:var(--shadow-lg);border:1px solid var(--divider)}
.pedit-modal-header{padding:20px 24px;border-bottom:1px solid var(--divider);font-weight:600;font-size:17px;display:flex;justify-content:space-between;align-items:center;color:var(--text-primary);position:sticky;top:0;background:var(--bg-card);z-index:1;border-radius:var(--radius-lg) var(--radius-lg) 0 0}
.pedit-modal-close{background:none;border:none;font-size:22px;cursor:pointer;color:var(--text-hint);padding:0 8px;transition:color var(--transition-fast);line-height:1}
.pedit-modal-close:hover{color:var(--text-primary)}
.pedit-modal-body{padding:20px 24px}
.pedit-field{margin-bottom:16px}
.pedit-field label{display:block;font-size:12px;font-weight:500;color:var(--text-secondary);margin-bottom:6px}
.pedit-field input,.pedit-field textarea{width:100%;padding:10px 14px;border:1px solid var(--divider);border-radius:var(--radius-sm);font-size:14px;outline:none;background:var(--bg-card);color:var(--text-primary);transition:all var(--transition-normal);font-family:inherit;box-sizing:border-box}
.pedit-field input:focus,.pedit-field textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light)}
.pedit-field textarea{min-height:60px;resize:vertical;line-height:1.5}
.pedit-field .field-hint{font-size:11px;color:var(--text-hint);margin-top:4px}
.pedit-modal-footer{display:flex;gap:12px;padding:16px 24px;border-top:1px solid var(--divider)}
.pedit-modal-btn{flex:1;padding:12px;border-radius:20px;border:none;cursor:pointer;font-size:14px;font-weight:450;transition:all var(--transition-fast);font-family:inherit}
.pedit-modal-btn:hover{transform:translateY(-1px)}
.pedit-modal-btn:active{transform:scale(.95)}
.pedit-modal-btn.cancel{background:var(--bg-secondary);color:var(--text-secondary);border:1px solid var(--divider)}
.pedit-modal-btn.save{background:var(--accent);color:white;box-shadow:0 2px 8px var(--accent-glow)}
.pedit-modal-btn.save:hover{background:var(--accent-hover);box-shadow:0 4px 16px var(--accent-glow)}
.pedit-assign-row{display:flex;align-items:center;gap:8px;padding:8px 10px;font-size:13px;color:var(--text-primary);cursor:pointer;border-radius:8px;transition:background var(--transition-fast)}
.pedit-assign-row:hover{background:var(--accent-light)}
.pedit-assign-row input[type="checkbox"]{accent-color:var(--accent);width:16px;height:16px;cursor:pointer;flex-shrink:0}
.pedit-assign-row span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* ===== Neko-chan floating widget ===== */
.neko-wrap{position:fixed;bottom:18px;right:18px;z-index:9999;cursor:pointer;user-select:none;-webkit-tap-highlight-color:transparent;touch-action:none;filter:drop-shadow(0 4px 16px rgba(0,0,0,0.2))}
.neko-svg{width:80px;height:auto;display:block;transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
.neko-wrap:hover .neko-svg{transform:scale(1.12)}
.neko-wrap:active .neko-svg{transform:scale(0.92)}
.neko-msg{position:absolute;top:-36px;right:0;background:rgba(40,35,32,0.92);backdrop-filter:blur(8px);color:#f0e8e0;padding:4px 12px;border-radius:10px;font-size:11px;white-space:nowrap;opacity:0;pointer-events:none;transition:opacity .3s;font-family:"PingFang SC","Noto Sans SC",sans-serif}
.neko-wrap:hover .neko-msg{opacity:1}
.neko-wrap.idle .neko-msg{opacity:0.35}
@keyframes nekoFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
.neko-svg{-webkit-animation:nekoFloat 3s ease-in-out infinite;animation:nekoFloat 3s ease-in-out infinite}
</style>


</head>
<body>
<div id="sidebar-overlay"></div>



<!-- neko-chan floating widget -->
<div class="neko-wrap" id="nekoWrap">
  <div class="neko-msg" id="nekoMsg">にゃ～</div>
  <svg class="neko-svg" id="nekoSvg" viewBox="0 0 120 130" fill="none" xmlns="http://www.w3.org/2000/svg">
    <ellipse cx="60" cy="118" rx="24" ry="10" fill="#f0e6db" opacity="0.3"/>
    <path d="M24 52C24 52 12 12 42 36" fill="#f5e6d3" stroke="#dccfc0" stroke-width="0.8"/>
    <path d="M24 52C24 52 15 22 37 38" fill="#fdd" opacity="0.45"/>
    <path d="M96 52C96 52 108 12 78 36" fill="#f5e6d3" stroke="#dccfc0" stroke-width="0.8"/>
    <path d="M96 52C96 52 105 22 83 38" fill="#fdd" opacity="0.45"/>
    <ellipse cx="60" cy="66" rx="36" ry="32" fill="#f5e6d3"/>
    <path d="M22 50Q30 24 60 22Q90 24 98 50L96 46Q84 26 60 24Q36 26 24 46Z" fill="#4d3728"/>
    <path d="M28 48Q40 30 60 28Q80 30 92 48L90 44Q78 26 60 24Q42 26 30 44Z" fill="#5c4433" opacity="0.5"/>
    <path d="M22 50Q18 62 20 76Q22 82 26 80Q24 66 28 54Z" fill="#4d3728"/>
    <path d="M98 50Q102 62 100 76Q98 82 94 80Q96 66 92 54Z" fill="#4d3728"/>
    <ellipse class="neko-eye" cx="46" cy="64" rx="7.5" ry="8.5" fill="#2a1a0a"/>
    <ellipse cx="48" cy="61" rx="3" ry="3" fill="white" opacity="0.85"/>
    <circle cx="44" cy="66" r="1.5" fill="white" opacity="0.3"/>
    <ellipse class="neko-eye" cx="74" cy="64" rx="7.5" ry="8.5" fill="#2a1a0a"/>
    <ellipse cx="76" cy="61" rx="3" ry="3" fill="white" opacity="0.85"/>
    <circle cx="72" cy="66" r="1.5" fill="white" opacity="0.3"/>
    <path class="neko-blink" d="M39 64Q46 70 53 64" stroke="#2a1a0a" stroke-width="2" fill="none" stroke-linecap="round" opacity="0"/>
    <path class="neko-blink" d="M67 64Q74 70 81 64" stroke="#2a1a0a" stroke-width="2" fill="none" stroke-linecap="round" opacity="0"/>
    <ellipse cx="34" cy="75" rx="7" ry="3.5" fill="#ffb3b3" opacity="0.35"/>
    <ellipse cx="86" cy="75" rx="7" ry="3.5" fill="#ffb3b3" opacity="0.35"/>
    <ellipse cx="60" cy="72" rx="2" ry="1.5" fill="#e8a090"/>
    <path d="M54 76Q60 82 66 76" stroke="#cc7766" stroke-width="1.2" fill="none" stroke-linecap="round"/>
    <line x1="10" y1="68" x2="34" y2="71" stroke="#d4bfb0" stroke-width="0.7" stroke-linecap="round"/>
    <line x1="10" y1="74" x2="34" y2="75" stroke="#d4bfb0" stroke-width="0.7" stroke-linecap="round"/>
    <line x1="12" y1="80" x2="34" y2="79" stroke="#d4bfb0" stroke-width="0.7" stroke-linecap="round"/>
    <line x1="110" y1="68" x2="86" y2="71" stroke="#d4bfb0" stroke-width="0.7" stroke-linecap="round"/>
    <line x1="110" y1="74" x2="86" y2="75" stroke="#d4bfb0" stroke-width="0.7" stroke-linecap="round"/>
    <line x1="108" y1="80" x2="86" y2="79" stroke="#d4bfb0" stroke-width="0.7" stroke-linecap="round"/>
    <ellipse cx="96" cy="120" rx="10" ry="7" fill="#f5e6d3" stroke="#dccfc0" stroke-width="0.5"/>
    <circle cx="90" cy="118" r="1.5" fill="#f5e6d3" stroke="#dccfc0" stroke-width="0.5"/>
    <circle cx="95" cy="117" r="1.5" fill="#f5e6d3" stroke="#dccfc0" stroke-width="0.5"/>
    <circle cx="100" cy="118" r="1.5" fill="#f5e6d3" stroke="#dccfc0" stroke-width="0.5"/>
  </svg>
</div><div id="app">
    <!-- ===== Sidebar (Desktop) ===== -->
    <nav id="sidebar">
        <div class="sidebar-inner">
            <div class="sidebar-brand">
                <div class="sidebar-brand-name">Sioboot</div>
                <div class="sidebar-brand-sub">微信智能助手 · 东方雅韵</div>
            </div>
            <div class="sidebar-divider"></div>
            <div class="sidebar-nav">
                <div class="sidebar-nav-section">
                    <div class="sidebar-nav-label">会话</div>
                    <div class="sidebar-nav-item active" data-action="chat-list" id="sidebar-chat-list">
                        <span class="nav-icon"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg></span>
                        <span>聊天记录</span>
                    </div>
                    <div class="sidebar-nav-item" data-action="new-chat" id="sidebar-new-chat">
                        <span class="nav-icon"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg></span>
                        <span>新建会话</span>
                    </div>
                </div>
                <div class="sidebar-nav-section">
                    <div class="sidebar-nav-label">工作区</div>
                    <div class="sidebar-nav-item" data-action="knowledge" id="sidebar-knowledge">
                        <span class="nav-icon"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg></span>
                        <span>知识库</span>
                        <span class="nav-badge" style="background:var(--text-hint)">soon</span>
                    </div>
                    <div class="sidebar-nav-item" data-action="favorites" id="sidebar-favorites">
                        <span class="nav-icon"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg></span>
                        <span>收藏</span>
                        <span class="nav-badge" style="background:var(--text-hint)">soon</span>
                    </div>
                    <div class="sidebar-nav-item" data-action="workspace" id="sidebar-workspace">
                        <span class="nav-icon"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg></span>
                        <span>工作区</span>
                        <span class="nav-badge" style="background:var(--text-hint)">soon</span>
                    </div>
                </div>
            </div>
            <div class="sidebar-footer">
                <div class="sidebar-nav-item" data-action="settings" id="sidebar-settings" style="margin:0">
                    <span class="nav-icon"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></span>
                    <span>设置</span>
                </div>
                <div class="sidebar-nav-item" data-action="help" id="sidebar-help" style="margin:0">
                    <span class="nav-icon"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>
                    <span>帮助</span>
                </div>
            </div>
        </div>
    </nav>

    <!-- ===== Login Page ===== -->
    <div id="login-page" class="login-container">
        <div class="login-header">
            <h1>Sioboot</h1>
            <p>微信官方接口 · 扫码即连 · 温润相伴</p>
        </div>
        <div class="qr-container">
            <div id="qr-loading" class="loading-spinner"></div>
            <div id="qr-code"></div>
            <div id="status-text" class="status-text">正在获取二维码...</div>
            <div style="display: flex; gap: 10px; justify-content: center; margin-top: 20px;">
                <button id="refresh-btn" class="refresh-btn">刷新状态</button>
                <button id="force-chat-btn" class="refresh-btn primary">进入聊天</button>
            </div>
        </div>
    </div>

    <!-- ===== Chat List Page ===== -->
    <div id="chat-list-page" class="chat-list-container">
        <div class="chat-list-header">
            <button id="chat-list-add-btn" class="chat-list-add-btn" title="添加用户"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
            <span class="chat-list-header-title">Sioboot</span>
            <button id="chat-list-settings-btn" class="chat-list-settings-btn"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></button>
        </div>
        <div id="chat-list-items" class="chat-list-items">
            <div class="chat-list-empty">
                <div class="chat-list-empty-icon">💬</div>
                <div>暂无聊天</div>
            </div>
        </div>
    </div>

    <!-- ===== Chat Page ===== -->
    <div id="chat-page" class="chat-container">
        <div class="chat-header">
            <button id="chat-back-btn" class="chat-back-btn"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg></button>
            <span id="chat-header-title" class="chat-header-title"></span>
            <button id="chat-menu-btn" class="chat-header-menu-btn"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg></button>
        </div>
        <div id="messages-area" class="messages-area">
            <div class="empty-state">
                <div class="empty-state-icon">💬</div>
                <div>点击文本消息可使用 AI 回复<br>点击媒体消息可查看/下载</div>
            </div>
        </div>
        <div class="input-area">
            <button id="plus-btn" class="plus-button"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
            <input type="text" id="message-input" class="message-input" placeholder="输入消息..." />
            <button id="send-btn" class="send-button"><svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
        </div>
        <div id="media-panel" class="media-panel">
            <div class="media-panel-inner">
                <div class="media-option" id="media-photo">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="var(--text-primary)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></div>
                    <div class="media-option-label">相册</div>
                </div>
                <div class="media-option" id="media-camera">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="var(--text-primary)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg></div>
                    <div class="media-option-label">拍摄</div>
                </div>
                <div class="media-option" id="media-video">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="var(--text-primary)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg></div>
                    <div class="media-option-label">视频</div>
                </div>
                <div class="media-option" id="media-file">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="var(--text-primary)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></div>
                    <div class="media-option-label">文件</div>
                </div>
            </div>
        </div>
        <input type="file" id="file-photo" accept="image/*" style="display:none" />
        <input type="file" id="file-camera" accept="image/*" capture="environment" style="display:none" />
        <input type="file" id="file-video" accept="video/*" style="display:none" />
        <input type="file" id="file-video-capture" accept="video/*" capture="environment" style="display:none" />
        <input type="file" id="file-doc" accept="*/*" style="display:none" />
    </div>

    <!-- ===== Bottom Nav (Mobile) ===== -->
    <div class="bottom-nav">
        <div class="bottom-nav-item active" id="bn-chats">
            <span class="bn-icon"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg></span>
            <span>聊天</span>
        </div>
        <div class="bottom-nav-item" id="bn-new-chat">
            <span class="bn-icon"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg></span>
            <span>新建</span>
        </div>
        <div class="bottom-nav-item" id="bn-settings">
            <span class="bn-icon"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></span>
            <span>设置</span>
        </div>
    </div>
</div>

<!-- ===== Settings Panel ===== -->
<div id="settings-panel" class="settings-panel">
    <div id="settings-main" class="settings-page active">
        <div class="settings-nav-header">
            <button class="back-btn" id="settings-back-btn">‹</button>
            <span class="nav-title">设置</span>
        </div>
        <div class="settings-scroll">
            <div class="settings-group">
                <div class="settings-item" id="settings-theme-item">
                    <div class="settings-item-icon" style="background:var(--accent-light);color:var(--accent);">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
                    </div>
                    <div class="settings-item-content">
                        <div class="settings-item-label">深色模式</div>
                    </div>
                    <div class="settings-item-action">
                        <button class="theme-toggle" id="theme-toggle-btn"><div class="theme-toggle-knob"></div></button>
                    </div>
                </div>
            </div>
            <div class="settings-group">
                <div class="settings-item" id="settings-api-item">
                    <div class="settings-item-icon" style="background:rgba(183,134,74,0.1);color:var(--accent);">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1010 10 4 4 0 01-5-5 4 4 0 01-5-5"/><path d="M8.5 2.3A10 10 0 002 11.4"/></svg>
                    </div>
                    <div class="settings-item-content">
                        <div class="settings-item-label">AI 回复设置</div>
                        <div class="settings-item-desc">配置 AI 自动回复参数</div>
                    </div>
                    <div class="settings-item-arrow">›</div>
                </div>
            </div>
            <div class="settings-group">
                <div class="settings-item" id="settings-persona-item">
                    <div class="settings-item-icon" style="background:rgba(183,134,74,0.1);color:var(--accent);">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                    </div>
                    <div class="settings-item-content">
                        <div class="settings-item-label">角色管理</div>
                        <div class="settings-item-desc">创建 AI 角色卡，设定性格与风格</div>
                    </div>
                    <div class="settings-item-arrow">›</div>
                </div>
            </div>
            <div class="settings-group">
                <div class="settings-item" id="settings-about-item">
                    <div class="settings-item-icon" style="background:var(--accent-light);color:var(--accent);">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                    </div>
                    <div class="settings-item-content">
                        <div class="settings-item-label">关于</div>
                        <div class="settings-item-desc">查看作者与版本信息</div>
                    </div>
                    <div class="settings-item-arrow">›</div>
                </div>
            </div>
        </div>
    </div>
    <div id="settings-api" class="settings-page">
        <div class="settings-nav-header">
            <button class="back-btn" id="api-back-btn">‹</button>
            <span class="nav-title">AI 回复设置</span>
        </div>
        <div class="settings-scroll">
            <div class="settings-body">
                <div class="setting-item">
                    <label class="setting-checkbox">
                        <input type="checkbox" id="ai-auto-reply"> 启用 AI 自动回复
                    </label>
                </div>
                <div class="setting-item">
                    <label class="setting-checkbox">
                        <input type="checkbox" id="ai-scheduled-reply"> 启用 AI 定时回复
                    </label>
                </div>
                <div class="setting-item">
                    <label class="setting-label">API URL</label>
                    <input type="text" id="api-url" class="setting-input" placeholder="https://api.openai.com/v1/chat/completions">
                </div>
                <div class="setting-item">
                    <label class="setting-label">API Key</label>
                    <input type="password" id="api-key" class="setting-input" placeholder="sk-...">
                </div>
                <div class="setting-item">
                    <label class="setting-label">模型名称</label>
                    <input type="text" id="model-name" class="setting-input" placeholder="deepseek-chat">
                </div>
                <div class="setting-item">
                    <label class="setting-label">主动发送间隔(秒)</label>
                    <input type="number" id="active-interval" class="setting-input" value="60" min="10" max="3600">
                </div>
                <div class="setting-row">
                    <div class="setting-item">
                        <label class="setting-label">最少字数</label>
                        <input type="number" id="min-words" class="setting-input" value="10" min="5" max="500">
                    </div>
                    <div class="setting-item">
                        <label class="setting-label">最多字数</label>
                        <input type="number" id="max-words" class="setting-input" value="200" min="20" max="1000">
                    </div>
                </div>
                <div class="setting-item">
                    <label class="setting-label">系统提示词</label>
                    <textarea id="system-prompt" class="setting-input" rows="3" placeholder="你是一个微信聊天助手..."></textarea>
                </div>
                <button class="settings-save">保存设置</button>
            </div>
        </div>
    </div>
    <div id="settings-about" class="settings-page">
        <div class="settings-nav-header">
            <button class="back-btn" id="about-back-btn">‹</button>
            <span class="nav-title">关于</span>
        </div>
        <div class="settings-scroll">
            <div class="settings-body">
                <div class="about-logo">
                    <img class="about-logo-img" src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCADIAMgDASIAAhEBAxEB/8QAGwAAAgMBAQEAAAAAAAAAAAAABAUAAgMGAQf/xAA2EAACAQMDAgQEAwkAAwEAAAABAgMABBESITEFQRMiUWEGMnGBFKKRFSNCobHB0eHwM2Lxcv/EABkBAAMBAQEAAAAAAAAAAAAAAAIDBAEABf/EAC0RAAICAgICAgECBAcAAAAAAAABAhEDIRIxBEETIlEycQUUYYEzQpGxwfDx/9oADAMBAAIRAxEAPwD7ABtXoGc172qAHtUFx89xttV0TGa8AwM4qwLE4HFZc6W7VZUDDNe6RirAhQBxRr3MM9C4qEZFXxtVScDbmmEgDcGZEY2qhGTVyDyTUHNT2IcqFxzXjeXc7D1q5x3rKUiQmIMBnmi5UJ1XM3uEUYGD22NL5oFmmaTWThcKPy+uKMvBHb2TsU4Gc1yP7S6gym4iQJbqRq1bE78fWlZGvTCNxj8RnHYpaTM0bnQ27UdHLa3EBh8mwwxhk1y8PVBLcJASVQnIHqff2p7ZW0MUouiG1yJjz8UpMoUaFCMZSTsza/8ABtrIox8x4wM1wN3qUmQHDA7E19EvbS1aPDuDJ6A1xnVrSOWYlMKPalZcil/tqoeK+JC7nkF/FbRa3fMqxaVAOeec1zl/1Z4FOJefMcnJPbj+1D3IkiaRFchidmNLWgaC8Z7+Bp3ThA4C57Z9R7U1AGNyfI5GpaAm4uTJc5JBGBtnFP4beaVdQU+GhGAh2G2dzya1sOmi6k0NHiQ8CMaQuf7D1NNrbp7JcBC6uhABKjAyNv053pwAuzMAIh3R+ixWiS3E4LSSDIyeBWc0kX4loYgTpG5A2/WiOp3y20C28RUYGxBH86RpJqDEMQD3xv8Aal5cgUgCGojZriNY2JJOjGAKlK7O0e4vASWSPjHO3+alcLPU2/zPpwXSoGc17H5j7etRRqxvtV1AGwqmvcRL4zt2r0YA2qvfAqryHOlcZ7n0oGcCcFubLuc+lWyOazXUvlxkVqBitVrnGTzHc1XHqa09q8atIsTBK5HFVIyPSvRjisp7q3t1zNNHGPV2AoLA7hAE9TG6iaXSFJAHYd6y8IPLkZ1g88V7ddSit7hLdRrlZdZGQAi/mJ9KT9a65bdOhaWWcnuFTkip8jgHW41FLajHqEc0q6UkGnk+9JL5DJbiF4sR9wNs4pVF8eWjxeK8UyxFtIl4AptJ17p34VNMwmkOCoj8x39hQMjXdHcautTn0KxzsHXKqQRtg7e//cUxn+Ip1jaNEXcAZPb1+lLLvrnRrryMxjmDFG8Qbhvr2+9YRJbzgiGUsT3BzSm5YxRhkctiN4b5imqXLOex4H1pbeTBVWUyamLEYoB+sxW85t1BIAILnkEelBXvUfF4AwPb/sVvw8gARA+QC6m92sFzOowqF8BiDkDFIusvFBc6bUFoxsGc/NWz+NeDSrhVGxI5/T0pbcWjm4WFm1BPmZT/ACqnEgRUxiMp5dCN+hX1xcXIiSeRA4AkY4/4CusfqDWMOJCs2lT5gdz9a4W2ZYQIl44yKZxSqYiCSq5wWxnJ/vWPs6ExDQjiO8S9nQwnfT5nC9xRkk8SOsWAScZx2pGGNtayeGCEjbJTVgkn1PtWdq1zcxMiOrMVIzsMY3Jo+K+pvIzr4r6GC3dVK62bmpXHJ1AqYon0s2CG3P23qVjQgRPsDdStkAHjLnuaEfqoS4w0ulfTH965pWOrn/VFLGUk8wB27ihx+Q2T7HoRzYFTXudBc9WS3jXTksx+YVWLqgDgyEBScBs81zkjDT522BwBW9oPxGYUZfNvgjj3FT5chP2BhDGo0Z2kEqTRh0OQa1VjqwaR2rTWNuUY5C8Y3IrZepyNIBoynds0xM1AEydsRs11HJYAc14GBzQBvI3jzqA7bHNYydVS2bSf3g7laYfLB/aCMTHqMiB32Ar5r8Q3N1ZdV/EdQcMvi/u1Q5xvkAA7Cuk+Ibm6RYeoWrSNDGpZ0H8J9SK+adf6xNd3Vu7h5lMYcFpMgZzqz6emK5lLkV1G4icexCur/GDX0rh2XbCxqOR7e/34pJJ1uO7DG7mSPBBVM4O3fPb7UjvAJLh2ByCdiaw/BTTMCo2FUpgAAJg8tcRH0XUzcs8EcatE3zK/B9fvR3RL636TNLbSLHGZTlXBOo+gPtXH3Iltmwcq+xBB3+tDC4zIsk+qbBzhmPNH8FDR1A50eo76y0rdVnuI4wIJXBwNsHHf61nFe3fTZiImKNzp7etDp1dZZBClsqoRpIZzv7d6cdM6cnVru3SZZMRrpYo2xA4Oa0MaCONTgD+pY1Tw+s2v4xBpuF/8ijn/AHWMkE4jZSCoZe9OoOhDpji5sJDlF88bnIk+/baqdaRVhSa2+V1DlM/zqJyVYKvR6jSARz9+4hDvaIyBVBxzQBm8Lc9+SatPLqZmL5A496Xu5kk0tnHtVHxAdyUEsYUl6yB/D21bEkVeG5ZWLFSxA8mCQAc80IsTkjGd6Mt4CGBJGOcniiCXMveofE00pcTShVfzaB3Pat5rpbWIxwIELfMe4+9Cq6atSjJAwMV4V1glsk+9N+ATDk/ErFIiZdgS+cr7VKukMYGXOdtt8YqUlsR/ENSan0IOg8xwMV7JLq31EH61js4JAwM7Vm+50KfrvXkEu9IfU9AOBuQOZWO5OOxoiyeaC4V4gNXG9Ut4lVTnGaLjC+bcDbmiyUND1ORz79xotw6yGSQZ7nFCXN4hnPhllVhuAeaEeYBCA2ayRgW3NKUsfqIwADZhkUroAFYgHfB9a9cXErIkbqGZhlnGQBWIfgnitQ4IJLBcetVr8PxkXRimLXKdVSFZoobqZ/BkRg8jysFb0XA2zXzb4g6jA90yWyfu18qjAGw4rvuuQzv0ErbSvNI75kU8e2K+R3Kytc+Hgl2PApniCzZPUWwPGvzC7KFrq4yc4HFPrW0BQnG57UL0y1u7QKWgiII/PvXQwhWT5cZ7VU2XfcNEoTkutWWMyhcqR+lcu6MJCBtX028hV42U25fPviuR6h0O7yXjtGA7aWDHHvTceYEVFZMW7ERIGU6w2l1IIK8g06svip7XqSXUlrHrHlZlcgsO/saSkywykMGwNtxuK9dwUbGM49KaVVtxGxO1g+J7y4tWHhx6bgEBoz8pzg8076b0g9chgt3nNuyKS7Y7Dt/SvnFpcG3W3i1LHE8p1FuBkY4ru/h+/tFuLeMuxOSpbgMw7ZqDOGQWguo/HT2GNRf13oknROpNauweMgNHIvDKf+4pSUAJOMN7V0/xZfS9Q6giIjukR8KMruDwP1zXPX0EvT7uSCYo0sbYOk5Ge4/tVStyQcu6kbCmNdTzXHGDsCwGwI5+tSPW7ZPJ9/8AsVmoaU62yDniug6HN06NJbe7sjPPKMJJrACYHG/BzXM/FSaupqgk1FkUZPlQV6xCd81nNGbe6eHUNtyVbUMc896gV5WAwcE+lNV2b7eoXBRr3NEJeULny85qVpHEFcLkffg1KQ/IncpTiBOukumkHlGAK2QqiZOdR+9DC2kxuMDjNWRH8QeGpKgYz6Us4UoAaEWC12YxELNbNKH0lRkgjGaz8Rgux2xxivNPhxEuWds+vNeQuWikBVUJ7tSURWJ/AjSxEp4upwADWy8/Ws9Bxk1G8RV1bY425pObxwGtdR6ZTU1ExBwNzmi7eN7mZI0AyTuTwKBt2D5B152JGKe9PeG2fKRt4hU/NuRUzKoO5rdalOseB0XolxNKweQx4GRjLe1fGbBGuesq6kAqrMT6f9mvo3xJBe9bjnRceHH8zHhcDO1cJ8MQg9RvC2CViAA+rVb4gXiSIDKRQMtL0qR18tzL4urUZAP5c04sZJbaLRJIZGAxqI5NF+Go559KqYFMZcOoGacGU9mMKEHUxuXmkTKMRk749KUtD1SG6MkNyJIs/wDjc74p9EmQVIwfUHINafhVxnvWCh1N4k9xB1OxS5tzMYgsv8W1cTNGVkZACMHivpV0mmM57VwHUExeyOBgZ296dhPqT519ysQE0KxyJkV0Xw2k/wC1FkRVMasp0uMj6/Uc1zcUpDADBB3PtXT/AA3Ctx1VIXYhWBxg4OcdvemZv8ImIQDmB3O065b9Ou/ht+poGt7gYP7t8Zc+oHY81wLYMnmGog5ck811fU2uFkNqkCeEi5iQxhmOOT7mlFj0pGN1G9vJLPoUxkRHCknB5PuKl8YHibN3uDkWz1E4llmZjwgO2njH1rpvhz9lzKsE9tI8y58ZsFsg8YxwBQsHT53delraq9wX1DC5ZMc8dqexW3U+lItk9nHEjp4jSJgsd+CR3/1W5m5Y6XR/ev8Av7TE0bMRdcTpn7TYWJKqM+IoG2r2qsYy6ZOMcegpj0zpsHULa5urmJ1dZNPiIpxj19KKFhYWUYjjj1Sg69b7nGf+2rD5Ix1iFkiNGEsOdgAwRbdAmw3B2yKlGQ2E7SJMAfC4AbuO+3apUuTyt7Nxi4dR/Mq4O3lAydqlpBHjLQlwRuCSPvTKeGJULYxvtpG9S1tp1mYs+BjbGxzSVzsLP/n+kaVUioAlphsA8b5Pb2rWO2kFwECI4zvrwMCj7oKbdIivhHPzqdzVMKluqAb4xzvmgOUjZPcELeoC9uGJI0r6qB/SvUg3YnPFbxpkY78ZzvRTQnyKWywGwPOKUMjnYhkAagEcYQbc8HFR5it4kQfHiKUJ/Smcdu8T6wBk8kilXUbXxOo2mkHLFskdj2NcGs28NKJoT34lvYbHo8kESAEpgnsM85r5J8PXSwdeRZWwswMZOe54/nXffFN0G+GZNQ0zrOIpR79/sRivlrps7jIZe49c816XiC0N+4DjjVT6DftLYxNOkJnA+YA4Kit4o7l0WRbcMp4KuMUB8P8AWF6xZNFMR+JiXDj86/m/zRP4F4yRBK6LngEij48RRjFcMblp7oWql7iF4wNydq2tpTcwiREkVDuPEXSarB0+KNg7/vH5y1EySpGp3FC/UIEXqA9Q0rbOzdhXz+9v7QxuoBaXJ7bfrXRfEPVswvFGck8n0FcFMQzEgc8e9U4EsWZNnycTqEwOT5vXY016V1AwXMb5IaNgy452pNFqSLBPJou0UMpfjT/OqWOiJKosifZ4fC6nYpdRMN1yGX5lJ5xVYenKkryzMzq4xjWRsfX1rmfgjqfgTeBKSY5G0j0BP/Cu+WFZj4RYLg4NeHl54W4g6ljAMOVTn+np+E6kbizGhiCAxXIUd8j9KPvfGvHgSeaQlCDoUAKexz6U3hsUjDaSCDkknj61SGweSTWjNpB2z2xWHySdDqJXGK3EtivULG3a3FyfAPlCEZ0jPH6VJIYmkJEfmxucc01ntiJZX2AxgDG4rNIGZQzKcYoG8lmaz1HpjXj/AFgKRtqUnUAR8vY1KOMTSOukYx3qUl8gJsCGq0KMbRg/xAbDdvWo8+JAqqxYkgACg2uP3PmbAPPvVxP4YZvEIU4JJOwpnMVRia3L3MqGEz3DiONOS3Y9qp02V7uUvPaFUXARw4YMaqZo7lWUMrxEFWKnNRMiAJAwQ6iflyP+4rlKk0ZhBEaLbKJmJjG57b1mfDaYGL51PmLCs1u5IY1KIrnOGC77fStLS4TMkjxkOx7+lEWFUNTqPZhbKixgkjUR2oaO1Uzq7MMLuAfWsw6KQApz3Oau02xYHYbEZrLXszgCNCcR8eWRmmIt1Yl2UOg/iIUnP1xXDXNpDFAXjIIt286kYIYHBFfZrqKC6lieUEeG4cADk1wvWPg64vzdXdk2XEvlhP5aow5QPqTUcCOM4Tp73XT74XUSlWiXJBGzKexrsOmfEFp1J/DiSRZgNRRh27010DfC7dY6bDdCL8JcvAIZIXXynTt27d65yx+BupdI6i87MhW3JJGfnTHIqg5VcG9EQQQKqM5bh/4UI9zS+5WSUHW+3oKYFdYHpQHUpZIISYYfE7ADnNSK7salVKBc4frLk3JRQQucAetJXTzHUMY7CmXUhP8Aij4wxJq7cA0KbabkofWvZx6UTy8tliYMZPUb+lObILJbAjfYKNvf/dJ5IWDb5Zjv5RsKe9HsbmaeGERuCw2yMbe1dlICzsItp13wx01ZpRHIjoC2dQHsCK+mxqiRrnBbTyeaTdL6ZLAYy2hVQDyge3/ymlwGEeYxlhvgmvAz5C+xLGqwJJ3CwjRuzfNvxXlvcSwwFV3UfxcnevAzbIEByMkjt60NdySRxBYFJbOTk6cj2NLxIWIBNQD1U1ncy5Vxp1MBkGtg6qxU5wNhtVI8akM+M6DkDgH2qMNQCruAe/empjINg7NGcWnrFgmhVXJ+Y1KutyrWo0qcnnUuCKlbnRS1Ezlc1AWkjd0yM6dxS7qVu7hruK9eAIu68qaap02dxGwKD/wDRoKXMTpaSQafEYhtG6/X/AFQKjqRYmq3HamJbePqZdLuOMFWBBCtz7kf3p/DI0MTkjfBO/wBN6zjSKOMQwgIoOCorUxGYgDzYO+/ahd+R1GOxNc5LeWcxDxAWz/F/3NHxXCgBj5m+XJ9aFhjBfRK4QE4BParX0K2rx+E6upOdjkg+4rkF7MHTNUYi/iKqI1JY+grF7lFjY6Rvzjil8dw2QXUhmycKO1apbxxRgSNhCdvN60LmCyEdRjaIzx/KNucnYUS8PhgOoBDb5FAxSMi6Q+lCO1Sa6LHQjnQBjzb4rfpx33AprhUcwIwdsEkAf1rR1EiMrb6gVIoKCWSaTQhGSe/ajSUtondVNzMNgo4LdhRYwzzDqcBNGbeR4mGCjFT9jQ0gyM0y6sso6hceIVaUtl9PGe9KX8c5VY8+5NXLhJ36j/kiq96db3Dq0qZKnI7V4tir/JGMD0FMGtWUB5XBJPygVdRg4wAO+KuTGQNyV8wuhFa9LX8Qk0QEc0balYetfSOj/heoWv4n8MiXSqElyBkfT2NciqK0gOR75plY301jOJIQDjZlPcUXkeJ82PXcUM3EzqiCGI0YwNzjmpcqPKsQ1jTu/oe1CQ9SivYD4OpJF+aOsxdSAsNRGGzjNeLXxFkZdx3IEAgw2W48GESrGGwACDkbfasmYzwKJTEhc7KrZGPXehpLvw7PGSTgk78+1CwaZJSf4O2dq45BVVCrVmHjBR8AkDyg/wCK1gmjDKApOftS+KeRFeFgpUsTjuKze4WNy7sAB3PagFXqFTN0IxuZwWbSPmPc8VKVvdRsgyRjYhhUrmtt1DRGrqbx3Ygl1BmZgcaSeBWEhR5/EwBK2W1Ek71lJGJdNyzMi40njBBIqk7PJLGqp586cjmjd2auRmKijoRl0iRXum8aJY9QOzHGrtkUyvjBFdkQ6R5R8vFZJ0cyW6+PE5kj8ynON88YpavVLcXkkc0UyFdiGXB/3WridgQouA7hmDT0yNKzR5wwOPWiJLpUiS3jzl9jqHelsttJa3WQ5aOTzo4OxHaqm4drV3bzHOTml2wHCGVBsiGs6I4TJ24I4q8iRzokZbONwV2pa88lzEPCRlMbebI2omzWVjJ4XmKZXPYGllDU1egy9xiVdVUjUY1GCc5rJZVPytsdjVYJ5PBKSadR2On1rKC2WF5mJO57nj6UB4gf1hjibszWe8a3t9MRCs3fuPesXuyiW9orkOY3nkw24ONv61rewQwxwuw8xBZv7UjsVMz3F47lnc6F+lev4+NDjAk7HdiSY5XSM55JPc1iFYDfP1oiUadzQ4kyW1c9varCFvcUWIFCeuVBAIzihHAZ8EnHGFrR2JYgfSqgYIFMGcMaXUwYq/VPdBSPYYPcc1sjPgNkHNYM2hidWBWtpOkpKfM3BxTUK3RMW4rqHWUoScNkKx2Oe1NZ0GdS8MACQaRSSBXC6cZGM+9OLKZZYkCjUwXDD0rzP4otgZB2NH/iF443x/vMOoCSaOOGJwkJ+Yg4b2raMCCNY9RYrwxrwtiZB4RLBgMZ39/tU6ks77W4YknOMcivLIJoXKEIFkibxRxx+aUqHyWVdXb/ABSe6OqWTxXUD8o9KIvMT3BcWkfjoAAdOdXb6UsuYJJbtZJl82d9+KtxlVXctQULBlPPCQzqVTAwD6VKNdUfQJV1AkhSOfualLOVY35R7hMs8dwhRsaSPMPUVhZyg6VZjqBwCTnIoITIc4XSCcD2rElreJZhJ8r5G3eh4AieRzoidfb9dPT4HaVmlU5OWOcGqWV+OvTKLiRERxjIX9Nq5uwxKzm4c+HIckD/ABT+3uILeARWxjRc5AWLBTtksefam48R4gmE5++ppfdMa2uliEh8EkaZCfLRKfDki27oZVlVvyHtSKN7xZfNcvIPQ9veust+qA2sWvCng4bv9KM+Nyu+53Iic9fBenyeAm8gGnSWwWHc0PJ0yW2mlu42Ihk3YFid+2Mduf1orqiR3l9HcRhnxqDYG59K2/HS+AsLAPpXDK2OR9Klal/THgnjawS0Ky3CT6TEDyBnFFHUG0J8xbk996pG0bIE1GM42zxRfS4Te3TAriNdyfSkAFmGp1CruC9WjZrLSM63BZcg70ot2ENuqLgYFMuszk9RYK2UQYUA8ClEz9thscivew4/jTUkbJ7MtL55AS2R7cCsGGFyKvCjNKqndRvmvbkouQveiyAjGWP7Qcf2aDptk+pqwNVDbbelXB8uMZqVb42vcs17nmFIyd81RgY3UoMFewOM15cmRYcxAlicYHaspYskyGUggZO9Mwu3K/UVkqq9w1mEiFSfPjIo3o1xiYZ2J8rUoBW3zI8jHOMhq2hmj8UOkm/OPWt8nIaJB3Bw4yxqp1Mmr8SjHBCkjahbm6ldgV0qVOlwx0n2pabqPw/Em1rhtlWsLiXxI2kGcb4BNeTjyFX51v8ArL/5PlomNRE5RjM23OBWMlvLPOiojc4O2xGN/wC1C2F0zRBGcnGw9qdxytYza3DPG6jfHB/3TKORyxicqHF9YBcWbQOm7AINhjapTCecSEl3AHpn+VSsfEL7mo5I3OSlmDOTGmCRn70QkZns2hlYBiwIPpSz8RqmV4wQuwYGtJr54zrAJfbBNWYPFyZtLPMbIq7MNiaS36g+ssIgMq3YH0/rWln1RRd6ViLBoyCW2H1qyqbmxSQxkFjz2rFZYba5hMr6RoIyexpeRDjfj/tHcuYBjC2uBLNqlkSPVllzt5fpRXjhbgLGcgbq+fvSyZHurW1YYi8KDBB9RsfvXltdrbwhS3iKcZVfbb9a7+YyfmEEHG4xkuB47Lqzk6mAODj3oGOV26gsgDFCcnJ4xQwm1XXkTV5sagO1FwQq1w8Ds0c2QACMZ9qRZW4/GSn6vcYyyQtbqIz5h/Djmujh8DpvSQC6hnA1NxnPeuR1PDMi6BpBC4HeiepT/ibpHLEoFC49u9M8XGMmSBlb62Jg4Wa7kMSAJuQPQUvmBaVfQ84o8SiGB9vO+30FCp5suRueBXsoAWppG2xLoRHCxb0oKfUZskbetFXDBId/rQMDa0aRySScY+lT+UxbQPUdiAB3PFlRWwzBRnG5xvRagLu3ell3bXBl8WHLA8oSKOR/3eBsVwCp5FLT8mN5E6M3UCTIHHtQV8hDoh3GQcCry3Zt08oy3YUIzStPAW3c5ZgDRllIoQGmE8zSMQd96rFPFGGLg5A23oi8QqPKox60A9vJIpJQ6e+ajdTy+09fAynHrUIbqrzSI74IXYKN6Le/aRAEQADlV4pSIo7QIWO+clAe1dYOmpdwwCGVRHp3wNyfpScoVKMxPJQvx/EDspuQiEudyeBzTp5ZniRBIwCkE6tz9BS+xS2t7mWMyMjpnJYY+49azu+oNPLOlnkBBgtj5f8AftSuLFvrI8/JhXP1hvj+NrIGCrYORUrC3DiMb68jk1KWym4pWaokFu1u6o4JJXUn07/oauYvEI0gMD2Na3MTTR4VyrLvGedJH9jWFqJY0CyDDYyQO3tXqfzLKgAP9pI2MBoQeoS2iNHIPLrGMniucTqE9wkhuEVpFfOkjge3rTq8tvxdtKmrSzLt7nsKR2du+plZSpZdJJHyntTPGXHxZmhAkzorTqJu7BlcASeIUITspGCd/tXsUBt0dmbyq2ACd2Hek/TS0V1KhiIJXylST/8Aa6W4sB+zFuDcI+oDVpxv/PakZcX2PHqP3xIEAl6m0TRpqG2QnuD2pql0ZZBNKP3qKEP/ALYHP1/xXOT2glEeqTASQYxzg10tpbI0Qcgnw9tR7j3pD9agKb/eDx3jeOxkyXLAgnvTOYKEV8HfOPQ0E/T3uJA8eNCckU3uIh+xkcfn1D6cVmIlfsOjqNHEqB7ie5b92d+KshBQEHtVbhQwIB5FVgYGNc9gK9U5OJu+4gCxUrPlvKKwij0KoI77fStysskoWKNnZjgADNGN0y9tYhcPEoVPmyRtUTOGO40CoHpxgnb2oWbSW1F9LgbN6VvLcF2LOf8AVJ+oTt4RRVIGd27U9bocoQXkaEIa9jWMyOQZMYwq7ihYp5Jpw6IVAXG+9DwgNH5Pue9FRS+UAjYbADbNBdmpzhUWj3Cp5dCZOAuPmIodFklYuFYR9gawL+POiSOdA524psJI5QUUEYFaoDNRk4cmzcGuenxTQvP4wR448xr+YjfFP+gXNt+zFus7uvDdh6Z7Vzk86RhkUBmIPJPlFD9FjuRJLYzMxVFEgTOB7D65/pSvJxc+QJ6MzG9MKEcXsks1wzMUZiCiaOV981pZ2zpbLCyBFA333YmtIbMJbKj7sTqJH5vWjMYBzUrPrivUcEo2e5lJIsRUAbdsVKzI1/SpQE1H/UaMFhLb6vlXuBQx8jtq+2alSmyR+p5IFCDIJVhv+tDkgELGpfS2Wc8/Q/pUqUwdQF7qDW+qe7kZFzjB1E4z6ijWMwaSGTJRvNGVGxHp9alStYxzbqZxWwkSSUMcoMketObG7ea10oyrIDgBhsalSkZNrG4jbC/xCreV4laIHJfY4pre4/ZoCZ0KQBUqVyH6L+8PIAGofiI23GPSs4GCyhSv8WBnvUqVdmNDXoScdQ2G+FtI0mRrJwFVcavr7e1Luo9Uuru4jWZyVzuoOAo+lSpSwiqbE5iag0sZnjBikK75JApXdREFY2L+U6QAN2qVKbepRhPqbiBYYcKgQHfHesJVEZVlDZJ4qVKSDsybPNLCHVMXYDbPNEsSZ2RCTLjf2qVK1WIaJ/yykNo5BmkBAG4GO/rW17i3uLXqKRnSg0Pq5xznapUpYctkoyv4lXx+Y7j1CJVVl3BG2KGvbg24UaScntUqVOo+1RuABnFy8BMsQIUg8EVKlChbuC4AYz//2Q==" alt="作者头像" />
                    <div class="about-logo-name">Sioboot</div>
                </div>
                <div class="about-info">
                    <div class="about-row">
                        <div class="about-label">作者</div>
                        <div class="about-value" id="about-author">加载中...</div>
                    </div>
                    <div class="about-row">
                        <div class="about-label">版本号</div>
                        <div class="about-value" id="about-version">加载中...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- ===== Settings: 角色管理 ===== -->
    <div id="settings-persona" class="settings-page">
        <div class="settings-nav-header">
            <button class="back-btn" id="persona-back-btn">‹</button>
            <span class="nav-title">角色管理</span>
        </div>
        <div class="settings-scroll">
            <div class="settings-body">
                <div class="setting-item">
                    <label class="setting-label" style="font-size:14px;font-weight:550">角色列表</label>
                </div>
                <div id="persona-list-items"></div>
                <button class="persona-create-btn" id="persona-create-btn">+ 创建新角色</button>

                <div style="margin-top:24px;padding-top:20px;border-top:1px solid var(--divider)">
                    <div class="setting-item" style="margin-bottom:12px">
                        <label class="setting-label" style="font-size:14px;font-weight:550">角色应用模式</label>
                    </div>
                    <div class="persona-mode-group">
                        <div class="persona-mode-option">
                            <input type="radio" name="persona-mode" id="pmode-none" value="none">
                            <label for="pmode-none">
                                不启用角色
                                <span class="mode-desc">AI 使用系统提示词回复，不加载角色</span>
                            </label>
                        </div>
                        <div class="persona-mode-option">
                            <input type="radio" name="persona-mode" id="pmode-global" value="global">
                            <label for="pmode-global">
                                全局角色
                                <span class="mode-desc">所有用户共用同一个角色卡</span>
                            </label>
                        </div>
                        <div class="persona-mode-option">
                            <input type="radio" name="persona-mode" id="pmode-peruser" value="per_user">
                            <label for="pmode-peruser">
                                逐用户指定
                                <span class="mode-desc">为每个用户单独指定角色卡</span>
                            </label>
                        </div>
                    </div>

                    <div id="persona-mode-settings" style="display:none">
                        <div id="persona-global-section" style="display:none">
                            <div class="persona-section-title">选择全局角色</div>
                            <select id="persona-global-select" class="persona-peruser-select" style="width:100%;max-width:none;padding:10px 14px"></select>
                        </div>

                        <div id="persona-peruser-section" style="display:none">
                            <div class="persona-section-title">为用户指定角色</div>
                            <div class="persona-peruser-list" id="persona-peruser-list"></div>
                        </div>
                    </div>

                    <button class="persona-save-config-btn" id="persona-save-config-btn">保存角色配置</button>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- ===== Modals ===== -->
<div id="ai-modal" class="ai-modal">
    <div class="ai-modal-content">
        <div class="ai-modal-header">
            <span>AI 回复助手</span>
            <button class="ai-modal-close" id="ai-modal-close">×</button>
        </div>
        <div class="ai-modal-body">
            <div class="ai-modal-label">原消息：</div>
            <div class="ai-modal-msg-preview" id="ai-modal-msg-preview"></div>
            <label class="ai-modal-label">回复要求（可选）：</label>
            <textarea id="ai-instruction" class="ai-instruction-input" rows="3" placeholder="例如：帮我反驳他、用温和的语气回复、加个表情包、怼回去..."></textarea>
        </div>
        <div class="ai-modal-footer">
            <button class="ai-modal-btn cancel" id="ai-modal-cancel">取消</button>
            <button class="ai-modal-btn send" id="ai-modal-send">发送 AI 回复</button>
        </div>
    </div>
</div>
<div id="toast" class="toast"></div>
<div id="media-upload-progress" class="media-upload-progress">
    <div class="media-upload-box">
        <div class="media-upload-spinner"></div>
        <div class="media-upload-text">正在发送...</div>
    </div>
</div>
<div id="nickname-modal" class="nickname-modal">
    <div class="nickname-modal-content">
        <div class="nickname-modal-title">设置备注名</div>
        <div id="nickname-modal-userid" class="nickname-modal-userid"></div>
        <input type="text" id="nickname-input" class="nickname-modal-input" placeholder="输入备注名..." />
        <div class="nickname-modal-btns">
            <button id="nickname-cancel-btn" class="nickname-modal-btn cancel">取消</button>
            <button id="nickname-save-btn" class="nickname-modal-btn save">保存</button>
        </div>
    </div>
</div>
<div id="add-user-modal" class="add-user-modal">
    <div class="add-user-modal-content">
        <div class="add-user-modal-title">添加新用户</div>
        <div class="add-user-modal-status" id="add-user-status">正在生成二维码...</div>
        <div class="add-user-modal-qr" id="add-user-qr"></div>
        <button class="add-user-modal-close" id="add-user-close-btn">关闭</button>
    </div>
</div>

<!-- ===== Persona Edit Modal ===== -->
<div id="persona-edit-modal" class="pedit-modal">
    <div class="pedit-modal-content">
        <div class="pedit-modal-header">
            <span id="pedit-modal-title">新建角色</span>
            <button class="pedit-modal-close" id="pedit-modal-close">×</button>
        </div>
        <div class="pedit-modal-body">
            <div class="pedit-field">
                <label>角色名称 *</label>
                <input type="text" id="pedit-name" placeholder="例如：温瑶" />
            </div>
            <div class="pedit-field">
                <label>性格特征</label>
                <textarea id="pedit-personality" placeholder="温柔体贴，善解人意，有点小傲娇..."></textarea>
                <div class="field-hint">描述角色的核心性格特点</div>
            </div>
            <div class="pedit-field">
                <label>语言风格</label>
                <textarea id="pedit-language" placeholder="语气柔和，喜欢用~结尾，偶尔撒娇..."></textarea>
                <div class="field-hint">说话方式、口头禅、语气习惯</div>
            </div>
            <div class="pedit-field">
                <label>背景设定</label>
                <textarea id="pedit-background" placeholder="23岁，大学刚毕业，在一家咖啡店工作..."></textarea>
                <div class="field-hint">年龄、职业、生活背景等</div>
            </div>
            <div class="pedit-field">
                <label>行为习惯</label>
                <textarea id="pedit-behavior" placeholder="关心对方日常，会主动分享生活中的小事..."></textarea>
                <div class="field-hint">做事风格、互动模式</div>
            </div>
            <div class="pedit-field">
                <label>其他设定</label>
                <textarea id="pedit-other" placeholder="喜欢猫，怕黑，下雨天心情会不好..."></textarea>
                <div class="field-hint">爱好、禁忌、特殊设定等</div>
            </div>
            <div class="pedit-field" id="pedit-user-assign-section" style="display:none">
                <label>指定使用此角色的用户</label>
                <div id="pedit-user-assign-list" class="persona-peruser-list" style="max-height:200px;overflow-y:auto"></div>
                <div class="field-hint">勾选的用户将在「逐用户指定」模式下使用此角色</div>
            </div>
        </div>
        <div class="pedit-modal-footer">
            <button class="pedit-modal-btn cancel" id="pedit-cancel-btn">取消</button>
            <button class="pedit-modal-btn save" id="pedit-save-btn">保存角色</button>
        </div>
    </div>
</div>

<script>
''' + bot._generate_wasm_wrapper(session_token) + '''

// ── neko-chan idle animation ──
(function(){
var W=document.getElementById('nekoWrap'),S=document.getElementById('nekoSvg'),M=document.getElementById('nekoMsg'),blinkEls=S.querySelectorAll('.neko-blink'),eyeEls=S.querySelectorAll('.neko-eye'),hasG=typeof gsap!=='undefined',msgs=['\u306b\u3083\uff5e','\u308b\u306d\u3053\u3060\u3063\u3066\u3088\uff5e','\u306a\u3067\u306a\u3067\uff5e','\u304a\u306f\u3088\u3046\uff5e','\u3084\u3063\u3068\u304a\u6c17\u3065\u304d\u3067\u3059\u306d\uff5e'],mi=0;
setInterval(function(){
blinkEls.forEach(function(e){e.style.opacity='1'});eyeEls.forEach(function(e){e.style.opacity='0'});
setTimeout(function(){blinkEls.forEach(function(e){e.style.opacity='0'});eyeEls.forEach(function(e){e.style.opacity='1'})},150);
},3000+Math.random()*2000);
if(hasG){
var ears=S.querySelectorAll('path:nth-child(2),path:nth-child(4)');
W.addEventListener('mouseenter',function(){
gsap.to(ears,{rotation:-3,transformOrigin:'50% 80%',duration:.15,yoyo:true,repeat:3,ease:'power1.inOut'});
gsap.to(S,{scale:1.08,duration:.3,ease:'back.out(2)'});
M.textContent=msgs[mi];mi=(mi+1)%msgs.length;
});
W.addEventListener('mouseleave',function(){gsap.to(S,{scale:1,duration:.3,ease:'power2.out'})});
}
W.addEventListener('click',function(){
if(hasG){gsap.timeline().to(S,{scale:1.25,duration:.15,ease:'power2.out'}).to(S,{scale:0.92,duration:.1,ease:'power1.in'}).to(S,{scale:1,duration:.2,ease:'elastic.out(1,0.4)'})}
else{var i=0;var bounce=setInterval(function(){S.style.transform='scale('+(1+0.15*Math.sin(i++*1.5))+')';if(i>6){clearInterval(bounce);S.style.transform=''}},50)}
M.textContent='\u306b\u3083\uff5e\u2661';
setTimeout(function(){M.textContent=msgs[0]},2000);
});
})();
</script>
</body>
</html>'''
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Set-Cookie', 'session_token=' + session_token + '; Path=/; SameSite=Lax')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))



            def _serve_status(self):
                status = {
                    'logged_in': bot.token is not None,
                    'login_done': bot._login_done,
                    'current_user': bot._current_user,
                    'bot_id': bot.bot_id,
                    'user_count': len(bot._context_tokens),
                    'users': list(bot._context_tokens.keys()),
                    'message_count': len(bot._messages)
                }
                self._send_json(status)
            
            def _serve_qrcode(self):
                if bot._login_done and bot.token:
                    self._send_json({
                        'error': 'already_logged_in',
                        'message': '已连接',
                        'login_done': True,
                        'redirect_to_chat': True
                    })
                    return
                
                if not bot._qrcode_matrix:
                    self._send_json({'error': 'no_qrcode', 'message': '正在获取二维码...'})
                    return
                
                qr_data = {
                    'matrix': bot._qrcode_matrix,
                    'qrcode_key': bot._qrcode_key,
                    'login_done': bot._login_done
                }
                self._send_json(qr_data)
            
            def _serve_messages(self):
                params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                since = params.get('since', [None])[0]
                user_filter = params.get('user', [None])[0]
                
                messages = []
                for msg in bot._messages:
                    if since and msg.get('id', 0) <= int(since):
                        continue
                    if user_filter:
                        if msg.get('type') == 'in' and msg.get('from') != user_filter:
                            continue
                        if msg.get('type') == 'out' and msg.get('to') != user_filter:
                            continue
                    msg_copy = dict(msg)
                    bot._enrich_msg_with_cache_id(msg_copy)
                    messages.append(msg_copy)
                
                self._send_json({
                    'messages': messages,
                    'current_user': bot._current_user
                })
            
            def _serve_users(self):
                users = []
                for uid in bot._context_tokens:
                    users.append(uid)
                self._send_json({'users': users, 'current_user': bot._current_user})
            
            def _serve_ai_config(self):
                safe_config = {
                    "auto_reply": bot.ai_config.get("auto_reply"),
                    "scheduled_reply": bot.ai_config.get("scheduled_reply"),
                    "api_url": bot.ai_config.get("api_url", ""),
                    "api_key": bot.ai_config.get("api_key", ""),
                    "active_interval": bot.ai_config.get("active_interval"),
                    "model": bot.ai_config.get("model"),
                    "min_words": bot.ai_config.get("min_words"),
                    "max_words": bot.ai_config.get("max_words"),
                    "system_prompt": bot.ai_config.get("system_prompt")
                }
                self._send_json(safe_config)

            def _serve_about(self):
                self._send_json({
                    "version": bot.SCRIPT_VERSION,
                    "author": bot.AUTHOR_NAME
                })
            
            def _serve_cached_media(self, cache_key):
                try:
                    if not cache_key or not all(c in '0123456789abcdef' for c in cache_key.lower()):
                        self.send_error(400)
                        return
                    
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    user_param = params.get('user', [None])[0]
                    
                    cached = None
                    if user_param:
                        cached = bot._get_user_cached_media(user_param, cache_key)
                    if not cached:
                        cached = bot._get_cached_media(cache_key)
                    
                    if not cached:
                        self.send_error(404)
                        return
                    media_data, mime, filename = cached
                    is_download = params.get('download', [''])[0] == '1'
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(media_data)))
                    self.send_header('Cache-Control', 'public, max-age=31536000')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    if filename:
                        disposition = 'attachment' if is_download else 'inline'
                        self.send_header('Content-Disposition', disposition + '; filename="' + filename + '"')
                    self.end_headers()
                    self.wfile.write(media_data)
                except BrokenPipeError:
                    pass
                except Exception as e:
                    print(f"[WEB] 缓存媒体服务异常: {e}")

            def _handle_save_ai_config(self, data):
                try:
                    print(f"[WEB] 收到 AI 配置保存请求: auto_reply={data.get('auto_reply')}, scheduled_reply={data.get('scheduled_reply')}, api_url={data.get('api_url', '')[:50]}, api_key={'已设置' if data.get('api_key') else '未设置'}")
                    
                    bot.ai_config["auto_reply"] = data.get("auto_reply", False)
                    bot.ai_config["scheduled_reply"] = data.get("scheduled_reply", False)
                    bot.ai_config["api_url"] = data.get("api_url", "")
                    bot.ai_config["api_key"] = data.get("api_key", "")
                    bot.ai_config["model"] = data.get("model", "deepseek-chat")
                    bot.ai_config["active_interval"] = data.get("active_interval", 60)
                    bot.ai_config["min_words"] = data.get("min_words", 10)
                    bot.ai_config["max_words"] = data.get("max_words", 200)
                    bot.ai_config["system_prompt"] = data.get("system_prompt", "")
                    
                    bot._save_ai_config()
                    
                    if data.get('scheduled_reply'):
                        for user_id in bot._context_tokens.keys():
                            bot._schedule_active_message(user_id)
                    else:
                        for timer in bot._active_timers.values():
                            timer.cancel()
                        bot._active_timers.clear()
                    
                    self._send_json({'success': True, 'config': bot.ai_config})
                except Exception as e:
                    print(f"[WEB] 保存 AI 配置失败: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _handle_send(self, data):
                try:
                    text = data.get('text', '').strip()
                    
                    print(f"[WEB] 收到发送请求: text='{text}', current_user={bot._current_user}")
                    
                    if not text:
                        self._send_json({'success': False, 'error': '消息不能为空'})
                        return
                    
                    if not bot._current_user:
                        self._send_json({'success': False, 'error': '没有选择用户'})
                        return
                    
                    success = bot.send_text(bot._current_user, text)
                    
                    if success:
                        self._send_json({'success': True, 'message': {'text': text, 'time': datetime.now().strftime('%H:%M:%S'), 'type': 'out'}})
                    else:
                        self._send_json({'success': False, 'error': '发送失败'})
                        
                except Exception as e:
                    print(f"[WEB] 发送异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _handle_send_media(self, data):
                try:
                    media_type = data.get('media_type', '')
                    filename = data.get('filename', 'file')
                    file_data_b64 = data.get('file_data', '')
                    thumbnail_b64 = data.get('thumbnail', '')
                    
                    if not file_data_b64:
                        self._send_json({'success': False, 'error': '文件数据为空'})
                        return
                    
                    if not bot._current_user:
                        self._send_json({'success': False, 'error': '没有选择用户'})
                        return
                    
                    try:
                        file_bytes = base64.b64decode(file_data_b64)
                    except Exception as e:
                        self._send_json({'success': False, 'error': '文件数据解码失败'})
                        return
                    
                    print(f"[WEB] 收到媒体发送请求: type={media_type}, filename={filename}, size={len(file_bytes)} bytes, user={bot._current_user}")
                    
                    success = False
                    media_type_int = 0
                    media_data_url = ""
                    
                    if media_type == 'image':
                        if thumbnail_b64:
                            media_data_url = 'data:image/jpeg;base64,' + thumbnail_b64
                        success = bot.send_image(bot._current_user, file_bytes, filename,
                                                 media_data=media_data_url)
                        media_type_int = 2
                    elif media_type == 'video':
                        if thumbnail_b64:
                            media_data_url = 'data:image/jpeg;base64,' + thumbnail_b64
                        success = bot.send_video(bot._current_user, file_bytes, filename,
                                                 media_data=media_data_url)
                        media_type_int = 5
                    elif media_type == 'file':
                        success = bot.send_file(bot._current_user, file_bytes, filename)
                        media_type_int = 4
                    else:
                        self._send_json({'success': False, 'error': f'不支持的媒体类型: {media_type}'})
                        return
                    
                    if success:
                        type_name = bot.MEDIA_TYPE_NAMES.get(media_type_int, "文件")
                        msg_data = {
                            'text': f'[{type_name}] {filename}',
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'type': 'out',
                            'media_type': media_type_int,
                            'media_filename': filename,
                            'media_data': media_data_url
                        }
                        if bot._messages:
                            for m in reversed(bot._messages):
                                if m.get('type') == 'out' and m.get('media_type') == media_type_int and not m.get('media_cache_id'):
                                    msg_data['id'] = m.get('id')
                                    if file_bytes and media_type_int in (2, 5):
                                        mime = bot._detect_mime(file_bytes)
                                        if mime == 'application/octet-stream':
                                            mime = 'video/mp4' if media_type_int == 5 else 'image/jpeg'
                                        cache_key = hashlib.md5(file_bytes).hexdigest()
                                        bot._save_media_cache(cache_key, file_bytes, mime, filename)
                                        msg_data['media_cache_id'] = cache_key
                                        m['media_cache_id'] = cache_key
                                        if m.get('media_cdn'):
                                            try:
                                                cdn_info = json.loads(m['media_cdn']) if isinstance(m['media_cdn'], str) else m['media_cdn']
                                                cdn_cache_key = bot._media_cache_key(cdn_info)
                                                if cdn_cache_key != cache_key:
                                                    bot._save_media_cache(cdn_cache_key, file_bytes, mime, filename)
                                            except Exception:
                                                pass
                                    break
                        self._send_json({'success': True, 'message': msg_data})
                    else:
                        self._send_json({'success': False, 'error': '媒体发送失败'})
                        
                except Exception as e:
                    print(f"[WEB] 媒体发送异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _handle_download_media(self, data):
                try:
                    cdn_info_str = data.get('cdn_info', '')
                    if not cdn_info_str:
                        self._send_json({'success': False, 'error': '缺少 CDN 信息'})
                        return
                    
                    if isinstance(cdn_info_str, dict):
                        cdn_info = cdn_info_str
                    else:
                        try:
                            cdn_info = json.loads(cdn_info_str)
                        except (json.JSONDecodeError, TypeError) as je:
                            print(f"[WEB] CDN 信息 JSON 解析失败: {je}, raw={str(cdn_info_str)[:200]}")
                            self._send_json({'success': False, 'error': 'CDN 信息格式错误'})
                            return
                    
                    cache_key = bot._media_cache_key(cdn_info)
                    
                    media_data = bot.download_media(cdn_info)
                    
                    if media_data:
                        mime = bot._detect_mime(media_data)
                        self._send_json({
                            'success': True,
                            'cache_key': cache_key,
                            'mime': mime
                        })
                    else:
                        self._send_json({'success': False, 'error': '下载失败'})
                        
                except Exception as e:
                    print(f"[WEB] 媒体下载异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})

            def _handle_switch_user(self, data):
                try:
                    user_id = data.get('user_id')
                    
                    if user_id and user_id in bot._context_tokens:
                        bot.set_current_user(user_id)
                        self._send_json({'success': True, 'current_user': user_id})
                    else:
                        self._send_json({'success': False, 'error': '无效的用户'})
                        
                except Exception as e:
                    self._send_json({'success': False, 'error': str(e)})
            
            def _serve_personas(self):
                try:
                    data = bot.pm.to_frontend_data(list(bot._context_tokens.keys()))
                    self._send_json(data)
                except Exception as e:
                    self._send_json({'error': str(e)})

            def _serve_persona_config(self):
                try:
                    self._send_json({
                        'persona_mode': bot.pm.get_mode(),
                        'global_persona_id': bot.pm.get_global_persona_id(),
                        'user_persona_map': dict(bot.pm.user_persona_map),
                        'users': list(bot._context_tokens.keys()),
                        'personas': bot.pm.get_all_personas(),
                    })
                except Exception as e:
                    self._send_json({'error': str(e)})

            def _handle_persona_save(self, data):
                try:
                    persona_id = data.get('id')
                    if persona_id and persona_id in bot.pm.personas:
                        bot.pm.update_persona(persona_id, data)
                        self._send_json({'success': True, 'persona': bot.pm.get_persona(persona_id)})
                    else:
                        new_id = bot.pm.add_persona(data)
                        self._send_json({'success': True, 'persona': bot.pm.get_persona(new_id)})
                except Exception as e:
                    self._send_json({'success': False, 'error': str(e)})

            def _handle_persona_delete(self, data):
                try:
                    persona_id = data.get('id')
                    if persona_id and bot.pm.delete_persona(persona_id):
                        self._send_json({'success': True})
                    else:
                        self._send_json({'success': False, 'error': '角色卡不存在'})
                except Exception as e:
                    self._send_json({'success': False, 'error': str(e)})

            def _handle_persona_config(self, data):
                try:
                    bot.pm.apply_frontend_config(data)
                    self._send_json({'success': True})
                except Exception as e:
                    self._send_json({'success': False, 'error': str(e)})

            def _serve_history(self):
                try:
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

                    user_id = params.get('user', [None])[0]
                    limit_str = params.get('limit', ['200'])[0]

                    try:
                        limit = min(int(limit_str), 500)
                    except (ValueError, TypeError):
                        limit = 200

                    if user_id:
                        history_msgs = bot.get_user_messages(user_id, limit)
                    else:
                        all_msgs = bot._messages if bot._messages else []
                        history_msgs = all_msgs[-limit:]

                    enriched = []
                    for msg in history_msgs:
                        msg_copy = dict(msg)
                        bot._enrich_msg_with_cache_id(msg_copy)
                        enriched.append(msg_copy)

                    self._send_json({
                        'messages': enriched,
                        'total': len(bot._messages),
                        'found': len(history_msgs),
                        'user_id': user_id or '',
                        'limit': limit
                    })
                except Exception as e:
                    self._send_json({
                        'messages': [],
                        'total': 0,
                        'found': 0,
                        'user_id': '',
                        'limit': 200,
                        'error': str(e)
                    })
            
            def _send_json(self, data, status=200):
                try:
                    self.send_response(status)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                except BrokenPipeError:
                    pass
                except Exception:
                    pass
        
        return WebHandler
    
    def _print_ascii_qrcode(self, qrcode_url: str):
        qr = qrcode.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        buffer = io.StringIO()
        qr.print_ascii(out=buffer, invert=True)
        output = buffer.getvalue()
        
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding='utf-8')
                print(output)
            except Exception:
                print(output.encode('utf-8', errors='replace').decode('utf-8'))
        elif is_termux():
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                print(output)
            except Exception:
                safe_output = output.encode('ascii', errors='replace').decode('ascii')
                print(safe_output)
        else:
            print(output)
    
    def login_with_qrcode(self) -> bool:
        print("正在获取连接二维码...")
        try:
            url = f"{self.ILINK_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"获取二维码失败: {e}")
            return False
        
        self._qrcode_key = data.get("qrcode")
        qrcode_url = data.get("qrcode_img_content")
        
        if not self._qrcode_key:
            print("获取二维码失败")
            return False
        
        self._qrcode_matrix = self._get_qrcode_matrix(qrcode_url)
        self._print_ascii_qrcode(qrcode_url)
        print("请使用微信扫码并确认连接...")
        print("Sioboot")
        
        while not self._login_done:
            if sys.stdin.isatty():
                if sys.platform == "win32":
                    try:
                        import msvcrt
                        if msvcrt.kbhit():
                            cmd = sys.stdin.readline().strip()
                            if cmd.lower() in ["/http", "/web"]:
                                self._open_browser()
                                continue
                    except (ImportError, AttributeError):
                        pass
                elif is_termux():
                    try:
                        try:
                            import select as sel_module
                            try:
                                rlist, _, _ = sel_module.select([sys.stdin], [], [], 0.1)
                                if rlist:
                                    cmd = sys.stdin.readline().strip()
                                    if cmd.lower() in ["/http", "/web"]:
                                        self._open_browser()
                                        continue
                            except (OSError, ValueError, ImportError):
                                pass
                        except Exception:
                            pass
                    except Exception:
                        pass
                else:
                    try:
                        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                        if rlist:
                            cmd = sys.stdin.readline().strip()
                            if cmd.lower() in ["/http", "/web"]:
                                self._open_browser()
                                continue
                    except (OSError, ValueError):
                        pass
            
            try:
                status_url = f"{self.ILINK_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={self._qrcode_key}"
                status_req = urllib.request.Request(status_url, headers={"iLink-App-ClientVersion": "1"})
                with urllib.request.urlopen(status_req, timeout=5) as status_resp:
                    status = json.loads(status_resp.read().decode('utf-8'))
            except Exception as e:
                time.sleep(1)
                continue
            
            if status.get("status") == "scaned":
                print("已扫码，请在手机上确认...")
            elif status.get("status") == "confirmed":
                self.token = status.get("bot_token")
                self.bot_id = status.get("ilink_bot_id")
                self.user_id = status.get("ilink_user_id")
                print(f"连接成功!")
                print(f"   bot_id: {self.bot_id}")
                print(f"   user_id: {self.user_id}")
                
                self._bot_accounts[self.token] = {
                    "bot_id": self.bot_id or "",
                    "user_id": self.user_id or "",
                    "cursor": self._cursor,
                    "context_tokens": {}
                }
                
                print("正在拉取历史消息，恢复会话...")
                self._fetch_and_restore_conversations()
                
                self._save_config()
                self._login_done = True
                print(f"[WEB] 连接成功！网页端应该会自动跳转到聊天界面")
                print(f"[WEB] 如果没有跳转，请刷新浏览器页面: http://localhost:{self._web_port}")
                return True
            elif status.get("status") == "expired":
                print("二维码已过期")
                return False
            time.sleep(2)
        
        if self._login_done:
            return True
        return False

    def _fetch_and_restore_conversations(self):
        for _ in range(5):
            body = {"get_updates_buf": self._cursor}
            result = self._post("getupdates", body, timeout=5)
            if result.get("get_updates_buf"):
                self._cursor = result["get_updates_buf"]
            messages = result.get("msgs", [])
            for msg in messages:
                from_user = msg.get("from_user_id")
                ctx_token = msg.get("context_token")
                if from_user and ctx_token:
                    is_new = from_user not in self._context_tokens
                    self._register_user_to_account(from_user, ctx_token, self.token)
                    if is_new:
                        print(f"恢复会话: {from_user}")
                    
                    text = ""
                    for item in msg.get("item_list", []):
                        if item.get("type") == 1:
                            text = item.get("text_item", {}).get("text", "")
                    if text:
                        new_msg = {
                            'from': from_user,
                            'to': 'me',
                            'text': text,
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'type': 'in'
                        }
                        self._add_message_to_history(new_msg)
            if not messages:
                break
        if self._context_tokens:
            print(f"已恢复 {len(self._context_tokens)} 个会话，{len(self._messages)} 条本地消息")
            print(f"当前会话用户: {self._current_user}")
            for user_id in self._context_tokens.keys():
                self._on_new_user(user_id)
        else:
            print("没有找到历史会话")
    
    def _build_headers(self, token: str = None) -> dict:
        random_uin = random.randint(0, 0xFFFFFFFF)
        wechat_uin = base64.b64encode(str(random_uin).encode()).decode()
        use_token = token or self.token
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {use_token}",
            "X-WECHAT-UIN": wechat_uin,
        }
    
    def _post(self, endpoint: str, body: dict, timeout: int = 30, token: str = None) -> dict:
        if is_termux():
            timeout = max(timeout, 30)
            if "getupdates" in endpoint:
                timeout = 30
        
        body["base_info"] = {"channel_version": "1.0.3"}
        headers = self._build_headers(token=token)
        url = f"{self.ILINK_BASE_URL}/ilink/bot/{endpoint}"
        
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        max_retries = 2 if is_termux() else 0
        
        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    result = response.read().decode('utf-8')
                    if result.strip() == "{}":
                        return {"ret": 0}
                    return json.loads(result)
            except (urllib.error.URLError, Exception) as e:
                is_timeout = (
                    isinstance(e, urllib.error.URLError) and isinstance(e.reason, TimeoutError)
                ) or "timeout" in str(e).lower() or "timed out" in str(e).lower()
                
                if is_timeout:
                    if attempt < max_retries:
                        print(f"[TERMUX] 网络超时，重试 ({attempt + 1}/{max_retries})...")
                        time.sleep(2)
                        continue
                    return {"ret": -1, "errmsg": "timeout"}
                
                if attempt < max_retries:
                    print(f"[TERMUX] 请求失败: {e}，重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(3)
                    continue
                    
                return {"ret": -1, "errmsg": str(e)}
        
        return {"ret": -1, "errmsg": "max retries exceeded"}
    
    _MEDIA_ITEM_KEYS = ["image_item", "video_item", "file_item", "voice_item"]
    
    def _extract_cdn_media(self, item: dict) -> Optional[dict]:
        for ik in self._MEDIA_ITEM_KEYS:
            mi = item.get(ik)
            if mi and isinstance(mi, dict) and mi.get("media"):
                cdn_media = dict(mi["media"])
                if not cdn_media.get("aes_key") and mi.get("aeskey"):
                    cdn_media["aes_key"] = base64.b64encode(mi["aeskey"].encode('utf-8')).decode('utf-8')
                return cdn_media
        return None
    
    def _process_message_items(self, item_list: list) -> tuple:
        text = ""
        media_info = None
        
        for item in item_list:
            if item.get("text_item"):
                text_item = item["text_item"]
                if isinstance(text_item, dict):
                    text = text_item.get("text", "")
                    
            if item.get("image_item"):
                img_item = item["image_item"]
                if isinstance(img_item, dict):
                    media_info = {
                        "type": "image",
                        "filename": img_item.get("filename", "image.jpg"),
                        "item": item
                    }
                    
            elif item.get("video_item"):
                video_item = item["video_item"]
                if isinstance(video_item, dict):
                    media_info = {
                        "type": "video",
                        "filename": video_item.get("filename", "video.mp4"),
                        "duration": video_item.get("duration", 0),
                        "item": item
                    }
                    
            elif item.get("file_item"):
                file_item = item["file_item"]
                if isinstance(file_item, dict):
                    media_info = {
                        "type": "file",
                        "filename": file_item.get("filename", "file.bin"),
                        "description": file_item.get("description", ""),
                        "item": item
                    }
                    
            elif item.get("voice_item"):
                voice_item = item["voice_item"]
                if isinstance(voice_item, dict):
                    media_info = {
                        "type": "voice",
                        "filename": voice_item.get("filename", "voice.silk"),
                        "duration": voice_item.get("duration", 0),
                        "item": item
                    }
        
        return text, media_info
    
    def start_add_user_qrcode(self) -> str:
        def _gen_qrcode():
            try:
                url = f"{self.ILINK_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                
                qrcode_url = data.get("qrcode_img_content")
                qrcode_key = data.get("qrcode")
                
                with self._add_user_lock:
                    self._pending_qrcode = {
                        "key": qrcode_key,
                        "matrix": self._get_qrcode_matrix(qrcode_url) if qrcode_url else None,
                        "status": "waiting",
                        "started_at": time.time()
                    }
                
                if qrcode_url:
                    self._print_ascii_qrcode(qrcode_url)
                    print(f"[添加用户] 二维码已生成，请扫描")
                
                start_ts = time.time()
                while time.time() - start_ts < 120:
                    if not self._running:
                        break
                    try:
                        status_url = f"{self.ILINK_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={qrcode_key}"
                        status_req = urllib.request.Request(status_url, headers={"iLink-App-ClientVersion": "1"})
                        with urllib.request.urlopen(status_req, timeout=5) as status_resp:
                            status = json.loads(status_resp.read().decode('utf-8'))
                    except Exception:
                        time.sleep(1)
                        continue
                    
                    st = status.get("status", "")
                    
                    with self._add_user_lock:
                        if st == "scaned":
                            if self._pending_qrcode:
                                self._pending_qrcode["status"] = "scaned"
                            print("[添加用户] 已扫码，请在手机上确认...")
                        elif st == "confirmed":
                            new_token = status.get("bot_token")
                            new_bot_id = status.get("ilink_bot_id")
                            new_user_id = status.get("ilink_user_id")
                            
                            if not new_token:
                                print("[添加用户] 错误：未获取到 bot_token")
                                if self._pending_qrcode:
                                    self._pending_qrcode["status"] = "error"
                                break
                            
                            new_account = {
                                "bot_id": new_bot_id or "",
                                "user_id": new_user_id or "",
                                "cursor": "",
                                "context_tokens": {}
                            }
                            self._bot_accounts[new_token] = new_account

                            if not self.token:
                                self.token = new_token
                                self.bot_id = new_bot_id
                                self.user_id = new_user_id
                                self._login_done = True

                            print(f"[添加用户] 新 bot 账号已创建: {new_token[:8]}... (bot_id: {new_bot_id})")

                            # 立即注册扫码用户，使其出现在聊天列表
                            if new_user_id and new_user_id not in self._context_tokens:
                                self._context_tokens[new_user_id] = ""  # placeholder，收到首条消息时更新
                                self._user_token_map[new_user_id] = new_token
                                new_account["context_tokens"][new_user_id] = ""
                                if not self._current_user:
                                    self._current_user = new_user_id
                                print(f"[添加用户] 已注册新用户: {new_user_id}")
                                self._on_new_user(new_user_id)

                            with self._add_user_lock:
                                if self._pending_qrcode:
                                    self._pending_qrcode["status"] = "done"
                                    self._pending_qrcode["users"] = list(self._context_tokens.keys())

                            # 先标记完成再异步恢复数据，避免阻塞下一次添加用户
                            threading.Thread(target=self._fetch_and_restore_for_account, args=(new_token, new_account), daemon=True).start()
                            self._save_config()
                            self._start_account_poll(new_token, new_account)
                            break
                        elif st == "expired":
                            with self._add_user_lock:
                                if self._pending_qrcode:
                                    self._pending_qrcode["status"] = "expired"
                            print("[添加用户] 二维码已过期")
                            break
                    
                    time.sleep(1.5)
                else:
                    with self._add_user_lock:
                        if self._pending_qrcode and self._pending_qrcode.get("status") == "waiting":
                            self._pending_qrcode["status"] = "timeout"
                    print("[添加用户] 二维码等待超时")
                    
            except Exception as e:
                print(f"[添加用户] 获取二维码失败: {e}")
                with self._add_user_lock:
                    self._pending_qrcode = {"key": "", "matrix": None, "status": "error", "error": str(e)}
        
        qrcode_key = uuid.uuid4().hex[:12]
        with self._add_user_lock:
            self._pending_qrcode = {"key": qrcode_key, "matrix": None, "status": "generating"}
        
        thread = threading.Thread(target=_gen_qrcode, daemon=True)
        thread.start()
        return qrcode_key
    
    def _fetch_and_restore_for_account(self, bot_token: str, account: dict):
        for _ in range(5):
            body = {"get_updates_buf": account.get("cursor", "")}
            result = self._post("getupdates", body, timeout=5, token=bot_token)
            if result.get("get_updates_buf"):
                account["cursor"] = result["get_updates_buf"]
            messages = result.get("msgs", [])
            for msg in messages:
                from_user = msg.get("from_user_id")
                ctx_token = msg.get("context_token")
                if from_user and ctx_token:
                    is_new = from_user not in self._context_tokens
                    self._register_user_to_account(from_user, ctx_token, bot_token)
                    
                    text = ""
                    for item in msg.get("item_list", []):
                        if item.get("type") == 1:
                            text = item.get("text_item", {}).get("text", "")
                    if text:
                        new_msg = {
                            'from': from_user,
                            'to': 'me',
                            'text': text,
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'type': 'in'
                        }
                        self._add_message_to_history(new_msg)
                    
                    if is_new:
                        self._on_new_user(from_user)
            if not messages:
                break
        
        user_count = len(account.get("context_tokens", {}))
        print(f"[账号 {bot_token[:8]}...] 已恢复 {user_count} 个会话")
    
    def get_add_user_status(self) -> dict:
        with self._add_user_lock:
            if not self._pending_qrcode:
                return {"status": "none", "message": "没有进行中的添加操作"}
            return dict(self._pending_qrcode)
    
    def start_polling(self):
        if self.token and self.token not in self._bot_accounts:
            self._bot_accounts[self.token] = {
                "bot_id": self.bot_id or "",
                "user_id": self.user_id or "",
                "cursor": self._cursor,
                "context_tokens": dict(self._context_tokens)
            }
        
        for bot_token, account in self._bot_accounts.items():
            self._start_account_poll(bot_token, account)
    
    def _start_account_poll(self, bot_token: str, account: dict):
        def poll():
            cursor = account.get("cursor", "")
            while self._running:
                try:
                    body = {"get_updates_buf": cursor}
                    result = self._post("getupdates", body, timeout=25, token=bot_token)
                    
                    if result.get("get_updates_buf"):
                        cursor = result["get_updates_buf"]
                        account["cursor"] = cursor
                        self._save_config()
                    
                    messages = result.get("msgs", [])
                    for msg in messages:
                        from_user = msg.get("from_user_id")
                        ctx_token = msg.get("context_token")
                        
                        text, media_info = self._process_message_items(msg.get("item_list", []))
                        
                        msg_text = text
                        msg_type = 'in'
                        msg_metadata = {}
                        
                        if media_info:
                            media_type_int = self.MEDIA_TYPE_MAP.get(media_info["type"], 0)
                            media_prefix = self.MEDIA_TYPE_PREFIXES.get(media_info["type"], f"[{media_info['type']}]")
                            
                            if text:
                                msg_text = f"{media_prefix} {text}"
                            else:
                                msg_text = f"{media_prefix} {media_info.get('filename', '')}"
                            
                            msg_metadata = {
                                'media_type': media_type_int,
                                'media_filename': media_info.get('filename', ''),
                                'media_duration': media_info.get('duration', 0),
                                'has_media': True
                            }
                            
                            media_item = media_info.get("item", {})
                            cdn_media = self._extract_cdn_media(media_item)
                            if cdn_media:
                                msg_metadata['media_cdn'] = json.dumps(cdn_media)
                                _prefetch_fn = media_info.get('filename', '')
                                threading.Thread(target=self._prefetch_media, args=(cdn_media, _prefetch_fn, from_user), daemon=True).start()
                            
                            print(f"\n[收到{media_info['type']}] {from_user}: {media_info.get('filename', '')}")
                        elif text:
                            print(f"\n[收到消息] {from_user}: {text}")
                        
                        if msg_text:
                            new_msg = {
                                'from': from_user,
                                'to': 'me',
                                'text': msg_text,
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'type': msg_type,
                                **msg_metadata
                            }
                            
                            self._add_message_to_history(new_msg)
                            
                            if self._message_callback:
                                self._message_callback(new_msg)
                            
                            if text:
                                threading.Thread(target=self._auto_ai_reply, args=(from_user, text), daemon=True).start()
                        
                        if from_user and ctx_token:
                            is_new = from_user not in self._context_tokens
                            self._register_user_to_account(from_user, ctx_token, bot_token)
                            self._save_config()
                            if is_new:
                                self._on_new_user(from_user)
                                print(f"[USER] 新用户 {from_user} (账号 {bot_token[:8]}...)")
                except Exception as e:
                    time.sleep(0.5)
        
        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        self._poll_threads.append(thread)
        token_short = bot_token[:8] if bot_token else "?"
        print(f"[POLL] 已启动轮询线程: {token_short}...")
    
    def send_text(self, to_user_id: str, text: str) -> bool:
        context_token = self._context_tokens.get(to_user_id)
        if not context_token:
            print(f"[发送失败] 没有 {to_user_id} 的会话，让对方先发一条消息")
            return False
        
        use_token = self._get_token_for_user(to_user_id)
        
        client_id = f"msg-{uuid.uuid4().hex[:16]}"
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}]
            }
        }
        result = self._post("sendmessage", body, token=use_token)
        
        errcode = result.get("errcode")
        ret = result.get("ret")
        
        if ret == 0 or errcode == 0:
            print(f"[发送成功] 给 {to_user_id}: {text[:50]}...")
            out_msg = {
                'from': 'me',
                'to': to_user_id,
                'text': text,
                'time': datetime.now().strftime('%H:%M:%S'),
                'type': 'out'
            }
            self._add_message_to_history(out_msg)
            return True
        
        if errcode in self.EXPIRED_CODES or ret in self.EXPIRED_CODES:
            print(f"[发送失败] 会话已过期，需要对方重新发消息")
            self._context_tokens.pop(to_user_id, None)
            self._save_config()
            return False
        
        if ret == -1:
            print(f"[发送失败] {result.get('errmsg', '未知错误')}")
            return False
        
        print(f"[发送成功] 给 {to_user_id}: {text[:50]}...")
        out_msg = {
            'from': 'me',
            'to': to_user_id,
            'text': text,
            'time': datetime.now().strftime('%H:%M:%S'),
            'type': 'out'
        }
        self._add_message_to_history(out_msg)
        return True
    
    CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"

    def _random_hex(self, num_bytes: int) -> str:
        raw = os.urandom(num_bytes)
        return raw.hex()

    def _md5_hex(self, data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    _AES_SBOX = [
        0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
        0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
        0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
        0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
        0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
        0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
        0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
        0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
        0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
        0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
        0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
        0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
        0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
        0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
        0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
        0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
    ]
    _AES_INV_SBOX = [
        0x52,0x09,0x6a,0xd5,0x30,0x36,0xa5,0x38,0xbf,0x40,0xa3,0x9e,0x81,0xf3,0xd7,0xfb,
        0x7c,0xe3,0x39,0x82,0x9b,0x2f,0xff,0x87,0x34,0x8e,0x43,0x44,0xc4,0xde,0xe9,0xcb,
        0x54,0x7b,0x94,0x32,0xa6,0xc2,0x23,0x3d,0xee,0x4c,0x95,0x0b,0x42,0xfa,0xc3,0x4e,
        0x08,0x2e,0xa1,0x66,0x28,0xd9,0x24,0xb2,0x76,0x5b,0xa2,0x49,0x6d,0x8b,0xd1,0x25,
        0x72,0xf8,0xf6,0x64,0x86,0x68,0x98,0x16,0xd4,0xa4,0x5c,0xcc,0x5d,0x65,0xb6,0x92,
        0x6c,0x70,0x48,0x50,0xfd,0xed,0xb9,0xda,0x5e,0x15,0x46,0x57,0xa7,0x8d,0x9d,0x84,
        0x90,0xd8,0xab,0x00,0x8c,0xbc,0xd3,0x0a,0xf7,0xe4,0x58,0x05,0xb8,0xb3,0x45,0x06,
        0xd0,0x2c,0x1e,0x8f,0xca,0x3f,0x0f,0x02,0xc1,0xaf,0xbd,0x03,0x01,0x13,0x8a,0x6b,
        0x3a,0x91,0x11,0x41,0x4f,0x67,0xdc,0xea,0x97,0xf2,0xcf,0xce,0xf0,0xb4,0xe6,0x73,
        0x96,0xac,0x74,0x22,0xe7,0xad,0x35,0x85,0xe2,0xf9,0x37,0xe8,0x1c,0x75,0xdf,0x6e,
        0x47,0xf1,0x1a,0x71,0x1d,0x29,0xc5,0x89,0x6f,0xb7,0x62,0x0e,0xaa,0x18,0xbe,0x1b,
        0xfc,0x56,0x3e,0x4b,0xc6,0xd2,0x79,0x20,0x9a,0xdb,0xc0,0xfe,0x78,0xcd,0x5a,0xf4,
        0x1f,0xdd,0xa8,0x33,0x88,0x07,0xc7,0x31,0xb1,0x12,0x10,0x59,0x27,0x80,0xec,0x5f,
        0x60,0x51,0x7f,0xa9,0x19,0xb5,0x4a,0x0d,0x2d,0xe5,0x7a,0x9f,0x93,0xc9,0x9c,0xef,
        0xa0,0xe0,0x3b,0x4d,0xae,0x2a,0xf5,0xb0,0xc8,0xeb,0xbb,0x3c,0x83,0x53,0x99,0x61,
        0x17,0x2b,0x04,0x7e,0xba,0x77,0xd6,0x26,0xe1,0x69,0x14,0x63,0x55,0x21,0x0c,0x7d,
    ]
    _AES_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]

    @staticmethod
    def _xtime(a):
        return ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else (a << 1) & 0xff

    @staticmethod
    def _gmul(a, b):
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xff
            if hi:
                a ^= 0x1b
            b >>= 1
        return p

    @classmethod
    def _aes_key_expansion(cls, key: bytes) -> list:
        Nk = len(key) // 4
        Nr = Nk + 6
        W = []
        for i in range(Nk):
            W.append(list(key[4*i:4*i+4]))
        for i in range(Nk, 4*(Nr+1)):
            t = list(W[i-1])
            if i % Nk == 0:
                t = t[1:] + t[:1]
                t = [cls._AES_SBOX[b] for b in t]
                t[0] ^= cls._AES_RCON[i//Nk - 1]
            elif Nk > 6 and i % Nk == 4:
                t = [cls._AES_SBOX[b] for b in t]
            W.append([W[i-Nk][j] ^ t[j] for j in range(4)])
        return W

    @classmethod
    def _aes_encrypt_block(cls, block: bytes, round_keys: list) -> bytes:
        Nr = len(round_keys) // 4 - 1
        s = [[0]*4 for _ in range(4)]
        for i in range(16):
            s[i%4][i//4] = block[i]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[c][r]
        for rnd in range(1, Nr):
            s = [[cls._AES_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
            for r in range(1, 4):
                s[r] = s[r][r:] + s[r][:r]
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = cls._xtime(a[0]) ^ cls._xtime(a[1]) ^ a[1] ^ a[2] ^ a[3]
                s[1][c] = a[0] ^ cls._xtime(a[1]) ^ cls._xtime(a[2]) ^ a[2] ^ a[3]
                s[2][c] = a[0] ^ a[1] ^ cls._xtime(a[2]) ^ cls._xtime(a[3]) ^ a[3]
                s[3][c] = cls._xtime(a[0]) ^ a[0] ^ a[1] ^ a[2] ^ cls._xtime(a[3])
            for c in range(4):
                for r in range(4):
                    s[r][c] ^= round_keys[rnd*4+c][r]
        s = [[cls._AES_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[Nr*4+c][r]
        out = []
        for i in range(16):
            out.append(s[i%4][i//4])
        return bytes(out)

    @classmethod
    def _aes_decrypt_block(cls, block: bytes, round_keys: list) -> bytes:
        Nr = len(round_keys) // 4 - 1
        s = [[0]*4 for _ in range(4)]
        for i in range(16):
            s[i%4][i//4] = block[i]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[Nr*4+c][r]
        for rnd in range(Nr-1, 0, -1):
            for r in range(1, 4):
                s[r] = s[r][-r:] + s[r][:-r]
            s = [[cls._AES_INV_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
            for c in range(4):
                for r in range(4):
                    s[r][c] ^= round_keys[rnd*4+c][r]
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = cls._gmul(a[0],14) ^ cls._gmul(a[1],11) ^ cls._gmul(a[2],13) ^ cls._gmul(a[3],9)
                s[1][c] = cls._gmul(a[0],9) ^ cls._gmul(a[1],14) ^ cls._gmul(a[2],11) ^ cls._gmul(a[3],13)
                s[2][c] = cls._gmul(a[0],13) ^ cls._gmul(a[1],9) ^ cls._gmul(a[2],14) ^ cls._gmul(a[3],11)
                s[3][c] = cls._gmul(a[0],11) ^ cls._gmul(a[1],13) ^ cls._gmul(a[2],9) ^ cls._gmul(a[3],14)
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
        s = [[cls._AES_INV_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[c][r]
        out = []
        for i in range(16):
            out.append(s[i%4][i//4])
        return bytes(out)

    @staticmethod
    def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
        pad_len = block_size - (len(data) % block_size)
        return data + bytes([pad_len] * pad_len)

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        if not data:
            raise ValueError("Empty data")
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 16:
            raise ValueError(f"Invalid padding: {pad_len}")
        if data[-pad_len:] != bytes([pad_len] * pad_len):
            raise ValueError("Invalid PKCS7 padding")
        return data[:-pad_len]

    def _aes_ecb_encrypt(self, plain: bytes, key: bytes) -> bytes:
        if _HAS_PYCRYPTODOME:
            cipher = _CryptoAES.new(key, _CryptoAES.MODE_ECB)
            padded = self._pkcs7_pad(plain)
            return cipher.encrypt(padded)
        round_keys = self._aes_key_expansion(key)
        padded = self._pkcs7_pad(plain)
        out = bytearray()
        for i in range(0, len(padded), 16):
            out.extend(self._aes_encrypt_block(padded[i:i+16], round_keys))
        return bytes(out)

    def _aes_ecb_decrypt(self, encrypted: bytes, key: bytes) -> bytes:
        if _HAS_PYCRYPTODOME:
            cipher = _CryptoAES.new(key, _CryptoAES.MODE_ECB)
            decrypted = cipher.decrypt(encrypted)
            return self._pkcs7_unpad(decrypted)
        round_keys = self._aes_key_expansion(key)
        if len(encrypted) % 16 != 0:
            raise ValueError("Encrypted data length must be multiple of 16")
        out = bytearray()
        for i in range(0, len(encrypted), 16):
            out.extend(self._aes_decrypt_block(encrypted[i:i+16], round_keys))
        return self._pkcs7_unpad(bytes(out))

    def _upload_media(self, file_bytes: bytes, filename: str, media_type: int, to_user_id: str) -> Optional[dict]:
        try:
            print(f"[媒体上传] 正在上传 {filename}, 类型={media_type}, 大小={len(file_bytes)} bytes")

            use_token = self._get_token_for_user(to_user_id)

            aes_key_hex = self._random_hex(16)
            aes_key_bytes = bytes.fromhex(aes_key_hex)

            encrypted = self._aes_ecb_encrypt(file_bytes, aes_key_bytes)

            filekey = self._random_hex(16)
            raw_md5 = self._md5_hex(file_bytes)

            body = {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": len(file_bytes),
                "rawfilemd5": raw_md5,
                "filesize": len(encrypted),
                "no_need_thumb": True,
                "aeskey": aes_key_hex
            }

            result = self._post("getuploadurl", body, token=use_token)

            ret = result.get("ret")
            errcode = result.get("errcode")

            if ret is not None and ret != 0:
                print(f"[媒体上传失败] getuploadurl 失败: ret={ret}, errcode={errcode}, errmsg={result.get('errmsg', '')}")
                return None
            if errcode is not None and errcode != 0:
                print(f"[媒体上传失败] getuploadurl 失败: ret={ret}, errcode={errcode}, errmsg={result.get('errmsg', '')}")
                return None

            upload_param = result.get("upload_param")
            if not upload_param:
                print(f"[媒体上传失败] 未获取到 upload_param, 返回数据: {json.dumps(result, ensure_ascii=False)[:300]}")
                return None

            cdn_url = self.CDN_BASE + "/upload?encrypted_query_param=" + urllib.parse.quote(upload_param, safe='') + "&filekey=" + urllib.parse.quote(filekey, safe='')

            print(f"[媒体上传] 获取到上传参数，正在上传到 CDN...")

            req = urllib.request.Request(
                cdn_url,
                data=encrypted,
                method='POST',
                headers={'Content-Type': 'application/octet-stream'}
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                encrypted_param = resp.headers.get('x-encrypted-param', '')
                if not encrypted_param:
                    resp_body = resp.read()
                    print(f"[媒体上传失败] CDN 响应缺少 x-encrypted-param 头, status={resp.status}, body={resp_body[:200]}")
                    return None

                aes_key_b64 = base64.b64encode(aes_key_hex.encode('utf-8')).decode('utf-8')

                cdn_media = {
                    "encrypt_query_param": encrypted_param,
                    "aes_key": aes_key_b64,
                    "encrypt_type": 1
                }

                uploaded = {
                    "filekey": filekey,
                    "media": cdn_media,
                    "aes_key_hex": aes_key_hex,
                    "raw_size": len(file_bytes),
                    "encrypted_size": len(encrypted),
                    "md5": raw_md5,
                    "filename": filename
                }

                print(f"[媒体上传成功] filekey={filekey}, enc_size={len(encrypted)}")
                return uploaded

        except Exception as e:
            print(f"[媒体上传异常] {e}")
            import traceback
            traceback.print_exc()
            return None

    def _send_media_message(self, to_user_id: str, media_item: dict,
                            description: str = "", media_data: str = "",
                            media_filename: str = "", media_duration: int = 0) -> bool:
        context_token = self._context_tokens.get(to_user_id)
        if not context_token:
            print(f"[发送失败] 没有 {to_user_id} 的会话，让对方先发一条消息")
            return False

        if description:
            self.send_text(to_user_id, description)

        use_token = self._get_token_for_user(to_user_id)
        client_id = f"ilink-sdk:{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [media_item]
            }
        }

        result = self._post("sendmessage", body, token=use_token)

        errcode = result.get("errcode")
        ret = result.get("ret")

        success = (ret is None or ret == 0) and (errcode is None or errcode == 0)

        if errcode is not None and errcode in self.EXPIRED_CODES:
            success = False
        if ret is not None and ret in self.EXPIRED_CODES:
            success = False

        if success:
            type_name = self.MEDIA_TYPE_NAMES.get(media_item.get("type", 0), "媒体")
            print(f"[发送成功] {type_name} 给 {to_user_id}")
            out_msg = {
                'from': 'me',
                'to': to_user_id,
                'text': f"[{type_name}]" + (f" {description}" if description else ""),
                'time': datetime.now().strftime('%H:%M:%S'),
                'type': 'out',
                'media_type': media_item.get("type"),
                'media_data': media_data,
                'media_filename': media_filename or description,
                'media_duration': media_duration
            }
            cdn_media = self._extract_cdn_media(media_item)
            if cdn_media:
                out_msg['media_cdn'] = json.dumps(cdn_media)
            self._add_message_to_history(out_msg)
            return True

        if errcode in self.EXPIRED_CODES or ret in self.EXPIRED_CODES:
            print(f"[发送失败] 会话已过期，需要对方重新发消息")
            self._context_tokens.pop(to_user_id, None)
            self._save_config()
            return False

        print(f"[发送失败] ret={ret}, errcode={errcode}, errmsg={result.get('errmsg', '')}")
        return False

    def send_image(self, to_user_id: str, image_bytes: bytes,
                   filename: str = "image.jpg", description: str = "",
                   media_data: str = "") -> bool:
        print(f"[发送图片] 准备发送图片给 {to_user_id}: {filename} ({len(image_bytes)} bytes)")

        uploaded = self._upload_media(image_bytes, filename, media_type=1, to_user_id=to_user_id)
        if not uploaded:
            print("[发送图片失败] 上传失败")
            return False

        image_item = {
            "media": uploaded["media"],
            "aeskey": uploaded["aes_key_hex"],
            "mid_size": uploaded["encrypted_size"]
        }

        media_item = {
            "type": 2,
            "image_item": image_item
        }

        return self._send_media_message(to_user_id, media_item, description,
                                        media_data=media_data, media_filename=filename)

    def send_file(self, to_user_id: str, file_bytes: bytes,
                  filename: str = "file.bin", description: str = "",
                  media_data: str = "") -> bool:
        print(f"[发送文件] 准备发送文件给 {to_user_id}: {filename} ({len(file_bytes)} bytes)")

        uploaded = self._upload_media(file_bytes, filename, media_type=3, to_user_id=to_user_id)
        if not uploaded:
            print("[发送文件失败] 上传失败")
            return False

        file_item = {
            "media": uploaded["media"],
            "file_name": filename,
            "md5": uploaded["md5"],
            "len": str(uploaded["raw_size"])
        }

        media_item = {
            "type": 4,
            "file_item": file_item
        }

        return self._send_media_message(to_user_id, media_item, description,
                                        media_filename=filename)

    def send_voice(self, to_user_id: str, voice_bytes: bytes,
                   filename: str = "voice.silk", duration_ms: int = 1000,
                   sample_rate: int = 16000) -> bool:
        print(f"[发送语音] 准备发送语音给 {to_user_id}: {filename} ({len(voice_bytes)} bytes, {duration_ms}ms)")

        uploaded = self._upload_media(voice_bytes, filename, media_type=4, to_user_id=to_user_id)
        if not uploaded:
            print("[发送语音失败] 上传失败")
            return False

        voice_item = {
            "media": uploaded["media"],
            "encode_type": 6,
            "bits_per_sample": 16,
            "playtime": duration_ms,
            "sample_rate": sample_rate
        }

        media_item = {
            "type": 3,
            "voice_item": voice_item
        }

        return self._send_media_message(to_user_id, media_item,
                                        media_filename=filename, media_duration=duration_ms)

    def send_video(self, to_user_id: str, video_bytes: bytes,
                   filename: str = "video.mp4", duration_ms: int = 5000,
                   description: str = "", media_data: str = "") -> bool:
        print(f"[发送视频] 准备发送视频给 {to_user_id}: {filename} ({len(video_bytes)} bytes, {duration_ms}ms)")

        uploaded = self._upload_media(video_bytes, filename, media_type=2, to_user_id=to_user_id)
        if not uploaded:
            print("[发送视频失败] 上传失败")
            return False

        video_item = {
            "media": uploaded["media"],
            "video_size": uploaded["encrypted_size"],
            "play_length": duration_ms,
            "video_md5": uploaded["md5"]
        }

        media_item = {
            "type": 5,
            "video_item": video_item
        }

        return self._send_media_message(to_user_id, media_item, description,
                                        media_data=media_data, media_filename=filename,
                                        media_duration=duration_ms)

    def _media_cache_key(self, cdn_media_info: dict) -> str:
        eqp = cdn_media_info.get("encrypt_query_param") or cdn_media_info.get("encrypted_query_param") or ""
        return hashlib.md5(eqp.encode('utf-8')).hexdigest()

    def _enrich_msg_with_cache_id(self, msg: dict) -> dict:
        if msg.get('media_cdn') and msg.get('media_type'):
            try:
                cdn_info = json.loads(msg['media_cdn']) if isinstance(msg['media_cdn'], str) else msg['media_cdn']
                cache_key = self._media_cache_key(cdn_info)
                
                user_id = msg.get('from') if msg.get('type') == 'in' else msg.get('to')
                
                cached = None
                if user_id:
                    cached = self._get_user_cached_media(user_id, cache_key)
                if not cached:
                    cached = self._get_cached_media(cache_key)
                if cached:
                    msg['media_cache_id'] = cache_key
                    msg['media_cache_user'] = user_id
            except Exception:
                pass
        return msg

    def _media_cache_path(self, cache_key: str) -> Path:
        return self._media_cache_dir / cache_key

    def _media_meta_path(self, cache_key: str) -> Path:
        return self._media_cache_dir / (cache_key + ".meta")

    def _get_cached_media(self, cache_key: str) -> Optional[tuple]:
        data_path = self._media_cache_path(cache_key)
        meta_path = self._media_meta_path(cache_key)
        if data_path.exists() and meta_path.exists():
            try:
                media_data = data_path.read_bytes()
                meta = json.loads(meta_path.read_text('utf-8'))
                return (media_data, meta.get('mime', 'application/octet-stream'), meta.get('filename', ''))
            except Exception:
                return None
        return None

    def _save_media_cache(self, cache_key: str, media_data: bytes, mime: str, filename: str = ""):
        try:
            self._media_cache_path(cache_key).write_bytes(media_data)
            meta = {'mime': mime, 'filename': filename, 'size': len(media_data)}
            self._media_meta_path(cache_key).write_text(json.dumps(meta, ensure_ascii=False), 'utf-8')
        except Exception as e:
            print(f"[媒体缓存] 保存失败: {e}")

    def _prefetch_media(self, cdn_media_info: dict, filename: str = "", user_id: str = ""):
        try:
            cache_key = self._media_cache_key(cdn_media_info)
            
            if user_id and self._get_user_cached_media(user_id, cache_key):
                return
            if self._get_cached_media(cache_key):
                return
            
            print(f"[媒体预取] 开始下载: {cache_key[:12]}...")
            result = self.download_media(cdn_media_info, filename=filename, user_id=user_id)
            if result:
                print(f"[媒体预取] 完成: {cache_key[:12]}..., {len(result)} bytes")
            else:
                print(f"[媒体预取] 失败: {cache_key[:12]}...")
        except Exception as e:
            print(f"[媒体预取] 异常: {e}")

    def _detect_mime(self, data: bytes) -> str:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        if data[:4] == b'GIF8':
            return 'image/gif'
        if data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WEBP':
            return 'image/webp'
        if data[:2] == b'\xff\xd8':
            return 'image/jpeg'
        if data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WAVE':
            return 'audio/wav'
        if len(data) > 3 and (data[:3] == b'ID3' or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')):
            return 'audio/mpeg'
        if data[:4] == b'fLaC':
            return 'audio/flac'
        if data[:4] == b'OggS':
            return 'audio/ogg'
        if len(data) > 9 and data[:9] == b'#!SILK_V3':
            return 'audio/silk'
        if len(data) > 10 and data[:1] == b'\x02' and data[1:10] == b'#!SILK_V3':
            return 'audio/silk'
        if len(data) > 5 and data[:5] == b'#!AMR':
            return 'audio/amr'
        if len(data) > 8 and data[:4] == b'\x00\x00\x00':
            box_type = data[4:8]
            if box_type == b'ftyp':
                return 'video/mp4'
            if box_type == b'MThd':
                return 'audio/midi'
        if data[:4] == b'\x1a\x45\xdf\xa3':
            return 'video/webm'
        return 'application/octet-stream'

    def _silk_to_wav(self, silk_data: bytes) -> Optional[bytes]:
        try:
            import pilk
        except ImportError:
            print("[SILK转WAV] pilk 未安装，尝试 ffmpeg")
            return self._ffmpeg_to_wav(silk_data)
        if silk_data[:1] == b'\x02' and len(silk_data) > 10 and silk_data[1:10] == b'#!SILK_V3':
            silk_data = silk_data[1:]
        if silk_data[:9] != b'#!SILK_V3':
            print("[SILK转WAV] 非 SILK V3 格式")
            return self._ffmpeg_to_wav(silk_data)
        try:
            tmp_in = self._media_cache_dir / ('_silk_tmp_in_' + uuid.uuid4().hex[:12] + '.silk')
            tmp_out = self._media_cache_dir / ('_silk_tmp_out_' + uuid.uuid4().hex[:12] + '.pcm')
            tmp_in.write_bytes(silk_data)
            pilk.decode(str(tmp_in), str(tmp_out), pcm_rate=24000)
            if not tmp_out.exists() or tmp_out.stat().st_size == 0:
                print("[SILK转WAV] pilk 解码无输出，尝试 ffmpeg")
                return self._ffmpeg_to_wav(silk_data)
            pcm_data = tmp_out.read_bytes()
            sample_rate = 24000
            num_channels = 1
            bits_per_sample = 16
            byte_rate = sample_rate * num_channels * bits_per_sample // 8
            block_align = num_channels * bits_per_sample // 8
            data_size = len(pcm_data)
            wav_buf = io.BytesIO()
            wav_buf.write(b'RIFF')
            wav_buf.write(struct.pack('<I', 36 + data_size))
            wav_buf.write(b'WAVE')
            wav_buf.write(b'fmt ')
            wav_buf.write(struct.pack('<I', 16))
            wav_buf.write(struct.pack('<H', 1))
            wav_buf.write(struct.pack('<H', num_channels))
            wav_buf.write(struct.pack('<I', sample_rate))
            wav_buf.write(struct.pack('<I', byte_rate))
            wav_buf.write(struct.pack('<H', block_align))
            wav_buf.write(struct.pack('<H', bits_per_sample))
            wav_buf.write(b'data')
            wav_buf.write(struct.pack('<I', data_size))
            wav_buf.write(pcm_data)
            print(f"[SILK转WAV] pilk 转换成功: {len(silk_data)} bytes SILK -> {wav_buf.tell()} bytes WAV")
            return wav_buf.getvalue()
        except Exception as e:
            print(f"[SILK转WAV] pilk 转换失败: {e}，尝试 ffmpeg")
            return self._ffmpeg_to_wav(silk_data)
        finally:
            try:
                tmp_in.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                tmp_out.unlink(missing_ok=True)
            except Exception:
                pass

    def _ffmpeg_to_wav(self, audio_data: bytes) -> Optional[bytes]:
        tmp_in = None
        tmp_out = None
        try:
            tmp_in = self._media_cache_dir / ('_ffmpeg_tmp_in_' + uuid.uuid4().hex[:12])
            tmp_out = self._media_cache_dir / ('_ffmpeg_tmp_out_' + uuid.uuid4().hex[:12] + '.wav')
            tmp_in.write_bytes(audio_data)
            result = subprocess.run(
                ['ffmpeg', '-y', '-i', str(tmp_in), '-f', 'wav', '-ar', '24000', '-ac', '1', str(tmp_out)],
                capture_output=True, timeout=30
            )
            if tmp_out.exists() and tmp_out.stat().st_size > 44:
                wav_data = tmp_out.read_bytes()
                print(f"[ffmpeg转WAV] 转换成功: {len(audio_data)} bytes -> {len(wav_data)} bytes")
                return wav_data
            print(f"[ffmpeg转WAV] 转换失败: {result.stderr.decode('utf-8', errors='replace')[:200]}")
            return None
        except Exception as e:
            print(f"[ffmpeg转WAV] 异常: {e}")
            return None
        finally:
            for tmp in (tmp_in, tmp_out):
                if tmp:
                    try:
                        if tmp.exists(): tmp.unlink()
                    except Exception:
                        pass

    def download_media(self, cdn_media_info: dict, filename: str = "", user_id: str = "") -> Optional[bytes]:
        cache_key = self._media_cache_key(cdn_media_info)

        if user_id:
            cached = self._get_user_cached_media(user_id, cache_key)
            if cached:
                return cached[0]
        
        cached = self._get_cached_media(cache_key)
        if cached:
            return cached[0]

        with self._media_download_lock:
            if cache_key in self._media_downloading:
                wait_event = self._media_downloading[cache_key]
            else:
                wait_event = None

        if wait_event:
            wait_event.wait(timeout=60)
            if user_id:
                cached = self._get_user_cached_media(user_id, cache_key)
                if cached:
                    return cached[0]
            cached = self._get_cached_media(cache_key)
            if cached:
                return cached[0]
            return None

        event = threading.Event()
        with self._media_download_lock:
            self._media_downloading[cache_key] = event

        try:
            encrypt_query_param = cdn_media_info.get("encrypt_query_param")
            aes_key_b64 = cdn_media_info.get("aes_key")
            
            if not encrypt_query_param:
                encrypt_query_param = cdn_media_info.get("encrypted_query_param")
            if not encrypt_query_param:
                return None
            
            if not aes_key_b64:
                aes_key_hex = cdn_media_info.get("aeskey") or cdn_media_info.get("aes_key_hex")
                if aes_key_hex:
                    aes_key_b64 = base64.b64encode(aes_key_hex.encode('utf-8')).decode('utf-8')
            
            if not aes_key_b64:
                return None

            download_url = self.CDN_BASE + "/download?encrypted_query_param=" + urllib.parse.quote(encrypt_query_param, safe='')

            print(f"[媒体下载] 正在从 CDN 下载...")
            req = urllib.request.Request(download_url)

            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()

                decoded_key = base64.b64decode(aes_key_b64)
                if len(decoded_key) == 16:
                    aes_key_bytes = decoded_key
                else:
                    aes_key_hex = decoded_key.decode('utf-8')
                    aes_key_bytes = bytes.fromhex(aes_key_hex)

                decrypted = self._aes_ecb_decrypt(data, aes_key_bytes)
                print(f"[媒体下载成功] 解密后大小: {len(decrypted)} bytes")

                mime = self._detect_mime(decrypted)
                if mime == 'audio/silk':
                    wav_data = self._silk_to_wav(decrypted)
                    if wav_data:
                        decrypted = wav_data
                        mime = 'audio/wav'
                        filename = filename.replace('.silk', '.wav') if filename else 'voice.wav'
                elif mime == 'audio/amr':
                    wav_data = self._ffmpeg_to_wav(decrypted)
                    if wav_data:
                        decrypted = wav_data
                        mime = 'audio/wav'
                        filename = filename.replace('.amr', '.wav') if filename else 'voice.wav'

                self._save_media_cache(cache_key, decrypted, mime, filename)
                
                if user_id:
                    self._save_user_media_cache(user_id, cache_key, decrypted, mime, filename)

                return decrypted

        except Exception as e:
            print(f"[媒体下载异常] {e}")
            return None
        finally:
            with self._media_download_lock:
                self._media_downloading.pop(cache_key, None)
            event.set()

    def download_media_from_message_item(self, message_item: dict) -> Optional[bytes]:
        cdn_media_info = self._extract_cdn_media(message_item)

        if cdn_media_info and cdn_media_info.get("encrypt_query_param"):
            return self.download_media(cdn_media_info)

        print("[下载失败] 消息项中未找到有效的媒体信息")
        return None
    
    def list_users(self) -> list:
        return list(self._context_tokens.keys())
    
    def get_current_user(self):
        return self._current_user
    
    def set_current_user(self, user_id: str):
        if user_id in self._context_tokens:
            self._current_user = user_id
            self._save_config()
            print(f"已切换到: {user_id}")
    
    def stop(self):
        self._running = False
        for timer in self._active_timers.values():
            timer.cancel()
        self._active_timers.clear()
        if self._http_server:
            self._http_server.shutdown()

def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 12 + "Sioboot" + " " * 18 + "║")
    print("║" + " " * 18 + "-无忧传递-" + " " * 22 + "║")
    print("║" + " " * 19 + "v2.3" + " " * 26 + "║")
    print("╚" + "═" * 58 + "╝")
    
    if is_termux():
        print("\n[TERMUX] 运行环境: Android/Termux")
        print("[TERMUX] 网络模式: 可能需要代理或 VPN 访问微信服务器")
        print("[TERMUX] 提示: 如果网络不稳定，程序会自动重试")
        print()
    
    bot = WeChatiLinkBot()
    
    bot.start_web_interface()
    
    if is_termux():
        print(f"\n[Sioboot] 📱 网页地址: http://localhost:{bot._web_port}")
        print("[TERMUX] 💡 使用方法:")
        print("   方法1: 在手机浏览器访问上述地址")
        print("   方法2: 在电脑浏览器访问 http://<你的IP>:{bot._web_port}")
        print("   (需确保手机和电脑在同一网络)")
        print("[TERMUX] 输入 /web 可再次显示地址\n")
    
    if bot.load_config():
        print("[sioboot]已获取到连接缓存")
    else:
        print("[sioboot]首次运行，请扫码连接（若控制台的二维码错乱可在网页或终端扫码!）")
        if not bot.login_with_qrcode():
            return
    
    bot.start_polling()
    
    print("[sioboot]后台监听已启动，等待消息...")
    print(f"[sioboot]网页地址: http://localhost:{bot._web_port}")
    
    users = bot.list_users()
    if users:
        print(f"\n已保存 {len(users)} 个会话")
        for uid in users:
            marker = "[sioboot]" if uid == bot.get_current_user() else "   "
            print(f"{marker}{uid}")
    else:
        print("\n暂未有任何会话")
        print("[sioboot]对方扫完二维码后必须先发送一条消息才能建立联系!")
    
    print("\n" + "┌" + "─" * 58 + "┐")
    print("│ 直接输入消息 -> 回复给当前用户" + " " * 23 + "│")
    print("│ /users  查看所有用户" + " " * 31 + "│")
    print("│ /switch 切换用户" + " " * 32 + "│")
    print("│ /web    打开网页聊天界面" + " " * 27 + "│")
    print("│ /quit   退出" + " " * 36 + "│")
    print("└" + "─" * 58 + "┘" + "\n")
    
    try:
        while True:
            user_input = input("send:").strip()
            if not user_input:
                continue
            if user_input == "/quit":
                break
            elif user_input == "/users":
                users = bot.list_users()
                if users:
                    print("[sioboot]用户列表:")
                    for i, uid in enumerate(users, 1):
                        marker = "▶" if uid == bot.get_current_user() else "  "
                        print(f"{marker}{i}. {uid}")
                else:
                    print("[sioboot]暂无用户")
                continue
            elif user_input.startswith("/switch "):
                target = user_input[8:].strip()
                bot.set_current_user(target)
                continue
            elif user_input == "/switch":
                users = bot.list_users()
                if len(users) <= 1:
                    print("[sioboot]只有一个用户，无需切换")
                    continue
                print("[sioboot]选择用户:")
                for i, uid in enumerate(users, 1):
                    print(f"  {i}. {uid}")
                try:
                    choice = input("[sioboot]请输入序号: ").strip()
                    idx = int(choice) - 1
                    if 0 <= idx < len(users):
                        bot.set_current_user(users[idx])
                    else:
                        print("[sioboot]无效序号")
                except ValueError:
                    print("[sioboot]请输入数字")
                continue
            elif user_input == "/web":
                bot._open_browser()
                continue
            else:
                current = bot.get_current_user()
                if not current:
                    print("[sioboot]没有可回复的用户，请让好友先发消息")
                    continue
                bot.send_text(current, user_input)
    except KeyboardInterrupt:
        print()
    finally:
        bot.stop()

if __name__ == "__main__":
    main()