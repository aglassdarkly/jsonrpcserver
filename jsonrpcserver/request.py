"""
Request module.

The Request class represents a JSON-RPC request object. Used internally by the
library, but class attributes can be modified to configure various options for
handling requests.
"""
import logging
import traceback
import inspect
from contextlib import contextmanager

from . import config
from .log import log_
from .response import RequestResponse, NotificationResponse, ExceptionResponse
from .exceptions import JsonRpcServerError, InvalidRequest, MethodNotFound
from .request_utils import *


_LOGGER = logging.getLogger(__name__)


class Request(object):
    """
    Represents a JSON-RPC Request object.

    Encapsulates a JSON-RPC request, providing details such as the method name,
    arguments, and whether it's a request or a notification, and provides a
    ``process`` method to execute the request.
    """
    @property
    def is_notification(self):
        """Returns True if the request is a JSON-RPC Notification (ie. No id
        attribute is included). False if it's a request.
        """
        return hasattr(self, 'request_id') and self.request_id is None

    @contextmanager
    def handle_exceptions(self):
        """Sets the response value"""
        try:
            yield
        except Exception as exc:
            # Log the exception if it wasn't explicitly raised by the method
            if not isinstance(exc, JsonRpcServerError):
                log_(_LOGGER, 'error', traceback.format_exc())
            # Notifications should not be responded to, even for errors (unless
            # overridden in configuration)
            if self.is_notification and not config.notification_errors:
                self.response = NotificationResponse()
            else:
                self.response = ExceptionResponse(
                    exc, getattr(self, 'request_id', None))

    def __init__(self, request):
        """
        :param request: JSON-RPC request, in dict form
        """
        # Handle validation/parse exceptions
        with self.handle_exceptions():
            # Validate against the JSON-RPC schema
            if config.schema_validation:
                validate_against_schema(request)
            # Get method name from the request. We can assume the key exists
            # because the request passed the schema.
            self.method_name = request['method']
            # Get arguments from the request, if any
            self.args, self.kwargs = get_arguments(request.get('params'))
            # Get request id, if any
            self.request_id = request.get('id')
            # Convert camelCase to underscore
            if config.convert_camel_case:
                self.method_name = convert_camel_case(self.method_name)
                if self.kwargs:
                    self.kwargs = convert_camel_case_keys(self.kwargs)
            self.response = None

    def call(self, methods):
        """Find the method from the passed list, and call it, returning a
        Response"""
        # Validation or parsing may have failed in __init__, in which case
        # there's no point calling. It would've already set the response.
        if not self.response:
            # call_context handles setting the result/exception of the call
            with self.handle_exceptions():
                # Get the method object from a list (raises MethodNotFound)
                callable_ = get_method(methods, self.method_name)
                args, kwargs = (self.args, self.kwargs)
                # Ensure the arguments match the method's signature
                validate_arguments_against_signature(callable_, args, kwargs)
                # Call the method
                result = callable_(*(self.args or []), **(self.kwargs or {}))
                # Set the response
                if self.is_notification:
                    self.response = NotificationResponse()
                else:
                    self.response = RequestResponse(self.request_id, result)
        # Ensure the response has been set
        assert self.response, 'Call must set response'
        assert isinstance(self.response, (ExceptionResponse, \
            NotificationResponse, RequestResponse)), 'Invalid response type'
        return self.response
