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
