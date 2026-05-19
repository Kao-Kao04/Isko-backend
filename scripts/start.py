"""
Railway startup script.
Migrations run with a hard 60-second timeout so a hung DB connection
never prevents uvicorn from binding to the port.
"""
import os
import subprocess
import sys
import threading

# Ensure the project root (/app on Railway) is on sys.path so 'app.main' is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(cmd: list[str], timeout: int = 60) -> int:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.stdout:
            print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, end='', file=sys.stderr)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(f'[startup] {" ".join(cmd)} timed out after {timeout}s', file=sys.stderr)
        return 1


def migrate():
    print('[startup] running alembic upgrade head ...')
    rc = run(['alembic', 'upgrade', 'head'])
    if rc == 0:
        print('[startup] migrations OK')
        return

    print('[startup] upgrade failed — stamping d4b7e5162f49 and retrying')
    run(['alembic', 'stamp', 'd4b7e5162f49'])
    rc2 = run(['alembic', 'upgrade', 'head'])
    if rc2 == 0:
        print('[startup] migrations OK (after stamp)')
    else:
        print('[startup] migrations still failed — continuing anyway', file=sys.stderr)


if __name__ == '__main__':
    # Run migrations in a background thread so uvicorn binds to the port
    # immediately — Railway health checks won't time out waiting for migrations.
    t = threading.Thread(target=migrate, daemon=True)
    t.start()

    port = int(os.environ.get('PORT', 8000))
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=port)
