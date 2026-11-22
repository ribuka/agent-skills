"""Tests for qiita_post.py with a fake Qiita API and a fake token store.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qiita_post.py"
ITEM_ID = "0123456789abcdef0123"
SYNONYMS = {"test": "テスト"}  # Qiita renames some tags to a canonical name


def load_module():
    spec = importlib.util.spec_from_file_location("qiita_post", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeQiita:
    """Records requests and keeps one item, like the Qiita items API."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.item: dict | None = None
        self.version = 0

    def _store(self, payload: dict) -> dict:
        self.version += 1
        self.item = {
            "id": ITEM_ID, "url": f"https://qiita.com/u/items/{ITEM_ID}",
            "title": payload["title"], "body": payload["body"], "private": payload["private"],
            "tags": [{"name": SYNONYMS.get(t["name"], t["name"]), "versions": []} for t in payload["tags"]],
            "updated_at": f"2026-11-22T10:00:0{self.version}+09:00",
        }
        return dict(self.item)

    def __call__(self, method: str, path: str, token: str, payload: dict | None = None) -> dict:
        assert token == "secret"
        self.calls.append((method, path, payload))
        if method == "POST":
            return self._store(payload)
        if method == "GET":
            return dict(self.item)
        if method == "PATCH":
            return self._store(payload)
        raise AssertionError(method)


@pytest.fixture
def qp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = load_module()
    fake = FakeQiita()
    monkeypatch.setattr(module, "api", fake)
    monkeypatch.setattr(module, "read_token", lambda: "secret")
    # Never depend on the user's real config.local.conf or home directory name.
    config_dir = tmp_path / "skill"
    config_dir.mkdir()
    (config_dir / "config.conf").write_text(
        f"DRAFTS_DIR={tmp_path / 'drafts'}\nPRIVATE_WORDS=山田太郎, acme\n", encoding="utf-8")
    monkeypatch.setattr(module, "SKILL_DIR", config_dir)
    monkeypatch.setattr(module.Path, "home", classmethod(lambda cls: tmp_path / "alice"))
    module.fake = fake
    return module


def article(tmp_path: Path, frontmatter: str, body: str = "# 見出し\n\n本文\n") -> Path:
    path = tmp_path / "a.md"
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return path


NEW = 'title: "タイトル: 例"\ntags: ["Python", "VSCode"]'


def test_create_forces_private_and_writes_back(qp, tmp_path: Path, capsys) -> None:
    path = article(tmp_path, NEW)
    assert qp.main(["create", str(path)]) == 0
    method, _, payload = qp.fake.calls[0]
    assert method == "POST" and payload["private"] is True and payload["tweet"] is False
    assert payload["title"] == "タイトル: 例" and payload["body"] == "# 見出し\n\n本文\n"
    meta, body = qp.read_article(path)
    assert meta["id"] == ITEM_ID and meta["private"] is True and body == "# 見出し\n\n本文\n"
    assert "private: true" in capsys.readouterr().out


def test_create_rejects_public_and_reposts(qp, tmp_path: Path, capsys) -> None:
    assert qp.main(["create", str(article(tmp_path, NEW + "\nprivate: false"))]) == 1
    assert qp.main(["create", str(article(tmp_path, NEW + f'\nid: "{ITEM_ID}"'))]) == 1
    assert qp.fake.calls == []
    assert capsys.readouterr().out.count("error: failed:") == 2


def test_missing_token_reports_no_token(qp, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(qp, "read_token", lambda: None)
    assert qp.main(["create", str(article(tmp_path, NEW))]) == 3
    assert "error: no-token:" in capsys.readouterr().out


@pytest.mark.parametrize("frontmatter", [
    'tags: ["Python"]',
    'title: "t"',
    'title: "t"\ntags: []',
    'title: "t"\ntags: ["a b"]',
    'title: "t"\ntags:\n  - Python',
    'title: "t"\ntags: ["Python"]\npublic: true',
])
def test_invalid_frontmatter(qp, tmp_path: Path, frontmatter: str) -> None:
    with pytest.raises(qp.Failure):
        qp.read_article(article(tmp_path, frontmatter))


def test_update_keeps_visibility_and_detects_remote_edits(qp, tmp_path: Path, capsys) -> None:
    path = article(tmp_path, NEW)
    qp.main(["create", str(path)])
    path.write_text(path.read_text(encoding="utf-8").replace("本文", "修正"), encoding="utf-8")
    assert qp.main(["update", str(path)]) == 0
    assert qp.fake.calls[-1][2]["private"] is True and "修正" in qp.fake.item["body"]

    qp.fake.item["updated_at"] = "2026-11-23T00:00:00+09:00"  # edited on Qiita
    assert qp.main(["update", str(path)]) == 4
    assert "error: out-of-sync:" in capsys.readouterr().out
    assert qp.main(["pull", str(path)]) == 0
    assert qp.main(["update", str(path)]) == 0


def test_publish_uses_remote_content_and_requires_sync(qp, tmp_path: Path) -> None:
    path = article(tmp_path, NEW)
    qp.main(["create", str(path)])
    path.write_text(path.read_text(encoding="utf-8").replace("本文", "未投稿の修正"), encoding="utf-8")
    assert qp.main(["publish", str(path)]) == 4
    assert qp.fake.item["private"] is True

    qp.main(["update", str(path)])
    assert qp.main(["publish", str(path)]) == 0
    payload = qp.fake.calls[-1][2]
    assert payload["private"] is False and "未投稿の修正" in payload["body"]
    assert qp.read_article(path)[0]["private"] is False
    calls = len(qp.fake.calls)
    assert qp.main(["publish", str(path)]) == 0
    assert all(method == "GET" for method, _, _ in qp.fake.calls[calls:])


@pytest.mark.parametrize("edit", [
    lambda body: body.replace("本文", "    本文"),    # indented: becomes a code block
    lambda body: body.replace("本文", "本文  "),      # trailing spaces: a line break
])
def test_publish_detects_whitespace_only_edits(qp, tmp_path: Path, edit) -> None:
    path = article(tmp_path, NEW)
    qp.main(["create", str(path)])
    meta, body = qp.read_article(path)
    qp.write_article(path, meta, edit(body))
    assert qp.main(["publish", str(path)]) == 4
    assert qp.fake.item["private"] is True and qp.fake.calls[-1][0] == "GET"


def test_publish_on_public_item_keeps_remote_edits_safe(qp, tmp_path: Path) -> None:
    path = article(tmp_path, NEW)
    qp.main(["create", str(path)])
    qp.main(["publish", str(path)])
    synced = path.read_text(encoding="utf-8")
    qp.fake.item.update(body="Qiita で編集\n", updated_at="2026-11-23T00:00:00+09:00")
    assert qp.main(["publish", str(path)]) == 4
    assert path.read_text(encoding="utf-8") == synced
    assert qp.main(["update", str(path)]) == 4
    assert qp.fake.item["body"] == "Qiita で編集\n"


def test_renamed_tag_is_written_back_so_publish_matches(qp, tmp_path: Path) -> None:
    path = article(tmp_path, 'title: "t"\ntags: ["test"]')
    qp.main(["create", str(path)])
    assert qp.read_article(path)[0]["tags"] == ["テスト"]
    assert qp.main(["publish", str(path)]) == 0


def test_draft_path_uses_config(qp, tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "config.conf").write_text("DRAFTS_DIR=~/unused\nPRIVATE_WORDS=\n", encoding="utf-8")
    (tmp_path / "config.local.conf").write_text(f"DRAFTS_DIR={tmp_path / 'drafts'}\n", encoding="utf-8")
    monkeypatch.setattr(qp, "SKILL_DIR", tmp_path)
    assert qp.main(["draft-path", "--slug", "copilot-permissions"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"path: {tmp_path / 'drafts'}") and out.strip().endswith("-copilot-permissions.md")
    assert (tmp_path / "drafts").is_dir()
    assert qp.main(["draft-path", "--slug", "Bad Slug"]) == 1


def test_shipped_config_is_valid() -> None:
    config = (SCRIPT.parents[1] / "config.conf").read_text(encoding="utf-8")
    assert "DRAFTS_DIR=~/Documents/qiita-post" in config and "\nPRIVATE_WORDS=\n" in config


@pytest.mark.parametrize("text, kind", [
    ("連絡先は taro.yamada@gmail.com です", "email address"),
    (r"C:\Users\taro\repos を開く", "user home path"),
    ("cd /Users/taro/work", "user home path"),
    ("cat /home/taro/.bashrc", "user home path"),
    ("token: " + "0123456789abcdef" * 2 + "01234567", "40-hex token"),
    ("GH_TOKEN=ghp_" + "A1b2C3d4E5" * 4, "GitHub token"),
    ("key = sk-ant-" + "x" * 30, "API key"),
    ("AKIAABCDEFGHIJKLMNOP", "AWS access key"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "private key"),
    ("書いた人: 山田太郎", "private word"),
    ("repo: ACME/tools", "private word"),
    ("~/alice-notes じゃなく alice のメモ", "private word"),
    # Japanese right before or after: Python's \b would see no boundary here.
    ("連絡先taro.yamada@gmail.comです", "email address"),
    ("トークンghp_" + "A" * 36 + "です", "GitHub token"),
    ("キーsk-" + "x" * 30 + "を使う", "API key"),
    ("鍵AKIAABCDEFGHIJKLMNOPです", "AWS access key"),
    ("場所はC:\\Users\\taro\\work", "user home path"),
    ("場所は/home/taro/work", "user home path"),
])
def test_private_info_is_detected(qp, text: str, kind: str) -> None:
    findings = qp.find_private_info(text, qp.private_words())
    assert findings and kind in findings[0]
    assert "taro.yamada" not in findings[0] and "ghp_A1b2C3" not in findings[0]  # masked


@pytest.mark.parametrize("text", [
    "user@example.com と git@github.com:owner/repo.git",
    r"%USERPROFILE%\.agents は C:\Users\<name>\.agents、C:\Users\Public も",
    "~/.agents/skills と /Users/you/work",
    "https://example.com/home/page",
    "commit 2d1ec5b と `@types/node`",
    "acmeco や pharmacy は別の語",
])
def test_ordinary_text_is_not_flagged(qp, text: str) -> None:
    assert qp.find_private_info(text, qp.private_words()) == []


def test_short_home_directory_name_is_a_private_word(qp, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(qp.Path, "home", classmethod(lambda cls: tmp_path / "li"))
    assert "li" in qp.private_words()
    assert qp.find_private_info("account: li", qp.private_words())
    assert qp.find_private_info("link と list", qp.private_words()) == []


def test_private_info_stops_create_update_and_publish(qp, tmp_path: Path, capsys) -> None:
    leaky = article(tmp_path, 'title: "acme の話"\ntags: ["Python"]')
    assert qp.main(["create", str(leaky)]) == 5
    assert "error: private-info: " in capsys.readouterr().out and qp.fake.calls == []

    path = article(tmp_path, NEW)
    qp.main(["create", str(path)])
    meta, body = qp.read_article(path)
    qp.write_article(path, meta, body + "\n連絡先 taro@corp.co.jp\n")
    calls = len(qp.fake.calls)
    assert qp.main(["update", str(path)]) == 5
    assert len(qp.fake.calls) == calls

    qp.fake.item["body"] = qp.fake.item["body"] + "C:/Users/taro/x\n"  # leaked via a Qiita edit
    qp.main(["pull", str(path)])
    assert qp.main(["publish", str(path)]) == 5
    assert qp.fake.item["private"] is True
