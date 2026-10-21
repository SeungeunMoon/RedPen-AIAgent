"""실제 162개 조문의 무손실 분할과 출처 연결을 검증한다."""

import json
from pathlib import Path

import pytest

from ingest.chunk import ChunkingConfig, SearchChunk, chunk_article, chunk_snapshot
from ingest.normalize import NormalizedDocument

SOURCE = Path(__file__).resolve().parents[2] / 'data/regulations/processed/20261021T043743991211Z-whole-article-v1'
FILES = sorted(SOURCE.glob('*.normalized.json'))


@pytest.mark.parametrize('path', FILES, ids=lambda path: path.stem)
def test_real_articles_are_lossless_bounded_and_traceable(path):
    document = NormalizedDocument.model_validate_json(path.read_bytes())
    ids = []
    for article in document.chunks:
        chunks = chunk_article(article, ChunkingConfig())
        assert ''.join(chunk.regulation.text for chunk in chunks) == article.text
        assert chunks == chunk_article(article, ChunkingConfig())
        previous_end = 0
        for chunk in chunks:
            restored = SearchChunk.model_validate_json(chunk.model_dump_json())
            assert restored == chunk
            assert 0 < len(chunk.regulation.text) <= 1200
            assert chunk.start_char == previous_end
            assert article.text[chunk.start_char:chunk.end_char] == chunk.regulation.text
            assert chunk.parent_chunk_id == article.chunk_id
            for field in ['source_path', 'source_url', 'law_id', 'version_id', 'effective_from', 'hierarchy']:
                assert getattr(chunk.regulation, field) == getattr(article, field)
            doc = chunk.to_document()
            assert article.law_name in doc.page_content
            assert doc.metadata['parent_chunk_id'] == article.chunk_id
            assert doc.id == chunk.regulation.chunk_id
            assert all(isinstance(value, (str, int, float, bool)) for value in doc.metadata.values())
            previous_end = chunk.end_char
            ids.append(chunk.regulation.chunk_id)
    assert len(ids) == len(set(ids))


def test_snapshot_output_and_overwrite_protection(tmp_path):
    output = tmp_path / 'chunks'
    summary = chunk_snapshot(SOURCE, output, ChunkingConfig())
    assert sum(record['articles'] for record in summary['documents']) == 162
    assert summary['supplementary_indexed'] is False
    assert sum(record['chunks'] for record in summary['documents']) > 162
    for record in summary['documents']:
        assert len((output / record['file']).read_text().splitlines()) == record['chunks']
    with pytest.raises(FileExistsError):
        chunk_snapshot(SOURCE, output, ChunkingConfig())


def test_tampered_input_rejected_before_output(tmp_path):
    manifest = json.loads((SOURCE / 'manifest.json').read_text())
    manifest['documents'] = manifest['documents'][:1]
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / manifest['documents'][0]['file']).write_text('{}')
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='해시'):
        chunk_snapshot(tmp_path, output, ChunkingConfig())
    assert not output.exists()


def test_synthetic_long_text_without_boundaries_and_config_ids():
    article = NormalizedDocument.model_validate_json(FILES[0].read_bytes()).chunks[0]
    article = article.model_copy(update={'text': '가나다' * 1000})
    chunks = chunk_article(article, ChunkingConfig(chunk_size=100))
    assert ''.join(chunk.regulation.text for chunk in chunks) == article.text
    assert all(len(chunk.regulation.text) <= 100 for chunk in chunks)
    assert chunks[0].regulation.chunk_id != chunk_article(article, ChunkingConfig(chunk_size=200))[0].regulation.chunk_id
