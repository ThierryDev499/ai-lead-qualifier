"""Qualify only bundled fictional leads and export real model output."""
import json
from pathlib import Path
import httpx

with httpx.Client(base_url='http://127.0.0.1:8104', timeout=200, trust_env=False) as client:
    response = client.post('/api/samples')
    response.raise_for_status()
    results = []
    for lead in response.json():
        if lead['score'] is None:
            response = client.post('/api/leads/' + lead['id'] + '/qualify')
            response.raise_for_status()
            lead = response.json()
        else:
            lead = client.get('/api/leads/' + lead['id']).json()
        assert 0 <= lead['score'] <= 100
        assert len(lead['analysis']['reasons']) == 4
        results.append(lead)
        print(f"{lead['data']['name']}: {lead['score']} / {lead['classification']}", flush=True)
    assert results[0]['score'] > results[2]['score'], 'Explicit buying intent should outrank information-only interest.'
    Path('examples/qualification-response.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
