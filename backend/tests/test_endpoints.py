from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import auth, endpoints, main
from app.models import InventoryAsset
from test_access_and_screenshots import client
from test_objective_reviews import context


@pytest.fixture
def endpoint(context, monkeypatch):
    monkeypatch.setattr(endpoints, 'get_settings', auth.get_settings)
    asset = InventoryAsset(asset_type='HARDWARE', asset_identifier='PC-001', name='Windows PC')
    context['db'].add(asset); context['db'].commit()
    return {**context, 'asset': asset, 'url': '/api/endpoints/' + asset.id}


def review(**kwargs):
    return {'expected_revision': 0, 'platform': 'WINDOWS', 'scope': 'IN_SCOPE', 'enclave': 'Cloud enclave', 'tenantId': 'tenant-a',
            'owner': 'IT owner', 'notes': 'Reviewed endpoint evidence.', 'checks': {k: 'UNKNOWN' for k in endpoints.CHECKS}, **kwargs}


def test_review_history_unknown_and_stale_save(endpoint):
    c = endpoint['client']; url = endpoint['url']
    initial = c.get(url).json()
    assert initial['review']['scope'] == 'UNKNOWN'
    assert set(initial['review']['checks'].values()) == {'UNKNOWN'}
    data = c.put(url, json=review(screenshot_ids=[endpoint['screenshot']], checks={k: 'VERIFIED' for k in endpoints.CHECKS})).json()
    assert data['review']['revision'] == 1
    assert data['review']['screenshots'][0]['sha256'] == 'c' * 64
    assert c.put(url, json=review()).status_code == 409
    assert c.put(url, json=review(expected_revision=1, notes='Second review')).status_code == 200
    assert c.get(url).json()['history'][1]['snapshot']['notes'] == 'Reviewed endpoint evidence.'
    assert c.get(endpoint['base']).json()['review']['revision'] == 0


@pytest.mark.parametrize('extra', [{'enclave': ''}, {'tenantId': ''}, {'checks': {}}, {'checks': {k: 'VERIFIED' for k in endpoints.CHECKS}}, {'screenshot_ids': ['missing']}])
def test_validation(endpoint, extra):
    assert endpoint['client'].put(endpoint['url'], json=review(**extra)).status_code == 422


def test_observations_do_not_overwrite_review(endpoint):
    c = endpoint['client']; db = endpoint['db']; asset = endpoint['asset']
    assert c.put(endpoint['url'], json=review()).status_code == 200
    endpoints.capture_observation(db, asset, {'operatingSystem': 'Windows', 'isEncrypted': False, 'complianceState': 'noncompliant'}, 'tenant-a', datetime.utcnow())
    db.commit()
    data = c.get(endpoint['url']).json()
    assert data['observation']['data']['isEncrypted'] is False
    assert set(data['review']['checks'].values()) == {'UNKNOWN'}
    assert data['review']['owner'] == 'IT owner'
    assert c.put(endpoint['url'], json=review(expected_revision=1, tenantId='tenant-b')).status_code == 422


def test_gap_tenant_scope_idempotency_and_exceptions_disabled(endpoint):
    c = endpoint['client']; url = endpoint['url']
    assert c.put(url, json=review(checks={k: 'GAP' for k in endpoints.CHECKS})).status_code == 200
    gap = {'expected_revision': 1, 'request_key': str(uuid4()), 'run_id': endpoint['other'], 'identifier': endpoint['identifier'], 'title': 'Resolve endpoint gaps'}
    assert c.post(url + '/poam', json=gap).status_code == 422
    gap['run_id'] = endpoint['run']
    result = c.post(url + '/poam', json=gap)
    assert result.status_code == 201, result.text
    assert c.post(url + '/poam', json=gap).json()['id'] == result.json()['id']
    assert len(c.get(url).json()['poam']) == 1
    assert c.get('/api/poam/' + result.json()['id']).json()['identifier'] == endpoint['identifier']
    assert c.post('/api/exceptions', json={'title': 'Not allowed'}).status_code == 404
    assert c.get(endpoint['base'] + '/resources?kind=POLICY_EXCEPTION').status_code == 422
    c.delete('/api/session')
    assert c.get('/api/endpoints').status_code == 401


def test_sync_records_encryption_and_missing_values(endpoint, monkeypatch):
    class Graph:
        async def get_collection(self, path, permission):
            if path.startswith('/deviceManagement/managedDevices?'):
                assert 'isEncrypted' in path and 'complianceState' in path
                return [{'id': 'test-device', 'deviceName': 'Synced PC', 'operatingSystem': 'Windows', 'isEncrypted': True}]
            return []
    monkeypatch.setattr(main, 'GraphClient', Graph)
    monkeypatch.setattr(main, 'get_settings', lambda: SimpleNamespace(azure_tenant_id='tenant-a'))
    result = endpoint['client'].post('/api/sync/inventory')
    assert result.status_code == 200, result.text
    rows = endpoint['client'].get('/api/endpoints').json()['items']
    item = next(row for row in rows if row['name'] == 'Synced PC')
    assert item['observation']['data']['isEncrypted'] is True
    assert item['observation']['data']['complianceState'] is None
    assert item['review']['scope'] == 'UNKNOWN'
