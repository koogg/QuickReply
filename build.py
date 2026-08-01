"""一键打包脚本。

用法：
    python build.py            # 清理后构建 onedir 产物
    python build.py --clean    # 仅清理 build/ dist/ 缓存

产物在 dist/QuickReply/，整个目录可直接复制走作为完整应用。
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, 'QuickReply.spec')
DIST = os.path.join(ROOT, 'dist', 'QuickReply')
BUILD = os.path.join(ROOT, 'build')


def _die(msg):
    print(f'[build] {msg}', file=sys.stderr)
    sys.exit(1)


def _venv_python():
    venv_py = os.path.join(ROOT, '.venv', 'Scripts', 'python.exe')
    return venv_py if os.path.exists(venv_py) else sys.executable


def _run(cmd):
    print(f'[build] > {" ".join(cmd)}')
    subprocess.check_call(cmd)


def check_prerequisites():
    py = _venv_python()
    if not os.path.exists(SPEC):
        _die(f'找不到 {SPEC}，请确认在项目根目录执行。')
    if not os.path.exists(os.path.join(ROOT, 'icon.ico')):
        print('[build] 警告：未找到 icon.ico，exe 将使用默认图标。')
    # 确保已安装 pyinstaller
    try:
        subprocess.check_call([py, '-c', 'import PyInstaller'])
    except subprocess.CalledProcessError:
        print('[build] 未检测到 PyInstaller，正在安装…')
        _run([py, '-m', 'pip', 'install', 'pyinstaller'])
    return py


def clean():
    for d in (BUILD, DIST, os.path.join(ROOT, 'dist')):
        if os.path.exists(d):
            print(f'[build] 清理 {d}')
            shutil.rmtree(d, ignore_errors=True)


def build():
    py = check_prerequisites()
    clean()
    _run([py, '-m', 'PyInstaller', SPEC, '--noconfirm',
          '--distpath', os.path.join(ROOT, 'dist'),
          '--workpath', BUILD])
    if not os.path.exists(DIST):
        _die('构建完成但未找到产物目录，请检查日志。')
    # icon.ico 在 _internal/ 子目录下，复制一份到 exe 同级让用户可见
    dep_ico = os.path.join(DIST, '_internal', 'icon.ico')
    top_ico = os.path.join(DIST, 'icon.ico')
    if os.path.exists(dep_ico) and not os.path.exists(top_ico):
        shutil.copy2(dep_ico, top_ico)
    total = 0
    for dirpath, _, files in os.walk(DIST):
        for f in files:
            total += os.path.getsize(os.path.join(dirpath, f))
    print(f'[build] OK  产物: {DIST}')
    print(f'[build] 总大小: {total/1024/1024:.1f} MB')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clean', action='store_true', help='仅清理，不构建')
    args = ap.parse_args()
    if args.clean:
        clean()
        return
    build()


if __name__ == '__main__':
    main()