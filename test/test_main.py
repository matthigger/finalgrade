import pathlib
import shutil

import pytest

import finalgrade
from finalgrade.__main__ import main, parser

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


def _copy_test_data(tmp_path):
    """Copy test scope.csv and default config to tmp_path."""
    f_scope = tmp_path / 'scope.csv'
    shutil.copy(test_folder / 'scope.csv', f_scope)
    f_config = tmp_path / 'config.yaml'
    shutil.copy(
        pathlib.Path(finalgrade.__file__).parent / 'config.yaml',
        f_config)
    return str(f_scope), str(f_config)


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
        """Run with default config on test CSV"""
        f_scope, f_config = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--config', f_config, '-q'])
        main(args)
        assert (tmp_path / 'grade_full.csv').exists()

    def test_custom_output(self, tmp_path):
        """-o should change output path"""
        f_scope, f_config = _copy_test_data(tmp_path)
        f_out = str(tmp_path / 'my_grades.csv')
        args = parser.parse_args([
            'grade', f_scope, '--config', f_config, '-o', f_out, '-q'])
        main(args)
        assert pathlib.Path(f_out).exists()

    def test_per_student(self, tmp_path):
        """--per_student should create a per_student/ folder"""
        f_scope, f_config = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--config', f_config, '--per_student', '-q'])
        main(args)
        per_stud_folder = tmp_path / 'per_student'
        assert per_stud_folder.exists()
        csvs = list(per_stud_folder.glob('*.csv'))
        assert len(csvs) == 5  # 5 students in test data

    def test_late_csv(self, tmp_path):
        """--late_csv should produce a late days CSV"""
        f_scope, f_config = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--config', f_config, '--late_csv', 'late.csv',
            '-q'])
        main(args)
        assert (tmp_path / 'late.csv').exists()

    def test_plot_default_name(self, tmp_path):
        """--plot without a filename should use hist.html"""
        f_scope, f_config = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--config', f_config, '--plot', '-q'])
        main(args)
        assert (tmp_path / 'hist.html').exists()

    def test_plot_custom_name(self, tmp_path):
        """--plot with a filename should use that name"""
        f_scope, f_config = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--config', f_config, '--plot', 'my_hist.html',
            '-q'])
        main(args)
        assert (tmp_path / 'my_hist.html').exists()

    def test_resolve_config_existing(self, tmp_path):
        """Without --config, should pick up existing config.yaml"""
        f_scope, f_config = _copy_test_data(tmp_path)
        args = parser.parse_args(['grade', f_scope, '-q'])
        main(args)
        assert (tmp_path / 'grade_full.csv').exists()

    def test_resolve_config_new(self, tmp_path):
        """Without --config and no existing config, should create one"""
        f_scope = tmp_path / 'scope.csv'
        shutil.copy(test_folder / 'scope.csv', f_scope)
        # no config.yaml copied — should be auto-created
        args = parser.parse_args(['grade', str(f_scope), '-q'])
        main(args)
        assert (tmp_path / 'config.yaml').exists()
        assert (tmp_path / 'grade_full.csv').exists()

    def test_new_config_flag(self, tmp_path):
        """--new-config should create a timestamped config"""
        f_scope, f_config = _copy_test_data(tmp_path)
        args = parser.parse_args([
            'grade', f_scope, '--new-config', '-q'])
        main(args)
        # should have the original config.yaml plus a new timestamped one
        configs = list(tmp_path.glob('config*.yaml'))
        assert len(configs) == 2
