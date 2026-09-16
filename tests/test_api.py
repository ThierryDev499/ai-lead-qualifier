import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.ai import LocalAI

DATA=json.loads(Path('examples/leads.json').read_text())[0]


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setattr(LocalAI,'qualify',lambda *args:json.dumps({'fit':25,'urgency':20,'budget':20,'authority':15,'reasons':['Explicit automation need','Start this month','Approved budget','Decision maker'],'intent':'automation_project','next_action':'Arrange a discovery session with operations.','outreach':'We can discuss the reconciliation workflow and its integration requirements.'}))
    with TestClient(app) as client:yield client


def test_score_filters_history_and_crm(client):
    lead=client.post('/api/leads',json=DATA).json(); id=lead['id']
    assert client.post(f'/api/leads/{id}/crm-sync').status_code==409
    result=client.post(f'/api/leads/{id}/qualify').json()
    assert result['score']==80 and result['classification']=='quente'
    assert client.get('/api/leads?classification=quente').json()[0]['id']==id
    assert client.get('/api/leads?classification=frio').json()==[]
    first=client.post(f'/api/leads/{id}/crm-sync').json()
    second=client.post(f'/api/leads/{id}/crm-sync').json()
    assert first['simulated'] and first['external_id']==second['external_id']
    assert client.get('/api/dashboard').json()['crm_records']==1
    assert client.get('/api/leads/'+id).json()['history'][-1]['kind']=='crm_simulated'


def test_webhook_auth_and_idempotency(client,monkeypatch):
    headers={'Idempotency-Key':'fixture-1','X-Webhook-Token':'test-only-fixture'}
    monkeypatch.delenv('WEBHOOK_TOKEN',raising=False)
    assert client.post('/api/webhooks/leads',json=DATA,headers=headers).status_code==503
    monkeypatch.setenv('WEBHOOK_TOKEN','test-only-fixture')
    assert client.post('/api/webhooks/leads',json=DATA,headers={'Idempotency-Key':'x'}).status_code==401
    first=client.post('/api/webhooks/leads',json=DATA,headers=headers)
    second=client.post('/api/webhooks/leads',json=DATA,headers=headers)
    assert first.status_code==201 and second.status_code==200
    assert first.json()['id']==second.json()['id']
    assert client.post('/api/webhooks/leads',json=DATA|{'budget':10},headers=headers).status_code==409


def test_validation_and_samples(client):
    assert client.post('/api/leads',json=DATA|{'email':'invalid'}).status_code==422
    assert client.post('/api/leads',json=DATA|{'budget':-1}).status_code==422
    assert client.get('/api/leads/missing').status_code==404
    client.post('/api/samples');client.post('/api/samples')
    assert len(client.get('/api/leads').json())==3
    assert 'text/javascript' in client.get('/static/app.js').headers['content-type']


def test_invalid_model_output_and_outage_preserve_lead(client,monkeypatch):
    id=client.post('/api/leads',json=DATA).json()['id']
    monkeypatch.setattr(LocalAI,'qualify',lambda *args:'{"fit":999}')
    assert client.post(f'/api/leads/{id}/qualify').status_code==502
    assert client.get('/api/leads/'+id).json()['score'] is None
    def fail(*args):raise HTTPException(503,'offline')
    monkeypatch.setattr(LocalAI,'qualify',fail)
    assert client.post(f'/api/leads/{id}/qualify').status_code==503


def test_contact_fields_are_not_sent_to_model(client,monkeypatch):
    id=client.post('/api/leads',json=DATA).json()['id']
    captured=[]
    def inspect(self,data,schema):
        captured.append(json.loads(data));raise HTTPException(503,'stop after inspection')
    monkeypatch.setattr(LocalAI,'qualify',inspect)
    client.post(f'/api/leads/{id}/qualify')
    assert not {'name','email','phone'}.intersection(captured[0])
