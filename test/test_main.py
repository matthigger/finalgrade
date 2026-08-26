import pathlib
import shutil

import pytest

import finalgrade
from finalgrade.__main__ import main, parser

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


def _copy_test_data(tmp_path):
    """Copy test scope.csv and default policy to tmp_path."""
    f_scope = tmp_path / 'scope.csv'
    shutil.copy(test_folder / 'scope.csv', f_scope)
    f_policy = tmp_path / 'policy.yaml'
    shutil.copy(
        pathlib.Path(finalgrade.__file__).parent / 'policy.yaml',
        f_policy)
    return str(f_scope), str(f_policy)


class TestMainCLI:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(['--version'])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert finalgrade.__version__ in captured.out

    def test_no_subcommand_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            main(parser.parse_args([]))
        assert exc_info.value.code == 1

    def test_basic_run(self, tmp_path):
        """Run with default policy on test CSV"""
        f_scope, f_policy = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--policy', f_policy, '-q'])
        main(args)
        assert (tmp_path / 'grade_full.csv').exists()

    def test_custom_output(self, tmp_path):
        """-o should change output path"""
        f_scope, f_policy = _copy_test_data(tmp_path)
        f_out = str(tmp_path / 'my_grades.csv')
        args = parser.parse_args([
            'grade', f_scope, '--policy', f_policy, '-o', f_out, '-q'])
        main(args)
        assert pathlib.Path(f_out).exists()

    def test_per_student(self, tmp_path):
        """--per_student should create a per_student/ folder"""
        f_scope, f_policy = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--policy', f_policy, '--per_student', '-q'])
        main(args)
        per_stud_folder = tmp_path / 'per_student'
        assert per_stud_folder.exists()
        csvs = list(per_stud_folder.glob('*.csv'))
        assert len(csvs) == 5  # 5 students in test data

    def test_late_csv(self, tmp_path):
        """--late_csv should produce a late days CSV"""
        f_scope, f_policy = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--policy', f_policy, '--late_csv', 'late.csv',
            '-q'])
        main(args)
        assert (tmp_path / 'late.csv').exists()

    def test_resolve_config_existing(self, tmp_path):
        """Without --policy, should pick up existing policy.yaml"""
        f_scope, f_policy = _copy_test_data(tmp_path)
        args = parser.parse_args(['grade', f_scope, '-q'])
        main(args)
        assert (tmp_path / 'grade_full.csv').exists()

    def test_resolve_config_new(self, tmp_path):
        """Without --policy and no existing policy, should create one"""
        f_scope = tmp_path / 'scope.csv'
        shutil.copy(test_folder / 'scope.csv', f_scope)
        # no policy.yaml copied — should be auto-created
        args = parser.parse_args(['grade', str(f_scope), '-q'])
        main(args)
        assert (tmp_path / 'policy.yaml').exists()
        assert (tmp_path / 'grade_full.csv').exists()

    def test_new_config_flag(self, tmp_path):
        """--new-policy should create a timestamped policy"""
        f_scope, f_policy = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--new-policy', '-q'])
        main(args)
        # should have the original policy.yaml plus a new timestamped one
        policies = list(tmp_path.glob('policy*.yaml'))
        assert len(policies) == 2


class TestStudentCommand:
    """ the files students need, from the command line """

    YAML = """\
category:
  weight:
    hw: 50
    quiz: 50
waive:
  bob@u.edu: hw2
note:
  carol@u.edu: a private word
"""

    def _run(self, f_scope_std, extra_list=()):
        tmp_path = f_scope_std.parent
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text(self.YAML)

        main(parser.parse_args(['student', str(f_scope_std), '--policy',
                                str(f_policy), '-q', *extra_list]))
        return tmp_path / 'student'

    def test_one_policy_and_a_csv_each(self, f_scope_std):
        out = self._run(f_scope_std)

        assert (out / 'policy_student.yaml').exists()
        assert sorted(p.name for p in (out / 'grades').iterdir()) == \
            ['anders_alice.csv', 'baker_bob.csv', 'chen_carol.csv']

    def test_each_csv_is_one_student(self, f_scope_std):
        out = self._run(f_scope_std)
        text = (out / 'grades' / 'anders_alice.csv').read_text()

        assert 'alice@u.edu' in text
        assert 'bob' not in text
        assert len(text.strip().split('\n')) == 2

    def test_the_policy_names_nobody(self, f_scope_std):
        out = self._run(f_scope_std)
        text = (out / 'policy_student.yaml').read_text()

        for email in ('alice@u.edu', 'bob@u.edu', 'carol@u.edu'):
            assert email not in text
        assert 'a private word' not in text

    def test_one_student_on_request(self, f_scope_std):
        out = self._run(f_scope_std, ['--email', 'carol@u.edu'])

        assert [p.name for p in (out / 'grades').iterdir()] == \
            ['chen_carol.csv']
        # the policy is the class's either way, because it is the class's
        assert (out / 'policy_student.yaml').exists()

    def test_a_student_who_is_not_there(self, f_scope_std):
        with pytest.raises(SystemExit) as exc_info:
            self._run(f_scope_std, ['--email', 'nobody@u.edu'])

        assert exc_info.value.code == 2

    def test_somewhere_else_on_request(self, f_scope_std):
        f_out = f_scope_std.parent / 'handouts'
        self._run(f_scope_std, ['-o', str(f_out)])

        assert (f_out / 'policy_student.yaml').exists()
        assert (f_out / 'grades' / 'anders_alice.csv').exists()

    def test_the_pair_grades_an_unadjusted_student(self, f_scope_std):
        """ the whole reason the two files travel together

        Alice is the one this policy singles out for nothing, so the shared
        file is exactly right for her.  Bob has a waiver in it, and would
        have to write that line in himself.
        """
        import warnings

        from finalgrade.policy import Policy

        out = self._run(f_scope_std)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            policy = Policy.from_file(f_scope_std.parent / 'policy.yaml')
            _, df_class = policy(str(f_scope_std))

            mine = Policy.from_file(out / 'policy_student.yaml')
            _, df_mine = mine(str(out / 'grades' / 'anders_alice.csv'))

        assert list(df_mine.index) == ['alice@u.edu']
        assert df_mine.at['alice@u.edu', 'mean'] == \
            df_class.at['alice@u.edu', 'mean']
