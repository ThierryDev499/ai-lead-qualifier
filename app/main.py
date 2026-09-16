import hashlib
import hmac
import json
import logging
import mimetypes
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .ai import LocalAI

load_dotenv()
mimetypes.add_type('text/javascript', '.js')
ROOT = Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('lead-qualifier')


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    folder = Path(os.getenv('DATA_DIR', 'data'))
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / 'leads.sqlite', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def event(conn, lead_id, kind, detail):
    conn.execute('INSERT INTO events(lead_id,kind,detail,created_at) VALUES(?,?,?,?)', (lead_id, kind, detail, now()))


@asynccontextmanager
async def lifespan(app):
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,data TEXT,score INTEGER,classification TEXT,analysis TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,lead_id TEXT REFERENCES leads(id),kind TEXT,detail TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS incoming(idempotency_key TEXT PRIMARY KEY,body_hash TEXT,lead_id TEXT REFERENCES leads(id));
        CREATE TABLE IF NOT EXISTS crm(lead_id TEXT PRIMARY KEY REFERENCES leads(id),external_id TEXT,payload TEXT,updated_at TEXT);
        ''')
    yield


app = FastAPI(title='AI Lead Qualifier', version='1.0.0', lifespan=lifespan)


@app.middleware('http')
async def access_log(request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    log.info('%s %s status=%d duration_ms=%d', request.method, request.url.path, response.status_code, (time.monotonic() - start) * 1000)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


class Lead(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    company: str = Field(min_length=2, max_length=150)
    email: str = Field(max_length=200, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    phone: str = Field(min_length=8, max_length=30)
    role: str = Field(min_length=2, max_length=100)
    company_size: int = Field(ge=1, le=1_000_000)
    segment: str = Field(min_length=2, max_length=100)
    budget: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)
    interest: str = Field(min_length=3, max_length=250)
    message: str = Field(min_length=10, max_length=5000)
    source: str = Field(min_length=2, max_length=100)


class Analysis(BaseModel):
    fit: int = Field(ge=0, le=30)
    urgency: int = Field(ge=0, le=25)
    budget: int = Field(ge=0, le=25)
    authority: int = Field(ge=0, le=20)
    reasons: list[str] = Field(min_length=4, max_length=4)
    intent: str = Field(min_length=2, max_length=250)
    next_action: str = Field(min_length=10, max_length=1000)
    outreach: str = Field(min_length=10, max_length=3000)


def serialize(row):
    result = dict(row)
    result['data'] = json.loads(result['data'])
    result['analysis'] = json.loads(result['analysis']) if result['analysis'] else None
    return result


def get_lead(lead_id):
    with db() as conn:
        row = conn.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Lead not found.')
    return serialize(row)


def create_lead(body, key=None):
    data = json.dumps(body.model_dump(), sort_keys=True)
    digest = hashlib.sha256(data.encode()).hexdigest()
    lead_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if key:
            previous = conn.execute('SELECT * FROM incoming WHERE idempotency_key=?', (key,)).fetchone()
            if previous:
                if previous['body_hash'] != digest:
                    raise HTTPException(409, 'Idempotency key reused with different lead data.')
                return serialize(conn.execute('SELECT * FROM leads WHERE id=?', (previous['lead_id'],)).fetchone()), False
        conn.execute('INSERT INTO leads(id,data,created_at,updated_at) VALUES(?,?,?,?)', (lead_id, data, now(), now()))
        if key:
            conn.execute('INSERT INTO incoming VALUES(?,?,?)', (key, digest, lead_id))
        event(conn, lead_id, 'created', 'Lead registered.')
    return get_lead(lead_id), True


@app.get('/api/health')
def health():
    return {'status': 'ok', 'provider': 'ollama', 'model': LocalAI().model}


@app.post('/api/leads', status_code=201)
def create(body: Lead):
    return create_lead(body)[0]


@app.post('/api/webhooks/leads', status_code=201)
def webhook(body: Lead, response: Response,
            idempotency_key: Annotated[str, Header(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')],
            x_webhook_token: Annotated[str | None, Header()] = None):
    expected = os.getenv('WEBHOOK_TOKEN')
    if not expected:
        raise HTTPException(503, 'Webhook token not configured.')
    if not x_webhook_token or not hmac.compare_digest(x_webhook_token.encode(), expected.encode()):
        raise HTTPException(401, 'Invalid webhook token.')
    result, created = create_lead(body, idempotency_key)
    response.status_code = 201 if created else 200
    return result


@app.post('/api/samples', status_code=201)
def samples():
    rows = json.loads((ROOT / 'examples/leads.json').read_text(encoding='utf-8'))
    return [create_lead(Lead(**row), f'sample-{i}')[0] for i, row in enumerate(rows)]


@app.get('/api/leads')
def leads(classification: Literal['frio', 'morno', 'quente', 'pending'] | None = None, source: str | None = None):
    with db() as conn:
        rows = [serialize(r) for r in conn.execute('SELECT * FROM leads ORDER BY score DESC,updated_at DESC')]
    return [r for r in rows if (not classification or (r['classification'] or 'pending') == classification) and (not source or r['data']['source'] == source)]


@app.get('/api/leads/{lead_id}')
def detail(lead_id: str):
    result = get_lead(lead_id)
    with db() as conn:
        result['history'] = [dict(r) for r in conn.execute('SELECT kind,detail,created_at FROM events WHERE lead_id=? ORDER BY id', (lead_id,))]
        crm = conn.execute('SELECT external_id,updated_at FROM crm WHERE lead_id=?', (lead_id,)).fetchone()
        result['crm'] = dict(crm) | {'simulated': True} if crm else None
    return result


@app.post('/api/leads/{lead_id}/qualify')
def qualify(lead_id: str):
    lead = get_lead(lead_id)
    business = {k: v for k, v in lead['data'].items() if k not in ('name', 'email', 'phone')}
    ai = LocalAI()
    raw = ai.qualify(json.dumps(business), Analysis.model_json_schema())
    try:
        result = Analysis.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(502, 'Invalid model output; lead qualification was not changed.') from exc
    score = result.fit + result.urgency + result.budget + result.authority
    classification = 'quente' if score >= 70 else 'morno' if score >= 40 else 'frio'
    data = result.model_dump() | {'model': ai.model, 'rubric_version': 1}
    with db() as conn:
        conn.execute('UPDATE leads SET score=?,classification=?,analysis=?,updated_at=? WHERE id=?', (score, classification, json.dumps(data), now(), lead_id))
        event(conn, lead_id, 'qualified', json.dumps({'score': score, 'classification': classification, **data}))
    return detail(lead_id)


@app.post('/api/leads/{lead_id}/crm-sync')
def crm_sync(lead_id: str):
    lead = get_lead(lead_id)
    if lead['score'] is None:
        raise HTTPException(409, 'Qualify the lead before syncing to the demo CRM.')
    with db() as conn:
        previous = conn.execute('SELECT external_id FROM crm WHERE lead_id=?', (lead_id,)).fetchone()
        external_id = previous['external_id'] if previous else 'DEMO-' + str(uuid.uuid4())[:8]
        conn.execute('INSERT INTO crm VALUES(?,?,?,?) ON CONFLICT(lead_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at', (lead_id, external_id, json.dumps(lead), now()))
        event(conn, lead_id, 'crm_simulated', 'Saved to local CRM simulator: ' + external_id)
    return {'simulated': True, 'external_id': external_id, 'destination': 'local SQLite CRM simulator'}


@app.get('/api/dashboard')
def dashboard():
    with db() as conn:
        return {'counts': [dict(r) for r in conn.execute("SELECT COALESCE(classification,'pending') AS classification,count(*) AS count FROM leads GROUP BY classification")], 'average_score': conn.execute('SELECT avg(score) FROM leads').fetchone()[0], 'crm_records': conn.execute('SELECT count(*) FROM crm').fetchone()[0]}


@app.get('/')
def index():
    return FileResponse(ROOT / 'web/index.html')


app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
