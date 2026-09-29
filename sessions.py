import json
from pathlib import Path

SESSION_DIR=Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)

def load_session(session_id):
    path=SESSION_DIR/f"{session_id}.json"

    if not path.exists():
        return [
        {
        "role":"system",
        "content":"你是GIS专家。"
        },
    ]
    with open(path,"r",encoding="utf-8") as f:
        return json.load(f)

def save_session(session_id,messages):
    path=SESSION_DIR/f"{session_id}.json"
    with open(path,"w",encoding="utf-8") as f:
        json.dump(
            messages,
            f,
            ensure_ascii=False,
            indent=2,
        )