import os

from app.core.environment import load_runtime_environment


def test_dotenv_legacy_tracing_is_loaded_without_exposing_values(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(('LANGCHAIN_', 'LANGSMITH_')):
            monkeypatch.delenv(name)
    for name in ('LANGCHAIN_TRACING_V2','LANGCHAIN_API_KEY','LANGCHAIN_PROJECT',
                 'LANGSMITH_TRACING','LANGSMITH_API_KEY','LANGSMITH_PROJECT'):
        monkeypatch.setenv(name,'')
    path=tmp_path/'.env'
    path.write_text('LANGCHAIN_TRACING_V2=true\nLANGCHAIN_API_KEY=test-only\nLANGCHAIN_PROJECT=file-project\n')
    # dotenv 우선순위 확인을 위해 테스트용 빈 환경변수를 제거한다.
    for name in ('LANGCHAIN_TRACING_V2','LANGCHAIN_API_KEY','LANGCHAIN_PROJECT'):
        monkeypatch.delenv(name)
    load_runtime_environment(path)
    assert os.environ['LANGSMITH_TRACING'] == 'true'
    assert os.environ['LANGSMITH_API_KEY'] == 'test-only'
    assert os.environ['LANGSMITH_PROJECT'] == 'file-project'


def test_terminal_environment_wins_over_dotenv(tmp_path,monkeypatch):
    monkeypatch.setenv('LANGSMITH_PROJECT','terminal-project')
    monkeypatch.setenv('LLM_MODEL','terminal-model')
    path=tmp_path/'.env'
    path.write_text('LANGSMITH_PROJECT=file-project\nLLM_MODEL=file-model\n')
    load_runtime_environment(path)
    assert os.environ['LANGSMITH_PROJECT'] == 'terminal-project'
    assert os.environ['LLM_MODEL'] == 'terminal-model'
