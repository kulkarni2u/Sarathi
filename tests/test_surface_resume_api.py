from src.service import create_app


def setup_task(tmp_path):
    app = create_app(tmp_path / 'service.db')
    conn, storage = app._storage()
    workspace = storage.create_workspace(name='test', root_path=str(tmp_path))
    task = storage.create_task(workspace_id=workspace['id'], title='Resume task')
    return app, storage, task


def test_resume_requires_approved_graph(tmp_path):
    app, storage, task = setup_task(tmp_path)
    status, payload = app.handle('POST', f"/api/tasks/{task['id']}/resume", body={})
    assert status == 409
    assert payload['error']['code'] == 'approval_required'
    assert storage.get_task(task['id'])['status'] == task['status']


def test_resume_schedules_approved_ready_work(tmp_path):
    app, storage, task = setup_task(tmp_path)
    storage.create_approval_gate(workspace_id=task['workspace_id'], task_id=task['id'], name='Task graph', status='approved')
    node = storage.create_subtask(workspace_id=task['workspace_id'], task_id=task['id'], title='Do work', status='queued')
    status, payload = app.handle('POST', f"/api/tasks/{task['id']}/resume", body={})
    assert status == 200
    assert payload['data']['scheduled'][0]['id'] == node['id']
    assert storage.get_subtask(node['id'])['status'] == 'in_progress'


def test_resume_unknown_task(tmp_path):
    app = create_app(tmp_path / 'service.db')
    status, payload = app.handle('POST', '/api/tasks/missing/resume', body={})
    assert status == 404
    assert payload['error']['code'] == 'not_found'


def test_full_engine_approval_requeues_persisted_task(tmp_path):
    from src.engine import TaskContext, Complexity, Phase, PhaseResult, PersistenceManager
    app, storage, task = setup_task(tmp_path)
    task = storage.update_task(task['id'], status='waiting_human', metadata={'execution_mode': 'full_engine', 'engine_task_id': 'engine-1'})
    context = TaskContext(task_id='engine-1', description='run', complexity=Complexity.LOW)
    context.current_phase = Phase.BUILD
    context.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome='escalate', artifacts={'pause_execution': True}, evidence={'human_attention_required': True}))
    PersistenceManager(str(tmp_path / '.sarathi/tasks')).save_task(context)
    status, payload = app.handle('POST', f"/api/tasks/{task['id']}/approve", body={'name': 'Engine approval', 'status': 'approved', 'metadata': {'approved_by': 'tester'}})
    assert status == 201
    assert payload['data']['task']['status'] == 'queued'
    saved = PersistenceManager(str(tmp_path / '.sarathi/tasks')).load_task('engine-1')
    assert saved.phase_results[-1].artifacts['approval']['approved'] is True


def test_full_engine_resume_returns_conflict_for_missing_approval(tmp_path):
    app, storage, task = setup_task(tmp_path)
    storage.update_task(task['id'], status='waiting_human', metadata={'execution_mode': 'full_engine'})
    status, payload = app.handle('POST', f"/api/tasks/{task['id']}/resume", body={})
    assert status == 409
    assert payload['error']['code'] == 'approval_required'


def test_full_engine_approval_uses_registered_workspace_policy(tmp_path, monkeypatch):
    from src.engine import TaskContext, Complexity, Phase, PhaseResult, PersistenceManager
    app, storage, task = setup_task(tmp_path)
    policy = tmp_path / 'policy-pack'
    policy.mkdir()
    # A missing relative pack in the service cwd must not affect workspace approval.
    task = storage.update_task(task['id'], status='waiting_human', metadata={'execution_mode': 'full_engine', 'engine_task_id': 'engine-2', 'policy_pack': 'policy-pack'})
    context = TaskContext(task_id='engine-2', description='run', complexity=Complexity.LOW)
    context.current_phase = Phase.BUILD
    context.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome='escalate', artifacts={'pause_execution': True}, evidence={'human_attention_required': True}))
    PersistenceManager(str(tmp_path / '.sarathi/tasks')).save_task(context)
    from src.service import full_engine
    def reject_service_cwd_engine(*args, **kwargs):
        raise AssertionError('Approval constructed Engine inside service process')
    monkeypatch.setattr(full_engine, 'Engine', reject_service_cwd_engine)
    updated = full_engine.resume_full_engine_task(storage, task, approval={'approved': True})
    assert updated['status'] == 'queued'
