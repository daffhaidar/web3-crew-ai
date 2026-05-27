import os
import zipfile
import subprocess
import shutil
from crewai.tools import tool

@tool("System Admin & Auto Learner")
def sysadmin_auto_learner(action: str, target: str) -> str:
    """
    Tool dewa untuk instalasi dan belajar mandiri.
    
    Args:
        action: 'install' (untuk uv pip), 'train_from_zip' (path lokal), atau 'clone_train' (url github).
        target: String target (URL atau path).
    """
    # 1. Install via git/uv
    if action == "install":
        print(f"[SysAdmin] Instalasi: {target}...")
        try:
            # Contoh target: 'git+https://github.com/CloakHQ/cloakbrowser'
            cmd = ["uv", "pip", "install", target]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return f"✅ Berhasil instal {target}!\n{result.stdout}"
        except subprocess.CalledProcessError as e:
            return f"❌ Gagal instal {target}. Error: {e.stderr}"

    # 2. Belajar dari ZIP lokal
    elif action == "train_from_zip":
        if not os.path.exists(target): return "❌ File tidak ada."
        extract_dir = "/tmp/bot_training_module"
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(target, 'r') as z: z.extractall(extract_dir)
        return _read_md_files(extract_dir)

    # 3. FITUR BARU: Belajar dari GitHub
    elif action == "clone_train":
        print(f"[SysAdmin] Cloning repo: {target}...")
        clone_dir = "/tmp/repo_training"
        if os.path.exists(clone_dir): shutil.rmtree(clone_dir)
        try:
            subprocess.run(["git", "clone", "--depth", "1", target, clone_dir], check=True)
            return _read_md_files(clone_dir)
        except Exception as e:
            return f"❌ Gagal clone: {e}"

    return "❌ Action invalid."

def _read_md_files(path: str) -> str:
    knowledge = []
    for root, _, files in os.walk(path):
        for file in files:
            if file.endswith('.md'):
                with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                    knowledge.append(f"--- {file} ---\n{f.read()}")
    return "✅ TRAINING SUCCESS!\n\n" + "\n\n".join(knowledge) if knowledge else "✅ Berhasil, tapi kaga ada .md"