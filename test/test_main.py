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
    """ the two files each student needs, from the command line """

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

    def test_a_folder_per_student(self, f_scope_std):
        out = self._run(f_scope_std)

        assert sorted(p.name for p in out.iterdir()) == \
            ['anders_alice', 'baker_bob', 'chen_carol']
        for folder in out.iterdir():
            assert (folder / 'policy.yaml').exists()
            assert (folder / 'grades.csv').exists()

    def test_each_folder_is_one_student(self, f_scope_std):
        out = self._run(f_scope_std)
        text = (out / 'anders_alice' / 'grades.csv').read_text()

        assert 'alice@u.edu' in text
        assert 'bob' not in text
        assert len(text.strip().split('\n')) == 2

    def test_nobody_elses_policy(self, f_scope_std):
        out = self._run(f_scope_std)
        text = (out / 'baker_bob' / 'policy.yaml').read_text()

        assert 'bob@u.edu' in text
        assert 'carol' not in text
        assert 'a private word' not in text

    def test_one_student_on_request(self, f_scope_std):
        out = self._run(f_scope_std, ['--email', 'carol@u.edu'])

        assert [p.name for p in out.iterdir()] == ['chen_carol']

    def test_a_student_who_is_not_there(self, f_scope_std):
        with pytest.raises(SystemExit) as exc_info:
            self._run(f_scope_std, ['--email', 'nobody@u.edu'])

        assert exc_info.value.code == 2

    def test_somewhere_else_on_request(self, f_scope_std):
        f_out = f_scope_std.parent / 'handouts'
        self._run(f_scope_std, ['-o', str(f_out)])

        assert (f_out / 'anders_alice' / 'policy.yaml').exists()

    def test_the_pair_grades_that_student(self, f_scope_std):
        """ the whole reason the two files travel together """
        import warnings

        from finalgrade.policy import Policy

        out = self._run(f_scope_std)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            policy = Policy.from_file(f_scope_std.parent / 'policy.yaml')
            _, df_class = policy(str(f_scope_std))

            folder = out / 'anders_alice'
            mine = Policy.from_file(folder / 'policy.yaml')
            _, df_mine = mine(str(folder / 'grades.csv'))

        assert list(df_mine.index) == ['alice@u.edu']
        assert df_mine.at['alice@u.edu', 'mean'] == \
            df_class.at['alice@u.edu', 'mean']
