"""Tests for lib/speckled_gate/shell.py [T-F07-04]."""
import unittest

from speckled_gate import shell
from speckled_gate.shell import ShellAction as A, actions, split_commands


def W(target, detail=""):
    return A("write", target, detail)


# One positive case per row of the writer table (TASKS-F07, T-F07-04 step 5), plus
# redirects. Each command must produce at least the listed actions.
POSITIVE = [
    ("redirect >", "echo hi > out.txt", [W("out.txt")]),
    ("redirect >> and 2>", "make 2>err.log >>build.log", [W("err.log"), W("build.log")]),
    ("redirect &>", "npm test &> log.txt", [W("log.txt")]),
    ("redirect >|", "date >| stamp", [W("stamp")]),
    ("tee", "echo hi | tee -a a.txt b.txt", [W("a.txt"), W("b.txt")]),
    ("sed -i", "sed -i 's/a/b/' src/x.py", [W("src/x.py")]),
    ("sed -i with -e", "sed -i.bak -e 's/a/b/' -e 's/c/d/' x.py y.py", [W("x.py"), W("y.py")]),
    ("sed -i '' (macOS)", "sed -i '' 's/a/b/' x.py", [W("x.py")]),
    ("perl -pi -e", "perl -pi -e 's/a/b/' x.py", [W("x.py")]),
    ("cp", "cp -r src/a.py dest/", [W("dest/")]),
    ("cp -t", "cp -t dest a b", [W("dest")]),
    ("install", "install -m 644 build/app bin/app", [W("bin/app")]),
    ("mv", "mv old.py new.py", [A("move", "old.py"), W("new.py")]),
    ("rm", "rm a.txt b.txt", [A("delete", "a.txt"), A("delete", "b.txt")]),
    ("rmdir", "rmdir build", [A("delete", "build")]),
    ("unlink", "unlink link", [A("delete", "link")]),
    ("shred", "shred -u secret.key", [A("delete", "secret.key")]),
    ("rm -rf", "rm -rf build", [A("delete", "build"), A("rm-recursive-force")]),
    ("touch", "touch a b", [W("a"), W("b")]),
    ("truncate", "truncate -s 0 log.txt", [W("log.txt")]),
    ("mkdir", "mkdir -p src/new", [W("src/new")]),
    ("ln", "ln -s ../shared.py link.py", [W("link.py")]),
    ("dd", "dd if=/dev/zero of=disk.img bs=1M count=1", [W("disk.img")]),
    ("patch", "patch -p1 < fix.diff", [W(None, "patch")]),
    ("git apply", "git apply fix.diff", [W(None, "patch")]),
    ("git checkout --", "git checkout -- a.py b.py", [W("a.py"), W("b.py")]),
    ("git restore", "git restore src/x.py", [W("src/x.py")]),
    ("git reset --hard", "git reset --hard HEAD~1", [W(None, "repo-wide")]),
    ("git checkout .", "git checkout .", [W(None, "repo-wide")]),
    ("git clean -fd", "git clean -fd", [W(None, "repo-wide")]),
    ("git stash pop", "git stash pop", [W(None, "repo-wide")]),
    ("find -delete", "find . -name '*.pyc' -delete",
     [A("delete", None, "find"), A("rm-recursive-force", None, "find")]),
    ("find -exec rm", "find build -exec rm {} +",
     [A("delete", None, "find"), A("rm-recursive-force", None, "find")]),
    ("git commit", "git commit -m 'wip'", [A("git-commit")]),
    ("git -C commit", 'git -C ../speckled commit -m "x"', [A("git-commit")]),
    ("git -c commit", "git -c user.name=x commit -m y", [A("git-commit")]),
    ("git push", "git push origin main", [A("git-push")]),
    ("gh pr create", "gh pr create --fill", [A("pull-request")]),
    ("gh pr merge", "gh pr merge 12 --squash", [A("pull-request")]),
    ("hub pull-request", "hub pull-request -m x", [A("pull-request")]),
    ("claude --settings", "claude --settings '{\"x\": 1}' -p hi", [A("hooks-disabled")]),
    ("claude disableAllHooks", "claude -p 'do it' --settings='{\"disableAllHooks\":true}'",
     [A("hooks-disabled")]),
    ("git config core.hooksPath", "git config --local core.hooksPath /dev/null", [A("hooks-path")]),
    ("secret env argument", "cat .env", [A("reads-secret-env", ".env")]),
    ("secret env nested path", "grep KEY config/.env.production",
     [A("reads-secret-env", "config/.env.production")]),
    ("secret env redirect", "echo KEY=1 > .env.local",
     [W(".env.local"), A("reads-secret-env", ".env.local")]),
    ("secret env source", "source ./.env && npm start", [A("reads-secret-env", "./.env")]),
]

# Wrappers, nesting, operators and directory changes.
NESTED = [
    ("sudo env bash -c", 'sudo env X=1 bash -c "echo hi > out.txt"', [W("out.txt")]),
    ("bash -c inside sh -c", "bash -c 'sh -c \"rm -rf x\"'", [A("rm-recursive-force")]),
    ("bash -lc", "bash -lc 'git push'", [A("git-push")]),
    ("sudo -u", "sudo -u bob rm -rf /srv/x", [A("delete", "/srv/x"), A("rm-recursive-force")]),
    ("VAR= prefix", "FOO=1 /bin/rm -rf dir", [A("rm-recursive-force")]),
    ("nohup and time", "nohup time -p touch done.flag", [W("done.flag")]),
    ("xargs rm -rf", "ls | xargs rm -rf", [A("delete", None, "xargs"), A("rm-recursive-force", None, "xargs")]),
    ("xargs -I", "ls | xargs -I {} cp {} backup/", [W("backup/", "xargs")]),
    ("and-list", "npm test && rm -fr /tmp/x", [A("rm-recursive-force")]),
    ("command substitution", "echo $(rm -rf x)", [A("rm-recursive-force")]),
    ("backticks", "echo `rm -rf x`", [A("rm-recursive-force")]),
    ("$( ) in double quotes", 'echo "done: $(rm -rf x)"', [A("rm-recursive-force")]),
    ("backticks in double quotes", 'echo "now `git push`"', [A("git-push")]),
    ("nested substitution", "echo $(echo $(touch deep.txt))", [W("deep.txt")]),
    ("substitution with ) in quotes", "x=$(printf ')'; touch p.txt)", [W("p.txt")]),
    ("substitution as an argument", "cp a.py $(git rev-parse --show-toplevel)/b.py",
     [W(f"{shell._SUBST}/b.py")]),
    ("newline", "echo a\ntouch b.txt", [W("b.txt")]),
    ("cd then write", "cd ../speckled && touch hooks/x.py", [W("../speckled/hooks/x.py")]),
    ("cd then repo-wide", "cd ../speckled; git reset --hard", [W("../speckled", "repo-wide")]),
    ("git -C path", "git -C ../speckled checkout -- a.py", [W("../speckled/a.py")]),
    ("heredoc writes target", "cat > notes.md <<EOF\nrm -rf /\nEOF", [W("notes.md")]),
]

# Commands that must produce no actions at all.
NOTHING = [
    'echo "rm -rf /"',
    "echo 'git commit -m done'",
    "grep -r rm src",
    'echo "copy .env.example to .env"',
    "cat .env.example",
    "python gen.py",
    "ls -la",
    "git status",
    "git log --oneline -5",
    "git checkout main",
    "true 2>/dev/null",
    "cat <<'EOF'\nrm -rf x\ngit push\nEOF",
    "echo hi 2>&1",
    "echo '$(rm -rf x)'",          # single quotes: not run
    "echo '`git push`'",
    "echo $((1 + 2))",             # arithmetic, not a command
    "claude plugin validate --strict .",
]


class Positive(unittest.TestCase):
    def check(self, cases):
        for name, command, expected in cases:
            with self.subTest(name, command=command):
                got = actions(command)
                for action in expected:
                    self.assertIn(action, got)

    def test_writer_table(self):
        self.check(POSITIVE)

    def test_wrappers_nesting_and_operators(self):
        self.check(NESTED)


class Negative(unittest.TestCase):
    def test_commands_that_do_nothing(self):
        for command in NOTHING:
            with self.subTest(command=command):
                self.assertEqual(actions(command), [])

    def test_fd_number_is_not_a_file(self):
        self.assertEqual(actions("rm x.txt 2>/dev/null"), [A("delete", "x.txt")])

    def test_exact_results(self):
        # Checks that nothing extra is reported, not only that the expected actions are there.
        for command, expected in [
            ("sed -i '' 's/a/b/' x.py", [W("x.py")]),
            ("sed -i 's/a/b/' x.py", [W("x.py")]),
            ("perl -pi -e 's/a/b/' x.py", [W("x.py")]),
            ("mv a b c/", [A("move", "a"), A("move", "b"), W("c/")]),
            ("git commit -m 'touch x'", [A("git-commit")]),
            ("cp .env.example .env.local", [W(".env.local"), A("reads-secret-env", ".env.local")]),
        ]:
            with self.subTest(command=command):
                self.assertEqual(actions(command), expected)

    def test_heredoc_body_is_not_commands(self):
        got = actions("cat > notes.md <<EOF\nrm -rf /\ngit push\nEOF\ntouch after.txt")
        self.assertEqual(got, [W("notes.md"), W("after.txt")])


class Tokenizing(unittest.TestCase):
    def test_split_commands(self):
        self.assertEqual(split_commands("a 1 && b 2 | c; d &"), [["a", "1"], ["b", "2"], ["c"], ["d"]])

    def test_unclosed_quote(self):
        self.assertEqual(actions('echo "open'), [])
        self.assertIsNotNone(shell.last_error)

    def test_last_error_resets(self):
        actions('echo "open')
        actions("touch x")
        self.assertIsNone(shell.last_error)


if __name__ == "__main__":
    unittest.main()
