import pytest
import logging
import socket
import time
from unittest.mock import Mock, patch

@pytest.fixture
def mock_log_client(mocker) -> Mock:
    log_client_mock = mocker.Mock(spec=LogClientLaas)
    log_client_mock.send_log.return_value = None
    return log_client_mock


@pytest.fixture
def test_config() -> dict[str, str]:
    return {
        "auid": "ap12345",
        "code_name": "testcode",
        "version": 1,
        "data_set": "testlog",
        "event_type": "event",
        "kafka_topic": "test_topic",
        "laas_retention": "1day",
    }


def test_emit_should_send_logs_to_log_client_with_hostname(mocker, test_config, mock_log_client):
    """Test that emit adds hostname to log record and sends to log client."""
    expected_record = logging.LogRecord(
        name="bla", level=logging.INFO, pathname="", lineno=10, msg="This is a log message", args=None, exc_info=None
    )

    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    handler = KafkaLoggingHandlerLaas(test_config)

    # Verify the original record doesn't have hostname
    assert not hasattr(expected_record, 'hostname')

    handler.emit(expected_record)
    time.sleep(0.1)
    handler.close()

    # Verify send_log was called with hostname in the log data
    mock_log_client.send_log.assert_called_once()
    call_args = mock_log_client.send_log.call_args
    
    # Check that hostname is correctly added to the log record
    assert "hostname" in call_args[1]["log"]
    assert call_args[1]["log"]["hostname"] == socket.gethostname()
    
    # Verify the original record now has hostname attribute
    assert hasattr(expected_record, 'hostname')
    assert expected_record.hostname == socket.gethostname()


def test_hostname_initialization_on_handler_creation(mocker, test_config, mock_log_client):
    """Test that hostname is captured during handler initialization."""
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    
    with patch('socket.gethostname', return_value='test-hostname-123'):
        handler = KafkaLoggingHandlerLaas(test_config)
        assert handler.hostname == 'test-hostname-123'


def test_hostname_consistency_across_multiple_logs(mocker, test_config, mock_log_client):
    """Test that the same hostname is used for multiple log records."""
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    
    with patch('socket.gethostname', return_value='consistent-hostname') as mock_gethostname:
        handler = KafkaLoggingHandlerLaas(test_config)
        
        # Create multiple log records
        record1 = logging.LogRecord(
            name="test1", level=logging.INFO, pathname="", lineno=1, msg="Message 1", args=None, exc_info=None
        )
        record2 = logging.LogRecord(
            name="test2", level=logging.ERROR, pathname="", lineno=2, msg="Message 2", args=None, exc_info=None
        )
        
        handler.emit(record1)
        handler.emit(record2)
        time.sleep(0.1)
        handler.close()
        
        # Verify socket.gethostname was only called once during initialization
        mock_gethostname.assert_called_once()
        
        # Verify both records have the same hostname
        assert mock_log_client.send_log.call_count == 2
        calls = mock_log_client.send_log.call_args_list
        
        hostname1 = calls[0][1]["log"]["hostname"]
        hostname2 = calls[1][1]["log"]["hostname"]
        
        assert hostname1 == hostname2 == 'consistent-hostname'
        assert record1.hostname == record2.hostname == 'consistent-hostname'


def test_send_log_exception_handling_preserves_hostname_assignment(mocker, test_config, mock_log_client):
    """Test that hostname is still assigned even if log_client.send_log raises an exception."""
    # Make send_log raise an exception
    mock_log_client.send_log.side_effect = Exception("Kafka connection error")
    
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    # Mock the parent handleError method to avoid actual error handling
    mocker.patch.object(KafkaLoggingHandlerLaas, "handleError")
    
    handler = KafkaLoggingHandlerLaas(test_config)
    
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname="", lineno=1, msg="Test message", args=None, exc_info=None
    )
    
    # This should not raise an exception due to the try/except in send_log
    handler.send_log(record)
    
    # Verify hostname was still assigned to the record
    assert hasattr(record, 'hostname')
    assert record.hostname == socket.gethostname()
    
    # Verify the exception was caught and send_log was attempted
    mock_log_client.send_log.assert_called_once()


def test_send_log_with_none_log_client(mocker, test_config):
    """Test that send_log handles gracefully when log_client is None."""
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=None)
    
    handler = KafkaLoggingHandlerLaas(test_config)
    
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=1, msg="Test message", args=None, exc_info=None
    )
    
    # This should not raise an exception
    handler.send_log(record)
    
    # Hostname should still be assigned
    assert hasattr(record, 'hostname')
    assert record.hostname == socket.gethostname()


def test_close_should_cleanup_log_client(mocker, test_config, mock_log_client):
    """Test that close method properly cleans up the log client."""
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    handler = KafkaLoggingHandlerLaas(test_config)

    handler.close()

    mock_log_client.close.assert_called_once()
    assert handler.log_client is None


def test_exception_with_stacktrace_includes_hostname(mocker, test_config, mock_log_client):
    """Test that exception logs with stack traces also include hostname."""
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    handler = KafkaLoggingHandlerLaas(test_config)

    logger = logging.getLogger("test_exception_with_stacktrace")
    logger.addHandler(handler)

    # This should not print a TypeError: cannot pickle 'traceback' object
    try:
        raise ValueError("We have a problem with a stack trace")
    except ValueError as e:
        logger.error("exception with stack trace %s", e, exc_info=e)

    time.sleep(0.1)
    handler.close()
    
    # Verify that the log was sent with hostname
    mock_log_client.send_log.assert_called()
    call_args = mock_log_client.send_log.call_args
    assert "hostname" in call_args[1]["log"]
    assert call_args[1]["log"]["hostname"] == socket.gethostname()
