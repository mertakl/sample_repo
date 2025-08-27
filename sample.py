import logging
import socket
import pytest
from unittest.mock import Mock

# Assuming your classes (KafkaLoggingHandlerLaas, LogClientLaas, etc.)
# are in a module named `your_logging_module`.
from your_logging_module import KafkaLoggingHandlerLaas, LogClientLaas


## Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def mock_log_client(mocker) -> Mock:
    """A mock of the LogClientLaas to isolate the handler for testing."""
    return mocker.Mock(spec=LogClientLaas)


@pytest.fixture
def test_config() -> dict[str, str]:
    """Provides a standard dictionary for the log client configuration."""
    return {
        "auid": "ap12345",
        "code_name": "testcode",
        "version": "1.0",
        "data_set": "testlog",
        "event_type": "event",
        "kafka_topic": "test_topic",
        "laas_retention": "1day",
    }


@pytest.fixture
def kafka_handler(mocker, test_config, mock_log_client) -> KafkaLoggingHandlerLaas:
    """
    A fixture that provides a fully initialized KafkaLoggingHandlerLaas
    instance with a mocked log client, and handles cleanup.
    """
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    handler = KafkaLoggingHandlerLaas(log_client_config=test_config)
    yield handler
    # Teardown: ensure the handler is properly closed after the test runs
    handler.close()


## Test Functions
# --------------------------------------------------------------------------

def test_send_log_adds_hostname_correctly(kafka_handler, mock_log_client):
    """
    ✅ Verifies that the handler correctly retrieves the machine's hostname and
    adds it to the log record dictionary before sending it.
    """
    # Arrange
    log_message = "This is a test log message"
    log_record = logging.LogRecord(
        name="test_logger", level=logging.INFO, pathname="/fake/path",
        lineno=42, msg=log_message, args=None, exc_info=None
    )
    expected_hostname = socket.gethostname()

    # Act
    # The handler's `emit` method will call the `send_log` method internally
    kafka_handler.emit(log_record)

    # Assert
    mock_log_client.send_log.assert_called_once()

    # For clearer assertions, capture the keyword arguments passed to the mock
    _, kwargs = mock_log_client.send_log.call_args
    sent_log_dict = kwargs.get("log")

    assert sent_log_dict is not None, "The log dictionary was not sent."
    assert "hostname" in sent_log_dict, "The 'hostname' key is missing from the log record."
    assert sent_log_dict["hostname"] == expected_hostname
    assert sent_log_dict["msg"] == log_message


def test_handler_initialization_fails_if_hostname_cannot_be_resolved(mocker, test_config):
    """
    EDGE CASE: Verifies that the handler's __init__ method raises an exception
    if `socket.gethostname()` fails, preventing an invalid handler state.
    """
    # Arrange
    error_message = "Could not resolve hostname"
    mocker.patch("socket.gethostname", side_effect=socket.gaierror(error_message))

    # Act & Assert
    with pytest.raises(socket.gaierror, match=error_message):
        KafkaLoggingHandlerLaas(log_client_config=test_config)


def test_close_should_cleanup_log_client(kafka_handler, mock_log_client):
    """
    Verifies that calling close() on the handler also closes the underlying
    log client and sets it to None.
    """
    # Act
    kafka_handler.close()

    # Assert
    mock_log_client.close.assert_called_once()
    assert kafka_handler.log_client is None


def test_exception_with_stacktrace_is_handled(kafka_handler, mock_log_client):
    """
    Verifies that logs containing exception information are processed
    without raising a pickling error for the traceback object.
    """
    # Arrange
    logger = logging.getLogger("test_exception_logger")
    logger.propagate = False  # Prevent log from propagating to root logger
    logger.handlers.clear()
    logger.addHandler(kafka_handler)

    # Act
    try:
        raise ValueError("This is a test exception.")
    except ValueError as e:
        logger.error("An exception occurred: %s", e, exc_info=True)

    # Assert
    mock_log_client.send_log.assert_called_once()
    _, kwargs = mock_log_client.send_log.call_args
    sent_log_dict = kwargs.get("log")

    assert "exc_info" in sent_log_dict
    assert sent_log_dict["exc_info"] is not None
