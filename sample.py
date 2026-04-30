import pandas as pd
from unittest.mock import patch, Mock

def test_process_all_documents(mocker, orchestrator, mock_document_fetcher, mock_doc_processor, sharepoint_doc):
    """Test _process_all_documents method."""
    # Setup mocks
    mock_document = mocker.Mock(spec=SharepointDocument)
    mock_document.source = "eureka"
    mock_document.name = "test_doc1"

    mock_documents = [sharepoint_doc, mock_document]
    mock_document_fetcher.get_documents.return_value = mock_documents

    mocker.patch(
        "bnppf_rag_engine.sharepoint.orchestrator.failed_download_uid_from_last_successful_run", return_value=set()
    )

    # ✅ Mock read_csv to return an empty (but valid) DataFrame
    mocker.patch(
        "bnppf_rag_engine.cos.utils.read_csv",
        return_value=pd.DataFrame()
    )

    orchestrator._process_all_documents(LIBRARIES_AND_SUBFOLDERS)

    # Verify document fetcher was called
    mock_document_fetcher.get_documents.assert_called_once_with(
        libraries_and_subfolders=LIBRARIES_AND_SUBFOLDERS,
    )

    # Verify document processor methods were called
    mock_doc_processor.manage_deleted_documents.assert_called_once_with(all_documents=mock_documents)
    mock_doc_processor.write_log_files.assert_called_once()

    # Verify each document was processed
    assert mock_doc_processor.process_document.call_count == len(mock_documents)
