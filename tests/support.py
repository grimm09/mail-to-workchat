from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def config_text(*, notifier: str = "", reply_body: str | None = None) -> str:
    body = reply_body if reply_body is not None else (
        "안녕하세요.\\n\\n요청 번호 {case_id}를 확인했습니다.\\n\\n감사합니다."
    )
    return f'''
[app]
name = "Test app"
data_dir = "runtime"
templates_dir = "templates"
initial_sync = "baseline"
snippet_chars = 120

[[accounts]]
id = "test-mailbox"
label = "Test mailbox"
host = "imap.example.com"
username = "operator@example.com"
password_env = "TEST_MAILBOX_PASSWORD"

{notifier}

[[rules]]
id = "action-required"
name = "Action required"
notification_title = "Action required"
reply_body_seed = {body!r}

[rules.match]
sender_regex = "alerts@example\\\\.com"
subject_regex = "(?i)action required"
body_regex = "(?i)case id"

[rules.fields.case_id]
source = "body"
pattern = "(?im)^case id\\\\s*:\\\\s*(?P<value>[A-Z0-9-]+)"
required = true
'''.replace("'안녕하세요", '"안녕하세요').replace("감사합니다.'", '감사합니다."')


def fixture(name: str = "sample_alert.eml") -> Path:
    return PROJECT_ROOT / "tests" / "fixtures" / name


def workspace_tempdir() -> tempfile.TemporaryDirectory[str]:
    base = PROJECT_ROOT / ".test-tmp"
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base)
