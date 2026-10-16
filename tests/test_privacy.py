from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from tests.support import PROJECT_ROOT, workspace_tempdir


def public_release_files(root: Path = PROJECT_ROOT):
    """Scan the publication surface, not ignored operator secrets and runtime state."""
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, check=True, capture_output=True,
        )
        paths = [root / name for name in result.stdout.decode("utf-8").split("\0") if name]
    else:
        paths = [root / name for name in (
            "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE",
            "README.zh-CN.md", "CHANGELOG.zh-CN.md", "CONTRIBUTING.zh-CN.md", "SECURITY.zh-CN.md",
            "pyproject.toml", "MANIFEST.in", "Dockerfile", ".env.example", ".gitignore", ".dockerignore", ".gitattributes",
            "config/config.example.toml", "config/config.en.example.toml", "config/config.zh-CN.example.toml",
        )]
        for name in ("src", "tests", "docs", "templates.example", ".github"):
            paths.extend((root / name).rglob("*"))
    for path in sorted(set(paths)):
        if path.is_file() and "__pycache__" not in path.parts:
            if path.is_symlink() or root.resolve() not in path.resolve().parents:
                raise AssertionError("release files must not escape the project")
            yield path


def private_release_artifact(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return (
        (path.name.startswith(".env") and path.name != ".env.example")
        or path.suffix.lower() in {".sqlite3", ".db", ".log"}
        or path.name.lower().endswith((".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal", ".db-wal", ".db-shm", ".db-journal"))
        or path.name.endswith((".local.toml", ".local.json"))
        or relative.as_posix() == "config/config.toml"
        or relative.parts[0] in {".runtime", "data", "drafts", "proposals", "templates"}
    )


class PrivacyRegressionTests(unittest.TestCase):
    @staticmethod
    def _public_text_files():
        for path in public_release_files():
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and ".git" not in path.parts
                and ".test-tmp" not in path.parts
                and path.suffix.lower() not in {".pyc", ".sqlite3", ".db"}
            ):
                try:
                    yield path, path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue

    def test_repository_contains_no_known_personal_markers(self):
        blocked = {
            "consumer-mail-domain": re.compile(r"@163\.com", re.IGNORECASE),
            "source-business-name": re.compile("cou" + "pang", re.IGNORECASE),
            "windows-production-path": re.compile(r"[A-Za-z]:\\\\(?:Users|hermes)\\", re.IGNORECASE),
            "literal-dingtalk-token": re.compile(r"access_token=[A-Za-z0-9_-]{16,}"),
            "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            "github-token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
            "cloud-access-key": re.compile(r"AKIA[A-Z0-9]{16}"),
        }
        failures = []
        for path, text in self._public_text_files():
            for label, pattern in blocked.items():
                if pattern.search(text):
                    failures.append(f"{label}: {path.relative_to(PROJECT_ROOT)}")
        self.assertEqual(failures, [])

    def test_literal_example_emails_use_only_reserved_domain(self):
        unexpected = []
        email_pattern = re.compile(r"[A-Z0-9._%+\-]+@([-A-Z0-9.\\]+)", re.IGNORECASE)
        for path, text in self._public_text_files():
            for match in email_pattern.finditer(text):
                domain = match.group(1).replace("\\", "").rstrip(".").lower()
                if "." in domain and domain != "example.com":
                    unexpected.append(f"{path.relative_to(PROJECT_ROOT)}: {domain}")
        self.assertEqual(unexpected, [])

    def test_no_runtime_or_secret_artifacts_are_present(self):
        forbidden = [str(path.relative_to(PROJECT_ROOT)) for path in public_release_files()
                     if private_release_artifact(path, PROJECT_ROOT)]
        self.assertEqual(forbidden, [])

    def test_ignored_operator_files_are_not_scanned_but_forced_git_files_are(self):
        with workspace_tempdir() as directory:
            root = Path(directory)
            (root / ".gitignore").write_text(".env\nconfig/config.toml\n", encoding="utf-8")
            (root / ".env").write_text("SYNTHETIC_VALUE=local-only\n", encoding="utf-8")
            (root / "config").mkdir()
            config = root / "config/config.toml"
            config.write_text("# synthetic local configuration\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            self.assertNotIn(config, list(public_release_files(root)))
            self.assertNotIn(root / ".env", list(public_release_files(root)))
            subprocess.run(["git", "add", "-f", "config/config.toml"], cwd=root, check=True, capture_output=True)
            paths = list(public_release_files(root))
            self.assertIn(config, paths)
            self.assertTrue(private_release_artifact(config, root))

    def test_source_archive_scan_also_ignores_private_operator_config(self):
        with workspace_tempdir() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config/config.toml").write_text("# synthetic local configuration\n", encoding="utf-8")
            (root / "config/personal.local.toml").write_text("# synthetic private configuration\n", encoding="utf-8")
            public_names = (
                "README.md", "README.zh-CN.md", "CHANGELOG.md", "CHANGELOG.zh-CN.md",
                "CONTRIBUTING.md", "CONTRIBUTING.zh-CN.md", "SECURITY.md", "SECURITY.zh-CN.md",
                "config/config.example.toml", "config/config.en.example.toml", "config/config.zh-CN.example.toml",
                "docs/languages.md", "docs/languages.zh-CN.md",
                "templates.example/en/action-required.toml", "templates.example/zh-CN/action-required.toml",
            )
            expected = {root / name for name in public_names}
            for path in expected:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# public example\n", encoding="utf-8")
            self.assertEqual(set(public_release_files(root)), expected)

    def test_database_sidecars_are_private_even_outside_runtime_directory(self):
        for name in ("state.sqlite3-wal", "state.sqlite3-shm", "state.sqlite3-journal", "state.db-wal", "state.db-shm", "state.db-journal"):
            with self.subTest(name=name):
                self.assertTrue(private_release_artifact(PROJECT_ROOT / name, PROJECT_ROOT))

    def test_release_has_no_smtp_or_attachment_download_implementation(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("import smtplib", source)
        self.assertNotIn("urlretrieve", source)
        self.assertNotIn("requests.get", source)


if __name__ == "__main__":
    unittest.main()
