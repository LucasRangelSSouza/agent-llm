import os
import sys
import logging

from agent.infrastructure.observability.trace import get_trace_id


class LoggerManager:
    """
    LoggerManager provides a centralized logging utility with support for trace ids,
    configurable debug mode, and Sentry integration for error tracking.

    Attributes:
        settings: Application settings object, loaded from configuration.
        debug (bool): Flag to enable or disable debug logging and Sentry integration.
        logger (logging.Logger): The logger instance used for logging messages.
    """

    def __init__(
        self, debug: bool = False,
    ) -> None:
        self.debug = debug
        self.logger = logging.getLogger("logger")
        self.logger.setLevel(logging.DEBUG if self.debug else logging.INFO)

        if not self.logger.handlers:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.DEBUG if self.debug else logging.INFO)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

    def log_info(self, message: str) -> None:
        """
        Logs an info-level message with the optional trace id context.

        Args:
            message (str): The message to be logged.
        """
        trace = get_trace_id()
        log_message = f"id: {trace} - {message}" if trace else message
        self.logger.info(log_message)

    def log_debug(self, message: str) -> None:
        """
        Logs a debug-level message with the optional trace id context.

        Args:
            message (str): The debug message to be logged.
        """
        trace = get_trace_id()
        if self.debug:
            debug_message = f"id: {trace} - {message}" if trace else message
            self.logger.debug(debug_message)

    def log_error(self, message: str) -> None:
        """
        Logs an error-level message with the optional trace id context
        and sends the error message to Sentry if debug mode is disabled.

        Args:
            message (str): The error message to be logged and reported.
        """
        trace = get_trace_id()
        error_message =f"mapping id: {trace} - {message}" if trace else message
        self.logger.error(error_message)

    def log_warning(self, message: str) -> None:
        """
        Logs an warning-level message with the optional trace id context
        and sends the warning message to Sentry if debug mode is disabled.

        Args:
            message (str): The waning message to be logged and reported.
        """
        trace = get_trace_id()
        waning_message = f"mapping id: {trace} - {message}" if trace else message
        self.logger.warning(waning_message)


ENV = os.getenv("APP_ENVIRONMENT")
DEBUG_FLAG = ENV == "dev"

LOGGER = LoggerManager(debug=DEBUG_FLAG)
