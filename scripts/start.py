"""
Railway startup script.
Runs alembic upgrade head safely — if the DB has no alembic tracking
(existing tables but no alembic_version), stamps the baseline first so
only truly new migrations run.
"""
import os
import subprocess
import sys


def run(cmd: list[str]) -> int:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    return result.returncode


def migrate():
    # First attempt — works when DB is already tracked by alembic
    rc = run(['alembic', 'upgrade', 'head'])
    if rc == 0:
        print('[startup] alembic upgrade head: OK')
        return

    print('[startup] alembic upgrade head failed — stamping baseline and retrying')
    # DB has tables but no alembic_version, or version is unknown.
    # Stamp at the penultimate revision (all tables that already exist),
    # then upgrade to head which only runs the new migrations (with IF NOT EXISTS).
    stamp_rc = run(['alembic', 'stamp', 'd4b7e5162f49'])
    if stamp_rc != 0:
        print('[startup] alembic stamp failed — starting anyway', file=sys.stderr)
        return

    retry_rc = run(['alembic', 'upgrade', 'head'])
    if retry_rc == 0:
        print('[startup] alembic upgrade head (after stamp): OK')
    else:
        print('[startup] alembic upgrade head still failed — starting anyway', file=sys.stderr)


if __name__ == '__main__':
    migrate()

    port = int(os.environ.get('PORT', 8000))
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=port)
