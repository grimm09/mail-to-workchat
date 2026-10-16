from __future__ import annotations

import re
import shutil
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from tests.support import PROJECT_ROOT, fixture, workspace_tempdir

from mail_to_workchat.app import Application
from mail_to_workchat.config import load_config
from mail_to_workchat.templates.learning import build_proposal


ROOT_DOCS = ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md")
EXAMPLES = (
    ("en", "config/config.en.example.toml", "templates.example/en/action-required.toml", "Hello,"),
    ("zh-CN", "config/config.zh-CN.example.toml", "templates.example/zh-CN/action-required.toml", "您好，"),
    ("ko", "config/config.example.toml", "templates.example/action-required.toml", "안녕하세요."),
)


def documentation_pairs():
    originals = [PROJECT_ROOT / name for name in ROOT_DOCS]
    originals.extend(path for path in sorted((PROJECT_ROOT / "docs").glob("*.md"))
                     if not path.name.endswith(".zh-CN.md"))
    return [(path, path.with_name(f"{path.stem}.zh-CN.md")) for path in originals]


def prose(text: str) -> str:
    # These docs use fenced code blocks and ordinary inline Markdown links.
    return re.sub(r"(?ms)^```[^\n]*\n.*?^```[ \t]*$", "", text)


def heading_anchors(text: str) -> set[str]:
    headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", prose(text))
    return {re.sub(r"[^\w\s-]", "", heading.lower()).strip().replace(" ", "-")
            for heading in headings}


class BilingualDocumentationTests(unittest.TestCase):
    def test_every_document_has_reciprocal_language_links(self):
        pairs = documentation_pairs()
        expected = {path.name for pair in pairs for path in pair if path.parent.name == "docs"}
        self.assertEqual({path.name for path in (PROJECT_ROOT / "docs").glob("*.md")}, expected)
        for english, chinese in pairs:
            with self.subTest(document=english.name):
                self.assertTrue(chinese.is_file(), f"missing {chinese.name}")
                self.assertIn(f"({chinese.name})", english.read_text(encoding="utf-8"))
                self.assertIn(f"({english.name})", chinese.read_text(encoding="utf-8"))

    def test_local_markdown_links_and_section_anchors_resolve(self):
        for pair in documentation_pairs():
            for source in pair:
                text = prose(source.read_text(encoding="utf-8"))
                for link in re.findall(r"\[[^\]\n]+\]\(([^\s)]+)\)", text):
                    parts = urlsplit(link)
                    if parts.scheme or parts.netloc:
                        continue
                    with self.subTest(document=source.name, link=link):
                        target = (source.parent / unquote(parts.path)).resolve() if parts.path else source
                        self.assertIn(PROJECT_ROOT.resolve(), target.parents)
                        self.assertTrue(target.is_file(), f"broken link: {link}")
                        if parts.fragment:
                            self.assertIn(unquote(parts.fragment), heading_anchors(target.read_text(encoding="utf-8")))

    def test_readmes_keep_release_and_privacy_boundaries(self):
        for name in ("README.md", "README.zh-CN.md"):
            with self.subTest(document=name):
                text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
                for marker in ("0.2.1", "Alpha", "MIT", "LICENSE", "reply_body_seed"):
                    self.assertIn(marker, text)
                suffix = ".zh-CN" if name.endswith(".zh-CN.md") else ""
                for guide in ("privacy", "security-review", "languages"):
                    self.assertIn(f"docs/{guide}{suffix}.md", text)


class LocalizedExampleTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect"):
            guard = patch(target, side_effect=AssertionError("examples must not use the network"))
            guard.start()
            self.addCleanup(guard.stop)

    @staticmethod
    def _application(config_name: str, root: Path) -> Application:
        config = load_config(PROJECT_ROOT / config_name)
        app = replace(config.app, data_dir=root / "runtime", templates_dir=root / "templates")
        return Application(replace(config, app=app))

    def test_variants_change_only_language_and_display_text(self):
        normalized = []
        for language, config_name, _, _ in EXAMPLES:
            with self.subTest(language=language):
                path = PROJECT_ROOT / config_name
                config = load_config(path)
                self.assertEqual(config.app.default_reply_language, language)
                self.assertEqual(config.app.initial_sync, "baseline")
                self.assertFalse(config.interaction.enabled)
                self.assertTrue(config.interaction.template_confirmation_required)
                self.assertTrue(all(not bot.enabled and bot.require_mention for bot in config.bots))
                self.assertEqual(config.rules[0].reply_language, language)
                self.assertTrue(config.rules[0].reply_body_seed.strip())
                raw = tomllib.loads(path.read_text(encoding="utf-8"))
                raw["app"].pop("default_reply_language")
                for account in raw["accounts"]:
                    account.pop("label")
                for rule in raw["rules"]:
                    for field in ("name", "notification_title", "reply_language", "reply_body_seed"):
                        rule.pop(field)
                normalized.append(raw)
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[0], normalized[2])

    def test_each_configuration_previews_and_approves_offline(self):
        for language, config_name, _, greeting in EXAMPLES:
            with self.subTest(language=language), workspace_tempdir() as directory:
                app = self._application(config_name, Path(directory))
                first = app.preview_eml(fixture())
                self.assertTrue(first.matched)
                self.assertEqual(first.draft_status, "needs_review")
                self.assertIsNotNone(first.draft)
                self.assertIn(greeting, first.draft.body)
                self.assertIn("EX-1001", first.draft.body)
                self.assertNotIn("{case_id}", first.draft.body)
                proposal = app.templates.load_proposal("action-required")
                self.assertEqual(proposal.language, language)
                self.assertFalse(proposal.approved)
                self.assertIn("{case_id}", proposal.reply_body)
                self.assertNotIn("EX-1001", proposal.reply_body)
                app.templates.approve("action-required")
                approved = app.preview_eml(fixture())
                self.assertEqual(approved.draft_status, "ready")
                self.assertEqual(approved.draft.body, first.draft.body)
                self.assertEqual(app.database.processed_count(), 0)

    def test_each_selected_template_renders_without_ambiguity(self):
        for language, config_name, template_name, greeting in EXAMPLES:
            with self.subTest(language=language), workspace_tempdir() as directory:
                app = self._application(config_name, Path(directory))
                shutil.copyfile(PROJECT_ROOT / template_name, app.config.app.templates_dir / "action-required.toml")
                templates = app.templates.load_approved()
                self.assertEqual(len(templates), 1)
                self.assertEqual(templates[0].language, language)
                self.assertEqual(templates[0].match, app.config.rules[0].match)
                self.assertEqual(templates[0].fields, app.config.rules[0].fields)
                result = app.preview_eml(fixture())
                self.assertEqual(result.draft_status, "ready")
                self.assertIn(greeting, result.draft.body)
                self.assertIn("EX-1001", result.draft.body)
                self.assertIsNone(result.proposal_path)

    def test_empty_seed_retains_documented_korean_fallback(self):
        config = load_config(PROJECT_ROOT / "config/config.en.example.toml")
        proposal = build_proposal(replace(config.rules[0], reply_body_seed=""), {"case_id": "EX-1001"})
        self.assertEqual(proposal.language, "en")
        self.assertIn("안녕하세요", proposal.reply_body)
        self.assertIn("{case_id}", proposal.reply_body)


if __name__ == "__main__":
    unittest.main()
