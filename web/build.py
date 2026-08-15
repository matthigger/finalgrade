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

# pyodide ships pandas, numpy and ruamel.yaml, but not these, and the banner
# export writes an xlsx.  fetched at build time rather than from pypi at run
# time, so the page owes nothing to the network once it has loaded
VENDOR_TUP = ('openpyxl', 'et-xmlfile')


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


def bust_cache(out):
    """ stamps app.js and style.css with a hash of themselves

    Without this a browser holds the previous build indefinitely -- the page
    is one html file that never changes name, so a fix can ship and simply
    not arrive, which is worse than not shipping it.
    """
    import hashlib

    text = (out / 'index.html').read_text()
    for name in ('app.js', 'style.css'):
        digest = hashlib.sha256((out / name).read_bytes()).hexdigest()[:10]
        text = text.replace(f'"{name}"', f'"{name}?v={digest}"')
    (out / 'index.html').write_text(text)


def fetch_vendor(folder):
    """ downloads the pure-python wheels pyodide doesn't ship """
    before_set = set(folder.glob('*.whl'))

    subprocess.run(
        [sys.executable, '-m', 'pip', 'download', '--no-deps', '--quiet',
         '--dest', str(folder), *VENDOR_TUP],
        check=True)

    name_list = sorted(p.name for p in set(folder.glob('*.whl')) - before_set)

    bad_list = [n for n in name_list if not n.endswith('-any.whl')]
    if bad_list:
        # a platform wheel would be built for this machine, not for wasm
        raise SystemExit(f'vendored wheel is not pure python: {bad_list}')

    return name_list


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

    bust_cache(out)

    # the example the 'try an example' button loads: a hundred students whose
    # awkward cases are each named after what they do (web/make_example.py)
    shutil.copy(WEB / 'example.csv', out / 'example.csv')

    wheel = build_wheel(out / 'wheel')
    vendor_list = fetch_vendor(out / 'wheel')
    (out / 'wheel.json').write_text(json.dumps({
        'wheel': f'wheel/{wheel}',
        'vendor': [f'wheel/{name}' for name in vendor_list],
    }, indent=2) + '\n')

    # github pages otherwise runs the whole site through jekyll, which
    # ignores files and folders whose names begin with an underscore
    (out / '.nojekyll').write_text('')

    print(f'built {out}')
    print(f'  wheel: {wheel}')
    print(f'  vendor: {", ".join(vendor_list)}')
    print(f'  serve: python -m http.server -d {out}')


if __name__ == '__main__':
    main()
