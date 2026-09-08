import pytest

from app import auth, poam_workflow
from test_access_and_screenshots import client
from test_objective_reviews import context, payload


@pytest.fixture
def gap(context, monkeypatch):
    monkeypatch.setattr(poam_workflow, 'get_settings', auth.get_settings)
    c = context
    response = c['client'].post('/api/poam', json={'title': 'Original gap', 'finding_id': c['finding'],
        'milestones': ['Validate scope'], 'target_date': '2020-01-01T12:00:00Z'})
    assert response.status_code == 201
    return {**c, 'url': '/api/poam/' + response.json()['id'], 'id': response.json()['id']}


def update(**kwargs):
    return {'expected_revision': 0, 'title': 'Updated gap', 'status': 'IN_PROGRESS', 'owner': 'Owner',
            'milestones': [{'title': 'Validate scope', 'complete': False}], **kwargs}


def test_history_baseline_and_stale_save(gap):
    c = gap['client']; url = gap['url']
    assert c.get(url).json()['overdue'] is True
    response = c.patch(url, json=update())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['revision'] == 1
    assert [r['revision'] for r in data['history']] == [1, 0]
    assert data['history'][1]['snapshot']['title'] == 'Original gap'
    assert data['history'][0]['recordedBy'] == 'reviewer'
    assert c.patch(url, json=update(title='Stale overwrite')).status_code == 409
    assert c.patch(url, json={'title': 'Legacy bypass', 'status': 'CLOSED'}).status_code == 422
    assert c.get(url).json()['title'] == 'Updated gap'
    assert any(item['id'] == gap['id'] for item in c.get('/api/poam/register').json()['items'])


@pytest.mark.parametrize('extra', [
    {'owner': ''}, {'closure_notes': ''}, {'screenshot_ids': []},
    {'milestones': [{'title': 'Unfinished', 'complete': False}]}, {'screenshot_ids': ['missing']},
])
def test_closure_validation(gap, extra):
    body = update(status='CLOSED', closure_notes='Verified remediation', screenshot_ids=[gap['screenshot']],
                  milestones=[{'title': 'Validate scope', 'complete': True}], **{})
    body.update(extra)
    assert gap['client'].patch(gap['url'], json=body).status_code == 422
    assert gap['client'].get(gap['url']).json()['history'] == []


def test_closure_requests_completed_rereview_without_changing_decision(gap):
    c = gap['client']
    assert c.put(gap['base'] + '/review', json=payload(decision='NOT_MET')).status_code == 200
    response = c.patch(gap['url'], json=update(status='CLOSED', closure_notes='Verified remediation',
        screenshot_ids=[gap['screenshot']], milestones=[{'title': 'Validate scope', 'complete': True}]))
    assert response.status_code == 200, response.text
    assert response.json()['rereviewPending'] is True
    assert response.json()['overdue'] is False
    assert response.json()['screenshots'][0]['sha256'] == 'c' * 64
    objective = c.get(gap['base']).json()
    assert objective['review']['decision'] == 'NOT_MET'
    assert objective['review']['revision'] == 1
    assert len(objective['rereviewRequests']) == 1
    assert objective['findings'][0]['status'] == 'MANUAL_REVIEW'
    summary = c.get(f'/api/assessments/{gap["run"]}/summary').json()
    assert summary['queues']['reReview'] == [gap['identifier']]
    assert c.get(f'/api/assessments/{gap["other"]}/summary').json()['queues']['reReview'] == []
    assert c.put(gap['base'] + '/review', json=payload(expected_revision=1, status='IN_REVIEW')).status_code == 200
    assert c.get(gap['url']).json()['rereviewPending'] is True
    assert c.put(gap['base'] + '/review', json=payload(expected_revision=2)).status_code == 200
    assert c.get(gap['url']).json()['rereviewPending'] is False
    assert c.get(gap['base']).json()['rereviewRequests'] == []


@pytest.mark.parametrize('status', ['COMPLETE', 'CLOSED'])
def test_cannot_create_already_closed(gap, status):
    assert gap['client'].post('/api/poam', json={'title': 'Bypass closure', 'status': status}).status_code == 422


@pytest.mark.parametrize('extra', [{'title': '   '}, {'milestones': ['   ']}])
def test_cannot_create_blank_record(gap, extra):
    assert gap['client'].post('/api/poam', json={'title': 'Valid title', **extra}).status_code == 422
