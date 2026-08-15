#!/usr/bin/env python3
""" assembles the static site into _site/

The page is plain html, css and js -- there is no bundler and nothing to
compile.  The only build step is that the browser needs a wheel of this
package to install, and needs to be told its filename (which carries a
version).  So: build a wheel, copy the page next to it, write wheel.json.

    python web/build.py [--out _site]

Serve the result with any static file server; opening index.html straight
off disk will not work, because it loads a module over http.
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'

# copied verbatim into the site
ASSET_TUP = ('index.html', 'style.css', 'app.js', 'favicon.svg')


def build_wheel(folder):
    """ builds a wheel of this package into folder, returns its name """
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob('*.whl'):
        stale.unlink()

    subprocess.run(
        [sys.executable, '-m', 'build', '--wheel', '--outdir', str(folder),
         str(ROOT)],
        check=True)

    wheel_list = sorted(folder.glob('*.whl'))
    if len(wheel_list) != 1:
        raise SystemExit(f'expected one wheel in {folder}, got {wheel_list}')
    return wheel_list[0].name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=str(ROOT / '_site'),
                        help='directory to build into (default: _site)')
    args = parser.parse_args()

    out = pathlib.Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in ASSET_TUP:
        shutil.copy(WEB / name, out / name)

    # the example the 'try an example' button loads.  it is the suite's own
    # fixture, so the page always demonstrates something that is tested
    shutil.copy(ROOT / 'test' / 'scope.csv', out / 'example.csv')

    wheel = build_wheel(out / 'wheel')
    (out / 'wheel.json').write_text(
        json.dumps({'wheel': f'wheel/{wheel}'}, indent=2) + '\n')

    # github pages otherwise runs the whole site through jekyll, which
    # ignores files and folders whose names begin with an underscore
    (out / '.nojekyll').write_text('')

    print(f'built {out}')
    print(f'  wheel: {wheel}')
    print(f'  serve: python -m http.server -d {out}')


if __name__ == '__main__':
    main()
