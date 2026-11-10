"""Scope guard for benchmark Python children; native libraries are not OS-sandboxed."""
import os
import runpy
import socket
import shutil
import sys
from pathlib import Path

WORK = Path(os.environ['GAB_WORK']).resolve()
PROJECT = Path(os.environ['GAB_PROJECT']).resolve()
EXTRA = Path(os.environ['GAB_EXTRA']).resolve()
READ = [WORK, PROJECT / 'gis_agent', Path('E:/exe/qgis'), Path(sys.base_prefix), EXTRA,
        Path(os.environ['APPDATA']) / 'Python', Path(os.environ['APPDATA']) / 'QGIS', Path('C:/Windows')]
WRITE = [WORK / 'output', WORK / 'temp', WORK / 'scripts']


def allowed(value, roots):
    if isinstance(value, int):
        return True
    try:
        p = Path(os.fsdecode(value)).resolve()
    except (TypeError, ValueError):
        return True
    return any(p == root or p.is_relative_to(root) for root in roots)


def audit(event, args):
    if event == 'open' and not isinstance(args[0], int):
        flags = args[2] or 0
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        if not allowed(args[0], WRITE if writing else READ):
            raise PermissionError('Benchmark file outside allowed scope')
    elif event in {'os.listdir', 'os.scandir'} and args[0] is not None:
        # FileFinder must enumerate the parent once to discover the allowed package.
        # This permits directory names only; file reads outside READ remain denied.
        if Path(args[0]).resolve()!=PROJECT and not allowed(args[0], READ):
            raise PermissionError('Benchmark directory outside allowed scope')
    elif event in {'os.remove', 'os.rmdir', 'os.mkdir'}:
        if not allowed(args[0], WRITE):
            raise PermissionError('Benchmark mutation outside output scope')
    elif event == 'os.rename':
        if any(not allowed(v, WRITE) for v in args[:2]):
            raise PermissionError('Benchmark rename outside output scope')
    elif event == 'subprocess.Popen':
        executable = shutil.which(os.fsdecode(args[0])) or os.fsdecode(args[0])
        command = str(args[1]).replace('\\', '/').lower()
        qgis = Path('E:/exe/qgis').resolve()
        resolved = Path(executable).resolve()
        # Processing/GDAL may launch installed native utilities. Preserve that route.
        if not (resolved.is_relative_to(qgis) or
                (resolved.name.lower() in {'cmd.exe', 'cmd'} and 'e:/exe/qgis/' in command)):
            raise PermissionError('Benchmark subprocess must be an installed QGIS/GDAL utility')
    elif event == 'os.system':
        raise PermissionError('Use explicit installed QGIS/GDAL utilities')
    elif event in {'socket.connect', 'socket.getaddrinfo'}:
        raise PermissionError('Benchmark scripts use supplied local data; network disabled')


for key in list(os.environ):
    if any(x in key.upper() for x in ('API_KEY', 'ACCESS_KEY', 'SECRET', 'TOKEN')):
        os.environ.pop(key, None)
sys.dont_write_bytecode = True
sys.path.insert(0, str(EXTRA))
sys.addaudithook(audit)
args = sys.argv[1:]
while args and args[0].startswith('-'):
    args.pop(0)
if len(args) != 1 or Path(args[0]).name != 'script_entry.py':
    raise ValueError('Only the existing script_entry.py may be launched')
sys.argv = args
runpy.run_path(args[0], run_name='__main__')
