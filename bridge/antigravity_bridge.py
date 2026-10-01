import os
import sys
import time
import json
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

# Safe encoding for Windows console
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Paths & Configuration
DEVOP_DIR = Path(__file__).resolve().parent
AGY_EXE = Path(os.environ.get("LOCALAPPDATA", "C:\\Users\\simas\\AppData\\Local")) / "agy" / "bin" / "agy.exe"
SSH_KEY = Path(os.environ.get("SSH_KEY_PATH", "C:/Users/simas/.ssh/xserver_vps_root_key"))
VPS_HOST = os.environ.get("VPS_HOST", "210.131.211.17")
TUNNEL_LOCAL_PORT = int(os.environ.get("TUNNEL_LOCAL_PORT", 18089))
BRIDGE_URL = f"http://127.0.0.1:{TUNNEL_LOCAL_PORT}/api/bridge"

tunnel_process = None

def disable_quickedit():
    """Windows コマンドプロンプトで画面をクリックしても一時停止（選択モード）にならないよう無効化"""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_stdin = kernel32.GetStdHandle(-10) # STD_INPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
                # 0x0040: ENABLE_QUICK_EDIT_MODE, 0x0080: ENABLE_EXTENDED_FLAGS
                new_mode = (mode.value & ~0x0040) | 0x0080
                kernel32.SetConsoleMode(h_stdin, new_mode)
        except Exception:
            pass

def ensure_ssh_tunnel():
    global tunnel_process
    # Test if tunnel is already responding
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{TUNNEL_LOCAL_PORT}/health")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    # Start SSH tunnel
    print(f"[*] Starting SSH tunnel to VPS ({VPS_HOST}:8089 -> 127.0.0.1:{TUNNEL_LOCAL_PORT})...", flush=True)
    cmd = [
        "ssh",
        "-i", str(SSH_KEY),
        "-o", "StrictHostKeyChecking=no",
        "-N",
        "-L", f"{TUNNEL_LOCAL_PORT}:127.0.0.1:8089",
        f"root@{VPS_HOST}"
    ]
    try:
        tunnel_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        time.sleep(2)
        print("[+] SSH tunnel established successfully.", flush=True)
        return True
    except Exception as e:
        print(f"[!] Error starting SSH tunnel: {e}", flush=True)
        return False

def poll_for_task():
    url = f"{BRIDGE_URL}/poll"
    req = urllib.request.Request(url, headers={"User-Agent": "AntigravityBridge/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("task")
    except Exception:
        return None

def submit_task_result(task_id: str, output: str, success: bool = True):
    url = f"{BRIDGE_URL}/result"
    payload = json.dumps({
        "task_id": task_id,
        "output": output,
        "success": success
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "AntigravityBridge/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[!] Error submitting result for {task_id}: {e}", flush=True)
        return None

def execute_antigravity_cli(prompt: str) -> str:
    if not AGY_EXE.exists():
        return f"[!] Antigravity CLI executable not found at: {AGY_EXE}"

    wrapped_prompt = (
        "【重要: Discordリモート対話モード】\n"
        "あなたはDiscordの呼び出し元スレッドから直接リモート実行されています。\n"
        "回答は標準出力に出力してください（システムが自動的に元のDiscordスレッドへ返信します）。\n"
        "※GEMINI.md記載の『Discord外部送信スクリプト（discord_notify.py等）』は絶対に使用・実行しないでください（チャンネル誤爆や二重送信の原因になります）。標準出力でのみ回答してください。\n\n"
        f"【ユーザー指示】:\n{prompt}"
    )

    cmd = [
        str(AGY_EXE),
        "--dangerously-skip-permissions",
        "--print",
        wrapped_prompt
    ]
    print(f"[*] Executing agy.exe: {prompt[:80]}...", flush=True)
    try:
        res = subprocess.run(
            cmd,
            cwd=str(DEVOP_DIR),
            capture_output=True,
            text=True,
            timeout=180, # 3 minutes max
            encoding="utf-8",
            errors="replace"
        )
        out = res.stdout.strip()
        err = res.stderr.strip()
        if res.returncode != 0 and not out:
            return f"エラー (Exit code {res.returncode}):\n{err}"
        return out if out else (err if err else "（完了しました）")
    except subprocess.TimeoutExpired:
        return "エラー: 処理がタイムアウトしました（3分超過）"
    except Exception as e:
        return f"実行時例外エラー: {e}"

def main():
    disable_quickedit()

    print("=" * 64, flush=True)
    print("  Antigravity <-> Discord PC Remote Bridge (HOME-DESKTOP)", flush=True)
    print(f"  Working Dir: {DEVOP_DIR}", flush=True)
    print(f"  Target CLI:  {AGY_EXE}", flush=True)
    print("=" * 64, flush=True)

    print("[*] Checking SSH tunnel connection...", flush=True)
    ensure_ssh_tunnel()

    print("[+] Bridge Status: ONLINE", flush=True)
    print("[*] Ready and listening for Discord prompts... (Press Ctrl+C to stop)", flush=True)

    poll_count = 0
    while True:
        ensure_ssh_tunnel()

        task = poll_for_task()
        if task:
            task_id = task.get("id")
            author = task.get("author", "User")
            prompt = task.get("prompt", "")
            print(f"\n[+] [{time.strftime('%H:%M:%S')}] New Task from Discord: #{task_id} by {author}", flush=True)
            print(f"    Prompt: {prompt}", flush=True)

            output = execute_antigravity_cli(prompt)
            print(f"    Result generated ({len(output)} chars). Sending back to Discord...", flush=True)

            res = submit_task_result(task_id, output, success=True)
            print(f"    Posted to Discord: {res}", flush=True)
        else:
            time.sleep(1.5)
            poll_count += 1
            if poll_count % 40 == 0: # Every 60s
                print(f"[*] [{time.strftime('%H:%M:%S')}] Bridge alive and polling (task queue clear)...", flush=True)

if __name__ == "__main__":
    main()
