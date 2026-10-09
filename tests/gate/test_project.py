"""Tests for lib/speckled_gate/project.py [T-F07-05]."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from speckled_gate.project import classify, find_project, load_project, refresh_registry, repo_for
from speckled_gate.shell import _SUBST

from .fixtures import make_project

CONFIG = """\
project: Acme
docs_dir: docs
enforcement: block
repos:
  - ../app
  - ../api
enforcement_exempt:
  - "*.lock"
  - "docs/*"
"""


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(os.path.realpath(self._tmp.name))
        self.paths = make_project(self.tmp, CONFIG, code_repos=["app", "api"])
        self.home = self.tmp / "home"
        self.plugin_data = self.tmp / "plugin-data"
        self.plugin_root = self.tmp / "plugin"
        for d in (self.home, self.plugin_data, self.plugin_root):
            d.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def find(self, cwd, plugin_root=None):
        return find_project(cwd, plugin_root or self.plugin_root, self.plugin_data, self.home)


class Discovery(Base):
    def test_from_inside_the_planning_repo(self):
        project = self.find(self.paths.root / "docs" / "tasks")
        self.assertEqual(project.root, self.paths.root)
        self.assertEqual(project.enforcement, "block")
        self.assertEqual(project.repos, [self.paths.repos["app"], self.paths.repos["api"]])
        self.assertEqual(project.repo_names, ["../app", "../api"])
        self.assertEqual(project.docs_dir, self.paths.root / "docs")
        self.assertIsNone(project.config_error)
        self.assertIsNone(project.wrong_start)

    def test_from_a_code_repo_is_a_wrong_start(self):
        self.assertIsNone(self.find(self.paths.repos["app"]))  # not registered yet
        refresh_registry(self.find(self.paths.root))
        (self.paths.repos["app"] / "src").mkdir()
        project = self.find(self.paths.repos["app"] / "src")
        self.assertIsNotNone(project)
        self.assertEqual(project.root, self.paths.root)
        self.assertEqual(project.enforcement, "block")
        self.assertEqual(project.wrong_start, self.paths.repos["app"])

    def test_registry_not_refreshed_from_a_wrong_start(self):
        refresh_registry(self.find(self.paths.root))
        registry = self.plugin_data / "projects.json"
        registry.write_text(registry.read_text().replace(str(self.paths.repos["api"]), "/gone/api"))
        before = registry.read_text()
        refresh_registry(self.find(self.paths.repos["app"]))
        self.assertEqual(registry.read_text(), before)

    def test_stale_registry_entry_is_ignored(self):
        refresh_registry(self.find(self.paths.root))
        (self.paths.root / "speckled.yaml").unlink()
        self.assertIsNone(self.find(self.paths.repos["app"]))

    def test_no_project(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.assertIsNone(self.find(elsewhere))


class Loading(Base):
    def write(self, text):
        (self.paths.root / "speckled.yaml").write_text(text)
        return load_project(self.paths.root, self.plugin_root, self.plugin_data, self.home)

    def test_modes(self):
        for text, mode in [("project: x\n", "off"), ("enforcement: off\n", "off"),
                           ("enforcement: WARN\nrepos: []\n", "warn"), ("enforcement: block\n", "block")]:
            with self.subTest(text=text):
                project = self.write(text)
                self.assertEqual(project.enforcement, mode)
                self.assertIsNone(project.config_error)

    def test_broken_yaml_with_block_fails_closed(self):
        project = self.write("enforcement: block\nrepos: [../app\n")
        self.assertEqual(project.enforcement, "block")
        self.assertIn("speckled.yaml", project.config_error)
        self.assertTrue(project.repos_unknown)

    def test_broken_yaml_without_enforcement_is_off(self):
        project = self.write("project: x\nrepos: [../app\n")
        self.assertEqual(project.enforcement, "off")

    def test_unknown_mode_is_block_with_error(self):
        project = self.write("enforcement: strict\n")
        self.assertEqual(project.enforcement, "block")
        self.assertIn("strict", project.config_error)

    def test_repos_must_be_a_list(self):
        project = self.write("enforcement: warn\nrepos: ../app\n")
        self.assertEqual(project.enforcement, "warn")
        self.assertIn("lists", project.config_error)


class Classify(Base):
    def setUp(self):
        super().setUp()
        self.project = self.find(self.paths.root)

    def cls(self, path, project=None):
        return classify(project or self.project, path)

    def test_every_protected_path(self):
        root, app, api = self.paths.root, self.paths.repos["app"], self.paths.repos["api"]
        for path in [root / "speckled.yaml", root / ".speckled" / "active-task",
                     root / ".speckled" / "log.jsonl", root / ".git" / "hooks" / "pre-commit",
                     root / ".claude" / "settings.json", root / ".claude" / "settings.local.json",
                     app / ".claude" / "settings.json", api / ".claude" / "settings.local.json",
                     self.home / ".claude" / "settings.json",
                     self.plugin_data / "projects.json",
                     self.plugin_root / "hooks" / "gate.py", self.plugin_root / "lib" / "x.py"]:
            with self.subTest(path=str(path.relative_to(self.tmp))):
                self.assertEqual(self.cls(path), "protected")

    def test_governed_and_free(self):
        root, app = self.paths.root, self.paths.repos["app"]
        self.assertEqual(self.cls(app / "src" / "main.py"), "governed")
        self.assertEqual(self.cls(app / ".claude" / "commands" / "x.md"), "governed")
        self.assertEqual(self.cls(root / "docs" / "frds" / "F01.md"), "free")
        self.assertEqual(self.cls(root / "README.md"), "free")
        self.assertEqual(self.cls(self.tmp / "elsewhere" / "x.txt"), "free")

    def test_exemptions(self):
        app = self.paths.repos["app"]
        self.assertEqual(self.cls(app / "poetry.lock"), "free")
        self.assertEqual(self.cls(app / "docs" / "guide" / "intro.md"), "free")  # * matches /
        self.assertEqual(self.cls(app / "src" / "docs.py"), "governed")

    def test_exemption_never_unprotects(self):
        (self.paths.root / "speckled.yaml").write_text(CONFIG + '  - ".claude/*"\n')
        project = self.find(self.paths.root)
        self.assertEqual(self.cls(self.paths.repos["app"] / ".claude" / "settings.json", project),
                         "protected")

    def test_dotdot_and_relative_paths(self):
        root, app = self.paths.root, self.paths.repos["app"]
        self.assertEqual(self.cls(root / "docs" / ".." / ".." / "app" / "x.py"), "governed")
        self.assertEqual(classify(self.project, "../app/x.py", cwd=root), "governed")
        self.assertEqual(classify(self.project, "speckled.yaml", cwd=root), "protected")

    def test_symlinks(self):
        root, app = self.paths.root, self.paths.repos["app"]
        (app / "src").mkdir()
        os.symlink(app / "src", root / "docs" / "linked-src")
        os.symlink(root / "speckled.yaml", self.tmp / "innocent.txt")
        self.assertEqual(self.cls(root / "docs" / "linked-src" / "x.py"), "governed")
        self.assertEqual(self.cls(self.tmp / "innocent.txt"), "protected")

    @unittest.skipUnless(sys.platform == "darwin", "case-insensitive file systems only")
    def test_case_differences(self):
        upper = Path(str(self.paths.root / "SPECKLED.yaml"))
        self.assertEqual(self.cls(upper), "protected")
        self.assertEqual(self.cls(Path(str(self.paths.repos["app"]).upper()) / "x.py"), "governed")

    def test_substitution_placeholder_is_governed(self):
        self.assertEqual(classify(self.project, f"{_SUBST}/b.py", cwd=self.tmp), "governed")

    def test_unreadable_config_governs_everything_outside_the_planning_repo(self):
        (self.paths.root / "speckled.yaml").write_text("enforcement: block\nrepos: [../app\n")
        project = self.find(self.paths.root)
        self.assertEqual(self.cls(self.tmp / "anything" / "x.py", project), "governed")
        self.assertEqual(self.cls(self.paths.root / "docs" / "x.md", project), "free")
        self.assertEqual(self.cls(self.paths.root / "speckled.yaml", project), "protected")

    def test_repo_for(self):
        app = self.paths.repos["app"]
        self.assertEqual(repo_for(self.project, app / "src" / "x.py"), ("../app", "src/x.py"))
        self.assertIsNone(repo_for(self.project, self.paths.root / "README.md"))


class DogfoodingLayout(Base):
    """D10: the plugin's working copy is itself a listed code repo."""

    def test_only_hooks_json_is_protected(self):
        plugin = self.paths.repos["api"]  # pretend the plugin is loaded from ../api
        project = self.find(self.paths.root, plugin_root=plugin)
        self.assertEqual(classify(project, plugin / "hooks" / "hooks.json"), "protected")
        self.assertEqual(classify(project, plugin / "hooks" / "gate.py"), "governed")
        self.assertEqual(classify(project, plugin / "lib" / "speckled_gate" / "rules.py"), "governed")


class Registry(Base):
    def test_contents_and_merge(self):
        path = self.plugin_data / "projects.json"
        path.write_text(json.dumps({"v": 1, "repos": {"/gone/repo": "/gone/plans"}}))
        refresh_registry(self.find(self.paths.root))
        data = json.loads(path.read_text())
        self.assertEqual(data["v"], 1)
        self.assertEqual(data["repos"], {str(self.paths.repos["app"]): str(self.paths.root),
                                         str(self.paths.repos["api"]): str(self.paths.root)})
        self.assertFalse((self.plugin_data / "projects.json.tmp").exists())

    def test_not_written_when_off(self):
        (self.paths.root / "speckled.yaml").write_text("enforcement: off\nrepos: [../app]\n")
        refresh_registry(self.find(self.paths.root))
        self.assertFalse((self.plugin_data / "projects.json").exists())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores permissions")
    def test_read_only_folder_is_ignored(self):
        os.chmod(self.plugin_data, 0o500)
        try:
            refresh_registry(self.find(self.paths.root))  # must not raise
            self.assertFalse((self.plugin_data / "projects.json").exists())
        finally:
            os.chmod(self.plugin_data, 0o700)

    def test_corrupt_registry_is_treated_as_empty(self):
        (self.plugin_data / "projects.json").write_text("{not json")
        self.assertIsNone(self.find(self.paths.repos["app"]))
        refresh_registry(self.find(self.paths.root))
        self.assertIsNotNone(self.find(self.paths.repos["app"]))


if __name__ == "__main__":
    unittest.main()
