"""Durable progress tracking for YouTube subtitle revisions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4
from storage import connect
from youtube_revision_service import get_revision, revise_youtube

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='youtube-revision')
_lock = Lock()
_running = set()

def _table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS youtube_revision_jobs (
        id TEXT PRIMARY KEY, video_id TEXT NOT NULL, status TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT 'queued', progress INTEGER NOT NULL DEFAULT 0,
        detail TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

def get_job(job_id):
    with connect() as conn:
        _table(conn)
        row = conn.execute('SELECT * FROM youtube_revision_jobs WHERE id=?', (job_id,)).fetchone()
        return dict(row) if row else None

def latest_job(video_id):
    with connect() as conn:
        _table(conn)
        row = conn.execute('SELECT * FROM youtube_revision_jobs WHERE video_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1', (video_id,)).fetchone()
        return dict(row) if row else None

def _update(job_id, status, stage, progress, detail='', error=''):
    with connect() as conn:
        _table(conn)
        conn.execute('UPDATE youtube_revision_jobs SET status=?, stage=?, progress=?, detail=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                     (status, stage, min(100, max(0, int(progress))), detail, error, job_id))

def _run(job_id, video_id):
    try:
        _update(job_id, 'running', 'preparing', 1, '正在准备修订')
        revise_youtube(video_id, progress_callback=lambda p, stage, detail:
                       _update(job_id, 'running', stage, p, detail))
        _update(job_id, 'completed', 'completed', 100, '已保存到数据库')
    except Exception as exc:
        _update(job_id, 'failed', 'failed', 0, '修订失败', str(exc))
    finally:
        with _lock:
            _running.discard(video_id)

def submit(video_id):
    cached = get_revision(video_id)
    if cached is not None:
        return {'status':'completed','stage':'cached','progress':100,'cached':True,'detail':'使用数据库缓存'}
    with _lock:
        previous = latest_job(video_id)
        if previous and previous['status'] in ('queued','running') and video_id in _running:
            return previous
        job_id = uuid4().hex
        with connect() as conn:
            _table(conn)
            conn.execute('INSERT INTO youtube_revision_jobs(id,video_id,status,stage) VALUES(?,?,?,?)',
                         (job_id, video_id, 'queued', 'queued'))
        _running.add(video_id)
        _executor.submit(_run, job_id, video_id)
        return get_job(job_id)
