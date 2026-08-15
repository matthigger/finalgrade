""" the gradebook the page's "try an example" button loads

An example is a promise about what the tool handles, so these check that the
awkward cases are all still in it.  If web/make_example.py is regenerated and
one of them goes missing, the page quietly stops demonstrating it.
"""
import pathlib
import warnings

import pytest

import finalgrade
from finalgrade import web

F_EXAMPLE = pathlib.Path(finalgrade.__file__).parents[1] / 'web' / 'example.csv'

# what a course would plausibly do with this gradebook, exercising the lot
YAML_EXAMPLE = """\
category:
  weight:
    hw: 40
    quiz: 25
    exam: 35
  drop_low:
    hw: 1
  late_penalty:
    hw:
      penalty_per_day: .1
      excuse_day: 2

assignments:
  substitute:
    exam2a:
      - exam2b
  exclude:
    - exam2b
"""


@pytest.fixture(scope='module')
def csv_text():
    return F_EXAMPLE.read_text()


@pytest.fixture(scope='module')
def graded(csv_text):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return web.grade(csv_text, YAML_EXAMPLE, 'example.csv')


def by_name(graded, part):
    return next(s for s in graded['student_list'] if part in s['email'])


class TestShape:
    def test_it_is_there(self):
        assert F_EXAMPLE.exists(), 'run web/make_example.py'

    def test_a_hundred_students(self, graded):
        assert graded['n_student'] == 100

    def test_the_assignments(self, csv_text):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            info = web.load_csv(csv_text)

        name_list = [a['name'] for a in info['ass_list']]
        assert sum(n.startswith('hw') for n in name_list) == 8
        assert sum(n.startswith('quiz') for n in name_list) == 4
        assert {'exam1', 'exam2a', 'exam2b'} <= set(name_list)

    def test_it_grades_cleanly(self, graded):
        assert graded['ok']

    def test_every_letter_is_earned_by_somebody(self, graded):
        """ a demo with no failing students demonstrates half a histogram """
        letter_set = {l['letter'] for l in graded['letter_list']}
        assert {'A', 'B', 'C', 'D', 'E'} <= letter_set


class TestTheCast:
    def test_nobody_who_did_no_homework(self, graded):
        stud = by_name(graded, 'doesntdohw')

        assert stud['cat_dict']['hw'] == 0
        assert stud['cat_dict']['quiz'] > .5

    def test_two_students_submitted_nothing_at_all(self, graded):
        """ two, because one is easy to dismiss as a glitch in the export """
        zero_list = [s for s in graded['student_list'] if s['mean'] == 0]

        assert len(zero_list) >= 2
        assert any('noshow' in s['email'] for s in zero_list)

    def test_somebody_started_late(self, graded, csv_text):
        stud = by_name(graded, 'stevens')

        assert stud['ass_dict']['hw1'] == 0
        assert stud['ass_dict']['hw8'] > .5

    def test_somebody_dropped_out(self, graded):
        stud = by_name(graded, 'duncan')

        assert stud['ass_dict']['hw1'] > .5
        assert stud['ass_dict']['hw8'] == 0

    def test_the_makeup_exam_substitutes_in(self, graded):
        """ exam2a is blank for them; exam2b stands in for it """
        stud = by_name(graded, 'reyes')

        assert stud['ass_dict']['exam2a'] > .5

    def test_a_late_student_loses_credit_to_the_penalty(self, csv_text):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            late = web.grade(csv_text, YAML_EXAMPLE, 'example.csv')
            no_late = web.grade(
                csv_text, YAML_EXAMPLE.split('  late_penalty:')[0]
                + 'assignments:\n  substitute:\n    exam2a:\n      - exam2b\n'
                  '  exclude:\n    - exam2b\n', 'example.csv')

        idx = [s['email'] for s in late['student_list']].index(
            by_name(late, 'larry')['email'])

        assert late['student_list'][idx]['cat_dict']['hw'] < \
            no_late['student_list'][idx]['cat_dict']['hw']

    def test_a_perfect_student(self, graded):
        stud = by_name(graded, 'park')

        assert stud['mean'] == 1
        assert stud['letter'] == 'A'

    def test_a_real_zero_is_not_an_absence(self, graded):
        """ zheng sat exam1 and scored nothing, which is not the same as
        never sitting it -- both are 0, and only one is a story """
        stud = by_name(graded, 'zheng')

        assert stud['ass_dict']['exam1'] == 0
        assert stud['cat_dict']['hw'] > .5
