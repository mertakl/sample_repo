##Here is the original code;


class KafkaLoggingConfigLaas(LogClientConfig):
    """
    A model for log client configuration.
    """

    laas_retention: str = Field(default=Retention.MONTH.value)
    level: str = Field(default="INFO")


class KafkaLoggingHandlerLaas(BaseKafkaLoggingHandler):
    """
    A logging handler that captures logs and send them to LaaS (group's LaaS solution) log client.
    """

    def __init__(self, log_client_config: dict):
        """
        Initialize the KafkaLoggingHandler instance.

        Args:
        log_client_config(dict): Dictionary with log client configuration.
        """
        self.hostname = socket.gethostname()

        log_client = self.get_log_client(log_client_config)
        handler_config = self.get_handler_config(log_client_config)
        super().__init__(handler_config, log_client)

    def get_log_client(self, log_client_config: dict):
        """
        Create and return a LogClientLaas instance using the provided configuration.

        Args:
            log_client_config (dict): Dictionary with log client configuration.

        Returns:
            LogClientLaas: An instance of LogClientLaas configured with the provided settings.
        """
        handler_config = self.get_handler_config(log_client_config)
        return LogClientLaas(handler_config)

    def get_handler_config(self, log_client_config: dict):
        """
        Validate and return a KafkaLoggingConfigLaas instance using the provided configuration.

        Args:
            log_client_config (dict): Dictionary with log client configuration.

        Returns:
            KafkaLoggingConfigLaas: An instance of KafkaLoggingConfigLaas validated with the provided settings.
        """
        return KafkaLoggingConfigLaas.model_validate(log_client_config)

    def send_log(self, record: logging.LogRecord):
        """
        Forwards the log safely to the kafka log client

        Args:
            record (logging.LogRecord): The log record to be sent.
        """
        try:
            if self.log_client:
                record.hostname = self.hostname
                self.log_client.send_log(laas_retention=self.laas_retention, log=record.__dict__)
        except Exception as ex:
            logger.error(ex)
            super().handleError(record)
			
#I  made a change for the hostname.I need you to update/enrich the test for it.


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


def test_emit_should_send_logs_to_log_client(mocker, test_config, mock_log_client):
    expected_record = logging.LogRecord(
        name="bla", level=logging.INFO, pathname="", lineno=10, msg="This is a log message", args=None, exc_info=None
    )

    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    handler = KafkaLoggingHandlerLaas(test_config)

    handler.emit(expected_record)
    time.sleep(0.1)
    handler.close()

    mock_log_client.send_log.assert_called_once()
    # Check if the hostname is correctly added to the log record
    assert mock_log_client.send_log.call_args[1]["log"]["hostname"] == socket.gethostname()


def test_close_should_cleanup_log_client(mocker, test_config, mock_log_client):
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    handler = KafkaLoggingHandlerLaas(test_config)

    handler.close()

    mock_log_client.close.assert_called_once()
    assert handler.log_client is None


def test_exception_with_stacktrace(mocker, test_config, mock_log_client):
    mocker.patch.object(KafkaLoggingHandlerLaas, "get_log_client", return_value=mock_log_client)
    handler = KafkaLoggingHandlerLaas(test_config)

    logger = logging.getLogger("test_exception_with_stacktrace")
    logger.addHandler(handler)

    # this should not print a TypeError: cannot pickle 'traceback' object  (hard to catch automatically, check your screen)
    try:
        raise ValueError("We have a problem with a stack trace")
    except ValueError as e:
        logger.error("exception with stack trace %s", e, exc_info=e)
