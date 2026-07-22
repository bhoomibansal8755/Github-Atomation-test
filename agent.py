import subprocess
import os
import json
import time
import google.generativeai as genai
from datetime import datetime
from config import GEMINI_API_KEY, REPO_PATH, GIT_BRANCH, COMMIT_PREFIX

# ==============================
# PATHS
# ==============================
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
TASKS_FILE  = os.path.join(BASE_DIR, "tasks.json")
LOG_FILE    = os.path.join(BASE_DIR, "agent.log")

# ==============================
# LOGGING
# ==============================
def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ==============================
# TASK MANAGER
# ==============================
def load_tasks():
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tasks(data):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_next_pending_task(data):
    """Sabse pehla pending task return karo"""
    for task in data["tasks"]:
        if task["status"] == "pending":
            return task
    return None  # Saare tasks done!

def mark_task_done(data, task_id):
    """Task ko done mark karo aur timestamp daalo"""
    for task in data["tasks"]:
        if task["id"] == task_id:
            task["status"] = "done"
            task["committed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    save_tasks(data)

# ==============================
# FILE READER
# ==============================
def read_repo_file(filename):
    """Portfolio repo se file padhna"""
    filepath = os.path.join(REPO_PATH, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        log(f"Read existing file: {filename} ({len(content)} chars)")
        return content
    log(f"File not found, will create new: {filename}", "WARN")
    return ""

def write_repo_file(filename, content):
    """Portfolio repo mein file likhna"""
    filepath = os.path.join(REPO_PATH, filename)
    # Folder bhi bana do agar exist nahi karta
    os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"File written: {filename} ({len(content)} chars)")

# ==============================
# GEMINI CODE GENERATOR
# ==============================
def generate_code(filename, task_description, existing_code):
    """Gemini se updated code lena"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.5-flash")

    if existing_code:
        prompt = f"""You are a frontend developer working on a portfolio website.

FILE: `{filename}`

CURRENT FILE CONTENT:
{existing_code}

TODAY'S TASK: {task_description}

STRICT RULES:
1. Return ONLY the complete updated file content
2. Keep ALL existing code — only add or modify what the task requires
3. NO markdown backticks, NO explanation, NO comments about what you changed
4. Write clean, production-quality code
5. Changes should look like a real developer's commit — meaningful but not overwhelming
"""
    else:
        prompt = f"""You are a frontend developer starting a portfolio website from scratch.

FILE TO CREATE: `{filename}`

TASK: {task_description}

STRICT RULES:
1. Return ONLY the raw file content
2. NO markdown backticks, NO explanation
3. Write clean, modern, production-quality code
"""

    log(f"Calling Gemini API for: {filename}")
    response = model.generate_content(prompt)
    
    # Clean up agar Gemini ne backticks daale toh
    code = response.text.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        # Pehli aur aakhri line hata do (```html ... ```)
        code = "\n".join(lines[1:-1]).strip()
    
    log(f"Code received from Gemini: {len(code)} chars")
    return code

# ==============================
# GIT OPERATIONS
# ==============================
def run_git(cmd):
    """Git command chalao"""
    result = subprocess.run(
        cmd,
        cwd=REPO_PATH,
        capture_output=True,
        text=True,
        shell=True
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        log(f"GIT OK: {cmd[:50]} → {output[:100]}")
        return True
    else:
        log(f"GIT FAIL: {cmd[:50]} → {output[:200]}", "ERROR")
        return False

def build_commit_message(filename, task_description):
    """Conventional commit message banana"""
    ext = filename.split(".")[-1]
    prefix = COMMIT_PREFIX.get(ext, "chore")
    # Task description ko 60 chars tak cut karo
    short_task = task_description[:60]
    return f"{prefix}({filename}): {short_task}"

def git_commit_push(filename, task_description):
    """Add → Commit → Push"""
    commit_msg = build_commit_message(filename, task_description)
    
    success = all([
        run_git("git add ."),
        run_git(f'git commit -m "{commit_msg}"'),
        run_git(f"git push origin {GIT_BRANCH}"),
    ])
    
    if success:
        log(f"Successfully pushed: {commit_msg}")
    else:
        log(f"Push failed for: {commit_msg}", "ERROR")
    
    return success

# ==============================
# MAIN AGENT RUN
# ==============================
def run_agent():
    log("=" * 50)
    log("AI Commit Agent — Starting")
    log("=" * 50)

    # Tasks load karo
    data = load_tasks()
    
    # Next pending task lo
    task = get_next_pending_task(data)
    
    if not task:
        log("ALL TASKS COMPLETED! tasks.json mein koi pending task nahi.", "WARN")
        log("Naye tasks daalo tasks.json mein aur status 'pending' karo.")
        return

    log(f"Task #{task['id']}: [{task['file']}] {task['task']}")

    try:
        # Step 1: Existing file padhna
        existing_code = read_repo_file(task["file"])

        # Step 2: Gemini se code generate karna
        new_code = generate_code(task["file"], task["task"], existing_code)

        # Step 3: File likhna
        write_repo_file(task["file"], new_code)

        # Step 4: Git push
        success = git_commit_push(task["file"], task["task"])

        # Step 5: Task mark done
        if success:
            mark_task_done(data, task["id"])
            log(f"Task #{task['id']} marked as DONE ✓")
        else:
            log(f"Task #{task['id']} push failed — will retry next run", "ERROR")

    except Exception as e:
        log(f"Exception: {str(e)}", "ERROR")

    log("Agent run complete.")
    log("=" * 50)

# ==============================
if __name__ == "__main__":
    run_agent()