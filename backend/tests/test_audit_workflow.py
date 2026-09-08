from uuid import uuid4

import pytest

from app import auth, audit_workflow
from app.models import AuditEvidenceReview
from test_access_and_screenshots import client
from test_objective_reviews import context


@pytest.fixture
def audit(context, monkeypatch):
    monkeypatch.setattr(audit_workflow, 'get_settings', auth.get_settings)
    context['db'].add(AuditEvidenceReview(run_id=context['run'], notes='Earlier review notes', review_owner='Earlier owner'))
    context['db'].commit()
    return {**context, 'url': f'/api/assessments/{context["run"]}/audit-review'}


def body(**kwargs):
    return {'expected_revision': 0, 'review_owner': 'Audit owner', 'status': 'GAP', 'notes': 'Missing event coverage.',
            'retention_days': 90, 'review_frequency': 'Monthly', 'required_event_categories': ['Sign-ins'],
            'next_review_date': '2020-01-01', **kwargs}


def test_preserves_baseline_history_and_rejects_stale_save(audit):
    c = audit['client']; url = audit['url']
    result = c.put(url, json=body(resources=[{'kind': 'SCREENSHOT', 'id': audit['screenshot']}]))
    assert result.status_code == 200, result.text
    data = result.json()
    assert [row['revision'] for row in data['history']] == [1, 0]
    assert data['history'][1]['snapshot']['notes'] == 'Earlier review notes'
    assert data['history'][0]['recordedBy'] == 'reviewer'
    assert data['review']['resources'][0]['sha256'] == 'c' * 64
    assert c.put(url, json=body(notes='Stale overwrite')).status_code == 409
    assert c.put(url, json={'status': 'SUPPORTED'}).status_code == 422
    queue = c.get('/api/audit-reviews').json()['items']
    assert next(row for row in queue if row['runId'] == audit['run'])['overdue'] is True
    assert next(row for row in queue if row['runId'] == audit['other'])['revision'] == 0


def test_evidence_scope_and_supported_validation(audit):
    c = audit['client']; url = audit['url']
    assert c.put(url, json=body(status='SUPPORTED')).status_code == 422
    assert c.put(url, json=body(review_owner='  ')).status_code == 422
    assert c.put(url, json=body(resources=[{'kind': 'SCREENSHOT', 'id': 'missing'}])).status_code == 422
    assert c.put(f'/api/assessments/{audit["other"]}/audit-review', json=body(resources=[{'kind': 'DISCOVERY', 'id': audit['evidence']}])).status_code == 422
    result = c.put(url, json=body(status='SUPPORTED', resources=[{'kind': 'DISCOVERY', 'id': audit['evidence']}]))
    assert result.status_code == 200
    assert c.get(audit['base']).json()['review']['revision'] == 0
    assert c.get(audit['base']).json()['findings'][0]['status'] == 'MANUAL_REVIEW'
    assert c.get('/api/assessments/missing/audit-review').status_code == 404


def test_gap_linking_and_idempotency(audit):
    c = audit['client']; url = audit['url']
    identifier = c.get(url).json()['objectives'][0]['identifier']
    payload = {'expected_revision': 1, 'request_key': str(uuid4()), 'title': 'Repair audit coverage', 'identifier': identifier}
    assert c.post(url + '/poam', json=payload).status_code == 409
    assert c.put(url, json=body()).status_code == 200
    assert c.post(url + '/poam', json={**payload, 'identifier': audit['identifier']}).status_code == 422
    result = c.post(url + '/poam', json=payload)
    assert result.status_code == 201, result.text
    assert c.post(url + '/poam', json=payload).json()['id'] == result.json()['id']
    assert len(c.get(url).json()['poam']) == 1
    gap = c.get('/api/poam/' + result.json()['id']).json()
    assert gap['identifier'] == identifier and gap['runId'] == audit['run']
    assert gap['owner'] == 'Audit owner' and gap['description'] == 'Missing event coverage.'
    assert c.get(f'/api/assessments/{audit["run"]}/objectives/{identifier}').json()['review']['revision'] == 0


def test_review_without_legacy_record_and_unauthenticated_access(audit):
    c = audit['client']
    other = f'/api/assessments/{audit["other"]}/audit-review'
    assert c.put(other, json=body(status='NOT_APPLICABLE', next_review_date=None)).status_code == 200
    c.delete('/api/session')
    for path in ['/api/audit-reviews', audit['url']]:
        assert c.get(path).status_code == 401
    assert c.put(other, json=body()).status_code == 401
